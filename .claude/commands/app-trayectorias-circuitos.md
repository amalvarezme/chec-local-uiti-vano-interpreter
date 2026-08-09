---
description: Publica el cuaderno 03 (trayectorias de circuito por ventanas deslizantes, con mapa geografico) como una Databricks App en una URL fija, detectando y reparando por su cuenta todo lo que falte — si no estan el CSV o los shapefiles en el Volume encadena /subir-datos-databricks, y configura el permiso de lectura de la app sin intervencion manual. Pregunta solo el nombre de la app y la URL del workspace destino.
---

Follow this exact sequence when `/app-trayectorias-circuitos` is invoked. It publishes `notebooks/project_flow/03_uiti_vano_trayectorias_circuitos.ipynb` as a browsable dashboard at a stable URL, and it is **self-healing**: it inspects the target workspace first and creates whatever is missing.

This is the sibling of `/app-agrupamiento-vanos-circuitos`, which does the same for `02`. The two are **independent apps** with independent HTML artifacts — deploying one never touches the other. Read that command when something here is unclear about the shared mechanics; only the differences are spelled out below.

**Why Databricks Apps and not Lakeview.** Same reason as `02`: `03` fits K-Means with scikit-learn over 8 coordinate spaces, builds 25 Plotly traces including a geographic map, and drives everything from a hand-written HTML+JS panel (cell 7). Lakeview executes neither Python nor arbitrary JS.

## What `03` needs that `02` did NOT

This is the single most important difference and the reason the preflight below is bigger. Verified by reading the notebook:

| Input | `02` | `03` |
|---|---|---|
| `data/Indicadores_vano_v3.csv` | yes | yes |
| `data/GEO/MVLINSEC.shp` (+ sidecars) | no | **yes** — the circuit map's line segments |
| `data/GEO/GDBCHEC_TRANSFOR.shp` (+ sidecars) | no | **yes** — transformer markers |
| `data/GEO/SWITCHES.shp` (+ sidecars) | no | **yes** — switch markers |
| `geopandas`, `scikit-learn` | no / yes | **both** |

A shapefile is not one file. `MVLINSEC.shp` is useless without at least `.shx` and `.dbf`, and without `.prj` geopandas cannot resolve the CRS for the `to_crs('EPSG:4326')` call. `/subir-datos-databricks` mirrors the whole `data/` tree, so all sidecars travel — which is exactly why this command delegates to it rather than copying single files.

Still **not** needed: no Delta table, no view, no Lakeview dashboard, no model checkpoint, no source package. `03` imports neither `chec_impacto` nor `chec_local_interpreter`.

**Scope.** MUST NOT create or refresh any Delta table or view, MUST NOT touch the Lakeview dashboard, MUST NOT modify the file under `notebooks/project_flow/`, MUST NOT touch the `02` app or its HTML, and MUST NOT create any `site`-named path inside the Volume.

## 0. Ask the user for the two required inputs

Ask, one at a time, and wait:
1. The app name. The API constrains it to **2–30 characters, lowercase alphanumerics and hyphens**, unique in the workspace. Propose `trayectorias-circuitos` as the default. It MUST differ from the `02` app's name.
2. The Databricks workspace URL.

If a step finds a missing prerequisite, **do not ask whether to create it**. Only pause for an expired OAuth token or a privilege the profile cannot grant.

## 1. Resolve profile and identity

Follow `.claude/commands/app-agrupamiento-vanos-circuitos.md` **section 1** verbatim, including its warning: never pipe `2>&1` into a JSON parser, because the CLI intermittently prints `Databricks skills are not installed...` on stderr and that reads as a bogus auth failure. Use `2>/dev/null` when parsing.

## 2. Preflight — inspect everything, then repair

Read-only checks first; report the full list of what is missing in one message, then fix each without asking.

