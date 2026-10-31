import json
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
        db.execute("""create table if not exists people (
            id integer primary key, ts real, name text, role text)""")
        db.execute("""create table if not exists runs (
            id integer primary key, ts real, person integer, scenario text,
            facts text, checks text, missed text, ms integer)""")
        db.execute("""create table if not exists asks (
            id integer primary key, ts real, person integer, question text, scenario text, step text,
            log_id integer, status text default 'open', answer text, mentor integer, answered_ts real)""")
        columns = [r[1] for r in db.execute("pragma table_info(log)")]
        if "helpful" not in columns:
            db.execute("alter table log add column helpful integer")
        if "person" not in columns:
            db.execute("alter table log add column person integer")
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


def add(question, known, topic, title, ms, engine, novice, person=None):
    return run(lambda db: db.execute(
        "insert into log (ts, question, known, topic, title, ms, engine, novice, person) values (?,?,?,?,?,?,?,?,?)",
        (time.time(), question, int(known), topic, title, ms, engine, int(novice), person)).lastrowid)


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


def _missed_stats(rows, scenario_catalog):
    missed_top = {}
    missed_groups = {}
    for row in rows:
        scenario = scenario_catalog.get(row["scenario"], {})
        scenario_title = scenario.get("title", row["scenario"])
        product = scenario.get("product", scenario_title)
        for item in json.loads(row["missed"]):
            key = (item["step"], item["item"])
            missed_top[key] = missed_top.get(key, 0) + 1
            group = (scenario_title, product)
            missed_groups[group] = missed_groups.get(group, 0) + 1
    return {
        "missed_top": [{"step": step, "item": item, "n": n}
                       for (step, item), n in sorted(missed_top.items(), key=lambda x: -x[1])[:12]],
        "missed_by_scenario_product": [{"scenario": scene, "product": product, "n": n}
                                       for (scene, product), n in sorted(missed_groups.items(), key=lambda x: -x[1])],
    }


def stats(scenario_catalog=None):
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
        missed = _missed_stats(db.execute("select scenario, missed from runs"), scenario_catalog or {})
        unanswered = db.execute("""select a.person, coalesce(p.name, 'без имени') name, count(*) n
            from asks a left join people p on p.id = a.person where a.status = 'open'
            group by a.person, p.name order by n desc, name""").fetchall()
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
            **missed,
            "unanswered_by_person": [dict(r) for r in unanswered],
        }
    return run(work)


def people():
    return run(lambda db: [dict(r) for r in db.execute("select id, name, role from people order by name")])


def person(person_id):
    row = run(lambda db: db.execute("select id, name, role from people where id = ?", (person_id,)).fetchone())
    return dict(row) if row else None


def add_person(name, role):
    def work(db):
        for row in db.execute("select id, name from people where role = ?", (role,)):
            if row["name"].casefold() == name.casefold():
                return row["id"]
        return db.execute("insert into people (ts, name, role) values (?,?,?)", (time.time(), name, role)).lastrowid
    return run(work)


def add_run(person_id, scenario, facts, checks, missed, ms):
    return run(lambda db: db.execute(
        "insert into runs (ts, person, scenario, facts, checks, missed, ms) values (?,?,?,?,?,?,?)",
        (time.time(), person_id, scenario, json.dumps(facts, ensure_ascii=False),
         json.dumps(checks, ensure_ascii=False), json.dumps(missed, ensure_ascii=False), ms)).lastrowid)


def runs(person_id=None, limit=50):
    def work(db):
        rows = db.execute("""select r.*, p.name from runs r left join people p on p.id = r.person
            where ? is null or r.person = ? order by r.ts desc limit ?""", (person_id, person_id, limit)).fetchall()
        return [dict(r, facts=json.loads(r["facts"]), checks=json.loads(r["checks"]), missed=json.loads(r["missed"])) for r in rows]
    return run(work)


def add_ask(person_id, question, scenario, step, log_id):
    def work(db):
        if log_id:
            db.execute("update log set escalated = 1 where id = ?", (log_id,))
        return db.execute("insert into asks (ts, person, question, scenario, step, log_id) values (?,?,?,?,?,?)",
                          (time.time(), person_id, question, scenario, step, log_id)).lastrowid
    return run(work)


ASK = """select a.*, p.name, m.name mentor_name from asks a
    left join people p on p.id = a.person left join people m on m.id = a.mentor"""


def asks(status=None):
    return run(lambda db: [dict(r) for r in db.execute(
        ASK + " where ? is null or a.status = ? order by a.status = 'answered', a.ts desc limit 100", (status, status))])


def get_ask(ask_id):
    row = run(lambda db: db.execute(ASK + " where a.id = ?", (ask_id,)).fetchone())
    return dict(row) if row else None


def answer_ask(ask_id, answer, mentor):
    return run(lambda db: db.execute(
        "update asks set status = 'answered', answer = ?, mentor = ?, answered_ts = ? where id = ? and status = 'open'",
        (answer, mentor, time.time(), ask_id)).rowcount) > 0
