---
description: Publica el simulador de riesgo por vano del cuaderno 06 como una Databricks App en una URL fija, servido con Voila sobre un kernel vivo. Precalcula fuera de la app todo lo que hoy se deriva del CSV de 540 MB, de modo que el arranque baje de 2.867 MB a 579 MB y de 909 MB leidos a 94,5 MB. Detecta y repara por su cuenta lo que falte. Pregunta solo el nombre de la app y la URL del workspace destino.
---

Follow this exact sequence when `/app-simulador-vano` is invoked. It publishes
`notebooks/project_flow/06_uiti_vano_explicabilidad_simulador.ipynb` — the per-vano
explainability and risk simulator — at a stable URL, and it is **self-healing**: it inspects
the target workspace first and creates whatever is missing.

## Why this one cannot be a static HTML file

Every other `/app-*` command in this family exports the notebook's own HTML and serves it from
a Volume. That works because `01`–`04` compute everything up front and let the browser filter
it. **`06` cannot**: its whole point is that clicking *Simular* runs a PyTorch MIL model on the
bags the user selected, with the knob values the user typed. There is no precomputable answer —
the input space is 26 simulable variables over up to 10 vanos. The panel is `ipywidgets` end to
end (`go.FigureWidget`, `.observe`, `on_click`, an `asyncio` debounce), so it needs a **live
Python kernel**, not a static document.

Two routes exist and only one is sane:

- **Voila** serves the notebook itself. The notebook stays the single source of truth, and its
  ~1.900 lines of panel logic (cells 11–16) are reused verbatim.
- **A Dash/Streamlit rewrite** would mean re-implementing those 1.900 lines against a different
  callback model, and maintaining two panels that must agree forever. Reject it unless the user
  explicitly asks for a rewrite.

This command uses **Voila**. Note that Voila is **not** on Databricks' list of officially
supported app frameworks (Streamlit, Dash, Gradio, Flask, FastAPI, Uvicorn, Express), but
`app.yaml`'s `command` accepts any process. Streamlit and Dash both drive their UI over
WebSockets and both are supported, so the Apps proxy passes WebSockets — which is what
`ipywidgets` needs. **That is an inference, not a documented guarantee**: section 8 verifies it
against the running app and does not assume it.

## The one design decision that makes this fit: precompute the bundle

Measured on this machine, over the current base, running the notebook's own cells:

| | notebook as written | with the bundle |
|---|---|---|
| bytes read at startup | **909 MB** (CSV 540 + `bolsas_mil_full.joblib` 190 + shapefiles 180) | **94,5 MB** |
| data resident in RAM | **2.867 MB** | **579 MB** |
| interface (figure + widgets) | +69 MB | +69 MB |
| **total per session** | **2.936 MB** | **~648 MB** |
| load time | 7,1 s | 0,3 s (plus 1,8 s of imports) |

A Databricks App is **MEDIUM = 2 vCPU / 6 GB** (0,5 DBU/h) or **LARGE = 4 vCPU / 12 GB**
(1 DBU/h). Voila gives every browser session its own kernel process, so per-session cost is
what sets the ceiling:

- **without the bundle, a MEDIUM app fits exactly ONE session** — two would need 5,9 GB before
  the server and the OS get anything;
- **with the bundle, six or seven** fit on MEDIUM, and roughly fifteen on LARGE.

Where the 2,3 GB goes: cell 4 calls `procesar_dataset_completo` on the 540 MB CSV and costs
**+1.919 MB**, and cell 6 reads three shapefiles for **+326 MB**. Both are pure derivation.
Verified by reading every cell below 9: `context_df` and `Xdf` — the two objects that hold
those megabytes — are referenced **zero times** after cell 9. What survives is small: the
vano×ventana table, the knob catalog, two encoder dicts, and the reduced map traces.

So the bundle carries the *results* and the app never opens the CSV, the shapefiles or the
bolsas artifact.

### Build the bundle locally, not with a job

The other commands in this family submit a Databricks job. **Do not do that here.** A job would
first need the 909 MB of sources mirrored into the Volume and would then spend cluster compute
to produce 94,5 MB. Building locally uploads only the 94,5 MB, spends no Databricks compute, and
guarantees the pieces are mutually consistent because one process produces all of them.

