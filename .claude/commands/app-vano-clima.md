---
description: Publica el cuaderno 01 (nube por vano sobre el mapa, con las 6 variables seleccionables, la serie de tiempo de doble eje y los 6 violines) como una Databricks App en una URL fija, detectando y reparando por su cuenta todo lo que falte — si no estan el CSV o los shapefiles en el Volume encadena /subir-datos-databricks, y configura el permiso de lectura de la app sin intervencion manual. Pregunta solo el nombre de la app y la URL del workspace destino.
---

> **Read `.claude/commands/_contrato-despliegue-databricks.md` before anything else.** It is mandatory and it overrides what follows:
> - **A. Run log** — open the bitacora *before* asking the user anything, record every numbered step as you finish it, and always close it. Its path and final state are part of the report back to the user.
> - **B. Never abort** — a restriction gets recorded and worked around; the command runs to the end regardless. Wherever this file says "stop and report", rule B applies instead.
> - **C. Unity Catalog target** — `workspace.default.chec-simulador` below is a default, not a requirement. Resolve it at runtime and substitute the resolved value into every path here.
> - **D. Known restrictions** — D1–D9. If one shows up, do not re-diagnose it.

Follow this exact sequence when `/app-vano-clima` is invoked. It publishes `notebooks/old_version/01_uiti_vano_clima.ipynb` as a browsable dashboard at a stable URL, and it is **self-healing**: it inspects the target workspace first and creates whatever is missing, so it works against a workspace that has never been touched as well as against one that already has everything.

This is the fourth member of the app family, after `/app-agrupamiento-vanos-circuitos` (`02`), `/app-trayectorias-circuitos` (`03`) and `/app-trayectorias-vanos` (`04`). Everything it does that is not specific to `01` is deliberately identical to those three, so read them as the reference when something here is terse.

**Why Databricks Apps and not Lakeview.** Same reason as its three siblings: `01` builds **16 Plotly traces** in a 4x3 grid — a geographic map as a 2x2 block, a dual-axis time series and six violins — and drives all of it from a hand-written HTML+JS panel (cell 9) that swaps between every circuit in the base (208 today), 6 variables and 25 hourly lags entirely in the browser. Lakeview executes neither Python nor arbitrary JS.

**Scope.** MUST NOT create or refresh any Delta table or view, MUST NOT touch the Lakeview dashboard, MUST NOT modify the file under `notebooks/`, and MUST NOT create any `site`-named path inside the Volume.

## 0. Ask the user for the two required inputs

Ask, one at a time, and wait for each answer:
1. The name for the Databricks App: **2–30 characters, lowercase alphanumerics and hyphens only**, unique in the workspace. If the answer has spaces, uppercase or accents, propose the normalized form and confirm (`Vano Clima` → `vano-clima`).
2. The Databricks workspace URL (e.g. `https://dbc-xxxxxxxx-xxxx.cloud.databricks.com`).

If a step below finds a missing prerequisite, **do not ask whether to create it** — creating it is this command's job. Only pause for the two things that genuinely need a human: an expired OAuth token, and a privilege the profile is not allowed to grant.

## 1. Resolve profile and identity

Follow `.claude/commands/_contrato-despliegue-databricks.md` **section E1** verbatim with the URL from step 0, then confirm with a real call:
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

## 2. What `01` actually needs

Verified by reading the notebook — do not re-derive it:

| Dependency | in Databricks Runtime | needed |
|---|---|---|
| `pandas`, `numpy` | yes | yes |
| `plotly` | yes, but **too old** | **`>=6`**, see step 3 |
| `geopandas` | no | **yes** |
| `scipy`, `scikit-learn` | — | **NO**, `01` fits nothing |
| `chec_impacto`, `chec_local_interpreter` | — | **NO**, `01` imports neither |

It reads exactly two things from the Volume: `data/Indicadores_vano_v3.csv` and the three shapefiles under `data/GEO/`. It needs **no** Delta table, **no** view, **no** Lakeview dashboard, **no** model checkpoint and **no** source package. It also writes **no** side artifact — unlike `04`, which drops a CSV under `reports/reportescircuitos/artifacts/`.

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
If this fails on privileges, **do not stop** — this is contract rule B. Resolve the target with contract section C (the catalog is discovered, not hardcoded), record the deviation in the bitacora, and carry on. Only when no catalog anywhere grants `CREATE VOLUME` does this become a `bloqueante` restriction — and even then the run continues, so the report ends up listing every other wall too, not just the first one.

