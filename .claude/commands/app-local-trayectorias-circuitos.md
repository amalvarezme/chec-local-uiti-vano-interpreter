---
description: Abre en el navegador el tablero local de trayectoria y agrupamiento de circuitos (cuaderno 03), instalando y construyendo por su cuenta lo que falte. No usa Databricks ni conexion.
---

> **Read `.claude/commands/_contrato-apps-locales.md` first.** It is mandatory and holds
> the whole procedure: fixed port, already-running check, preflight, background launch,
> what to report, and the restrictions already met in the field.

Opens the local dashboard built from
`notebooks/old_version/03_uiti_vano_trayectorias_circuitos.ipynb`: the circuit cloud
grouped by K-Means, the dual-axis time series with the active window drawn at triple
size, and the circuit map — all governed by one sliding window.

## Parameters for the shared contract

| | |
|---|---|
| app folder | `aplicaciones/03_trayectorias_circuitos` |
| port | **8803** |
| build output (contract check 3) | `03_trayectorias_circuitos/panel/index.html` |
| build cost, if missing | **~71 s** — 58,7 s of it is cell 2 reading the 540 MB CSV |
| environment size, if missing | 633 MB |
| startup timeout once built | 20 s |

## What is specific to this one

- **It needs the shapefiles**, not just the CSV: `data/GEO/MVLINSEC.shp` and its
  siblings. If they are missing the build fails inside the notebook — say which file and
  stop, since nothing in the repo regenerates them.
- **The K-Means is fitted at build time, in Python.** What travels to the browser are
  resolved coordinates and labels. Moving the slider reorders opacities over points that
  already exist; it never re-fits anything. If the user asks why it reacts instantly,
  that is the reason.
- **The active-window point rides the immediate path of the slider, not the debounced
  one.** The expensive repaints are deliberately debounced 140 ms; the enlarged point is
  eleven numbers per series and moves with the drag. If someone reports it lagging behind
  the slider, that wiring broke — `tests/test_project_flow_ventana_activa.py` pins it.
- **The cloud has exactly two opacity levels**, 1.0 and 0.30. A point IS a
  (circuit, window) pair, so "which one am I looking at" has a single answer. If a third
  tone shows up, the old three-level cascade came back.
- It shares `plotly.js` with the other three static dashboards — same file, same hash
  `8ef4c6ab13`, verified. Whoever opened any of them already has it cached, and this one
  then costs 1,65 MB instead of 3,05 MB.

## Rebuilding

Only when the user asks, or when they say the data changed. It is not automatic: unlike
the simulator, this dashboard does not check whether its notebook moved.

```
cd aplicaciones/03_trayectorias_circuitos && \
  PYTHONUNBUFFERED=1 python3 ../_comun/gestor.py iniciar --puerto 8803 --reconstruir
```

Announce the ~71 s first, and stop any running instance before rebuilding — the server
holds the old panel in memory and would keep serving it.
