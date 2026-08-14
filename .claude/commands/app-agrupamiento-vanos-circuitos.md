---
description: Publica el tablero de VANOS del cuaderno 02 (agrupamiento de vanos por UITI acumulado, con el top 10 de circuitos por vanos en clase Alto) como una Databricks App en una URL fija, detectando y reparando por su cuenta todo lo que falte — si no hay datos en el Volume encadena /subir-datos-databricks, y configura el permiso de lectura de la app sin intervención manual. Pregunta solo el nombre de la app y la URL del workspace destino.
---

> **Read `.claude/commands/_contrato-despliegue-databricks.md` before anything else.** It is mandatory and it overrides what follows:
> - **A. Run log** — open the bitacora *before* asking the user anything, record every numbered step as you finish it, and always close it. Its path and final state are part of the report back to the user.
> - **B. Never abort** — a restriction gets recorded and worked around; the command runs to the end regardless. Wherever this file says "stop and report", rule B applies instead.
> - **C. Unity Catalog target** — `workspace.default.chec-simulador` below is a default, not a requirement. Resolve it at runtime and substitute the resolved value into every path here.
> - **D. Known restrictions** — D1–D9. If one shows up, do not re-diagnose it.

Follow this exact sequence when `/app-agrupamiento-vanos-circuitos` is invoked. It publishes the **vano board** of `notebooks/base_apps/02_uiti_vano_kmeans.ipynb` as a browsable dashboard at a stable URL (the notebook renders two boards; only that one is published — see edit 3), and it is **self-healing**: it inspects the target workspace first and creates whatever is missing, so it works against a workspace that has never been touched as well as against one that already has everything.

**Why this is not a Lakeview dashboard.** Lakeview publishes SQL datasets plus declarative widgets; that stack was retired from this repo for exactly the reason below. `02` is a different animal — it fits K-Means with scikit-learn (8 coordinate spaces, frozen over the full window), builds 23 Plotly traces on the circuit board and 25 on the vano board — the latter on a 6x4 grid, including a horizontal stacked bar of the top 10 circuits by vanos in the `Alto` class and a full-width per-circuit ranking over all 208 circuits, coloured by P50/P75/P97 risk range, both recomputed in the browser for the selected date range — and drives them from a hand-written HTML+JS panel (cells 6 and 13) that also builds a two-sheet `.xlsx` on the client. Lakeview executes neither Python nor arbitrary JS, so porting `02` would mean rewriting the analysis and losing the Voronoi partition contours, the marginal KDEs, the violins and the panel. This command therefore uses **Databricks Apps**, which hosts arbitrary Python web servers, and serves the notebook's own HTML verbatim.

**What this command does NOT need.** Verified by reading the notebook: `02` reads exactly one file, `data/Indicadores_vano_v3.csv`, and imports neither `chec_impacto` nor `chec_local_interpreter`. It needs **no** Delta table, **no** view, **no** Lakeview dashboard, **no** shapefile, **no** model checkpoint, and **no** source package. Do not create or check any of those here — if they are absent, that is not this command's problem. Nothing in this repo creates them any more: the Lakeview dashboard and the tables job were retired.

**Scope.** MUST NOT create or refresh any Delta table or view, MUST NOT touch the Lakeview dashboard, MUST NOT modify the file under `notebooks/`, and MUST NOT create any `site`-named path inside the Volume.

## 0. Ask the user for the two required inputs

Ask, one at a time, and wait for each answer:
1. The name for the Databricks App. The API constrains this to **2–30 characters, lowercase alphanumerics and hyphens only**, unique in the workspace. If the answer has spaces, uppercase or accents, propose the normalized form and confirm before continuing (`Agrupamiento Vanos Circuitos` → `agrupamiento-vanos-circuitos`). Note this is the **app** name, independent of this command's name; an app already deployed as `agrupamiento-circuitos` keeps that URL unless the user asks to recreate it..
2. The Databricks workspace URL (e.g. `https://dbc-xxxxxxxx-xxxx.cloud.databricks.com`).

If a step below finds a missing prerequisite, **do not ask whether to create it** — creating it is this command's job. Only pause for the two things that genuinely need a human: an expired OAuth token, and a privilege the profile is not allowed to grant.

## 1. Resolve profile and identity

