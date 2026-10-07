import json
import math
import re

import snowballstemmer

from .config import MIN_COVER, ROOT

KB = ROOT / "kb"
stem = snowballstemmer.stemmer("russian").stemWord

STOP = set("""а в во и или к ко на не о об от по с со у за из для до при это что как какой какая какие
какое каков сколько ли же бы есть если то так там где когда кто чем чего мне нам он она они его ее их
можно нужно надо будет быть ему клиент клиента клиенту клиентом втб банк банка банке мой моя вы я
подскажи расскажи скажи про такое такой спрашивает спрашивают хочет хотят интересует интересуется
говорит узнать дают дает бывает нужен нужна нужны могу может можем делать если какого какую каким какое какие чему
сейчас вообще именно тоже еще уже или либо ну вот""".split())
SAME = {"кэшбэк": "кешбэк", "кэшбек": "кешбэк", "кешбек": "кешбэк", "стоит": "стоимость",
        "цена": "стоимость", "платить": "стоимость", "sms": "смс", "кредитка": "кредитная",
        "кредитке": "кредитная", "кредитку": "кредитная", "кредитки": "кредитная",
        "дебетовка": "дебетовая", "жкх": "жку", "налик": "наличные", "нал": "наличные",
        "процент": "ставка", "закрыть": "закрытие", "закрою": "закрытие", "снять": "снятие",
        "снимать": "снятие", "перевести": "перевод", "открыть": "открытие", "годовых": "ставка"}


def stems(text):
    out = []
    for w in re.findall(r"[a-zа-я0-9]+", text.lower().replace("ё", "е")):
        w = SAME.get(w, w)
        if w not in STOP:
            out.append(stem(w))
    return out


def load():
    chunks = []
    for path in sorted(KB.glob("*.md")):
        head, body = path.read_text(encoding="utf-8").split("---\n", 2)[1:]
        meta = dict(line.split(": ", 1) if ": " in line else (line.rstrip(":"), "") for line in head.strip().splitlines())
        for part in ("\n" + body).split("\n## ")[1:]:
            name, text = part.split("\n", 1)
            lines = [l[2:].strip() for l in text.splitlines() if l.startswith("- ")]
            chunks.append({
                "doc": path.stem,
                "title": meta["title"],
                "topic": meta["topic"],
                "source": meta["source"],
                "url": meta.get("url", ""),
                "actual": meta.get("actual", ""),
                "ask": [x.strip() for x in meta.get("ask", "").split("|") if x.strip()],
                "offer": [x.strip() for x in meta.get("offer", "").split("|") if x.strip()],
                "section": name.strip(),
                "lines": lines,
                "tokens": stems(meta["title"]) * 2 + stems(name) * 2 + stems(" ".join(lines)),
            })
    return chunks


CHUNKS = load()
GLOSSARY = json.loads((KB / "glossary.json").read_text(encoding="utf-8"))
CHECKLISTS = json.loads((KB / "checklists.json").read_text(encoding="utf-8"))

N = len(CHUNKS)
AVG = sum(len(c["tokens"]) for c in CHUNKS) / N
DF = {}
for c in CHUNKS:
    for t in set(c["tokens"]):
        DF[t] = DF.get(t, 0) + 1
IDF = {t: math.log(1 + (N - n + 0.5) / (n + 0.5)) for t, n in DF.items()}
MAX_IDF = math.log(1 + (N + 0.5) / 0.5)


def search(question, product="", n=3):
    q = list(dict.fromkeys(stems(question)))
    if not q:
        return [], 0, q
    scored = []
    for c in CHUNKS:
        score = 0
        for t in q:
            f = c["tokens"].count(t)
            if f:
                score += IDF[t] * f * 2.5 / (f + 1.5 * (0.25 + 0.75 * len(c["tokens"]) / AVG))
        if score:
            scored.append((score * (2 if c["title"] == product else 1), c))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return [], 0, q
    top = set(scored[0][1]["tokens"])
    total = sum(IDF.get(t, MAX_IDF) for t in q)
    cover = sum(IDF.get(t, MAX_IDF) for t in q if t in top) / total
    return [c for _, c in scored[:n]], cover, q


def best_lines(chunk, q, n=3):
    marks = [sum(t in stems(line) for t in q) for line in chunk["lines"]]
    top = sorted(range(len(marks)), key=lambda i: -marks[i])[:n]
    picked = [i for i in sorted(top) if marks[i] > 0]
    if not picked:
        picked = list(range(min(2, len(marks))))
    return [chunk["lines"][i] for i in picked]


def terms(text):
    low = text.lower().replace("ё", "е")
    found = []
    for term, meaning in GLOSSARY.items():
        key = term.lower().replace("ё", "е")
        if key[:-2] in low if len(key) > 6 else key in low:
            found.append({"term": term, "meaning": meaning})
    return found[:4]


def known(cover):
    return cover >= MIN_COVER
