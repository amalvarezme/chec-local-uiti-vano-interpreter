---
name: informe-gerencial
description: "Produce one cross-circuit managerial report synthesized across a risk band's worst circuits, with the full-fleet ranking bars highlighting the sampled set. Trigger: /informe-gerencial, managerial report, cross-circuit synthesis, executive report for a risk band."
license: Apache-2.0
metadata:
  author: chec-local-uiti-vano-interpreter
  version: "0.1.0"
  runtime: claude
  canonical_contract: src/chec_local_interpreter/informe_gerencial_contract.py
  invokes_skills:
    - .claude/skills/report/SKILL.md
    - .claude/skills/graphify/SKILL.md
---

## Overview

`/informe-gerencial` produces exactly ONE managerial-facing HTML report synthesized ACROSS the most
representative circuits of one criticality group (or the whole fleet, for `todos`), instead of one
report per circuit. It does not reimplement `/report`'s single-circuit pipeline, `/reporte-lote`'s
batch loop, or `ranking_circuitos`'s band computation. It owns exactly the pieces those
three do not: sampling a band down to its 12 WORST circuits (largest `vanos_criticos`, i.e. the head of the
ranking's own `posicion`) — or, for `todos`, down to 12 by BAND QUOTA (5 alto + 5 medio-alto + 2 medio), detecting which of those 12 are missing a prior `/report` run,
gating on a single explicit confirmation before auto-triggering `/report` for the missing ones (by
reference to [`report/SKILL.md`](../report/SKILL.md), never by copying its prose), **always**
rendering the standalone circuit-clustering chart for the confirmed window right after that same
checkpoint (step 1.5, reusing the shared circuit-clustering contract by reference, never a
second confirmation), loading each sampled circuit's narrative content, and assembling the
report (a deterministic band-wide preamble, executive summary, window concentration, aggregate risk,
recommended actions and a per-circuit annex) plus one embedded full-fleet ranking bar chart and one
radial causes/intervention-strategies graph (step 2.6, built from the agents' own run artifacts, no
`graphify` involved) into a single HTML page. `report/SKILL.md` is never edited and a standalone
`/report`/`/reporte-lote` invocation is completely unaffected by this Skill's existence.

Canonical contract (pure Python, no LLM call anywhere in this module):
[`informe_gerencial_contract.py`](../../../src/chec_local_interpreter/informe_gerencial_contract.py).

## Where the managerial report lands

`reports/informesgerenciales/` — its own root, not a subfolder of the circuit runs. It used
to live in `reports/reportescircuitos/html/informe-gerencial/`, hanging off the circuits'
HTML, which is exactly where nobody looks for it and where a cleanup of the circuit reports
took it along without being able to choose otherwise.

What it READS stays where the circuits write it: `reports/reportescircuitos/runs/` for the
runs it synthesises, `reports/reportescircuitos/html/` for their reports, and
`reports/vault/` for the notes. This report is a synthesis; it produces no run of its own.


## When to Use

Load this Skill when the user wants a single, synthesized, cross-circuit managerial view of a
risk band or the whole fleet — e.g. "informe gerencial de Riesgo Alto", "resumen ejecutivo del grupo
Medio-Alto", "/informe-gerencial todos". If the user wants one circuit's full report, use `/report`
directly. If the user wants every circuit's INDIVIDUAL report run in one batch (not a synthesized
cross-circuit view), use `/reporte-lote` instead.

## Argument contract

Invocation: `/informe-gerencial <grupo> [fecha_inicio fecha_fin]`.

- `grupo` — **required**. Must be one of `bajo|medio|medio-alto|alto|todos`; any other value is a
  usage error, rejected before any dataset access. These are the four RISK BANDS of the circuit
  ranking (`ranking_circuitos.NOMBRES_RANGO`), **not** `/reporte-lote`'s five K-Means tiers — see
  "Which grouping this Skill speaks" below. `/reporte-lote` shares this exact allowlist; the retired
  K-Means slugs (`muy-alta|alta|…|baja`) are a usage error in both, deliberately, because they would
  otherwise resolve to an empty band without saying the vocabulary changed.
