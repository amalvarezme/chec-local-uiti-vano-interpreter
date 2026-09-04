"""Dos preguntas: (a) el backward de un Linear diminuto en MPS, aislado;
(b) si el problema es tamano, un lote 16x mayor debe cerrar la brecha."""
import time, torch, torch.nn as nn

def sync(d):
    if d == "mps": torch.mps.synchronize()

def t(fn, d, rep=200):
    for _ in range(20): fn()
    sync(d); t0 = time.perf_counter()
    for _ in range(rep): fn()
    sync(d); return (time.perf_counter() - t0) / rep * 1e6

print("=== (a) un solo Linear, forward vs forward+backward ===")
print(f"{'filas x 80 -> 128':<22}{'':<6}{'CPU us':>9}{'MPS us':>9}{'MPS/CPU':>9}")
for n in (664, 6640, 66400):
    r = {}
    for d in ("cpu", "mps"):
        lin = nn.Linear(80, 128).to(d)
        x = torch.randn(n, 80, device=d, requires_grad=True)
        def fwd(): 
            with torch.no_grad(): lin(x)
        def fb():
            lin.zero_grad(); y = lin(x); y.sum().backward()
        r[d] = (t(fwd, d, 100), t(fb, d, 100))
    print(f"  n={n:<8} forward      {r['cpu'][0]:>9.1f}{r['mps'][0]:>9.1f}{r['mps'][0]/r['cpu'][0]:>8.1f}x")
    print(f"  n={n:<8} fwd+backward {r['cpu'][1]:>9.1f}{r['mps'][1]:>9.1f}{r['mps'][1]/r['cpu'][1]:>8.1f}x")

print("\n=== (b) una MLP como la del modelo, escalando el lote ===")
class Mini(nn.Module):
    def __init__(s):
        super().__init__()
        s.a = nn.Sequential(nn.Linear(80,128), nn.LayerNorm(128), nn.ReLU(),
                            nn.Linear(128,128), nn.LayerNorm(128), nn.ReLU(),
                            nn.Linear(128,64))
    def forward(s, x): return s.a(x)

print(f"{'instancias':<14}{'CPU ms':>10}{'MPS ms':>10}{'MPS/CPU':>10}")
for n in (664, 2656, 10624, 42496, 169984):
    r = {}
    for d in ("cpu", "mps"):
        m = Mini().to(d); o = torch.optim.AdamW(m.parameters(), lr=1e-3)
        x = torch.randn(n, 80, device=d)
        def paso():
            o.zero_grad(); m(x).sum().backward(); o.step()
        r[d] = t(paso, d, 30) / 1000
    marca = "  <- MPS gana" if r["mps"] < r["cpu"] else ""
    print(f"{n:<14}{r['cpu']:>10.2f}{r['mps']:>10.2f}{r['mps']/r['cpu']:>9.1f}x{marca}")
