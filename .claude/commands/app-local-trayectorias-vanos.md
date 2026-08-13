---
description: Abre en el navegador el tablero local de agrupamiento y evolucion por vano (cuaderno 04), instalando y construyendo por su cuenta lo que falte. No usa Databricks ni conexion.
---

> **Read `.claude/commands/_contrato-apps-locales.md` first.** It is mandatory and holds
> the whole procedure: fixed port, already-running check, preflight, background launch,
> what to report, and the restrictions already met in the field.

Opens the local dashboard built from
`notebooks/old_version/04_uiti_vano_trayectorias_vano.ipynb`. It is the same dashboard as
`/app-local-trayectorias-circuitos` one level down: where that one places circuits, this
one places vanos inside the selected circuit, with its map, its K-Means cloud and the
sliding window driving both views at once.

## Parameters for the shared contract

| | |
|---|---|
| app folder | `aplicaciones/04_trayectorias_vanos` |
| port | **8804** |
| build output (contract check 3) | `04_trayectorias_vanos/panel/index.html` |
| build cost, if missing | **~71 s** — 67,2 s of it is cell 2 reading the 540 MB CSV |
| environment size, if missing | 633 MB |
| startup timeout once built | 20 s |

## What is specific to this one

- **Never clean this notebook's stored output.** It is the only one of the five whose
  saved output is an INPUT: `scripts/extract_geometrias_014.py` reads the K-Means
  geometry out of it, and notebooks 05 and 06 share that geometry. Building does not
  touch it — `_comun/cuaderno.py` reads the document and `exec`s the sources, never
  writing back — and that is verified: after a build, `git status --porcelain notebooks/`
  comes back empty. Check it anyway if you ever rebuild.
- **It needs the shapefiles**, not just the CSV: `data/GEO/MVLINSEC.shp` and its
  siblings. If they are missing the build fails inside the notebook — say which file and
  stop, since nothing in the repo regenerates them.
- **The equipment traces must be the LAST ones on the map.** In MapLibre trace order is
  layer order, and the 25 px white halo used to paint over the transformers and switches.
  If someone reports that equipment disappeared, that is where to look — not in the data.
- **It never lights up another circuit.** The buckets are already split by circuit; the
  only exception is having no circuit selected, where the window rules alone. Otherwise
  the whole cloud would go uniformly grey and the slider would say nothing.
- It shares `plotly.js` with the other three static dashboards — same file, same hash
  `8ef4c6ab13`, verified. This one then costs 1,41 MB instead of 2,81 MB.

## Rebuilding

Only when the user asks, or when they say the data changed. It is not automatic: unlike
the simulator, this dashboard does not check whether its notebook moved.

```
cd aplicaciones/04_trayectorias_vanos && \
  PYTHONUNBUFFERED=1 python3 ../_comun/gestor.py iniciar --puerto 8804 --reconstruir
```

Announce the ~71 s first, and stop any running instance before rebuilding — the server
holds the old panel in memory and would keep serving it.
