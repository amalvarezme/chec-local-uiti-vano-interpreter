# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Notebook-first local interpreter for the `UITI_VANO` indicator in the CHEC electrical
distribution dataset. Deterministic Python code loads structured data, filters by
circuit/date window, detects critical points in the daily series, and builds a
structured context package. LLM agents (via `llm/skills/` playbooks) interpret that
context — they never select data, infer missing variables, or introduce evidence the
Python layer didn't already compute.

The repo has grown beyond the original "steps 1-3" descriptive interpreter into a
broader multi-agent architecture (see `docs/arquitecturayflujo.md` and
`docs/ContextoProyectoSimuladorCHEC.md`): MGCECDL predictive classification/SHAP,
graph interpretability, what-if simulation, geo network exploration, expert PDF
alignment, and a secondary Astro static site for publishing generated HTML reports.

## Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Tests (from repo root; conftest.py adds src/ to sys.path)
pytest -q
pytest tests/test_critical_points.py::test_name_here -q   # single test

# Offline LLM contract/guardrail evals (no API key required)
python llm/evals/run_llm_eval.py

# Astro site (reports/graphs viewer)
npm run dev          # local dev, BASE_PATH=/
npm run dev:pages    # dev matching GitHub Pages base path
npm run build
npm run preview
```

There is no `pyproject.toml`/`pytest.ini` — `tests/conftest.py` inserts `src/` onto
`sys.path` manually, so packages under `src/` are imported as top-level modules
(`chec_local_interpreter`, `chec_impacto`), not installed via pip.

## Architecture

### Two Python packages under `src/`

- **`chec_local_interpreter`** — the core local interpreter (steps 1-3 flow):
  - `data/` — loading (`loader.py`), schema validation (`schema.py`), event counts.
  - `analysis/` — critical point detection (`critical_points.py`), attribution,
    structured context assembly (`context_builder.py`), domain context, graph extraction.
  - `llm/` — prompt assembly (`prompt.py`, `contracts.py`), client, output validation
    (`validation.py`), and skill-file loading/enforcement (`skills.py`).
  - `reports/` — HTML report workflow, web export, PDF discussion extraction,
    expert-alignment comparison, plotting.
  - `simulation/` — what-if simulator and cost modeling.
  - `geo/` — circuit/network geographic mapping.
- **`chec_impacto`** — the MGCECDL predictive/inference side:
  - `models/`, `training/` — MGCECDL model definition and training.
  - `interpretability/` — SHAP-based performance, circuit analysis, document
    replication for the inference notebooks.
  - `data/` — climate data completion, graph construction/visualization.

### Notebooks drive both packages

Notebooks under `notebooks/{core,inference,web}/` are the actual entry points; they
import helper functions from `src/` rather than defining logic inline. When adding
notebook functionality, put the implementation in the matching `src/` package/module
and import it from the notebook — do not duplicate logic in-notebook. Notebook
groups:

- `notebooks/core/` — PDF discussion table extraction, the main local interpreter
  report notebook, geo/network exploration, the simulator.
- `notebooks/inference/` — climate completion, MGCECDL Optuna search, training,
  performance/SHAP, circuit analysis, document replication.
- `notebooks/web/` — generates graph HTML assets consumed by the Astro site.

### LLM skills (`llm/skills/`)

All skill playbooks live in one flat directory, disambiguated by filename prefix
(this was recently flattened from separate `skills/`, `skills_inference/`,
`skills_expert_alignment/`, `skills_auto_simulator/` directories):

- `base_0N_*` — required skills for the core descriptive/base agent flow.
- `inference_0N_*` — required skills for the MGCECDL inference agent flow.
- `expert_alignment_0N_*` — required skills for the expert-PDF comparison agent.
- `auto_simulator_0N_*` — required skills for the automatic min/max sensitivity flow.
- `shared_0N_*` — required by every profile (JSON output safety, domain language,
  model/graph guardrails).
- `pdf_discussion_extraction_*` — PDF discussion table extractor skill + its own README.

`src/chec_local_interpreter/llm/skills.py` defines the required-skill tuples per
`profile` (`"base"`, `"inferencia"`, `"expert_alignment"`, `"auto_simulator"`) and is
the source of truth for which files a given agent flow must load; notebooks verify
these files exist/load before running. When adding a new skill file, follow the
existing `{profile}_{NN}_{name}.md` naming and register it in the matching tuple in
`skills.py`.

### Deterministic vs LLM boundary

This boundary is enforced by validators, not just convention — see
`src/chec_local_interpreter/llm/validation.py` and `llm/README.md`:

- Python computes context (circuits, dates, series, critical points, attribution,
  SHAP/graphs); the LLM only interprets it and must return JSON matching
  `llm/prompts/uiti_vano_explanation.output_schema.json`.
- Output must cite dates, `critical_point_id`s, and variables present in the supplied
  context — guardrails reject invented evidence, out-of-context dates, unknown point
  IDs, and variables marked unavailable being treated as observed.
- Predictive/forecasting language is prohibited in base-agent explanations but
  expected/valid in the inference-agent flow (`validar_respuesta_inferencia`).
- Invalid LLM output is saved with its validation errors under
  `reports/interpretability/artifacts/` and never presented as final analysis.

### Outputs

Structured artifacts land under `reports/interpretability/artifacts/`
(`structured_context_*.json`, `llm_prompt_*.md`, `critical_points_*.csv`, timeseries
PNGs, optional `llm_analysis_*`, `inference_llm_analysis_*`, `expert_alignment_*`).
HTML reports from the main interpreter notebook go to `reports/interpretability/html/`.
MGCECDL interactive graphs go to `reports/mgcecdl-results/interactive_graphs/`.

### Astro site (`src/pages/`, `public/`, `lib/`)

Static site publishing generated graph/report HTML (circuit maps, critical points,
MGCECDL network graphs) as Astro pages/`.html.ts` route handlers. Deployed to GitHub
Pages from `main`; `dev` uses `BASE_PATH=/` while `dev:pages`/production build use the
GitHub Pages subpath.
