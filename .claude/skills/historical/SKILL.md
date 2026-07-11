---
name: historical
description: "Produce the historical/base descriptive diagnosis of UITI_VANO behavior for CHEC's selected circuit(s) and period, citing only already-selected structured context, with optional per-finding provenance. Trigger: historical analysis, base descriptive diagnosis, UITI_VANO behavior explanation, critical-point interpretation, circuit characterization."
license: Apache-2.0
metadata:
  author: chec-local-uiti-vano-interpreter
  version: "0.1.0"
  role: .claude/agents/historical.md
  rules: .claude/agents/rules/invariants.md
  ported_from:
    - .claude/skills/historical/prompt/01_structured_context_builder.md
    - .claude/skills/historical/prompt/02_critical_point_interpreter.md
    - .claude/skills/historical/prompt/03_uiti_vano_behavior_explainer.md
    - .claude/skills/historical/prompt/04_domain_grounding_guardrails.md
    - .claude/skills/historical/prompt/05_llm_output_validator.md
    - .claude/skills/historical/prompt/06_base_repair.md
    - .claude/skills/historical/prompt/07_base_output_contract.md
---

## Overview

This Skill is the single, current source of the historical/base agent's reasoning guidance. It
**ports** (does not duplicate) the seven prompt playbooks listed in `ported_from` above into one
Skill body with frontmatter, per `docs/agents-guide.md`'s three-meanings-of-"skills" table. The
`prompt/` subdir IS the machine-fed source: `assemble_skill_bundle(profile="base")` loads those
same files directly from `.claude/skills/historical/prompt/` (relocated from `llm/skills/` in
`sdd/retire-llm-directory`); `SKILL.md` is this English condensation for human/agent context, not
a separate copy. Going forward, author and revise the historical/base reasoning guidance in the
`prompt/` playbooks, and keep this condensation in sync.

This Skill governs how the `historical` agent role (`.claude/agents/historical.md`) authors its
descriptive diagnosis. Every binding invariant (frozen boundaries, validator-gated output,
prohibited components, provenance, and the language register below) is defined once in
`.claude/agents/rules/invariants.md` — this Skill focuses on the domain-specific reasoning
content, not the invariants themselves.

## When to Use

Load this Skill when authoring the historical/base diagnosis for one or more circuits: describing
`UITI_VANO` behavior over the selected period using only the already-built structured context
(critical points, daily series, domain groups) — never new selection or detection.

## Structured context construction (ported from `01_structured_context_builder.md`)

The deterministic Python layer builds the structured context **before** any call to this agent:
selecting circuits, the period, the daily `UITI_VANO` series, the critical points, and the
attribution summaries for each critical point, domain variable groups, and relationship rules. The
output is a compact, JSON-serializable context package.

Rules this agent must honor about the context it receives:

- It only ever contains data derived from the selected circuits and date window.
- Unavailable optional variables are explicitly listed in the context metadata.
- IDs stay as text strings.
- Large windows are summarized rather than sent as a full raw dataset.
- Enough event rows around each critical point are included to allow interpretation.
- The daily series is already in compact form.
- Domain/protection relationship rules are already included in the context package.
- No external evidence, documents, vector stores, models, masks, simulations, or final-report
  material is ever added to the context — if it is not in the envelope, it does not exist for this
  agent.

## Critical-point interpretation (ported from `02_critical_point_interpreter.md`)

This agent interprets the critical points already selected by the deterministic code layer. It
never selects, adds, removes, or reorders them.

- Do not add, remove, or reorder critical points.
- Use `criticality_types`/`types`, `selection_reason`, `criticality_score`/`score`, daily
  aggregates, and attribution summaries already present on each critical point.
- Describe why each critical point is relevant to `UITI_VANO` behavior at the period level.
- Relate the critical point's interpretation to domain variable groups when available.
- Distinguish between "observed in the data" and "plausible contributing factor."
- Cite evidence by date and `critical_point_id` whenever a finding depends on a specific critical
  point.
- Never invent missing variables, event labels, or unavailable columns.

## `UITI_VANO` behavior explanation (ported from `03_uiti_vano_behavior_explainer.md`)

Produce the final analysis in Spanish as structured JSON, with these required output sections:
`headline`, `executive_summary`, `key_findings`, `period_synthesis`, `cause_hypothesis_note`,
`evidence`, `data_gaps`, `limitations`, `recommended_actions`.

- Focus on `UITI_VANO`.
- Explain behavior over time, not only isolated days.
- Group findings by dominant mechanism when possible: event/impact, protection, topology,
  physical/electrical characteristics, assets, and environment/risk/climate.
- Include dates and critical values.
- In `cause_hypothesis_note`, estimate the plausible root cause based on the graph knowledge,
  the technical justifications, the analyzed variables, event counts, and `UITI_VANO` impact.
  Justifications should be detailed, explicitly naming which columns/variables relate most closely
  to the proposed causes.
