---
description: Publica el cuaderno 02 (agrupamiento de circuitos y de vanos) como una Databricks App en una URL fija, detectando y reparando por su cuenta todo lo que falte — si no hay datos en el Volume encadena /subir-datos-databricks, y configura el permiso de lectura de la app sin intervención manual. Pregunta solo el nombre de la app y la URL del workspace destino.
---

Follow this exact sequence when `/app-agrupamiento-circuitos` is invoked. It publishes `notebooks/project_flow/02_uiti_vano_kmeans.ipynb` as a browsable dashboard at a stable URL, and it is **self-healing**: it inspects the target workspace first and creates whatever is missing, so it works against a workspace that has never been touched as well as against one that already has everything.

**Why this is not a Lakeview dashboard.** `/deploy-databricks-dashboard` publishes `circuit_explorer_dashboard.lvdash.json`: SQL datasets plus declarative widgets. `02` is a different animal — it fits K-Means with scikit-learn (8 coordinate spaces, frozen over the full window), builds 23 Plotly traces on the circuit board and 19 on the vano board, and drives them from a hand-written HTML+JS panel (cells 6 and 13). Lakeview executes neither Python nor arbitrary JS, so porting `02` would mean rewriting the analysis and losing the Voronoi partition contours, the marginal KDEs, the violins and the panel. This command therefore uses **Databricks Apps**, which hosts arbitrary Python web servers, and serves the notebook's own HTML verbatim.

**What this command does NOT need.** Verified by reading the notebook: `02` reads exactly one file, `data/Indicadores_vano_v3.csv`, and imports neither `chec_impacto` nor `chec_local_interpreter`. It needs **no** Delta table, **no** view, **no** Lakeview dashboard, **no** shapefile, **no** model checkpoint, and **no** source package. Do not create or check any of those here — if they are absent, that is not this command's problem. `/deploy-databricks-dashboard` owns them.

**Scope.** MUST NOT create or refresh any Delta table or view, MUST NOT touch the Lakeview dashboard, MUST NOT modify the file under `notebooks/project_flow/`, and MUST NOT create any `site`-named path inside the Volume.

## 0. Ask the user for the two required inputs

Ask, one at a time, and wait for each answer:
1. The name for the Databricks App. The API constrains this to **2–30 characters, lowercase alphanumerics and hyphens only**, unique in the workspace. If the answer has spaces, uppercase or accents, propose the normalized form and confirm before continuing (`Agrupamiento Circuitos` → `agrupamiento-circuitos`).
2. The Databricks workspace URL (e.g. `https://dbc-xxxxxxxx-xxxx.cloud.databricks.com`).

If a step below finds a missing prerequisite, **do not ask whether to create it** — creating it is this command's job. Only pause for the two things that genuinely need a human: an expired OAuth token, and a privilege the profile is not allowed to grant.

## 1. Resolve profile and identity

Follow `.claude/commands/deploy-databricks-dashboard.md` **section 1** verbatim with the URL from step 0. Carry the resolved `<profile>` everywhere below.

`databricks auth profiles` reports a `Valid` column, but treat it as advisory only — confirm with a real call, because an expired refresh token surfaces only there:
```
databricks current-user me -p <profile> -o json 2>/dev/null
```

**Never pipe `2>&1` into a JSON parser** anywhere in this command. The CLI intermittently emits `Databricks skills are not installed. To work with Databricks reliably, first run: databricks aitools install` on **stderr**, and merging it into stdout prepends non-JSON text, so `json.load` dies with `Expecting value: line 1 column 1` on a perfectly healthy call (confirmed empirically — it read as an auth failure when the token was fine). Use `2>/dev/null` when parsing, and only `2>&1` when you actually want to read an error message.
- Success → take `userName` as `<userName>` for every Workspace path below.
- `Error: A new access token could not be retrieved because the refresh token is invalid` → stop and ask the user to run this themselves via the `!` prefix (interactive OAuth, cannot be run for them), then resume:
  ```
  databricks auth login --profile <profile>
  ```

Confirm the Apps surface exists (verified present on CLI v1.8.0):
```
databricks apps list -p <profile>
```
If the subcommand does not exist, stop and tell the user to upgrade the Databricks CLI — do not fall back to hand-rolled REST calls.

## 2. Preflight — inspect everything, then repair

Run all of these read-only checks **before** changing anything, and build an explicit list of what is missing. Report that list to the user in one message, then proceed to fix each item without asking.

