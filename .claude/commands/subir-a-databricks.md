---
description: Migra/sincroniza el resto de los activos locales del proyecto (data/, ambos paquetes fuente, los 9 notebooks de project_flow y los reportes de interpretabilidad descubiertos en tiempo de ejecución) al mismo Volume/workspace de Databricks usado por /deploy-databricks-dashboard, preguntando solo la URL del workspace destino.
---

Follow this exact sequence when `/subir-a-databricks` is invoked. It extends the Volume/Workspace layout already created by `/deploy-databricks-dashboard` (same `workspace.default.chec-simulador` Volume, same `/Workspace/Users/<userName>/databricks-integration/...` code area) with everything that command does NOT already migrate: the full `data/` tree, both source packages, the 9 `notebooks/project_flow/*.ipynb` notebooks, and any HTML files currently under `reports/interpretability/html/`. It reuses that command's profile, warehouse, and freshness-check logic by explicit cross-reference — read `.claude/commands/deploy-databricks-dashboard.md` when this doc says so, do not re-derive that logic. This touches shared workspace state (uploads files, may run a job, publishes a dashboard), so confirm with the user before any step that spends compute or creates something visible to others.

**Out of scope**: this command MUST NOT provision, reference, or deploy any Databricks Apps resource, nor any static-website report-serving mechanism. Reports are uploaded as plain files to the Volume (step 7) — nothing more.

## 0. Ask the user for the one required input

Ask, and wait for the answer:
1. The Databricks workspace URL (e.g. `https://dbc-xxxxxxxx-xxxx.cloud.databricks.com`).

Do not ask for a dashboard name here — step 8 reuses whatever dashboard already exists from a prior `/deploy-databricks-dashboard` run, or asks at that point only if none exists yet. Do not ask about profile, warehouse, or catalog up front — those resolve automatically below.

## 1. Resolve profile and warehouse (reuse, do not re-derive)

Follow `.claude/commands/deploy-databricks-dashboard.md` **section 1** ("Resolve a CLI profile for that workspace") and **section 2** ("Resolve a SQL warehouse") verbatim, using the workspace URL from step 0. Carry forward the resolved `<profile>` and `<warehouse_id>` for every command below.

- Matching profile found → use it.
- No matching profile → tell the user to run `databricks auth login --host <workspace-url>` via the `!` prefix (interactive OAuth, cannot be run for them), then re-resolve.

Also get the profile's own user identity, needed for every Workspace path below:
```
databricks current-user me -p <profile>
```
Use the returned `userName` in place of `<userName>` everywhere in this document.

## 2. Reuse the `circuit_clustering` freshness gate

Follow `.claude/commands/deploy-databricks-dashboard.md` **section 3**'s `criticidad`-vs-`CRITICALITY_GROUP_LABELS` freshness check (the `SELECT DISTINCT criticidad FROM workspace.default.circuit_clustering` comparison against `src/chec_local_interpreter/plotting.py`). Record the result — fresh or stale — as `<tables_status>`. This value gates step 6; do not run that command's own step 4 (table rebuild) here, only its check.

If `circuit_clustering` does not exist at all yet, treat `<tables_status>` as stale (step 6 will build it from scratch).

## 3. Upload the `data/` tree to the Volume

Mirror the full local `data/` directory to the Volume as-is — no format conversion, no new Delta tables here (the existing `uiti_vano_tables.py` job, reused unmodified in step 6, remains the only tabular representation):

```
databricks fs cp -r data dbfs:/Volumes/workspace/default/chec-simulador/data --overwrite -p <profile>
```

Exclude before uploading (do not copy these): `.DS_Store`, `.gitkeep`, `.openmeteo_cache.sqlite` (regenerable HTTP cache, not source data).

Document the hybrid nature of this upload to the user:

| File / pattern | Treatment |
|---|---|
| `Indicadores_vano_v3.csv` | Uploaded as-is; ALSO the sole Delta-conversion candidate (materialized by the step-6 job into `indicadores_vano` / `circuit_clustering` / `circuit_geo`) |
| `GEO/*` (all shapefile sidecars) | Uploaded as-is, binary, no conversion |
| `graphs/*.npy`, `graphs/*.json` | Uploaded as-is |
| `models/*.zip`, `models/manifest.sha256.json` | Uploaded as-is |
| `optuna/*.journal`, `optuna/*.pkl` | Uploaded as-is |
| `COSTOS ITEMS CONTRATOS.xlsx`, `Variables_seleccion.xlsx` | Uploaded as-is |
| `site/data/variables.json` (extra item — `site/` is otherwise NOT migrated by this command) | Uploaded separately into the same Volume data folder, since notebook `07` needs it as a required read-only input: `databricks fs cp site/data/variables.json dbfs:/Volumes/workspace/default/chec-simulador/data/variables.json --overwrite -p <profile>` |

## 4. Verbatim import of both source packages

Same `import-dir --overwrite` pattern `/deploy-databricks-dashboard` section 4.3 already uses for `chec_local_interpreter` — repeat it here for that package AND add `chec_impacto` (which that command does not upload):

```
databricks workspace import-dir src/chec_local_interpreter /Workspace/Users/<userName>/databricks-integration/chec_local_interpreter_src/chec_local_interpreter --overwrite -p <profile>
databricks workspace import-dir src/chec_impacto /Workspace/Users/<userName>/databricks-integration/chec_impacto_src/chec_impacto --overwrite -p <profile>
```

If `import-dir` rejects a non-notebook file in either package, fall back to individual `databricks workspace import <target_path> --file <local_file> --language PYTHON --format RAW --overwrite -p <profile>` calls for the rejected files, same fallback `/deploy-databricks-dashboard` documents.

Also upload the shared `requirements.txt` next to the two package roots, so the notebooks in step 5 can `%pip install -r` it from the Volume-relative bootstrap:
```
databricks workspace import /Workspace/Users/<userName>/databricks-integration/requirements.txt --file requirements.txt --language PYTHON --format RAW --overwrite -p <profile>
```

## 5. Notebook bootstrap shim (staged copies only — never touch the originals)

**Hard invariant**: every notebook uploaded in this step is a modified COPY prepared in a scratch location (e.g. `/private/tmp/.../scratchpad/`), never the file under `notebooks/project_flow/` in this repo. Only the notebook's bootstrap cell(s) — the code that computes where the repo/data/`src` live — is rewritten in the copy. All other cells (markdown, analysis, outputs) stay byte-identical to the repo original. After this step finishes, `git status --porcelain notebooks/project_flow/` in this repo MUST show zero changes — if it does not, something wrote to the wrong path; stop and fix that before continuing.

The 9 notebooks fall into 3 bootstrap variants.