- **Vegetation and DDT analysis (mandatory):** always analyze and include the influence of `NR_T`
  (vegetation risk level near the vano) and `DDT` (ground discharge density). Both variables are
  always present in the study data. This agent must:
  1. Evaluate `NR_T` at the critical points and explicitly discuss whether vegetation could have
     contributed to events or `UITI_VANO` deterioration.
  2. Correlate `DDT` with the other available climate variables (precipitation, wind, cloud cover,
     etc.) and explicitly evaluate its impact on event frequency and `UITI_VANO` severity.
  3. Highlight, using tabular-evidence language, whether `NR_T` and `DDT` reinforce or contradict
     the root-cause hypotheses.
  4. **Never** state that DDT or vegetation (`NR_T`) data is unavailable — they are always present
     in the analyzed table.
- Avoid unsupported claims.
- Never mention external document review, operational logs, regulatory review, predictive-model
  inference, relevance masks, simulation, or final-report generation.
- Use every provided critical point as evidence, but synthesize one consolidated period-level
  diagnosis.

## Domain-grounding guardrails (ported from `04_domain_grounding_guardrails.md`)

Use the domain context as an anchor for the structured dataset only — treat it as interpretive
guidance, not proof.

Compact domain guidance:

- Climate lags can indicate accumulated environmental stress.
- `NR_T` (vegetation risk level) and `DDT` (ground discharge density) are variables **always
  present** in the study table; they must be analyzed in every report as possible modulators of
  events and `UITI_VANO`.
- Precipitation, wind, and gusts can support environmental hypotheses alongside `NR_T` and `DDT`.
- Conductor, length, phases, neutral/guard wire, and taxonomy describe susceptibility.
- `LVSW`, `CNT_VN`, `FID_VANO`, and `CIRCUITO` describe topology and propagation context.
- Protection equipment and protected users help explain impact scope and restoration context.
- Asset variables help describe vulnerability and exposure.
- Duration and affected users help explain event-level outage impact.

Forbidden language (never write these phrases or their direct equivalents):

- "definitively caused", "demonstrates that", "the cause was", "according to regulation",
  "the log shows", "the model predicts"
- Any phrase stating that `DDT`/`NR_T` data is unavailable or missing — they are always present.

Forbidden association: never relate manual operations to causes, characterizations, or failure
justifications — manual operations are controlled staff interventions and do not affect the
circuit's primary operation.

Preferred language: "suggests", "is compatible with", "could be associated with", "the tabular
evidence shows", "within the available variables", "cannot be confirmed with this local version".

## Output validation (ported from `05_llm_output_validator.md`)

Every response is validated before being presented as an analysis. A valid response:

- Is valid JSON.
- Complies with `uiti_vano_explanation.output_schema.json`.
- Only references dates present in `critical_points` or the daily series.
- Never references an unavailable column as if it were present.
- Never claims to use external document review, operational logs, regulatory review,
  predictive-model inference, relevance masks, simulations, or final-report generation.
- Includes limitations.
- Includes data gaps when optional variables are missing.

If validation fails, the raw invalid output and validation errors are saved for review under
`reports/interpretability/artifacts/historical/{circuito}/` (this Skill's own agent-namespaced
artifacts root — see `.claude/agents/rules/invariants.md`, Rule 3) — the invalid output is never
presented as the final analysis.

## Repair mode (ported from `06_base_repair.md`)

Repair mode is used only when a previous response failed validation.

- Return only valid JSON — no markdown, no `<think>` tags, no comments or text before/after the
  JSON object.
- Use only the repair context provided.
- Use only dates and `critical_point_id`s present in `critical_points` or the context's
  start/end window.
- Never mention external document review, operational logs, regulatory review, what-if analysis,
  simulation, relevance masks, or final-report generation.
- If optional columns are unavailable per the context metadata, include them in `data_gaps`.
- At least one `data_gaps`/finding item should address `NR_T` and `DDT` if they appear in the
  context.
- Develop the analysis needed to correct the response without losing findings.
- Every list block has a maximum of 5 items.
- Every narrative text field is one closed, complete paragraph.
- Prioritize closing the JSON object correctly and completely.
- If the previous attempt failed on JSON syntax, regenerate the full object from scratch — never
  patch a truncated fragment.

## Base output contract (ported from `07_base_output_contract.md`)

Role: descriptive historical analyst of `UITI_VANO` for electrical distribution networks,
producing a descriptive diagnosis for the selected circuit(s) and period.

Scope:

- Work only on flow steps 1–3: circuit/vano selection, deterministic critical-point
  identification, and preliminary semantic diagnosis.
- Use only the structured JSON context package, variable descriptions, variable groups, and
  relationship rules included in the context.
- Never detect new critical points or change the points provided by the deterministic layer.
- Never use or mention external document review, operational logs, regulatory review, vector
  stores, predictive models, relevance masks, simulations, what-if scenarios, or final reports.

Output:

- Return only a valid JSON object, in Spanish.
- No `<think>` tags, markdown, comments, code fences, or text before/after the JSON.
- The response must be compact, with every array and the root object fully closed. Verify the JSON
  parses without repair before finalizing.