Use the job route only if the user says the source data is not available locally; in that case
run the same builder as a notebook task against the Volume-mirrored inputs.

### Two more levers, both measured

**Memory-map the instance matrix.** `X_inst.npy` is 88 MB of `float32`. Loaded with
`np.load(..., mmap_mode='r')` it costs **+0 MB** of private RSS, and reading 5.000 rows from it
still costs **+0 MB** — the pages live in the OS page cache, so every Voila kernel on the
container shares one copy instead of each holding its own 88 MB.

**That lever only works because of the fix in `mil_simulador_015`.** The five dashboard entry
points (`simular_bolsas`, both `sensibilidad_minmax_*`, `relevancia_hacia_uiti_minimo`,
`plan_hacia_clase_minima`) used to write `np.asarray(X_inst, dtype=np.float64)[filas]`, which
promotes the **whole** matrix before taking a few hundred rows: **176,7 MB reserved and thrown
away on every pass**, against **0,6 MB** for `np.asarray(X_inst[filas], dtype=np.float64)`,
bit-for-bit identical. On a memory-mapped array the old form would also read all 88 MB from disk
on every click and turn a shared mapping into a private copy. The repo now carries the fixed
form and two tests that pin it
(`test_simular_bolsas_only_promotes_the_selected_rows_to_float64`,
`test_no_entry_point_promotes_the_whole_instance_matrix`). **If those tests are failing, stop —
the memory numbers in this command no longer hold.**

## Scope

MUST NOT modify `notebooks/project_flow/06_uiti_vano_explicabilidad_simulador.ipynb` (the shim
is applied to a scratch COPY), MUST NOT create or refresh any Delta table, view or Lakeview
dashboard, and MUST NOT touch the artifacts the other `/app-*` commands publish under
`dashboards/`.

## 0. Ask the user for the two required inputs

Ask, one at a time, and wait for each answer:
1. The name for the Databricks App. The API constrains this to **2–30 characters, lowercase
   alphanumerics and hyphens only**, unique in the workspace (`Simulador Vano` →
   `simulador-vano`). If the answer has spaces, uppercase or accents, propose the normalized
   form and confirm.
2. The Databricks workspace URL (e.g. `https://dbc-xxxxxxxx-xxxx.cloud.databricks.com`).

Do **not** ask which compute size to use — decide it in step 6 from the measured footprint, and
report the choice. Only ask if the user wants more than about six concurrent users.

If a step below finds a missing prerequisite, **do not ask whether to create it** — creating it
is this command's job. Only pause for the two things that genuinely need a human: an expired
OAuth token, and a privilege the profile is not allowed to grant.

## 1. Resolve profile and identity

Follow `.claude/commands/deploy-databricks-dashboard.md` **section 1** verbatim with the URL
from step 0. Carry the resolved `<profile>` everywhere below.

`databricks auth profiles` reports a `Valid` column, but treat it as advisory only — confirm
with a real call:
```
databricks current-user me -p <profile> -o json 2>/dev/null
```

**Never pipe `2>&1` into a JSON parser** anywhere in this command. The CLI intermittently emits
`Databricks skills are not installed...` on **stderr**, and merging it into stdout makes
`json.load` die with `Expecting value: line 1 column 1` on a perfectly healthy call. Use
`2>/dev/null` when parsing, and `2>&1` only when you want to read an error message.

- Success → take `userName` as `<userName>` for every Workspace path below.
- `Error: A new access token could not be retrieved because the refresh token is invalid` → stop
  and ask the user to run this themselves via the `!` prefix, then resume:
  ```
  databricks auth login --profile <profile>
  ```

Confirm the Apps surface exists and supports sizing (verified on CLI v1.8.0, which reports
`--compute-size  Supported values: [LARGE, MEDIUM, XLARGE]`):
```
databricks apps list -p <profile>
databricks apps create --help 2>&1 | grep -- --compute-size
```
If either is missing, stop and tell the user to upgrade the Databricks CLI — do not hand-roll
REST calls.

**Check the app quota before creating anything.** The workspace caps concurrent apps (observed:
three), and an app in `DELETING` still counts against it. `databricks apps list` up front avoids
discovering this after the bundle is already uploaded.

## 2. Preflight — inspect everything, then repair

