import os
import sys
import tempfile
from pathlib import Path

os.environ["LLM"] = "off"
os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "log.db")
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from app import scenarios
from app.main import app

client = TestClient(app, raise_server_exceptions=False)
failed = 0


def check(name, ok, extra=""):
    global failed
    failed += not ok
    print(("   " if ok else "!! ") + name + (f"  ({extra})" if extra and not ok else ""))


def errors(data):
    try:
        scenarios.validate(data, "тест")
        return ""
    except scenarios.ScenarioError as e:
        return str(e)


def base():
    return {
        "id": "test", "title": "Тест", "product": "Кредитная «Карта возможностей»",
        "steps": [
            {"id": "age", "type": "question", "title": "Возраст", "fact": "age",
             "options": [{"label": "До 70", "value": "young"}, {"label": "Старше", "value": "old"}]},
            {"id": "fit", "type": "verdict", "title": "Итог"},
        ],
        "offers": [{"product": "Карта", "rules": [{"when": {"age": "old"}, "fit": "no", "reason": "возраст"}],
                    "otherwise": {"fit": "yes", "reason": "подходит"}}],
    }


print("Проверка сценариев")
check("сценарии из папки scenarios загружаются без ошибок", not scenarios.PROBLEMS and scenarios.ALL, scenarios.PROBLEMS)
check("правильный сценарий проходит проверку", errors(base()) == "")
bad = base()
bad["steps"][1]["when"] = {"income": "15k"}
check("условие на неспрошенный факт ловится", "ещё не спрошен" in errors(bad))
bad = base()
bad["offers"][0]["rules"][0]["when"] = {"age": "child"}
check("условие на несуществующее значение ловится", "нет значения" in errors(bad))
bad = base()
bad["steps"].append({"id": "say", "type": "say", "title": "Скажите",
                     "items": [{"text": "x", "source": "kreditnaya-karta", "section": "Нет такого"}]})
check("ссылка на несуществующий раздел базы ловится", "нет раздела" in errors(bad))
bad = base()
bad["steps"][1]["id"] = "age"
check("повтор id шага ловится", "повторяется" in errors(bad))
bad = base()
bad["product"] = "Ипотека"
check("неизвестный продукт ловится", "нет в базе" in errors(bad))
bad = base()
bad["offers"][0]["otherwise"] = {}
check("предложение без otherwise ловится", "otherwise" in errors(bad))

print("Правила «подходит / не подходит»")
card = scenarios.ALL["kreditnaya-karta"]


def fit(facts):
    return {v["product"]: v["fit"] for v in scenarios.verdict(card, facts)}


check("клиент 30 лет с доходом на покупки: карта подходит, кредит под вопросом",
      fit({"age": "19-70", "income": "15k", "goal": "spend"}) == {"Кредитная «Карта возможностей»": "yes", "Кредит наличными": "maybe"})
check("клиент 72 лет: карта не подходит", fit({"age": "71-75", "income": "15k", "goal": "big"})["Кредитная «Карта возможностей»"] == "no")
check("нет дохода: не подходит ничего", set(fit({"age": "19-70", "income": "none", "goal": "spend"}).values()) == {"no"})
check("крупная сумма: кредит подходит", fit({"age": "19-70", "income": "15k", "goal": "big"})["Кредит наличными"] == "yes")
check("доход 5–15 тысяч: кредит не подходит", fit({"age": "19-70", "income": "5k", "goal": "big"})["Кредит наличными"] == "no")

check("без ответов ничего не обещаем: везде «уточните»", set(fit({}).values()) == {"maybe"})
check("отказ по возрасту виден сразу, даже без остальных ответов", fit({"age": "over75"})["Кредитная «Карта возможностей»"] == "no")

state = scenarios.state(card, {"goal": "big"})
ids = [s["id"] for s in state["steps"]]
check("вопрос про наличные скрыт, если нужна крупная сумма", "cash" not in ids, ids)
check("до ответа на цель вопрос про наличные виден", "cash" in [s["id"] for s in scenarios.state(card, {})["steps"]])
say = next(s for s in state["steps"] if s["id"] == "say")
check("для крупной суммы проговаривается ставка кредита", any("19,9%" in x["text"] for x in say["items"]))
check("для крупной суммы не проговаривается снятие наличных", not any("наличных" in x["text"] for x in say["items"]))

print("API сценариев")
r = client.get("/api/scenarios")
check("список трёх сценариев", r.status_code == 200 and
    {x["id"] for x in r.json()["scenarios"]} == {"debit-card", "kreditnaya-karta", "pension-transfer"}, r.text)
check("неизвестный сценарий: 404", client.get("/api/scenarios/nope").status_code == 404)
r = client.post("/api/scenarios/kreditnaya-karta/state", json={"facts": {"goal": "refi"}})
check("состояние по ответам", r.status_code == 200 and r.json()["verdict"], r.text)
check("факты не строкой: 400", client.post("/api/scenarios/kreditnaya-karta/state", json={"facts": {"age": 30}}).status_code == 400)

