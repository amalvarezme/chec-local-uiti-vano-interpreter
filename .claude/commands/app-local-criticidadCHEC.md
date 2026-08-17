---
description: Abre CriticidadCHEC, la aplicacion principal local: el menu desde el que se lanzan, se vigilan y se cierran los cinco tableros de criticidad por vano. Es el unico comando de las aplicaciones locales — los cinco tableros se abren desde su pagina, no con comandos propios. No usa Databricks ni conexion.
---

Opens **CriticidadCHEC**, the local desktop application. It draws no dashboard of its own:
it is the menu that governs the other five, launching each as a child process on its own
port and with its own environment, and stopping them again.

**It is the only entry point.** Until 2026-08-17 each dashboard also had its own command
(`/app-local-clima`, `/app-local-agrupamiento-circuitos`,
`/app-local-trayectorias-circuitos`, `/app-local-trayectorias-vanos`,
`/app-local-simulador`). Six commands for one application meant six copies of the same
preflight drifting apart, and a user who had to know which of the six they wanted before
seeing anything. The dashboards did not go anywhere: they are opened from this menu's page,
on the same ports, by the same `gestor.py`. This file absorbed the shared contract those
six read, so everything the launch needs is here.

Each app also has its own double-click launchers — `Iniciar.app` on macOS, `iniciar.bat` on
Windows. This command exists to do the same from the session, with the preflight and the
diagnosis a double-click cannot give.

## A. Fixed port per app — never pick a free one

| app folder | port | que sirve |
|---|---|---|
| `00_criticidad_chec` | **8800** | el menu — lo que abre este comando |
| `01_clima` | **8801** | nube por vano y clima (cuaderno 01) |
| `02_agrupamiento_vanos` | **8802** | agrupamiento por UITI acumulado y nº de eventos (cuaderno 02) |
| `03_trayectorias_circuitos` | **8803** | trayectoria y agrupamiento de circuitos (cuaderno 03) |
| `04_trayectorias_vanos` | **8804** | agrupamiento y evolucion por vano (cuaderno 04) |
| `06_simulador` | **8866** | simulador de riesgo por vano, con Voila (cuaderno 06) |

Every app uses the port in this table, on every path — the double-click launcher included.
It used to fall back to a port the system assigned when its own was taken, and that turned
the second double-click into a second copy of the same dashboard on a URL nobody knew:
measured, `01_clima` on 8801 and another one on 53745, invisible to CriticidadCHEC, which
looks for the apps where this table says. Pass `--puerto <port>` anyway: it is what keeps
the URL stable when the command and the launcher disagree.

**The menu owns these ports.** `catalogo()` in `aplicaciones/_comun/menu.py` carries the
same numbers and a test pins them against this table. They must not diverge: with the
shared port the menu **recognises** an app that was already open instead of duplicating it.
The simulator's 8866 is not a hole in the 88xx sequence — it is the port Voila uses.

## B. If it is already running, do not start a second one

The app refuses this on its own — it leaves its pid in `00_criticidad_chec/.servidor.pid`,
and an arrival on a port that pid already owns opens the browser on the running instance and
exits 0 instead of serving a second copy. Check it here anyway: the check below tells the
USER what happened, and it is the only one that runs before the app is even started.

```
lsof -nP -iTCP:8800 -sTCP:LISTEN
```

If something is listening, confirm it is this app and not an unrelated process:

```
ps -p <pid> -o command= | head -1
```

- The command line contains `aplicaciones/00_criticidad_chec/app.py` → **it is already
  running.** Report `http://127.0.0.1:8800/`, re-open the browser with
  `/usr/bin/open http://127.0.0.1:8800/`, and stop. Do not relaunch, do not rebuild.
- It is something else → tell the user which process owns the port and stop. Do not kill a
  process you did not start.

## C. Preflight — inspect, then repair without asking

Creating what is missing is this command's job. Do not ask permission for any of it; only
report what you had to do.

| # | check | if missing |
|---|---|---|
| 1 | `python3 --version` is 3.10+ | stop and say how to install it (macOS `brew install python@3.11`) |
| 2 | `aplicaciones/00_criticidad_chec/.venv/bin/python` exists | run step D1 |
| 3 | `data/Indicadores_vano_v3.csv` is over 1 MB | it is an unfetched Git-LFS pointer: run `git lfs pull` |

