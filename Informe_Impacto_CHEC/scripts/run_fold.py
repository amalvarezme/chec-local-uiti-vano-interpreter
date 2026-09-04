"""Run notebook cells 0..44 (prep + fold helpers), then ONE fold with history
capture. Never reaches the model-saving cell (64), so data/models/ is untouched."""
import json, os, sys, pathlib
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

ROOT = pathlib.Path("/Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter")
OUT  = pathlib.Path(sys.argv[1])
nb = json.load(open(ROOT / "notebooks/05_mil_vano_ventana.ipynb"))
cells = nb["cells"]

def _noop_display(*a, **k):
    return None

g = {"__name__": "__main__", "display": _noop_display}
os.chdir(ROOT / "notebooks")

def run(i):
    c = cells[i]
    if c["cell_type"] != "code":
        return
    src = "".join(c["source"])
    if i == 1:
        src += '\nmode = "full"\nEJECUCION = "entrenamiento"\n'
    print(f"--- cell {i} ---", flush=True)
    exec(compile(src, f"<cell{i}>", "exec"), g)

for i in range(0, 45):
    run(i)

print("=== prep done, running ONE fold with history ===", flush=True)
import numpy as np, torch, time
np.set_printoptions(suppress=True)

construir_folds = g["construir_folds_agrupados"]
bag_index = g["bag_index"]; X_inst_bolsas = g["X_inst_bolsas"]
clase_observada = g["clase_observada"]; geometria = g["geometria"]

folds = construir_folds(bag_index, clase_observada, n_splits=g["N_SPLITS"], seed=g["RANDOM_STATE"])
train_idx, test_idx = folds[0]

sub = g["construir_subindice_bolsas"]
bi_tr, X_tr = sub(bag_index, X_inst_bolsas, train_idx)
bi_te, X_te = sub(bag_index, X_inst_bolsas, test_idx)

fm, fs = g["calcular_estadisticas_reconstruccion_mgcecdl"](X_tr)
kl = g["KernelDensityWeightedMSELoss"].from_targets(np.log1p(bi_tr.y))
modelo, perdida = g["construir_modelo_y_perdida"](fm, fs, kl)

t0 = time.time()
res = g["entrenar_mil"](
    modelo, perdida, X_tr, bi_tr, epochs=g["EPOCHS"],
    bag_batch_size=g["BAG_BATCH_SIZE"], lr=g["LR"], weight_decay=g["WEIGHT_DECAY"],
    seed=g["RANDOM_STATE"], device=g["DEVICE"], verbose=True,
)
elapsed = time.time() - t0

u_hat_te, _ = g["evaluar_lote_completo"](res["model"], X_te, bi_te)
n_obs_te = bi_te.counts.astype(np.float64)
clase_te, _ = g["asignar_clase"](n_obs_te, u_hat_te, geometria)
clase_obs_te = np.asarray(clase_observada)[test_idx]
from sklearn.metrics import f1_score, confusion_matrix, accuracy_score

payload = {
    "epochs": g["EPOCHS"],
    "n_bolsas_train": int(len(bi_tr.offsets) - 1),
    "n_bolsas_test": int(len(bi_te.offsets) - 1),
    "segundos_entrenamiento": elapsed,
    "history": res.get("history"),
    "historial_epocas": res.get("historial_epocas"),
    "fold_macro_f1": float(f1_score(clase_obs_te, clase_te, average="macro", labels=[0,1,2,3])),
    "fold_accuracy": float(accuracy_score(clase_obs_te, clase_te)),
    "fold_confusion": confusion_matrix(clase_obs_te, clase_te, labels=[0,1,2,3]).tolist(),
}
OUT.write_text(json.dumps(payload, indent=1, default=float))
print("WROTE", OUT, "in", round(elapsed,1), "s", flush=True)