Run all of these read-only checks **before** changing anything, build an explicit list of what
is missing, report it in one message, then fix each item without asking.

| # | Check | Command | If missing → |
|---|---|---|---|
| 1 | Local model artifact | `ls -l data/models/mil_vano_ventana_v1.pt` | stop: `05_mil_vano_ventana.ipynb` produces it |
| 2 | Local bolsas cache | `ls -l data/derived/bolsas_mil_full.joblib` | stop: same notebook |
| 3 | Local CSV is a real LFS payload | `ls -l data/Indicadores_vano_v3.csv` | `git lfs pull` |
| 4 | Local shapefiles | `ls data/GEO/MVLINSEC.shp` | stop and say so |
| 5 | Volume exists | `databricks fs ls dbfs:/Volumes/workspace/default/chec-simulador -p <profile>` | step 2a |
| 6 | Bundle already uploaded | `databricks fs ls dbfs:/Volumes/workspace/default/chec-simulador/paquete_06 -p <profile>` | step 4 |
| 7 | App exists | `databricks apps list -p <profile>` | step 6 |

Checks 1–4 are local and gate everything: the bundle is built here, so a missing local artifact
is a hard stop with the name of the notebook that produces it. A ~130-byte CSV is an unfetched
Git-LFS pointer, not the data.

Also run the two guard tests before building anything — the bundle's whole value rests on them:
```
.venv/bin/python -m pytest tests/test_mil_simulador_015.py -q
```

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
If this fails on privileges, stop and report exactly that — do not silently pick a different
catalog or schema; every command in this family hardcodes `workspace.default.chec-simulador`.

## 3. Build the bundle

Write the builder into the scratch directory — **not** into the repo. It runs the notebook's
**own** cells 1–9 and freezes the resulting namespace, so the bundle can never drift from what
the notebook computes: if the loading cells change, the bundle follows on the next build.

```python
"""Congela lo que el cuaderno 06 deriva al arrancar, para que la app no lo rehaga.

Corre las celdas 1..9 del propio cuaderno y guarda el resultado. No reimplementa nada:
si esas celdas cambian, el paquete cambia con ellas.
"""
import contextlib, hashlib, io, json, os, pathlib, sys, time

RAIZ = pathlib.Path(__file__).resolve().parents[N]      # ajusta N: la raiz del repo
SALIDA = pathlib.Path(sys.argv[1])
SALIDA.mkdir(parents=True, exist_ok=True)
os.chdir(RAIZ / 'notebooks' / 'project_flow')

CUADERNO = RAIZ / 'notebooks/project_flow/06_uiti_vano_explicabilidad_simulador.ipynb'
nb = json.loads(CUADERNO.read_text('utf-8'))
ns = {'__name__': '__main__'}
t0 = time.perf_counter()
for i in range(1, 10):
    c = nb['cells'][i]
    if c['cell_type'] == 'code':
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(''.join(c['source']), f'celda{i}', 'exec'), ns)
print(f'celdas 1-9 en {time.perf_counter() - t0:.1f} s')

import joblib, numpy as np, shutil

ns['TABLA'].to_parquet(SALIDA / 'tabla.parquet', compression='zstd')
# float32 y contiguo: es el dtype que el modelo usa igual, y asi el .npy se puede
# mapear en memoria y compartirse entre los kernels de Voila.
np.save(SALIDA / 'X_inst.npy', np.ascontiguousarray(ns['X_INST'], dtype=np.float32))
(SALIDA / 'geo.json').write_text(json.dumps(
    {'geo': ns['GEO_POR_CIRCUITO'], 'trafos': ns['TRAFOS'], 'switches': ns['SWITCHES']},
    separators=(',', ':')))
joblib.dump({'knobs': ns['KNOBS'], 'feature_names': ns['feature_names'],
             'label_encoders': ns['label_encoders'],
             'max_values_imputed': ns['max_values_imputed'],
             'bag_index': ns['BAG_INDEX'], 'features_mil': list(ns['FEATURES_MIL']),
             'ventanas': ns['VENTANAS']},
            SALIDA / 'catalogo.joblib', compress=3)
for origen in (RAIZ / 'data/derived/geometrias_014.json',
               RAIZ / 'data/models/mil_vano_ventana_v1.pt',
               RAIZ / 'data/COSTOS ITEMS CONTRATOS.xlsx'):
    shutil.copy2(origen, SALIDA / origen.name)

# El manifiesto es lo que permite comprobar en el arranque de la app que el paquete
# esta completo y que el modelo es el mismo con el que se construyo.
manifiesto = {'construido_en': time.strftime('%Y-%m-%d %H:%M:%S'),
              'cuaderno_sha1': hashlib.sha1(CUADERNO.read_bytes()).hexdigest(),
              'n_bolsas': len(ns['BAG_INDEX'].keys),
              'n_instancias': int(ns['X_INST'].shape[0]),
              'n_features': len(ns['FEATURES_MIL']),
              'archivos': {}}
for f in sorted(SALIDA.iterdir()):
    if f.name != 'manifiesto.json':
        manifiesto['archivos'][f.name] = {
            'bytes': f.stat().st_size,
            'sha256': hashlib.sha256(f.read_bytes()).hexdigest()}
(SALIDA / 'manifiesto.json').write_text(json.dumps(manifiesto, indent=1))
total = sum(v['bytes'] for v in manifiesto['archivos'].values())
print(f'{len(manifiesto["archivos"])} archivos | {total / 1024 / 1024:.1f} MB')
```

