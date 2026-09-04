import json, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["DejaVu Serif"],
    "mathtext.fontset": "dejavuserif",
    "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8.5,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
    "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "figure.dpi": 220,
})

d = json.load(open("fold_history.json"))
h = d["history"]
ep = [r["epoch"] for r in h]

def col(k):
    return [r[k] for r in h]

fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.45, 2.55), constrained_layout=True)
fig.get_layout_engine().set(w_pad=0.08)

AZUL, NARANJA, VERDE, MORADO, GRIS = "#1f5fa9", "#d1751a", "#2e7d32", "#6a3d9a", "#8a8a8a"

a1.plot(ep, col("total_loss"), color=AZUL, lw=1.6, marker="o", ms=2.2)
a1.set_yscale("log")
a1.set_title("Pérdida total de entrenamiento", pad=4)
a1.set_xlabel("época"); a1.set_ylabel("pérdida (escala logarítmica)")
a1.annotate("8,18 en la época 1", xy=(1.55, 7.3), fontsize=7, color=AZUL)
a1.annotate("0,565 en la época 30", xy=(30.4, 0.515),
            fontsize=7, color=AZUL, ha="right")
a1.annotate("repunte reproducible\nhacia la época 23", xy=(23, h[22]["total_loss"]),
            xytext=(13.0, 2.6), fontsize=6.5, color="0.35", ha="center",
            arrowprops=dict(arrowstyle="-", lw=0.5, color="0.55",
                            connectionstyle="arc3,rad=-0.3"))

for k, lab, c, ls in (
    ("supervised_loss",          "error sobre el UITI de la bolsa",  AZUL,    "-"),
    ("class_loss",               "error sobre el grupo de criticidad", NARANJA, "-"),
    ("reconstruction_loss",      "reconstrucción de las variables",   VERDE,   "-"),
    ("mutual_information_loss",  "término del grafo de restricciones", MORADO,  (0, (4, 2))),
):
    a2.plot(ep, col(k), color=c, lw=1.3, ls=ls, label=lab)
a2.set_yscale("log")
a2.set_title("Los cuatro términos que la componen", pad=4)
a2.set_xlabel("época")
a2.legend(loc="upper right", frameon=False, handlelength=1.9, borderpad=0.2, labelspacing=0.28)

from matplotlib.ticker import FixedLocator, FixedFormatter, NullLocator

def ticks_es(ax, valores):
    ax.yaxis.set_major_locator(FixedLocator(valores))
    ax.yaxis.set_major_formatter(FixedFormatter(
        [("%g" % v).replace(".", ",") for v in valores]))
    ax.yaxis.set_minor_locator(NullLocator())

ticks_es(a1, [0.5, 0.7, 1, 2, 4, 8])
ticks_es(a2, [0.2, 0.3, 0.5, 1, 2, 4, 6])

for ax in (a1, a2):
    ax.set_xlim(0.4, 30.6)
    ax.set_xticks([1, 5, 10, 15, 20, 25, 30])
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(True, lw=0.3, color="0.9", which="major")
    ax.set_axisbelow(True)

fig.savefig("curvas_entrenamiento.png", bbox_inches="tight", pad_inches=0.04, facecolor="white")
print("ok",
      "total", round(h[0]["total_loss"], 4), "->", round(h[-1]["total_loss"], 4),
      "| sup", round(h[0]["supervised_loss"], 4), "->", round(h[-1]["supervised_loss"], 4),
      "| clase", round(h[0]["class_loss"], 4), "->", round(h[-1]["class_loss"], 4),
      "| rec", round(h[0]["reconstruction_loss"], 4), "->", round(h[-1]["reconstruction_loss"], 4),
      "| mi", round(h[0]["mutual_information_loss"], 4), "->", round(h[-1]["mutual_information_loss"], 4))
