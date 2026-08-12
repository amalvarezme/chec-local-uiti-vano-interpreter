---
description: Abre en el navegador el simulador local de riesgo por vano (cuaderno 06), servido con Voila sobre un kernel vivo, instalando y construyendo por su cuenta lo que falte. No usa Databricks ni conexion.
---

> **Read `.claude/commands/_contrato-apps-locales.md` first.** It is mandatory and holds
> the whole procedure: fixed port, already-running check, preflight, background launch,
> what to report, and the restrictions already met in the field — R3 and R4 are this
> app's.

Opens the local simulator built from
`notebooks/project_flow/06_uiti_vano_explicabilidad_simulador.ipynb`: the historical map
and the simulated-criticality one, selection of up to 10 vanos, the 26 simulable
variables, the top variables per vano, the relevance graph and the cost of the plan.

## This one is not a static document

The other two `/app-local-*` commands serve an HTML file. This one serves a **live
Python kernel** through Voila, because *Simular* runs the PyTorch MIL model on the vanos
the user marked with the values they typed — 26 variables over up to 10 vanos is not a
precomputable space. Everything below follows from that.

## Parameters for the shared contract

| | |
|---|---|
| app folder | `notebooks/project_flow/aplicaciones/06_simulador` |
| port | **8866** |
| build output (contract check 3) | `06_simulador/paquete/manifiesto.json` **and** `06_simulador/cuaderno/06_simulador.ipynb` |
| build cost, if missing | **~8 s**, with a peak of 3,01 GB of RAM |
| environment size, if missing | **1,6 GB** — PyTorch is nearly all of it |
| startup timeout once built | **90 s** — Voila starts a kernel and runs the whole notebook before answering |

8866 and not a port in the 88xx sequence of the other two: it is the port `app.py`
already prefers when launched by double-click, so both paths land on the same URL.

## Extra preflight, specific to this one

Beyond the contract's checks, the **build** needs artifacts no other app does. Check
before building, and if one is missing stop with the name of the notebook that produces
it — nothing here can regenerate them:

| file | produced by |
|---|---|
| `data/models/mil_vano_ventana_v1.pt` | `05_mil_vano_ventana.ipynb` |
| `data/derived/bolsas_mil_full.joblib` | `05_mil_vano_ventana.ipynb` |
| `data/derived/geometrias_014.json` | extracted from `04_uiti_vano_trayectorias_vano.ipynb` |
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

## It rebuilds itself, and that is deliberate

Unlike the other two, `iniciar` checks whether notebook 06 changed since the package was
built — the manifest stores its sha1 — and rebuilds on its own if so. Do not suppress
this. A package frozen from old startup cells feeding a newer notebook is the one way
the dashboard draws data that no longer corresponds **without raising any error**.

If it rebuilds, say why: *"notebook 06 changed since the last build"*.

## What to tell the user when it opens

- **The first load is instant, the second is not.** Restriction R4: one pre-executed
  kernel waits, so the first page answers in 4 ms and the next takes ~6 s while a new
  kernel starts. Expected, not a fault.
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
cd notebooks/project_flow/aplicaciones/06_simulador && \
  PYTHONUNBUFFERED=1 python3 ../_comun/gestor.py iniciar --puerto 8866 --reconstruir
```

Stop any running instance first: a live kernel holds the old package memory-mapped.