Run it with the project interpreter (`.venv/bin/python`, which is where `geopandas`, `torch` and
the project packages live) and assert the result: **7 files, ~94,5 MB**, dominated by
`X_inst.npy` at 88,1 MB. Fail if the total is under 50 MB — that means a cell silently produced
an empty object.

`git status --porcelain notebooks/project_flow/06_uiti_vano_explicabilidad_simulador.ipynb` MUST
be empty afterwards. The builder only reads the notebook; if it reports a change, stop.

## 4. Upload the bundle

```
databricks fs mkdir dbfs:/Volumes/workspace/default/chec-simulador/paquete_06 -p <profile>
databricks fs cp <scratch>/paquete -r dbfs:/Volumes/workspace/default/chec-simulador/paquete_06 --overwrite -p <profile>
```
Then list it back and compare the byte counts against `manifiesto.json`. `fs cp -r` drags
`.DS_Store` along on macOS — delete it from the Volume if it appears, since the app's startup
check walks the manifest and an extra file is noise it will report.

## 5. Stage the app source

Five items in the scratch directory, deliberately not added to the repo.

**`06_simulador.ipynb`** — the shimmed COPY of the notebook. Strip every code cell's `outputs`
and `execution_count` first (the repo copy is 245 KB; a locally-executed one re-embeds
megabytes). Keep the `jupyter.source_hidden` metadata and `hide-input` tags that are already
there — Voila hides input anyway (`strip_sources` defaults to true), but they keep the file
honest if someone opens it in Jupyter.

Apply exactly these edits, asserting each match is **unique** and failing loudly if not. A
silently-skipped edit produces a notebook that dies deep inside the app with no useful log.

**Edit 1 — cell 1, drop the two imports the app does not need.**
```python
import geopandas as gpd                                    → (delete the line)
from chec_impacto.data import procesar_dataset_completo     → (delete the line)
```
`geopandas` is never touched again once the map traces come from the bundle. Deleting the
pipeline import saves nothing measurable on its own — `mil_persistencia` pulls the same
transitive tree (`sklearn`, `shap`, `optuna`, `numba`, `matplotlib`) anyway, which is why they
stay in `requirements.txt` below — but leaving an import of a module the app must never call is
how someone reintroduces the 540 MB read later. **Leave the `sys.modules` purge loop and the
`_sonda` / `assert hasattr(_sonda, 'caja')` probe completely untouched.**

**Edit 2 — cell 1, add the bundle root right after the `sys.path` block.** Cell 1 imports
`asyncio`, `gc`, `sys`, `time` and `pathlib` but **neither `os` nor `json`**, and edits 2 and 6
need both — add them to the import block in the same edit:
```python
import json
import os
...
PAQUETE = Path(os.environ.get('PAQUETE_06', '/tmp/paquete_06'))
```

