---
name: pdf-discussion-extraction
description: "Decide whether a technical-report PDF fragment should become a row in the discussion table (circuit, date/interval, analysis, evidence) for CHEC's expert-PDF extraction notebook. Trigger: PDF discussion extraction, expert report row extraction, technical-report fragment classification."
license: Apache-2.0
metadata:
  author: chec-local-uiti-vano-interpreter
  version: "0.1.0"
  contract_tier: light
  role: .claude/agents/pdf-discussion-extraction.md
  ported_from:
    - .claude/skills/pdf-discussion-extraction/prompt/01_pdf_discussion_extractor.md
---

## Overview

This Skill documents the reasoning contract used inline by
`notebooks/core/01_pdf_discussion_table_from_pdfs.ipynb` to decide, per PDF text fragment,
whether a row belongs in the final discussion table. It **ports** (does not duplicate) the
single prompt playbook listed in `ported_from` above, per `docs/agents-guide.md`'s
three-meanings-of-"skills" table. The `prompt/` subdir IS the machine-fed source: the
notebook's `PDFDiscussionExtractionSkill` wrapper reads
`.claude/skills/pdf-discussion-extraction/prompt/01_pdf_discussion_extractor.md` directly
(relocated from `llm/skills_pdf_discussion_extraction/` in `sdd/retire-llm-directory`);
`SKILL.md` is this English condensation for human/agent context, not a separate copy.

**Light contract (`contract_tier: light`)**: unlike `historical`/`inference`/`expert-alignment`,
this agent has **no `agent_tools` L2 CLI and no dedicated provenance validator**. The LLM call
(`call_llm(...)`) and its validation (`validate_llm_row(...)`, discarding invalid rows to
`invalid_llm_outputs.json`) happen entirely inline in the notebook cell today, with no runtime
`/reporte`/batch path invoking this agent. Building L2/provenance machinery now would be new
functionality, not a relocation — out of scope for this change (see design D4). This Skill and
its paired agent role file (`.claude/agents/pdf-discussion-extraction.md`) document the existing
inline flow only.

## When to Use

Load this Skill when authoring or reviewing the extraction prompt that decides whether a single
PDF text fragment should produce a discussion-table row.

## Role and source rules

You are invoked per-fragment by the notebook's `PDFDiscussionExtractionSkill.extract()` method,
which fills the playbook's template placeholders (`{fecha_inicio_usuario}`, `{fecha_fin_usuario}`,
`{nombre_pdf}`, `{circuito_pdf}`, `{pagina_inicio}`, `{pagina_fin}`,
`{periodo_general_informe}`, `{fragmento}`) and calls the configured LLM.

Source rules (from the playbook, Spanish is the operational contract — see
`.claude/skills/pdf-discussion-extraction/prompt/01_pdf_discussion_extractor.md` for the
authoritative, unabridged rule list):

- Use only the fragment text and the metadata supplied in the template — never invent dates,
  circuits, causes, or events.
- `Circuito` must be exactly the caller-supplied `circuito_pdf` — never replaced by an internal
  mention in the fragment; if `circuito_pdf` is empty/unavailable, do not produce a row.
- Do not produce a row without sufficient textual evidence, without a resolvable date/interval,
  or when the discussion does not overlap the user-supplied date range.
- Follow the playbook's date-assignment hierarchy (explicit discussion date/interval first,
  falling back to a directly associated table/figure/Gantt/section, then the mentioned
  event/maintenance date, then the report's general period only when the discussion has no date
  of its own but clearly belongs to that period; otherwise, no row).

## Output contract

Return only valid JSON, one of two shapes — matching the playbook verbatim:

- Include: `{"include": true, "Circuito": ..., "Fecha inicio": "YYYY-MM-DD", "Fecha fin": "YYYY-MM-DD", "Análisis": ..., "Evidencia": ...}`
- Exclude: `{"include": false, "reason": "..."}`

The notebook's `validate_llm_row(...)` is the acceptance gate for the `include: true` shape (date
bounds, required fields); rows that fail validation are discarded and recorded in
`invalid_llm_outputs.json`. This relocation does not change that validation behavior.

## Related artifacts

- Agent role (light contract, no CLI): `.claude/agents/pdf-discussion-extraction.md`
- Architecture and the three-meanings-of-"skills" table: `docs/agents-guide.md`
- Notebook caller (inline `call_llm` + `validate_llm_row`):
  `notebooks/core/01_pdf_discussion_table_from_pdfs.ipynb`
- Ported-from playbook (the machine-fed source, loaded directly by the notebook's
  `PDFDiscussionExtractionSkill` wrapper):
  `.claude/skills/pdf-discussion-extraction/prompt/01_pdf_discussion_extractor.md`
