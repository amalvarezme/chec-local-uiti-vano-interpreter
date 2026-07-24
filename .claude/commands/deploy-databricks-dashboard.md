---
description: Regenera el dashboard AI/BI "Explorador de circuito UITI_VANO" completo en un workspace de Databricks (tablas base + vistas + dashboard Lakeview), preguntando solo el nombre del dashboard y la URL del workspace destino.
---

Follow this exact sequence when `/deploy-databricks-dashboard` is invoked. It builds a working copy of the dashboard defined in `notebooks/databricks/circuit_explorer_dashboard.lvdash.json` — same datasets, same widgets, same maps — in a target Databricks workspace. This touches shared workspace state (creates tables/views, runs a job, publishes a dashboard), so confirm with the user before any step that spends compute or creates something visible to others.

## 0. Ask the user for the two required inputs

Ask, one at a time, and wait for each answer:
1. The display name for the new dashboard.
2. The Databricks workspace URL (e.g. `https://dbc-xxxxxxxx-xxxx.cloud.databricks.com`).

Do not ask about anything else up front (warehouse, catalog, etc.) — resolve those automatically in the steps below, and only fall back to asking the user if a step below explicitly says to.

## 1. Resolve a CLI profile for that workspace

Run:
```
databricks auth profiles
```
Normalize the given URL (strip trailing slash) and match it against the `Host` column.

- **Match found** → use that profile name (`-p <profile>`) for every command below.
- **No match** → tell the user no CLI profile is configured for that host, and ask them to run this themselves via the `!` prefix (interactive OAuth, cannot be run for them):
  ```
  databricks auth login --host <workspace-url>
  ```
  Then re-run `databricks auth profiles` to pick up the new profile before continuing.

## 2. Resolve a SQL warehouse

Run:
```
databricks warehouses list -p <profile>
```
Pick the first warehouse in `RUNNING` state. If none is running, pick the first available warehouse regardless of state (it will auto-start on first query). If the list is empty, stop and tell the user to create a SQL warehouse in that workspace first (Databricks UI or `databricks warehouses create`) — do not create one automatically, since it has ongoing cost implications the user should choose.

Call the resolved id `<warehouse_id>` for the rest of this command.

## 3. Check which prerequisite data objects already exist

