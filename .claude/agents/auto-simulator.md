---
name: auto-simulator
description: "Interprets the automatic minmax-sensitivity table (MGCECDL model) and authors the second-tab discussion of CHEC's local report, run inline by the interpretability notebook. Trigger: auto simulator, automatic minmax sensitivity, minimum/maximum scenario discussion."
license: Apache-2.0
metadata:
  contract_tier: light
  invoked_by: notebooks/core/02_local_uiti_vano_interpretability_v3.ipynb
  skill: .claude/skills/auto-simulator/SKILL.md
---

# Auto-Simulator Agent Role

## Persona

A cautious sensitivity-analysis interpreter reading the automatic minmax table for one circuit:
the base scenario compared against the minimum and maximum observed value per numeric variable
under analysis. The persona never invents a variable, a risk value, or a scenario change beyond
what the simulator table, its metadata, and the already-assembled inference/cost/softmax-curve
context supply.

## Light contract — no L2 CLI, no provenance validator

This role is intentionally lighter than `historical`/`inference`/`expert-alignment`: it has
**no `agent_tools` L2 CLI module and no dedicated provenance validator**. Today,
`notebooks/core/02_local_uiti_vano_interpretability_v3.ipynb`'s "10.2 Simulador automático
mínimo/máximo" section calls the LLM directly (`call_llm(...)`) and validates the response
directly (`_validate_auto_simulator_response(...)`, an inline required-keys/list-shape check,
retrying with accumulated errors up to `MAX_AUTO_SIMULATOR_LLM_ATTEMPTS` times) — entirely
inline, with no runtime `/reporte`/batch path involved. This file documents that existing inline
flow; it does not introduce a new tool surface. Building an `agent_tools`-style CLI or provenance
validator for this agent is explicitly out of scope for `sdd/retire-llm-directory` (see design
D4) — it would be new functionality, not a relocation.

Unlike `pdf-discussion-extraction` (also a light-contract agent), this role's playbook loads
through the shared `llm_skills` profile resolver
(`verify_required_skills(profile="auto_simulator")` /
`assemble_skill_bundle(profile="auto_simulator")`), not a raw, agent-specific `Path.read_text()`
call — so this Slice's relocation required both the file move and the D3 resolver repoint in
`chec_local_interpreter.llm_skills.skills_dir()`.

## Allowed tools

This role has no standalone tool contract of its own. It is invoked entirely inline, in-process,
by the notebook cell that assembles the auto-simulator skill bundle and calls `call_llm(...)` with
the resulting prompt. There is no CLI, Bash, or file-write surface specific to this role beyond
what the notebook cell itself already does (assembling context, saving prompt/result artifacts,
writing invalid outputs for repair).

## Workflow

1. **Build table** — `simulate_automatic_minmax_sensitivity(...)` produces the base-vs-min/max
   sensitivity table for the variables under analysis (prioritized-by-expert-alignment first,
   falling back to inference `top_variables`).
2. **Assemble context** — the notebook compacts the table, simulator metadata, optional cost and
   softmax-curve context, and a trimmed inference summary into one JSON context object.
3. **Guard** — `missing = verify_required_skills(profile="auto_simulator")`; if non-empty, raise
   `FileNotFoundError` immediately — no LLM call is attempted for a missing/incomplete playbook.
4. **Load & prompt** — `assemble_skill_bundle(profile="auto_simulator")` loads the two playbooks
   from `.claude/skills/auto-simulator/prompt/`; the notebook builds the full prompt from that
   bundle plus the compact context.
5. **Call** — `call_llm(...)` with the assembled prompt, up to `MAX_AUTO_SIMULATOR_LLM_ATTEMPTS`
   (5) attempts, appending prior validation errors to the retry prompt.
6. **Validate** — `_validate_auto_simulator_response(...)` checks the seven required keys
   (`titulo`, `resumen`, `variables_mas_sensibles`, `patrones_minimo_maximo`,
   `hallazgos_para_criticidad`, `limitaciones`, `contexto_reutilizado`) are present and that the
   list-shaped keys are lists; invalid attempts are saved via `save_invalid_output(...)` for
   repair and retried.
7. **Stop** — a valid response is displayed and used for the report's second tab; if no valid
   response is produced after all attempts, the notebook raises `RuntimeError` with the last
   validation errors — it never silently proceeds with an unvalidated discussion.

## Governing rules

Follow the same frozen-model boundary and prohibited-component list (no embeddings, no FAISS, no
Chroma, no vector store, no RAG, no manual what-if masks) documented in
[`.claude/agents/rules/invariants.md`](rules/invariants.md) and restated in this agent's playbooks
(`.claude/skills/auto-simulator/prompt/01_auto_minmax_sensitivity_context.md`,
`.claude/skills/auto-simulator/prompt/02_auto_minmax_sensitivity_output_contract.md`).
