import json

import httpx

from . import config

RULES = """Ты помощник выездного менеджера банка. Менеджер на встрече с клиентом и задаёт тебе вопрос.
Отвечай только по фрагментам базы знаний ниже. Ничего не добавляй от себя и не придумывай цифры.
Ответ: два-три коротких предложения с точными цифрами из фрагментов.
Если во фрагментах нет ответа на вопрос, верни "known": false.
Верни только JSON такого вида:
{"known": true, "answer": "текст ответа", "source": 1, "ask": ["что уточнить у клиента"], "offer": ["что предложить клиенту"]}
"source" это номер фрагмента, на котором основан ответ. В "ask" до трёх вопросов, в "offer" до двух предложений."""

SIMPLE = "\nМенеджер новичок: объясняй простыми словами, без банковского жаргона."


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
    try:
        r = httpx.post(config.OLLAMA_URL + "/api/chat", json=body, headers=headers, timeout=40)
        r.raise_for_status()
        data = json.loads(r.json()["message"]["content"])
        data["answer"] = str(data.get("answer", "")).strip()
        data["source"] = int(data.get("source", 1))
        data["ask"] = [str(x) for x in data.get("ask", [])][:3]
        data["offer"] = [str(x) for x in data.get("offer", [])][:2]
        return data
    except Exception:
        return None