**Do not touch the `ROOT` walk-up loop above it.** It climbs from the working directory looking
for a `src/` folder, and step 5's layout is chosen so that it lands on the app root on the first
try — which is why the packages go to `<base>/src/...` and `scripts` to `<base>/scripts`, exactly
mirroring the repo. Flattening them next to `arranque.py` instead would send that loop climbing
to `/`, put `/` and `/src` on `sys.path`, and every project import would fail. Verify the layout
rather than trusting it: the notebook's own first-cell `_sonda` probe fails loudly if
`chec_local_interpreter` did not import from where you think.

**Edit 3 — cell 3, read the geometry from the bundle instead of re-extracting it.** Replace
```python
GEOMETRIAS_PATH = DEFAULT_OUTPUT_PATH
if not GEOMETRIAS_PATH.exists():
    extraer_geometrias_014(DEFAULT_NOTEBOOK_PATH, GEOMETRIAS_PATH)
```
with
```python
GEOMETRIAS_PATH = PAQUETE / 'geometrias_014.json'
```
**Keep the sha1 verification and the assert that follow.** They are what guarantees the two maps
share one KMeans geometry, they cost microseconds, and the bundle is exactly the thing that
could go stale.

**Edit 4 — cell 4, replace the whole `procesar_dataset_completo` block** (from `datos =` through
`del datos` / `gc.collect()` / the `print`) with:
```python
_cat = joblib.load(PAQUETE / 'catalogo.joblib')
feature_names = list(_cat['feature_names'])
label_encoders = _cat['label_encoders']
max_values_imputed = _cat['max_values_imputed']
print(f'{len(feature_names)} features (del paquete; el CSV no se abre en la app)')
```
Keep `DATA_PATH`, `VARIABLES_SELECCION_PATH` and `MODEL_DIR` defined but repoint the two that
are still read:
```python
COSTOS_ITEMS_PATH = PAQUETE / 'COSTOS ITEMS CONTRATOS.xlsx'
MODEL_DIR = PAQUETE
```
`context_df`, `Xdf` and `n_filas_x` must **not** be defined. That is the point of the edit, and
it is safe: they are referenced zero times below cell 9.

**Edit 5 — cell 5, memory-map the instance matrix instead of loading the bolsas artifact.**
Replace the `RUTA_BOLSAS_MIL` assert, `cargar_bolsas`, `X_INST = np.asarray(...)`, `del BOLSAS`
block with:
```python
# `mmap_mode='r'` y no una carga normal: los 88 MB quedan en el cache de paginas del
# sistema, asi que TODOS los kernels de Voila del contenedor comparten una sola copia
# en vez de llevar 88 MB privados cada uno. Medido: leer 5.000 filas cuesta +0 MB.
X_INST = np.load(PAQUETE / 'X_inst.npy', mmap_mode='r')
FEATURES_MIL = list(_cat['features_mil'])
BAG_INDEX = _cat['bag_index']
```
Keep `RUTA_MODELO_MIL = MODEL_DIR / 'mil_vano_ventana_v1.pt'`, `cargar_modelo_mil(...,
device='cpu', ...)` and **all four asserts** that follow — the geometry comparison against
`GEOMETRIA_014` and the `FEATURES_MIL[:len(feature_names)]` check are what stop a stale bundle
from silently repainting the map with another model's classes.

**Edit 6 — cell 6, load the table and the traces instead of deriving them.** Replace
`VENTANAS = construir_ventanas(context_df['FECHA'])` and
`TABLA = construir_tabla_vano_ventana(context_df, VENTANAS)` with:
```python
VENTANAS = _cat['ventanas']
TABLA = pd.read_parquet(PAQUETE / 'tabla.parquet')
```
and replace the whole shapefile block — from `def _norm_id(...)` through `del _lineas, _utiles` —
with:
```python
_geo = json.loads((PAQUETE / 'geo.json').read_text('utf-8'))
GEO_POR_CIRCUITO, TRAFOS, SWITCHES = _geo['geo'], _geo['trafos'], _geo['switches']
```
**Keep everything else in the cell**: `mask_para`, `clases_para`, `CIRCUITOS`,
`VANOS_POR_CIRCUITO`, `VENTANAS_POR_CIRCUITO` and the `DATOS_VENTANA` loop all derive from
`TABLA` in well under a second and would only bloat the bundle. Add `import json` to cell 1 if
it is not already there.

