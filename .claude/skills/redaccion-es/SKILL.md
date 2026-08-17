---
name: redaccion-es
description: "Trigger: /redaccion-es, revisar redaccion en espanol, tildes, ortografia, mayusculas, texto de figuras o interfaz. Corrige gramatica, tildes, mayusculas y signos de apertura; recorta verboseo, dialecto y redundancia hacia espanol tecnico."
license: Apache-2.0
metadata:
  author: chec-local-uiti-vano-interpreter
  version: "1.0"
  verificador: .claude/skills/redaccion-es/assets/revisar.py
---

## Activation Contract

Load when the user asks to review Spanish writing in this repo: code comments, docstrings,
notebook markdown, panel copy, figure titles, axis labels, tick labels, or button text.
Applies to Spanish only — English identifiers, keys, and API names are out of scope.

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
