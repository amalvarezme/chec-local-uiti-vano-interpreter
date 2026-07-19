---
name: informe-gerencial
description: "Produce one cross-circuit managerial report synthesized across a criticality group's most representative circuits, with a full-fleet clustering scatter highlighting the sampled set. Trigger: /informe-gerencial, managerial report, cross-circuit synthesis, executive report for a criticality tier."
license: Apache-2.0
metadata:
  author: chec-local-uiti-vano-interpreter
  version: "0.1.0"
  runtime: claude
  canonical_contract: src/chec_local_interpreter/informe_gerencial_contract.py
  invokes_skills:
    - .claude/skills/report/SKILL.md
---

## Overview

`/informe-gerencial` produces exactly ONE managerial-facing HTML report synthesized ACROSS the most
representative circuits of one criticality group (or the whole fleet, for `todos`), instead of one
report per circuit. It does not reimplement `/report`'s single-circuit pipeline, `/reporte-lote`'s
batch loop, or `compute_circuit_criticality_groups`'s clustering. It owns exactly the pieces those
three do not: sampling a group down to its 20 most representative circuits (by `centroid_distance`
to their assigned cluster centroid), detecting which of those 20 are missing a prior `/report` run,
gating on a single explicit confirmation before auto-triggering `/report` for the missing ones (by
reference to [`report/SKILL.md`](../report/SKILL.md), never by copying its prose), loading each
sampled circuit's narrative content, and assembling the cross-circuit synthesis (common patterns,
notable outliers, aggregate/fleet-level risk, recommended actions) plus one embedded full-fleet
clustering scatter into a single HTML page. `report/SKILL.md` is never edited and a standalone
`/report`/`/reporte-lote` invocation is completely unaffected by this Skill's existence.

Canonical contract (pure Python, no LLM call anywhere in this module):
[`informe_gerencial_contract.py`](../../../src/chec_local_interpreter/informe_gerencial_contract.py).

## When to Use

Load this Skill when the user wants a single, synthesized, cross-circuit managerial view of a
criticality tier or the whole fleet — e.g. "informe gerencial de Alta", "resumen ejecutivo del grupo
Muy Alta", "/informe-gerencial todos". If the user wants one circuit's full report, use `/report`
directly. If the user wants every circuit's INDIVIDUAL report run in one batch (not a synthesized
cross-circuit view), use `/reporte-lote` instead.

## Argument contract

Invocation: `/informe-gerencial <grupo> [fecha_inicio fecha_fin]`.

- `grupo` — **required**. Must be one of `muy-alta|alta|media|baja|muy-baja|todos`; any other value
  is a usage error, rejected before any dataset access — same allowlist `/reporte-lote` uses.
- `fecha_inicio` / `fecha_fin` — **optional, as a PAIR**, same pair contract `/reporte-lote` uses:
  - Both omitted: resolve to the dataset-wide date range.
  - Both given: passed through unchanged.
  - Exactly one given is a usage error.

Examples:

| Invocation | Result |
|---|---|
| `/informe-gerencial alta` | Group `alta` resolved against the full dataset-wide date range |
| `/informe-gerencial media 2026-01-01 2026-02-01` | Group `media` resolved against that explicit window |
| `/informe-gerencial baja 2026-01-01` | **Rejected** — usage error, `fecha_fin` missing |
| `/informe-gerencial critica` | **Rejected** — usage error, unknown `grupo` |
| `/informe-gerencial todos` | Full fleet computed via `compute_circuit_criticality_groups`, then sampled to 20 |

## Representativeness sampling (>20 circuits)

When the resolved group has more than 20 circuits, exactly the 20 circuits with the smallest
`centroid_distance` (most representative of their cluster) are used — never all of them, never a
random subset. Groups with 20 or fewer circuits use all of them unfiltered. This is entirely owned by
`informe_gerencial_contract.sample_representatives`; this Skill never re-derives or overrides it.

## Single user checkpoint (missing-run confirmation gate)

This Skill has exactly **one** interactive checkpoint, and it fires only when needed:

- If every sampled circuit already has a prior `/report` run, **no gate is shown** — proceed straight
  from step 1 to step 3 (content loading + synthesis + render), same silent-continuation convention
  `/reporte-lote` uses once its own single checkpoint clears.
- If ANY sampled circuit has no prior run, state the missing **count** and the **list of missing
  circuit names** to the user **once**, and require explicit confirmation before auto-triggering
  `report/SKILL.md`'s Run-sequence steps 2-8 (including its sub-step 4b, the auto-simulator dispatch
  — nine distinct actions in total per that Skill's own numbering) for those circuits only. If the
  user declines, **stop here** — do not trigger any missing pipeline and do not proceed to synthesis.

This mirrors the `awaiting_confirmation` → `confirm`/`confirm_and_trigger_missing` contract shape
`informe_gerencial_contract.resolve()` already returns, and the exact same single-checkpoint UX
convention `reporte-lote/SKILL.md` uses for its own gate — never a second confirmation later in the
run, never a per-circuit prompt.

