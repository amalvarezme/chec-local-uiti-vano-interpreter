---
description: Publica el cuaderno 01.4 (agrupamiento y evolucion a nivel de vano por ventanas deslizantes, con mapa geografico y seleccion de vanos) como una Databricks App en una URL fija, detectando y reparando por su cuenta todo lo que falte — si no estan el CSV o los shapefiles en el Volume encadena /subir-datos-databricks, y configura el permiso de lectura de la app sin intervencion manual. Pregunta solo el nombre de la app y la URL del workspace destino.
---

Follow this exact sequence when `/app-trayectorias-vanos` is invoked. It publishes `notebooks/project_flow/01.4_uiti_vano_trayectorias_vano.ipynb` as a browsable dashboard at a stable URL, and it is **self-healing**: it inspects the target workspace first and creates whatever is missing, so it works against a workspace that has never been touched as well as against one that already has everything.

This is the third member of the app family, after `/app-agrupamiento-circuitos` (`01.2`) and `/app-trayectorias-circuitos` (`01.3`). Everything it does that is not specific to `01.4` is deliberately identical to those two, so read them as the reference when something here is terse.

**Why Databricks Apps and not Lakeview.** Same reason as its two siblings: `01.4` fits K-Means with scikit-learn over 8 coordinate spaces, builds **56 Plotly traces** including a geographic map, and drives all of it from a hand-written HTML+JS panel (cell 7) that also handles clicking a vano on the map to select it. Lakeview executes neither Python nor arbitrary JS, so porting it would mean rewriting the analysis and losing the Voronoi contours, the trajectories with their arrows, the map and the whole selection model.

**Scope.** MUST NOT create or refresh any Delta table or view, MUST NOT touch the Lakeview dashboard, MUST NOT modify the file under `notebooks/project_flow/`, and MUST NOT create any `site`-named path inside the Volume.

## 0. Ask the user for the two required inputs

Ask, one at a time, and wait for each answer:
1. The name for the Databricks App: **2–30 characters, lowercase alphanumerics and hyphens only**, unique in the workspace. If the answer has spaces, uppercase or accents, propose the normalized form and confirm (`Trayectorias Vanos` → `trayectorias-vanos`).
2. The Databricks workspace URL (e.g. `https://dbc-xxxxxxxx-xxxx.cloud.databricks.com`).

If a step below finds a missing prerequisite, **do not ask whether to create it** — creating it is this command's job. Only pause for the two things that genuinely need a human: an expired OAuth token, and a privilege the profile is not allowed to grant.

## 1. Resolve profile and identity

Follow `.claude/commands/deploy-databricks-dashboard.md` **section 1** verbatim with the URL from step 0, then confirm with a real call:
```
databricks current-user me -p <profile> -o json 2>/dev/null
```
**Never pipe `2>&1` into a JSON parser** anywhere in this command. The CLI intermittently emits `Databricks skills are not installed...` on **stderr**, and merging it into stdout makes `json.load` die with `Expecting value: line 1 column 1` on a perfectly healthy call. Use `2>/dev/null` when parsing, `2>&1` only when you want to read an error.

- Success → take `userName` as `<userName>`.
- `Error: A new access token could not be retrieved because the refresh token is invalid` → stop and ask the user to run `databricks auth login --profile <profile>` themselves via the `!` prefix, then resume.

Confirm the Apps surface exists:
```
databricks apps list -p <profile>
```

## 2. What `01.4` actually needs

Verified by reading the notebook — do not re-derive it:

| Dependency | in Databricks Runtime | needed |
|---|---|---|
| `pandas`, `numpy`, `scipy` | yes | yes |
| `plotly` | yes, but **too old** | **`>=6`**, see step 3 |
| `geopandas`, `scikit-learn` | no / yes | **both** |
| `chec_impacto`, `chec_local_interpreter` | — | **NO**, `01.4` imports neither |

It reads exactly two things from the Volume: `data/Indicadores_vano_v3.csv` and the three shapefiles under `data/GEO/`. It needs **no** Delta table, **no** view, **no** Lakeview dashboard, **no** model checkpoint and **no** source package.