| # | Check | Command | If missing → |
|---|---|---|---|
| 1 | Volume exists | `databricks fs ls dbfs:/Volumes/workspace/default/chec-simulador -p <profile>` | step 2a |
| 2 | Source CSV present | `databricks fs ls dbfs:/Volumes/workspace/default/chec-simulador/data -p <profile>` | step 2b |
| 3 | Notebook uploaded | `databricks workspace list /Workspace/Users/<userName>/databricks-integration/project_flow -p <profile>` | step 3 |
| 4 | Generated HTML present | `databricks fs ls dbfs:/Volumes/workspace/default/chec-simulador/dashboards -p <profile>` | step 4 |
| 5 | App exists | `databricks apps list -p <profile>` | step 6 |

Steps 3–6 always run anyway (they refresh the notebook, the HTML and the app source), so checks 3–5 exist to report state, not to skip work. Checks 1 and 2 are the ones that gate real branching.

### 2a. Create the Volume if it does not exist

A missing Volume is a hard failure of every later step, and it is cheap to create:
```
databricks api post /api/2.1/unity-catalog/volumes -p <profile> --json '{
  "catalog_name": "workspace",
  "schema_name": "default",
  "name": "chec-simulador",
  "volume_type": "MANAGED",
  "comment": "Datos y artefactos del proyecto CHEC UITI_VANO"
}'
```
If this fails on privileges (the profile lacks `CREATE VOLUME` on `workspace.default`), stop and report exactly that — do not silently pick a different catalog or schema, since every other command in this family hardcodes `workspace.default.chec-simulador`.

### 2b. Delegate the data upload — do not reimplement it

If `Indicadores_vano_v3.csv` is absent from the Volume, **run `/subir-datos-databricks`** against the same workspace URL rather than writing your own `fs cp`. That command is the single source of truth for mirroring `data/`, including the cleanup of `.DS_Store` / `.gitkeep` / `.openmeteo_cache.sqlite` that `databricks fs cp -r` drags along, and the extra `site/data/variables.json` item.

Warn the user before it starts: `data/Indicadores_vano_v3.csv` is **566 MB** (Git-LFS tracked), so this leg dominates the wall-clock of a cold run. Everything else in this command is seconds-to-minutes.

If only that one CSV is missing and the user would rather not mirror the whole `data/` tree, the minimal equivalent is:
```
databricks fs cp data/Indicadores_vano_v3.csv dbfs:/Volumes/workspace/default/chec-simulador/data/Indicadores_vano_v3.csv --overwrite -p <profile>
```
Prefer the delegated command; use this only when the user explicitly asks for the narrow path.

Before either, confirm the local file is a real Git-LFS payload and not an unfetched pointer — a pointer is ~130 bytes and would upload a useless stub:
```
ls -l data/Indicadores_vano_v3.csv
```
If it is tiny, run `git lfs pull` first.

## 3. Stage and upload the shimmed copy of `02`

**Hard invariant**: the modified notebook is a COPY in the scratch directory. `git status --porcelain notebooks/project_flow/` MUST be empty when this step ends.

**Strip every code cell's `outputs` and `execution_count` first.** The repo file is 9.4 MB on disk, almost all of it embedded `text/html` from the last local run; stripped, the staged copy is **0.07 MB** (measured). `databricks workspace import --format JUPYTER` enforces a 10 MB limit, so this is not optional hygiene — it is what keeps the import under the ceiling.

Four edits, everything else byte-identical. Assert each match is unique and fail loudly if not — a silently-skipped edit produces a notebook that fails deep inside the job.

**Edit 1 — cell 1**: uncomment the install line the notebook already ships:
```python
# %pip install pandas numpy scipy scikit-learn plotly
```
→ `%pip install pandas numpy scipy scikit-learn plotly`

Do **not** substitute the repo-wide `requirements.txt` install that `/subir-notebooks-databricks` applies to the 9 `project_flow` notebooks: `02` imports neither local package, so that would pull `torch`/`shap`/`geopandas`/`optuna` for nothing. Keep it as cell index 1 — `%pip install` restarts the interpreter, so no state-bearing cell may precede it.

**Edit 2 — cell 2**: replace the `find_repo_root()` definition **and** its call
```python
REPO_ROOT = find_repo_root()
```
with
```python
REPO_ROOT = Path('/Volumes/workspace/default/chec-simulador')
```
The name is deliberately preserved, so cell 2's and cell 10's `REPO_ROOT / 'data' / 'Indicadores_vano_v3.csv'`, plus cells 7 and 14's `REPO_ROOT / 'reports' / 'interpretability' / 'artifacts'` CSV writes, all keep resolving with zero downstream edits. Leave every import (including the now-unused `from IPython.display import HTML, display`) and every constant untouched.

