# Agent Rules — Invariants

Binding rules for every agent role under `.claude/agents/`, derived verbatim from `AGENTS.md`.
These are not style guidance — violating any of them is a defect. Every role file must link here.

## Rule 1 — Frozen-Model Boundary

The M-GCECDL model artifact (`data/models/mgcecdl_classifier_best.zip`) and the restricted
model-implementation subpackage this repository denies write/edit access to (see
`.claude/settings.json`'s `permissions.deny` block) are off-limits to every agent role. No agent
may read or write the model artifact, and no `agent_tools` code may import that subpackage —
directly or through any submodule.

This is enforced structurally (the L2 tool-adapter CLI has no import path to it — see
`docs/agents-guide.md`'s 4-layer architecture) and automatically, by an import-guard test, a
tracked integrity manifest at `data/models/manifest.sha256.json`, and this very content guard,
all in `tests/test_frozen_model_guard.py`.

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

## Rule 6 — Provenance Required (Additive)

Every claim in `coincidencias`, `diferencias`, or `variables_a_priorizar` SHOULD carry a
`provenance` object: `{"data_ref": [...], "agent": "expert-alignment", "rule": "<playbook id>"}`.

- `data_ref` entries must resolve against the circuit's own already-validated allowed dates,
  variables, and PDF row references — never a fact outside what the envelope handed you.
- `agent` must equal `expert-alignment` (the producing role's id).
- `rule` must be one of: `01_pdf_report_comparison`, `02_predictive_variable_prioritization`,
  `03_graph_context_for_alignment` — the three playbook ids ported into
  `.claude/skills/expert-alignment/SKILL.md`.

Provenance is additive and optional per claim: omitting it never fails validation on its own, but
every claim you can trace to a specific source should carry one, so the (data, agent, rule) trail
is enforceable rather than decorative.

## Rule 7 — Cautious Language Register

Report content is authored in Spanish, in a technical and cautious register: prefer
`asociación`, `consistencia`, `posible explicación`, and `requiere validación` over direct causal
claims. Direct causality language — `causó`, `causa` used causally, `demuestra causalidad`,
`prueba causal` — is rejected outright by the schema validator; do not attempt to phrase around
this rule, honor it.