Run against `<warehouse_id>` via the SQL Statement Execution API:
```
databricks api post /api/2.0/sql/statements -p <profile> --json '{
  "warehouse_id": "<warehouse_id>",
  "statement": "SHOW TABLES IN workspace.default",
  "wait_timeout": "30s"
}'
```
Check for these six objects in the result:
- `indicadores_vano` (base table — reproducible, see step 4)
- `indicadores_vano_v_3` (wide weather-enriched table — **external prerequisite, NOT reproducible from this repo**; it backs the geo maps' vano/transformer/switch geometry and has no known upstream ETL committed here)
- `circuit_clustering` (reproducible, see step 4)
- `circuit_geo` (reproducible, see step 4 — currently unused by the dashboard's own widgets but built by the same notebook, keep parity)
- `circuit_map_lines_equipment` (view, reproducible via `notebooks/databricks/circuit_map_lines_equipment_view.sql`, depends on `indicadores_vano_v_3`)
- `circuit_daily_evolution` (view, reproducible via `notebooks/databricks/circuit_daily_evolution_view.sql`, depends on `indicadores_vano`)

**If `indicadores_vano_v_3` is missing**, stop here. Explain to the user that this table is an external data-engineering prerequisite outside this repo's scope (no ETL for it exists in the repo) and must be provisioned in the target workspace before the dashboard's geo maps can work. Offer to continue building everything else (clustering/daily-evolution widgets will work; maps will show query errors) only if the user explicitly agrees to proceed without maps.

**If `circuit_clustering` already exists**, do not skip it silently — its `criticidad` values can go stale relative to the repo's current label scheme even though the table itself is present (this happened once: an earlier deploy's uploaded `chec_local_interpreter` source went stale relative to a later `plotting.py` rename, so the notebook kept computing the old label set even on a "verbatim" re-run). Check the live label set against the repo's current source of truth before trusting the table:
```
databricks api post /api/2.0/sql/statements -p <profile> --json '{
  "warehouse_id": "<warehouse_id>",
  "statement": "SELECT DISTINCT criticidad FROM workspace.default.circuit_clustering",
  "wait_timeout": "30s"
}'
```
Compare the returned set against `CRITICALITY_GROUP_LABELS` in `src/chec_local_interpreter/plotting.py` (read the file, don't guess). If they differ, tell the user the deployed table is stale and offer to rebuild it: redo step 4's sub-steps 2–5 (refresh the uploaded source + notebook, then re-run the job) — the CSV/shapefile-existence check in sub-step 1 and the view-creation sub-step 6 can be skipped since only `circuit_clustering` needs rebuilding.

## 4. Build the reproducible base tables (only the missing ones)

Only do this for tables/views actually missing from step 3.

1. Check the source data exists in the target workspace's Volume:
   ```
   databricks fs ls dbfs:/Volumes/workspace/default/chec-simulador/data -p <profile>
   ```
   Needs `Indicadores_vano_v3.csv` and `GEO/MVLINSEC.shp`. If missing, ask the user whether to upload from the local repo's `data/` directory (Git-LFS tracked) via `databricks fs cp`, or whether the target workspace already mirrors this data under a different path — do not guess a path.

2. Get the profile's own user identity (workspace file/notebook paths are per-user):
   ```
   databricks current-user me -p <profile>
   ```
   Use the returned `userName` in place of `andresmarino07@gmail.com` below.

3. Upload the real repo source files as workspace files (never reimplement `compute_circuit_criticality_groups` — import it verbatim, same pattern as the existing PoC). `import-dir` has no `--format` flag — pass `--overwrite` so a re-run always refreshes a stale copy:
   ```
   databricks workspace import-dir src/chec_local_interpreter /Workspace/Users/<userName>/databricks-integration/chec_local_interpreter_src/chec_local_interpreter --overwrite -p <profile>
   ```
   (If `import-dir` rejects non-notebook files, fall back to individual `databricks workspace import <target_path> --file <local_file> --language PYTHON --format RAW --overwrite -p <profile>` calls for `__init__.py`, `config.py`, `event_counts.py`, `plotting.py`.)

   `import-dir` also has no exclude mechanism — if the local `src/chec_local_interpreter` tree has any `__pycache__/*.pyc` from local runs, they get uploaded too (confirmed empirically: a run against a real workspace uploaded 100+ stale `.pyc` files this way). Clean them up afterward — do not leave them in the Workspace:
   ```
   databricks workspace delete --recursive /Workspace/Users/<userName>/databricks-integration/chec_local_interpreter_src/chec_local_interpreter/__pycache__ -p <profile>
   ```
   (repeat for any nested `__pycache__` subfolder the local tree has — check with `find src/chec_local_interpreter -type d -name __pycache__` first).

4. Create the parent Workspace folder before importing single files into it — `workspace import` does NOT auto-create parent directories (confirmed empirically: on a workspace where `.../databricks-integration` didn't exist yet, this failed with "The parent folder ... does not exist"):
   ```
   databricks workspace mkdirs /Workspace/Users/<userName>/databricks-integration -p <profile>
   ```
   Then upload the notebook itself. `workspace import` takes exactly one positional arg (the target path) — the source file goes in `--file`, not as a second positional arg:
   ```
   databricks workspace import /Workspace/Users/<userName>/databricks-integration/uiti_vano_tables --file notebooks/databricks/uiti_vano_tables.py --language PYTHON --format SOURCE --overwrite -p <profile>
   ```
   If `<userName>` differs from `andresmarino07@gmail.com`, the notebook's `CHEC_SRC_DIR` constant hardcodes the old path — edit the uploaded copy's `CHEC_SRC_DIR` (or the local file before upload) to match the new user path.

5. Run it headless (serverless, one-time job — confirm with the user before running, it provisions compute):
   ```
   databricks jobs submit --json '{
     "run_name": "uiti_vano_tables-deploy",
     "tasks": [{
       "task_key": "build_tables",
       "notebook_task": {"notebook_path": "/Workspace/Users/<userName>/databricks-integration/uiti_vano_tables"}
     }]
   }' -p <profile>
   ```
   Poll `databricks jobs get-run <run_id> -p <profile>` until terminal state; if it fails, surface the notebook's error output to the user rather than retrying blindly.

6. Create the two views (only the ones missing / only if their base table now exists):
   ```
   databricks api post /api/2.0/sql/statements -p <profile> --json "{\"warehouse_id\": \"<warehouse_id>\", \"statement\": $(python3 -c "import json;print(json.dumps(open('notebooks/databricks/circuit_daily_evolution_view.sql').read()))"), \"wait_timeout\": \"30s\"}"
   ```
   and the same for `circuit_map_lines_equipment_view.sql` (only if `indicadores_vano_v_3` exists — see step 3).

## 5. Create and publish the Lakeview dashboard

1. Build the create-request payload (the dashboard JSON must be embedded as an escaped string under `serialized_dashboard`, not passed as `--serialized-dashboard` on the command line — it is too large):
   ```
   python3 -c "
   import json
   spec = open('notebooks/databricks/circuit_explorer_dashboard.lvdash.json').read()
   payload = {
       'display_name': '<user-provided dashboard name>',
       'warehouse_id': '<warehouse_id>',
       'serialized_dashboard': spec,
   }
   json.dump(payload, open('/tmp/lakeview_create_payload.json', 'w'))
   "
   ```
2. Create the draft dashboard:
   ```
   databricks lakeview create --json @/tmp/lakeview_create_payload.json -p <profile>
   ```
   Capture the returned `dashboard_id`.
3. Publish it:
   ```
   databricks lakeview publish <new_dashboard_id> --warehouse-id <warehouse_id> -p <profile>
   ```
4. Verify:
   ```
   databricks lakeview get <new_dashboard_id> -p <profile>
   ```
   Confirm `lifecycle_state` is `ACTIVE` and `warehouse_id` matches.
5. Delete the temp payload file (`/tmp/lakeview_create_payload.json`) once confirmed.

## 6. Report back

Tell the user, in their language:
- The new `dashboard_id` and which profile/workspace it was created in.
- That it's reachable from that workspace's Databricks UI under Dashboards (do not fabricate a direct URL — none was confirmed from the CLI's output).
- Which of the 6 prerequisite objects were already present vs. freshly built in this run.
- If `indicadores_vano_v_3` was missing and the user chose to proceed anyway: remind them the geo maps will show query errors until that table is provisioned.
