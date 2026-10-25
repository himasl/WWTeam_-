import os
import sys
import tempfile
from pathlib import Path

os.environ["LLM"] = "on"
os.environ["OLLAMA_URL"] = "http://model.test"
os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "log.db")
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import sqlite3

import httpx
from fastapi.testclient import TestClient

from app import config, db, llm
from app.main import app

client = TestClient(app, raise_server_exceptions=False)
GOOD = "Какой льготный период по кредитной карте?"
failed = 0


def check(name, ok, extra=""):
    global failed
    failed += not ok
    print(("   " if ok else "!! ") + name + (f"  ({extra})" if extra and not ok else ""))


def model(content=None, error=None, status=200):
    def fake(*args, **kwargs):
        if error:
            raise error
        request = httpx.Request("POST", "http://model.test/api/chat")
        return httpx.Response(status, json={"message": {"content": content}}, request=request)
    llm.httpx.post = fake


def ask(body):
    r = client.post("/api/ask", json=body)
    return r.status_code, r.json()


print("Входные данные")
for name, body in [
    ("пустой вопрос", {"q": ""}),
    ("вопрос из пробелов", {"q": "   \n  "}),
    ("слишком длинный вопрос", {"q": "а" * (config.MAX_QUESTION + 1)}),
    ("нет поля q", {"novice": True}),
    ("q не строка", {"q": 123}),
    ("novice не булево", {"q": GOOD, "novice": "да"}),
    ("неизвестный продукт", {"q": GOOD, "product": "Ипотека"}),
]:
    code, data = ask(body)
    check(f"{name}: 400 и понятный текст", code == 400 and isinstance(data.get("detail"), str), f"{code} {data}")
r = client.post("/api/ask", content="не json", headers={"Content-Type": "application/json"})
check("тело не JSON: 400", r.status_code == 400, r.text)
r = client.post("/api/ask", json=["список"])
check("тело не объект: 400", r.status_code == 400, r.text)
code, data = ask({"q": "а" * config.MAX_QUESTION})
check("вопрос ровно на пределе длины принимается", code == 200, code)

print("Ответы модели")
cases = [
    ("правильный JSON", '{"known": true, "answer": "До 110 дней.", "source": 1, "ask": ["Для чего карта?"], "offer": []}', "модель", True),
    ("JSON в блоке ```json", 'Вот ответ:\n```json\n{"known": true, "answer": "До 110 дней.", "source": "1"}\n```', "модель", True),
    ("source строкой «фрагмент 2»", '{"known": "true", "answer": "До 110 дней.", "source": "фрагмент 2", "ask": "Для чего карта?"}', "модель", True),
    ("source за пределами списка", '{"known": true, "answer": "До 110 дней.", "source": 9}', "модель", True),
    ("known true, но ответ пустой", '{"known": true, "answer": ""}', "модель", False),
    ("модель отказалась", '{"known": false, "answer": ""}', "модель", False),
    ("обычный текст без JSON", "Льготный период до 110 дней.", "поиск", True),
    ("JSON-массив вместо объекта", '["До 110 дней"]', "поиск", True),
    ("битый JSON", '{"known": true, "answer": "До 110', "поиск", True),
]
for name, content, engine, known in cases:
    model(content)
    code, data = ask({"q": GOOD})
    check(f"{name}: 200, режим «{engine}», ответ {'есть' if known else 'нет'}",
          code == 200 and data["engine"] == engine and data["known"] == known, f"{code} {data.get('engine')} {data.get('known')} {data.get('detail')}")
calls = []
def picky(*args, **kwargs):
    calls.append("think" in kwargs["json"])
    request = httpx.Request("POST", "http://model.test/api/chat")
    if "think" in kwargs["json"]:
        return httpx.Response(400, json={"error": "model does not support thinking"}, request=request)
    return httpx.Response(200, json={"message": {"content": '{"known": true, "answer": "До 110 дней.", "source": 1}'}}, request=request)
llm.httpx.post = picky
code, data = ask({"q": GOOD})
check("модель не знает think: повтор без него, ответ от модели", code == 200 and data["engine"] == "модель" and calls == [True, False], f"{calls} {data.get('engine')}")
sent = {}
def spy(*args, **kwargs):
    sent.update(kwargs["json"])
    request = httpx.Request("POST", "http://model.test/api/chat")
    return httpx.Response(200, json={"message": {"content": '{"known": true, "answer": "До 110 дней.", "source": 1}'}}, request=request)
llm.httpx.post = spy
ask({"q": GOOD})
check("по умолчанию в запросе think: false", sent.get("think") is False, sent.get("think"))
model(error=httpx.ReadTimeout("timeout"))
code, data = ask({"q": GOOD})
check("модель не ответила вовремя: ответ из базы", code == 200 and data["engine"] == "поиск" and data["known"], data)
model(error=httpx.ConnectError("refused"))
code, data = ask({"q": GOOD})
check("модель недоступна: ответ из базы", code == 200 and data["known"], data)
model("{}", status=500)
code, data = ask({"q": GOOD})
check("модель вернула 500: ответ из базы", code == 200 and data["known"], data)
model(error=httpx.ConnectError("refused"))
code, data = ask({"q": "можно ли открыть счёт в юанях"})
check("серая зона без модели: отказ", code == 200 and not data["known"], data)

