import json
import logging
import re

import httpx

from . import config

log = logging.getLogger("wpomoshnik.llm")

RULES = """Ты помощник выездного менеджера банка. Менеджер на встрече с клиентом и задаёт тебе вопрос.
Отвечай только по фрагментам базы знаний ниже. Ничего не добавляй от себя и не придумывай цифры.
Ответ: два-три коротких предложения с точными цифрами из фрагментов.
Если во фрагментах нет ответа на вопрос, верни "known": false.
Верни только JSON такого вида:
{"known": true, "answer": "текст ответа", "source": 1, "ask": ["что уточнить у клиента"], "offer": ["что предложить клиенту"]}
"source" это номер фрагмента, на котором основан ответ. В "ask" до трёх вопросов, в "offer" до двух предложений."""

SIMPLE = "\nМенеджер новичок: объясняй простыми словами, без банковского жаргона."


def to_list(value, n):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if str(x).strip()][:n]


def to_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ("true", "да", "1", "yes")
    return bool(value)


def to_source(value):
    found = re.search(r"\d+", str(value))
    return int(found.group()) if found else 1


def parse(text):
    found = re.search(r"\{.*\}", text, re.S)
    if not found:
        raise ValueError("в ответе модели нет JSON")
    data = json.loads(found.group())
    if not isinstance(data, dict):
        raise ValueError("ответ модели не объект JSON")
    answer = str(data.get("answer") or "").strip()
    return {
        "known": to_bool(data.get("known", bool(answer))) and bool(answer),
        "answer": answer,
        "source": to_source(data.get("source", 1)),
        "ask": to_list(data.get("ask"), 3),
        "offer": to_list(data.get("offer"), 2),
    }


def ask(question, chunks, novice):
    if config.LLM != "on":
        return None
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(f"Фрагмент {i}. {c['title']}. {c['section']}\n" + "\n".join(c["lines"]))
    headers = {}
    if config.OLLAMA_API_KEY:
        headers["Authorization"] = "Bearer " + config.OLLAMA_API_KEY
    body = {
        "model": config.OLLAMA_MODEL,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
        "messages": [
            {"role": "system", "content": RULES + (SIMPLE if novice else "")},
            {"role": "user", "content": "\n\n".join(parts) + "\n\nВопрос: " + question},
        ],
    }
    if config.OLLAMA_THINK in ("false", "true"):
        body["think"] = config.OLLAMA_THINK == "true"
    try:
        r = httpx.post(config.OLLAMA_URL + "/api/chat", json=body, headers=headers, timeout=config.OLLAMA_TIMEOUT)
        if r.status_code == 400 and "think" in r.text and "think" in body:
            body.pop("think")
            r = httpx.post(config.OLLAMA_URL + "/api/chat", json=body, headers=headers, timeout=config.OLLAMA_TIMEOUT)
        r.raise_for_status()
        return parse(r.json()["message"]["content"])
    except httpx.TimeoutException:
        log.warning("модель не ответила за %s с", config.OLLAMA_TIMEOUT)
    except httpx.HTTPStatusError as e:
        log.warning("модель вернула ошибку %s: %s", e.response.status_code, e.response.text[:200])
    except httpx.HTTPError as e:
        log.warning("модель недоступна: %s", e)
    except (KeyError, TypeError, ValueError) as e:
        log.warning("не удалось разобрать ответ модели: %s", e)
    return None


def status():
    if config.LLM != "on":
        return "выключена"
    headers = {"Authorization": "Bearer " + config.OLLAMA_API_KEY} if config.OLLAMA_API_KEY else {}
    try:
        httpx.get(config.OLLAMA_URL + "/api/tags", headers=headers, timeout=3).raise_for_status()
        return "доступна"
    except httpx.HTTPError:
        return "недоступна"
