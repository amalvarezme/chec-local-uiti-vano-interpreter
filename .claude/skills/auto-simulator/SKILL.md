---
name: auto-simulator
description: "Interpret the automatic minmax-sensitivity table (MGCECDL model, base vs. minimum/maximum observed scenarios per variable) and author a compact JSON discussion for the second tab of CHEC's local report. Trigger: auto simulator, automatic minmax sensitivity, minimum/maximum scenario discussion, auto-simulator output contract."
license: Apache-2.0
metadata:
  author: chec-local-uiti-vano-interpreter
  version: "0.1.0"
  contract_tier: light
  role: .claude/agents/auto-simulator.md
  ported_from:
    - .claude/skills/auto-simulator/prompt/01_auto_minmax_sensitivity_context.md
    - .claude/skills/auto-simulator/prompt/02_auto_minmax_sensitivity_output_contract.md
---

## Overview

This Skill documents the reasoning contract used inline by
`notebooks/core/02_local_uiti_vano_interpretability_v3.ipynb`'s "10.2 Simulador automático
mínimo/máximo" section to interpret the automatic minmax-sensitivity table before writing the
second-tab discussion of the local report. It **ports** (does not duplicate) the two prompt
playbooks listed in `ported_from` above, per `docs/agents-guide.md`'s three-meanings-of-"skills"
table. The `prompt/` subdir IS the machine-fed source: the notebook's
`assemble_skill_bundle(profile="auto_simulator")` / `verify_required_skills(profile="auto_simulator")`
calls load those same files directly from `.claude/skills/auto-simulator/prompt/` (relocated from
`llm/skills_auto_simulator/` in `sdd/retire-llm-directory`); `SKILL.md` is this English
condensation for human/agent context, not a separate copy.

**Light contract (`contract_tier: light`)**: unlike `historical`/`inference`/`expert-alignment`,
this agent has **no `agent_tools` L2 CLI and no dedicated provenance validator**. The LLM call
(`call_llm(...)`) and its validation (`_validate_auto_simulator_response(...)`, an inline
required-keys/list-shape check) happen entirely inline in the notebook cell today, with no
runtime `/reporte`/batch path invoking this agent. Building L2/provenance machinery now would be
new functionality, not a relocation — out of scope for this change (see design D4). This Skill
and its paired agent role file (`.claude/agents/auto-simulator.md`) document the existing inline
flow only. It does still route through the shared `llm_skills` profile resolver
(`skills_dir(profile="auto_simulator")`), which is why D3's per-profile resolver repoint applies
here, unlike pdf-discussion-extraction's fully decoupled raw-path load.

## When to Use

Load this Skill when authoring or reviewing the auto-simulator discussion prompt: interpreting
the base-vs-minimum/maximum sensitivity table, its metadata, and the surrounding inference/cost/
softmax-curve context already available in the notebook.

## Role and source rules

You are invoked once per report run, after `simulate_automatic_minmax_sensitivity(...)` builds the
sensitivity table for the circuit's numeric variables under analysis (prioritized by expert
alignment when available, otherwise variables from the MGCECDL inference scenarios). Your job is
to interpret ONLY that table, the simulator metadata, and the optional context already assembled
by the notebook — never to re-derive or invent numbers.

Source rules (from the playbooks, Spanish is the operational contract — see
`.claude/skills/auto-simulator/prompt/01_auto_minmax_sensitivity_context.md` for the authoritative,
unabridged rule list):

- Allowed sources only: the `simulador_automatico_minmax` table, simulator metadata (circuito,
  periodo, row count, warnings, model), the optional `curvas_softmax_top_variables` and
  `costos_items_contratos` contexts, the inference context already in the notebook (scenarios,
  `top_variables`, modos CHEC, HTML graphs), and general inference/graph skill context as
  interpretive guidance only.
- Never invent variables, values, risks, or changes; never surface scaled/encoded/embedding
  values in the visible explanation.
- Treat `riesgo_base`, `riesgo_valor_minimo`, `riesgo_valor_maximo` as model outputs; prioritize
  the risk-label columns (`riesgo_base_etiqueta`, `riesgo_valor_minimo_etiqueta`,
  `riesgo_valor_maximo_etiqueta`).
- Category-transition priority over numeric detail: check first whether the minimum/maximum
  scenario changes the risk category versus the base scenario. Strong transitions (bajo -> alto,
  alto -> bajo) rank above bajo -> medio, medio -> alto, alto -> medio, medio -> bajo.
- Do not write a long variable-by-variable explanation; summarize general patterns and mention
  only the variables needed to justify a transition or notable sensitivity, using
  `magnitud_max_cambio_abs` to identify the most sensitive variables.
- `costos_items_contratos` (when present) is used only to add an economic reading via the
  delivered costs — approximate matches by textual proximity, never a budget or a firm
  intervention recommendation.
- `curvas_softmax_top_variables` (when present) is used only to discuss, in general terms, how the
  Q1-Q4 class probabilities shift for the graphed variables and whether the lowest-risk tested
  value aligns with higher Q1 / lower Q4 probability.
- `mejor_escenario_menor_riesgo` values may be reported as the model's own estimated values for
  lower risk within the tested range — always framed as simulated values, never an automatic
  operational instruction.
- Incorporate simulator warnings as explicit limitations or execution gaps.

## Output contract

Return only valid JSON — no markdown, no `<think>` tags, no text before or after the object; the
JSON must be fully closed (commas, brackets, braces balanced) and every list capped at 5 items.
Required keys, matching `.claude/skills/auto-simulator/prompt/02_auto_minmax_sensitivity_output_contract.md`
verbatim: `titulo`, `resumen`, `variables_mas_sensibles`, `patrones_minimo_maximo`,
`hallazgos_para_criticidad`, `limitaciones`, `contexto_reutilizado`. The notebook's
`_validate_auto_simulator_response(...)` is the acceptance gate (required-keys presence +
list-shape check); on failure it retries with the accumulated errors appended to the prompt, up
to `MAX_AUTO_SIMULATOR_LLM_ATTEMPTS` (5) times before raising. This relocation does not change
that validation or retry behavior.

## Related artifacts

- Agent role (light contract, no CLI): `.claude/agents/auto-simulator.md`
- Architecture and the three-meanings-of-"skills" table: `docs/agents-guide.md`
- Notebook caller (inline `call_llm` + `_validate_auto_simulator_response`, section "10.2
  Simulador automático mínimo/máximo"):
  `notebooks/core/02_local_uiti_vano_interpretability_v3.ipynb`
- Shared profile resolver: `chec_local_interpreter.llm_skills.skills_dir(profile="auto_simulator")`
- Ported-from playbooks (the machine-fed source, loaded by
  `assemble_skill_bundle(profile="auto_simulator")`):
  `.claude/skills/auto-simulator/prompt/01_auto_minmax_sensitivity_context.md`,
  `.claude/skills/auto-simulator/prompt/02_auto_minmax_sensitivity_output_contract.md`
