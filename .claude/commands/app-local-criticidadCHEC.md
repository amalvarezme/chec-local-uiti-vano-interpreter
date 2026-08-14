---
description: Abre CriticidadCHEC, el menu local desde el que se lanzan, se vigilan y se cierran los cinco tableros de criticidad por vano. No usa Databricks ni conexion.
---

> **Read `.claude/commands/_contrato-apps-locales.md` first.** It is mandatory and holds
> the whole procedure: fixed port, already-running check, preflight, background launch,
> what to report, and the restrictions already met in the field.

Opens **CriticidadCHEC**, the menu that governs the other five local apps. It draws no
dashboard of its own: it launches each one as a child process, on its own port and with
its own environment, and can stop them again.

## Parameters for the shared contract

| | |
|---|---|
| app folder | `aplicaciones/00_criticidad_chec` |
| port | **8800** |
| build output (contract check 3) | *none* — the menu builds nothing |
| build cost, if missing | **0 s** |
| environment size, if missing | ~20 MB |
| startup timeout once built | 10 s |

## What is specific to this one

- **It has no dependencies and no `construir.py`.** That is the design, not an
  oversight: the menu launches the others as child processes precisely so it never has
  to import them. Importing any would cost it the union of five requirement lists —
  `torch` included, 1,6 GB — just to draw a menu. Its `requirements.txt` exists only so
  the gestor recognises the folder.
- **It owns the other five ports.** `catalogo()` in `_comun/menu.py` carries the same
  ports as the table in the shared contract, and a test pins them against that table.
  They must not diverge: if the menu opened clima on another port, an instance launched
  by hand and one launched from the menu would coexist without seeing each other, each
  building and serving separately. With the shared port the menu **recognises** an app
  that was already open instead of duplicating it.
- **Closing the menu closes everything it opened, and only the menu can do that.**
  `Ctrl+C` in its window and the *Cerrar todo* button in its page are the only two
  paths to a general shutdown. The two buttons inside a dashboard — *Volver al menú* and
  *Cerrar* — shut down **that** dashboard with its port and whatever hangs off it, and
  leave the other four and the menu running; the menu notices on its own, because it
  polls the five ports every 2,5 s. Measured over the five apps, each opened from the
  menu, closed from its own button, reopened on the same port and stopped again from the
  menu, then three at once with *Cerrar todo*: every port free, menu exits 0, no orphan
  process and no orphan kernel. `tests/test_menu_apagado.py` holds that shape as tests.
- **"Detenida" means the port is free, and nothing else.** The menu waits for the port
  to be released before saying so, and what it cannot free comes back as a failure
  naming the port. It never kills by port: something it did not launch is reported, not
  shot at — the same rule as section B of the shared contract. That is also what the
  final screen of *Cerrar todo* lists, because after it there is no menu left to ask.
- **Each dashboard opens in its own tab, on purpose.** A tab that navigates accumulates
  its own history, and that is exactly what stops a script from closing it. One tab per
  app means each is born from the menu's `window.open()`, and a window a script opened
  can always be closed by a script — which is what makes *Volver al menú* actually close
  the tab. Do not "simplify" this into a single tab without reading
  `aplicaciones/_comun/menu_pagina.py`, whose module docstring explains the two
  measurements behind it.
- **The simulator is the exception in two places.** Its bar is `ipywidgets`, not
  injected HTML, because Voila serves it — see the `_BOTON_CERRAR` block in
  `06_simulador/preparar.py`. And the menu stops it with `SIGTERM` to the pid in
  `06_simulador/.servidor.pid` rather than `POST /apagar`, because Voila has no shutdown
  route. That pid file is also the only way to reach a simulator the menu did not
  launch, so the menu checks it against the process table before signalling it.
- **Never health-check the simulator with a page request.** Voila renders the notebook
  on every request, so each `GET /` leaves a ~700 MB kernel behind — measured going from
  one to six kernels just by asking whether it was alive, and the load it created made
  Voila miss the probe deadline, so the menu declared it dead and stopped signalling it.
  The menu asks the port, not the app: a TCP connection, which renders nothing.

## If the user asks to open one specific dashboard

Use its own command — `/app-local-clima`, `/app-local-agrupamiento-circuitos`,
`/app-local-trayectorias-circuitos`, `/app-local-trayectorias-vanos`,
`/app-local-simulador`. This one is for "open the menu" or "I want to see everything".
Both routes share the ports, so they never fight.
