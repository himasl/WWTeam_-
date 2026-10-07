import sqlite3
import time

from .config import ROOT

PATH = ROOT / "data" / "log.db"
PATH.parent.mkdir(exist_ok=True)


def connect():
    db = sqlite3.connect(PATH)
    db.row_factory = sqlite3.Row
    return db


with connect() as db:
    db.execute("""create table if not exists log (
        id integer primary key, ts real, question text, known integer, topic text,
        title text, ms integer, engine text, novice integer, escalated integer default 0)""")


def add(question, known, topic, title, ms, engine, novice):
    with connect() as db:
        cur = db.execute(
            "insert into log (ts, question, known, topic, title, ms, engine, novice) values (?,?,?,?,?,?,?,?)",
            (time.time(), question.strip(), int(known), topic, title, ms, engine, int(novice)))
        return cur.lastrowid


def escalate(row_id):
    with connect() as db:
        db.execute("update log set escalated = 1 where id = ?", (row_id,))


def stats():
    with connect() as db:
        one = db.execute("""select count(*) total, coalesce(sum(known), 0) known,
            coalesce(sum(escalated), 0) escalated, coalesce(avg(ms), 0) ms from log""").fetchone()
        topics = db.execute("""select topic, count(*) n from log where known = 1
            group by topic order by n desc""").fetchall()
        often = db.execute("""select min(question) question, title, count(*) n from log where known = 1
            group by lower(question) order by n desc, max(ts) desc limit 8""").fetchall()
        gaps = db.execute("""select min(question) question, count(*) n, max(escalated) escalated from log
            where known = 0 group by lower(question) order by n desc, max(ts) desc limit 12""").fetchall()
    return {
        "total": one["total"],
        "known": one["known"],
        "escalated": one["escalated"],
        "ms": round(one["ms"]),
        "topics": [dict(r) for r in topics],
        "often": [dict(r) for r in often],
        "gaps": [dict(r) for r in gaps],
    }