**Edit 7 — cell 7, take the knob catalog from the bundle.** Replace the `build_knobs(...)` call
with `KNOBS = _cat['knobs']`, keeping the `print`. `build_knobs` needs `Xdf` — the full feature
frame — which is exactly the object edit 4 removed.

After the edits, `compile()` every code cell. That catches syntax damage but **not** a name
used before it is defined, so also assert that the strings `context_df`, `Xdf` and
`procesar_dataset_completo` appear **nowhere** in the staged copy.

**`app.yaml`:**
```yaml
command:
  - "python"
  - "arranque.py"
env:
  - name: "PAQUETE_06"
    value: "/tmp/paquete_06"
```

**`requirements.txt`** — derived by importing the app's real module set and listing what landed
in `site-packages`, not by guessing:
```
voila
jupyter-server
ipywidgets
anywidget
plotly
pandas
numpy
scipy
scikit-learn
torch
shap
optuna
matplotlib
joblib
pyarrow
openpyxl
cloudpickle
databricks-sdk
```
`anywidget` is not optional — `plotly>=6`'s `go.FigureWidget` raises `ImportError` without it,
and the entire dashboard is a `FigureWidget`. `shap`, `optuna`, `matplotlib` and `numba` (pulled
by `shap`) are there because `chec_impacto.models.mil_persistencia` imports them transitively —
confirmed by listing `sys.modules` after the minimal import set. **`geopandas` is deliberately
absent.** Trimming further than this is what caused a `ModuleNotFoundError` on `optuna` in a
sibling command; re-run the import audit before removing anything.

**`arranque.py`** — downloads the bundle to the container's local disk, then execs Voila:
```python
"""Baja el paquete del Volume al disco local y arranca Voila sobre el cuaderno.

Al disco local y no leyendo /Volumes directamente: el montaje FUSE dentro del
contenedor de una app no esta garantizado, y ademas el mapeo en memoria de X_inst.npy
necesita un archivo local de verdad para que el cache de paginas lo comparta entre los
kernels de Voila.
"""
import json, os, pathlib, subprocess, sys, time

from databricks.sdk import WorkspaceClient

VOLUME = os.environ.get('VOLUME_06',
                        '/Volumes/workspace/default/chec-simulador/paquete_06')
DESTINO = pathlib.Path(os.environ.get('PAQUETE_06', '/tmp/paquete_06'))
PUERTO = os.environ.get('DATABRICKS_APP_PORT', '8000')

DESTINO.mkdir(parents=True, exist_ok=True)
w = WorkspaceClient()
t0 = time.perf_counter()
manifiesto = json.loads(w.files.download(f'{VOLUME}/manifiesto.json').contents.read())
for nombre, meta in manifiesto['archivos'].items():
    local = DESTINO / nombre
    if local.exists() and local.stat().st_size == meta['bytes']:
        continue                      # un reinicio del proceso no vuelve a bajarlo
    with open(local, 'wb') as f:
        f.write(w.files.download(f'{VOLUME}/{nombre}').contents.read())
    if local.stat().st_size != meta['bytes']:
        raise SystemExit(f'{nombre}: {local.stat().st_size} bytes, '
                         f'se esperaban {meta["bytes"]}')
print(f'paquete listo en {time.perf_counter() - t0:.1f} s '
      f'({sum(m["bytes"] for m in manifiesto["archivos"].values()) / 1024 / 1024:.1f} MB) '
      f'| construido {manifiesto["construido_en"]}', flush=True)

os.execvp('voila', [
    'voila', str(pathlib.Path(__file__).parent / '06_simulador.ipynb'),
    f'--port={PUERTO}', '--no-browser', '--Voila.ip=0.0.0.0',
    '--VoilaConfiguration.show_tracebacks=True',
    # Un kernel caliente esperando: el primer visitante no paga los 2,1 s de imports
    # ni los 0,3 s del paquete.
    '--preheat_kernel=True', '--pool_size=1',
    # Cada sesion son ~648 MB. Una pestania olvidada los retiene hasta que se recicla,
    # y `cull_connected` es lo que hace que una pestania ABIERTA pero quieta tambien
    # cuente: sin el, un navegador dejado abierto nunca libera su kernel.
    '--MappingKernelManager.cull_idle_timeout=900',
    '--MappingKernelManager.cull_interval=120',
    '--MappingKernelManager.cull_connected=True',
])
```
`os.execvp` and not `subprocess.run`: Voila must become PID 1's child directly so the platform's
signals reach it and the launcher leaves no resident copy of itself behind.

