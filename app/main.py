import json
import logging
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from typing import Literal, Optional

from pydantic import BaseModel, Field, StrictBool, StrictInt, StrictStr

from . import config, db, kb, llm, scenarios
from .config import MAX_QUESTION, ROOT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("wpomoshnik")

app = FastAPI(title="WПомощник")
TITLES = {p["title"] for p in kb.PRODUCTS}


class Ask(BaseModel):
    q: StrictStr
    novice: StrictBool = False
    product: StrictStr = ""
    person: Optional[StrictInt] = None


class Person(BaseModel):
    name: StrictStr
    role: Literal["сотрудник", "наставник"]


class Facts(BaseModel):
    facts: dict[str, StrictStr] = Field(default_factory=dict)


class Run(BaseModel):
    scenario: StrictStr
    person: Optional[StrictInt] = None
    facts: dict[str, StrictStr] = Field(default_factory=dict)
    checks: dict[str, list[StrictBool]] = Field(default_factory=dict)
    ms: StrictInt = 0


class Colleague(BaseModel):
    q: StrictStr
    person: Optional[StrictInt] = None
    scenario: StrictStr = ""
    step: StrictStr = ""
    log_id: Optional[StrictInt] = None


class Answer(BaseModel):
    answer: StrictStr
    mentor: Optional[StrictInt] = None


class Mark(BaseModel):
    id: StrictInt


class Feedback(BaseModel):
    id: StrictInt
    helpful: StrictBool


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


def question_text(value):
    question = " ".join(value.split())
    if not question:
        raise HTTPException(400, "Вопрос пустой")
    if len(question) > MAX_QUESTION:
        raise HTTPException(400, f"Вопрос длиннее {MAX_QUESTION} символов, сократите его")
    return question


def check(body):
    question = question_text(body.q)
    if body.product and body.product not in TITLES:
        raise HTTPException(400, "Нет такого продукта")
    known_person(body.person)
    return question


def known_person(person_id):
    if person_id is not None and not db.person(person_id):
        raise HTTPException(400, "Нет такого сотрудника")


def scenario(sid):
    if sid not in scenarios.ALL:
        raise HTTPException(404, "Сценарий не найден")
    return scenarios.ALL[sid]


def answer_from_sections(question, chunks, q, level, novice):
    out = {"known": False, "answer": "", "sources": [], "ask": [], "offer": [], "terms": [], "engine": "поиск"}
    if level == "none":
        return out

    best = chunks[0]
    reply = llm.ask(question, chunks, novice)
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
        out["sources"] = [source(best, q)] + [source(c, q) for c in chunks if c is not best and c["title"] == best["title"]][:2]
        if novice:
            out["terms"] = kb.terms(question + " " + out["answer"])
    else:
        out.update(answer="", ask=[], offer=[])
    return out


def run(question, product, novice, person=None):
    start = time.time()
    chunks, cover, q = kb.search(question, product)
    level = kb.level(cover) if chunks else "none"
    if level != "none":
        yield {"stage": "found", "model": config.LLM == "on",
               "sections": [{"title": c["title"], "section": c["section"]} for c in chunks]}
    out = answer_from_sections(question, chunks, q, level, novice)
    ms = round((time.time() - start) * 1000)
    out["ms"] = ms
    best = out["sources"][0] if out["known"] else None
    topic = next((c["topic"] for c in chunks if best and c["title"] == best["title"]), "")
    try:
        out["id"] = db.add(question, out["known"], topic, best["title"] if best else "", ms, out["engine"], novice, person)
    except db.Unavailable as e:
        log.error("вопрос не записан в журнал: %s", e)
        out["id"] = None
    yield {"stage": "done", **out}


@app.post("/api/ask")
def ask(body: Ask):
    question = check(body)
    result = next(event for event in run(question, body.product, body.novice, body.person)
                  if event["stage"] == "done")
    return {key: value for key, value in result.items() if key != "stage"}