**General rule (applies to all 3 variants — corrects a defect a second `sdd-verify` pass found: the previous version of this doc deleted each bootstrap cell's downstream-referenced path variables along with the git/path-walk logic, which would raise `NameError` in Databricks for 5 of the 9 notebooks)**: the shim replaces ONLY the root-resolution logic — the `resolve_project_root()` / `find_repo_root()` function + its call (Variant A / 07), or the `Path.cwd()` walk-up loop (Variant B / C) — plus the `sys.path`-insertion block that immediately follows it. **Every other line already present in that same bootstrap cell is left completely unchanged**, and so is every later cell that references the root variable or any name derived from it. This works because the replacement always **aliases the exact same root-variable name the notebook already used** (`PROJECT_ROOT` for 01-06, `REPO_ROOT` for 07, `ROOT` for 08/09) to `DATA_DIR.parent` — so any existing `<root_var> / "data" / ...` expression still resolves to `DATA_DIR / ...`, any `<root_var> / "reports" / ...` expression still resolves to a Volume `reports/` subfolder, etc., without having to hunt down and individually rewrite every downstream reference.

Canonical replacement block (swap in for the root-resolution + sys.path portion only; `<root_var>` is the notebook's own name per the per-variant note below):
```python
DATA_DIR = Path("/Volumes/workspace/default/chec-simulador/data")
<root_var> = DATA_DIR.parent
# --- only for notebooks that import chec_impacto / chec_local_interpreter (all except 01 and 08) ---
for _p in ("/Workspace/Users/<userName>/databricks-integration/chec_impacto_src",
           "/Workspace/Users/<userName>/databricks-integration/chec_local_interpreter_src"):
    if _p not in sys.path:
        sys.path.insert(0, _p)
```
(`%pip install -r /Workspace/Users/<userName>/databricks-integration/requirements.txt` stays a separate, unmodified cell where the notebook already has one.)

**Variant A — full git bootstrap (`02`, `03`, `04`, `05`, `06`)**: `<root_var>` = `PROJECT_ROOT`. These notebooks define `resolve_project_root()` (which `git clone`s `REPO_URL`/`REPO_BRANCH` when no local checkout is found), `install_project_requirements()` (subprocess `pip install -r requirements.txt`), and `ensure_lfs_data()` (subprocess `git lfs pull` + pointer-file check for `Indicadores_vano_v3.csv`). Remove those 3 function definitions, their 3 calls (`PROJECT_ROOT = resolve_project_root()`, `install_project_requirements(PROJECT_ROOT)`, `ensure_lfs_data(PROJECT_ROOT)`), and the `SRC_PATH = PROJECT_ROOT / "src"` / `sys.path.insert` block, replacing all of that with the canonical block above. Leave `os.chdir(PROJECT_ROOT)` and every notebook-specific line after it (in the same cell, and in later cells) completely untouched — this is what keeps `02`'s `OPTUNA_DIR` (referenced downstream in its optuna-search cell), `03`'s `OPTUNA_DIR`/`study_paths` (referenced downstream), `04`'s `MODEL_DIR`/`RESULTS_DIR`/`SITE_RESULTS_DIR`/`NOMBRE_MODELO` (referenced downstream), `05`'s downstream `PROJECT_ROOT` reference (the cell computing `GRAPH_OUTPUT_DIR`), and `06`'s downstream `RESULTS_DIR`/`PROJECT_ROOT` reference all working without any further change. (`05_mgcecdl_circuit_analysis.ipynb`'s bootstrap cell is byte-for-byte the same `resolve_project_root`/`install_project_requirements`/`ensure_lfs_data` shape as 02/03/04/06 — it belongs here, not in Variant B.)

**Variant B — path-var (`01`, `09`)**: `<root_var>` = `PROJECT_ROOT` for `01`, `ROOT` for `09`. Both compute a project root by walking up from `Path.cwd()`, with no git-clone or subprocess logic.
- `01`: remove only the `resolve_project_root()` function definition and its call (`PROJECT_ROOT = resolve_project_root()`); no `sys.path` block is needed (01 never imports `chec_impacto`/`chec_local_interpreter`). Leave `FECHA_FORMAT`, `INPUT_PATH`, `OUTPUT_PATH`, and `Xdata = pd.read_csv(INPUT_PATH)` untouched in the same cell — they already derive from `PROJECT_ROOT` and keep resolving correctly through the alias, which is what makes cells 14 and 17's direct `PROJECT_ROOT` references (the Open-Meteo cache path and the final `Indicadores_vano_v3.csv` output path) keep working without modification.
- `09`: remove only the `ROOT = Path.cwd().resolve()` walk-up loop and the `src_path = str(ROOT / "src")` / `sys.path.insert` lines, replacing both with the canonical block (including the `sys.path` insert, since 09 does import both packages). Leave every other line of that cell, and cell 4's `DATA_PATH`, `VARIABLES_SELECCION_PATH`, `MODEL_DIR`, `OUTPUT_DIR` (all `ROOT`-derived), completely untouched.

`07_graph_preserved_connections_uiti_vano.ipynb` is a special case, kept as its own dedicated shim (not the generic block above): its root variable is `REPO_ROOT` (and its `MGCECDL_PROJECT_ROOT`, originally just `REPO_ROOT` under another name), and its bootstrap cell locates `site/data/variables.json` rather than `src/`. Its later cells also write interactive HTML to `site/assets/site/results/...` (an output tree this command never uploads and Databricks has no reason to populate, since that HTML is already published through the project's separate GitHub Actions/Pages channel).

**Correction (post-third-verify)**: 07's bootstrap cell (cell 2) does MORE than compute the root — it also carries 6 module-level imports (`json`, `os`, `numpy as np`, `networkx as nx`, `from openpyxl import load_workbook`, `from pyvis.network import Network`) and a `MODE_COLORS` dict, all consumed verbatim by unchanged cells 3, 5, and 6. A prior pass wholesale-replaced the entire cell, silently dropping all 7 of those and producing a `NameError` on `json` (cell 6's first executable line) and, in sequence, on `os`, `np`, `nx`, `load_workbook`, `Network`, and `MODE_COLORS`. The fix below follows the exact same general principle used for every other notebook: replace ONLY the actual root-resolution logic — the `find_repo_root()` function definition and its call (`REPO_ROOT = find_repo_root()`) — and leave every import and the `MODE_COLORS` dict completely untouched. Replace just that function+call in the copy with this shim (everything else in the cell — the 8 `import`/`from ... import` lines at the top, and the `MODE_COLORS` dict at the bottom — stays byte-identical to the original):

```python
# %pip install networkx pyvis openpyxl   (kept as its own separate cell, unchanged)
import json
import os
import sys
from pathlib import Path

import numpy as np

import networkx as nx
from openpyxl import load_workbook
from pyvis.network import Network

# --- only this block replaces find_repo_root()/REPO_ROOT = find_repo_root() ---
for _p in ("/Workspace/Users/<userName>/databricks-integration/chec_impacto_src",
           "/Workspace/Users/<userName>/databricks-integration/chec_local_interpreter_src"):
    if _p not in sys.path:
        sys.path.insert(0, _p)
DATA_DIR = Path("/Volumes/workspace/default/chec-simulador/data")
MGCECDL_PROJECT_ROOT = DATA_DIR.parent  # so MGCECDL_PROJECT_ROOT / "data" / "Variables_seleccion.xlsx" still resolves to DATA_DIR / "Variables_seleccion.xlsx"
REPO_ROOT = MGCECDL_PROJECT_ROOT  # alias — cell 3's resolve_selection_path() still references REPO_ROOT directly in its `candidates` list (eagerly evaluated, so it must exist even if never chosen); the original notebook already had `MGCECDL_PROJECT_ROOT = REPO_ROOT`, i.e. both names always held the same value
JSON_PATH = DATA_DIR / "variables.json"  # uploaded as an extra item in step 3
OUTPUT_DIR = DATA_DIR.parent / "outputs" / "graphs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
FULL_OUTPUT = OUTPUT_DIR / "grafo_red_nivel2.html"
SELECTED_OUTPUT = OUTPUT_DIR / "grafo_red_nivel2_seleccionadas.html"
MGCECDL_OUTPUT = OUTPUT_DIR / "grafo_red_nivel2_mgcecdl.html"
# --- end replacement; the block below is unchanged from the original cell ---

# Color por modo (A-F) del diccionario de variables, usado en los grafos y su leyenda.
MODE_COLORS = {
    'A': '#e74c3c',
    'B': '#f39c12',
    'C': '#9b59b6',
    'D': '#3498db',
    'E': '#1abc9c',
    'F': '#2ecc71',
}
```

This keeps all 8 original imports and `MODE_COLORS` byte-identical (so cell 3's `os.environ.get(...)`/`load_workbook(...)`, cell 5's `nx.DiGraph()`/`Network(...)`/`MODE_COLORS[mode_id]`, and cell 6's `json.load(...)`/`np.save(...)` all keep working unchanged), keeps `resolve_selection_path()` (cell 3, unchanged — its `candidates` list references both `MGCECDL_PROJECT_ROOT` and `REPO_ROOT` directly) and the later `chec_impacto` re-import working unchanged, while redirecting the three HTML outputs to `dbfs:/Volumes/workspace/default/chec-simulador/outputs/graphs/` instead of a `site/` tree this command never uploads. `07`'s own `%pip install networkx pyvis openpyxl` cell stays a separate, unmodified cell (that dependency is unrelated to the bootstrap being replaced).

**Variant C — standalone hardcoded path (`08`)**: `<root_var>` = `ROOT`. This notebook walks up to find `src/` and sets `GEO_DIR = ROOT / "data" / "GEO"`, `EVENTS_PATH = ROOT / "data" / "Indicadores_vano_v3.csv"`, `OUTPUT_DIR = ROOT / "reports" / "geo"`, and `LINE_PATH`/`TRANSFORMER_PATH`/`SWITCH_PATH` (all derived from `GEO_DIR`), with no `src` import at all. Remove only the `ROOT = Path.cwd().resolve()` walk-up loop (`while not (ROOT / "src").is_dir()...`), replacing it with `DATA_DIR = Path("/Volumes/workspace/default/chec-simulador/data")` and `ROOT = DATA_DIR.parent`; no `sys.path` block is needed since `08` never imports the local packages. Leave `GEO_DIR`, `EVENTS_PATH`, `OUTPUT_DIR`, `LINE_PATH`, `TRANSFORMER_PATH`, `SWITCH_PATH` completely untouched — they already derive from `ROOT`/`GEO_DIR` and keep resolving correctly through the alias. (This also fixes a defect in the doc's own previous wording, "repoint just those two constants," which never addressed `OUTPUT_DIR = ROOT / "reports" / "geo"` in that same cell — deleting `ROOT` without aliasing it would have raised `NameError` there too, before even reaching a later cell.) Add a `%pip install geopandas folium` cell if the target compute environment doesn't already provide it.

### Per-notebook bootstrap-variable audit (added post-second-verify; extended post-third-verify to also walk `Import`/`ImportFrom` AST nodes and plain dict `Assign`s, not just path variables — this is the exact gap that let 07's import-deletion bug through the previous audit)

| Notebook | Root var | Other names the bootstrap cell defines and a *later* cell references directly | Still defined after the shim? |
|---|---|---|---|
| 01 | `PROJECT_ROOT` | `FECHA_FORMAT`, `INPUT_PATH`, `OUTPUT_PATH` (cells 14, 16, 17); `PROJECT_ROOT` itself (cells 14, 17) | Yes — those lines are kept unchanged in the same cell; `PROJECT_ROOT` is aliased |
| 02 | `PROJECT_ROOT` | `OPTUNA_DIR` (used in the optuna-search cell) | Yes — kept unchanged, derives from `DATA_DIR` |
| 03 | `PROJECT_ROOT` | `OPTUNA_DIR`, `study_paths` (used in the training cell) | Yes — kept unchanged |
| 04 | `PROJECT_ROOT` | `MODEL_DIR` (used loading the checkpoint), `RESULTS_DIR`, `SITE_RESULTS_DIR`, `NOMBRE_MODELO` (used in later cells) | Yes — kept unchanged |
| 05 | `PROJECT_ROOT` | `DATA_DIR`; `PROJECT_ROOT` itself (cell computing `GRAPH_OUTPUT_DIR`) | Yes — `DATA_DIR` from shim, `PROJECT_ROOT` aliased |
| 06 | `PROJECT_ROOT` | `DATA_DIR`; `PROJECT_ROOT` itself (cell computing `RESULTS_DIR`) | Yes — `DATA_DIR` from shim, `PROJECT_ROOT` aliased |
| 07 | `REPO_ROOT` (+ `MGCECDL_PROJECT_ROOT`) | `JSON_PATH`, `FULL_OUTPUT`, `SELECTED_OUTPUT`, `MGCECDL_OUTPUT` (used in the graph-build cell); `REPO_ROOT`/`MGCECDL_PROJECT_ROOT` themselves (`resolve_selection_path()`); **imports `json` (cell 6 `json.load`/`json.dumps`), `os` (cell 3 `os.environ.get`), `sys` (cell 6 `sys.path.insert`/`sys.modules`), `np` (cell 6 `np.save`), `nx` (cell 5 `nx.DiGraph()`), `load_workbook` (cell 3), `Network` (cell 5); dict `MODE_COLORS` (cell 5 `create_graph`/`save_graph`)** | Yes — dedicated shim now aliases both `MGCECDL_PROJECT_ROOT` and `REPO_ROOT`, AND keeps all 8 original imports plus `MODE_COLORS` byte-identical (previous pass wholesale-replaced the cell and silently dropped these 7 non-path names; fixed this pass by only swapping the `find_repo_root()`/`REPO_ROOT = find_repo_root()` lines) |
| 08 | `ROOT` | `GEO_DIR`, `EVENTS_PATH`, `OUTPUT_DIR`, `LINE_PATH`, `TRANSFORMER_PATH`, `SWITCH_PATH` (used across most later cells) | Yes — kept unchanged, derive from `ROOT`/`GEO_DIR` |
| 09 | `ROOT` | `DATA_PATH`, `VARIABLES_SELECCION_PATH`, `MODEL_DIR`, `OUTPUT_DIR` (cell 4) | Yes — kept unchanged, derive from `ROOT` |

Upload all 9 staged copies (format `JUPYTER`, matching each file's `.ipynb` content):
```
databricks workspace import /Workspace/Users/<userName>/databricks-integration/project_flow/<notebook_name> --file <staged_copy_path> --format JUPYTER --overwrite -p <profile>
```
Repeat once per notebook (`01_climate` ... `09_simulador`). After the loop, run the invariant check:
```
git status --porcelain notebooks/project_flow/
```
Confirm the output is empty before moving on.

## 6. Conditional tables job

If `<tables_status>` from step 2 is fresh (or all 6 prerequisite objects already exist and match), skip this step entirely and go to step 7.

Otherwise, reuse `.claude/commands/deploy-databricks-dashboard.md` **section 4**'s job-submit/poll pattern verbatim (upload `uiti_vano_tables.py` if not already present from a prior run, `databricks jobs submit` with the same `notebook_task` shape, poll `databricks jobs get-run <run_id> -p <profile>` until terminal). Confirm with the user before submitting — it provisions compute.

If that section's view-creation sub-step turns out to be needed (a required view is missing after the job), do NOT auto-execute the `CREATE VIEW` statement. Present the exact SQL and ask the user to run it themselves via the `!` prefix, same deferral `/deploy-databricks-dashboard` section 4.6 uses.

## 7. Upload interpretability reports (runtime discovery)

List what currently exists — do not assume a count or filenames from any prior run:
```
ls reports/interpretability/html/*.html 2>/dev/null | wc -l
```

Then copy whatever is present:
```
databricks fs cp -r reports/interpretability/html dbfs:/Volumes/workspace/default/chec-simulador/reports/interpretability/html --overwrite -p <profile>
```

`-r` transfers exactly the files found at run time. If the directory is empty (zero `.html` files), this is a no-op — report that to the user as "no reports found, nothing uploaded" rather than treating it as an error.

## 8. Publish the Lakeview dashboard (last)

Cross-reference `.claude/commands/deploy-databricks-dashboard.md` **section 5** (create draft → publish → verify `ACTIVE`) verbatim. If a dashboard from a prior `/deploy-databricks-dashboard` run already exists for this workspace, ask the user whether to republish it (same `dashboard_id`, refreshed `serialized_dashboard`) or create a new one; only ask for a display name if creating new. Confirm with the user before this step — publishing a dashboard is visible to other workspace users.

**Scope check**: after this step, no Databricks Apps resource has been created and no static-site/report-serving configuration has been touched — reports live only as plain files under the Volume path from step 7.

## 9. Report back

Tell the user, in their language:
- The profile and workspace this run used.
- Which of the 6 prerequisite data objects (from step 2 / `/deploy-databricks-dashboard` section 3) were already fresh vs. rebuilt by step 6.
- How many report files were found and uploaded in step 7 (including "0, no-op" if none).
- The `dashboard_id` from step 8 and whether it was newly created or republished.
- Confirmation that `git status --porcelain notebooks/project_flow/` was empty at the end of step 5 — i.e., no local repo file was modified by this command.
