---
description: Abre en el navegador el tablero local de agrupamiento por UITI acumulado y numero de eventos (cuaderno 02), instalando y construyendo por su cuenta lo que falte. No usa Databricks ni conexion.
---

> **Read `.claude/commands/_contrato-apps-locales.md` first.** It is mandatory and holds
> the whole procedure: fixed port, already-running check, preflight, background launch,
> what to report, and the restrictions already met in the field.

Opens the local dashboard built from
`notebooks/project_flow/02_uiti_vano_kmeans.ipynb`: K-Means into 4 groups over
accumulated UITI and event count, with date-range calendars, the marginal densities, the
per-group violins and the label CSV download.

## The unit this opens is the VANO, not the circuit

The command name says *circuitos*, and the notebook does build a circuit-level board —
but **what this app publishes is the vano-level one**, the same choice the Databricks
sibling `/app-agrupamiento-vanos-circuitos` makes: it is the board that answers the
operational question, which vanos and from which circuits concentrate the criticality.
The circuit board stays as an intermediate step to be read inside the notebook.

Each point is a **vano** (27.390 of them), and its circuit shows in the tooltip but does
not take part in the grouping. Say this if the user seems to expect a point per circuit —
it is a real difference, not a detail:

> The groups are not comparable with the circuit ones even though they share names. A
> vano in `Alto` almost always lives in an `Alto` circuit, but an `Alto` circuit contains
> vanos from all four groups.

If the user actually wants the circuit board, it is not published as an app: it is read
by running the notebook, or through `/agrupamiento-circuitos`, which generates the
standalone circuit-clustering chart.

## Parameters for the shared contract

| | |
|---|---|
| app folder | `notebooks/project_flow/aplicaciones/02_agrupamiento_vanos` |
| port | **8802** |
| build output (contract check 3) | `02_agrupamiento_vanos/panel/index.html` |
| build cost, if missing | **~51 s** — the notebook reads the 540 MB CSV **twice**, once per circuit and once per vano |
| environment size, if missing | 530 MB |
| startup timeout once built | 20 s |

## What is specific to this one

- **No shapefiles.** This dashboard draws no map, so `data/GEO/` is irrelevant: only the
  CSV is needed, and only to build.
- **It is the lightest of the three**: 6,08 MB of document, of which 4,63 MB are
  `plotly.js` and only 1,41 MB the data. First open transfers 1,77 MB compressed; later
  ones, 16 KB. And since `plotly.js` is byte-for-byte the one `/app-local-clima` uses,
  opening this one after that costs **378 KB**.
- **A short range degenerates the grouping**, and it is worth warning about if the user
  narrows the calendars a lot: over a single month only 10.089 of the 27.390 vanos record
  any event and 55,8% of those record exactly one. The event axis then carries almost no
  information and the partition ends up decided by UITI alone.

## Rebuilding

Only when the user asks, or when they say the data changed — it is not automatic.

```
cd notebooks/project_flow/aplicaciones/02_agrupamiento_vanos && \
  PYTHONUNBUFFERED=1 python3 ../_comun/gestor.py iniciar --puerto 8802 --reconstruir
```

Announce the ~51 s first, and stop any running instance before rebuilding — the server
holds the old panel in memory and would keep serving it.