| # | Check | Command | If missing → |
|---|---|---|---|
| 1 | Volume exists | `databricks fs ls dbfs:/Volumes/workspace/default/chec-simulador -p <profile>` | 2a |
| 2 | Source CSV | `databricks fs ls dbfs:/Volumes/workspace/default/chec-simulador/data -p <profile>` | 2b |
| 3 | **GEO shapefiles** | `databricks fs ls dbfs:/Volumes/workspace/default/chec-simulador/data/GEO -p <profile>` | 2b |
| 4 | Notebook uploaded | `databricks workspace list /Workspace/Users/<userName>/databricks-integration/project_flow -p <profile>` | 3 |
| 5 | Generated HTML | `databricks fs ls dbfs:/Volumes/workspace/default/chec-simulador/dashboards -p <profile>` | 4 |
| 6 | App exists | `databricks apps list -p <profile>` | 6 |

For check 3, confirm all three shapefiles **and their sidecars** are present — at minimum `MVLINSEC.{shp,shx,dbf,prj}`, `GDBCHEC_TRANSFOR.{shp,shx,dbf,prj}`, `SWITCHES.{shp,shx,dbf,prj}`. A bare `.shp` with no `.shx` fails inside the job with an opaque driver error, not a clear "file missing", so check the set rather than just the folder's existence.

### 2a. Create the Volume if absent

Identical to `/app-agrupamiento-vanos-circuitos` section 2a (`POST /api/2.1/unity-catalog/volumes`, catalog `workspace`, schema `default`, name `chec-simulador`, `MANAGED`).

### 2b. Delegate the data upload

If the CSV **or** any shapefile is missing, run `/subir-datos-databricks` against the same workspace URL. Do not hand-roll `fs cp` for individual files: the sidecar set is easy to get wrong, and that command already owns the mirror plus the `.DS_Store`/`.gitkeep`/`.openmeteo_cache.sqlite` cleanup.

Warn first that `data/Indicadores_vano_v3.csv` is **566 MB** (Git-LFS tracked) and dominates a cold run. Confirm the local file is a real payload and not an unfetched LFS pointer (`ls -l data/Indicadores_vano_v3.csv`; a pointer is ~130 bytes → `git lfs pull`). The GEO tree is also LFS-tracked — check it the same way.

## 3. Stage and upload the shimmed copy of `03`

**Hard invariant**: the modified notebook is a COPY in the scratch directory. Assert on `03` itself and report other modified notebooks as observations only:
```
test -z "$(git status --porcelain notebooks/project_flow/03_uiti_vano_trayectorias_circuitos.ipynb)" && echo LIMPIO || echo MODIFICADO
```
Never write it as `git status --porcelain <path> && echo ok` — git exits 0 on a dirty tree.

**Strip every code cell's `outputs` and `execution_count`.** `03` no longer stores its rendered board in the repo — cell 7's `display_data` is committed empty, matching `01` and `02`, whose boards are likewise reachable as standalone HTML under `reports/paneles/`. Strip anyway: a local run repopulates cell 7 with ~11 MB of `text/html`, and a staged copy taken right after one is over the 10 MB `--format JUPYTER` import limit outright.

Note this is `03`-only. **`04`'s output must never be stripped in the repo**: `scripts/extract_geometrias_014.py` reads its K-Means geometry out of that stored HTML. Nothing reads `03`'s.

Four edits; everything else byte-identical.

