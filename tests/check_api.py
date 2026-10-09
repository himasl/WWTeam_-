import os
import sys
import tempfile
from pathlib import Path

os.environ["LLM"] = "on"
os.environ["OLLAMA_URL"] = "http://model.test"
os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "log.db")
sys.path.insert(0, str(Path(__file__).parent.parent))

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