`--preheat_kernel`, `--pool_size` and the two `MappingKernelManager.cull_*` settings are
documented Voila CLI options. `cull_connected` comes from `jupyter-server`'s
`MappingKernelManager`, not from Voila's own page — if the installed version rejects it, drop
that one flag and keep the rest; the cost is that an open-but-idle tab holds its kernel.

**Do not pass `--base_url`.** Voila's reverse-proxy documentation uses it because Apache mounts
the app under a subpath; Databricks Apps proxies at the root, and a `base_url` there would make
every asset 404. That documentation is also where the diagnostic for step 8 comes from: the
widget round-trip runs over `/api/kernels/`, so if the page renders but nothing reacts, that is
the path the proxy is dropping.

**The two source packages.** The app needs `chec_impacto`, `chec_local_interpreter` and
`scripts` (the last one is not optional — `ventanas_015.py` imports
`scripts.extract_geometrias_014` **at module import time**). Mirror them into the app source
folder with `databricks sync`, which — unlike `workspace import-dir`, used by the sibling
commands — has an exclude mechanism, so `__pycache__` never reaches the workspace:
```
databricks sync src/chec_local_interpreter <base>/src/chec_local_interpreter --exclude '**/__pycache__/**' --full -p <profile>
databricks sync src/chec_impacto           <base>/src/chec_impacto           --exclude '**/__pycache__/**' --full -p <profile>
databricks sync scripts                    <base>/scripts                    --exclude '**/__pycache__/**' --full -p <profile>
```
with `<base> = /Workspace/Users/<userName>/databricks-integration/apps/<app-name>`. **The
`src/` level is load-bearing, not cosmetic** — see edit 2: it is what makes the notebook's own
`ROOT` walk-up resolve, so the first cell needs no shim at all. `scripts` sits at the root
because that is where the repo has it and where `ROOT` puts it on `sys.path`.

Upload the four flat files with `--format RAW` (`import-dir` reinterprets
`.py` as notebooks):
```
databricks workspace mkdirs <base> -p <profile>
databricks workspace import <base>/arranque.py       --file <scratch>/arranque.py       --format RAW --language PYTHON --overwrite -p <profile>
databricks workspace import <base>/app.yaml          --file <scratch>/app.yaml          --format RAW --overwrite -p <profile>
databricks workspace import <base>/requirements.txt  --file <scratch>/requirements.txt  --format RAW --overwrite -p <profile>
databricks workspace import <base>/06_simulador.ipynb --file <scratch>/06_simulador.ipynb --format JUPYTER --overwrite -p <profile>
```

## 6. Create the App, declaring the Volume as a resource

Pick the size from the measured footprint, and say why in the report:

- **MEDIUM (2 vCPU / 6 GB, 0,5 DBU/h)** — the default. ~648 MB per session leaves room for six
  or seven concurrent users after the server and OS overhead.
- **LARGE (4 vCPU / 12 GB, 1 DBU/h)** — only if the user said more than about six people will
  use it at once. The extra vCPUs also halve the wall-clock of a *Simular* click on a large
  selection, since the MIL model runs on CPU (`device='cpu'` is deliberate in cell 5: moving
  decades of instances to a GPU costs more than it saves).

```
databricks apps create --compute-size MEDIUM --json '{
  "name": "<app-name>",
  "description": "Simulador de riesgo por vano y explicabilidad (cuaderno 06)",
  "resources": [{
    "name": "volumen-chec-simulador",
    "description": "Volume con el paquete precalculado del cuaderno 06",
    "uc_securable": {
      "securable_type": "VOLUME",
      "securable_full_name": "workspace.default.chec-simulador",
      "permission": "READ_VOLUME"
    }
  }]
}' -p <profile>
```
The `uc_securable` resource makes Databricks apply the volume grant itself while provisioning
the app's service principal — confirmed on a cold workspace by a sibling command. Verify it
landed rather than assuming; the service principal is new on every re-creation, so a grant left
by a previous app of the same name is worthless:
```
databricks api post /api/2.0/sql/statements -p <profile> --json '{"warehouse_id":"<warehouse_id>","statement":"SHOW GRANTS `<sp_client_id>` ON VOLUME workspace.default.`chec-simulador`","wait_timeout":"30s"}'
```
Wrap the payload in **single** quotes — escaping backticked identifiers inside a double-quoted
string breaks in zsh. If the app already exists, attach the same resource with
`databricks apps update <app-name> --json '<same body without name>'`.