- `fecha_inicio` / `fecha_fin` — **optional, as a PAIR**, same pair contract `/reporte-lote` uses:
  - Both omitted: resolve to the dataset-wide date range.
  - Both given: passed through unchanged.
  - Exactly one given is a usage error.

Examples:

| Invocation | Result |
|---|---|
| `/informe-gerencial alto` | Band `Riesgo Alto` (top 3% by critical vanos) over the full dataset-wide range |
| `/informe-gerencial medio-alto 2026-01-01 2026-02-01` | Band `Riesgo Medio-Alto` over that explicit window |
| `/informe-gerencial bajo 2026-01-01` | **Rejected** — usage error, `fecha_fin` missing |
| `/informe-gerencial alta` | **Rejected** — usage error, that is `/reporte-lote`'s K-Means vocabulary |
| `/informe-gerencial todos` | Full fleet via `ranking_circuitos`; preamble covers ALL circuits and vanos, then 12 sampled by band quota (5 alto + 5 medio-alto + 2 medio) |

## Which grouping this Skill speaks

The bands come from the **circuit ranking** — `src/chec_local_interpreter/ranking_circuitos.py`, the
verbatim Python port of the second dashboard of notebook 02 (`src/chec_tableros/agrupamiento.py`):
per circuit, the COUNT of its vanos in Medio-Alto + Alto, cut at P50/P75/P97 into `Riesgo Bajo`,
`Riesgo Medio`, `Riesgo Medio-Alto`, `Riesgo Alto`. That is the same calculation that paints the bar
chart, the same one `/report` cites through `context_builder`, and the same one whose band name goes
to the Circuitos sheet of the Excel export.

It used to come from `plotting.compute_circuit_criticality_groups` — K-Means over the circuit's event
count × UITI sum, five tiers including `Riesgo Muy Alto` and `Riesgo Medio-Bajo`. Both vocabularies
contain the string "Riesgo Alto" and it means DIFFERENT circuits: measured over the 208-circuit fleet,
16 circuits by K-Means, 7 by the ranking, only 3 in both. The managerial report was grouping by a
criterion its own embedded figure could not show. `context_builder` had already been migrated for
`/report`; this Skill was the last holdout.

`/reporte-lote` migrated with it: `batch_report_contract.GROUP_SLUGS` holds the single shared
definition and `informe_gerencial_contract` re-exports it, so the two commands cannot drift apart
again. Splitting them would mean splitting that allowlist, never copying it.

## Sampling to 12 (>12 circuits in the band)

When the resolved band has more than 12 circuits, exactly the 12 with the LARGEST `vanos_criticos`
are used — the head of the ranking's own `posicion` (1 = worst) — never all of them, never a random
subset. Bands with 12 or fewer circuits use all of them unfiltered, which is the normal case for
`Riesgo Alto` (7 circuits, the top 3% of the fleet).

**Known bias, state it when reading the report:** the 12 sit against the band's UPPER edge, so the
report describes the band's worst tail, not the band. The previous criterion (smallest
`centroid_distance`, the most TYPICAL circuit of its K-Means class) had the opposite bias and no
analogue here — the ranking has no circuit centroids. Owned entirely by
`informe_gerencial_contract.sample_representatives`; this Skill never re-derives or overrides it.

### `todos` samples by BAND QUOTA, not by fleet-wide top 12

`todos` does **not** take the 12 largest `vanos_criticos` of the fleet. It fills a per-band quota,
`informe_gerencial_contract.CUOTA_TODOS`:

| Band | Circuits |
|---|---|
| `Riesgo Alto` | 5 |
| `Riesgo Medio-Alto` | 5 |
| `Riesgo Medio` | 2 |
| `Riesgo Bajo` | 0 |

Within each band the pick is still the largest `vanos_criticos`, same tie-break. Twelve total, the
same cap a single band gets.

**Why the quota exists:** the fleet-wide top 12 came entirely from `Riesgo Alto` and
`Riesgo Medio-Alto` — measured, 7 + 5 — so a report titled "all circuits" never once looked at a
`Riesgo Medio` circuit, and could not say what distinguishes the band that is not critical yet from
the ones that are. The two worst bands weigh the same because that is where intervention happens;
`Riesgo Medio` enters with two so the report can draw that contrast. `Riesgo Bajo` is excluded: 101
circuits with no critical span.

