---
name: pdf-discussion-extraction
description: "Decide, per PDF, which candidate technical-report sections become rows in the discussion table (circuit, date/interval, analysis, evidence) for CHEC's expert-PDF extraction. Trigger: PDF discussion extraction, expert report row extraction, technical-report section classification, batch PDF discussion runbook."
license: Apache-2.0
metadata:
  author: chec-local-uiti-vano-interpreter
  version: "0.2.0"
  contract_tier: light
  role: .claude/agents/pdf-discussion-extraction.md
  ported_from:
    - .claude/skills/pdf-discussion-extraction/prompt/01_pdf_discussion_extractor.md
---

## Overview

This Skill documents the reasoning contract for the agent-native PDF-discussion batch runbook
(design D5, `sdd/agent-native-pipeline-and-site-split`): given a whole PDF's candidate sections, it
decides, section by section, whether each one becomes a row in the final discussion table. It
**ports** (does not duplicate) the single prompt playbook listed in `ported_from` above, per
`docs/agents-guide.md`'s three-meanings-of-"skills" table. The `prompt/` subdir IS the machine-fed
source: this agent's `agent_tools` L2 CLI reads
`.claude/skills/pdf-discussion-extraction/prompt/01_pdf_discussion_extractor.md` directly via
`chec_local_interpreter.config.agent_prompt_dir`; `SKILL.md` is this English condensation for
human/agent context, not a separate copy.

**Batch contract (superseding the earlier per-fragment shape)**: this Skill previously classified
one PDF text fragment per agent turn, mirroring the now-retired
`notebooks/core/01_pdf_discussion_table_from_pdfs.ipynb`'s inline `PDFDiscussionExtractionSkill`
driver loop one-to-one. Design D5 replaced that entirely with a per-PDF BATCH: the deterministic
`chec_local_interpreter.pdf_discussion_pipeline` module (PR A2a) now owns PDF-to-Markdown
conversion, candidate-section selection, and batch-payload assembly
(`prepare_pdf_discussion_batch`); this agent classifies **every candidate section of one PDF in a
single turn**, returning a `{filas, descartes}` array instead of one row at a time. The deprecated
notebook, its inline `call_llm(...)` fallback, and the `llm_client.py` module it was the last live
caller of have all been retired -- this Skill's batch runbook is now the only implementation
(`sdd/agent-native-pipeline-and-site-split`, PR A2b).

**Light contract (`contract_tier: light`)**: unlike `historical`/`inference`/`expert-alignment`,
this agent has **no dedicated provenance validator** — its `agent_tools` L2 CLI
(`chec_local_interpreter.agent_tools.pdf_discussion`) exists, but its `validate` verb runs
`validate_pdf_discussion_row` (an unchanged required-columns/date-overlap/`include`-flag check) once
per row in the batch, not a citable-universe provenance check. A coding agent (Claude Code) invokes
the L2 CLI directly (see Run sequence below), reading the built prompt and authoring the JSON
response itself — no Python code ever calls an LLM API.

## Run sequence (how a coding agent should invoke this Skill)

1. Run `prepare_pdf_discussion_batch(pdf_dir, fecha_inicio_usuario, fecha_fin_usuario, run_dir)`
   (`chec_local_interpreter.pdf_discussion_pipeline`, deterministic Python, not this CLI) once per
   run — it globs every PDF in `pdf_dir`, resolves each one's circuit, converts it to Markdown,
   selects candidate sections, and writes one `{stem}.bc-input.json` payload per PDF under `run_dir`
   (sub-split into `{stem}.bc-input.{n}.json` only when a PDF's candidate content exceeds
   `max_batch_chars`).
