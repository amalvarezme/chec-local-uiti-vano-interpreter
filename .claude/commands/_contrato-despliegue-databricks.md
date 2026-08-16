---
description: Shared contract for every Databricks deployment command in this repo (`/app-*`, `/subir-*-databricks`) — the run log, the never-abort rule, Unity Catalog target resolution, and the catalogue of restrictions already met in the field. Not invocable on its own.
---

This file is an appendix, not a command. Every command in the family reads it
**first** and follows it for the four concerns below. It exists because those
concerns were previously copy-pasted into every command file and drifted.

Sections:
- **A. The run log (bitacora)** — every run writes one Markdown report.
- **B. Never abort** — a restriction is data to record, not a reason to stop.
- **C. Resolving the Unity Catalog target** — the catalog is discovered, never assumed.
- **D. Known restrictions** — what has already been hit, with the workaround.
- **E. Profile and warehouse** — resolving the CLI profile and a SQL warehouse.

---

## A. The run log (bitacora) — mandatory

Every run of every command in this family MUST produce one Markdown log under
`reports/despliegues/`, written incrementally by `scripts/bitacora_despliegue.py`.
This is not optional and not "if something goes wrong": a clean run must produce
one too, because the log is also the record of what a healthy deploy looks like.

**Open it as the very first action, before asking the user anything** — an
abandoned run must still leave evidence of how far it got.

```
RUTA_BITACORA=$(python3 scripts/bitacora_despliegue.py init \
  --comando /app-vano-clima \
  --cuaderno notebooks/base_apps/01_uiti_vano_clima.ipynb)
```

Then, **after every numbered step**, record it. Not at the end from memory — at
the time, so a crash mid-step leaves the preceding steps intact:

```
python3 scripts/bitacora_despliegue.py paso --archivo "$RUTA_BITACORA" \
  --id 2 --titulo "Preflight" --estado ok \
  --detalle "El Volume existia; faltaban los shapefiles" \
  --comando "databricks fs ls dbfs:/Volumes/.../data/GEO -p azure-chec" \
  --salida "$SALIDA_RECORTADA"
```

`--estado` is one of:

| Estado | Cuando |
|---|---|
| `ok` | El paso hizo lo que debia |
| `degradado` | Se logro el objetivo por un camino alterno (anotar cual en `--detalle`) |
| `restriccion` | Bloqueado por un permiso/cupo/limite externo; ademas registrar la restriccion |
| `fallo` | Fallo tecnico que no es una restriccion externa |
| `omitido` | No se corrio, por depender de un paso anterior que no quedo |

Every `restriccion` and every `fallo` also gets its own entry, with the field
that actually matters — **who can unblock it**:

```
python3 scripts/bitacora_despliegue.py restriccion --archivo "$RUTA_BITACORA" \
  --id R1 --titulo "Falta USE CATALOG para el service principal" \
  --severidad bloqueante --paso 6 \
  --evidencia "<mensaje literal del CLI>" \
  --impacto "La app arranca pero responde 500 al leer el Volume" \
  --rodeo "Se otorgo READ_VOLUME sobre el Volume, que si se puede" \
  --quien-desbloquea "El dueno del catalogo (ver Catalog Explorer > Owner)"
```

Severidad: `bloqueante` (el objetivo del comando no se cumple), `limitante`
(se cumple a medias), `informativa` (no afecta el resultado, pero costo tiempo
y conviene que quede escrito).

Close it as the last action, always — including when the run went badly:

```
python3 scripts/bitacora_despliegue.py cerrar --archivo "$RUTA_BITACORA" --url "<url de la app>"
python3 scripts/bitacora_despliegue.py resumen --archivo "$RUTA_BITACORA"
```

`cerrar` derives the final state and prints it: `COMPLETO`,
`COMPLETO CON RESTRICCIONES`, or `INCOMPLETO`. **Do not report success to the
user in terms softer than what `cerrar` printed.** If it says INCOMPLETO, the
message to the user says so too.

The final report to the user MUST include the path of the log and its final
state. The log is a deliverable of the command, on the same footing as the app.

**Do not paste secrets into `--salida` or `--evidencia` deliberately.** The
script redacts tokens it recognises (`dapi…`, JWTs, `Bearer …`,
`"access_token": …`), but that is a safety net, not a licence.

### A1. One log per run, even when commands delegate

When a command delegates to another (`/subir-a-databricks` calling
`/app-vano-clima`, or any command calling `/subir-datos-databricks`), the
**caller owns the log and the callee reuses it**. Pass `$RUTA_BITACORA` down;
the delegated command skips `init` and writes its steps into the same file,
prefixing its step ids so they stay distinguishable — `5.1`, `5.2` for the first
delegated command, `6.1`… for the next.