print("Журнал")
model(error=httpx.ConnectError("refused"))
code, data = ask({"q": "какая ставка по ипотеке"})
check("вопрос записан, есть id", code == 200 and isinstance(data["id"], int), data)
r = client.post("/api/escalate", json={"id": data["id"]})
check("эскалация существующего вопроса: 200", r.status_code == 200, r.text)
r = client.post("/api/escalate", json={"id": 999999})
check("эскалация несуществующего вопроса: 404", r.status_code == 404, r.text)
r = client.post("/api/escalate", json={"id": "abc"})
check("эскалация с id не числом: 400", r.status_code == 400, r.text)
r = client.get("/api/stats")
check("статистика: 200", r.status_code == 200 and r.json()["total"] >= 1, r.text)

print("Отзывы")
model(error=httpx.ConnectError("refused"))
code, data = ask({"q": GOOD})
r = client.post("/api/feedback", json={"id": data["id"], "helpful": True})
check("отметка «помог»: 200", r.status_code == 200, r.text)
code, data2 = ask({"q": "сколько стоит выпуск стикера"})
client.post("/api/feedback", json={"id": data2["id"], "helpful": False})
s = client.get("/api/stats").json()
check("статистика считает отметки", s["rated"] == 2 and s["helped"] == 1 and len(s["unhelpful"]) == 1, s)
r = client.post("/api/feedback", json={"id": 999999, "helpful": True})
check("отметка несуществующего вопроса: 404", r.status_code == 404, r.text)
r = client.post("/api/feedback", json={"id": data["id"], "helpful": "да"})
check("отметка не булевым значением: 400", r.status_code == 400, r.text)

print("Потоковый ответ")
def stream(body):
    r = client.post("/api/ask/stream", json=body)
    return r.status_code, [json.loads(x) for x in r.text.splitlines() if x.strip()]
model('{"known": true, "answer": "До 110 дней.", "source": 1}')
code, events = stream({"q": GOOD})
check("найденные разделы, затем ответ", code == 200 and [e["stage"] for e in events] == ["found", "done"] and events[0]["sections"] and events[1]["known"], events)
code, events = stream({"q": "какой курс доллара"})
check("вопрос вне базы: сразу готовый отказ", code == 200 and [e["stage"] for e in events] == ["done"] and not events[0]["known"], events)
r = client.post("/api/ask/stream", json={"q": ""})
check("пустой вопрос в потоке: 400 до начала потока", r.status_code == 400, r.text)
code, events = stream({"q": "сколько стоит обслуживание карты", "product": "Дебетовая «Карта для жизни»"})
check("вопрос с выбранным продуктом", code == 200 and events[-1]["known"], events[-1])
r = client.get("/api/products").json()
check("каталог: продукты с примерами и чек-листами", r["products"] and all(p["examples"] and p["checklist"] for p in r["products"]) and r["unknown"], r)
check("памятки нет среди продуктов", all("Памятка" not in p["title"] for p in r["products"]))

print("Старая база журнала")
old = Path(tempfile.mkdtemp()) / "old.db"
con = sqlite3.connect(old)
con.execute("""create table log (id integer primary key, ts real, question text, known integer, topic text,
    title text, ms integer, engine text, novice integer, escalated integer default 0)""")
con.execute("insert into log (ts, question, known) values (1, 'старый вопрос', 1)")
con.commit()
con.close()
keep = config.DB_PATH
config.DB_PATH = old
r = client.post("/api/feedback", json={"id": 1, "helpful": True})
check("журнал без колонки отметок обновляется сам", r.status_code == 200, r.text)
config.DB_PATH = keep
check("health: журнал доступен", client.get("/api/health").json()["db"] is True)

good_path = config.DB_PATH
blocker = Path(tempfile.mkdtemp()) / "file"
blocker.write_text("")
config.DB_PATH = blocker / "log.db"
code, data = ask({"q": GOOD})
check("журнал недоступен: ответ всё равно приходит, id пустой", code == 200 and data["known"] and data["id"] is None, f"{code} {data}")
r = client.get("/api/stats")
check("журнал недоступен: статистика 503", r.status_code == 503 and "detail" in r.json(), r.text)
r = client.post("/api/escalate", json={"id": 1})
check("журнал недоступен: эскалация 503", r.status_code == 503, r.text)
r = client.post("/api/feedback", json={"id": 1, "helpful": True})
check("журнал недоступен: отметка 503", r.status_code == 503, r.text)
check("health: журнал недоступен", client.get("/api/health").json()["db"] is False)
config.DB_PATH = good_path

print("Прочее")
original = db.stats
db.stats = lambda: 1 / 0
r = client.get("/api/stats")
check("неожиданная ошибка: 500 с текстом, сервер жив", r.status_code == 500 and r.json()["detail"], r.text)
db.stats = original
check("после ошибки сервер отвечает", client.get("/api/products").status_code == 200)

print(f"\nпровалено проверок: {failed}")
sys.exit(1 if failed else 0)
