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
    - .claude/skills/agrupamiento-circuitos/SKILL.md
    - .claude/skills/graphify/SKILL.md
---

## Overview

`/informe-gerencial` produces exactly ONE managerial-facing HTML report synthesized ACROSS the most
representative circuits of one criticality group (or the whole fleet, for `todos`), instead of one
report per circuit. It does not reimplement `/report`'s single-circuit pipeline, `/reporte-lote`'s
batch loop, or `compute_circuit_criticality_groups`'s clustering. It owns exactly the pieces those
three do not: sampling a group down to its 12 most representative circuits (by `centroid_distance`
to their assigned cluster centroid), detecting which of those 12 are missing a prior `/report` run,
gating on a single explicit confirmation before auto-triggering `/report` for the missing ones (by
reference to [`report/SKILL.md`](../report/SKILL.md), never by copying its prose), **always**
rendering the standalone circuit-clustering chart for the confirmed window right after that same
checkpoint (step 1.5, reusing `agrupamiento-circuitos`'s own shared contract by reference, never a
second confirmation), loading each sampled circuit's narrative content, and assembling the
cross-circuit synthesis (common patterns,
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

- `grupo` — **required**. Must be one of `muy-alta|alta|medio-alta|medio-baja|baja|todos`; any other value
  is a usage error, rejected before any dataset access — same allowlist `/reporte-lote` uses.
- `fecha_inicio` / `fecha_fin` — **optional, as a PAIR**, same pair contract `/reporte-lote` uses:
  - Both omitted: resolve to the dataset-wide date range.
  - Both given: passed through unchanged.
  - Exactly one given is a usage error.

Examples:

| Invocation | Result |
|---|---|
| `/informe-gerencial alta` | Group `alta` resolved against the full dataset-wide date range |
| `/informe-gerencial medio-alta 2026-01-01 2026-02-01` | Group `medio-alta` resolved against that explicit window |
| `/informe-gerencial baja 2026-01-01` | **Rejected** — usage error, `fecha_fin` missing |
| `/informe-gerencial critica` | **Rejected** — usage error, unknown `grupo` |
| `/informe-gerencial todos` | Full fleet computed via `compute_circuit_criticality_groups`, then sampled to 12 |

## Representativeness sampling (>12 circuits)

When the resolved group has more than 12 circuits, exactly the 12 circuits with the smallest
`centroid_distance` (most representative of their cluster) are used — never all of them, never a
random subset. Groups with 12 or fewer circuits use all of them unfiltered. This is entirely owned by
`informe_gerencial_contract.sample_representatives`; this Skill never re-derives or overrides it.

## Single user checkpoint (missing-run confirmation gate)

This Skill has exactly **one** interactive checkpoint, and it fires only when needed:

- If every sampled circuit already has a prior `/report` run, **no gate is shown** — proceed straight
  from step 1 to step 3 (content loading + synthesis + render), same silent-continuation convention
  `/reporte-lote` uses once its own single checkpoint clears.
- If ANY sampled circuit has no prior run, state the missing **count** and the **list of missing
  circuit names** to the user **once**, and require explicit confirmation before auto-triggering
  `report/SKILL.md`'s Run-sequence steps 2-8 ONLY (including its sub-step 4b, the auto-simulator
  dispatch — nine distinct actions in total per that Skill's own numbering; step 9, the
  vault-note-plus-chained-`/graphify` projection, is deliberately excluded here — see step 2's own
  vault-population sub-step below) for those circuits only. If the user declines, **stop here** — do
  not trigger any missing pipeline and do not proceed to synthesis.

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
  whatever Bash surface `report/SKILL.md` itself uses while its steps 2-8 (ONLY — never its step 9) run
  for a missing circuit in step 2 below, plus this Skill's own two additional direct CLI verbs: `python
  -m chec_local_interpreter.vault_note_contract render <circuito>` (step 2's new vault-population
  sub-step) and `python -m chec_local_interpreter.graph_view_builder build ...` (step 2.5's new
  sub-step). This Skill never gets a general shell — same structural guarantee as `report` and
  `reporte-lote` (`.claude/agents/rules/invariants.md`, Rule 1). No subprocess/shell string-building
  happens in Python anywhere in this flow: `report/SKILL.md`'s steps are invoked by-reference through
  the Skill tool, never assembled into a shell command from user-controlled text.
- **Skill** — to invoke `report/SKILL.md`'s Run-sequence steps 2-8 ONLY, per missing circuit, in step
  2's loop. `report/SKILL.md` governs its own further Bash/Skill/Read restrictions independently for
  those steps; this Skill does not bypass them.
  - **`graphify/SKILL.md` carve-out, scoped to step 2.5 only** — a full (non-incremental) graphify
    rebuild scoped to `reports/vault` as graphify's OWN working directory (never `--update` against
    the shared project-root graph — see step 2.5.2 for why) and `/graphify query "<question>"` are
    invoked ONLY inside step 2.5, to produce the cross-circuit graph-patterns JSON handed to step 3's
    `--graph-patterns`. This is the ONLY place any LLM-assisted/graph tool is invoked in this Skill's
    entire run sequence; step 1, step 2's `/report` loop, and step 3's `render` verb never touch
    `graphify`. `informe_gerencial_contract.py` itself never calls `graphify` or any LLM — it only
    reads the JSON file step 2.5 already wrote (design: "LLM step lives in the SKILL runbook, file
    handoff to Python").
    **Carve-out note:** step 2's new vault-population sub-step below directly calls
    `vault_note_contract.render(circuito)` — the same vault PROJECTION `report/SKILL.md`'s own step 9
    performs — but deliberately WITHOUT step 9's chained `/graphify` call. That duplicated projection is
    a direct Python/CLI render call, not a `/graphify` invocation, so this invariant ("step 2.5 is the
    ONLY place any LLM-assisted/graph tool is invoked") stays true; step 2.5's new sub-step 2.5.6
    (`graph_view_builder build`, see below) is likewise a plain CLI verb over an already-refreshed
    `graph.json`, not a `/graphify` call itself, so it does not violate this invariant either.
- **Read** — to inspect the contract's JSON output and the final rendered HTML path.
- **Write** — scoped to step 2.5 only, to persist the agent-authored graph-patterns JSON to
  `reports/interpretability/runs/.informe-gerencial/graph-patterns.<grupo>.<win>.json` and the
  `graph_view_builder`-produced graph-view HTML to
  `reports/interpretability/runs/.informe-gerencial/graph-view.<grupo>.<win>.html` before step 3 reads
  them back.

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
      `batch_report_contract.preflight_batch`'s own `todos` bypass), samples down to the 12 most
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
   5. **Render the circuit-clustering chart for the confirmed window (always, no exceptions).**
      Immediately once 1.4's confirmation clears — before step 2's missing-circuit auto-trigger (or,
      when nothing is missing, before step 3) — run the same shared contract `agrupamiento-circuitos`
      uses, directly by its render verb:
      `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.circuit_clustering_contract render <fecha_inicio> <fecha_fin> --runtime claude`.
      Reuse this Skill's own already-resolved/confirmed `fecha_inicio`/`fecha_fin` from 1.2-1.4 — never
      re-run `agrupamiento-circuitos`'s own preflight or its own confirmation prompt, since that would
      ask the user to confirm the identical window a second time in the same checkpoint. Unconditional:
      run it for every `/informe-gerencial` invocation regardless of `grupo`, including `todos`, and
      independent of whether `missing_runs.count` is 0. A failure here is alert-and-**continue** (see
      the Error handling summary below) — it never blocks or delays step 2/3. Report the returned
      `output_html` path to the user alongside the step 1.4 confirmation summary. Note this is a
      distinct artifact from the full-fleet scatter embedded inside the final managerial HTML by step
      3 (see "Full-fleet scatter (non-negotiable)" below) — the two never substitute for each other.

2. **Auto-trigger `/report` for each missing circuit, in order (only when `missing_runs.count > 0`
   and the user confirmed).** For each `circuito` in the confirmed `missing_runs.circuitos` list,
   sequentially: execute [`report/SKILL.md`](../report/SKILL.md)'s Run-sequence **steps 2 through 8
   exactly as written there, and NO FURTHER** (including its sub-step 4b, but explicitly stopping
   before its own step 9 — see the vault-population sub-step below), substituting the current
   `circuito` and THIS Skill's already-resolved `fecha_inicio`/`fecha_fin` for `report/SKILL.md`'s own
   step-1 outputs — no per-circuit re-preflight, no new date window. Do **not** run `report/SKILL.md`'s
   step 1 for any circuit; this Skill's step 1 already replaced it for the whole group.

   **Alert-and-continue override (scoped to this loop only, same convention `reporte-lote` uses).** On
   any step 2-8 failure for `circuito` (zero events in the window, a `ReportPipelineError`, or agent
   validation retries exhausted), record it and proceed to the next missing circuit — never turn a
   per-circuit failure into a question back to the user. A circuit that fails here still has no
   content in the final synthesis step (its `load_circuit_content` call returns `None`; the render
   step's Annex marks it "sin contenido disponible" instead of erroring the whole report). A circuit
   that fails here also skips the vault-population sub-step below entirely (there is nothing to
   project a vault note from).

   **Vault population (new sub-step, runs once steps 2-8 succeed for `circuito`).** Immediately after
   steps 2-8 succeed for this `circuito` (never on a step 2-8 failure — see above), run
   `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.vault_note_contract render <circuito>`
   directly — the SAME vault PROJECTION `report/SKILL.md`'s own step 9 performs, called here as a
   direct CLI verb rather than by re-executing step 9 verbatim, and deliberately WITHOUT step 9's
   chained `/graphify reports/vault --update` (that graphify refresh happens exactly once, batched for
   every sampled circuit together, in step 2.5 below — never per-circuit here). This projects
   `reports/vault/<circuito>.md` before step 2.5 runs. A non-zero exit (`usage_error`,
   `skipped_incomplete`, or `execution_error`) is **alert-and-continue**: record it and proceed to the
   next missing circuit — it NEVER rolls back this circuit's already-succeeded steps 2-8 report
   artifacts (see the Error handling summary below).

2.5. **Refresh the graph, query cross-circuit patterns, and hand off a validated JSON file to step 3
   (always attempted, degrades gracefully, never a second confirmation).** Runs once, after step 2 (so
   every sampled circuit's vault note is as current as it will get for this run), before step 3's
   render. Entirely non-interactive; on any failure it alerts and continues per the Error handling
   summary below — the deterministic sections of the report always render regardless.
   1. **Skip condition:** if fewer than 2 circuits were sampled (`len(sampled) < 2`), skip this step
      entirely — cross-circuit comparison is meaningless for a single circuit — and proceed to step 3
      without a `--graph-patterns` path (the contract's own `n_sampled < 2` render state then omits the
      subsection; see `_graph_patterns_html`).
   2. **Delete, then force a graph rebuild, fully isolated from the project-wide graph:** before
      invoking graphify, delete `reports/vault/graphify-out/` in its entirety (`graph.json`, `cache/`,
      `manifest.json`, and every other sidecar it contains) — mandatory every single invocation,
      regardless of whether a prior `graphify-out/` exists or looks healthy. Only then run the
      graphify pipeline (`.claude/skills/graphify/SKILL.md`, by reference — same "by reference, never
      copying its prose" convention step 2 uses for `/report`) with `reports/vault` as graphify's OWN
      working directory AND input path (every bash block in that run executes with cwd
      `reports/vault`, `INPUT_PATH='.'`), so its own `graphify-out/` lands at
      `reports/vault/graphify-out/graph.json` — structurally identical in shape to the project-root
      `graphify-out/graph.json` an ordinary whole-project `/graphify .` run produces, but a genuinely
      SEPARATE file, never read or written by that other run, and never touched by anything outside
      this step.

      **Why deleting first is mandatory, not just "pass full mode":** a scoped `--update` against a
      manifest ever built from a wider scope was the original bug this isolation eliminated (a prior
      run of this step, before that fix, misread ~271 unrelated project files as "deleted" and would
      have pruned them from the shared project graph) — but "full mode" alone does not fully close
      this. Confirmed in production twice: an `/informe-gerencial alta` run's step 2.5 silently
      dropped previously-cached concept nodes and collapsed edges 256→26 while nominally running
      "full" extraction, because graphify's own content-hash semantic-extraction cache (Step 3 Part
      B0 of its own SKILL.md) reuses cached per-file results across invocations **regardless of
      `--update` vs. full mode**; the very next `/informe-gerencial medio-alta` run then found
      `reports/vault/graphify-out/graph.json` already sitting at 0 edges on disk before doing any
      work, inherited unnoticed from that same corruption. A cross-run content-hash cache is exactly
      the incremental-in-spirit shortcut this step exists to avoid, even when no `--update` flag is
      ever passed. Deleting the whole directory first — cache included — guarantees every node and
      edge is freshly re-derived from the vault notes' actual on-disk content every invocation, with
      nothing left to merge from and nothing to silently disagree with. The vault corpus is tiny
      (typically 4-40 short markdown notes, a few thousand words total), so a fully fresh extraction
      costs effectively nothing extra — this is a correctness fix, not a cost trade-off.

      Because the directory is deleted first, graphify's own `#479` shrink-guard (refusing to write a
      graph smaller than the existing `graph.json`) can never trigger for this step — there is no
      existing file left to shrink against. If the rebuild itself fails outright (a hard error, a
      timeout, or `Graph is empty`), alert and **continue** straight to step 3 with no
      `--graph-patterns` path (same alert-and-continue convention step 1.5's chart render already
      uses) — never retry, never block, and NEVER fall back to reading the project-root
      `graphify-out/graph.json` instead — that file is out of scope for this step, unconditionally.
   3. **Query for recurring cross-circuit themes** against THIS isolated vault graph only (invoke
      `graphify query` with `reports/vault` as its own working directory, same isolation as step 2.5.2
      — never the project-root graph), restricted to circuits that actually have a vault note (drop any
      sampled circuit with none from the query's own input list — it simply does not contribute a data
      point, the graph step still runs for the rest):
      `/graphify query "temas recurrentes en <lista de circuitos muestreados con nota de bóveda>"`.
   4. **Parse the answer into the validated JSON shape** (`informe-gerencial-graph-patterns/v1`):
      `{"schema_version": "informe-gerencial-graph-patterns/v1", "query": "<the question asked>",
      "min_support": 2, "patterns": [{"tema": "...", "circuitos": ["...", "..."], "soporte": N}, ...]}`.
      Only include a pattern if it recurs in `>= 2` distinct queried circuits (min support) — the
      contract's own `load_graph_patterns` re-validates and re-filters this on read, so a
      generously-inclusive parse here is safe, never a correctness requirement on this step alone.
   5. **Write the file** to
      `reports/interpretability/runs/.informe-gerencial/graph-patterns.<grupo>.<fecha_inicio>_<fecha_fin>.json`
      (creating the `.informe-gerencial/` directory if absent), then pass that exact path to step 3 as
      `--graph-patterns <path>`.
   6. **Build the scoped graph-view figure** (new sub-step, runs after the JSON write above, regardless
      of whether steps 2.5.2-2.5.5 succeeded or degraded — it only needs the isolated `graph.json` that
      step 2.5.2's rebuild already produced on disk, whether from this run or a prior one): run
      `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.graph_view_builder build --graph-json
      reports/vault/graphify-out/graph.json --output
      reports/interpretability/runs/.informe-gerencial/graph-view.<grupo>.<fecha_inicio>_<fecha_fin>.html
      --sampled <sampled circuits that have a vault note>`. This is a plain Python CLI invocation, never
      a `/graphify` slash-command call (see the Allowed-tools carve-out note above) — it reads the
      isolated vault graph directly via `graphify.export.to_html`, isolated inside that module only,
      and NEVER the project-root `graphify-out/graph.json`. The figure's "Communities" side panel is
      grouped PER SAMPLED CIRCUIT (one toggleable checkbox per circuit, plus a shared bucket for any
      bridge node with no single owning circuit) — never graphify's own topic-based clustering — so a
      reader can isolate one circuit's contribution to the cross-circuit sub-graph. On success, pass
      the written HTML path to
      step 3 as `--graph-view <path>`. On any failure (`execution_error`, `skipped_empty`, or a non-zero
      exit), alert and **continue** straight to step 3 with no `--graph-view` path — exactly the same
      alert-and-continue convention the graph-rebuild-fails row above already uses; the itemized
      graph-patterns list (if it built) still renders, only the embedded figure is omitted.

3. **Load content, synthesize, and render the single HTML report.** Once step 2.5 has either produced a
   graph-patterns path and/or a graph-view path, or been skipped/failed (never blocks on either), run
   the shared contract's `render` verb:
   `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.informe_gerencial_contract render <grupo> [fecha_inicio fecha_fin] --runtime claude [--graph-patterns <path from step 2.5.5>] [--graph-view <path from step 2.5.6>]`.
   This re-resolves the SAME deterministic group/window/sampling as step 1 (K-Means is
   `random_state=42`-seeded, so the sampled 12 are reproducible), then for each sampled circuit calls
   `load_circuit_content` (vault-note preferred, raw-JSON fallback per Content sourcing below),
   loads and re-validates `--graph-patterns` via `load_graph_patterns` (missing/omitted path -> `None`,
   malformed file -> `[]`, valid file -> filtered/recomputed pattern list, never raising regardless of
   what step 2.5 produced), loads `--graph-view` via `load_graph_view` (missing/omitted path -> `None`,
   unreadable -> `None`, readable -> raw HTML text, never raising), assembles the cross-circuit
   synthesis via `synthesize(...)` (Resumen ejecutivo del grupo, Patrones comunes, Circuitos atípicos,
   Riesgo agregado, Acciones recomendadas, Anexo por circuito), renders the full HTML page via
   `render_managerial_report(...)` with the embedded full-fleet scatter described above plus the
   "Patrones cross-circuito (grafo)" subsection (labeled "Interpretación asistida por LLM (grafo)",
   visibly distinct from the deterministic "Patrones comunes"/"Cálculo determinista" table) — including,
   when both the itemized pattern list AND the graph-view HTML are available, the embedded `srcdoc`
   figure alongside the list; when only the list is available, the list alone with a muted indicator
   that the figure is not available this run — and persists the whole report to disk. Report the
   returned `output_html` path to the user. This step runs exactly once per invocation and never asks
   the user anything further.

## Content sourcing

For each sampled circuit, `load_circuit_content` prefers `reports/vault/{circuito}.md` as the
narrative source; if absent, it falls back to the raw `expert-alignment.out.json` run artifact under
`reports/interpretability/runs/{circuito}/`. If neither exists (e.g. step 2's auto-trigger failed for
that circuit), the circuit still appears in the report's Anexo section, marked as having no content
available — the report is never blocked by one circuit's missing content. When a vault note is used
AND a prior run directory is resolvable, `cause_hypothesis_note`/`variable_groups_used`/
`variables_a_priorizar` are sourced from that run's own JSON artifacts (same completeness as the
raw-JSON path, via the shared `_structured_fields` helper); when no run directory is resolvable, only
`cause_hypothesis_note` is recovered, parsed directly from the note's own `### Hipótesis de causa`
section — `variable_groups_used`/`variables_a_priorizar` are never fabricated from the note text.

