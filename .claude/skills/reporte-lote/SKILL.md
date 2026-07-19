---
name: reporte-lote
description: "Run /report for every circuit belonging to one criticality group (or the whole fleet). Trigger: /reporte-lote, batch report, criticality-group report, run report for all circuits in a tier."
license: Apache-2.0
metadata:
  author: chec-local-uiti-vano-interpreter
  version: "0.1.0"
  runtime: claude
  canonical_contract: src/chec_local_interpreter/batch_report_contract.py
  invokes_skills:
    - .claude/skills/report/SKILL.md
---

## Overview

`/reporte-lote` batches `/report` across every circuit in one circuit-criticality group (or every
circuit in the dataset, for `todos`). It does not reimplement any part of the single-circuit report
pipeline. It owns exactly one thing `/report` does not: resolving a group slug to a concrete circuit
list plus a shared dataset-wide date window, behind a single up-front confirmation. Once that
checkpoint clears, this Skill loops over the resolved circuits and, for each one, runs
[`report/SKILL.md`](../report/SKILL.md)'s existing Run-sequence steps 2-9 exactly as documented
there — by reference, never by copying or restating their prose. The one deliberate, explicitly
scoped exception is how a per-circuit failure is handled inside this loop (see "Alert-and-continue
override" below); `report/SKILL.md` itself is never edited and a standalone `/report` invocation is
completely unaffected by this Skill's existence.

## When to Use

Load this Skill when the user wants `/report` run for a whole criticality tier or the whole fleet in
one go — e.g. "run reports for all Muy Alta circuits", "/reporte-lote alta", "batch report every
circuit". If the user wants exactly one circuit's report, use `/report`/`/reporte` directly instead;
this Skill is strictly for the multi-circuit, group-resolved case.

## Argument contract

Invocation: `/reporte-lote <grupo> [fecha_inicio fecha_fin]`.

- `grupo` — **required**. Must be one of `muy-alta|alta|media|baja|muy-baja|todos`; any other value
  is a usage error, rejected before any dataset access — no preflight call, no run_dir, nothing.
- `fecha_inicio` / `fecha_fin` — **optional, as a PAIR**, same pair contract `/report` uses:
  - Both omitted: resolve to the **dataset-wide** date range (the min/max `FECHA` across ALL
    circuits, not any single circuit's `circuit_date_range`) — the batch spans potentially many
    circuits, so the window must be one they can all share.
  - Both given: passed through unchanged.
  - **Exactly one given is a usage error.** Reject it immediately (e.g. "da ambas fechas,
    fecha_inicio y fecha_fin, o ninguna") — do not guess, do not default only the missing bound.

Examples:

| Invocation | Result |
|---|---|
| `/reporte-lote muy-alta` | Group resolved against the full dataset-wide date range |
| `/reporte-lote alta 2026-01-01 2026-02-01` | Group resolved against that explicit window |
| `/reporte-lote media 2026-01-01` | **Rejected** — usage error, `fecha_fin` missing |
| `/reporte-lote critica` | **Rejected** — usage error, unknown `grupo` |
| `/reporte-lote todos` | Every circuit in the dataset, no criticality-label filtering |

## Single user checkpoint (start of flow only)

The resolved circuit list, its count, and the resolved `fecha_inicio`/`fecha_fin` window are the
**only** things this Skill ever corroborates with the user, and only **once**, before any circuit's
`report/SKILL.md` steps 2-9 begin. Once that single checkpoint clears, the entire rest of the batch —
every circuit's full run, in sequence, through to the final summary — proceeds **without asking the
user anything else**. This holds even for `grupo=todos` regardless of how many circuits that
resolves to: there is no per-circuit checkpoint, no "continue to the next one?", and no second
confirmation anywhere later in the run. Silence between circuits is expected; the next thing the
user sees is either the alert for an empty/invalid group (a hard stop below, before the checkpoint)
or the final batch summary.

## Allowed tools

- **Bash** — restricted to invoking the shared batch contract's own verbs
  (`chec_local_interpreter.batch_report_contract preflight` / `write-manifest`, e.g. via `python -m
  chec_local_interpreter.batch_report_contract ...`) for this Skill's own step 1 and final summary
  step, plus whatever Bash surface `report/SKILL.md` itself uses while its steps 2-9 run for the
  current circuit (this Skill does not relax or widen that surface — see its own "Allowed tools").
  This Skill never gets a general shell — same structural guarantee as `report` and every agent role
  (`.claude/agents/rules/invariants.md`, Rule 1).
- **Skill** — to invoke `report/SKILL.md`'s Run-sequence steps 2-9, per circuit, in the loop below.
  `report/SKILL.md` governs its own further Bash/Skill/Read restrictions independently for those
  steps; this Skill does not bypass them.
- **Read** — to inspect the batch contract's JSON output and any run_dir artifacts needed to report
  a circuit's outcome.

## Run sequence

**Environment bootstrap.** Run `batch_report_contract` commands from the repository root with
`PYTHONPATH=src .venv/bin/python`, same as `report/SKILL.md`.

Given `grupo` (and optionally `fecha_inicio`/`fecha_fin` as a validated pair):

1. **Validate arguments, resolve the group, and get the one-time user confirmation.** Owned entirely
   by this Skill — `report/SKILL.md`'s own step 1 is not invoked here; this replaces it for the whole
   batch.
   1. Reject an unknown `grupo` or a lone date per the argument contract above (usage error, stop
      here — no dataset load needed to catch either case).
   2. Resolve the group and window through the shared batch contract's preflight verb:
      `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.batch_report_contract preflight <grupo> [fecha_inicio fecha_fin] --runtime claude`.
      This delegates to `preflight_batch(...)`, which loads the dataset, resolves the window
      (dataset-wide default via `_dataset_date_range` when omitted, or the explicit pair), filters to
      that window, and resolves `grupo` to a circuit list (`available_circuits` for `todos`, or the
      circuits whose `compute_circuit_criticality_groups` label matches otherwise).
   3. Branch on the returned `status`:
      - `usage_error` or `execution_error` (e.g. zero events anywhere in the resolved window) —
        **generate an alert** with the returned error message(s) and **stop**. Do not create a
        run_dir for any circuit, do not proceed to confirmation.
      - `empty_group` (the group resolved to zero circuits in the window) — **generate an alert**
        naming the group label and window (e.g. "grupo `<label>` sin circuitos en la ventana
        `<fecha_inicio>`..`<fecha_fin>`, nada que ejecutar") and **stop**. This is a hard stop, same
        as `usage_error`/`execution_error` — do not request confirmation, do not run anything.
      - `awaiting_confirmation` — proceed to 1.4.
   4. State the resolved group label, the resolved `fecha_inicio`..`fecha_fin` window, the circuit
      count, and the full circuit list (`group.circuitos`) back to the user **once**, and get their
      confirmation before proceeding. This is the single checkpoint described above — do not repeat
      it, and do not add any other confirmation prompt later in the run, including per circuit.

2. **Run `report/SKILL.md` steps 2-9 for each confirmed circuit, in order.** For each `circuito` in
   the confirmed `group.circuitos` list, sequentially (never in parallel across circuits — only the
   independent sub-steps *within* one circuit's own step 3/4/4b may run concurrently, exactly as
   `report/SKILL.md` already documents for those): execute
   [`report/SKILL.md`](../report/SKILL.md)'s Run-sequence **steps 2 through 9 exactly as written
   there**, substituting the current `circuito` and this batch's already-resolved
   `fecha_inicio`/`fecha_fin` for `report/SKILL.md`'s own step-1 outputs. Do **not** run
   `report/SKILL.md`'s step 1 (its own argument validation/preflight/checkpoint) for any circuit —
   this Skill's step 1 above already replaced it for the whole batch. Every other instruction in
   `report/SKILL.md`'s steps 2-9 — `prepare`, the historical/inference/auto-simulator dispatch and
   its parallel-dispatch rule, the per-stage `record-usage`/`record-duration` capture,
   `prepare_expert_alignment`, `expert-alignment`, `render`, and the step-9 vault-note +
   `/graphify --update` chain (`vault-circuito/SKILL.md`) — applies to each circuit's run unchanged
   and in full.

   **Alert-and-continue override (batch-only, scoped to this loop).** `report/SKILL.md`'s own "Error
   handling summary" table makes every step 2-8 failure (zero events in the window, a `prepare`/
   `prepare_expert_alignment`/`render` `ReportPipelineError`, or agent validation retries exhausted)
   an alert-and-**stop** for that single circuit's run. Inside this Skill's loop only, that becomes
   alert-and-**continue**: on any such steps-2-8 failure for `circuito`, append `{"circuito":
   <circuito>, "status": "FAILED", "artifact_paths": [], "error": "<short failure reason>"}` to the
   in-memory batch results list, do **not** stop the batch, and proceed immediately to the next
   circuito in the list — never turn a per-circuit failure into a question back to the user. This
   override applies **only** inside `/reporte-lote`'s own loop; it does not change one character of
   `report/SKILL.md`'s file or behavior for a standalone `/report`/`/reporte` invocation, which
   remains alert-and-stop exactly as documented there.

   **Step-9 degradation rule (manifest status stays `SUCCESS`).** Step 9 (`vault-circuito`) is
   already alert-and-continue by its own design, standalone or batched — see `report/SKILL.md` step 9
   and `vault-circuito/SKILL.md`'s error table. Inside this loop, a step-9 degradation for `circuito`
   (vault note `skipped_incomplete`/`usage_error`/`execution_error`, or a failed chained `/graphify
   reports/vault --update`) does **NOT** flip that circuit's batch status to `FAILED` — its report
   HTML from steps 2-8 already succeeded. Instead, record the circuit `SUCCESS` exactly as on a clean
   run, but append a short degradation note to its entry: `{"circuito": <circuito>, "status":
   "SUCCESS", "artifact_paths": [<the returned HTML Path>], "error": null, "note": "<short step-9
   degradation reason, e.g. 'vault note skipped_incomplete: missing historical.out.json' or 'graphify
   --update failed: <reason>'>"}`. Only a steps-2-8 failure ever yields `FAILED`; a steps-2-8 success
   followed by a step-9 degradation is always `SUCCESS` (+ note).

   On a circuit's clean completion of step 9 with no degradation, append `{"circuito": <circuito>,
   "status": "SUCCESS", "artifact_paths": [<the returned HTML Path>], "error": null}` to the same
   in-memory list instead (no `note` key).

3. **Summarize the batch and persist the manifest.** Once every circuit in `group.circuitos` has
   either succeeded or been recorded FAILED:
   1. Present the results in chat as a table (circuito, status, report path or failure reason), plus
      success/failure totals.
   2. Pipe the accumulated entries list as a JSON array to the batch contract's manifest verb:
      `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.batch_report_contract write-manifest --grupo <grupo> [--criticidad <label>] --fecha-inicio <fecha_inicio> --fecha-fin <fecha_fin>`
      (omit `--criticidad` for `grupo=todos`, whose label is `None`) with the entries array on
      stdin. Report the returned `manifest_path` to the user alongside the chat table.
   3. This step runs exactly once per batch, after every circuit has resolved one way or the other —
      never mid-loop, and never skipped even when every circuit failed (the manifest must still
      record every failure).

## Error handling summary

| Failure | Where | User-facing outcome |
|---|---|---|
| Unknown `grupo` | Step 1 (this Skill) | Usage error, no dataset load, no circuit runs |
| Lone date given | Step 1 (this Skill) | Usage error, no dataset load, no circuit runs |
| Zero events anywhere in the resolved window (`execution_error`) | Step 1 preflight (this Skill) | Alert at step 1, before any run_dir exists, no confirmation requested |
| Group resolves to zero circuits (`empty_group`) | Step 1 preflight (this Skill) | Alert at step 1, before any run_dir exists, no confirmation requested |
| Any step 2-8 failure for one circuit (zero events in window, `ReportPipelineError`, agent validation retries exhausted) | Step 2 loop, per circuit | Recorded as `FAILED` with a reason in the batch results; the batch **continues** to the next circuit (see "Alert-and-continue override" above) — this is the one deliberate departure from `report/SKILL.md`'s own alert-and-stop table, scoped to this loop only |
| Step 9 degradation for one circuit (vault note `skipped_incomplete`/`usage_error`/`execution_error`, or chained `/graphify --update` failure) — steps 2-8 already succeeded | Step 2 loop, per circuit | Recorded as `SUCCESS` with the returned HTML path AND a short degradation `note` appended (see "Step-9 degradation rule" above); the batch **continues** to the next circuit; this is NEVER `FAILED` |
| Every circuit fails | Step 2 loop (all iterations) | Batch completes without crashing; step 3's summary and manifest list every circuit as `FAILED` with its reason |

None of the rows above, nor any mid-batch condition, turns into a question back to the user — the
single checkpoint is step 1.4 only (see "Single user checkpoint" above). Every failure from step 1's
preflight is an alert-and-stop; every steps-2-8 failure inside step 2's per-circuit loop is an
alert-and-continue recorded as `FAILED`; every step-9-only degradation inside that same loop is an
alert-and-continue recorded as `SUCCESS` with a degradation note.

## Related artifacts

- Batch resolution contract (L1, pure Python, no LLM call anywhere in this module):
  [`src/chec_local_interpreter/batch_report_contract.py`](../../../src/chec_local_interpreter/batch_report_contract.py)
- Per-circuit orchestrator, invoked by reference for steps 2-9 of every circuit in the batch:
  [`.claude/skills/report/SKILL.md`](../report/SKILL.md) /
  [`src/chec_local_interpreter/report_pipeline.py`](../../../src/chec_local_interpreter/report_pipeline.py)
- Step 9's own vault-note + graphify chaining, invoked transitively via `report/SKILL.md` step 9 for
  every circuit in the batch: [`.claude/skills/vault-circuito/SKILL.md`](../vault-circuito/SKILL.md) /
  [`src/chec_local_interpreter/vault_note_contract.py`](../../../src/chec_local_interpreter/vault_note_contract.py)
- Shared criticality-group computation used by the batch contract:
  `plotting.compute_circuit_criticality_groups`
- Structurally closest existing preflight-then-checkpoint Skill (frontmatter shape, Execution Steps
  numbering, Output Contract section):
  [`.claude/skills/agrupamiento-circuitos/SKILL.md`](../agrupamiento-circuitos/SKILL.md)
- Binding invariants (shared with every agent role/orchestrator above):
  `.claude/agents/rules/invariants.md`
- Tests: `tests/test_batch_report_contract.py` (argument/slug validation, group resolution, window
  resolution, manifest persistence and shape, path-injection rejection, CLI verbs)
