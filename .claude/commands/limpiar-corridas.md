---
description: Limpia de forma segura los artefactos desechables de corridas del pipeline /report (dry-run + confirmacion explicita)
---

Follow this exact sequence when `/limpiar-corridas` is invoked. This deletes disposable `/report` pipeline run artifacts and is irreversible once confirmed — never skip a step or assume consent.

1. **Dry-run first.** From the repo root, run:
   ```
   PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.cleanup_runs
   ```
   Show the full summary output to the user verbatim (every category, item counts, sizes, and the grand total). Do not summarize or truncate it.

2. **Ask for explicit confirmation**, in the user's language. Make clear that:
   - This action is IRREVERSIBLE.
   - Which categories will be affected (list them from the dry-run output).
   Do not assume consent from context — wait for an explicit yes/confirmation message from the user before proceeding.

3. **If the user wants to narrow scope** (only some categories, or exclude some), re-run the dry-run with `--only NAME[,NAME...]` or `--skip NAME[,NAME...]` first, e.g.:
   ```
   PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.cleanup_runs --only runs,html
   ```
   Show the updated summary to the user and ask for confirmation again before proceeding. Repeat this step as many times as the user wants to adjust scope.

4. **Only after explicit confirmation**, run the confirmed deletion with the exact same `--only`/`--skip` filters (if any) used in the last dry-run the user approved:
   ```
   PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.cleanup_runs --confirm "BORRAR TODO" [--only NAME[,NAME...]] [--skip NAME[,NAME...]]
   ```
   Report the final deletion summary (files deleted, space freed, per-category breakdown) back to the user verbatim.

5. **Never pass `--confirm` speculatively.** Do not run the command with `--confirm "BORRAR TODO"` before the user has seen the dry-run output for the exact scope being deleted and has said yes in chat. If the user's confirmation is ambiguous, re-show the dry-run and ask again rather than guessing.
