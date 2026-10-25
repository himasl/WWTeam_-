import sqlite3
import time

from . import config


class Unavailable(Exception):
    pass


def connect():
    try:
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(config.DB_PATH, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("""create table if not exists log (
            id integer primary key, ts real, question text, known integer, topic text,
            title text, ms integer, engine text, novice integer, escalated integer default 0)""")
        if "helpful" not in [r[1] for r in db.execute("pragma table_info(log)")]:
            db.execute("alter table log add column helpful integer")
        return db
    except (OSError, sqlite3.Error) as e:
        raise Unavailable(str(e)) from e


def run(work):
    db = connect()
    try:
        with db:
            return work(db)
    except sqlite3.Error as e:
        raise Unavailable(str(e)) from e
    finally:
        db.close()


def add(question, known, topic, title, ms, engine, novice):
    return run(lambda db: db.execute(
        "insert into log (ts, question, known, topic, title, ms, engine, novice) values (?,?,?,?,?,?,?,?)",
        (time.time(), question, int(known), topic, title, ms, engine, int(novice))).lastrowid)


def escalate(row_id):
    return run(lambda db: db.execute("update log set escalated = 1 where id = ?", (row_id,)).rowcount) > 0


def feedback(row_id, helpful):
    return run(lambda db: db.execute("update log set helpful = ? where id = ?", (int(helpful), row_id)).rowcount) > 0


def ok():
    try:
        run(lambda db: db.execute("select 1").fetchone())
        return True
    except Unavailable:
        return False


def stats():
    def work(db):
        one = db.execute("""select count(*) total, coalesce(sum(known), 0) known,
            coalesce(sum(escalated), 0) escalated, coalesce(avg(ms), 0) ms,
            coalesce(sum(helpful = 1), 0) helped, count(helpful) rated from log""").fetchone()
        topics = db.execute("""select topic, count(*) n from log where known = 1
            group by topic order by n desc""").fetchall()
        often = db.execute("""select min(question) question, title, count(*) n from log where known = 1
            group by lower(question) order by n desc, max(ts) desc limit 8""").fetchall()
        unhelpful = db.execute("""select min(question) question, title, count(*) n from log where helpful = 0
            group by lower(question) order by n desc, max(ts) desc limit 8""").fetchall()
        gaps = db.execute("""select min(question) question, count(*) n, max(escalated) escalated from log
            where known = 0 group by lower(question) order by n desc, max(ts) desc limit 12""").fetchall()
        return {
            "total": one["total"],
            "known": one["known"],
            "escalated": one["escalated"],
            "ms": round(one["ms"]),
            "helped": one["helped"],
            "rated": one["rated"],
            "unhelpful": [dict(r) for r in unhelpful],
            "topics": [dict(r) for r in topics],
            "often": [dict(r) for r in often],
            "gaps": [dict(r) for r in gaps],
        }
    return run(work)
