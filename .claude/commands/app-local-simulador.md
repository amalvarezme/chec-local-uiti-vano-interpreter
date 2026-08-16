---
description: Abre en el navegador el simulador local de riesgo por vano (cuaderno 06), servido con Voila sobre un kernel vivo, instalando y construyendo por su cuenta lo que falte. No usa Databricks ni conexion.
---

> **Read `.claude/commands/_contrato-apps-locales.md` first.** It is mandatory and holds
> the whole procedure: fixed port, already-running check, preflight, background launch,
> what to report, and the restrictions already met in the field — R3 and R4 are this
> app's.

Opens the local simulator built from `src/chec_tableros/simulador/`: the historical map
and the simulated-criticality one, selection of up to 15 vanos, the 26 simulable
variables, the top variables per vano, the relevance graph and the cost of the plan.

Nothing in this command changed when the board left
`notebooks/base_apps/06_uiti_vano_explicabilidad_simulador.ipynb`, and that is the point:
it drives `aplicaciones/06_simulador` through the shared contract and never touches the
board's source. The two build outputs below are the same two files — only what writes
`cuaderno/06_simulador.ipynb` changed (a generator, not a text patcher).

## This one is not a static document

The other two `/app-local-*` commands serve an HTML file. This one serves a **live
Python kernel** through Voila, because *Simular* runs the PyTorch MIL model on the vanos
the user marked with the values they typed — 26 variables over up to 15 vanos is not a
precomputable space. Everything below follows from that.

## Parameters for the shared contract

| | |
|---|---|
| app folder | `aplicaciones/06_simulador` |
| port | **8866** |
| build output (contract check 3) | `06_simulador/paquete/manifiesto.json` **and** `06_simulador/cuaderno/06_simulador.ipynb` |
| build cost, if missing | **~8 s**, with a peak of 3,01 GB of RAM |
| environment size, if missing | **1,6 GB** — PyTorch is nearly all of it |
| startup timeout once built | **90 s** — Voila starts a kernel and runs the whole notebook before answering |

8866 and not a port in the 88xx sequence of the other two: it is the port `app.py`
already prefers when launched by double-click, so both paths land on the same URL.

## Extra preflight, specific to this one

Beyond the contract's checks, the **build** needs artifacts no other app does. Check
before building, and if one is missing stop with the name of whatever produces it. Only
the geometry can be regenerated from this repo; the rest cannot:

| file | produced by |
|---|---|
| `data/models/mil_vano_ventana_v1.pt` | `05_mil_vano_ventana.ipynb` |
| `data/derived/bolsas_mil_full.joblib` | `05_mil_vano_ventana.ipynb` |
| `data/geometria_kmeans_014_v1.json` | tracked in git; reproducible with `scripts/exportar_geometria.py` |
| `data/GEO/MVLINSEC.shp` | not regenerable |

Once the package is built, none of them is opened again.

Also run the guard tests before a build — the memory numbers rest on them:

```
.venv/bin/python -m pytest tests/test_mil_simulador_015.py -q
```

36 tests, ~3 s. They pin that the entry points index the instance matrix **before**
promoting to `float64`; the old form read all 88 MB on every click and turned the
memory mapping into a private copy. If they fail, say so and do not claim the measured
figures.

## What "Diagnostico" studies

The button reads the user's marks as an **input**, so what it returns depends on what is ticked
when it is pressed:

1. the marked vanos — by checkbox or by clicking them on the base map — that have a cell in the
   active window (without one the model has nothing to score, and the panel names them apart);
2. filled up to **15** with the highest-UITI vanos of that window;
3. anything that did not fit is counted in the panel, so a capped list never reads as a circuit
   with only 15 vanos with events.

The rule lives in `ventanas_015.vanos_para_diagnostico` and is unit-tested; the notebook cell
only wires it. If the user reports "the diagnostic ignored my selection", check that the vanos
they marked have events in the active window before looking anywhere else — measured over 30
circuits, only 21% of the vano checkboxes have a cell in a given window.

## It rebuilds itself, and that is deliberate

Unlike the other two, `iniciar` checks whether **any of its inputs** changed since the
package was built and rebuilds on its own if so. Do not suppress this. A package frozen
from stale inputs feeding a newer notebook is the one way the dashboard draws data that
no longer corresponds **without raising any error**.

The manifest stores one fingerprint per input under `insumos`, in two forms
(`_comun/huellas.py`): **sha1** for the small ones — the notebook and the four files
copied into the package, ~1 MB, so a `git checkout` that only moves timestamps does not
trigger a rebuild — and **bytes + mtime** for the heavy ones (the 540 MB CSV, the bolsas
artifact, the three shapefiles with their `.dbf`). Hashing those 909 MB on every start
would cost seconds against the 0,3 s the package takes to load; a timestamp fails safe,
so at worst a `git lfs pull` buys one extra rebuild. The whole check costs **1 ms**,
measured.

If it rebuilds, say why — the reason names the input: *"cambio Variables_simular.xlsx
desde la ultima construccion"*. A package built before this existed reports *"el paquete
lo construyo una version anterior, que no registraba sus insumos"* and rebuilds once.

## What to tell the user when it opens

- **The first load takes ~4,5 s; the rest are instant.** The port answers at 0,77 s but
  the page needs a kernel, and starting it is where PyTorch gets imported. Expected, not
  a fault — the menu already shows "Cargando..." meanwhile. The local app does **not**
  pre-heat a kernel: measured A/B requesting the page the way the menu does, pre-heating
  did not shorten the wait (4,78 s vs 4,45 s — the spare kernel is not ready yet at
  0,77 s, so Voila starts a fresh one anyway) and left 1.694 MB resident instead of 931.
- **Each open tab holds its own kernel**, around 700 MB. A closed tab is reclaimed after
  10 minutes. An **open** one is not — deliberately, so nobody reading the dashboard
  loses their session mid-way.
- The notebook in the repository is untouched: what Voila serves is a patched copy under
  `06_simulador/cuaderno/`.

## If the page answers 500

Read `/tmp/app-local-06_simulador.log` before guessing. The known cause is restriction
R3 — Voila resolving the kernel to another environment. The log names the interpreter it
tried to launch: if it is not the one under `06_simulador/.venv`, that is the cause, and
the fix is deleting `06_simulador/.venv/share/jupyter/kernels/chec-simulador-vano` and
relaunching so `app.py` registers it again.

## Rebuilding by hand

```
cd aplicaciones/06_simulador && \
  PYTHONUNBUFFERED=1 python3 ../_comun/gestor.py iniciar --puerto 8866 --reconstruir
```

Stop any running instance first: a live kernel holds the old package memory-mapped.