### 2b. Delegate the data upload — do not reimplement it

If the CSV **or** any shapefile is missing, run `/subir-datos-databricks` against the same workspace URL. It owns the mirror of `data/` plus the `.DS_Store` / `.gitkeep` / `.openmeteo_cache.sqlite` cleanup, and it carries the sidecar set correctly.

Warn first: `data/Indicadores_vano_v3.csv` is **~566 MB today** (Git-LFS tracked; `ls -lh` shows it as 540 MiB, same thing) and dominates a cold run. The base is expected to be refreshed, so measure it rather than trusting that figure. Confirm it is a real payload and not an unfetched pointer (`ls -l data/Indicadores_vano_v3.csv`; ~130 bytes means run `git lfs pull`). The GEO tree is LFS-tracked too — check it the same way.

## 3. Stage and upload the shimmed copy of `01`

**Hard invariant**: the modified notebook is a COPY in the scratch directory. `git status --porcelain notebooks/old_version/01_uiti_vano_clima.ipynb` MUST be empty when this step ends.

**Strip every code cell's `outputs` and `execution_count` first.** The repo file is **68 MB** on disk, essentially all of it cell 9's embedded `text/html`; stripped it is **0.086 MB** (measured). Both figures scale with the base, so treat them as orders of magnitude, not constants. `databricks workspace import --format JUPYTER` enforces a 10 MB limit, so an unstripped copy is 8x over the ceiling — this is the single difference between the upload working and failing outright, and `01` is by far the worst offender in the family.

Four edits, everything else byte-identical. Assert each match is unique and fail loudly if not.

**Edit 1 — cell index 1, the dependency install.** The cell ships this, commented:
```python
# %pip install pandas numpy plotly geopandas
```
Uncomment it **and pin plotly**:
```python
%pip install -q pandas numpy "plotly>=6" geopandas
```
Cell 8 builds the grid with a `{'type': 'map', 'rowspan': 2, 'colspan': 2}` entry in its `specs` and uses `go.Scattermap`, the MapLibre trace family that only exists in modern Plotly. Databricks Runtime preinstalls an older Plotly, and a bare `plotly` requirement is **already satisfied** by it, so pip prints nothing and upgrades nothing; the failure then surfaces as `ValueError: Unsupported subplot type: 'map'` with a traceback pointing at the *system* site-packages. A version floor forces the upgrade. Prefer the floor over `--upgrade`, which would also pull newer pandas/numpy/geopandas.

Keep this as cell index 1: `%pip install` restarts the interpreter, so no state-bearing cell may precede it.

**Edit 2 — cell index 2 (id `5983bcd2`), the repo root and the browser flag.** Two replacements in the same cell.

Replace the `find_repo_root()` call:
```python
REPO_ROOT = find_repo_root()
```
with
```python
REPO_ROOT = Path('/Volumes/workspace/default/chec-simulador')
```
Aliasing the same name keeps every downstream path resolving untouched: cell 2's CSV read and cell 6's three `REPO_ROOT / 'data' / 'GEO' / ...` shapefile reads.

Then replace:
```python
ABRIR_EN_NAVEGADOR = True
```
with
```python
ABRIR_EN_NAVEGADOR = False
```
There is no browser inside a job. Leaving it `True` makes `webbrowser.open()` run against a headless container; it does not raise, it just silently does nothing, so this is hygiene rather than a crash — but leaving it on also leaves a misleading "abriendo en el navegador" line in the job log.

Note cell 2 reads with `engine='pyarrow'`, the same as `03` and `04`. Keep it: pyarrow ships with the Databricks Runtime and it is several times faster than the C parser on this file, with the resulting data identical byte for byte.

**Edit 3 — cell index 9 (id `f0a3a0d4`), do not render and do not double-write.** Two replacements at the tail of the cell.