## Full-fleet scatter (non-negotiable)

The embedded clustering scatter in the final report ALWAYS shows the FULL fleet — all 5 criticality
tiers, unfiltered by the requested `grupo` — via `plotting.plot_interactive_circuit_clustering(raw_df,
start_date, end_date, highlighted_circuits=<sampled circuits>)`, called AS-IS against the unfiltered
circuit universe. Only the sampled circuits are marked with an 'X' marker; every other circuit
remains visible as a normal point. Nothing is ever hidden from the scatter, regardless of `grupo`.
This is implemented once, inside `render_managerial_report`; this Skill never builds or filters the
scatter itself.

## Allowed tools

- **Bash** — restricted to invoking the shared contract's own verbs
  (`chec_local_interpreter.informe_gerencial_contract resolve` / `render`, e.g. via `python -m
  chec_local_interpreter.informe_gerencial_contract ...`) for this Skill's own steps 1 and 3, plus
  whatever Bash surface `report/SKILL.md` itself uses while its steps 2-8 run for a missing circuit in
  step 2 below. This Skill never gets a general shell — same structural guarantee as `report` and
  `reporte-lote` (`.claude/agents/rules/invariants.md`, Rule 1). No subprocess/shell string-building
  happens in Python anywhere in this flow: `report/SKILL.md`'s steps are invoked by-reference through
  the Skill tool, never assembled into a shell command from user-controlled text.
- **Skill** — to invoke `report/SKILL.md`'s Run-sequence steps 2-8, per missing circuit, in step 2's
  loop. `report/SKILL.md` governs its own further Bash/Skill/Read restrictions independently for those
  steps; this Skill does not bypass them.
- **Read** — to inspect the contract's JSON output and the final rendered HTML path.

## Run sequence

**Environment bootstrap.** Run `informe_gerencial_contract` commands from the repository root with
`PYTHONPATH=src .venv/bin/python`, same as `report/SKILL.md` and `reporte-lote/SKILL.md`.

Given `grupo` (and optionally `fecha_inicio`/`fecha_fin` as a validated pair):