@app.post("/api/ask/stream")
def ask_stream(body: Ask):
    question = check(body)

    def lines():
        try:
            for event in run(question, body.product, body.novice, body.person):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as e:
            log.error("ошибка при ответе на вопрос", exc_info=e)
            yield json.dumps({"stage": "error", "detail": "Внутренняя ошибка сервера"}, ensure_ascii=False) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@app.post("/api/escalate")
def escalate(body: Mark):
    if not db.escalate(body.id):
        raise HTTPException(404, "Вопрос не найден")
    return {"ok": True}


@app.post("/api/feedback")
def feedback(body: Feedback):
    if not db.feedback(body.id, body.helpful):
        raise HTTPException(404, "Вопрос не найден")
    return {"ok": True}


@app.get("/api/stats")
def stats():
    return db.stats(scenario_catalog=scenarios.ALL)


@app.get("/api/checklists")
def checklists():
    return kb.CHECKLISTS


@app.get("/api/products")
def products():
    return {"products": kb.PRODUCTS, "known": kb.CATALOG["known"], "examples": kb.CATALOG["examples"], "unknown": kb.CATALOG["unknown"]}


@app.get("/api/people")
def people():
    return db.people()


@app.post("/api/people")
def add_person(body: Person):
    name = " ".join(body.name.split())
    if not name or len(name) > 60:
        raise HTTPException(400, "Укажите имя до 60 символов")
    return db.person(db.add_person(name, body.role))


@app.get("/api/scenarios")
def scenario_list():
    items = [{k: s[k] for k in ("id", "title", "about", "product", "draft")} | {"steps": len(s["steps"])}
             for s in scenarios.ALL.values()]
    return {"scenarios": items, "problems": scenarios.PROBLEMS}


@app.get("/api/scenarios/{sid}")
def scenario_get(sid: str):
    return scenario(sid)


@app.post("/api/scenarios/{sid}/state")
def scenario_state(sid: str, body: Facts):
    return scenarios.state(scenario(sid), body.facts)


@app.post("/api/runs")
def add_run(body: Run):
    item = scenario(body.scenario)
    known_person(body.person)
    missed = scenarios.missed(item, body.facts, body.checks)
    verdict = scenarios.verdict(item, body.facts)
    run_id = db.add_run(body.person, body.scenario, body.facts, body.checks, missed, max(body.ms, 0))
    return {"id": run_id, "missed": missed, "verdict": verdict}


@app.get("/api/runs")
def run_list(person: Optional[int] = None):
    return db.runs(person)


@app.post("/api/asks")
def add_ask(body: Colleague):
    question = question_text(body.q)
    known_person(body.person)
    return db.get_ask(db.add_ask(body.person, question, body.scenario, body.step, body.log_id))


@app.get("/api/asks")
def ask_list(status: Optional[Literal["open", "answered"]] = None):
    return db.asks(status)


@app.get("/api/asks/{ask_id}")
def ask_get(ask_id: int):
    item = db.get_ask(ask_id)
    if not item:
        raise HTTPException(404, "Вопрос не найден")
    return item


@app.post("/api/asks/{ask_id}/answer")
def ask_answer(ask_id: int, body: Answer):
    text = body.answer.strip()
    if not text:
        raise HTTPException(400, "Ответ пустой")
    known_person(body.mentor)
    if not db.get_ask(ask_id):
        raise HTTPException(404, "Вопрос не найден")
    if not db.answer_ask(ask_id, text, body.mentor):
        raise HTTPException(409, "На вопрос уже ответили")
    return db.get_ask(ask_id)


@app.get("/api/health")
def health():
    return {"db": db.ok(), "model": llm.status(), "sections": len(kb.CHUNKS), "scenarios": len(scenarios.ALL)}


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/stats")
def stats_page():
    return FileResponse(ROOT / "web" / "stats.html")


@app.get("/colleagues")
def colleagues_page():
    return FileResponse(ROOT / "web" / "colleagues.html")


app.mount("/", StaticFiles(directory=ROOT / "web"), name="web")
