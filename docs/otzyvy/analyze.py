import csv
import json

NAMES = {
    "P": "Оплата и её расчёт",
    "T": "Личный авто и топливо",
    "F": "Штрафы и контроль",
    "L": "Нагрузка и маршруты встреч",
    "M": "Руководство и поддержка",
    "K": "Обучение и знание продуктов",
    "C": "Трудные клиенты и сорванные встречи",
    "S": "Давление продаж и план",
    "A": "Сбои приложения и техники",
    "E": "Прочее: найм, погода, коллектив",
}
HELPS = {"K": "да", "M": "частично", "C": "частично", "S": "частично", "A": "нет", "P": "нет", "T": "нет", "F": "нет", "L": "нет", "E": "нет"}

labels = {}
for line in open("labels.txt", encoding="utf-8"):
    n, *codes = line.split()
    labels[n] = [c for c in codes if c != "-"]

rows = list(csv.DictReader(open("reviews_raw.csv", encoding="utf-8")))
for r in rows:
    r["template"] = "да" if r["source"] == "kyrieros.ru" and r["n"] != "128" else ""
    r["labels"] = labels.get(r["n"], [])
    r["problems"] = "; ".join(NAMES[c] for c in r["labels"])

with open("reviews_labeled.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["№", "источник", "банк", "роль", "дата", "город", "что нравится", "что не нравится", "текст", "похоже на шаблон", "проблемы"])
    for r in rows:
        w.writerow([r["n"], r["source"], r["bank"], r["role"], r["date"], r["city"], r["plus"], r["minus"], r["text"], r["template"], r["problems"]])

base = [r for r in rows if r["source"] != "kyrieros.ru"]
with_complaint = [r for r in base if r["labels"]]
total = len(with_complaint)
share = []
for code, name in NAMES.items():
    n = sum(code in r["labels"] for r in with_complaint)
    share.append({"code": code, "problem": name, "reviews": n, "share": round(100 * n / total, 1), "helps": HELPS[code]})
share.sort(key=lambda x: -x["reviews"])
mentor = [r["n"] for r in base if "наставник" in (r["plus"] + r["text"]).lower() or ("коллег" in (r["plus"] + r["minus"] + r["text"]).lower() and "помог" in (r["plus"] + r["minus"] + r["text"]).lower())]
summary = {
    "all": len(rows),
    "base": len(base),
    "template": len(rows) - len(base),
    "with_complaint": total,
    "by_source": {s: sum(r["source"] == s for r in base) for s in ("DreamJob", "Отзовик", "kyrieros.ru")},
    "shares": share,
    "mentor_mentions": mentor,
    "product_related": round(100 * sum(any(c in r["labels"] for c in "K") for r in with_complaint) / total, 1),
    "product_any": round(100 * sum(any(c in r["labels"] for c in "KMCS") for r in with_complaint) / total, 1),
}
json.dump(summary, open("itogi.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
with open("shares.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["проблема", "отзывов", "доля, %", "помогает WПомощник"])
    for s in share:
        w.writerow([s["problem"], s["reviews"], s["share"], s["helps"]])
print(json.dumps(summary, ensure_ascii=False, indent=1))
