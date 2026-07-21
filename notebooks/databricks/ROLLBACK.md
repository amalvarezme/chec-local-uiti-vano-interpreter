# Rollback — `databricks-integration` PoC

Manual, one-time PoC. Every artifact it created is independent of the local repo's runtime
(`report_pipeline.py`, LLM agent roles, vault/graphify, GitHub Pages) — reverting any or all of the
steps below never touches those. All commands use profile `andresmarino07@gmail.com`
(`-p andresmarino07@gmail.com`).

## Full rollback (both PR 1 and PR 2)

Order matters only in that the dashboard should be trashed before the tables it reads are dropped
(cosmetic — an orphaned dashboard just shows query errors, it does not block table drops).

1. **Dashboard (PR 2)**:
   ```bash
   databricks lakeview trash 01f1849e6bbd1be9a5188c08fb912a80 -p andresmarino07@gmail.com
   ```
2. **Tables (PR 1)** — via `databricks api post /api/2.0/sql/statements` or the SQL editor, warehouse
   `9ff827fa83282a1a`:
   ```sql
   DROP TABLE workspace.default.circuit_geo;
   DROP TABLE workspace.default.circuit_clustering;
   DROP TABLE workspace.default.indicadores_vano;
   ```
3. **Notebook + uploaded source mirror (PR 1)**:
   ```bash
   databricks workspace delete /Users/andresmarino07@gmail.com/databricks-integration/uiti_vano_tables -p andresmarino07@gmail.com
   databricks workspace delete -r /Users/andresmarino07@gmail.com/databricks-integration/chec_local_interpreter_src -p andresmarino07@gmail.com
   ```
4. **Repo commits**: `git revert` the PR 1 commits (`60c9d2c`, `9d791bc` — reverts the `AGENTS.md`
   scoping edit and deletes `notebooks/databricks/uiti_vano_tables.py`) and the PR 2 commit(s) that
   add `notebooks/databricks/circuit_explorer_dashboard.lvdash.json` and this file. Independent
   reverts — reverting PR 2 alone leaves the 3 tables intact and queryable; reverting PR 1 alone
   would orphan the dashboard's queries (drop the dashboard first in that case).

## Partial rollback (PR 2 only, keep the 3 tables)

Trash the dashboard (step 1 above) and revert only the PR 2 commit(s). The 3 Delta tables and the
notebook from PR 1 are untouched and remain independently queryable via any SQL client against
warehouse `9ff827fa83282a1a`.

## Zero repo/runtime impact

No file under `src/`, `report_pipeline.py`, the LLM agent roles, `reports/vault/`, `reports/interpretability/`,
or GitHub Pages publishing was modified by either PR. `AGENTS.md` (PR 1) is the only file outside
`notebooks/databricks/` touched by this change, and it is additive scoping text, not a behavior
change to any pipeline.