A run that fans out to five app deployments must leave **one** report the user
can read end to end, not six partial ones. Only the outermost command calls
`init` and `cerrar`.

## B. Never abort on a restriction

This overrides every "stop and report exactly that" instruction still present
in the individual commands. Those were written for a workspace where the user
could fix the privilege themselves; that is no longer the general case, and
stopping at the first wall produces a report that hides the second one.

**The rule**: when a step hits a permission, quota or platform limit, record the
restriction, apply the best available workaround, and **carry on to the end of
the command**. The purpose of the run then shifts from "deploy the app" to
"produce the complete list of everything blocking the deploy" — which is worth
far more than one early error message.

Concretely:

1. Record the restriction (section A) with its literal evidence.
2. Apply the workaround from section D if one exists; mark the step `degradado`.
3. If there is no workaround, mark the step `restriccion` and **keep going**.
4. Steps that genuinely cannot run because the previous one produced nothing:
   mark them `omitido` with the reason — but still **attempt** every step whose
   inputs are independent. Most steps are more independent than they look: the
   app can be created and deployed even when the Volume is unreadable, and doing
   so surfaces the quota and provisioning restrictions that would otherwise stay
   hidden behind the first one.
5. Never invent a fallback that changes what gets published. Degrading how a
   file is *read* is fine; publishing a different artifact is not.

The only three things that still stop a run outright:

- an expired OAuth token — needs interactive `databricks auth login`, and the
  user must run it with `!`; record it and stop,
- an explicit instruction from the user to stop,
- an action that would destroy something the user did not authorise (deleting
  an app to free quota is a destructive action — see D5, ask first).

Everything else: record, work around, continue.

## C. Resolving the Unity Catalog target — discover, never assume

Every command in this family used to hardcode `workspace.default.chec-simulador`.
**That catalog does not exist in every workspace** and cannot always be created
(see D1). Resolve it at runtime instead, once, at the start:

```
databricks catalogs list -o json -p <profile> 2>/dev/null
```

Pick, in order of preference:

1. An existing catalog that already contains the `chec-simulador` volume — check
   with `databricks volumes list <catalog> default -o json -p <profile>`. If the
   volume exists, that is the target, full stop.
2. `workspace`, if it exists and the profile has `CREATE VOLUME` on `default`.
3. Any catalog where the profile holds `CREATE VOLUME`. **Prefer a schema with
   its own `storage_root`** — a schema that inherits the metastore root is the
   FUSE failure in D2. Check with
   `databricks schemas get <catalog>.<schema> -o json -p <profile>` and read
   `storage_root`; a schema showing none inherits.

Carry the result as `<catalogo>.<esquema>.chec-simulador` and derive both forms
from it — the FUSE path `/Volumes/<catalogo>/<esquema>/chec-simulador` and the
DBFS path `dbfs:/Volumes/<catalogo>/<esquema>/chec-simulador`. Where an existing
command still writes `workspace/default/chec-simulador` literally, substitute the
resolved value; the literal is a default, not a requirement.

Volume identifiers with a hyphen need backticks in SQL DDL:
``CREATE VOLUME <catalogo>.<esquema>.`chec-simulador` ``.

Record the resolved target in the log (`init --destino`), and record any
deviation from `workspace.default` as an `informativa` restriction — the next
run should not have to rediscover it.

## D. Known restrictions and their workarounds

Each of these was hit on a real run. When one appears, do not re-diagnose it:
record it with the id below and apply the workaround.

### D1 — The `workspace` catalog does not exist and cannot be created

Seen on `adb-418048194347500.0.azuredatabricks.net` (profile `azure-chec`). The
metastore grants only `USE_MARKETPLACE_ASSETS`, so `CREATE CATALOG` is refused.

**Workaround**: section C's discovery. Severity `informativa` once resolved —
it only becomes blocking if no catalog anywhere allows `CREATE VOLUME`.

### D2 — The FUSE mount of `/Volumes` answers 403 while the Files API works

A volume created in a schema with no `storage_root` of its own inherits the
metastore root, whose storage credential the compute cannot read. The volume is
perfectly writable through `databricks fs cp` and readable through
`w.files.download()`, but **`/Volumes/...` does not mount**: `mount.err` inside
the volume reads `adlv2: HTTP 403 ... permission denied`.

The trap is the symptom. A notebook whose shim sets
`REPO_ROOT = Path('/Volumes/...')` dies at `read_csv` with a plain
`FileNotFoundError` that never mentions mounting, and it is easy to lose an hour
in Unity Catalog permissions that are all fine.

**Workaround, in order**:
1. Prefer a schema whose `storage_root` is its own (section C.3). This is a real
   fix, not a patch.
