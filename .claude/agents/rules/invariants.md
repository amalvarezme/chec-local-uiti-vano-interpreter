# Agent Rules — Invariants

Binding rules for every agent role under `.claude/agents/`, derived verbatim from `AGENTS.md`.
These are not style guidance — violating any of them is a defect. Every role file must link here.

## Rule 1 — Frozen-Model Boundary

The M-GCECDL model artifact (`data/models/mgcecdl_classifier_best.zip`) and the restricted
model-implementation subpackage are off-limits to every agent role. No agent may read or write
the model artifact, and no `agent_tools` code may import that subpackage — directly or through
any submodule.

This is guaranteed in-repo, for every clone and CI run, by two always-enforced, code-checked
layers in `tests/test_frozen_model_guard.py` (run by `pytest -q`): an AST-based static import
guard (no `agent_tools` module may import the restricted subpackage) and a tracked sha256
model-manifest check (`data/models/manifest.sha256.json`) that fails loudly if the model artifact
ever drifts. Structurally, the L2 tool-adapter CLI also has no import path to the restricted
subpackage in the first place (see `docs/agents-guide.md`'s 4-layer architecture).

A local `.claude/settings.json` `permissions.deny` block is an **optional** additional safeguard
some developers may configure on their own machine — it is untracked by git (confirmed:
`git log --all -- .claude/settings.json` is empty) and does not ship with the repo or protect a
fresh clone or CI run. Do not rely on it as a guaranteed layer; the two guarantees above are the
ones that always apply.

*Note on wording*: this file intentionally avoids spelling out the restricted subpackage's
literal Python path, because that path's name is exactly what `tests/test_frozen_model_guard.py`'s
content guard rejects in this directory (by design — see Rule 3's own gate, which is the same
kind of code-checked-not-prose invariant). For the fully explicit reference, see
`docs/agents-guide.md`, which is outside the scanned directories.

## Rule 2 — Deterministic Selection Invariant

Circuit, period, and critical-point selection and detection are the sole responsibility of the
deterministic Python layer (L1, `chec_local_interpreter.expert_alignment`). No agent role may
perform its own selection or detection. Every agent receives already-selected context through the
L2 `build-context` envelope (`meta`, `context`, `prompt`, `allowed`) and may only interpret it —
never invent a new date, circuit, or critical point that wasn't already in that envelope.

## Rule 3 — JSON-Schema / Validator-Gated Output

No agent output is a valid report until it passes the L2 `validate` verb with exit code `0`.
`validate` is the single gate: it runs the schema validator first and, only if that succeeds, the
additive provenance validator, combining both error lists. An output that has not exited `validate`
at `0` must never be presented as a final report — on failure, the raw response and errors are
saved under `reports/interpretability/artifacts/{circuito}/` for later review, not published.

## Rule 4 — Prohibited Components

No agent role, Skill, playbook, or tool-adapter CLI may introduce any of: `RAG`, a `vector` store,
`Databricks`, `Dash`, or `FastAPI`. If you ever see one of these named as a dependency, workflow
step, or planned integration in a role, rules, or Skill file, that is a violation — flag it before
merging. (A reviewer can confirm this rule is present and grep-able by running
`grep -Ei "RAG|vector|Databricks|Dash|FastAPI"` against this file: every hit should be this
prohibition sentence or this instruction quoting the same pattern — never an allowed dependency
or workflow step naming one of them.)

## Rule 5 — No Forecasting Language Outside the Validated Inference Flow

Predictive or forecasting language about circuit behavior is prohibited in this pilot's output,
except inside the already-validated inference-agent flow (out of scope for the expert-alignment
role in this slice). The expert-alignment role compares existing descriptive and predictive-model
signals against expert discussion; it does not itself predict or forecast anything.

## Rule 6 — Provenance Optional Per Claim, Strictly Validated When Present

Provenance is **optional per claim, not required**: a claim in `coincidencias`, `diferencias`, or
`variables_a_priorizar` MAY carry a `provenance` object —
`{"data_ref": [...], "agent": "expert-alignment", "rule": "<playbook id>"}` — but omitting it
never fails validation on its own. This is a deliberate design choice for backward compatibility
with pre-provenance response shapes (additive keys), not a gap to be closed.

**When a `data_ref` IS provided, it is strictly validated and fails closed:**

- Every `data_ref` entry MUST resolve against the circuit's own already-validated allowed dates,
  variables, and PDF row references — never a fact outside what the envelope handed you.
  Validation rejects (fails closed) any `data_ref` that does not resolve, including the case where
  `variables_modelo_predictivo` is empty.
- `agent` must equal `expert-alignment` (the producing role's id).
- `rule` must be one of: `01_pdf_report_comparison`, `02_predictive_variable_prioritization`,
  `03_graph_context_for_alignment` — the three playbook ids ported into
  `.claude/skills/expert-alignment/SKILL.md`.

Do not read this rule as "provenance is required" (it isn't) or as "validation is loose when
present" (it isn't — any `data_ref` you do supply is held to the full resolvability check above).

## Rule 7 — Cautious Language Register

Report content is authored in Spanish, in a technical and cautious register: prefer
`asociación`, `consistencia`, `posible explicación`, and `requiere validación` over direct causal
claims. Direct causality language — `causó`, `causa` used causally, `demuestra causalidad`,
`prueba causal` — is rejected outright by the schema validator; do not attempt to phrase around
this rule, honor it.