## Cross-circuit graph patterns (step 2.5)

Beyond the deterministic `patrones_comunes` (tallies of each circuit's OWN previously-produced
technical fields), the final report's "Patrones cross-circuito (grafo)" subsection surfaces themes
that recur ACROSS the sampled circuits' vault notes, mined by `/graphify query` over an isolated,
vault-only knowledge graph (`reports/vault/graphify-out/graph.json`, rebuilt fresh every invocation —
see step 2.5.2) — the one and only LLM-assisted step in this Skill's run sequence (see Allowed tools
above). It degrades independently of every other section:

| Condition | Behavior |
|---|---|
| Fewer than 2 circuits sampled | Step 2.5 is skipped outright; the subsection is omitted from the HTML entirely (no muted placeholder — cross-circuit comparison does not apply to a single circuit) |
| One or more sampled circuits lack a vault note | Those circuits are excluded from the `/graphify query` input only; the step still runs for the remaining circuits with notes |
| The isolated vault-graph rebuild (step 2.5.2) fails outright or times out | Alert-and-**continue** straight to step 3 with no `--graph-patterns` path — the deterministic sections still render; subsection shows "análisis de grafo no disponible en esta corrida" |
| `/graphify query` returns nothing meeting `soporte >= 2` | The written JSON has an empty `patterns` list; subsection shows "sin patrones recurrentes con soporte >= 2" explicitly (never a silent omission) |
| `graph_view_builder build` (sub-step 2.5.6) fails, or the sub-graph has no matched nodes | Alert-and-**continue** straight to step 3 with no `--graph-view` path — the itemized pattern list still renders (independently of this failure), only the embedded figure is omitted |

