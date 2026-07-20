---
name: vault-circuito
description: "Trigger: internal step-9 runbook invoked by /report and /reporte-lote after a circuit's report renders. Projects the circuit's 3 validated narrative JSONs into reports/vault/{circuito}.md and chains an isolated /graphify reports/vault --update against reports/vault's own graph (never the project-root graph). Not intended for direct end-user invocation."
license: Apache-2.0
metadata:
  author: chec-local-uiti-vano-interpreter
  version: "0.1.0"
  runtime: claude
  canonical_contract: src/chec_local_interpreter/vault_note_contract.py
  invoked_by:
    - .claude/skills/report/SKILL.md (step 9)
    - .claude/skills/reporte-lote/SKILL.md (per-circuit step 9, via report/SKILL.md's steps 2-9)
---

## Overview

`vault-circuito` is step 9 of `/report`'s run sequence: a pure post-render projection that turns a
circuit's already-validated `historical.out.json`/`inference.out.json`/`expert-alignment.out.json`
into one upserted Spanish markdown note at `reports/vault/{circuito}.md`, then chains the real
`/graphify reports/vault --update` slash-command — scoped to an isolated graph rooted at
`reports/vault/graphify-out/graph.json`, never the project-root `graphify-out/graph.json` a
whole-project `/graphify .` run produces — so the vault stays incrementally indexed without ever
mixing with or corrupting the unrelated project-wide code/docs graph. It makes NO LLM calls of its
own — `vault_note_contract.py` performs pure file I/O — and it never touches `report_pipeline.py`'s
HTML critical path (steps 2-8 already succeeded and returned their result before this step ever
runs).

## When to Use

Loaded automatically by [`report/SKILL.md`](../report/SKILL.md)'s step 9, immediately after step 8
has already reported the rendered HTML path — both for a standalone `/report` run and for each
circuit inside a `/reporte-lote` batch (which runs `report/SKILL.md`'s steps 2-9 per circuit, per
[`reporte-lote/SKILL.md`](../reporte-lote/SKILL.md)). Not designed for direct end-user invocation —
there is no standalone `/vault-circuito` slash-command trigger. It may be run manually for debugging
via the CLI verb directly (see Related artifacts).

## Argument contract

Takes exactly one argument: `circuito` — the same circuit id already validated and confirmed by the
invoking `/report` run's own step 1. No dates: this step always projects the invoking run's OWN
just-completed `run_dir` implicitly, via `find_latest_run(circuito)` (max-timestamp subdir under
`reports/interpretability/runs/{canonical circuit id}/`), which is guaranteed to resolve to that same
run since it is the run that just wrote the 3 `*.out.json` files consumed here.

## Allowed tools

- **Bash** — restricted to `chec_local_interpreter.vault_note_contract render` (e.g.
  `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.vault_note_contract render <circuito>`)
  and nothing else. Same structural guarantee as every other role/orchestrator in this repo
  (`.claude/agents/rules/invariants.md`, Rule 1). The Python module itself never shells out — it
  performs no subprocess/shell invocation of any kind.
- **Skill** — to chain the real `/graphify` slash-command (step 2 below). This is orchestrator-level
  skill chaining, NOT a subprocess/shell call — `/graphify` is invoked exactly as `report/SKILL.md`
  invokes `historical`/`inference`/`expert-alignment`.
- **Read** — to inspect the resulting `reports/vault/{circuito}.md` when needed for diagnostics.

## Run sequence

**Environment bootstrap.** Run report-contract commands from the repository root with
`PYTHONPATH=src .venv/bin/python`, same as `report/SKILL.md`.

Given `circuito` (already validated/confirmed by the invoking `/report` run's own step 1):

1. **Render and write the vault note.** Run:

   ```bash
   PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.vault_note_contract render <circuito>
   ```

   This delegates to `vault_note_contract.render(circuito)`: finds the latest run dir, loads the 3
   `*.out.json` narratives (`historical.out.json` REQUIRED; `inference.out.json` and
   `expert-alignment.out.json` OPTIONAL — their absence degrades to a `partial` note with
   `> Sección no disponible en esta corrida.` placeholders, not a failure), renders the Spanish
   markdown, and upsert-writes it to `reports/vault/{circuito}.md` (full overwrite, no per-run
   history kept — latest-run-wins). Branch on the returned JSON `status`:
   - `success` or `partial` — the note was written; proceed to step 2.
   - `skipped_incomplete` (no run found, or `historical.out.json` missing/`ok: false`) —
     **alert-and-continue**: emit a clear message naming the missing file(s)/reason, leave any prior
     existing note untouched, and stop THIS step here (do not attempt step 2 — there is nothing new
     to index). This never raises an unhandled exception and never fails the already-completed
     `/report` run.
   - `usage_error`/`execution_error` — same alert-and-continue treatment; report the error and stop
     this step.

2. **Chain `/graphify reports/vault --update`, scoped to its own isolated graph.** Only reached when
   step 1 wrote or overwrote a note. Invoke the real `/graphify` slash-command with the fixed literal
   arguments `reports/vault --update` (never string-built from `circuito` — no injection surface),
   with `reports/vault` as graphify's OWN working directory (every bash block in that invocation
   executes with cwd `reports/vault`, `INPUT_PATH='.'`), so its `graphify-out/` lands at
   `reports/vault/graphify-out/graph.json` — a dedicated, isolated graph, never the project-root
   `graphify-out/graph.json` a whole-project `/graphify .` run produces or reads. `--update` stays
   safe here (unlike a scoped `--update` against a manifest that was ever built from a wider scope,
   which is a real bug caught and fixed elsewhere — see `informe-gerencial/SKILL.md`'s "Resolved
   limitation" note): because this isolated graph's own manifest is ALWAYS built and diffed at the
   same `reports/vault` scope, on every invocation, there is nothing wider for it to misdiagnose as
   deleted. `--update` is cache-aware/incremental: it re-extracts only new/changed files under
   `reports/vault/`, so a single circuit's invocation only processes that circuit's just-written note,
   never a full rebuild — this keeps the frequent, one-circuit-at-a-time cadence of this step cheap.

   **Graphify failure isolation (mandatory alert-and-continue).** If this invocation fails for any
   reason, do **not** roll back or delete the vault note written in step 1, do **not** re-raise into
   the invoking `/report`/`/reporte-lote` run, and do **not** turn it into a question back to the
   user. Emit a clear alert naming the graphify failure and report this step's outcome as the note
   write having succeeded with a graphify-failed sub-status — never a hard failure. Inside a
   `/reporte-lote` batch, this same policy means the enclosing circuit's batch-loop status stays
   `SUCCESS` with a short degradation note appended (see `reporte-lote/SKILL.md`'s "Alert-and-continue
   override" for the exact manifest wording) — it is a steps-2-8 failure, not a step-9 degradation,
   that yields `FAILED`.

## Error handling summary

| Failure | Where | Outcome |
|---|---|---|
| No run found / `historical.out.json` missing or `ok: false` | Step 1 (`vault_note_contract.render` → `skipped_incomplete`) | Alert naming the missing file(s); no note written/modified; step 2 not attempted; the invoking `/report`/`/reporte-lote` run is NOT failed |
| `inference.out.json` and/or `expert-alignment.out.json` missing | Step 1 (`→ partial`) | Note IS written, with placeholder sections for the missing narrative(s); step 2 still runs |
| Isolated `/graphify reports/vault --update` fails (including a shrink-guard trip) | Step 2 | Alert naming the failure; the already-written note from step 1 remains untouched on disk; never rolls back, never blocks, never aborts a `/reporte-lote` batch |

None of the rows above turns into a question back to the user — every outcome is either a silent
success or an alert-and-continue, matching `/reporte-lote`'s own established convention for
per-circuit step failures.

## Related artifacts

- Projection contract (L1, pure Python, no LLM call, no subprocess):
  [`src/chec_local_interpreter/vault_note_contract.py`](../../../src/chec_local_interpreter/vault_note_contract.py)
- Invoking runbooks: [`.claude/skills/report/SKILL.md`](../report/SKILL.md) (step 9, standalone),
  [`.claude/skills/reporte-lote/SKILL.md`](../reporte-lote/SKILL.md) (per-circuit, via
  `report/SKILL.md`'s steps 2-9)
- Chained slash-command: `/graphify` (a real Skill, not a subprocess call — see the design decision
  "How `/graphify` is invoked" in `sdd/vault-circuito/design`)
- Binding invariants: `.claude/agents/rules/invariants.md`
- Tests: `tests/test_vault_note_contract.py` (unit coverage for the pure contract; the runbook
  chaining itself — this file and the step-9/step-2-9 wiring in `report`/`reporte-lote` — is
  prose-only, not pytest-tested, same convention as the rest of the `report`/`reporte-lote` chaining)