**A band shorter than its quota contributes what it has and the sample stays short** — 10, not 12.
Backfilling from another band would silently change the composition the report declares, and the
reader has no way to notice. `_cuota_por_banda` never backfills.

## Single user checkpoint (missing-run confirmation gate)

This Skill has exactly **one** interactive checkpoint, and it fires only when needed:

- If every sampled circuit already has a prior `/report` run, **no gate is shown** — proceed straight
  from step 1 to step 3 (content loading + synthesis + render), same silent-continuation convention
  `/reporte-lote` uses once its own single checkpoint clears.
- If ANY sampled circuit has no prior run, state the missing **count** and the **list of missing
  circuit names** to the user **once**, and require explicit confirmation before auto-triggering
  `report/SKILL.md`'s Run-sequence steps 2-8 ONLY (the three agent dispatches included;
  step 9, the
  vault-note-plus-chained-`/graphify` projection, is deliberately excluded here — see step 2's own
  vault-population sub-step below) for those circuits only. If the user declines, **stop here** — do
  not trigger any missing pipeline and do not proceed to synthesis.

This mirrors the `awaiting_confirmation` → `confirm`/`confirm_and_trigger_missing` contract shape
`informe_gerencial_contract.resolve()` already returns, and the exact same single-checkpoint UX
convention `reporte-lote/SKILL.md` uses for its own gate — never a second confirmation later in the
run, never a per-circuit prompt.

## Preamble: "Panorama del grupo" (first section, always)

The report OPENS with a deterministic overview of the band, before any synthesis, built by
`perfil_de_banda` + `figura_preambulo` + `_preambulo_html`. It answers what the rest of the
report assumes: who is in the band, how many of the fleet's circuits that is, and what share
of the fleet's vanos — and of its CRITICAL vanos — they hold.

Its figure carries the same three readings as notebook 02's second dashboard
(`src/chec_tableros/agrupamiento.py`), deliberately, so a reader coming from the dashboard
recognizes the figure instead of translating it:

| Row | Panel | Answers |
|---|---|---|
| 1 | full-fleet ranking bars, band circuits outlined | where the band sits in the fleet |
| 2 left | vano counts per group, count outside + percentage inside | how the band's vanos split across the four vano groups |
| 2 right | violin of accumulated UITI per vano group (log axis) | how SEVERE each group is — what the count cannot say |

Two prose rules the section enforces, both learned from a measured run:

- The circuit denominator is the **fleet**, from `perfil["circuitos_flota"]`, never the
  group's own `circuit_count`. "7 circuits out of 7" says nothing; "7 out of 208" is the point.
- After the aggregate share, it names the single vano group where the band concentrates MOST,
  with its percentage. Measured on `alto`: the band holds 13.4% of the fleet's critical vanos
  overall but **22.8% of its `Alto` vanos** with only 10.5% of the vanos. The aggregate dilutes
  exactly the number that says where intervention pays.

### The preamble's universe is the GROUP, never the sample

`render_managerial_report` takes `circuitos_grupo` alongside `sampled`, and `perfil_de_banda` is
computed over the former. For a band of 12 or fewer the two coincide; for `todos` they differ by
208 vs 12, and computing the profile over the sample made "% of the fleet" a comparison of the
sample against itself. The `sampled` list is still what the ranking bars outline.

### `todos` switches the preamble's question (`_preambulo_flota_html`)

When `group["bandas"]` is present — set only for `todos` — the preamble takes a separate branch,
because the band-mode prose degenerates:

| Band mode asks | Why it fails for `todos` |
|---|---|
| who composes the group | 208 circuit codes in a row, which nobody reads |
| what share of the fleet it holds | 100% by construction — the fleet compared to itself |
| how disproportionate its critical share is | 1.0× by construction, so the paragraph is skipped |

