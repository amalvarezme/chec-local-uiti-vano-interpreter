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
L2 `build-context` envelope (`meta`, `context`, `allowed`; `prompt` is reserved for the separate
headless batch path — `agent_tools/batch.py` — and is not part of the interactive CLI stdout
contract) and may only interpret it — never invent a new date, circuit, or critical point that
wasn't already in that envelope.

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

Predictive or forecasting language about circuit behavior is prohibited in every role's output
governed by this file, except inside the already-validated inference-agent flow (Agent 2 —
inference/SHAP — out of scope for this slice). This binds both current roles:

- **expert-alignment** compares existing descriptive and predictive-model signals against expert
  discussion; it does not itself predict or forecast anything.
- **historical** (descriptive/base) describes PAST `UITI_VANO` behavior for the selected circuit(s)
  and period, using only already-selected structured context; it does not itself predict or
  forecast anything either. "Describing what the data shows happened" is not forecasting; stating
  what will happen, or asserting a definitive future outcome, is — and is prohibited here.

## Rule 6 — Provenance Optional Per Claim, Strictly Validated When Present

Provenance is **optional per claim, not required**, for every role governed by this file: a claim
MAY carry a `provenance` object — `{"data_ref": [...], "agent": "<role id>", "rule": "<playbook
id>"}` — but omitting it never fails validation on its own. This is a deliberate design choice for
backward compatibility with pre-provenance response shapes (additive keys), not a gap to be
closed.

**When a `data_ref` IS provided, it is strictly validated and fails closed, for every role:**

- Every `data_ref` entry MUST resolve against that role's own already-validated allowed context
  universe — never a fact outside what its envelope handed it. Validation rejects (fails closed)
  any `data_ref` that does not resolve.
- `agent` must equal the producing role's own id.
- `rule` must be one of that role's own declared playbook/Skill rule ids (each role's Skill
  declares its allowed `rule` ids and the response locations its provenance attaches to).

Do not read this rule as "provenance is required" (it isn't) or as "validation is loose when
present" (it isn't — any `data_ref` supplied is held to the full resolvability check below).

**Per-role instances:**

- **expert-alignment** — attaches provenance per item in `coincidencias`, `diferencias`, and
  `variables_a_priorizar`. `agent` must equal `expert-alignment`. `rule` must be one of:
  `01_pdf_report_comparison`, `02_predictive_variable_prioritization`,
  `03_graph_context_for_alignment`, `04_prior_report_continuity` — the four playbook ids ported
  into `.claude/skills/expert-alignment/SKILL.md`. `data_ref` entries resolve against the circuit's
  allowed dates, predictive-model variables, and PDF row references.
- **historical** — attaches provenance per item in `key_findings` (the base agent's per-claim
  evidence-bearing list, the analog of expert-alignment's per-item sections). `agent` must equal
  `historical`. `rule` must be one of the seven base playbook ids ported into
  `.claude/skills/historical/SKILL.md`: `01_structured_context_builder`,
  `02_critical_point_interpreter`, `03_uiti_vano_behavior_explainer`,
  `04_domain_grounding_guardrails`, `05_llm_output_validator`, `06_base_repair`,
  `07_base_output_contract`. `data_ref` entries resolve against the circuit's allowed dates,
  critical-point ids, and domain variables (never a variable marked unavailable for that context).

## Rule 7 — Cautious Language Register

Report content is authored in Spanish, in a technical and cautious register: prefer
`asociación`, `consistencia`, `posible explicación`, and `requiere validación` when framing
findings.
