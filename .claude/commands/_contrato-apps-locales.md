---
description: Shared contract for the local desktop apps (`/app-local-*`) — preflight, background launch, fixed ports, and how to stop them. Not invocable on its own.
---

> **Not a command.** `/app-local-clima`, `/app-local-agrupamiento-circuitos` and
> `/app-local-simulador` all read this file first. It holds everything they share, so
> the three cannot drift apart.

Every `/app-local-*` command opens one of the local dashboards built in
`notebooks/project_flow/aplicaciones/`. Each app already has its own launchers
(`iniciar.command` / `iniciar.bat`) for double-clicking from Finder or Explorer; these
commands exist to do the same from the session, with the preflight and the diagnosis
that a double-click cannot give.

## A. Fixed port per app — never pick a free one

| command | app folder | port |
|---|---|---|
| `/app-local-clima` | `01_clima` | **8801** |
| `/app-local-agrupamiento-circuitos` | `02_agrupamiento_vanos` | **8802** |
| `/app-local-simulador` | `06_simulador` | **8866** |

The apps themselves pick a free port when launched by double-click, which is right for
that path — but here a fixed port is what makes the URL stable across sessions and what
turns "is it already running?" into a single check. Always pass `--puerto <port>`.

## B. If it is already running, do not start a second one

Before anything else:

```
lsof -nP -iTCP:<port> -sTCP:LISTEN
```

If something is listening, confirm it is this app and not an unrelated process:

```
ps -p <pid> -o command= | head -1
```

- The command line contains `aplicaciones/<app folder>/app.py` → **it is already
  running.** Report `http://127.0.0.1:<port>/`, re-open the browser with
  `/usr/bin/open http://127.0.0.1:<port>/`, and stop. Do not relaunch, do not rebuild.
- It is something else → tell the user which process owns the port and stop. Do not
  kill a process you did not start.

## C. Preflight — inspect, then repair without asking

Creating what is missing is this command's job. Do not ask permission for any of it;
only report what you had to do.

| # | check | if missing |
|---|---|---|
| 1 | `python3 --version` is 3.10+ | stop and say how to install it (macOS `brew install python@3.11`) |
| 2 | `<app>/.venv/bin/python` exists | run step D1 |
| 3 | the app's build output exists (see the command's own file) | run step D2 |
| 4 | `data/Indicadores_vano_v3.csv` is over 1 MB | it is an unfetched Git-LFS pointer: run `git lfs pull` |

Check 4 only matters when something has to be **built**. A dashboard already built never
reads `data/` again — say so rather than blocking on it.

### D1. Install the environment

```
cd notebooks/project_flow/aplicaciones/<app folder> && python3 ../_comun/gestor.py instalar
```

Takes minutes and downloads hundreds of MB (1,6 GB for the simulator). Tell the user
this is happening **before** starting it, then run it in the foreground so its progress
is visible.

### D2. Build

`iniciar` builds by itself when something is missing, so there is no separate step to
run — but the wait is long enough that it must be announced, with the number from the
command's own file, before launching.

## E. Launch in the background, never in the foreground

The server blocks until `Ctrl+C`. Running it in the foreground would freeze the
session, so always launch it in the background, redirecting output to a log:

```
cd notebooks/project_flow/aplicaciones/<app folder> && \
  PYTHONUNBUFFERED=1 python3 ../_comun/gestor.py iniciar --puerto <port> > /tmp/app-local-<app>.log 2>&1
```

`PYTHONUNBUFFERED=1` is not optional: without it Python block-buffers stdout when it is
not a terminal, and the log stays empty — including the line with the URL and any error.

Then poll until the port answers, up to the timeout in the command's own file:

```
curl -s -o /dev/null -m 5 -w '%{http_code}' http://127.0.0.1:<port>/
```

- Answers `200` → done. Report the URL.
- The process died → **read the log and report the real error.** Never report a
  dashboard as open without having received a `200` from it.

## F. Report back

Give the user, in their language and in this order:

1. The URL, on its own line.
2. Whether the browser was opened automatically. The app does it itself with
   `/usr/bin/open`; if the log says it could not, say so and give the URL to paste.
3. Anything that had to be installed or built, and how long it took.
4. **How to stop it** — the app was launched detached, so `Ctrl+C` does not apply here:
   ```
   lsof -ti tcp:<port> -sTCP:LISTEN | xargs kill
   ```
   **`-sTCP:LISTEN` is not optional.** Without it, `lsof -ti tcp:<port>` also returns the
   browser, which holds an established connection to that same port — measured: the port
   answered with the server's pid *and* Chrome's. Piping that into `kill` closes the
   user's browser and leaves the server running, which is the exact opposite of the
   intent. The same filter belongs in every `lsof` in this contract.

## G. Restrictions already met in the field

Do not re-diagnose these.

- **R1 — `webbrowser` does not work on macOS from a launcher.** It resolves to
  `MacOSXOSAScript`, which talks to the browser over Apple Events and needs the
  Automation permission; without it, it fails silently. The apps use `/usr/bin/open`.
  Never "fix" a browser that does not open by going back to `webbrowser`.
- **R2 — `index.html` cannot be opened by double-click.** The data is fetched
  separately and browsers block that over `file://`. It has to be served. The page says
  so on screen if someone tries.
- **R3 — the simulator needs `ipykernel` in its environment** even though no cell
  imports it. Without it Voila falls back to the first user-level kernelspec it finds —
  which may point at another project's interpreter, or a deleted one — and answers 500.
  Its `requirements.txt` already carries it, and the app registers its own kernel
  (`chec-simulador-vano`) with `--sys-prefix`.
- **R4 — the first request to the simulator is instant, the second is not.** It keeps
  one pre-executed kernel waiting: the first page load answers in 4 ms and the next one
  takes ~6 s while a new kernel starts. That is expected, not a fault.

## H. Never

- Never modify the notebooks under `notebooks/project_flow/`. The simulator works on a
  patched **copy** inside its own folder; the other two only read theirs.
- Never launch in the foreground, and never report an open dashboard without a `200`.
- Never kill a process on the port that is not one of these apps.
- Never expose the app outside `127.0.0.1`. These dashboards have no authentication.
