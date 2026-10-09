import logging
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StrictBool, StrictInt, StrictStr

from . import db, kb, llm
from .config import MAX_QUESTION, ROOT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("wpomoshnik")

app = FastAPI(title="WПомощник")
PRODUCTS = list(dict.fromkeys(c["title"] for c in kb.CHUNKS))


class Ask(BaseModel):
    q: StrictStr
    novice: StrictBool = False
    product: StrictStr = ""


class Mark(BaseModel):
    id: StrictInt


@app.exception_handler(RequestValidationError)
def bad_request(request: Request, exc: RequestValidationError):
    fields = sorted({str(e["loc"][-1]) for e in exc.errors() if e["loc"] and e["loc"][0] == "body"})
    if not fields:
        text = "Тело запроса должно быть JSON-объектом"
    else:
        text = "Неверные поля запроса: " + ", ".join(fields)
    return JSONResponse(status_code=400, content={"detail": text})


@app.exception_handler(db.Unavailable)
def no_db(request: Request, exc: db.Unavailable):
    log.error("журнал недоступен: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "Журнал вопросов временно недоступен"})


@app.exception_handler(Exception)
def crash(request: Request, exc: Exception):
    log.error("ошибка при обработке %s", request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервера"})


def source(chunk, q):
    return {
        "title": chunk["title"],
        "section": chunk["section"],
        "source": chunk["source"],
        "url": chunk["url"],
        "actual": chunk["actual"],
        "quote": kb.best_lines(chunk, q),
    }


@app.post("/api/ask")
def ask(body: Ask):
    start = time.time()
    question = " ".join(body.q.split())
    if not question:
        raise HTTPException(400, "Вопрос пустой")
    if len(question) > MAX_QUESTION:
        raise HTTPException(400, f"Вопрос длиннее {MAX_QUESTION} символов, сократите его")
    if body.product and body.product not in PRODUCTS:
        raise HTTPException(400, "Нет такого продукта")
    chunks, cover, q = kb.search(question, body.product)
    out = {"known": False, "answer": "", "sources": [], "ask": [], "offer": [], "terms": [], "engine": "поиск"}
    level = kb.level(cover) if chunks else "none"
    if level != "none":
        best = chunks[0]
        reply = llm.ask(question, chunks, body.novice)
        if reply:
            out["engine"] = "модель"
            out["known"] = bool(reply.get("known")) and bool(reply["answer"])
            if 1 <= reply["source"] <= len(chunks):
                best = chunks[reply["source"] - 1]
            out["answer"] = reply["answer"]
            out["ask"] = reply["ask"] or best["ask"]
            out["offer"] = reply["offer"] or best["offer"]
        elif level == "high":
            out["known"] = True
            out["answer"] = " ".join(kb.best_lines(best, q))
            out["ask"] = best["ask"]
            out["offer"] = best["offer"]
        if out["known"]:
            out["sources"] = [source(best, q)] + [source(c, q) for c in chunks if c is not best][:2]
            if body.novice:
                out["terms"] = kb.terms(question + " " + out["answer"])
        else:
            out.update(answer="", ask=[], offer=[])
    ms = round((time.time() - start) * 1000)
    out["ms"] = ms
    best = out["sources"][0] if out["known"] else None
    topic = next((c["topic"] for c in chunks if best and c["title"] == best["title"]), "")
    try:
        out["id"] = db.add(question, out["known"], topic, best["title"] if best else "", ms, out["engine"], body.novice)
    except db.Unavailable as e:
        log.error("вопрос не записан в журнал: %s", e)
        out["id"] = None
    return out


@app.post("/api/escalate")
def escalate(body: Mark):
    if not db.escalate(body.id):
        raise HTTPException(404, "Вопрос не найден")
    return {"ok": True}


@app.get("/api/stats")
def stats():
    return db.stats()


@app.get("/api/checklists")
def checklists():
    return kb.CHECKLISTS


@app.get("/api/products")
def products():
    return PRODUCTS


@app.get("/api/health")
def health():
    return {"db": db.ok(), "model": llm.status(), "sections": len(kb.CHUNKS)}


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/stats")
def stats_page():
    return FileResponse(ROOT / "web" / "stats.html")


app.mount("/", StaticFiles(directory=ROOT / "web"), name="web")