**Edit 3 — cells 6 and 13**: capture instead of render.
```python
display(HTML(PANEL_HTML + FIGURA_HTML + PANEL_JS))            → BLOQUE_CIRCUITOS = PANEL_HTML + FIGURA_HTML + PANEL_JS
display(HTML(PANEL_VANO_HTML + FIGURA_VANO_HTML + PANEL_VANO_JS)) → BLOQUE_VANOS = PANEL_VANO_HTML + FIGURA_VANO_HTML + PANEL_VANO_JS
```
Cell 6 builds its figure with `include_plotlyjs=True` and cell 13 with `include_plotlyjs=False`, so the concatenation order is load-bearing: reversed, the vano board has no plotly.js.

**Edit 4 — append a final cell** that assembles and writes the document:
```python
from pathlib import Path

SALIDA = Path('/Volumes/workspace/default/chec-simulador/dashboards/agrupamiento_circuitos.html')
SALIDA.parent.mkdir(parents=True, exist_ok=True)

DOCUMENTO = f'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agrupamiento de circuitos y vanos por UITI acumulado</title>
<style>
  body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
         margin: 0; padding: 24px; color: #2b2b2b; background: #fff; }}
  h1 {{ font-size: 20px; margin: 0 0 4px 0; }}
  h2 {{ font-size: 17px; margin: 32px 0 8px 0; }}
  p.meta {{ font-size: 13px; color: #666; margin: 0 0 20px 0; }}
  hr {{ border: 0; border-top: 1px solid #e4c4c0; margin: 36px 0 24px 0; }}
</style>
</head>
<body>
<h1>Agrupamiento de circuitos y vanos por UITI acumulado</h1>
<p class="meta">Generado desde <code>02_uiti_vano_kmeans.ipynb</code> el {pd.Timestamp.now():%Y-%m-%d %H:%M} &mdash;
{len(df):,} eventos, {df["CIRCUITO"].nunique()} circuitos, {len(VANOS):,} vanos,
periodo {df["FECHA"].min():%Y-%m-%d} a {df["FECHA"].max():%Y-%m-%d}.</p>
<h2>Circuitos</h2>
{BLOQUE_CIRCUITOS}
<hr>
<h2>Vanos</h2>
{BLOQUE_VANOS}
</body>
</html>'''

SALIDA.write_text(DOCUMENTO, encoding='utf-8')
print(f'{SALIDA} -> {SALIDA.stat().st_size / 1024 / 1024:.2f} MB')
```

Upload:
```
databricks workspace mkdirs /Workspace/Users/<userName>/databricks-integration/project_flow -p <profile>
databricks workspace import /Workspace/Users/<userName>/databricks-integration/project_flow/02_uiti_vano_kmeans --file <staged_copy> --format JUPYTER --overwrite -p <profile>
```