2. For each `{stem}.bc-input*.json` payload written by step 1:
   a. Run `build-context` with the payload's JSON on stdin:
      `python -m chec_local_interpreter.agent_tools.pdf_discussion build-context`.
   b. Read the returned `prompt` from the envelope (`{meta, context, prompt}`) — ONE prompt covering
      every candidate section in this payload.
   c. Author the JSON response yourself (the coding agent): a single `{"filas": [...], "descartes":
      [...]}` object, per the Output contract below — one entry per candidate section, never
      omitted, never duplicated.
   d. Run `validate` with `{"response_text": <your response>, "circuito_pdf": ...,
      "fecha_inicio_usuario": ..., "fecha_fin_usuario": ...}` on stdin:
      `python -m chec_local_interpreter.agent_tools.pdf_discussion validate`.
   e. If a specific row in `errors`/`rejected` failed a genuine required-columns/date-overlap check
      (not a deliberate exclusion, which belongs in `descartes`), revise ONLY that row and retry
      from step (c) for the whole payload. Stop after at most 2 attempts per payload (matching
      `historical`'s `MAX_VALIDATION_RETRIES`).
   f. Once `validate` returns exit code `0` (the batch envelope parsed; some rows may still be in
      `rejected` after retries — that is expected, not a failure), write the returned `rows` array to
      `run_dir / f"{stem}.rows.json"` — this file is what step 3 collects.
3. Once every payload from step 1 has been processed, run
   `assemble_discussion_xlsx_from_run(run_dir, output_xlsx)` (deterministic Python, not this CLI) to
   collect every `{stem}.rows.json` under `run_dir` into the final `tabla_pdfs_intervalo_*.xlsx`.

## When to Use

Load this Skill when authoring or reviewing the extraction prompt that decides, for one whole PDF's
candidate sections, which of them should produce a discussion-table row.

## Role and source rules

You are invoked once per PDF (or once per sub-split batch, for a PDF whose candidate content exceeds
`max_batch_chars`) by the batch runbook's step 2 above, which fills the playbook's template
placeholders (`{fecha_inicio_usuario}`, `{fecha_fin_usuario}`, `{nombre_pdf}`, `{circuito_pdf}`,
`{periodo_general_informe}`, `{secciones}`) and expects you to author the full-batch JSON response.

Source rules (from the playbook, Spanish is the operational contract — see
`.claude/skills/pdf-discussion-extraction/prompt/01_pdf_discussion_extractor.md` for the
authoritative, unabridged rule list):

- Use only each section's own text and the metadata supplied in the template — never invent dates,
  circuits, causes, or events, and never let one section's content leak into another section's row.
- `Circuito` must be exactly the caller-supplied `circuito_pdf` for every row — never replaced by an
  internal mention in a section; if `circuito_pdf` is empty/unavailable, no row for any section.
- Do not produce a row for a section without sufficient textual evidence, without a resolvable
  date/interval, or when the discussion does not overlap the user-supplied date range — send that
  section to `descartes` instead.
- Follow the playbook's date-assignment hierarchy (explicit discussion date/interval first, falling
  back to a directly associated table/figure/Gantt/section, then the mentioned event/maintenance
  date, then the report's general period only when the discussion has no date of its own but clearly
  belongs to that period; otherwise, that section goes to `descartes`).
- Every candidate section supplied in the prompt must appear exactly once, in either `filas` or
  `descartes` — never in both, never omitted in silence.

## Output contract

Return only valid JSON — one object covering the WHOLE batch, matching the playbook verbatim:

```json
{
  "filas": [
    {"include": true, "Circuito": "...", "Fecha inicio": "YYYY-MM-DD", "Fecha fin": "YYYY-MM-DD", "Análisis": "...", "Evidencia": "..."}
  ],
  "descartes": [
    {"seccion_indice": 2, "reason": "..."}
  ]
}
```

`filas` entries use the same per-row shape the pre-batch Skill produced (each with `include: true`);
`descartes` entries identify an excluded section by its `indice` (`seccion_indice`) plus a brief
`reason`. The CLI's `validate` verb runs `validate_pdf_discussion_row` (UNCHANGED — date bounds,
required fields, forced `Circuito`) once per `filas[]` entry; a failing row is rejected individually
(`rejected`), never turning the whole batch invalid. `descartes` entries are persisted for
auditability but never run through `validate_pdf_discussion_row` — they were never candidate rows.

## Related artifacts

- Agent role (light contract, L2 CLI, no provenance validator):
  `.claude/agents/pdf-discussion-extraction.md`
- L2 tool-adapter CLI (batch contract): `src/chec_local_interpreter/agent_tools/pdf_discussion.py`
- Deterministic batch runbook (PDF→Markdown, candidate selection, payload assembly, xlsx assembly):
  `chec_local_interpreter.pdf_discussion_pipeline`
- Response validator (unchanged, applied per row): `chec_local_interpreter.llm_validation.validate_pdf_discussion_row`
- Architecture and the three-meanings-of-"skills" table: `docs/agents-guide.md`
- Ported-from playbook (the machine-fed source, loaded by the CLI's `build_context` via
  `chec_local_interpreter.config.agent_prompt_dir`):
  `.claude/skills/pdf-discussion-extraction/prompt/01_pdf_discussion_extractor.md`