- The object must comply with the schema delivered in the prompt.
- Use only `critical_point_id`s present in the context; use `null` when not applicable.
- Before answering, verify every schema-required field exists in the exact requested shape. Never
  replace lists of objects with dictionaries, or vice versa, even when the content seems
  equivalent.

Required diagnosis: analyze `UITI_VANO` behavior for the selected circuits and period, using the
provided critical points as evidence, and produce one consolidated period-level diagnosis.
Connect circuit characterization with the temporal evolution of `events` and `UITI_VANO`.

`circuit_characterization` must include:

- `text`: circuit-criticality synthesis.
- `top_vanos_percentile`, `p97_vanos_uiti_vano`, `p97_vanos_eventos`: copy the configured
  percentile and the top-percentile vanos from the context.
- `probable_justifications_rules`: items describing variable relationships that may contribute to
  the most-affected critical points and vanos.

Each `probable_justifications_rules` item must include `modo`, `variables_asociadas`,
`justificacion_fisico_logica` (strictly based on the context's own rules), and `analisis_causas`
(how those connections are compatible with the observed critical-point values).

Use `top_rows` values on critical days, correlating climate, infrastructure, and
physical/electrical modes. Report `FID_VANO` when present in the context.

**Vegetation and DDT:** one `probable_justifications_rules` item must correspond to the
"Entorno y Riesgo" mode with variables `NR_T` and `DDT`, whenever they are available in the
context. Evaluate whether `NR_T` at the critical points suggests vegetation contributed to events
or `UITI_VANO` deterioration, and whether `DDT` is compatible with a higher event frequency or
elevated `UITI_VANO` values. If `NR_T` or `DDT` are absent from the delivered context, report it as
a data gap — never invent an observation.

Style:

- Use tabular-evidence language: "sugiere", "es compatible con", "podría estar asociado con",
  "dentro de las variables disponibles".
- Separate observations, plausible interpretations, limitations, and next verification steps.
- Develop the analysis with enough detail to avoid losing relevant findings.
- Keep the writing clear and organized so the HTML report retains its executive style.
- Every list block has a maximum of 5 items; when more findings exist, prioritize the
  best-supported ones (dates, critical points, variables, and context rules).
- Narrative string fields (`period_synthesis`, `cause_hypothesis_note`, `text`,
  `analisis_causas`) must be closed paragraphs — use item arrays to distribute findings instead of
  an open-ended narrative field.

## Provenance contract

Add an optional `provenance` object to any `key_findings` item that traces back to a specific
source, per `.claude/agents/rules/invariants.md` Rule 6:

```json
"provenance": {
  "data_ref": ["2026-01-02", "cp-2026-01-02", "UITI_VANO"],
  "agent": "historical",
  "rule": "03_uiti_vano_behavior_explainer"
}
```

- `data_ref` entries resolve against the citable universe advertised in the envelope's `allowed`
  block: an ISO date, a `cp-YYYY-MM-DD` critical-point id, or a domain variable name — anything
  else, or a reference outside that universe, fails validation.
- `agent` must always be the literal string `"historical"`.
- `rule` must be one of the seven playbook ids ported into this Skill (`ported_from` above,
  stripped of their `NN_` prefix and `.md` suffix, in the same order
  `assemble_skill_bundle(profile="base")` loads them):
  `01_structured_context_builder`, `02_critical_point_interpreter`,
  `03_uiti_vano_behavior_explainer`, `04_domain_grounding_guardrails`,
  `05_llm_output_validator`, `06_base_repair`, `07_base_output_contract`.
- Omitting `provenance` on a `key_finding` never fails validation — it is optional per item, not
  required.

## Language register

Report content stays in the cautious Spanish register (this is the same register the schema
validator and `.claude/agents/rules/invariants.md` Rule 7 enforce):

- Mantén lenguaje cauteloso: sugiere, es compatible con, podría estar asociado con, dentro de las
  variables disponibles.
- No inventes observaciones para `NR_T`/`DDT` cuando no estén disponibles — repórtalo como brecha
  de datos.

## Related artifacts

- Agent role: `.claude/agents/historical.md`
- Binding rules: `.claude/agents/rules/invariants.md`
- Architecture and envelope contract: `docs/agents-guide.md`
- L1 deterministic Python: `src/chec_local_interpreter/context_builder.py`,
  `src/chec_local_interpreter/llm_contracts.py`, `src/chec_local_interpreter/llm_validation.py`
- Ported-from playbooks (the machine-fed source, loaded by
  `assemble_skill_bundle(profile="base")`):
  `.claude/skills/historical/prompt/01_structured_context_builder.md`,
  `.claude/skills/historical/prompt/02_critical_point_interpreter.md`,
  `.claude/skills/historical/prompt/03_uiti_vano_behavior_explainer.md`,
  `.claude/skills/historical/prompt/04_domain_grounding_guardrails.md`,
  `.claude/skills/historical/prompt/05_llm_output_validator.md`,
  `.claude/skills/historical/prompt/06_base_repair.md`,
  `.claude/skills/historical/prompt/07_base_output_contract.md`