**The menu has no build step and no `construir.py`, and that is the design.** It launches
the others as child processes precisely so it never has to import them: importing any would
cost it the union of five requirement lists — `torch` included, 1,6 GB — just to draw a
menu. Its `requirements.txt` exists only so the gestor recognises the folder. Its own
environment is ~20 MB and it starts in under 10 s.

Check 3 only matters for the dashboards the user will open afterwards, and only when one of
them has to be **built**: an already-built dashboard never reads `data/` again. Say so
rather than blocking the menu on it.

### D1. Install the environment

```
cd aplicaciones/00_criticidad_chec && python3 ../_comun/gestor.py instalar
```

For the menu this is seconds. **For the dashboards it is not**: the first time the user
opens one from the page, its own environment is installed and its panel built — minutes,
and hundreds of MB (1,6 GB for the simulator). Tell them that before they click, so a long
silence is not read as a hang.

## E. Launch in the background, never in the foreground

The server blocks until `Ctrl+C`. Running it in the foreground would freeze the session, so
always launch it in the background, redirecting output to a log:

```
cd aplicaciones/00_criticidad_chec && \
  PYTHONUNBUFFERED=1 python3 ../_comun/gestor.py iniciar --puerto 8800 > /tmp/app-local-criticidad-chec.log 2>&1
```

`PYTHONUNBUFFERED=1` is not optional: without it Python block-buffers stdout when it is not
a terminal, and the log stays empty — including the line with the URL and any error.

Then poll until the port answers, up to 10 s:

```
curl -s -o /dev/null -m 5 -w '%{http_code}' http://127.0.0.1:8800/
```

- Answers `200` → done. Report the URL.
- The process died → **read the log and report the real error.** Never report a dashboard as
  open without having received a `200` from it.

## F. What the menu does that a bare dashboard cannot

- **Closing the menu closes everything it opened, and only the menu can do that.** `Ctrl+C`
  in its window and the *Cerrar todo* button in its page are the only two paths to a general
  shutdown. The two buttons inside a dashboard — *Volver al menú* and *Cerrar* — shut down
  **that** dashboard with its port and whatever hangs off it, and leave the other four and
  the menu running; the menu notices on its own, because it polls the five ports every
  2,5 s. Measured over the five apps, each opened from the menu, closed from its own button,
  reopened on the same port and stopped again from the menu, then three at once with *Cerrar
  todo*: every port free, menu exits 0, no orphan process and no orphan kernel.
  `tests/test_menu_apagado.py` holds that shape as tests.
- **"Detenida" means the port is free, and nothing else.** The menu waits for the port to be
  released before saying so, and what it cannot free comes back as a failure naming the
  port. It never kills by port: something it did not launch is reported, not shot at. That is
  also what the final screen of *Cerrar todo* lists, because after it there is no menu left
  to ask.
- **Each dashboard opens in its own tab, on purpose.** A tab that navigates accumulates its
  own history, and that is exactly what stops a script from closing it. One tab per app means
  each is born from the menu's `window.open()`, and a window a script opened can always be
  closed by a script — which is what makes *Volver al menú* actually close the tab. Do not
  "simplify" this into a single tab without reading `aplicaciones/_comun/menu_pagina.py`,
  whose module docstring explains the two measurements behind it.
- **The simulator is the exception in two places.** Its bar is `ipywidgets`, not injected
  HTML, because Voila serves it — see the `_BOTON_CERRAR` block in
  `06_simulador/preparar.py`. And the menu stops it with `SIGTERM` to the pid in
  `06_simulador/.servidor.pid` rather than `POST /apagar`, because Voila has no shutdown
  route. That pid file is also the only way to reach a simulator the menu did not launch, so
  the menu checks it against the process table before signalling it.
- **Never health-check the simulator with a page request.** Voila renders the notebook on
  every request, so each `GET /` leaves a ~700 MB kernel behind — measured going from one to
  six kernels just by asking whether it was alive, and the load it created made Voila miss
  the probe deadline, so the menu declared it dead and stopped signalling it. The menu asks
  the port, not the app: a TCP connection, which renders nothing.

## G. Report back

Give the user, in their language and in this order:

1. The URL, on its own line.
2. Whether the browser was opened automatically. The app does it itself with `/usr/bin/open`;
   if the log says it could not, say so and give the URL to paste.
3. Anything that had to be installed or built, and how long it took.
4. That the five dashboards open from the menu's page — with the warning about the first
   open of each one, from D1.