Replace:
```python
display(HTML(PANEL_COMPLETO))
```
with
```python
# display() omitido en Databricks: 28 MB por el canal iopub tumban la ejecucion.
```
This is **not** hygiene. The block is ~28 MB (measured; it was 67 MB before the cloud series were deduplicated into a palette) and pushing it through iopub is exactly the failure reproduced locally (`Timeout waiting for IOPub output`, which silently drops the cell output); inside a Databricks job it hits the output limit instead. The document still gets written — by edit 4, straight to the Volume, never through the kernel's output channel.

Then replace:
```python
RUTA_PANEL = exportar_y_abrir(PANEL_COMPLETO, abrir=ABRIR_EN_NAVEGADOR)
```
with
```python
# El export local no corre aca: la celda final escribe el documento en el Volume.
```
Leaving it in would write the same ~28 MB twice into the Volume (once under `reports/paneles/`, once under `dashboards/`), for no benefit. Leave the `exportar_y_abrir` **definition** alone — only the call goes.

**Edit 4 — append a final cell** that assembles and writes the document:
```python
from pathlib import Path

SALIDA = Path('/Volumes/workspace/default/chec-simulador/dashboards/clima_vano.html')
SALIDA.parent.mkdir(parents=True, exist_ok=True)

DOCUMENTO = f'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nube por vano -- clima, vegetacion y descargas</title>
<style>
  body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
         margin: 0; padding: 24px; color: #2b2b2b; background: #fff; }}
  h1 {{ font-size: 20px; margin: 0 0 4px 0; }}
  p.meta {{ font-size: 13px; color: #666; margin: 0 0 20px 0; }}
  #{DIV_FIGURA} {{ width: 100%; }}
</style>
</head>
<body>
<h1>Nube por vano -- clima, vegetacion y descargas</h1>
<p class="meta">Generado desde <code>01_uiti_vano_clima.ipynb</code> el {pd.Timestamp.now():%Y-%m-%d %H:%M} &mdash;
{len(df):,} eventos, {len(CIRCUITOS)} circuitos, {len(VARS_VIOLIN)} variables seleccionables,
{LAG_MAX + 1} rezagos horarios.</p>
{PANEL_COMPLETO}
</body>
</html>'''

SALIDA.write_text(DOCUMENTO, encoding='utf-8')
print(f'{SALIDA} -> {SALIDA.stat().st_size / 1024 / 1024:.2f} MB')
```
Use **triple single quotes** for that f-string. Its body contains `"Segoe UI"` and no nested single quotes; writing it as `f"""` would nest same-type quotes inside an f-string, which only compiles on Python 3.12+ (PEP 701) and blows up on Databricks serverless. A local `ast.parse` on 3.13+ does **not** catch this — it accepts both forms.

The `#{DIV_FIGURA} {{ width: 100% }}` rule matters: cell 8 deliberately leaves the figure **without** `width`, and `to_html` is called with `default_width='100%'` and `config.responsive`, so the board stretches to the browser. Without a full-width container it renders into whatever the div collapses to.

The six names the template uses (`DIV_FIGURA`, `pd`, `df`, `CIRCUITOS`, `VARS_VIOLIN`, `LAG_MAX`, `PANEL_COMPLETO`) all exist in the notebook; verify they still do before relying on them.

Upload:
```
databricks workspace mkdirs /Workspace/Users/<userName>/databricks-integration/project_flow -p <profile>
databricks workspace import /Workspace/Users/<userName>/databricks-integration/old_version/01_uiti_vano_clima --file <staged_copy> --format JUPYTER --overwrite -p <profile>
```

Then check the invariant. **Scope the hard assertion to `01` itself** and treat anything else in the folder as informational — a sibling notebook may well be open in Jupyter while this runs:
```
test -z "$(git status --porcelain notebooks/old_version/01_uiti_vano_clima.ipynb)" && echo LIMPIO || echo MODIFICADO
git status --porcelain notebooks/
```
The first line MUST print `LIMPIO`. Do **not** write the check as `git status --porcelain <path> && echo ok`: `git status` exits 0 whether or not it printed anything.

## 4. Run the notebook once to generate the HTML