Fleet mode instead states the fleet's **composition by band** (7 / 40 / 60 / 101), what share of
its OWN vanos are critical, and — required, not optional — that the sections after the preamble
cover only the 12 sampled circuits and how those 12 were chosen. Without that last sentence the
reader carries the fleet's counts into a synthesis built from twelve circuits.

`perfil_de_banda` drops to the VANO level using `ranking_circuitos`'s own
`geometria_vanos`/`grupo_de_vanos`, so a vano lands in the same group here, in the dashboard,
and in the per-circuit report. It carries the full per-vano UITI list, not a summary: the
violin needs the DISTRIBUTION — a mean cannot tell a band of many mid vanos from one with a
few extremes, which is the difference that decides where to intervene. An empty or
column-less frame returns a zeroed profile; it never raises.

## Full-fleet ranking bars (non-negotiable)

The report's ranking figure ALWAYS shows the FULL fleet — all 208 circuits and all 4 risk bands,
unfiltered by the requested `grupo`. Only the band's circuits get a thick bar border; every other
circuit stays visible as a normal bar, in the color of its own band. Nothing is ever hidden,
regardless of `grupo`.

It is drawn exactly ONCE, inside the `Panorama del grupo` preamble (see above). There used to be a
second copy at the bottom of the report under "Mapa de agrupamiento"; it was the same 208-bar figure
again, arriving without the prose that explains it, and it cost 0.13 MB to say nothing new.

This used to be `plot_interactive_circuit_clustering`'s K-Means scatter. It was swapped when the
grouping moved to the ranking: the scatter placed a circuit by SIZE (events × accumulated UITI) and
its five classes were not the four bands the report was grouping by, so the reader saw a figure that
could not explain the group the text was talking about. `plot_ranking_circuitos` now accepts either a
single circuit name (`/report`, unchanged) or a list (this Skill); with a list it borders every one
of them and annotates none — twelve arrows over 208 bars of 2.8 px cover exactly what they point at.
Built once, inside `figura_preambulo`; this Skill never builds or filters it.

## Allowed tools

- **Bash** — restricted to invoking the shared contract's own verbs
  (`chec_local_interpreter.informe_gerencial_contract resolve` / `render`) for this Skill's own steps
  1 and 3, plus whatever Bash surface `report/SKILL.md` itself uses while its steps 2-8 (ONLY — never
  its step 9) run for a missing circuit in step 2, plus this Skill's own two additional direct CLI
  verbs: `python -m chec_local_interpreter.vault_note_contract render <circuito>` (step 2's
  vault-population sub-step) and `python -m chec_local_interpreter.intervention_graph build ...`
  (step 2.6). This Skill never gets a general shell — same structural guarantee as `report` and
  `reporte-lote` (`.claude/agents/rules/invariants.md`, Rule 1). No subprocess/shell string-building
  happens in Python anywhere in this flow: `report/SKILL.md`'s steps are invoked by-reference through
  the Skill tool, never assembled into a shell command from user-controlled text.
- **Skill** — to invoke `report/SKILL.md`'s Run-sequence steps 2-8 ONLY, per missing circuit, in step
  2's loop. `report/SKILL.md` governs its own further Bash/Skill/Read restrictions independently for
  those steps; this Skill does not bypass them.

  **`graphify` is NOT invoked anywhere in this run sequence.** It used to be, in a step 2.5 that
  built an isolated vault-only graph and mined cross-circuit themes from it for a
  "Patrones cross-circuito (grafo)" section. That section was retired on 2026-08-18, which left the
  whole step without a consumer, so the step went with it. Step 2's vault-population sub-step calls
  `vault_note_contract.render(circuito)` directly — the same vault PROJECTION `report/SKILL.md`'s own
  step 9 performs — but deliberately WITHOUT step 9's chained `/graphify` call, so the vault notes
  are still written (they remain a product in their own right) and nothing in this flow reads a
  graph. `intervention_graph.py` never imports or calls `graphify` either: it hand-authors its own
  HTML from the agents' run artifacts.