1. **Resolve the group, sample, detect missing runs, and get the one-time user confirmation.**
   1. Reject an unknown `grupo` or a lone date per the argument contract above — usage error, stop
      here, no dataset load needed.
   2. Resolve via the shared contract's `resolve` verb:
      `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.informe_gerencial_contract resolve <grupo> [fecha_inicio fecha_fin] --runtime claude`.
      This delegates to `resolve(...)`, which loads the dataset, resolves the window (dataset-wide
      default via `_dataset_date_range` when omitted, or the explicit pair), computes criticality via
      `compute_circuit_criticality_groups` directly (independent of, and never calling,
      `batch_report_contract.preflight_batch`'s own `todos` bypass), samples down to the 20 most
      representative circuits when the group exceeds that threshold, and checks each sampled circuit
      for a prior `/report` run.
   3. Branch on the returned `status`:
      - `usage_error` or `execution_error` — **alert** with the returned error message(s) and
        **stop**. No confirmation requested, nothing triggered.
      - `empty_group` — **alert** naming the group label and window (e.g. "grupo `<label>` sin
        circuitos en la ventana `<fecha_inicio>`..`<fecha_fin>`, nada que ejecutar") and **stop**.
      - `awaiting_confirmation` — proceed to 1.4.
   4. State the resolved group label, the resolved `fecha_inicio`..`fecha_fin` window, the sampled
      circuit count (out of the group's total `circuit_count`), and — only when `missing_runs.count >
      0` — the missing count and the full `missing_runs.circuitos` list, back to the user **once**,
      and get their confirmation before proceeding. This is the single checkpoint described above.
      If `missing_runs.count == 0`, this confirmation still covers proceeding straight to step 3 (no
      missing-run sub-list to show, but the checkpoint still applies before touching content/synthesis).

2. **Auto-trigger `/report` for each missing circuit, in order (only when `missing_runs.count > 0`
   and the user confirmed).** For each `circuito` in the confirmed `missing_runs.circuitos` list,
   sequentially: execute [`report/SKILL.md`](../report/SKILL.md)'s Run-sequence **steps 2 through 8
   exactly as written there** (including its sub-step 4b), substituting the current `circuito` and
   THIS Skill's already-resolved `fecha_inicio`/`fecha_fin` for `report/SKILL.md`'s own step-1
   outputs — no per-circuit re-preflight, no new date window. Do **not** run `report/SKILL.md`'s step
   1 for any circuit; this Skill's step 1 already replaced it for the whole group.

   **Alert-and-continue override (scoped to this loop only, same convention `reporte-lote` uses).** On
   any step 2-8 failure for `circuito` (zero events in the window, a `ReportPipelineError`, or agent
   validation retries exhausted), record it and proceed to the next missing circuit — never turn a
   per-circuit failure into a question back to the user. A circuit that fails here still has no
   content in the final synthesis step (its `load_circuit_content` call returns `None`; the render
   step's Annex marks it "sin contenido disponible" instead of erroring the whole report).

3. **Load content, synthesize, and render the single HTML report.** Once every missing circuit has
   either succeeded or been recorded as failed in step 2 (or step 2 was skipped because nothing was
   missing), run the shared contract's `render` verb:
   `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.informe_gerencial_contract render <grupo> [fecha_inicio fecha_fin] --runtime claude`.
   This re-resolves the SAME deterministic group/window/sampling as step 1 (K-Means is
   `random_state=42`-seeded, so the sampled 20 are reproducible), then for each sampled circuit calls
   `load_circuit_content` (vault-note preferred, raw-JSON fallback per Content sourcing below),
   assembles the cross-circuit synthesis via `synthesize(...)` (Resumen ejecutivo del grupo, Patrones
   comunes, Circuitos atípicos, Riesgo agregado, Acciones recomendadas, Anexo por circuito), renders
   the full HTML page via `render_managerial_report(...)` with the embedded full-fleet scatter
   described above, and persists it to disk. Report the returned `output_html` path to the user. This
   step runs exactly once per invocation and never asks the user anything further.

## Content sourcing

For each sampled circuit, `load_circuit_content` prefers `reports/vault/{circuito}.md` as the
narrative source; if absent, it falls back to the raw `expert-alignment.out.json` run artifact under
`reports/interpretability/runs/{circuito}/`. If neither exists (e.g. step 2's auto-trigger failed for
that circuit), the circuit still appears in the report's Anexo section, marked as having no content
available — the report is never blocked by one circuit's missing content.

## Error handling summary

| Failure | Where | User-facing outcome |
|---|---|---|
| Unknown `grupo` | Step 1 (this Skill) | Usage error, no dataset load, no circuit runs |
| Lone date given | Step 1 (this Skill) | Usage error, no dataset load, no circuit runs |
| Zero events anywhere in the resolved window (`execution_error`) | Step 1 (this Skill) | Alert at step 1, before any confirmation is requested |
| Group resolves to zero circuits (`empty_group`) | Step 1 (this Skill) | Alert at step 1, before any confirmation is requested |
| User declines the confirmation | Step 1.4 | **Stop.** No `/report` auto-trigger, no synthesis, no HTML produced |
| Any step 2-8 failure for one missing circuit | Step 2 loop, per circuit | Recorded and skipped; the loop **continues** to the next missing circuit (alert-and-continue, same departure `reporte-lote` documents, scoped to this loop only) |
| A sampled circuit still has no content at render time | Step 3 (`load_circuit_content` returns `None`) | Annex entry marked "sin contenido disponible"; the report still renders for every other circuit |

None of the rows above, nor any mid-run condition, turns into a second question back to the user —
the single checkpoint is step 1.4 only.

## Non-goals (explicit — do not touch)

- `plotting.run_kmeans`'s signature and return value are never modified by this Skill or its
  contract.
- `batch_report_contract.preflight_batch`'s own `todos` bypass is never called or modified; this
  Skill's `todos` path always goes through `compute_circuit_criticality_groups` directly via
  `resolve_group_dataframe`.
- `/reporte-lote` and `/report` (direct invocation) behavior is unchanged by this Skill's existence —
  their own SKILL.md files are never edited here.
- No shared HTML-shell helper is extracted from `plotting.render_llm_analysis` in this change; the
  managerial report's HTML shell is its own small, self-contained implementation in
  `render_managerial_report` (accepted duplication, logged as follow-up tech debt).

## Related artifacts

- Cross-circuit synthesis contract (L1, pure Python, no LLM call anywhere in this module):
  [`src/chec_local_interpreter/informe_gerencial_contract.py`](../../../src/chec_local_interpreter/informe_gerencial_contract.py)
- Per-circuit orchestrator, invoked by reference for missing circuits in step 2:
  [`.claude/skills/report/SKILL.md`](../report/SKILL.md) /
  [`src/chec_local_interpreter/report_pipeline.py`](../../../src/chec_local_interpreter/report_pipeline.py)
- Structurally closest sibling Skill (batch resolution + single-checkpoint gate, alert-and-continue
  loop convention): [`.claude/skills/reporte-lote/SKILL.md`](../reporte-lote/SKILL.md)
- Shared criticality-group computation reused directly (never through `preflight_batch`'s `todos`
  bypass): `plotting.compute_circuit_criticality_groups`
- Shared full-fleet clustering scatter, reused AS-IS with `highlighted_circuits`:
  `plotting.plot_interactive_circuit_clustering`
- Binding invariants (shared with every agent role/orchestrator above):
  `.claude/agents/rules/invariants.md`
- Tests: `tests/test_informe_gerencial_contract.py` (sampling, group resolution, missing-run
  detection, content loading, `resolve()`/`render_and_write()` status matrices, path-injection
  rejection, `synthesize`/`render_managerial_report` section assembly and full-fleet-highlight
  behavior, CLI verbs)