```
databricks jobs submit --no-wait --json @<scratch>/job.json -p <profile>
```
with
```json
{
  "run_name": "vano-clima-html",
  "tasks": [{
    "task_key": "build_html",
    "notebook_task": {"notebook_path": "/Workspace/Users/<userName>/databricks-integration/old_version/01_uiti_vano_clima"}
  }]
}
```
No cluster spec — serverless is fine, `01` uses no `ipywidgets`. Poll `databricks jobs get-run <run_id> -p <profile>` until terminal. On failure, surface the notebook's own error rather than retrying blindly.

**Verify by content, not by exit code.** Expect **tens of MB** — measured locally at **27.8 MB** for the current base, against `04`'s 11.6 MB. It is still the largest artifact in the family because `CTX` carries every circuit with, per circuit and per day, the 25 hourly lags of the four climate variables — but it used to be 67 MB, before those series were deduplicated into a palette (see the `nubePaleta` check below). **Do not hardcode that number**: it scales with the base, which is expected to be updated and to cover other time spans. Compare it against the size the job itself prints (`panel autocontenido escrito en ... (N MB)`) and only fail if it is under 1 MB, which means the board came out empty. Download it and assert:
```
databricks fs cp dbfs:/Volumes/workspace/default/chec-simulador/dashboards/clima_vano.html <scratch>/verif.html --overwrite -p <profile>
```
- exactly one `id="clima-nube-vano"` — that is `DIV_FIGURA`'s value, and it is **not** `02`'s `agrupamiento-vanos`, `03`'s `trayectorias-circuitos` nor `04`'s `vano-ventana`, so a copy-pasted check from a sibling command would silently pass on the wrong artifact;
- **the map layer non-empty**: count `"fids"`, and require it to equal the circuit count the job printed (`N circuitos ensamblados (con eventos y geometria)`) — **208 on the current base, but read it from the job output rather than hardcoding it**, since a refreshed base can cover a different set of circuits. The check that must never be relaxed is `> 0`: with the shapefiles missing or unreadable the notebook still succeeds and still writes an HTML of roughly the right size, just with no map, and a size check alone will not catch that;
- `scattermap` present, which doubles as proof the Plotly floor took effect;
- exactly one `"nubeCfg"`, the root-level cloud config that carries the six resolved colorscales. If it is absent the six variables fall back to Plotly's default scale;
- exactly one `"fidsPorDia"` per circuit. The cloud and the UITI layer travel as arrays **aligned to that shared list of vanos** instead of repeating the vano id as a key in each; if it is missing, the panel is from an older revision of the notebook and the JS will read `undefined`;
- exactly one `"nubePaleta"`, the root-level palette of unique climate series. `nubePorDia` no longer carries the 25-lag series per vano but its **integer position** in that palette — the series repeat ~13x between neighbouring vanos because Open-Meteo resolves climate on a multi-km grid. If `nubePaleta` is absent the artifact predates the deduplication and `paleta[series[i]]` reads `undefined`, which paints the whole cloud a single flat colour without raising. Its absence is also why the file would be ~67 MB instead of ~28 MB, so a size far above the expected range is the same symptom;
- `optgroup` present, which is the two-group variable `<select>` (climate vs. static). Its absence means only the four climate variables are offered.

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