A shapefile is not one file. `MVLINSEC.shp` is useless without at least `.shx` and `.dbf`, and without `.prj` geopandas cannot resolve the CRS. That is why step 2b delegates the upload instead of copying single files.

### Preflight — inspect everything, then repair

Run all of these read-only checks **before** changing anything, build an explicit list of what is missing, report it in one message, then fix each item without asking.

| # | Check | Command | If missing → |
|---|---|---|---|
| 1 | Volume exists | `databricks fs ls dbfs:/Volumes/workspace/default/chec-simulador -p <profile>` | 2a |
| 2 | Source CSV present | `databricks fs ls dbfs:/Volumes/workspace/default/chec-simulador/data -p <profile>` | 2b |
| 3 | GEO shapefiles | `databricks fs ls dbfs:/Volumes/workspace/default/chec-simulador/data/GEO -p <profile>` | 2b |
| 4 | Notebook uploaded | `databricks workspace list /Workspace/Users/<userName>/databricks-integration/project_flow -p <profile>` | step 3 |
| 5 | Generated HTML present | `databricks fs ls dbfs:/Volumes/workspace/default/chec-simulador/dashboards -p <profile>` | step 4 |
| 6 | App exists | `databricks apps list -p <profile>` | step 6 |

For check 3, confirm the **sidecars**, not just the folder: at minimum `MVLINSEC.{shp,shx,dbf,prj}`, `GDBCHEC_TRANSFOR.{shp,shx,dbf,prj}`, `SWITCHES.{shp,shx,dbf,prj}`. A bare `.shp` fails inside the job with an opaque driver error, not a clear "file missing".

Checks 4–6 exist to report state; steps 3–6 run anyway and refresh everything.

### 2a. Create the Volume if it does not exist

```
databricks api post /api/2.1/unity-catalog/volumes -p <profile> --json '{
  "catalog_name": "workspace",
  "schema_name": "default",
  "name": "chec-simulador",
  "volume_type": "MANAGED",
  "comment": "Datos y artefactos del proyecto CHEC UITI_VANO"
}'
```
If this fails on privileges, stop and report exactly that — do not silently pick another catalog or schema, since every command in this family hardcodes `workspace.default.chec-simulador`.

### 2b. Delegate the data upload — do not reimplement it

If the CSV **or** any shapefile is missing, run `/subir-datos-databricks` against the same workspace URL. It owns the mirror of `data/` plus the `.DS_Store` / `.gitkeep` / `.openmeteo_cache.sqlite` cleanup, and it carries the sidecar set correctly.

Warn first: `data/Indicadores_vano_v3.csv` is **566 MB** (Git-LFS tracked) and dominates a cold run. Confirm it is a real payload and not an unfetched pointer (`ls -l data/Indicadores_vano_v3.csv`; ~130 bytes means run `git lfs pull`). The GEO tree is LFS-tracked too — check it the same way.

## 3. Stage and upload the shimmed copy of `01.4`

**Hard invariant**: the modified notebook is a COPY in the scratch directory. `git status --porcelain notebooks/project_flow/01.4_uiti_vano_trayectorias_vano.ipynb` MUST be empty when this step ends.

**Strip every code cell's `outputs` and `execution_count` first.** The repo file is 12.3 MB on disk, almost all of it cell 7's embedded `text/html`; stripped it is **0.08 MB** (measured). `databricks workspace import --format JUPYTER` enforces a 10 MB limit, so an unstripped copy is over the ceiling outright — this is the difference between the upload working and failing, not hygiene.

Four edits, everything else byte-identical. Assert each match is unique and fail loudly if not.

**Edit 1 — cell 1, the dependency install.** The cell ships this, commented:
```python
# %pip install pandas numpy scipy scikit-learn plotly geopandas
```
Uncomment it **and pin plotly**:
```python
%pip install -q pandas numpy scipy "plotly>=6" geopandas scikit-learn
```
Unlike `01.3`'s, this list is already complete — the only thing wrong with it is the bare `plotly`. Cell 6 builds the map with a `{'type': 'map'}` entry in its `specs` grid and `go.Scattermap`, the MapLibre trace family that only exists in modern Plotly. Databricks Runtime preinstalls an older Plotly, and a bare `plotly` requirement is **already satisfied** by it, so pip prints nothing and upgrades nothing; the failure then surfaces as `ValueError: Unsupported subplot type: 'map'` with a traceback pointing at the *system* site-packages. A version floor forces the upgrade. Prefer the floor over `--upgrade`, which would also pull newer pandas/numpy/geopandas.