**Edit 1 — cell 1, the dependency install.** The cell already ships the complete, Databricks-correct line, commented:
```python
# %pip install -q pandas numpy pyarrow "plotly>=6" geopandas scikit-learn
```
Just uncomment it. Do **not** trim the list:
- `pyarrow` — cell 2 reads the CSV through `pyarrow.csv.open_csv` (see edit 2's note).
- `geopandas` (cell 5, which also uses `shapely`, pulled in as a geopandas dependency) and `scikit-learn` (cell 4).
- **The `>=6` on plotly is load-bearing.** Confirmed empirically: the first real run failed with
  ```
  ValueError: Unsupported subplot type: 'map'
    in /databricks/python/lib/python3.11/site-packages/plotly/_subplots.py
  ```
  Cell 6 builds the map with a `{'type': 'map'}` entry in its `specs` grid and `go.Scattermap`, the MapLibre trace family that only exists in modern Plotly. Databricks Runtime preinstalls an older Plotly, and a bare `plotly` requirement is **already satisfied** by it, so pip prints nothing and upgrades nothing — note the traceback path is the *system* site-packages, not the pip-installed one. A version floor forces the upgrade. Prefer the floor over `--upgrade`, which would also pull newer pandas/numpy/geopandas and risk breaking something that currently works.

The repo's own `requirements.txt` pins `plotly` with no floor either, so it cannot be leaned on here.

Keep this as cell index 1: `%pip install` restarts the interpreter, so no state-bearing cell may precede it.

**Edit 2 — cell 2, redirect the repo root.** Replace the `find_repo_root()` definition and its call:
```python
REPO_ROOT = find_repo_root()
```
with
```python
REPO_ROOT = Path('/Volumes/workspace/default/chec-simulador')
```
Aliasing the same name keeps all five downstream paths resolving untouched: cell 2's `leer_eventos()` CSV read, cell 5's `REPO_ROOT / 'data' / 'GEO' / 'MVLINSEC.shp'` and `REPO_ROOT / 'data' / 'GEO' / nombre_shp`, cell 7's `reports/paneles/` export, and cell 8's `reports/interpretability/artifacts/` CSV write. Leave every import and constant alone, including `_norm_id` — it lives in cell 2 and both the CSV and the geometry path call it, so moving or duplicating it would silently break the vano↔geometry join.

Then, in the same cell, replace:
```python
ABRIR_EN_NAVEGADOR = True
```
with
```python
ABRIR_EN_NAVEGADOR = False
```
There is no browser inside a job. Leaving it `True` makes `webbrowser.open()` run against a headless container; it does not raise, it just silently does nothing — but it also leaves a misleading "abriendo en el navegador" line in the job log. Edit 3 removes the export call outright, so this is belt-and-braces.

Note cell 2 reads through `leer_eventos()`, which wraps `pyarrow.csv.open_csv`. **Keep it as is.** It is not a stylistic choice: `pd.read_csv(engine='pyarrow')` materialises the whole 566 MB file before discarding the ~266 columns the notebook does not use, which measured **826 MB of peak RSS against 109 MB** for the block reader, at a cost of 0.2 s. On a serverless job that headroom is the difference between comfortable and OOM. Reverting it to `pd.read_csv` would silently undo the largest memory win in the notebook.

**Edit 3 — cell 7, do not render and do not double-write.** Two replacements at the tail of the cell.

Replace:
```python
display(HTML(PANEL_COMPLETO))
```
with
```python
# display() omitido en Databricks: el bloque va por el canal iopub y no hace falta.
```
The block is ~11 MB. Pushing it through iopub is pointless inside a job — nobody reads the cell output — and on larger boards it hits the output limit outright. The document still gets written, by edit 4, straight to the Volume.

Then replace:
```python
RUTA_PANEL = exportar_y_abrir(PANEL_COMPLETO, abrir=ABRIR_EN_NAVEGADOR)
```
with
```python
# El export local no corre aqui: la celda final escribe el documento en el Volume.
```
Leaving it in would write the same ~11 MB twice into the Volume (once under `reports/paneles/`, once under `dashboards/`), for no benefit. Leave the `exportar_y_abrir` **definition** alone — only the call goes.

`PANEL_COMPLETO` stays defined either way: it is assigned on its own line just above the `display()`, so edit 4 can use it.

**Edit 4 — append a final cell** that writes the document:
```python
from pathlib import Path

SALIDA = Path('/Volumes/workspace/default/chec-simulador/dashboards/trayectorias_circuitos.html')
SALIDA.parent.mkdir(parents=True, exist_ok=True)

DOCUMENTO = f'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trayectorias de circuito por ventanas deslizantes</title>
<style>
  body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
         margin: 0; padding: 24px; color: #2b2b2b; background: #fff; }}
  h1 {{ font-size: 20px; margin: 0 0 4px 0; }}
  p.meta {{ font-size: 13px; color: #666; margin: 0 0 20px 0; }}
  #{DIV_FIGURA} {{ width: 100%; }}
</style>
</head>
<body>
<h1>Trayectorias de circuito por ventanas deslizantes</h1>
<p class="meta">Generado desde <code>03_uiti_vano_trayectorias_circuitos.ipynb</code> el {pd.Timestamp.now():%Y-%m-%d %H:%M} &mdash;
{len(df):,} eventos, {len(CIRCUITOS)} circuitos, {len(VENTANAS)} ventanas, {len(CELDAS):,} celdas con eventos,
periodo {df["FECHA"].min():%Y-%m-%d} a {df["FECHA"].max():%Y-%m-%d}.</p>
{PANEL_COMPLETO}
</body>
</html>'''

SALIDA.write_text(DOCUMENTO, encoding='utf-8')
print(f'{SALIDA} -> {SALIDA.stat().st_size / 1024 / 1024:.2f} MB')
```

The `#{DIV_FIGURA} {{ width: 100% }}` rule is **required, not decoration**. Cell 6 deliberately leaves the figure without `width`, and cell 7 calls `to_html` with `default_width='100%'` and `config={{'responsive': True}}`. Those three work only together: without a full-width container the board renders into whatever the div collapses to, and the map — which frames itself with a `fitBounds` measured on the live canvas — then frames against that collapsed width. Serving the app at a narrow width is a layout bug, not a cosmetic one.

The six names the template uses (`DIV_FIGURA`, `pd`, `df`, `CIRCUITOS`, `VENTANAS`, `CELDAS`, `PANEL_COMPLETO`) all exist in the notebook; verify they still do before relying on them.

Upload:
```
databricks workspace mkdirs /Workspace/Users/<userName>/databricks-integration/project_flow -p <profile>
databricks workspace import /Workspace/Users/<userName>/databricks-integration/project_flow/03_uiti_vano_trayectorias_circuitos --file <staged_copy> --format JUPYTER --overwrite -p <profile>
```

## 4. Run the notebook once to generate the HTML

Submit a serverless job exactly as `/app-agrupamiento-vanos-circuitos` section 4 does, pointing at `.../project_flow/03_uiti_vano_trayectorias_circuitos`, with `run_name: "trayectorias-circuitos-html"`. `03` uses no `ipywidgets`, so serverless is fine. Poll `databricks jobs get-run` until terminal; on failure surface the notebook's own error.

Expect this leg to be slower than `02`'s: the job also reads three shapefiles from the Volume through the FUSE mount.

**Verify by content, not by exit code.** Expect **~10.9 MB** (cell 7's stored output measures 10.98 MB; the app document runs slightly under it because it drops Jupyter's wrapper — the previous 10.47 MB figure predates the two-row layout and the sample counts in the titles). It is larger than `02`'s circuit board, now ~5.2 MB (it was ~7.0 MB until the clustering space was fixed: its embedded `COMBINACIONES` went from 168 keys to 21, i.e. 2.08 → 0.26 MB of `CTX`). `03`'s own size barely moved for the same change, because its eight geometries were a few KB — the split here is roughly plotly.js 4.9 MB plus a 6.1 MB `CTX`, of which `geo` is 3.0 MB and `uitiVentana` 2.4 MB. Download it and assert (all verified against cell 7, not guessed):
- exactly one `id="trayectorias-circuitos"` — that is `DIV_FIGURA`'s value, and it is **not** the same string as the `02` app's `agrupamiento-circuitos` div, so a copy-paste of that check would silently pass on the wrong artifact,
- the panel controls `tr-circuito` and `tr-ventana` — those two and no others. There is **no** `tr-csv`: the CSV download button was removed from the board, and its reproducible replacement is cell 8, which writes the same table from the kernel. There are also **no** `tr-logx`, `tr-logy` or `tr-prep`: the clustering space is fixed (linear x, `log10` y, `minmax`) and `ESPACIOS` holds a single entry, so K-Means is fitted once instead of eight times. If any of those five ids appears, the staged copy is stale,
- `Plotly.newPlot` present,
- the responsive contract intact: `"responsive": true` in the config and no `"width":1480` in the figure layout. Both are cheap greps and both are the difference between a full-width board and one frozen at 1480 px,
- `function encuadrarCircuito(` and `maplibregl-map` present — the map's `fitBounds` measures the live canvas, and losing it puts the old zoom-from-degrees framing back,
- **the map layer non-empty** — count `"fids"` and `"centro"` in the document; both must equal the number of circuits with geometry (measured: **208 each**). This is the check that matters here: with the shapefiles missing or unreadable the notebook still succeeds and still writes an HTML of roughly the right size, just with no map. A size check alone will not catch it. `scattermap` should also appear, which doubles as proof the Plotly floor above took effect.

Reading the three shapefiles from the Volume through the FUSE mount **works** — confirmed on a real run, where cell 5 completed and the failure came later, in cell 6. That was the main risk going in; it is settled.

## 5. Stage the App source

Identical to `/app-agrupamiento-vanos-circuitos` section 5 — same `app.yaml`, same `requirements.txt` (`fastapi`, `uvicorn`, `databricks-sdk`), same `app.py` — with **one change**: point `RUTA_HTML` at this dashboard.
```python
RUTA_HTML = os.environ.get(
    "RUTA_HTML",
    "/Volumes/workspace/default/chec-simulador/dashboards/trayectorias_circuitos.html",
)
```
Upload the three files with `--format RAW` into `/Workspace/Users/<userName>/databricks-integration/apps/<app-name>/`, a folder distinct from the `02` app's.

## 6. Create the App with the Volume as a resource

Same `uc_securable` body as `/app-agrupamiento-vanos-circuitos` section 6 — Databricks applies `READ VOLUME` itself during service-principal provisioning, so no manual `GRANT` is needed. Verify it landed with `SHOW GRANTS` rather than assuming, and read `service_principal_client_id` from **this** app: it is new per app and per re-creation, so the `02` app's grant does nothing for this one.

Fallback to the manual grant only if that fails — see section 6a there, including the note that the auto-mode classifier denies `GRANT` through `databricks api post` and the user must run it with `!`.

## 7. Deploy

**Poll `compute_status` to `ACTIVE` first** — deploying against a `STARTING` app fails with `Cannot deploy app <name> as it is not in RUNNING state`. Roughly 5 polls at 20 s on a fresh create; use `command sleep`, a bare foreground `sleep` is blocked. Then `databricks apps deploy <app-name> --source-code-path ... -p <profile>`.

## 8. Verify and report back

Require `compute_status: ACTIVE`, `app_status: RUNNING`, `active_deployment.status: SUCCEEDED`. Capture `url` verbatim.

Tell the user, in their language:
- The app URL, name, and the profile/workspace used.
- **Everything the preflight found missing and what was done about it.**
- The HTML path (`.../dashboards/trayectorias_circuitos.html`), its measured size, and that the map layer was verified non-empty — not just that the file exists.
- Whether the volume permission came from `uc_securable` or a manual grant.
- **How to refresh**: re-run the step 4 job, then hit `/?refresh=1`. No redeploy.
- That the first load is slow (~10.5 MB gzipped) and later ones are cached, and that `/salud` answers without touching the Volume so it separates an app failure from a permission failure.
- That `uiti_ventanas_deslizantes.csv` also landed under `.../chec-simulador/reports/interpretability/artifacts/` as a side effect of cell 8.
- That the `02` app, if deployed, was untouched — the two are independent.
- That no Delta table, view or Lakeview dashboard was created or touched.