print("Сотрудники")
r = client.post("/api/people", json={"name": "  Анна   Смирнова ", "role": "сотрудник"})
anna = r.json()
check("сотрудник создаётся, имя очищено от лишних пробелов", r.status_code == 200 and anna["name"] == "Анна Смирнова", r.text)
again = client.post("/api/people", json={"name": "анна смирнова", "role": "сотрудник"}).json()
check("повторный выбор того же имени не создаёт дубль", again["id"] == anna["id"])
mentor = client.post("/api/people", json={"name": "Олег", "role": "наставник"}).json()
check("неизвестная роль: 400", client.post("/api/people", json={"name": "Иван", "role": "директор"}).status_code == 400)
check("пустое имя: 400", client.post("/api/people", json={"name": "  ", "role": "сотрудник"}).status_code == 400)
check("список сотрудников", len(client.get("/api/people").json()) == 2)
check("вопрос от несуществующего сотрудника: 400", client.post("/api/ask", json={"q": "кешбэк", "person": 999}).status_code == 400)
r = client.post("/api/ask", json={"q": "Какой льготный период по кредитной карте?", "person": anna["id"]})
check("вопрос привязывается к сотруднику", r.status_code == 200, r.text)
log_id = r.json()["id"]

print("Прохождение встречи")
facts = {"age": "19-70", "income": "15k", "goal": "spend", "cash": "no"}
full = scenarios.state(card, facts)
checks = {s["id"]: [True] * len(s["items"]) for s in full["steps"] if s["type"] in ("check", "say")}
r = client.post("/api/runs", json={"scenario": "kreditnaya-karta", "person": anna["id"], "facts": facts, "checks": checks, "ms": 600000})
check("встреча со всеми отметками сохраняется без пропусков", r.status_code == 200 and r.json()["missed"] == [], r.text)
checks["final"][1] = False
r = client.post("/api/runs", json={"scenario": "kreditnaya-karta", "person": anna["id"], "facts": facts, "checks": checks})
missed = r.json()["missed"]
check("пропущенный пункт попадает в итог", len(missed) == 1 and "ПИН" in missed[0]["item"], missed)
runs = client.get(f"/api/runs?person={anna['id']}").json()
check("история встреч сотрудника", len(runs) == 2 and runs[0]["name"] == "Анна Смирнова", runs)
stats = client.get("/api/stats").json()
check("аналитика пропусков по пункту, сценарию и продукту",
    any("ПИН" in x["item"] for x in stats["missed_top"]) and
    any(x["scenario"] == "Кредитная карта" and x["product"] == card["product"] for x in stats["missed_by_scenario_product"]))
check("встреча по неизвестному сценарию: 404", client.post("/api/runs", json={"scenario": "nope"}).status_code == 404)

print("Спросить коллег")
r = client.post("/api/asks", json={"q": "Можно ли оформить карту без СНИЛС?", "person": anna["id"],
                                   "scenario": "kreditnaya-karta", "step": "documents", "log_id": log_id})
ask = r.json()
check("вопрос коллегам создаётся открытым", r.status_code == 200 and ask["status"] == "open", r.text)
check("аналитика открытых вопросов по сотруднику",
      any(x["person"] == anna["id"] and x["name"] == "Анна Смирнова" and x["n"] == 1
          for x in client.get("/api/stats").json()["unanswered_by_person"]))
check("пустой вопрос коллегам: 400", client.post("/api/asks", json={"q": " "}).status_code == 400)
check("в очереди один открытый вопрос", len(client.get("/api/asks?status=open").json()) == 1)
check("неизвестный статус: 400", client.get("/api/asks?status=всё").status_code == 400)
r = client.post(f"/api/asks/{ask['id']}/answer", json={"answer": "Можно, СНИЛС не обязателен.", "mentor": mentor["id"]})
check("наставник отвечает", r.status_code == 200 and r.json()["status"] == "answered" and r.json()["mentor_name"] == "Олег", r.text)
check("ответ виден сотруднику", client.get(f"/api/asks/{ask['id']}").json()["answer"] == "Можно, СНИЛС не обязателен.")
check("повторный ответ: 409", client.post(f"/api/asks/{ask['id']}/answer", json={"answer": "Ещё"}).status_code == 409)
check("ответ на несуществующий вопрос: 404", client.post("/api/asks/999/answer", json={"answer": "x"}).status_code == 404)
check("пустой ответ: 400", client.post(f"/api/asks/{ask['id']}/answer", json={"answer": " "}).status_code == 400)
check("вопрос из журнала отмечен как переданный", client.get("/api/stats").json()["escalated"] == 1)
check("страница наставника открывается", client.get("/colleagues").status_code == 200)

print()
print("Все проверки пройдены" if not failed else f"Не пройдено проверок: {failed}")
sys.exit(1 if failed else 0)
