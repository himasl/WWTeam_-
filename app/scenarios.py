import json
import re
import sys

from . import kb
from .config import ROOT

FOLDER = ROOT / "scenarios"
TYPES = {"question", "check", "say", "tips", "verdict"}
FITS = {"yes", "no", "maybe"}


class ScenarioError(Exception):
    pass


def items_of(step):
    out = []
    for item in step.get("items", []):
        if isinstance(item, str):
            item = {"text": item}
        out.append({"text": item.get("text", ""), "reply": item.get("reply", ""), "when": item.get("when", {}),
                    "source": item.get("source", ""), "section": item.get("section", "")})
    return out


def labeled(items):
    titles = {c["doc"]: c["title"] for c in kb.CHUNKS}
    for x in items:
        x["where"] = f"{titles[x['source']]}, раздел «{x['section']}»" if x["source"] else ""
    return items


def check_when(when, known, where, errors):
    if not isinstance(when, dict):
        errors.append(f"{where}: when должен быть объектом вида {{\"факт\": \"значение\"}}")
        return
    for fact, value in when.items():
        values = value if isinstance(value, list) else [value]
        if fact not in known:
            errors.append(f"{where}: условие на факт «{fact}», который ещё не спрошен выше")
            continue
        for v in values:
            if v not in known[fact]:
                errors.append(f"{where}: у факта «{fact}» нет значения «{v}», есть: {', '.join(sorted(known[fact]))}")


def validate(data, name):
    errors = []
    if not isinstance(data, dict):
        raise ScenarioError(f"{name}: файл должен содержать объект JSON")
    sid = data.get("id", "")
    if not re.fullmatch(r"[a-z0-9-]+", str(sid)):
        errors.append(f"{name}: id должен состоять из латиницы, цифр и дефисов")
    if not data.get("title"):
        errors.append(f"{name}: нет title")
    product = data.get("product", "")
    titles = {c["title"] for c in kb.CHUNKS}
    if product and product not in titles:
        errors.append(f"{name}: продукта «{product}» нет в базе знаний")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append(f"{name}: нет шагов (steps)")
        raise ScenarioError("\n".join(errors))
    known = {}
    seen = set()
    sections = {(c["doc"], c["section"]) for c in kb.CHUNKS}
    for i, step in enumerate(steps, 1):
        where = f"{name}, шаг {i} «{step.get('id', '?')}»"
        if step.get("id") in seen or not step.get("id"):
            errors.append(f"{where}: id шага пустой или повторяется")
        seen.add(step.get("id"))
        kind = step.get("type")
        if kind not in TYPES:
            errors.append(f"{where}: type должен быть одним из: {', '.join(sorted(TYPES))}")
            continue
        if not step.get("title"):
            errors.append(f"{where}: нет title")
        check_when(step.get("when", {}), known, where, errors)
        if kind == "question":
            options = step.get("options", [])
            if not step.get("fact"):
                errors.append(f"{where}: у вопроса нет fact, куда записать ответ")
            if len(options) < 2 or not all(o.get("label") and o.get("value") for o in options):
                errors.append(f"{where}: нужно минимум два варианта с label и value")
            known.setdefault(step.get("fact"), set()).update(o.get("value") for o in options)
        if kind in ("check", "say", "tips"):
            items = items_of(step)
            if not items or not all(x["text"] for x in items):
                errors.append(f"{where}: нужен непустой список items с текстом")
            for x in items:
                check_when(x["when"], known, where + f", пункт «{x['text'][:30]}»", errors)
                if x["source"] and (x["source"], x["section"]) not in sections:
                    errors.append(f"{where}: в базе нет раздела «{x['section']}» в файле kb/{x['source']}.md")
            if kind == "tips" and not all(x["reply"] for x in items):
                errors.append(f"{where}: у каждого совета нужен reply")
        if kind == "verdict":
            offers = data.get("offers", [])
            if not offers:
                errors.append(f"{where}: для шага verdict нужен список offers")
            for o in offers:
                ow = f"{name}, предложение «{o.get('product', '?')}»"
                if not o.get("product"):
                    errors.append(f"{ow}: нет product")
                for r in o.get("rules", []):
                    check_when(r.get("when", {}), known, ow, errors)
                    if r.get("fit") not in FITS or not r.get("reason"):
                        errors.append(f"{ow}: у правила нужны fit (yes, no, maybe) и reason")
                other = o.get("otherwise", {})
                if other.get("fit") not in FITS or not other.get("reason"):
                    errors.append(f"{ow}: нужен otherwise с fit и reason")
    if errors:
        raise ScenarioError("\n".join(errors))
    return {
        "id": sid,
        "title": data["title"],
        "about": data.get("about", ""),
        "product": product,
        "draft": bool(data.get("draft", True)),
        "steps": [dict(s, items=labeled(items_of(s)), when=s.get("when", {})) for s in steps],
        "offers": data.get("offers", []),
    }