Then check the invariant. **Scope the hard assertion to `02` itself**, and treat anything else in the folder as informational — the user may well be editing a sibling notebook in Jupyter while this command runs, and a whole-folder check reports that as if this command had caused it (confirmed empirically: a run tripped on ` M 03_uiti_vano_trayectorias_circuitos.ipynb`, which was the user's own concurrent work):
```
test -z "$(git status --porcelain notebooks/project_flow/02_uiti_vano_kmeans.ipynb)" && echo LIMPIO || echo MODIFICADO
git status --porcelain notebooks/project_flow/
```
The first line MUST print `LIMPIO`; if it prints `MODIFICADO`, stop — something wrote to the repo copy. Report any other modified notebook from the second line as an observation, and do not touch it.

Do **not** write the check as `git status --porcelain <path> && echo ok`: `git status` exits 0 whether or not it printed anything, so that form reports success even on a dirty tree.

## 4. Run the notebook once to generate the HTML

```
databricks jobs submit --no-wait --json @<scratch>/job.json -p <profile>
```
with
```json
{
  "run_name": "agrupamiento-circuitos-html",
  "tasks": [{
    "task_key": "build_html",
    "notebook_task": {"notebook_path": "/Workspace/Users/<userName>/databricks-integration/project_flow/02_uiti_vano_kmeans"}
  }]
}
```
No cluster spec — the task runs on serverless. That is fine here: `02` uses no `ipywidgets` (that constraint belongs to `09_simulador`). Poll `databricks jobs get-run <run_id> -p <profile>` until terminal. On failure, surface the notebook's own error rather than retrying blindly.

**Verify the artifact by content, not by exit code.** Expect **~7.4 MB** (measured: 7,793,434 bytes). An earlier estimate of 8.5–9 MB was wrong — it came from summing the notebook's stored outputs, which carry Jupyter's own wrapper around the same HTML. Download it and assert both boards survived:
```
databricks fs cp dbfs:/Volumes/workspace/default/chec-simulador/dashboards/agrupamiento_circuitos.html <scratch>/verif.html --overwrite -p <profile>
```
Then confirm exactly one `id="agrupamiento-circuitos"`, exactly one `id="agrupamiento-vanos"`, the `ag-*` and `va-*` panel controls, and that `Plotly` appears. A size check alone cannot catch a missing second board; a `count()` on those two div ids can.

## 5. Stage the App source

Three files in the scratch directory, deliberately not added to the repo — the App is a thin shell over an artifact the notebook owns, so this command stays its single source of truth.

`app.yaml`:
```yaml
command: ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```
Databricks Apps expects the server on `DATABRICKS_APP_PORT`, default `8000`.

`requirements.txt`:
```
fastapi
uvicorn
databricks-sdk
```

`app.py`:
```python
"""Serves the agrupamiento HTML that 02_uiti_vano_kmeans generates into the Volume.

~7.4 MB, so it is read once and cached in memory rather than re-downloaded per request,
and always sent gzipped. GET /?refresh=1 drops the cache, which is how a re-run of the
notebook job becomes visible without redeploying the app.
"""

import os

from databricks.sdk import WorkspaceClient
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse

RUTA_HTML = os.environ.get(
    "RUTA_HTML",
    "/Volumes/workspace/default/chec-simulador/dashboards/agrupamiento_circuitos.html",
)

app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=1000)

_cache = {}


def _cargar():
    # files.download goes through the Unity Catalog Files API, which works from an app's
    # service principal. Do not assume /Volumes is FUSE-mounted inside the app container.
    w = WorkspaceClient()
    return w.files.download(RUTA_HTML).contents.read().decode("utf-8")


@app.get("/salud", response_class=PlainTextResponse)
def salud():
    # Deliberately does NOT touch the Volume: it separates "app is broken" from
    # "the Volume grant is missing", which otherwise look identical from a browser.
    return "ok"


@app.get("/", response_class=HTMLResponse)
def raiz(refresh: int = 0):
    if refresh or "html" not in _cache:
        _cache["html"] = _cargar()
    return HTMLResponse(_cache["html"])
```

Upload with `--format RAW` (verified: all three land as `FILE`, not `NOTEBOOK`). `import-dir` is avoided — it has no exclude mechanism and reinterprets `.py` as notebooks:
```
databricks workspace mkdirs /Workspace/Users/<userName>/databricks-integration/apps/<app-name> -p <profile>
databricks workspace import <base>/app.py           --file <scratch>/app.py           --format RAW --language PYTHON --overwrite -p <profile>
databricks workspace import <base>/app.yaml         --file <scratch>/app.yaml         --format RAW --overwrite -p <profile>
databricks workspace import <base>/requirements.txt --file <scratch>/requirements.txt --format RAW --overwrite -p <profile>
```

## 6. Create the App, declaring the Volume as a resource

This is the step that makes the deploy hands-off. Create the app with a `uc_securable` resource so **Databricks applies the volume grant itself** instead of leaving a manual `GRANT` behind:
```
databricks apps create --json '{
  "name": "<app-name>",
  "description": "Agrupamiento de circuitos y vanos por UITI acumulado (cuaderno 02)",
  "resources": [{
    "name": "volumen-chec-simulador",
    "description": "Volume con el HTML generado por el cuaderno 02",
    "uc_securable": {
      "securable_type": "VOLUME",
      "securable_full_name": "workspace.default.chec-simulador",
      "permission": "READ_VOLUME"
    }
  }]
}' -p <profile>
```
`uc_securable` is a documented app resource type alongside `secret`, `job`, `sql_warehouse` and `serving_endpoint`.

**This works — confirmed empirically on a cold workspace.** The API echoes the resource back in the create response, and immediately afterwards `SHOW GRANTS <sp_client_id> ON VOLUME workspace.default.\`chec-simulador\`` returns exactly one row, `READ VOLUME`, **without any `GRANT` ever being issued**. Databricks applies it as part of provisioning the app's service principal. Always verify it landed rather than assuming:
```
databricks api post /api/2.0/sql/statements -p <profile> --json '{"warehouse_id":"<warehouse_id>","statement":"SHOW GRANTS `<sp_client_id>` ON VOLUME workspace.default.`chec-simulador`","wait_timeout":"30s"}'
```
Note the service principal is new on every app re-creation, so a grant left over from a previous app of the same name is worthless — read `service_principal_client_id` from this app's `apps get`.

If the app already exists, do not fail — attach the same resource to it instead, via `databricks apps update <app-name> --json '<same body without name>'`.

### 6a. Fallback — the manual grant

Only if the `uc_securable` route fails (the API rejects the body, or the `SHOW GRANTS` check above comes back empty), fall back to granting explicitly. **Measure first; do not blind-fire three grants.** On a workspace where the app's service principal already belongs to the all-users group, `USE CATALOG` and `USE SCHEMA` are inherited and only `READ VOLUME` is genuinely missing (confirmed empirically: 1 row on the catalog, 6 on the schema, 0 on the volume).

Get `service_principal_client_id` from `databricks apps get <app-name> -o json -p <profile>`, resolve a warehouse per `deploy-databricks-dashboard` section 2, then check each object:
```
databricks api post /api/2.0/sql/statements -p <profile> --json '{"warehouse_id":"<warehouse_id>","statement":"SHOW GRANTS `<sp_client_id>` ON VOLUME workspace.default.`chec-simulador`","wait_timeout":"30s"}'
```
Wrap the whole JSON payload in **single** quotes. Escaping the backticked identifiers inside a double-quoted string breaks in zsh and returns non-JSON, which then fails to parse downstream.

For each privilege actually missing, issue the matching `GRANT ... TO \`<sp_client_id>\``.

**Expect the assistant to be blocked here.** Claude Code's auto-mode classifier denies `GRANT` statements issued through `databricks api post`, while allowing `SHOW GRANTS`. When that happens, do not attempt a workaround — hand the exact command to the user to run with the `!` prefix, and verify afterwards with `SHOW GRANTS` that the row count went from 0 to 1. The Catalog Explorer path (`Catalog` → `workspace` → `default` → `Volumes` → `chec-simulador` → `Permissions` → `Grant`, principal shown as `app-xxxxx <app-name>`) is an equivalent manual route.

## 7. Deploy

**Wait for the app's compute to reach `ACTIVE` first.** Deploying against a still-provisioning app fails hard (confirmed empirically: `Error: Cannot deploy app <name> as it is not in RUNNING state. Please start the app first.`). A fresh `apps create` took ~5 polls at 20 s to go from `STARTING` to `ACTIVE`:
```
for i in $(seq 1 30); do
  ST=$(databricks apps get <app-name> -p <profile> -o json | python3 -c "import json,sys; print((json.load(sys.stdin).get('compute_status') or {}).get('state'))")
  echo "[$i] compute=$ST"; [ "$ST" = "ACTIVE" ] && break; command sleep 20
done
```
Use `command sleep` — a bare `sleep` in the foreground is blocked in this harness. Then:
```
databricks apps deploy <app-name> --source-code-path /Workspace/Users/<userName>/databricks-integration/apps/<app-name> -p <profile>
```
Waits for `SUCCEEDED` and reports `mode: SNAPSHOT` plus `"App started successfully"`. On anything else, pull `databricks apps logs <app-name> -p <profile>` before touching anything.

## 8. Verify and report back

```
databricks apps get <app-name> -o json -p <profile>
```
Require all three: `compute_status: ACTIVE`, `app_status: RUNNING`, `active_deployment.status: SUCCEEDED`. Capture `url` verbatim — this is the one command in the family where the CLI hands you a real URL, so never fabricate one.

Tell the user, in their language:
- The app URL, the app name, and the profile/workspace used.
- **Everything the preflight found missing and what was done about it** — this is the headline of a cold run.
- That the HTML lives at `/Volumes/workspace/default/chec-simulador/dashboards/agrupamiento_circuitos.html`, its measured size, and the two div ids that were verified present.
- Whether the volume permission came from the `uc_securable` resource or from a manual grant.
- **How to refresh**: re-run step 4's job, then hit `/?refresh=1`. No redeploy — the app carries no data.
- That the first page load is slow (~7.4 MB gzipped from the Volume) and every later one is cached.
- That `/salud` answers without touching the Volume, so it distinguishes an app failure from a permission failure.
- That the two label CSVs also landed under `.../chec-simulador/reports/interpretability/artifacts/` as a side effect of cells 7 and 14.
- That `git status --porcelain notebooks/project_flow/` was empty — the repo notebook was never modified.
- That no Delta table, view or Lakeview dashboard was created or touched; point to `/deploy-databricks-dashboard` if those are wanted.