**Resolved limitation (formerly documented as a known limitation, fixed by the isolation change
above):** the previous design ran `/graphify reports/vault --update` as an incremental refresh
against a manifest that could be scoped wider than `reports/vault` (e.g. a whole-project graph built
at repo root) — besides the staleness risk this created (a deleted vault note not immediately
reflected by the incremental cache, so a stale pattern citing it could surface), a repo-root-anchored
manifest diffed against a subfolder-scoped rescan could misinterpret unrelated project files as
"deleted from scope" and prune real project-wide graph nodes on merge — a bug caught in production
before it corrupted the shared graph. Rebuilding a genuinely isolated vault-only graph from scratch
every invocation (step 2.5.2) eliminates both failure modes: there is no shared manifest to
misdiagnose, and the graph always reflects exactly what is currently on disk in `reports/vault/`,
never a stale incremental snapshot. `informe_gerencial_contract.load_graph_patterns` still additionally
intersects every pattern's `circuitos` with the CURRENT `sampled` list and recomputes `soporte` from
that intersection as defense-in-depth, but this is no longer compensating for a known staleness gap.

**Second resolved limitation (delete-before-rebuild):** "full (non-incremental) rebuild" alone was
not sufficient — graphify's own content-hash semantic-extraction cache (Step 3 Part B0 of its own
SKILL.md) persists across invocations regardless of `--update` vs. full mode, so a "full" rebuild
could still silently reuse and merge stale per-file cache entries. This produced two confirmed
production incidents: a `/informe-gerencial alta` step 2.5 run that collapsed edges 256→26 while
mid-run, and the graph sitting corrupted at 0 edges when the following `/informe-gerencial
medio-alta` run started. Step 2.5.2 now deletes `reports/vault/graphify-out/` (graph, cache, and
manifest) before every rebuild, so there is no cross-run cache left to consult — see step 2.5.2's own
prose for the full mechanism. As a direct consequence, graphify's `#479` shrink-guard can no longer
trigger for this step either (there is no existing `graph.json` left to shrink against), so that row
is removed from the tables above and below; only an outright rebuild failure or timeout degrades this
step now.