If `uc_securable` fails, fall back to `.claude/commands/app-agrupamiento-vanos-circuitos.md`
**section 6a**, including its warning that Claude Code's auto-mode classifier denies `GRANT`
through `databricks api post` — hand that command to the user with the `!` prefix rather than
working around it.

## 7. Deploy

**Wait for the app's compute to reach `ACTIVE` first** — deploying against a still-provisioning
app fails with `Cannot deploy app <name> as it is not in RUNNING state`:
```
for i in $(seq 1 30); do
  ST=$(databricks apps get <app-name> -p <profile> -o json | python3 -c "import json,sys; print((json.load(sys.stdin).get('compute_status') or {}).get('state'))")
  echo "[$i] compute=$ST"; [ "$ST" = "ACTIVE" ] && break; command sleep 20
done
databricks apps deploy <app-name> --source-code-path /Workspace/Users/<userName>/databricks-integration/apps/<app-name> -p <profile>
```
Use `command sleep` — a bare foreground `sleep` is blocked in this harness.

Expect this deploy to be **slower than every other app in this family**: `pip install torch`
alone dominates, and `shap`/`numba` build behind it. Budget ten minutes before treating it as
stuck. On anything other than `SUCCEEDED`, read `databricks apps logs <app-name> -p <profile>`
before touching anything.

## 8. Verify — and do not assume the WebSocket works

```
databricks apps get <app-name> -o json -p <profile>
```
Require all three: `compute_status: ACTIVE`, `app_status: RUNNING`,
`active_deployment.status: SUCCEEDED`. Capture `url` verbatim — never fabricate one.

Then read the logs and confirm, in order:
1. `paquete listo en N s (94.5 MB) | construido <fecha>` — the bundle downloaded and every file
   matched its manifest size. Absent → the Volume grant did not land; go back to step 6;
2. Voila's own startup line, and **no** `ModuleNotFoundError`. The likely offender is a package
   trimmed out of `requirements.txt`;
3. no `KeyError`/`NameError` naming `context_df` or `Xdf` — that means a shim edit was skipped.

**The check that actually matters is the browser, and it cannot be done from here.** Ask the
user to open the URL and confirm three things, because each fails differently:
- the panel and both maps render → the kernel started and the bundle loaded;
- **clicking a vano on the base map toggles its checkbox** → the WebSocket round-trip works.
  This is the one that would fail if the Apps proxy did not pass WebSockets, and it fails
  *silently*: the page looks perfect and simply does not react. If it does fail, the app is not
  fixable from the Voila side — report it and stop, do not start a Dash rewrite without asking;
- clicking **Simular** returns a result in a few seconds → the MIL model runs on the mapped
  matrix. Measured locally: 4,97 s for a full-circuit selection before the batching work, 1,41 s
  for the plan afterwards.

## 9. Report back

Tell the user, in their language:
- The app URL, the app name, the compute size **and why that size**, and the profile used.
- **Everything the preflight found missing and what was done about it** — the headline of a cold
  run.
- The bundle: where it lives, its measured size, and its `construido_en` timestamp.
- **How to refresh after re-running notebook 05 or changing the data**: rebuild the bundle
  (step 3), re-upload it (step 4), and restart the app. No redeploy is needed unless the
  notebook itself changed — the app carries no data of its own.
- The concurrency ceiling in plain terms: about six or seven simultaneous users on MEDIUM, and
  that an abandoned browser tab releases its ~648 MB after 15 minutes idle.
- That the first visitor does not wait, because one kernel is kept warm.
- That `git status --porcelain notebooks/project_flow/` was empty — the repo notebook was never
  modified.
- That no Delta table, view or Lakeview dashboard was created or touched.