- **Read** — to inspect the contract's JSON output and the final rendered HTML path.
- **Write** — to persist the `intervention_graph`-produced radial HTML (plus its sibling
  `.resumen.json`) to
  `reports/reportescircuitos/runs/.informe-gerencial/grafo-intervencion.<grupo>.<win>.html` before
  step 3 reads it back.
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
      `ranking_circuitos` directly (independent of, and never calling,
      `batch_report_contract.preflight_batch`'s own `todos` bypass), samples down to the 12 worst
      circuits of the band when it exceeds that threshold (or, for `todos`, by the band quota), and checks each sampled circuit
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
      when nothing is missing, before step 3) — run the shared circuit-clustering
      contract directly by its render verb:
      `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.circuit_clustering_contract render <fecha_inicio> <fecha_fin> --runtime claude`.
      Since 2026-08-18 that contract renders the RANKING bars, not the K-Means scatter — it
      was the last place in this flow speaking the retired five-tier vocabulary, showing
      classes (`Riesgo Muy Alto`, `Riesgo Medio-Bajo`) that neither this Skill nor
      `/reporte-lote` can name, on a different axis (circuit SIZE, events × UITI, rather than
      critical vanos). It renders with no highlighted circuit: this artifact is the fleet's
      picture BEFORE a band is chosen.
      Reuse this Skill's own already-resolved/confirmed `fecha_inicio`/`fecha_fin` from 1.2-1.4 — never
      re-run that contract's own preflight or add a second confirmation prompt, since that would
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
   that graphify refresh is gone entirely — see the Allowed-tools note). This projects
   `reports/vault/<circuito>.md`, which stays a product in its own right even though no step of this
   flow reads it back. A non-zero exit (`usage_error`,
   `skipped_incomplete`, or `execution_error`) is **alert-and-continue**: record it and proceed to the
   next missing circuit — it NEVER rolls back this circuit's already-succeeded steps 2-8 report
   artifacts (see the Error handling summary below).

2.6. **Build the radial causes/intervention-strategies figure (always attempted).** Depends on
   nothing but the run artifacts: no `graphify`, no `graph.json`, no vault note. It reads the
   concepts the agents already wrote into each sampled circuit's own run directory:
   `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.intervention_graph build --sampled <sampled circuits>
   --output
   reports/reportescircuitos/runs/.informe-gerencial/grafo-intervencion.<grupo>.<fecha_inicio>_<fecha_fin>.html`.

   It writes TWO files: the figure at `--output`, and its sibling
   `<output>.resumen.json`, which step 3 reads back automatically to NAME the causes and strategies
   in text next to the figure. Pass only the figure path to step 3, as `--graph-intervencion <path>`;
   the contract derives the sibling itself.

   Report to the user the `causa_count`/`estrategia_count` from the printed outcome JSON, plus any
   `circuitos_sin_corrida` — that list is the honest caveat for the figure (those circuits contributed
   nothing to it). On any failure (`execution_error`, or `skipped_empty` from fewer than 2 sampled
   circuits or no concept shared by 2 of them), alert and **continue** straight to step 3 with no
   `--graph-intervencion` path; the section is then omitted entirely rather than rendered as a
   placeholder. See "Radial causes/strategies graph (step 2.6)" below for what it draws and why.

3. **Load content, synthesize, and render the single HTML report.** Once step 2.6 has either
   produced its path or been skipped/failed (it never blocks on it), run the shared contract's
   `render` verb:
   `PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.informe_gerencial_contract render <grupo> [fecha_inicio fecha_fin] --runtime claude --provider "Claude Code" --model <model> [--graph-intervencion <path from step 2.6>]`.
   This re-resolves the SAME deterministic group/window/sampling as step 1 (K-Means is
   `random_state=42`-seeded, so the sampled 12 are reproducible), then for each sampled circuit calls
   `load_circuit_content` (vault-note preferred, raw-JSON fallback per Content sourcing below),
   loads `--graph-intervencion` via `load_graph_view` (missing/omitted path -> `None`, unreadable ->
   `None`, readable -> raw HTML text, never raising) plus its sibling `.resumen.json` via
   `load_intervention_summary`, assembles the synthesis via `synthesize(...)`, and renders the page
   via `render_managerial_report(...)`. Sections, in order: **Panorama del grupo** (the deterministic
   preamble, which also carries the only full-fleet ranking figure), **Resumen ejecutivo del grupo**,
   **Concentración por ventana**, **Causas y estrategias de intervención** (step 2.6's radial figure,
   labeled "Síntesis de los agentes"), **Riesgo agregado**, **Acciones recomendadas**, **Anexo por
   circuito**. Then it persists the whole report to disk. Report the returned `output_html` path to the user. This step runs exactly
   once per invocation and never asks the user anything further.

