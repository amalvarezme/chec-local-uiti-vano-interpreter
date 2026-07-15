# Report Runtime Contract

The CHEC report workflow is exposed through runtime-native adapters, but report behavior has one source of truth:

- `src/chec_local_interpreter/report_pipeline.py` owns deterministic report stages.
- `src/chec_local_interpreter/report_contract.py` owns request normalization and JSON outcomes.
- `.claude/skills/report/SKILL.md` remains the canonical end-to-end runbook path; its skill name is `report`.

Adapters must translate native invocation syntax into the shared contract. They must not duplicate preparation, diagnosis, inference, expert alignment, simulator, rendering, publication, or validation logic.

## Invocation matrix

| Runtime | Preferred invocation | Notes |
|---|---|---|
| Claude Code | `/report <circuito> [fecha_inicio fecha_fin]` | Existing first-class workflow. |
| OpenCode | `@report <circuito> [fecha_inicio fecha_fin]` | Reliable fallback until project slash-command support is verified. If verified, `/report` may be added as an alias. |
| Codex | `$report <circuito> [fecha_inicio fecha_fin]` | Codex must not prefer `/report`; Pi uses `/skill:report`. |
| Pi / el Gentleman | `/skill:report <circuito> [fecha_inicio fecha_fin]` | Pi-native skill command. |

## Argument contract

- `circuito` is required.
- Dates are optional as a pair.
- Omit both dates to use the circuit's full available range.
- Provide both dates to use an explicit range.
- Providing exactly one date is a usage error. Do not infer or silently default the missing bound.

## Shared preflight

Adapters should resolve the initial window through:

```bash
python -m chec_local_interpreter.report_contract preflight <circuito> [fecha_inicio fecha_fin] --runtime <runtime>
```

The preflight returns JSON with:

- `schema_version`
- `status`
- `request`
- `resolved_window`
- `next_actions`
- `errors`

The parent runtime should show the resolved circuit/date window once and ask for confirmation before any report stage writes a run directory.

## Runtime metadata

Adapters should pass provider and model metadata when the runtime exposes it explicitly:

```bash
python -m chec_local_interpreter.report_contract render <circuito> --run-dir <run_dir> --runtime <runtime> --provider <provider> --model <model>
```

When explicit metadata is absent, the shared contract resolves the effective model from runtime evidence in this order: explicit flags, `CHEC_LLM_PROVIDER` / `CHEC_LLM_MODEL`, runtime session/configuration, then `unknown`. For Pi / el Gentleman, the resolver reads the latest Pi session history for the current project and falls back to `~/.pi/agent/settings.json`; it must not treat adapter markdown frontmatter as execution authority.

## Boundaries

The workflow is local-only:

- no external LLM API calls;
- no automatic publishing;
- no site asset mutation;
- no model training;
- no Optuna search.

Generated reports are local HTML artifacts. Publishing to the site remains a separate deliberate action.