2. If none is available, keep the volume and change how the notebook *reads*:
   replace the FUSE path with a Files API download into local scratch at the top
   of the shim, and point `REPO_ROOT` at that scratch directory:
   ```python
   from pathlib import Path
   from databricks.sdk import WorkspaceClient

   REPO_ROOT = Path('/local_disk0/chec')          # scratch del driver, no el Volume
   VOLUMEN = '/Volumes/<catalogo>/<esquema>/chec-simulador'
   w = WorkspaceClient()

   def traer(relativa: str) -> Path:
       destino = REPO_ROOT / relativa
       destino.parent.mkdir(parents=True, exist_ok=True)
       if not destino.exists():
           with open(destino, 'wb') as fh:
               fh.write(w.files.download(f'{VOLUMEN}/{relativa}').contents.read())
       return destino
   ```
   Call `traer()` for the CSV and for **every shapefile sidecar** — `.shp` alone
   is useless without `.shx`, `.dbf` and `.prj` (D6). Writing results back goes
   through `w.files.upload(...)`, not an open() on `/Volumes`.
   Mark the step `degradado`, not `ok`.

The **serving** side is already safe: the `app.py` in every command reads through
`w.files.download`, precisely because the container may not have the mount.

### D3 — `uc_securable` fails without `USE CATALOG` on the catalog

```
Cannot add volume ...: all account users lack USE CATALOG permission on catalog
"<catalogo>", and the user does not have MANAGE permission on the catalog to
grant it to the app's service principal.
```

Being the *volume's* owner is enough to grant `READ_VOLUME` to the app's service
principal, but without `USE CATALOG` **and** `USE SCHEMA` the chain stays broken
and the app answers 500.

**Workaround**: create the app **without** the `resources` block, grant what you
can on the volume, and continue to deploy. The app will come up `RUNNING` with
`/salud` returning 200 — that is worth having, because it proves everything
except the grant. Record it `bloqueante`, and name the catalog owner as the one
who unblocks it (read the `Owner` field from `databricks catalogs get`). The
required grants, for the report:

```
GRANT USE CATALOG ON CATALOG <catalogo> TO `<sp_client_id>`;
GRANT USE SCHEMA  ON SCHEMA  <catalogo>.<esquema> TO `<sp_client_id>`;
```

`<sp_client_id>` is new on every app re-creation — read it from this app's
`databricks apps get`, never from a previous run.

### D4 — `GRANT` through `databricks api post` is denied to the assistant

Claude Code's auto-mode classifier allows `SHOW GRANTS` and denies `GRANT`. Do
not look for a way around it. Hand the exact statement to the user to run with
the `!` prefix, then verify with `SHOW GRANTS` that the row count moved. Record
`limitante` if the user runs it, `bloqueante` if nobody present can.

### D5 — Apps quota, and the states that look like failures

- The workspace caps at **3 apps**, and an app in `DELETING` still counts. After
  a delete, poll `apps list` until the name is **gone** (~45 s); the delete is
  not synchronous.
- Creating in the instant the slot frees leaves the app in `compute_status:
  ERROR` (`App creation failed unexpectedly`). Stop/start does not fix it —
  delete, wait for it to leave the listing, recreate. Wait ~20 s beyond seeing
  the slot free.
- A clean create can still land in `ERROR` with `Unexpectedly failed to start
  compute`. That one **is** fixed by `apps stop` → wait `STOPPED` → `apps start`.
- `apps create` and `apps deploy` wait for a terminal state and, on failure,
  exit non-zero with **empty stdout** — `json.load` on it dies with
  `Expecting value: line 1 column 1`. The app may well have been created anyway:
  check with `apps get` before retrying.
- `apps deploy` can fail repeatedly against a healthy app while the previous
  deployment keeps serving. If the code change is cosmetic, do not insist —
  `/?refresh=1` refreshes the data without redeploying.

**Deleting an app to free quota is destructive: ask the user first**, naming
which app would go. If they decline, record `bloqueante` and continue with the
rest of the command (the HTML still gets generated and verified).

### D6 — Upload limits and the things `fs cp` drags along

- `databricks workspace import --format JUPYTER` enforces a **10 MB** payload
  limit. Always strip `outputs` and `execution_count` from the staged copy.
  **Exception: notebook 04's stored output must not be stripped in the repo** — it
  is the board published as-is, so a stale one ships controls the source already
  removed. Strip the staged copy only. (Before 2026-08-15 the reason was that a
  script parsed its HTML for the K-Means geometry; that geometry is now tracked at
  `data/geometria_kmeans_014_v1.json` and the script is gone. The exception stands
  on the publishing argument alone.)
- `databricks fs cp -r` and `workspace import-dir` have **no exclude flag**. They
  will upload `.DS_Store`, `.gitkeep`, `.openmeteo_cache.sqlite` and
  `__pycache__/*.pyc`. Clean up afterwards with `fs rm` / `workspace delete
  --recursive`; there is no upload-time filter to lean on.