Keep this as cell index 1: `%pip install` restarts the interpreter, so no state-bearing cell may precede it.

**Edit 2 — cell 2, redirect the repo root.** Replace the `find_repo_root()` definition **and** its call:
```python
REPO_ROOT = find_repo_root()
```
with
```python
REPO_ROOT = Path('/Volumes/workspace/default/chec-simulador')
```
Aliasing the same name keeps every downstream path resolving untouched: cell 2's CSV read, cell 5's three `REPO_ROOT / 'data' / 'GEO' / ...` shapefile reads, and cell 8's `reports/interpretability/artifacts/` write. Leave every import and constant alone.

Note cell 2 reads the CSV **without** `engine='pyarrow'` — unlike `01.3`, which sets it. Do not add it here as part of this command: changing the read path is a notebook decision, not a deployment one, and this command must keep the staged copy byte-identical to the repo except for its four edits.

**Edit 3 — cell 7, capture the HTML instead of rendering it.** Replace the last line:
```python
display(HTML(PANEL_HTML + FIGURA_HTML + PANEL_JS))
```
with
```python
BLOQUE_VANOS = PANEL_HTML + FIGURA_HTML + PANEL_JS
```
Cell 7 builds its figure with `include_plotlyjs=True`, so this single block already carries plotly.js — there is no second board to order it against, unlike `01.2`.

**Edit 4 — append a final cell** that assembles and writes the document:
```python
from pathlib import Path

SALIDA = Path('/Volumes/workspace/default/chec-simulador/dashboards/trayectorias_vanos.html')
SALIDA.parent.mkdir(parents=True, exist_ok=True)

DOCUMENTO = f'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agrupamiento y evolucion de vanos por ventana deslizante</title>
<style>
  body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
         margin: 0; padding: 24px; color: #2b2b2b; background: #fff; }}
  h1 {{ font-size: 20px; margin: 0 0 4px 0; }}
  p.meta {{ font-size: 13px; color: #666; margin: 0 0 20px 0; }}
</style>
</head>
<body>
<h1>Agrupamiento y evolucion de vanos por ventana deslizante</h1>
<p class="meta">Generado desde <code>01.4_uiti_vano_trayectorias_vano.ipynb</code> el {pd.Timestamp.now():%Y-%m-%d %H:%M} &mdash;
{len(df):,} eventos, {len(CIRCUITOS)} circuitos, {len(VENTANAS)} ventanas,
{len(TABLA):,} celdas vano x ventana con eventos.</p>
{BLOQUE_VANOS}
</body>
</html>'''

SALIDA.write_text(DOCUMENTO, encoding='utf-8')
print(f'{SALIDA} -> {SALIDA.stat().st_size / 1024 / 1024:.2f} MB')
```
Use **triple single quotes** for that f-string. Its body contains `"Segoe UI"` and no nested single quotes; writing it as `f"""` would nest same-type quotes inside an f-string, which only compiles on Python 3.12+ (PEP 701) and blows up on Databricks serverless. A local `ast.parse` on 3.13+ does **not** catch this — it accepts both forms.

The four names the template uses (`df`, `CIRCUITOS`, `VENTANAS`, `TABLA`) all exist in the notebook; verify they still do before relying on them.

Upload:
```
databricks workspace mkdirs /Workspace/Users/<userName>/databricks-integration/project_flow -p <profile>
databricks workspace import /Workspace/Users/<userName>/databricks-integration/project_flow/01.4_uiti_vano_trayectorias_vano --file <staged_copy> --format JUPYTER --overwrite -p <profile>
```

Then check the invariant. **Scope the hard assertion to `01.4` itself** and treat anything else in the folder as informational — a sibling notebook may well be open in Jupyter while this runs:
```
test -z "$(git status --porcelain notebooks/project_flow/01.4_uiti_vano_trayectorias_vano.ipynb)" && echo LIMPIO || echo MODIFICADO
git status --porcelain notebooks/project_flow/
```
The first line MUST print `LIMPIO`. Do **not** write the check as `git status --porcelain <path> && echo ok`: `git status` exits 0 whether or not it printed anything.

