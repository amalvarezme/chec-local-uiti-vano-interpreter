# Kaggle CLI notes (official `kaggle-api`)

Source: https://github.com/Kaggle/kaggle-api (verified 2026-07-25). No official Kaggle MCP
server exists; several unofficial third-party ones do (e.g. `54yyyu/kaggle-mcp`,
`safe-kaggle-mcp`) — treat any of these as third-party and confirm with the user before use.
The official CLI/Python package below is the default path.

## Setup

```bash
pip install kaggle   # or: uv pip install kaggle
```

Auth: user places their own API token at `~/.kaggle/kaggle.json` (downloaded from
kaggle.com/settings → API → "Create New Token"), or sets `KAGGLE_USERNAME`/`KAGGLE_KEY` env
vars. Never generate, request, or store this token on the user's behalf.

### Verifying config & resolving username

```bash
kaggle config view
```

Prints only the non-secret parts of the active config (notably `- username: <name>`) — it
never prints the API key. Use its `username` value to fill any `REPLACE_WITH_KAGGLE_USERNAME`
placeholder in `kernel-metadata.json`/`dataset-metadata.json` before pushing. Never read
`~/.kaggle/kaggle.json` directly to get this value.

A lightweight liveness check that the token actually authenticates (not just that the file
exists):

```bash
kaggle datasets list -m 2>&1 | head -3
```

Run this once before the first real push in a session; an auth error here (invalid/expired
token) means push will fail too — report it verbatim and ask the user to regenerate their
token, rather than guessing the cause.

## `kernel-metadata.json` (lives alongside the notebook file)

```json
{
  "id": "username/kernel-slug",
  "title": "Kernel Title",
  "code_file": "notebook.ipynb",
  "language": "python",
  "kernel_type": "notebook",
  "is_private": "true",
  "enable_gpu": "false",
  "enable_internet": "false",
  "machine_shape": "",
  "dataset_sources": [],
  "competition_sources": [],
  "kernel_sources": [],
  "model_sources": []
}
```

- `id`/`title`: slug is the lowercased title with spaces → dashes; keep them in sync.
- `enable_internet`: set `"true"` if the notebook needs to `pip install` extra deps.
- `enable_gpu` + `machine_shape`, or the `push --accelerator` flag, request an accelerator
  (`NvidiaTeslaT4`, `NvidiaTeslaP100`, `NvidiaTeslaA100`, `NvidiaL4`, `NvidiaH100`, `TpuV5E8`,
  `TpuV6E8`, …) — availability varies by account tier/competition.
- Generate a starter file with `kaggle kernels init -p <folder>` instead of hand-writing it.

## Commands

```bash
# Create/update metadata scaffold for a new kernel folder
kaggle kernels init -p notebooks/kaggle_experiments/<slug>

# Upload + run (updates if the id already exists under this account)
kaggle kernels push -p notebooks/kaggle_experiments/<slug> [--accelerator NvidiaTeslaT4] [-t <timeout_s>]

# Poll real run state (running / complete / error) — do not assume from push's own exit code
kaggle kernels status username/kernel-slug

# Pull output files from the latest run once status is terminal
kaggle kernels output username/kernel-slug -p <local_output_dir> -o

# Pull code + metadata back down (rarely needed once you already have the local folder)
kaggle kernels pull username/kernel-slug -p <path> -m
```

`kernels status` is the only trustworthy signal of completion — poll it after every push
rather than assuming success from the push command's own exit code, and always read the
actual pulled output/metrics before reporting a run as passing.

## Datasets (private, code/data transport)

Used to transport `src/` code and data files to Kaggle without vendoring code into the
notebook or making the repo pip-installable (it has no `pyproject.toml`/`setup.py`). Same
official `kaggle-api`, different sub-command family (`kaggle datasets ...`, not
`kaggle kernels ...`). Never upload a dataset without the second explicit approval required by
the Dataset Transport Hard Rule in `SKILL.md`.

### `dataset-metadata.json` (lives alongside the packaged folder)

```json
{
  "title": "chec-impacto-src",
  "id": "<kaggle-username>/chec-impacto-src",
  "licenses": [{"name": "CC0-1.0"}]
}
```

- Generate the scaffold with `kaggle datasets init -p <folder>`, then edit `title`/`id`.
- `id` slug must be lowercase, dashes only, unique per account — keep it in sync with `title`.

### Commands

```bash
# First-time upload (folder must contain dataset-metadata.json)
kaggle datasets create -p <folder> --private

# Update an existing dataset with a new version (same folder structure)
kaggle datasets version -p <folder> -m "<version message>" --private
```

Never run `create` on a dataset that already exists — use `version` instead (same append-only
discipline as reusing an existing `kernel-metadata.json` `id`).

### Pinned dataset slugs (`uiti-vano-regression` family)

| Dataset | Packages | Staged from |
|---|---|---|
| `<kaggle-username>/chec-impacto-src` | `src/chec_impacto/` (whole subtree) | `kaggle datasets create -p src/chec_impacto --private` (first time), then `version` |
| `<kaggle-username>/uiti-vano-indicadores-v3` | `data/Indicadores_vano_v3.csv` + `data/Variables_seleccion.xlsx` | Stage both files into one folder (e.g. `notebooks/kaggle_experiments/<slug>/dataset_staging/`) alongside `dataset-metadata.json` before `create`/`version` — never point the command at the whole `data/` tree, which also holds unrelated GEO/model/optuna artifacts |

### `dataset_sources` in `kernel-metadata.json`

The notebook's `kernel-metadata.json` (see `## kernel-metadata.json` above) references both
dataset slugs by their full `username/slug` form:

```json
"dataset_sources": [
  "<kaggle-username>/chec-impacto-src",
  "<kaggle-username>/uiti-vano-indicadores-v3"
]
```

Kaggle mounts each at `/kaggle/input/<dataset-slug>/` — the notebook's bootstrap cell does
`sys.path.insert(0, "/kaggle/input/chec-impacto-src/src")` and reads the CSV/xlsx from
`/kaggle/input/uiti-vano-indicadores-v3/`.