## Radial causes/strategies graph (step 2.6)

Three concentric rings, read from the outside in: **circuits** share **causes**, and each cause leads
to the **intervention strategies** the alignment agent proposed
(`src/chec_local_interpreter/intervention_graph.py`).

| Ring | Node | Where it comes from |
|---|---|---|
| Outer | one sampled circuit | the sample itself |
| Middle | a shared causal theme | `historical.out.json`'s `cause_hypothesis_note`, bucketed by the shared `informe_gerencial_contract.cause_themes` |
| Inner | `<intervention family> · <VARIABLE>` | `expert-alignment.out.json`'s `variables_a_priorizar`: the family from the verb in `tipo_de_validacion_sugerida`, the variable verbatim |

Only concepts present in **2 or more** sampled circuits get a node. There is deliberately no
circuit-to-strategy edge — the figure's whole point is that an intervention is reached THROUGH a
cause — and a strategy left with no cause edge is dropped rather than drawn floating. Clicking any
node shows the agents' own sentences, verbatim, per circuit.

**Why nodes are keyed on the canonical fields and not on the agents' prose.** Measured over the 37
completed runs on disk: 205 of 206 `coincidencias`/`diferencias` themes are distinct strings, and 35
of the 36 `tipo_de_validacion_sugerida` texts written for `CNT_TRF` are distinct. Grouping on those
strings draws one node per circuit and shows no cross-circuit relation at all. What genuinely recurs
is the canonical part — the variable code (`CNT_TRF` in 36 circuits, `CNT_VN` in 33), the priority,
the causal theme. So the free text is preserved as evidence, never as an identity.

**This step never touched `graphify`.** That independence is why it survived when step 2.5 and its
section were retired: the graph
rebuild there has corrupted itself twice in production (see "Second resolved limitation" below), and
under the previous dual-graph toggle a failed rebuild also took down the radial figure, which never
needed it. The two sections now degrade independently.

## Content sourcing

For each sampled circuit, `load_circuit_content` prefers `reports/vault/{circuito}.md` as the
narrative source; if absent, it falls back to the raw `expert-alignment.out.json` run artifact under
`reports/reportescircuitos/runs/{circuito}/`. If neither exists (e.g. step 2's auto-trigger failed for
that circuit), the circuit still appears in the report's Anexo section, marked as having no content
available — the report is never blocked by one circuit's missing content. When a vault note is used
AND a prior run directory is resolvable, `cause_hypothesis_note`/`variable_groups_used`/
`variables_a_priorizar` are sourced from that run's own JSON artifacts (same completeness as the
raw-JSON path, via the shared `_structured_fields` helper); when no run directory is resolvable, only
`cause_hypothesis_note` is recovered, parsed directly from the note's own `### Hipótesis de causa`
section — `variable_groups_used`/`variables_a_priorizar` are never fabricated from the note text.

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
| `intervention_graph build` fails, or no concept is shared by 2+ sampled circuits | Step 2.6 (this Skill) | Alert-and-**continue** to step 3 with no `--graph-intervencion` path — the section is omitted entirely; every other section is unaffected |
| Some sampled circuits have no completed run | Step 2.6 (this Skill) | They contribute nothing to the figure and are listed in `circuitos_sin_corrida`; report that list to the user as the figure's caveat |
| A sampled circuit still has no content at render time | Step 3 (`load_circuit_content` returns `None`) | Annex entry marked "sin contenido disponible"; the report still renders for every other circuit |

None of the rows above, nor any mid-run condition, turns into a second question back to the user —
the single checkpoint is step 1.4 only.

## Non-goals (explicit — do not touch)