## Error handling summary

| Failure | Where | User-facing outcome |
|---|---|---|
| Unknown `grupo` | Step 1 (this Skill) | Usage error, no dataset load, no circuit runs |
| Lone date given | Step 1 (this Skill) | Usage error, no dataset load, no circuit runs |
| Zero events anywhere in the resolved window (`execution_error`) | Step 1 (this Skill) | Alert at step 1, before any confirmation is requested |
| Group resolves to zero circuits (`empty_group`) | Step 1 (this Skill) | Alert at step 1, before any confirmation is requested |
| User declines the confirmation | Step 1.4 | **Stop.** No `/report` auto-trigger, no synthesis, no HTML produced |
| Circuit-clustering chart render fails (step 1.5) | Step 1.5 (this Skill) | Alert-and-**continue** — reported to the user, but never blocks or delays step 2/3 |
| Any step 2-8 failure for one missing circuit | Step 2 loop, per circuit | Recorded and skipped; the loop **continues** to the next missing circuit (alert-and-continue, same departure `reporte-lote` documents, scoped to this loop only) |
| Vault-render failure (`usage_error`/`skipped_incomplete`/`execution_error`) for one circuit | Step 2 loop, vault-population sub-step | Alert-and-**continue** to the next missing circuit; that circuit's already-succeeded steps 2-8 report artifacts are NEVER rolled back |
| Fewer than 2 circuits sampled | Step 2.5 (this Skill) | Step 2.5 skipped outright; graph subsection omitted entirely from the HTML, no error |
| A sampled circuit has no vault note | Step 2.5 (this Skill) | That circuit excluded from the `/graphify query` input only; step 2.5 proceeds with the rest |
| Isolated vault-graph rebuild (step 2.5.2) or `/graphify query` fails outright or times out | Step 2.5 (this Skill) | Alert-and-**continue** to step 3 with no `--graph-patterns` path — deterministic sections still render, subsection shows "análisis de grafo no disponible en esta corrida" |
| `/graphify query` returns nothing meeting `soporte >= 2` | Step 2.5 (this Skill) | Empty `patterns` list written; subsection explicitly states no recurring pattern was found, never a silent omission |
| `graph_view_builder build` fails (sub-step 2.5.6) | Step 2.5 (this Skill) | Alert-and-**continue** to step 3 with no `--graph-view` path — list-only rendering if patterns succeeded, no figure; deterministic sections unaffected |
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
- `informe_gerencial_contract.py` stays deterministic and LLM-free — it never calls `graphify` or any
  LLM; step 2.5 above is the ONLY place this Skill's run sequence invokes the `/graphify`
  slash-command, and it lives entirely in this SKILL.md's own runbook, never inside the Python
  contract. `plotting.py` is not touched by the graph-patterns feature, nor by the graph-view feature —
  the new `_iframe_srcdoc` helper in `informe_gerencial_contract.py` is a small, deliberate 4-line
  duplicate, not an import from `plotting.py`'s own nested closure (accepted duplication, same
  established convention as the bullet above). `graph_view_builder.py` is the ONLY module anywhere in
  this feature that imports/calls `graphify.export.to_html` directly (a Python API call, not the
  `/graphify` slash-command) — `informe_gerencial_contract.py` only ever reads that module's already-
  written HTML file from disk.
