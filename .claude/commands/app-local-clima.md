---
description: Abre en el navegador el tablero local de nube por vano y clima (cuaderno 01), instalando y construyendo por su cuenta lo que falte. No usa Databricks ni conexion.
---

> **Read `.claude/commands/_contrato-apps-locales.md` first.** It is mandatory and holds
> the whole procedure: fixed port, already-running check, preflight, background launch,
> what to report, and the restrictions already met in the field.

Opens the local dashboard built from
`notebooks/old_version/01_uiti_vano_clima.ipynb`: the per-vano cloud over the map with
the 6 selectable variables, the dual-axis time series and the 6 violins, with all 208
circuits inside and the selector switching between them live.

## Parameters for the shared contract

| | |
|---|---|
| app folder | `aplicaciones/01_clima` |
| port | **8801** |
| build output (contract check 3) | `01_clima/panel/index.html` |
| build cost, if missing | **~25 s** — 15,5 s reading the 540 MB CSV, 7,4 s the shapefiles |
| environment size, if missing | 484 MB |
| startup timeout once built | 20 s |

## What is specific to this one

- **It needs the shapefiles**, not just the CSV: `data/GEO/MVLINSEC.shp` and its
  siblings. If they are missing, the build fails inside the notebook — say which file
  and stop, since nothing in the repo regenerates them.
- **Once built it never touches `data/` again.** If the user asks why it opens instantly
  the second time, that is the reason: the dashboard is a static document and every
  control runs in the browser.
- **It is the heaviest of the three dashboards**: 27,8 MB of document, 23,1 MB of which
  are the data for the 208 circuits. First open transfers 6,37 MB compressed; later ones,
  17 KB. If the user asks whether it can be made lighter, the honest answer is that the
  weight is the 208 circuits travelling to the browser so the selector can switch them
  without re-running Python — dropping it means giving up the live selector.
- It shares `plotly.js` with `/app-local-agrupamiento-circuitos`: whoever opened that
  one already has it cached, and this one then costs 4,98 MB instead of 6,37 MB.

## Rebuilding

Only when the user asks, or when they say the data changed. It is not automatic: unlike
the simulator, this dashboard does not check whether its notebook moved.

```
cd aplicaciones/01_clima && \
  PYTHONUNBUFFERED=1 python3 ../_comun/gestor.py iniciar --puerto 8801 --reconstruir
```

Announce the ~25 s first, and stop any running instance before rebuilding — the server
holds the old panel in memory and would keep serving it.
