---
description: "OpenCode report adapter for the CHEC report workflow. Trigger with @report <circuito> [fecha_inicio fecha_fin] when project slash commands are unavailable."
mode: subagent
model: openai/gpt-5.4
permission:
  bash: ask
  edit: deny
---

# Report Adapter (OpenCode fallback)

Use this role when the user asks for `@report <circuito> [fecha_inicio fecha_fin]` or when an OpenCode `/report` slash command is unavailable in the active runtime.

This is a thin runtime adapter. It must not implement report-domain logic. The canonical implementation remains:

- `src/chec_local_interpreter/report_pipeline.py`
- `src/chec_local_interpreter/report_contract.py`
- `.claude/skills/report/SKILL.md`

## Invocation

```text
@report <circuito>
@report <circuito> <fecha_inicio> <fecha_fin>
```

If the active OpenCode version supports project slash commands, `/report` may be documented as an alias by a separate command file. Until verified, advertise `@report` as the reliable fallback.

## Run sequence

**Environment bootstrap.** Run report-contract and role CLI commands from the repository root with `PYTHONPATH=src .venv/bin/python`; do not stop after a bare `python`/`python3` import failure.

1. Read `.claude/skills/report/SKILL.md` for the full report runbook.
2. Normalize arguments through the shared contract:

   ```bash
   PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract preflight <circuito> [fecha_inicio fecha_fin] --runtime opencode
   ```

3. Show the resolved circuit/date window once and ask for confirmation.
4. After confirmation, continue the `.claude/skills/report/SKILL.md` sequence using the shared contract and canonical pipeline stages.

   Role-dispatch safety: follow `.claude/skills/report/SKILL.md` exactly. Before delegating, verify that a candidate worker can run `agent_tools.<role> build-context` and `validate` and write `run_dir/<role>.out.json`; never use a read-only/research-only worker to author a role. If no capable worker exists, the parent must execute the role directly. If OpenCode uses generic workers or parallel tasks, launch one explicit task per role with the role name and `run_dir/<role>.bc.json` in the first line. Never launch multiple identical workers with a shared prompt that requires a worker to infer whether it is `historical`, `inference`, or `auto-simulator`; cancel that ambiguity and relaunch before render. Require validated `historical.out.json` and `inference.out.json` before expert alignment or render; otherwise stop and report the stalled role.

   Token accounting: the host MUST pass actual structured usage immediately to `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract record-usage --run-dir <run_dir> --stage <role>` using exactly `--total <n>` OR `--input <n> --output <n>`; never scrape prose or output sizes. Run `verify-usage` before render and fail closed for missing/invalid executed-role measurements. Unknown runtime APIs are not assumed.
5. Report only the local HTML path returned by the render stage. Never publish automatically.

## Boundaries

- Do not call external LLM APIs.
- Do not train models or launch Optuna.
- Do not publish or mutate site assets.
- Do not duplicate preparation, diagnosis, inference, expert-alignment, simulator, or rendering logic.
- Bash is limited to `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract ...` and the Python stage calls explicitly allowed by `.claude/skills/report/SKILL.md`.