`app.py` — **this one deviates from its three siblings on purpose**, and the reason is the size:
```python
"""Sirve el HTML de la nube por vano que genera 01_uiti_vano_clima en el Volume.

~28 MB, que comprimen a ~6.5 MB (medido). Frente a los otros tres apps de la familia hay
dos diferencias, ambas por ese tamaño:

1. Se cachean BYTES, no str. Los hermanos hacen .decode('utf-8') y guardan el texto; con
   28 MB eso duplica el pico de memoria durante la carga y obliga a re-encodear en cada
   respuesta, sin ganar nada -- el contenido nunca se inspecciona.
2. Se pre-comprime UNA vez y se cachea el gzip, en vez de usar GZipMiddleware, que
   recomprime los 28 MB en CADA peticion.

GET /?refresh=1 tira ambos caches, que es como se hace visible una re-corrida del job sin
volver a desplegar la app.
"""

import gzip
import os

from databricks.sdk import WorkspaceClient
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

RUTA_HTML = os.environ.get(
    "RUTA_HTML",
    "/Volumes/workspace/default/chec-simulador/dashboards/clima_vano.html",
)

app = FastAPI()

_cache = {}


def _cargar():
    # files.download va por la Files API de Unity Catalog, que si funciona desde el
    # service principal de una app. No asumir que /Volumes esta montado por FUSE dentro
    # del contenedor.
    w = WorkspaceClient()
    crudo = w.files.download(RUTA_HTML).contents.read()
    _cache["crudo"] = crudo
    _cache["gz"] = gzip.compress(crudo, 6)


@app.get("/salud", response_class=PlainTextResponse)
def salud():
    # A proposito NO toca el Volume: separa "la app esta rota" de "falta el permiso sobre
    # el Volume", que desde el navegador se ven igual.
    return "ok"


@app.get("/")
def raiz(request: Request, refresh: int = 0):
    if refresh or "crudo" not in _cache:
        _cargar()
    if "gzip" in request.headers.get("accept-encoding", ""):
        return Response(
            content=_cache["gz"],
            media_type="text/html; charset=utf-8",
            headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"},
        )
    return HTMLResponse(_cache["crudo"])
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
  "description": "Nube por vano: clima, vegetacion y descargas sobre el mapa (cuaderno 01)",
  "resources": [{
    "name": "volumen-chec-simulador",
    "description": "Volume con el HTML generado por el cuaderno 01",
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
- **The bitacora**: its path under `reports/despliegues/`, the final state `cerrar` printed (`COMPLETO`, `COMPLETO CON RESTRICCIONES` or `INCOMPLETO`), and the count of restrictions it holds. Do not soften that state in prose.
- **Every restriction recorded, with who unblocks each one** — reproduce the `resumen` output. A run that ended INCOMPLETO reports what is still blocking, not just what worked.

```
databricks apps get <app-name> -o json -p <profile>
```
Require all three: `compute_status: ACTIVE`, `app_status: RUNNING`, `active_deployment.status: SUCCEEDED`. Capture `url` verbatim — never fabricate one.

Tell the user, in their language:
- The app URL, the app name, and the profile/workspace used.
- **Everything the preflight found missing and what was done about it** — the headline of a cold run.
- That the HTML lives at `/Volumes/workspace/default/chec-simulador/dashboards/clima_vano.html`, its measured size, and which content checks passed (`id="clima-nube-vano"`, `"fids"` matching the circuit count the job printed, `scattermap`, `"nubeCfg"`, `"fidsPorDia"`, `optgroup`). Report the **observed** numbers, not the ones written here.
- Whether the volume permission came from the `uc_securable` resource or from a manual grant.
- **How to refresh**: re-run step 4's job, then hit `/?refresh=1`. No redeploy — the app carries no data.
- **That this board is the heaviest of the four**, and why: ~28 MB uncompressed, ~6.5 MB over the wire once gzipped (it was 67 MB / 7.3 MB before the palette deduplication — gzip already exploited the repetition, so the win shows up mostly in what the browser has to `JSON.parse` and hold in memory, not on the wire). The first load after a cold start pays the download from the Volume plus one compression; every later load is served from memory. `/salud` answers without touching the Volume, so it separates an app failure from a permission failure.
- **How the board is read**: the map is a 2x2 block; every vano with events that day gets its UITI quartile drawn over the black structure, and a vano with no events that day gets nothing but the black line. The translucent circles encode the **variable chosen in the panel** — six of them, four climate ones that the hourly-lag slider moves and two static per-vano ones (`NR_T`, vegetation risk, and `DDT`, ground discharges) for which that slider is disabled on purpose. Colour, not opacity, carries the value, over a per-variable scale with `cmin`/`cmax` fixed across the whole dataset, so a colour means the same thing in every circuit. Top right is the dual-axis series: daily circuit UITI on the left, daily median of the selected variable on the right, with the current day's point drawn at triple size. The six violins below describe the vano-events of the chosen day.
- That `git status --porcelain` on the notebook was empty — the repo copy was never modified.
- That no Delta table, view or Lakeview dashboard was created or touched. The Lakeview dashboard and the Delta tables job were retired, so there is nothing to point to — this family no longer creates tables or views at all.