def load():
    found = {}
    errors = []
    for path in sorted(FOLDER.glob("*.json")):
        try:
            item = validate(json.loads(path.read_text(encoding="utf-8")), path.name)
        except json.JSONDecodeError as e:
            errors.append(f"{path.name}: ошибка JSON в строке {e.lineno}: {e.msg}")
            continue
        except ScenarioError as e:
            errors.append(str(e))
            continue
        if item["id"] in found:
            errors.append(f"{path.name}: id «{item['id']}» уже занят другим сценарием")
        found[item["id"]] = item
    if errors:
        raise ScenarioError("\n".join(errors))
    return found


def fits(when, facts, strict):
    for fact, value in when.items():
        values = value if isinstance(value, list) else [value]
        if fact not in facts:
            if strict:
                return False
            continue
        if facts[fact] not in values:
            return False
    return True


def verdict(scenario, facts):
    open_questions = {s["fact"]: s["title"] for s in scenario["steps"]
                      if s["type"] == "question" and s["fact"] not in facts and fits(s["when"], facts, False)}
    out = []
    for offer in scenario["offers"]:
        rules = offer.get("rules", [])
        chosen = next((r for r in rules if fits(r.get("when", {}), facts, True)), offer["otherwise"])
        missing = [open_questions[f] for r in rules for f in r.get("when", {}) if f in open_questions]
        if missing and chosen["fit"] != "no":
            chosen = {"fit": "maybe", "reason": f"Ответьте на вопрос «{missing[0]}»"}
        out.append({"product": offer["product"], "fit": chosen["fit"], "reason": chosen["reason"]})
    return out


def state(scenario, facts):
    steps = []
    for step in scenario["steps"]:
        if not fits(step["when"], facts, False):
            continue
        shown = dict(step)
        shown["items"] = [x for x in step["items"] if fits(x["when"], facts, True)]
        steps.append(shown)
    return {"steps": steps, "verdict": verdict(scenario, facts)}


def missed(scenario, facts, checks):
    out = []
    for step in state(scenario, facts)["steps"]:
        if step["type"] not in ("check", "say"):
            continue
        ticks = checks.get(step["id"], [])
        for i, item in enumerate(step["items"]):
            if i >= len(ticks) or not ticks[i]:
                out.append({"step": step["title"], "item": item["text"], "type": step["type"]})
    return out


ALL = {}
PROBLEMS = ""
try:
    ALL = load()
except ScenarioError as e:
    PROBLEMS = str(e)


if __name__ == "__main__":
    if PROBLEMS:
        print("Найдены ошибки в сценариях:\n" + PROBLEMS)
        sys.exit(1)
    for s in ALL.values():
        print(f"ок  {s['id']}: {s['title']}, шагов {len(s['steps'])}, предложений {len(s['offers'])}")
    print(f"сценариев: {len(ALL)}")
