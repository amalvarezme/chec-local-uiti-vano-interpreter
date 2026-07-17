---
name: report
description: "Run the CHEC UITI_VANO report workflow in Pi / el Gentleman with /skill:report <circuito> [fecha_inicio fecha_fin]. Use for full local circuit reports."
license: Apache-2.0
metadata:
  runtime: pi
  canonical_skill: ../../../.claude/skills/report/SKILL.md
---

# Pi Report Skill

Use this skill for Pi-native report requests:

```text
/skill:report <circuito>
/skill:report <circuito> <fecha_inicio> <fecha_fin>
```

This is a thin Pi adapter over the shared report contract. It preserves el Gentleman orchestration discipline while keeping report behavior in the canonical Python pipeline.

## Source of truth

- `src/chec_local_interpreter/report_pipeline.py` owns report-domain behavior.
- `src/chec_local_interpreter/report_contract.py` owns normalized request/outcome serialization.
- `.claude/skills/report/SKILL.md` remains the canonical end-to-end report runbook.

## Argument rules

- `circuito` is required.
- Dates are optional as a pair.
- Reject a lone date immediately; never infer the missing bound.

## Run sequence

**Environment bootstrap (mandatory).** Run every report-contract and role CLI command from the repository root with `PYTHONPATH=src .venv/bin/python`. Do not try bare `python`/`python3` first and do not declare the environment unavailable merely because they cannot import `chec_local_interpreter`; this repository's supported local command is the virtualenv-prefixed form.

1. Read `.claude/skills/report/SKILL.md` before running the workflow.
2. Preflight through the shared contract:

   ```bash
   PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract preflight <circuito> [fecha_inicio fecha_fin] --runtime pi
   ```

3. State the resolved circuit/date window once and ask the user to confirm.
4. After confirmation, follow the canonical report sequence from `.claude/skills/report/SKILL.md`.
5. Use Pi subagents only for the role-authoring stages when useful and available; keep the parent Pi session responsible for orchestration. Before delegating, inspect the candidate agent's tool permissions: a role author must be able to run the role's `agent_tools.<role> build-context` and `validate` commands and write `run_dir/<role>.out.json`. Do **not** delegate role authoring to a read-only generic worker (including an installed `gentle-ai-worker` profile without Bash/write capability); it cannot complete the role and leaves the run stalled. In that case the parent session must author and validate the role output directly, or use a purpose-built role agent with the required permissions.

   If using a capable generic Pi worker, launch one explicit task per role with the role name and `run_dir/<role>.bc.json` in the first line. Never launch multiple identical workers with a shared prompt that requires the worker to infer whether it is `historical`, `inference`, or `auto-simulator`; that ambiguity must be cancelled and relaunched before render. Before moving to `prepare_expert_alignment` or `render`, require the expected `historical.out.json` and `inference.out.json` files to exist and validate successfully; if either is absent, stop and report the stalled role instead of claiming that the report is generating.
6. **Record Pi subagent usage before render.** The parent MUST take the structured `usage` from each `subagent_run` result and immediately call `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract record-usage --run-dir <run_dir> --stage <role> --total <n>` (or the split form). Do not scrape prose or session history, and do not assume an unavailable runtime API. Then run `verify-usage` with explicit expected/executed roles before render. Each completed Pi role task reports one combined `usage`/`subagent_tokens` value. After `historical`, `inference`, `auto-simulator` (when it ran), and `expert-alignment` complete, pass those measured values immediately to the shared `record-usage` command using the canonical total-only shape; do not write the sidecar ad hoc. This is mandatory whenever Pi exposes the usage values; do not substitute `chars // 4` estimates for the whole run.

   ```json
   {
     "historical": {"total": 77611},
     "inference": {"total": 95483},
     "auto-simulator": {"total": 64436},
     "expert-alignment": {"total": 100067}
   }
   ```

   Include only stages that actually ran. If Pi does not expose a measured total, omit that stage and let the shared renderer label the resulting total as mixed/estimated; never invent a count. The `tokens_total` header is the all-stage figure; the input/output split is unavailable for total-only Pi subagent usage and must not be treated as the full-run count.

   **Also record per-stage duration (mandatory, orchestrator-owned).** Independently of `usage`, note your own wall-clock time immediately before and after each `subagent_run` dispatch and call `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract record-duration --run-dir <run_dir> --stage <role> --seconds <after minus before>`. Pi's `subagent_run` result exposes only a combined `usage` total and NO duration field, so this wall-clock delta — which you own as the orchestrator — is the ONLY duration source and is always available regardless of what the sub-agent returns. Record the final successful attempt's delta only. Include only stages that actually ran; a skipped `auto-simulator` records neither usage nor duration and is omitted from the header. Per-stage duration therefore renders as `medidos` on Pi even though per-stage tokens remain a combined total.
7. When rendering, let the shared contract resolve the effective Pi model from runtime evidence:

   ```bash
   PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract render <circuito> --run-dir <run_dir> --runtime pi
   ```

   The resolver uses explicit flags/env first, then Pi session history, then `~/.pi/agent/settings.json`. Do not read markdown frontmatter as model authority.
8. Return the local HTML report path. Do not publish automatically.

## Boundaries

- No external LLM API calls.
- No automatic publishing or site asset mutation.
- No model training or Optuna search.
- Do not duplicate report preparation, simulator, inference, alignment, validation, or rendering logic.
- Generated technical artifacts remain in English unless the user explicitly requests otherwise.