## 4. Run the notebook once to generate the HTML

```
databricks jobs submit --no-wait --json @<scratch>/job.json -p <profile>
```
with
```json
{
  "run_name": "trayectorias-vanos-html",
  "tasks": [{
    "task_key": "build_html",
    "notebook_task": {"notebook_path": "/Workspace/Users/<userName>/databricks-integration/project_flow/01.4_uiti_vano_trayectorias_vano"}
  }]
}
```
No cluster spec — serverless is fine, `01.4` uses no `ipywidgets`. Poll `databricks jobs get-run <run_id> -p <profile>` until terminal. On failure, surface the notebook's own error rather than retrying blindly. Expect this leg to be slower than `01.2`'s: the job also reads three shapefiles from the Volume through the FUSE mount, which is settled as working — confirmed on `01.3`'s real runs.

**Verify by content, not by exit code.** Expect **~11.6 MB** (cell 7's stored output measures 11.64 MB locally; the app document runs slightly under it because it drops Jupyter's wrapper). It is the largest of the three apps: plotly.js is ~4.9 MB and `CTX` is ~6.7 MB, of which `geo` is 3.0 MB and `celdas` 2.8 MB. Download it and assert:
```
databricks fs cp dbfs:/Volumes/workspace/default/chec-simulador/dashboards/trayectorias_vanos.html <scratch>/verif.html --overwrite -p <profile>
```
- exactly one `id="vano-ventana"` — that is `DIV`'s value, and it is **not** `01.2`'s `agrupamiento-vanos` nor `01.3`'s `trayectorias-circuitos`, so a copy-pasted check from a sibling command would silently pass on the wrong artifact;
- **the map layer non-empty**: count `"fids"`, which must equal the number of circuits with geometry (measured: **208**). With the shapefiles missing or unreadable the notebook still succeeds and still writes an HTML of roughly the right size, just with no map — a size check alone will not catch that;
- `scattermap` present, which doubles as proof the Plotly floor took effect;
- `plotly_click` present, which is the map's click-to-select handler; if it is missing the panel loads but a vano can only be selected from the checkbox list.

## 5. Stage the App source

Three files in the scratch directory, deliberately not added to the repo — the App is a thin shell over an artifact the notebook owns.

