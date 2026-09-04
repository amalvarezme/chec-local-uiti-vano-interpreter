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

d = json.load(open("roc.json"))
curvas = {(c["umbral"], c["brazo"]): c for c in d["curvas"]}

fig, axes = plt.subplots(1, 3, figsize=(6.45, 2.4), constrained_layout=True)
fig.get_layout_engine().set(w_pad=0.055)
AZUL, NARANJA = "#1f5fa9", "#d1751a"

for ax, k in zip(axes, (1, 2, 3)):
    cm = curvas[(k, "modelo")]
    cb = curvas[(k, "estructural")]
    ax.plot([0, 1], [0, 1], color="0.75", lw=0.7, ls=(0, (3, 3)), zorder=1)
    ax.plot(cb["fpr"], cb["tpr"], color=NARANJA, lw=1.1, ls="--", zorder=2,
            label="Bosque aleatorio (AUC {:.3f})".format(cb["auc"]).replace(".", ","))
    ax.plot(cm["fpr"], cm["tpr"], color=AZUL, lw=1.4, zorder=3,
            label="M-GCECDL (AUC {:.3f})".format(cm["auc"]).replace(".", ","))
    titulo = "grupo {} o superior\n{:,} de {:,} bolsas".format(
        cm["nombre"], cm["n_pos"], d["n"]).replace(",", ".")
    ax.set_title(titulo, pad=4)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1.003)
    ax.set_xticks([0, .25, .5, .75, 1]); ax.set_yticks([0, .25, .5, .75, 1])
    ax.set_xticklabels(["0", "0,25", "0,50", "0,75", "1"])
    ax.set_yticklabels(["0", "0,25", "0,50", "0,75", "1"])
    ax.legend(loc="lower right", frameon=False, handlelength=1.6, borderpad=0.2)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(True, lw=0.3, color="0.9")
    ax.set_axisbelow(True)

axes[0].set_ylabel("aciertos sobre el grupo\n(sensibilidad)")
fig.supxlabel("falsas alarmas (1 $-$ especificidad)", fontsize=8)
fig.savefig("curvas_roc.png", bbox_inches="tight", pad_inches=0.04, facecolor="white")
print("ok")
