---
name: redaccion-es
description: "Trigger: /redaccion-es, revisar redaccion, tildes, ortografia, mayusculas, texto de figuras, prosa de informes generados. Revision EXHAUSTIVA y obligatoria de tildes; corrige mayusculas y signos, recorta verboseo hacia espanol tecnico."
license: Apache-2.0
metadata:
  author: chec-local-uiti-vano-interpreter
  version: "1.0"
  verificador: .claude/skills/redaccion-es/assets/revisar.py
---

## Activation Contract

Load when the user asks to review Spanish writing anywhere in this project. Two surfaces,
and the second is the one that kept getting missed:

1. **Repo source** — code comments, docstrings, notebook markdown, panel copy, figure
   titles, axis labels, tick labels, button text.
2. **Generated prose** — the agents' `*.out.json` under `reports/reportescircuitos/runs/`,
   the vault notes under `reports/vault/`, and the rendered `.html` of the per-circuit and
   managerial reports. This is prose an agent wrote, not a human, and it reaches the reader
   exactly as written.

Applies to Spanish only — English identifiers, keys, and API names are out of scope.

**Measured, so nobody has to take it on faith.** One managerial report for the `alto` band
shipped with **43 occurrences of unaccented prose across 14 distinct words** —
`vegetacion` 8 times, `hipotesis` 8, `validacion` 6, `proteccion` 5 — and nothing failed.
Two causes, both now fixed:

- The checker's word list did not CONTAIN those words. It had 153 entries and not one of
  `vegetacion`, `hipotesis`, `proteccion`, `atribucion`, `asociacion`, `topologico`. It
  could not see them however often it ran. The list now lives in
  `src/chec_local_interpreter/ortografia.py` (207 entries) and this checker imports it,
  so there is one list, not two.
- The agents' `validate` did not look at accents. An agent said so in writing during a real
  run: *"el validador no revisa ortografía ni acentos: la primera versión pasó con
  'Diagnóstico historico'"*. It now does — see the Mandatory review below.

## Mandatory exhaustive review (non-negotiable)

Accent and spelling review is **exhaustive and obligatory**, never a spot check and never
skipped because the text "looks fine". Concretely:

- Run the checker over **every** file you touch and over the generated artifacts, not a
  sample. A partial pass reports as a pass, which is how 43 defects shipped.
- The guard is a **mechanism, not a recommendation**: `agent_tools.{historical,inference,
  expert_alignment}.validate` runs `ortografia.errores_de_tilde` as its third stage, after
  schema and provenance. A response with unaccented prose exits non-zero and the agent must
  rewrite it. Do not weaken, monkeypatch away, or bypass that stage to make a run pass.
- When you add domain vocabulary that must carry an accent, add it to
  `SIEMPRE_CON_TILDE` in `src/chec_local_interpreter/ortografia.py`. A word that is not in
  the list is invisible to every consumer at once.
- Ambiguous spellings (`periodo`/`período`, `calculo`/`cálculo`, `critica`/`crítica`,
  `area`/`área`) carry `None` and are deliberately NOT auto-corrected. Report them; do not
  decide them — the two forms mean different things.
- **CODES never take accents.** `DURACION`, `PROMEDIO_KWH_TRF`, `COD_CAUSA` are dataset
  column names. The rule is mechanical — ALL-CAPS, or containing `_` or digits, is a code —
  so it needs no hand-maintained exception list.

## Hard Rules

1. Run [`assets/revisar.py`](assets/revisar.py) FIRST. It reports the mechanical defects
   deterministically; never eyeball what a check can decide.
2. Never change meaning, numbers, units, variable names, or dictionary keys. A label that
   feeds a lookup is code, not prose.
3. Never touch a Spanish string that is compared, parsed, or asserted elsewhere. Grep the
   literal before editing it.
4. Preserve the author's voice in comments. Fix defects; do not rewrite explanations that
   are already correct.
5. Every `¿` and `¡` needs its closing pair, and every closing needs its opening.
6. Sentence case in titles and labels — never Title Case, which is an English convention.
7. Neutral technical Spanish: no regionalisms, no `vos`, no colloquialisms.
8. Report each change with its file, its reason class, and the before/after.

## Decision Gates

| Finding | Action |
|---------|--------|
| Missing accent, spelling, agreement, unpaired `¿`/`¡` | Fix |
| Title Case, stray capital mid-sentence | Fix to sentence case |
| Redundant pair (`subir arriba`), filler (`de manera que`) | Cut |
| Regionalism, colloquialism, dialect | Replace with neutral term |
| Correct but long | Leave unless it exceeds a measured width limit |
| Ambiguous meaning, domain term you cannot verify | Report, do not change |
| String used as a key, compared, or asserted | Report, do not change |

## Execution Steps

1. `python3 .claude/skills/redaccion-es/assets/revisar.py <rutas...>` and read the report.
   It reads `.py`, `.md`, `.txt`, `.ipynb`, and — for generated prose — `.json` and `.html`.
   For a report run, point it at the run directory AND the rendered HTML, not just the source.
2. Read [`references/reglas-es.md`](references/reglas-es.md) for the accent, capitalization,
   and concision rules the checker cannot decide.
3. For each candidate string, grep the literal repo-wide before editing.
4. Apply fixes file by file. Widths of figure labels change: re-measure any label that grew.
5. Re-run the checker and the test suite.

## Output Contract

Return a table: file, line, reason class (`tilde`, `ortografia`, `mayusculas`, `signos`,
`verboseo`, `dialecto`, `redundancia`), before, after. List separately what was reported
but NOT changed, with the rule that blocked it.

## References

- [`references/reglas-es.md`](references/reglas-es.md) — accent, capitalization, and concision rules.
- [`assets/revisar.py`](assets/revisar.py) — deterministic checker.
