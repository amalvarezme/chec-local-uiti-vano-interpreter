---
name: report
description: "Run the CHEC UITI_VANO report workflow from Codex using $report <circuito> [fecha_inicio fecha_fin]. Use for full circuit reports; do not use /report in Codex."
license: Apache-2.0
metadata:
  runtime: codex
  canonical_skill: ../../../.claude/skills/report/SKILL.md
---

# Codex Report Skill

Use this skill for Codex-native report requests:

```text
$report <circuito>
$report <circuito> <fecha_inicio> <fecha_fin>
```

Codex must prefer `$report`. Do not document or suggest `/report` for Codex; Pi / el Gentleman uses `/skill:report`.

## Contract

This is a thin adapter over the shared project contract. It must not implement report-domain behavior.

Source of truth:

- `src/chec_local_interpreter/report_pipeline.py`
- `src/chec_local_interpreter/report_contract.py`
- `.claude/skills/report/SKILL.md`

## Argument rules

- `circuito` is required.
- Dates are optional as a pair.
- If one date is provided without the other, stop with a usage error.
- Never infer a missing date bound.

## Run sequence

**Environment bootstrap.** Run report-contract and role CLI commands from the repository root with `PYTHONPATH=src .venv/bin/python`; do not stop after a bare `python`/`python3` import failure.

1. Read `.claude/skills/report/SKILL.md` for the canonical workflow.
2. Translate `$report` arguments into the shared contract:

   ```bash
   PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract preflight <circuito> [fecha_inicio fecha_fin] --runtime codex
   ```

3. Present the resolved circuit/date window once and ask for confirmation.
4. After confirmation, follow the canonical report sequence:
   - prepare the run directory;
   - run historical, inference, and auto-simulator roles when their contexts exist;
   - prepare and run expert-alignment;
   - render the local HTML report.

   Role-dispatch safety: follow `.claude/skills/report/SKILL.md` exactly. Before delegating, verify that a candidate worker can run `agent_tools.<role> build-context` and `validate` and write `run_dir/<role>.out.json`; never use a read-only/research-only worker to author a role. If no capable worker exists, the parent must execute the role directly. If Codex uses generic workers or parallel tasks, launch one explicit task per role with the role name and `run_dir/<role>.bc.json` in the first line. Never launch multiple identical workers with a shared prompt that requires a worker to infer whether it is `historical`, `inference`, or `auto-simulator`; cancel that ambiguity and relaunch before render. Require validated `historical.out.json` and `inference.out.json` before expert alignment or render; otherwise stop and report the stalled role.

   Token accounting: the host MUST pass actual structured usage immediately to `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract record-usage --run-dir <run_dir> --stage <role>` using exactly `--total <n>` OR `--input <n> --output <n>`; never scrape prose or output sizes. Run `verify-usage` before render and fail closed for missing/invalid executed-role measurements. Unknown runtime APIs are not assumed.
5. Return the local report HTML path.

## Boundaries

- No external LLM API calls.
- No automatic publishing.
- No site asset mutation.
- No model training or Optuna search.
- No duplicated preparation, simulator, inference, alignment, validation, or rendering logic in this adapter.
