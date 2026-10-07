import time

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, kb, llm
from .config import ROOT

app = FastAPI(title="WПомощник")


class Ask(BaseModel):
    q: str
    novice: bool = False
    product: str = ""


class Mark(BaseModel):
    id: int


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
    chunks, cover, q = kb.search(body.q, body.product)
    out = {"known": False, "answer": "", "sources": [], "ask": [], "offer": [], "terms": [], "engine": "поиск"}
    if chunks and kb.known(cover):
        best = chunks[0]
        reply = llm.ask(body.q, chunks, body.novice)
        if reply:
            out["engine"] = "модель"
            out["known"] = bool(reply.get("known")) and bool(reply["answer"])
            if 1 <= reply["source"] <= len(chunks):
                best = chunks[reply["source"] - 1]
            out["answer"] = reply["answer"]
            out["ask"] = reply["ask"] or best["ask"]
            out["offer"] = reply["offer"] or best["offer"]
        else:
            out["known"] = True
            out["answer"] = " ".join(kb.best_lines(best, q))
            out["ask"] = best["ask"]
            out["offer"] = best["offer"]
        if out["known"]:
            out["sources"] = [source(best, q)] + [source(c, q) for c in chunks if c is not best][:2]
            if body.novice:
                out["terms"] = kb.terms(body.q + " " + out["answer"])
        else:
            out.update(answer="", ask=[], offer=[])
    ms = round((time.time() - start) * 1000)
    out["ms"] = ms
    best = out["sources"][0] if out["known"] else None
    topic = next((c["topic"] for c in chunks if best and c["title"] == best["title"]), "")
    out["id"] = db.add(body.q, out["known"], topic, best["title"] if best else "", ms, out["engine"], body.novice)
    return out


@app.post("/api/escalate")
def escalate(body: Mark):
    db.escalate(body.id)
    return {"ok": True}


@app.get("/api/stats")
def stats():
    return db.stats()


@app.get("/api/checklists")
def checklists():
    return kb.CHECKLISTS


@app.get("/api/products")
def products():
    return list(dict.fromkeys(c["title"] for c in kb.CHUNKS))


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/stats")
def stats_page():
    return FileResponse(ROOT / "web" / "stats.html")


app.mount("/", StaticFiles(directory=ROOT / "web"), name="web")
