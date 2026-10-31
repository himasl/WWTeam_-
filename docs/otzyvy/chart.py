import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

data = json.load(open("itogi.json", encoding="utf-8"))
shares = [s for s in data["shares"] if s["code"] != "E"] + [s for s in data["shares"] if s["code"] == "E"]
COLOR = {"да": "#104281", "частично": "#5598e7", "нет": "#c3c2b7"}
INK, SECOND, MUTED, SURFACE = "#0b0b0b", "#52514e", "#898781", "#fcfcfb"

plt.rcParams["font.family"] = "Inter"
fig, ax = plt.subplots(figsize=(13.33, 7.5), dpi=150)
fig.patch.set_facecolor(SURFACE)
ax.set_facecolor(SURFACE)
y = list(range(len(shares)))[::-1]
ax.barh(y, [s["share"] for s in shares], height=0.62, color=[COLOR[s["helps"]] for s in shares], edgecolor=SURFACE, linewidth=2)
for yi, s in zip(y, shares):
    ax.annotate(f'{s["share"]:.0f}%', (s["share"], yi), xytext=(8, 0), textcoords="offset points", va="center", fontsize=13, color=INK, fontweight="semibold")
    ax.annotate(f'{s["reviews"]} отз.', (s["share"], yi), xytext=(48, 0), textcoords="offset points", va="center", fontsize=11, color=MUTED)
ax.set_yticks(y, [s["problem"] for s in shares], fontsize=13, color=INK)
ax.set_xlim(0, 40)
ax.set_xticks([])
for side in ("top", "right", "bottom"):
    ax.spines[side].set_visible(False)
ax.spines["left"].set_color("#c3c2b7")
ax.tick_params(axis="y", length=0, pad=10)
fig.text(0.035, 0.93, "На что жалуются выездные сотрудники банков", fontsize=22, fontweight="bold", color=INK)
fig.text(0.035, 0.885, f'Доля отзывов с жалобой, {data["with_complaint"]} отзывов представителей Т-Банка на DreamJob и Отзовике, 2021–2026. В одном отзыве может быть несколько проблем.',
         fontsize=12, color=SECOND)
ax.legend(handles=[Patch(color=COLOR["да"], label="Решает WПомощник"), Patch(color=COLOR["частично"], label="Решает частично"),
                   Patch(color=COLOR["нет"], label="Вне продукта")],
          loc="lower right", frameon=False, fontsize=12, labelcolor=SECOND)
fig.text(0.035, 0.03, "Разметка вручную по тексту «что не нравится». Отзывы курьеров Альфа-Банка с kyrieros.ru не учтены: 80 из 81 написаны по одному шаблону.",
         fontsize=10, color=MUTED)
plt.subplots_adjust(left=0.3, right=0.97, top=0.84, bottom=0.09)
fig.savefig("zhaloby.png", facecolor=SURFACE)