- `workspace import`/`import-dir` do **not** create parent folders. Run
  `databricks workspace mkdirs` before every import.
- A shapefile is a **set**. `MVLINSEC.shp` without `.shx`/`.dbf` fails inside the
  job with an opaque driver error, and without `.prj` geopandas cannot resolve
  the CRS for `to_crs('EPSG:4326')`. Check the set, never just the folder.
- `data/Indicadores_vano_v3.csv` is **566 MB** and Git-LFS tracked. Confirm it is
  a real payload, not a ~130-byte pointer (`ls -l`), and `git lfs pull` if it is.

### D7 — Never pipe `2>&1` into a JSON parser

The CLI intermittently prints `Databricks skills are not installed...` on
**stderr**. Merged into stdout it prepends non-JSON and `json.load` dies with
`Expecting value: line 1 column 1` on a perfectly healthy call — which reads as
an auth failure when the token is fine. Use `2>/dev/null` when parsing, and
`2>&1` only when you actually want to read the error.

### D8 — Notebooks using `ipywidgets` cannot run on Serverless

Databricks requires a running classic cluster for `ipywidgets`; Serverless is
excluded, and the failure is silent (the cell executes, the widget never
renders). This affects the notebook-06 simulator path, which is why
`/app-simulador-vano` serves it through Voila on a live kernel rather than as a
static HTML job. Notebooks 01–04 use no `ipywidgets` and are fine on Serverless.

### D9 — Workspace state is not durable between sessions

A prior session's memory that "the tables/volume already exist" has been wrong
before, in this exact repo, on this exact workspace. Always re-run the read-only
preflight. Never skip a check because a note says it passed last time.

### D10 — `git push` can fail on the LFS locking API

`Remote "amalvarezme" does not support the Git LFS locking API ... Fatal error:
Unable to verify locks`. Only `data/Indicadores_vano_v3.csv` and `data/GEO/**`
are LFS-tracked, so a push touching only `.claude/`, `notebooks/` or
`reports/despliegues/` never exercises the locking API and goes through fine.
It has not reproduced in the last four pushes.

**Always try the plain `git push` first.** Only if it fails with that message,
hand the user this to run with the `!` prefix — the auto-mode classifier blocks
the assistant from running it, reading `-c` as a config mutation even though it
does not persist:

```
git -c lfs.https://github.com/amalvarezme/chec-local-uiti-vano-interpreter.git/info/lfs.locksverify=false push
```

Do not retry the `-c` form yourself, and do not run `git config` to persist it —
that is the user's call. Record it `limitante`.

**A second thing rejects a push: GitHub secret scanning.** It fires on the
*shape* of a credential, so a `dapi…` string in a committed bitacora blocks the
push even if the token is dead or invented (confirmed — it rejected a deliberately
fake one in a test fixture). If it fires, the right move is to remove the secret
from the commit, never to click the "allow secret" URL in the error. This is the
backstop behind the redaction in section A, not a replacement for it: keep tokens
out of `--salida` in the first place.

## E. Resolving the CLI profile and the SQL warehouse

These lived in `/deploy-databricks-dashboard` sections 1–2 and every other
command cross-referenced them. That command is gone (the Lakeview dashboard and
the Delta tables job were retired), so they live here now. Nothing about them
changed.

### E1. CLI profile

```
databricks auth profiles
```
Normalize the given URL (strip the trailing slash) and match it against the
`Host` column.

- **Match found** → use that profile (`-p <profile>`) for every command.
- **No match** → tell the user no CLI profile is configured for that host and
  ask them to run this themselves with the `!` prefix (interactive OAuth, it
  cannot be run for them), then re-run `databricks auth profiles`:
  ```
  databricks auth login --host <workspace-url>
  ```

`databricks auth profiles` prints a `Valid` column — treat it as advisory only.
An expired refresh token surfaces only on a real call:
```
databricks current-user me -p <profile> -o json 2>/dev/null
```
Take `userName` from it for every `/Workspace/Users/<userName>/…` path. Mind D7:
never pipe `2>&1` into a JSON parser.

### E2. SQL warehouse

Only needed to run `SHOW GRANTS` through `/api/2.0/sql/statements` when
verifying an app's volume permission (D3, D4). No other step needs it.

```
databricks warehouses list -p <profile>
```
Pick the first warehouse in `RUNNING` state. If none is running, pick the first
available one regardless of state — it auto-starts on the first query. If the
list is empty, **do not create one**: a warehouse has ongoing cost the user
should choose to incur. Record it as a `limitante` restriction (the grant cannot
be verified, though it may well have been applied) and continue.