Follow `.claude/commands/_contrato-despliegue-databricks.md` **section E1** verbatim with the URL from step 0. Carry the resolved `<profile>` everywhere below.

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
If this fails on privileges, **do not stop** — this is contract rule B. Resolve the target with contract section C (the catalog is discovered, not hardcoded), record the deviation in the bitacora, and carry on. Only when no catalog anywhere grants `CREATE VOLUME` does this become a `bloqueante` restriction — and even then the run continues, so the report ends up listing every other wall too, not just the first one.

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

**Hard invariant**: the modified notebook is a COPY in the scratch directory. `git status --porcelain notebooks/` MUST be empty when this step ends.

**Strip every code cell's `outputs` and `execution_count` first.** The repo file is now **97 KB** — the 8.84 MB of embedded `text/html` that used to sit in cells 6 and 13 was taken out of version control, since it is a regenerable artifact. Stripped, the staged copy measures **0.087 MB**. `databricks workspace import --format JUPYTER` enforces a 10 MB limit; with the repo copy this small the strip no longer decides whether the import fits, but keep it anyway — it costs nothing, and a future local run re-embeds those megabytes into the file the moment someone saves the notebook.

Four edits, everything else byte-identical. Assert each match is unique and fail loudly if not — a silently-skipped edit produces a notebook that fails deep inside the job.

**Edit 1 — cell 1**: uncomment the install line the notebook already ships:
```python
# %pip install pandas numpy scipy scikit-learn plotly
```
→ `%pip install pandas numpy scipy scikit-learn plotly`

Do **not** substitute the repo-wide `requirements.txt` install that `/subir-notebooks-databricks` applies to the 9 `project_flow` notebooks: `02` imports neither local package, so that would pull `torch`/`shap`/`geopandas`/`optuna` for nothing. Keep it as cell index 1 — `%pip install` restarts the interpreter, so no state-bearing cell may precede it.

`pyarrow` is **not** on that install line and must not be added: cells 2 and 10 read with `engine='pyarrow'` (15x faster than the C parser on this file — 0.06 s against 0.90 s, measured), and pyarrow ships with the Databricks Runtime, exactly as `01`, `03` and `04` already rely on. Adding it to the pip line would only risk resolving a different version than the runtime's. If a future runtime ever drops it, the symptom is an `ImportError` naming pyarrow on cell 2, not a wrong result.

**Edit 2 — cell 2**: replace the `find_repo_root()` definition **and** its call
```python
REPO_ROOT = find_repo_root()
```
with
```python
REPO_ROOT = Path('/Volumes/workspace/default/chec-simulador')
```
The name is deliberately preserved, so cell 2's and cell 10's `REPO_ROOT / 'data' / 'Indicadores_vano_v3.csv'`, plus cells 7 and 14's `REPO_ROOT / 'reports' / 'reportescircuitos' / 'artifacts'` CSV writes, all keep resolving with zero downstream edits. Leave every import (including the now-unused `from IPython.display import HTML, display`) and every constant untouched.

**Edit 2b — cell 2**: turn the browser off.
```python
ABRIR_EN_NAVEGADOR = True    →    ABRIR_EN_NAVEGADOR = False
```
There is no browser inside a job. Leaving it `True` makes `webbrowser.open()` run against a headless container; it does not raise, it just silently does nothing — but it also leaves a misleading "abriendo en el navegador" line in the job log.

**Edit 3 — cells 6, 13 and 15**: do not render and do not double-write.
```python
display(HTML(PANEL_CIRCUITOS))                    → # display() omitido en Databricks: el bloque va por iopub y tumba la ejecucion.
display(HTML(PANEL_VANOS))                        → # idem: el documento lo escribe la celda final, directo al Volume.
RUTA_PANEL = exportar_y_abrir(abrir=ABRIR_EN_NAVEGADOR)  → # El export local no corre aca: la celda final escribe en el Volume.
```
That third line matters as much as the other two. `exportar_y_abrir` writes to `REPO_ROOT / 'reports' / 'paneles'`, and edit 2 already repointed `REPO_ROOT` at the Volume — so leaving it in writes the same megabytes **twice** into the Volume, once under `reports/paneles/` and once under `dashboards/`. Leave everything else in cell 15 alone — in particular `FIGURA_VANO_SOLA` and `PANEL_VANOS_SOLO`, which edit 4 consumes.

### What gets published: the vano board only

The notebook renders **two** boards — circuits and vanos — but the app publishes **only the vano one**. That is the board that answers the operational question (which vanos, and from which circuits, concentrate the criticality); the circuit board stays as an intermediate step to read inside the notebook.

