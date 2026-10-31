import json
import math
import re

import snowballstemmer

from .config import COVER_HIGH, COVER_LOW, ROOT

KB = ROOT / "kb"
stem = snowballstemmer.stemmer("russian").stemWord

STOP = set((KB / "stopwords.txt").read_text(encoding="utf-8").split())
SAME = json.loads((KB / "synonyms.json").read_text(encoding="utf-8"))


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
                "examples": [x.strip() for x in meta.get("examples", "").split("|") if x.strip()],
                "checklist": meta.get("checklist", ""),
                "product": meta.get("product", "yes") != "no",
                "section": name.strip(),
                "lines": lines,
                "tokens": stems(meta["title"]) * 2 + stems(name) * 2 + stems(" ".join(lines)),
            })
    return chunks


CHUNKS = load()
GLOSSARY = json.loads((KB / "glossary.json").read_text(encoding="utf-8"))
CHECKLISTS = json.loads((KB / "checklists.json").read_text(encoding="utf-8"))
CATALOG = json.loads((KB / "catalog.json").read_text(encoding="utf-8"))

PRODUCTS = []
for c in CHUNKS:
    if c["product"] and all(p["title"] != c["title"] for p in PRODUCTS):
        PRODUCTS.append({"title": c["title"], "topic": c["topic"], "checklist": c["checklist"], "examples": c["examples"]})
order = CATALOG["topics"]
PRODUCTS.sort(key=lambda p: order.index(p["topic"]) if p["topic"] in order else len(order))

N = len(CHUNKS)
AVG = sum(len(c["tokens"]) for c in CHUNKS) / N
DF = {}
for c in CHUNKS:
    for t in set(c["tokens"]):
        DF[t] = DF.get(t, 0) + 1
IDF = {t: math.log(1 + (N - n + 0.5) / (n + 0.5)) for t, n in DF.items()}
MAX_IDF = math.log(1 + (N + 0.5) / 0.5)
OUT = {stem(w) for w in (KB / "out_of_scope.txt").read_text(encoding="utf-8").split()}


def weight(t):
    if t in IDF:
        return IDF[t]
    return MAX_IDF if t in OUT else 0.5


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
    total = sum(weight(t) for t in q)
    ranked = []
    for score, c in scored[:6]:
        have = set(c["tokens"])
        ranked.append((sum(weight(t) for t in q if t in have) / total, score, c))
    ranked.sort(key=lambda x: (-round(x[0], 2), -x[1]))
    return [c for _, _, c in ranked[:n]], ranked[0][0], q


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
        search_key = key[:-2] if len(key) > 6 else key
        if search_key in low:
            found.append({"term": term, "meaning": meaning})
    return found[:4]


def level(cover):
    if cover >= COVER_HIGH:
        return "high"
    if cover >= COVER_LOW:
        return "low"
    return "none"
