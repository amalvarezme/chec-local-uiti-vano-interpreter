"""Where does a training step's time go, on CPU vs MPS?
Times each stage separately, over the SAME batches, on both devices."""
import sys, os, time
sys.path.insert(0, "/Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src")
os.environ.setdefault("OMP_NUM_THREADS", "2")
import numpy as np, torch, joblib

ROOT = "/Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter"
from chec_impacto.models.mgcecdl_mil import MILBagRegressor, MILBagLoss, _lote_de_instancias
from chec_impacto.models.mgcecdl import MGCECDLRegressor
from chec_impacto.models.mgcecdl_graph import GraphEdgeIndex
from chec_impacto.models.criticality_assignment import Geometria
from chec_impacto.training.mgcecdl import calcular_estadisticas_reconstruccion_mgcecdl
from chec_impacto.models.mgcecdl import KernelDensityWeightedMSELoss

b = joblib.load(f"{ROOT}/data/derived/bolsas_mil_full.joblib")
bag_index, X, feats = b["bag_index"], np.asarray(b["X"], dtype=np.float32), list(b["features"])
art = torch.load(f"{ROOT}/data/models/mil_vano_ventana_v1.pt", map_location="cpu", weights_only=False)
A = np.asarray(art["adjacency"], dtype=np.float32)
idx = {f: i for i, f in enumerate(art["features"])}
pares = np.asarray([[idx[e["source"]], idx[e["target"]]] for e in art["edges"]], dtype=np.int64)
EDGE = GraphEdgeIndex(pairs=pares, weights=A[pares[:, 0], pares[:, 1]].astype(np.float32), names=list(art["features"]))
MODS = art["modalidades"]
print(f"bolsas: {len(bag_index.offsets)-1} | instancias: {X.shape} | aristas: {len(pares)}")

BATCH, N_STEPS, WARM = 256, 40, 3
rng = np.random.default_rng(0)
orden = rng.permutation(len(bag_index.offsets) - 1)
lotes = [orden[i*BATCH:(i+1)*BATCH] for i in range(N_STEPS)]

t0 = time.perf_counter()
armados = [_lote_de_instancias(bag_index, l) for l in lotes]
t_armar = (time.perf_counter() - t0) / N_STEPS * 1000

X_cpu = torch.as_tensor(X)
y_cpu = torch.as_tensor(np.asarray(bag_index.y), dtype=torch.float32)
nobs_cpu = torch.as_tensor(np.asarray(bag_index.counts), dtype=torch.float32)

t0 = time.perf_counter()
gathers = [X_cpu[torch.as_tensor(f)] for f, _ in armados]
t_gather = (time.perf_counter() - t0) / N_STEPS * 1000

fm, fs = calcular_estadisticas_reconstruccion_mgcecdl(X[:50000])
kl = KernelDensityWeightedMSELoss.from_targets(np.log1p(bag_index.y))
geo = Geometria(**art["geometria"])

def construir(dev):
    torch.manual_seed(42)
    base = MGCECDLRegressor(modality_feature_indices=MODS, hidden_dim=128, embed_dim=64, dropout=0.1)
    m = MILBagRegressor(base=base, adjacency=A, edge_index=EDGE, alpha=0.2, attn_dim=64,
                        fusion="film", film_modulated_modality="estructurales").to(dev)
    lf = MILBagLoss(feature_mean=fm, feature_std=fs, adjacency_matrix=A, kernel_loss=kl,
                    lambda_reconstruction=0.01, lambda_mutual_information=0.01,
                    lambda_gate_deviation=0.0, lambda_modality_supervised=0.0,
                    lambda_clase=1.0, geometria=geo, temperatura_clase=0.01,
                    reconstruction_normalization="soft").to(dev)
    return m, lf

def sync(dev):
    if dev == "mps": torch.mps.synchronize()

def medir(dev):
    model, loss_fn = construir(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-5)
    model.train()
    acc = dict(transferencia=0.0, adelante=0.0, atras=0.0, sincronizar=0.0)
    for k in range(N_STEPS):
        lote = lotes[k]; _f, bl = armados[k]
        sync(dev); t0 = time.perf_counter()
        x = gathers[k].to(dev)
        ib = torch.as_tensor(bl, dtype=torch.long, device=dev)
        y = y_cpu[lote].to(dev); nb = nobs_cpu[lote].to(dev)
        sync(dev); t1 = time.perf_counter()
        out = model(x, ib, len(lote))
        c = loss_fn.compute_components(out, x, y, nb)
        sync(dev); t2 = time.perf_counter()
        opt.zero_grad(); c["total_loss"].backward(); opt.step()
        sync(dev); t3 = time.perf_counter()
        _ = torch.stack([c[n].detach() for n in
                         ("total_loss","supervised_loss","reconstruction_loss")]).cpu().numpy()
        sync(dev); t4 = time.perf_counter()
        if k >= WARM:
            acc["transferencia"] += t1-t0; acc["adelante"] += t2-t1
            acc["atras"] += t3-t2; acc["sincronizar"] += t4-t3
    n = N_STEPS - WARM
    return {k2: v/n*1000 for k2, v in acc.items()}


def sync(d):
    if d == "mps": torch.mps.synchronize()

tam = [len(f) for f, _ in armados]
print(f"\ninstancias por lote: min={min(tam)} max={max(tam)} distintas={len(set(tam))} de {len(tam)} lotes")

def correr(d, fijo):
    model, loss_fn = construir(d)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-5); model.train()
    def paso(k):
        j = 7 if fijo else k
        lote = lotes[j]; _f, bl = armados[j]
        x = gathers[j].to(d); ib = torch.as_tensor(bl, dtype=torch.long, device=d)
        y = y_cpu[lote].to(d); nb = nobs_cpu[lote].to(d)
        opt.zero_grad()
        c = loss_fn.compute_components(model(x, ib, len(lote)), x, y, nb)
        c["total_loss"].backward(); opt.step()
    for k in range(8): paso(k)
    sync(d); t0 = time.perf_counter()
    for k in range(8, 40): paso(k)
    sync(d); return (time.perf_counter() - t0) / 32 * 1000

print(f"\n{'':<38}{'CPU ms':>9}{'MPS ms':>9}{'MPS/CPU':>9}")
print("-"*65)
for fijo, et in ((True, "el MISMO lote 32 veces (forma fija)"),
                 (False, "32 lotes DISTINTOS (forma variable)")):
    c = correr("cpu", fijo); m = correr("mps", fijo)
    print(f"{et:<38}{c:>9.2f}{m:>9.2f}{m/c:>8.1f}x")