- The isolated vault graph (`reports/vault/graphify-out/graph.json`) is rebuilt fresh every
  invocation and never merged with, read from, or written to the project-root `graphify-out/graph.json`
  produced by an ordinary whole-project `/graphify .` run — see "Resolved limitation" under
  "Cross-circuit graph patterns (step 2.5)" above for the incident that made this isolation
  non-negotiable.

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
- Standalone pre-batch clustering chart, invoked directly by its render verb in step 1.5 (distinct
  from the full-fleet scatter embedded in the final HTML above):
  [`.claude/skills/agrupamiento-circuitos/SKILL.md`](../agrupamiento-circuitos/SKILL.md) /
  [`src/chec_local_interpreter/circuit_clustering_contract.py`](../../../src/chec_local_interpreter/circuit_clustering_contract.py)
- Cross-circuit graph query, invoked ONLY in step 2.5 (the sole LLM-assisted step in this Skill's run
  sequence): [`.claude/skills/graphify/SKILL.md`](../graphify/SKILL.md)
- Vault-population sub-step (step 2), reused directly rather than via `report/SKILL.md`'s own step 9:
  [`src/chec_local_interpreter/vault_note_contract.py`](../../../src/chec_local_interpreter/vault_note_contract.py)
- Scoped graph-view builder, invoked ONLY in step 2.5.6 (the sole direct `graphify.export.to_html`
  caller in this feature): [`src/chec_local_interpreter/graph_view_builder.py`](../../../src/chec_local_interpreter/graph_view_builder.py)
- Binding invariants (shared with every agent role/orchestrator above):
  `.claude/agents/rules/invariants.md`
- Tests: `tests/test_informe_gerencial_contract.py` (sampling, group resolution, missing-run
  detection, content loading — including the vault-note/run-dir structured-fields bugfix,
  `load_graph_patterns` threshold/intersection/malformed-input handling, `resolve()`/
  `render_and_write()` status matrices, path-injection rejection, `synthesize`/`render_managerial_report`
  section assembly including the 3-state graph-patterns subsection, full-fleet-highlight behavior, CLI
  verbs including `--graph-patterns`/`--graph-view`), `tests/test_graph_view_builder.py` (seed/bridge
  sub-graph predicate, per-circuit community grouping for the embedded figure's "Communities" panel
  — one toggleable group per sampled circuit plus a shared bucket for off-circuit bridge nodes, never
  graphify's own topic-based clustering — oversize/malformed-input/never-raise behavior, CLI exit codes)
