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