5. **How to stop it** — the app was launched detached, so `Ctrl+C` does not apply here:
   ```
   lsof -ti tcp:8800 -sTCP:LISTEN | xargs kill
   ```
   **`-sTCP:LISTEN` is not optional.** Without it, `lsof -ti tcp:8800` also returns the
   browser, which holds an established connection to that same port — measured: the port
   answered with the server's pid *and* Chrome's. Piping that into `kill` closes the user's
   browser and leaves the server running, which is the exact opposite of the intent. The same
   filter belongs in every `lsof` here.

## H. Restrictions already met in the field

Do not re-diagnose these.

- **R1 — `webbrowser` does not work on macOS from a launcher.** It resolves to
  `MacOSXOSAScript`, which talks to the browser over Apple Events and needs the Automation
  permission; without it, it fails silently. The apps use `/usr/bin/open`. Never "fix" a
  browser that does not open by going back to `webbrowser`.
- **R2 — `index.html` cannot be opened by double-click.** The data is fetched separately and
  browsers block that over `file://`. It has to be served. The page says so on screen if
  someone tries.
- **R3 — the simulator needs `ipykernel` in its environment** even though no cell imports it.
  Without it Voila falls back to the first user-level kernelspec it finds — which may point
  at another project's interpreter, or a deleted one — and answers 500. Its
  `requirements.txt` already carries it, and the app registers its own kernel
  (`chec-simulador-vano`) with `--sys-prefix`.
- **R4 — the first request to the simulator is instant, the second is not.** It keeps one
  pre-executed kernel waiting: the first page load answers in 4 ms and the next one takes
  ~6 s while a new kernel starts. That is expected, not a fault.
- **R5 — a `.command` file is opened by whatever LaunchServices has bound to it, and that
  binding is per machine.** Measured with Ghostty installed:
  `open abrir-en-terminal.command` goes to Terminal.app and runs;
  `open -a Ghostty abrir-en-terminal.command` runs **nothing** — Ghostty claims `.command`
  with `CFBundleTypeRole = Editor`, so it just pulls focus to the session already open.
  Nothing written *inside* the script can fix that, because the script never runs. That is
  why the double-click entry is `Iniciar.app`: a bundle cannot be opened *with* another app,
  it is launched. Do not "simplify" it back into a `.command`.
- **R6 — never drive Terminal.app with `osascript` from these launchers.** It needs the
  Automation permission, and without it the call does not fail — it **hangs** waiting on a
  dialog (measured: 19 s and counting, with a dead window on screen). Same trap as R1.
  `Iniciar.app` writes a `.terminal` profile and hands it to `open`, which goes through
  LaunchServices and asks for no permission. Two keys in that profile are load-bearing and
  both were measured: `RunCommandAsShell` (false leaves the window open, because Terminal
  runs the command *inside* a login shell that survives it) and `shellExitAction = 0` (what
  closes the window when the dashboard closes). With `RunCommandAsShell` true the
  `CommandString` is **not** parsed by a shell: `exec`, quotes and spaces in the path all
  stop it from running, hence the trampoline script the launcher writes into `TMPDIR`.
- **R7 — the trampoline's name must include a fingerprint of the app's absolute PATH, and it
  must carry its target inside, quoted.** Both halves fixed a real failure. The folder is
  called `06_simulador` in the main clone *and* in every git worktree, so naming the temp
  files after the folder alone made two checkouts write the **same** file — last one wins.
  Measured on the user's machine: the simulator's trampoline pointed into
  `...-worktrees/simulador-apagado/`, a worktree already deleted; the double click exited 126
  and, because `shellExitAction` closes the window on exit, all you saw was a flash. The
  target used to live in a *second* file so it would not need quoting; that second file is
  exactly the one that went stale. A trampoline is a shell script, so the path fits inside in
  single quotes (escaping any it contains) — verified against a path holding both a quote and
  spaces. And it **checks the target exists before jumping**, printing what is missing and
  waiting: a window that closes on its own error message leaves nothing to read.

## I. Never

- Never modify the notebooks under `notebooks/`. The simulator works on a generated **copy**
  inside its own folder; the others only read theirs.
- Never launch in the foreground, and never report an open dashboard without a `200`.
- Never kill a process on one of these ports that is not one of these apps.
- Never expose the app outside `127.0.0.1`. These dashboards have no authentication.