Do **not** try to assemble that from `PANEL_VANOS`. Cell 13 builds it with `include_plotlyjs=False`, because when both boards travel together the library already arrived with the circuit one, and its `<style>` block for `.panel-agrup` lives in the circuit panel too. Published alone it would come out with **no Plotly and no styling** — a blank page with unstyled controls, and nothing raises.

Cell 15 already solves this and exposes the result: `PANEL_VANOS_SOLO = PANEL_CSS + PANEL_VANO_HTML + FIGURA_VANO_SOLA + PANEL_VANO_JS`, where `FIGURA_VANO_SOLA` is a second `to_html` of the same figure with `include_plotlyjs=True`. Use that variable and nothing else.

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
<title>Agrupamiento de vanos por UITI acumulado</title>
<style>
  body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
         margin: 0; padding: 24px; color: #2b2b2b; background: #fff; }}
  h1 {{ font-size: 20px; margin: 0 0 4px 0; }}
  p.meta {{ font-size: 13px; color: #666; margin: 0 0 20px 0; }}
  /* El div de la figura al ancho del contenedor. La figura de vanos ya NO trae `width`
     en su layout y su `to_html` pasa `default_width='100%'` mas `config.responsive`,
     asi que sin esta regla el tablero igual funciona pero queda a merced de lo que
     herede el div. Con las tres piezas juntas usa toda la pantalla y se reajusta al
     redimensionar (medido: 952 px de plot a 1000 px de ventana, 2352 a 2400, sin scroll
     horizontal en ningun caso). */
  #{DIV_VANO} {{ width: 100%; }}
</style>
</head>
<body>
<h1>Agrupamiento de vanos por UITI acumulado</h1>
<p class="meta">Generado desde <code>02_uiti_vano_kmeans.ipynb</code> el {pd.Timestamp.now():%Y-%m-%d %H:%M} &mdash;
{len(df):,} eventos, {df["CIRCUITO"].nunique()} circuitos, {len(VANOS):,} vanos,
periodo {df["FECHA"].min():%Y-%m-%d} a {df["FECHA"].max():%Y-%m-%d}.</p>
{PANEL_VANOS_SOLO}
</body>
</html>'''

SALIDA.write_text(DOCUMENTO, encoding='utf-8')
print(f'{SALIDA} -> {SALIDA.stat().st_size / 1024 / 1024:.2f} MB')
```

Upload:
```
databricks workspace mkdirs /Workspace/Users/<userName>/databricks-integration/project_flow -p <profile>
databricks workspace import /Workspace/Users/<userName>/databricks-integration/base_apps/02_uiti_vano_kmeans --file <staged_copy> --format JUPYTER --overwrite -p <profile>
```

Then check the invariant. **Scope the hard assertion to `02` itself**, and treat anything else in the folder as informational — the user may well be editing a sibling notebook in Jupyter while this command runs, and a whole-folder check reports that as if this command had caused it (confirmed empirically: a run tripped on ` M 03_uiti_vano_trayectorias_circuitos.ipynb`, which was the user's own concurrent work):
```
test -z "$(git status --porcelain notebooks/base_apps/02_uiti_vano_kmeans.ipynb)" && echo LIMPIO || echo MODIFICADO
git status --porcelain notebooks/
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
    "notebook_task": {"notebook_path": "/Workspace/Users/<userName>/databricks-integration/base_apps/02_uiti_vano_kmeans"}
  }]
}
```
No cluster spec — the task runs on serverless. That is fine here: `02` uses no `ipywidgets` (that constraint belongs to `06_uiti_vano_explicabilidad_simulador`). Poll `databricks jobs get-run <run_id> -p <profile>` until terminal. On failure, surface the notebook's own error rather than retrying blindly.

**Verify the artifact by content, not by exit code.** Expect **~6.1 MB**, which gzips to ~1.8 MB — the vano board measured 6.06 MB on the current base, of which **4.64 MB is the embedded plotly.js** and 1.41 MB the vano `CTX`. Two things brought it there: publishing one board instead of two (8.5 → 6.6 MB) and compacting the context (6.6 → 6.06 MB). The remaining 4.64 MB is not reducible from here — plotly 6.8.0 ships only the full `plotly.min.js`, and the board needs `scattergl` (27.390 points), `contour`, `violin` and `bar`, which no single official partial bundle covers; vendoring one would add an external dependency and a version to keep in sync for something gzip already halves. **Do not hardcode the number**: it scales with the base. Fail only under 1 MB, which means the board came out empty. Download it and assert:
```
databricks fs cp dbfs:/Volumes/workspace/default/chec-simulador/dashboards/agrupamiento_circuitos.html <scratch>/verif.html --overwrite -p <profile>
```
Then confirm:
- exactly one `id="agrupamiento-vanos"`, and **zero** `id="agrupamiento-circuitos"` — the circuit board must NOT be in the published artifact. A non-zero count means edit 4 was assembled from the wrong variable;
- exactly one each of the three `va-*` panel controls (`va-desde`, `va-hasta`, `va-csv`), and **zero** occurrences of `va-logx`, `va-logy` and `va-prep`. The axis-scale checkboxes and the preprocessing select were removed: the clustering space is fixed (linear x, `log10` y, `minmax`) and `ESPACIOS` holds a single entry, so K-Means is fitted once instead of eight times and the embedded combinations drop from 168 to 21. Any of those three ids means the staged copy is stale;
- `libroXlsx` and `CompressionStream` appear. The **Descargar etiquetas (Excel)** button builds a real two-sheet `.xlsx` **in the browser**, with no library: an `.xlsx` is a ZIP of XML parts, the ZIP is written by hand (CRC32 + local headers + central directory) and each part is deflated with the browser's native `CompressionStream('deflate-raw')`, falling back to STORE where that API is missing. Measured on the current base: 12.26 MB stored against **0.97 MB** deflated, validated by opening it with `openpyxl` (`testzip()` clean, both sheets, 27.390 + 208 rows). The `Circuitos` sheet lists **every** circuit, including those with no events in the window — all-zero counts and `grupo_ranking` 1 — and its `vanos_total`, `num_eventos` and `uiti_acumulado` add up to exactly what the `Vanos` sheet holds, which is the cheapest end-to-end check on the whole pipeline. No CDN is involved, which matters because the app runs under a CSP that would block one;
- `Plotly` appears **and** the artifact is over ~4 MB. Both together are what prove `PANEL_VANOS_SOLO` was used and not `PANEL_VANOS`: the latter carries no plotly.js, so it would come out ~2 MB and render a blank page. A `count()` on the div id alone cannot catch that;
- `.panel-agrup {` appears, which is `PANEL_CSS`. Without it the controls render unstyled — the board still works, so nothing else catches this;
- `"circuitosNombres"` appears. The context ships the 208 distinct circuit names once and an integer index per vano instead of repeating the name 27.390 times, and the JS resolves it through a single `circDe(v)` helper. Its absence means the artifact predates that compaction, and `CTX.circuitos[v]` would put an index number where the circuit name belongs — in the hover, in the downloaded workbook and in the top-10 ranking.

Three more checks guard the full-width rendering, because losing it degrades silently — the board still works, it just renders in a narrow column:
- the figure config carries `responsive: true`. **Match it whitespace-insensitively** — Plotly serializes the config block as `"responsive": true`, with a space after the colon, so a literal `grep '"responsive":true'` returns nothing on a perfectly good artifact (confirmed empirically; it read as a regression when nothing was wrong). Strip spaces before comparing, or match `"responsive":\s*true`. Without this flag the board does not re-fit when the window is resized;
- `width:100%` appears. Plotly emits it into the div because `to_html` gets `default_width='100%'`;
- `width:860px` appears **nowhere**. That was the hardcoded `width=860` in cell 12's layout; if it comes back, `default_width` is overridden and the board pins itself to that many pixels no matter how wide the screen is.

Finally, the vano board is a **6x4 grid** with 25 traces. Assert the two subplots that carry it:
- `Top 10 circuitos por vanos en clase Alto` — the horizontal stacked bar in rows 3-4, cols 3-4 (top 10 circuits by count of vanos in the `Alto` class, drawn as each circuit's percentage split across the four classes, in the K-Means palette);
- `Grupos Circuitos: Vanos en clase Medio-Alto y Alto por circuito` — rows 5-6, full width (one cell via `rowspan: 2`; with a single row the drawing area came out shorter than the block of rotated names hanging below it). It counts **both** critical classes, orders circuits ascending, and colours each bar by which of four ranges its count falls in, cut at **P50 / P75 / P97** — not at the quartiles: the distribution has a long right tail, and with 25/50/75 the top group swallowed a quarter of the circuits and mixed the genuinely critical ones in with the pack. With this cut the red group is the top 3% (7 circuits of 208 on the current base). **Every circuit in the base is plotted**, including those with no events at all in the selected window: they sit at zero on the left and count towards the percentiles. Leaving them out biased the cuts upward, the more so the shorter the range — over Feb–Apr, P50 read 40 looking only at the 158 circuits with events against 24 looking at all 208. Colours are the project's risk semaphore — `rgb(26,150,65)` green, `rgb(242,194,0)` yellow, `rgb(239,108,0)` orange, `rgb(198,40,40)` red — the **same** palette as the K-Means groups, taken from `COLORES_GRUPOS` rather than restated. It used to be a separate scale (`#1a9641`/`#ffd92f`/`#f57f20`/`#d7191c`) so nobody would read an equivalence with the old red ramp of the grouping; once the groups became a semaphore too, that argument inverted — two near-identical semaphores in one figure read as a bug, not as a distinction. What still differs is the UNIT: there a vano, here a circuit, and the subplot title names both by the same four risk words on purpose. Because the cuts are percentiles over a fixed population, the four group SIZES stay near-constant (104 / 53 / 44 / 7) whatever window is picked; what the window changes is which circuits land where and what the cut values are. The three cuts are marked with dotted verticals, and the subplot title names the four ranges by RISK — `Riesgo bajo` / `Riesgo Medio` / `Riesgo Medio-Alto` / `Riesgo Alto` — with how many circuits fall in each. The percentile values themselves live in the hover: "P75" means nothing to whoever operates the network, but the cut is still one hover away. Subplot titles render at 24 px and the figure title at 34 px, both double what they were: the board is meant to be read full-screen. Assert the four hex colours are present and that `rotularFila5` appears: that helper thins the x labels to the real pixel width (184 circuits at a 1000 px window leave 5.2 px per label and the names collide), and without it the axis is unreadable on a narrow screen. Its hover carries the circuit's accumulated UITI (one decimal) and its event total for the selected window; both are drawn there and not on the bars because at 184 circuits each bar is 2.8–7.0 px wide.

Its x axis is deliberately **linear, not categorical**, even though it is labelled with circuit names. On a category axis Plotly reads a numeric x as a *new category*, so the three cut dividers (numeric positions like 93.5, 138.5, 164.5) were drawn as three extra categories glued to the right edge instead of falling between the bars — confirmed empirically. The bars sit at 0..n-1 and the names come from `tickvals`/`ticktext`.

Three more checks guard the full-width rendering, because losing it degrades silently — the boards still work, they just render in a narrow column:
- `"responsive":true` appears **twice**, once per figure. Without it the board does not re-fit when the window is resized;
- `width:100%` appears at least twice (the two figure divs). Plotly emits it into each div because `to_html` gets `default_width='100%'`;
- `width:820px` appears **nowhere**. That was the hardcoded `width=820` in cell 5's layout (and `860` in cell 12's); if either comes back, `default_width` is overridden and the board pins itself to that many pixels no matter how wide the screen is.

Measured on the generated artifact: 952 px of plot at a 1000 px window, 1552 at 1600, 2352 at 2400, with no horizontal overflow at any of the three.

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

~6.1 MB, so it is read once and cached in memory rather than re-downloaded per request,
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
  "description": "Agrupamiento de vanos por UITI acumulado, con top 10 de circuitos (cuaderno 02)",
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

Get `service_principal_client_id` from `databricks apps get <app-name> -o json -p <profile>`, resolve a warehouse per the shared contract section E2, then check each object:
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
- **The bitacora**: its path under `reports/despliegues/`, the final state `cerrar` printed (`COMPLETO`, `COMPLETO CON RESTRICCIONES` or `INCOMPLETO`), and the count of restrictions it holds. Do not soften that state in prose.
- **Every restriction recorded, with who unblocks each one** — reproduce the `resumen` output. A run that ended INCOMPLETO reports what is still blocking, not just what worked.

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
- That the first page load is slow (~6.1 MB, ~1.8 MB gzipped from the Volume) and every later one is cached.
- That `/salud` answers without touching the Volume, so it distinguishes an app failure from a permission failure.
- That the two label CSVs also landed under `.../chec-simulador/reports/reportescircuitos/artifacts/` as a side effect of cells 7 and 14.
- That `git status --porcelain notebooks/` was empty — the repo notebook was never modified.
- That no Delta table, view or Lakeview dashboard was created or touched. The Lakeview dashboard and the Delta tables job were retired, so there is nothing to point to — this family no longer creates tables or views at all.