- `plotting.run_kmeans`'s signature and return value are never modified by this Skill or its
  contract.
- `batch_report_contract.preflight_batch`'s own `todos` bypass is never called or modified; this
  Skill's `todos` path always goes through `ranking_circuitos` directly via
  `resolve_group_dataframe`. `batch_report_contract` is no longer imported by this contract at all —
  the two speak different group vocabularies on purpose.
- `/reporte-lote` and `/report` (direct invocation) behavior is unchanged by this Skill's existence —
  their own SKILL.md files are never edited here.
- No shared HTML-shell helper is extracted from `plotting.render_llm_analysis` in this change; the
  managerial report's HTML shell is its own small, self-contained implementation in
  `render_managerial_report` (accepted duplication, logged as follow-up tech debt).
- `informe_gerencial_contract.py` stays deterministic and LLM-free — it never calls `graphify` or any
  LLM, and since the cross-circuit graph section was retired NOTHING in this flow does. It reuses
  `plotting.plot_ranking_circuitos` for the preamble's fleet bars and `glosario_variables.
  nombre_con_codigo` to name variables, both AS-IS.
- Every variable that reaches the page is written `Nombre natural (CODIGO)` via
  `glosario_variables.nombre_con_codigo` — the same helper `/report`, the vault note and the agent
  context already use. The code is never dropped: it is what has to be looked up in the dataset and
  in the simulator. `intervention_graph.etiqueta_de_estrategia` applies it to the strategy nodes, but
  only to what is DRAWN — the concept string stays the raw `<family> · <CODE>` because it is the
  identity that groups strategies across circuits and the key that travels to the `.resumen.json`.

## Naming rule: `Nombre natural (CODIGO)` in prose and tables, bare code in figures

Every dataset column that reaches a READER is written `Nombre natural (CODIGO)` — e.g.
`Densidad de descargas a tierra (DDT)`. The code is never dropped: it is what has to be
looked up in the dataset, in the simulator and in the variable-selection file. The name is
never dropped either: `DDT` means nothing to anyone outside the team, and one measured
report printed `NR_T` twenty-four times without once saying it is vegetation risk.

**Figures are the deliberate exception.** In a bar, a violin or a graph node the full name
does not fit and the axis already says what is being shown, so the bare code stays.

Three layers enforce it, and they are not interchangeable:

| Layer | What it does |
|---|---|
| `glosario_variables.nombre_con_codigo(codigo)` | one code -> `Nombre natural (CODIGO)`; returns the code unchanged when it is not in the glossary, so an unknown column never renders as `X (X)` |
| `glosario_variables.nombrar_en_prosa(texto)` | names each code the FIRST time it appears in a free-text string, leaves later mentions bare |
| `glosario_variables.nombrar_prosa_en_datos(data)` | the pass applied to a whole agent response at RENDER time |

Four properties of the prose pass that exist because each one was a real defect:

- **One pass over the ORIGINAL text.** Replacing code by code, each over the previous
  result, made the pass find the names it had just inserted: `UITI_VANO` expanded to
  `UITI atribuido al vano (UITI_VANO)` and the next round expanded that `UITI` again.
- **Case-sensitive.** `TIPO` and `CONDUCTOR` are codes; `tipo` and `conductor` are ordinary
  Spanish. A case-insensitive rule fills the report with noise.
- **Whole token only.** `DDT_EXTRA` is not `DDT`. Alternation runs longest-first so
  `CNT_VN_SW` wins over `CNT_VN`.
- **Identity keys are excluded** (`glosario_variables.CLAVES_DE_IDENTIDAD`): `variable`,
  `data_ref`, `concepto`, `variable_groups_used` and the run paths. `variable` is the key
  `intervention_graph` groups strategies on and the one that travels to the
  `.resumen.json`; expanding it breaks the grouping AND duplicates the name, because the
  table already passes it through the glossary when painting it.

**It runs at RENDER, never at save.** The `.out.json` is the artifact the agent's own
`validate` accepted; rewriting it would separate the file from its validation. A report can
therefore be re-rendered from existing runs to pick this up — no agent re-run needed.

**Group names are a separate map.** `Proteccion` and `Topologia` are schema enum
identifiers and stay unaccented in `variable_groups_used`; when DISPLAYED they go through
`domain_context.NOMBRE_LEGIBLE_GRUPO` (`Protección`, `Topología`). The report printed
`Modo Topologia` until that map was wired in.

## Related artifacts

- Cross-circuit synthesis contract (L1, pure Python, no LLM call anywhere in this module):
  [`src/chec_local_interpreter/informe_gerencial_contract.py`](../../../src/chec_local_interpreter/informe_gerencial_contract.py)
- Per-circuit orchestrator, invoked by reference for missing circuits in step 2:
  [`.claude/skills/report/SKILL.md`](../report/SKILL.md) /
  [`src/chec_local_interpreter/report_pipeline.py`](../../../src/chec_local_interpreter/report_pipeline.py)
- Structurally closest sibling Skill (batch resolution + single-checkpoint gate, alert-and-continue
  loop convention): [`.claude/skills/reporte-lote/SKILL.md`](../reporte-lote/SKILL.md)
- Shared risk-band computation reused directly (never through `preflight_batch`'s `todos` bypass):
  [`src/chec_local_interpreter/ranking_circuitos.py`](../../../src/chec_local_interpreter/ranking_circuitos.py),
  the Python port of `src/chec_tableros/agrupamiento.py`'s second dashboard
- Shared full-fleet ranking bars, reused AS-IS with a list of highlighted circuits:
  `plotting.plot_ranking_circuitos` (the same figure `/report` opens with)
- Standalone pre-batch clustering chart, invoked directly by its render verb in step 1.5 (distinct
  from the full-fleet scatter embedded in the final HTML above; it had its own
  `/agrupamiento-circuitos` Skill until 2026-08-17, and the contract module outlived it because
  this Skill always called the module, never the Skill):
  [`src/chec_local_interpreter/circuit_clustering_contract.py`](../../../src/chec_local_interpreter/circuit_clustering_contract.py)

- Vault-population sub-step (step 2), reused directly rather than via `report/SKILL.md`'s own step 9:
  [`src/chec_local_interpreter/vault_note_contract.py`](../../../src/chec_local_interpreter/vault_note_contract.py)
- `src/chec_local_interpreter/graph_view_builder.py` is NO LONGER invoked by this flow: it existed
  only for the retired step 2.5.6. The module and its tests are left in place rather than deleted,
  but nothing calls them — treat it as dead code pending a decision.
- Radial causes/strategies builder, invoked ONLY in step 2.6 (reads the agents' run artifacts
  directly; hand-authors its own fixed-position vis-network HTML, never imports/calls `graphify`):
  [`src/chec_local_interpreter/intervention_graph.py`](../../../src/chec_local_interpreter/intervention_graph.py)
- Binding invariants (shared with every agent role/orchestrator above):
  `.claude/agents/rules/invariants.md`
- Tests: `tests/test_informe_gerencial_contract.py` (sampling, group resolution, missing-run
  detection, content loading — including the vault-note/run-dir structured-fields bugfix,
  `resolve()`/
  `render_and_write()` status matrices, path-injection rejection, `synthesize`/`render_managerial_report`
  section assembly including the independent intervention/community graph sections and their degradation states, full-fleet-highlight
  behavior, the `Panorama del grupo` preamble, the retired sections staying retired, CLI verbs
  including `--graph-intervencion`),
  `tests/test_graph_view_builder.py` (seed/bridge sub-graph predicate, per-circuit community grouping
  for the embedded figure's "Communities" panel — one toggleable group per sampled circuit plus a
  shared bucket for off-circuit bridge nodes, never graphify's own topic-based clustering —
  oversize/malformed-input/never-raise behavior, CLI exit codes),
  `tests/test_intervention_graph.py` (intervention-family classification, accent-insensitive cause
  bucketing, min-support filtering, verbatim evidence, three-ring layout, no circuit-to-strategy edge,
  no orphan strategy, byte-identical repeat builds, `</script>`-in-evidence escaping, never-raise
  degrade behavior, `build` CLI exit codes)