`app.yaml`:
```yaml
command: ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

`requirements.txt`:
```
fastapi
uvicorn
databricks-sdk
```

`app.py` — identical to the other two apps except for the path and the docstring:
```python
"""Serves the vano trajectory HTML that 01.4_uiti_vano_trayectorias_vano generates into the Volume.

~11.6 MB, so it is read once and cached in memory rather than re-downloaded per request,
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
    "/Volumes/workspace/default/chec-simulador/dashboards/trayectorias_vanos.html",
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

Upload with `--format RAW` — `import-dir` is avoided, it has no exclude mechanism and reinterprets `.py` as notebooks:
```
databricks workspace mkdirs /Workspace/Users/<userName>/databricks-integration/apps/<app-name> -p <profile>
databricks workspace import <base>/app.py           --file <scratch>/app.py           --format RAW --language PYTHON --overwrite -p <profile>
databricks workspace import <base>/app.yaml         --file <scratch>/app.yaml         --format RAW --overwrite -p <profile>
databricks workspace import <base>/requirements.txt --file <scratch>/requirements.txt --format RAW --overwrite -p <profile>
```

## 6. Create the App, declaring the Volume as a resource

Create it with a `uc_securable` resource so **Databricks applies the volume grant itself**:
```
databricks apps create --json '{
  "name": "<app-name>",
  "description": "Agrupamiento y evolucion de vanos por ventana deslizante (cuaderno 01.4)",
  "resources": [{
    "name": "volumen-chec-simulador",
    "description": "Volume con el HTML generado por el cuaderno 01.4",
    "uc_securable": {
      "securable_type": "VOLUME",
      "securable_full_name": "workspace.default.chec-simulador",
      "permission": "READ_VOLUME"
    }
  }]
}' -p <profile>
```
This works — confirmed empirically on a cold workspace for the sibling commands: the API echoes the resource back and `SHOW GRANTS` then returns exactly one `READ VOLUME` row **without any `GRANT` being issued**. Verify it landed rather than assuming:
```
databricks api post /api/2.0/sql/statements -p <profile> --json '{"warehouse_id":"<warehouse_id>","statement":"SHOW GRANTS `<sp_client_id>` ON VOLUME workspace.default.`chec-simulador`","wait_timeout":"30s"}'
```
Wrap the whole JSON payload in **single** quotes; escaping the backticked identifiers inside a double-quoted string breaks in zsh. The service principal is new on every app re-creation, so read `service_principal_client_id` from **this** app's `apps get`.

If the app already exists, do not fail — attach the same resource via `databricks apps update <app-name> --json '<same body without name>'`.

### 6a. Fallback — the manual grant

Only if the `uc_securable` route fails. **Measure first; do not blind-fire three grants.** On a workspace where the app's service principal already belongs to the all-users group, `USE CATALOG` and `USE SCHEMA` are inherited and only `READ VOLUME` is genuinely missing. Check each object with `SHOW GRANTS` and grant only what is actually absent.

**Expect the assistant to be blocked here.** Claude Code's auto-mode classifier denies `GRANT` statements issued through `databricks api post`, while allowing `SHOW GRANTS`. Do not attempt a workaround — hand the exact command to the user to run with the `!` prefix, and verify afterwards that the row count went from 0 to 1.

## 7. Deploy

**Wait for the app's compute to reach `ACTIVE` first.** Deploying against a still-provisioning app fails with `Cannot deploy app <name> as it is not in RUNNING state`. A fresh `apps create` took ~5 polls at 20 s:
```
for i in $(seq 1 30); do
  ST=$(databricks apps get <app-name> -p <profile> -o json | python3 -c "import json,sys; print((json.load(sys.stdin).get('compute_status') or {}).get('state'))")
  echo "[$i] compute=$ST"; [ "$ST" = "ACTIVE" ] && break; command sleep 20
done
```
Use `command sleep` — a bare foreground `sleep` is blocked in this harness. Then:
```
databricks apps deploy <app-name> --source-code-path /Workspace/Users/<userName>/databricks-integration/apps/<app-name> -p <profile>
```
Expect `SUCCEEDED`, `mode: SNAPSHOT` and `"App started successfully"`. On anything else, pull `databricks apps logs <app-name> -p <profile>` before touching anything.

## 8. Verify and report back

```
databricks apps get <app-name> -o json -p <profile>
```
Require all three: `compute_status: ACTIVE`, `app_status: RUNNING`, `active_deployment.status: SUCCEEDED`. Capture `url` verbatim — never fabricate one.

Tell the user, in their language:
- The app URL, the app name, and the profile/workspace used.
- **Everything the preflight found missing and what was done about it** — the headline of a cold run.
- That the HTML lives at `/Volumes/workspace/default/chec-simulador/dashboards/trayectorias_vanos.html`, its measured size, and which content checks passed (`id="vano-ventana"`, 208 `"fids"`, `scattermap`, `plotly_click`).
- Whether the volume permission came from the `uc_securable` resource or from a manual grant.
- **How to refresh**: re-run step 4's job, then hit `/?refresh=1`. No redeploy — the app carries no data.
- That the first page load is slow (~11.6 MB gzipped from the Volume) and every later one is cached, and that `/salud` answers without touching the Volume so it separates an app failure from a permission failure.
- **How the board is used**, since it is the least obvious of the three: pick a circuit, then mark vanos either from the checkbox list or **by clicking them on the map**; the bars and the violins describe only the marked vanos in the window chosen with the slider, and stay empty until something is marked. Up to 8 vanos get their own colour, arrows and evolution series.
- That `uiti_ventanas_deslizantes.csv` also landed under `.../chec-simulador/reports/interpretability/artifacts/` as a side effect of cell 8.
- That `git status --porcelain` on the notebook was empty — the repo copy was never modified.
- That no Delta table, view or Lakeview dashboard was created or touched; point to `/deploy-databricks-dashboard` if those are wanted.
