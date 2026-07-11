---
name: pdf-discussion-extraction
description: "Decides whether one PDF text fragment becomes a row in CHEC's expert-report discussion table, run inline by the extraction notebook. Trigger: PDF discussion extraction, expert report row extraction, technical-report fragment classification."
license: Apache-2.0
metadata:
  contract_tier: light
  invoked_by: notebooks/core/01_pdf_discussion_table_from_pdfs.ipynb
  skill: .claude/skills/pdf-discussion-extraction/SKILL.md
---

# PDF-Discussion-Extraction Agent Role

## Persona

A cautious fragment classifier deciding, per PDF text fragment, whether it contains a
citable technical discussion that belongs in the final discussion table for one circuit and
date range. The persona never invents a circuit, date, cause, or event beyond what the fragment
and its supplied metadata already contain.

## Light contract — no L2 CLI, no provenance validator

This role is intentionally lighter than `historical`/`inference`/`expert-alignment`: it has
**no `agent_tools` L2 CLI module and no dedicated provenance validator**. Today,
`notebooks/core/01_pdf_discussion_table_from_pdfs.ipynb` calls the LLM directly
(`call_llm(...)`) and validates the response directly (`validate_llm_row(...)`, discarding
invalid rows to `invalid_llm_outputs.json`) — entirely inline, with no runtime `/reporte`/batch
path involved. This file documents that existing inline flow; it does not introduce a new tool
surface. Building an `agent_tools`-style CLI or provenance validator for this agent is explicitly
out of scope for `sdd/retire-llm-directory` (see design D4) — it would be new functionality, not
a relocation.

## Allowed tools

This role has no standalone tool contract of its own. It is invoked entirely inline, in-process,
by the notebook cell that builds `PDFDiscussionExtractionSkill` and calls `.extract(context)` for
each fragment. There is no CLI, Bash, or file-write surface specific to this role beyond what the
notebook cell itself already does (reading the playbook, calling the configured LLM, writing
`invalid_llm_outputs.json` for discarded rows).

## Workflow

1. **Load** — the notebook's `PDFDiscussionExtractionSkill.__init__` reads the playbook once from
   `.claude/skills/pdf-discussion-extraction/prompt/01_pdf_discussion_extractor.md`.
2. **Build prompt** — `build_prompt(context)` fills the playbook's `{key}` placeholders with the
   per-fragment context (`fecha_inicio_usuario`, `fecha_fin_usuario`, `nombre_pdf`,
   `circuito_pdf`, `pagina_inicio`, `pagina_fin`, `periodo_general_informe`, `fragmento`).
3. **Call** — `extract(context)` calls the configured LLM (`call_llm(...)`) with that prompt.
4. **Validate** — the notebook's `validate_llm_row(...)` checks the parsed response against the
   user-supplied date bounds and required fields; rows that fail are appended to
   `invalid_llm_outputs.json` alongside the raw extraction record, not silently dropped.
5. **Stop** — a valid, in-range row is appended to the final discussion table; an `include: false`
   response or a failed validation means no row is added for that fragment.

## Governing rules

Follow the same frozen-model boundary and prohibited-component list (no embeddings, no FAISS, no
Chroma, no vector store) documented in
[`.claude/agents/rules/invariants.md`](rules/invariants.md) and restated in this agent's playbook
(`.claude/skills/pdf-discussion-extraction/prompt/01_pdf_discussion_extractor.md`) and its
`README.md`.
