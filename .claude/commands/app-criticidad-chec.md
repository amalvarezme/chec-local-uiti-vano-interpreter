---
description: Publica los cuatro tableros estaticos de criticidad como UNA sola Databricks App con cuatro rutas. Los construye antes de subir con el mismo codigo que corre la aplicacion de escritorio, asi que no hace falta cluster ni cuaderno. Reemplaza a /app-vano-clima, /app-agrupamiento-vanos-circuitos, /app-trayectorias-circuitos y /app-trayectorias-vanos. Pregunta el nombre de la app y la URL del workspace destino.
---

> **Read `.claude/commands/_contrato-despliegue-databricks.md` before anything else.** It is mandatory and it overrides what follows:
> - **A. Run log** — open the bitacora *before* asking the user anything, record every numbered step as you finish it, and always close it. Its path and final state are part of the report back to the user.
> - **B. Never abort** — a restriction gets recorded and worked around; the command runs to the end regardless. Wherever this file says "stop and report", rule B applies instead.
> - **C. Unity Catalog target** — `workspace.default.chec-simulador` below is a default, not a requirement. Resolve it at runtime and substitute the resolved value into every path here.
> - **D. Known restrictions** — D1–D10. If one shows up, do not re-diagnose it.

Follow this exact sequence when `/app-criticidad-chec` is invoked. It publishes the four
static criticality dashboards — clima, agrupamiento, trayectorias de circuitos y
trayectorias de vanos — as **one** Databricks App with four routes, and it is
**self-healing**: it inspects the target workspace first and creates whatever is missing.

## Por que una app y no cuatro

Habia un comando y una app por tablero. Dos cosas los mataron a la vez:

1. **El cupo.** El workspace topa en **tres apps** (D5), asi que el cuarto tablero no
   cabia nunca. `/subir-a-databricks` llevaba una tabla de prioridad y dejaba `03` y `04`
   sin desplegar, con una restriccion `R-CUPO` anotada en cada corrida.
2. **El cuaderno.** Los cuatro publicaban parcheando un `.ipynb` por contenido y
   corriendolo como job en un cluster. Ese codigo salio a `src/chec_tableros/` en agosto
   de 2026 y los `.ipynb` se borraron: los cuatro comandos quedaron apuntando a archivos
   que no existen.

Una app con cuatro rutas gasta **un** cupo y deja de necesitar la tabla de prioridad. Y
como los tableros ahora son modulos, se construyen **aqui**, con el entorno del
repositorio, antes de subir nada: no hay job, no hay cluster, no hay cuaderno.

Medido en esta maquina: los cuatro paneles se construyen en **menos de 30 s** y pesan
**14,7 MB** en total ya comprimidos. Antes, cada uno era un job sobre un cluster que
habia que esperar a que arrancara.

**El simulador no esta aqui, y no es un olvido.** Su boton *Simular* corre el modelo MIL
de PyTorch sobre lo que el usuario elija: necesita un interprete vivo, y esto sirve
archivos. Se publica aparte, y ese comando es el unico que sigue necesitando un cluster
clasico (D8).

**Scope.** MUST NOT create or refresh any Delta table or view, MUST NOT touch any
Lakeview dashboard, MUST NOT modify anything under `src/` or `aplicaciones/`, and MUST
NOT create any `site`-named path inside the Volume.

## 0. Ask the user for the two required inputs

Open the bitacora first (rule A), then ask, one at a time, and wait for each answer:

1. **The name for the Databricks App.** The API constrains this to 2–30 characters,
   lowercase alphanumerics and hyphens, unique in the workspace. Default: `criticidad-chec`.
2. **The workspace URL.** Ask every run. Do **not** infer it from whichever profile
   happens to have a live session — that is how a deploy lands in the wrong workspace,
   and it is silent when both are reachable.

```
RUTA=$(python3 scripts/bitacora_despliegue.py init \
  --comando /app-criticidad-chec \
  --cuaderno "src/chec_tableros/ (clima, agrupamiento, trayectorias_circuitos, trayectorias_vanos)" \
  --workspace <url> --app <nombre> --perfil <perfil>)
```

## 1. Resolve profile and identity

Contract §E1. Record the profile and the `userName` — the Workspace path in step 5
depends on it.

## 2. Resolve the Unity Catalog target

Contract §C. Resolve `<catalogo>.<esquema>.chec-simulador` and use the resolved value
everywhere below. `workspace.default.chec-simulador` **is a default, not a requirement**:
that catalog does not exist in the CHEC workspace (D1).

Two paths matter from here on:

| | |
|---|---|
| paneles | `/Volumes/<catalogo>/<esquema>/chec-simulador/paneles/<clave>/` |
| fuente de la app | `/Workspace/Users/<userName>/databricks-integration/apps/<nombre>/` |

Create the Volume if it is missing, exactly as the retired `/app-vano-clima` §2a did.

## 3. Build the four panels — locally, no cluster

```
python3 scripts/empacar_app_databricks.py paneles --destino <scratch>/paneles
```

It prints one JSON entry per board with `estado` and either its packed size or the
reason it failed. **This is the step that replaced a notebook, a shim of four
content-edits and a Databricks job.**

Three properties it already guarantees, so do not re-implement them here:

- It builds with `chec_tableros.<modulo>.construir()` — the same code the desktop app
  runs. A second build path would be a second dashboard that has to match forever.
- A board that fails **does not stop the others**. Record it as a `degradado` step
  naming the board, and carry on.
- A board that fails leaves **no folder at all**. It never leaves a half-written mix of
  old and new pieces, which is a panel that loads and lies.

Record one numbered sub-step per board (`3.1`–`3.4`) with its size, so the bitacora says
what got published and what did not.

> One honest difference to know about: this builds with the **repository's** environment,
> and the desktop apps build with their own. Today that means the published panels carry
> plotly 3.6.0 and the local ones 3.7.0. Each panel is self-consistent — it bundles the
> version it was built with — so this is not a defect; it is just a reason not to chase a
> phantom difference when comparing a published panel against a local one.

## 4. Upload the panels

For each board that succeeded:

```
databricks fs mkdir dbfs:/Volumes/<catalogo>/<esquema>/chec-simulador/paneles/<clave> -p <perfil>
databricks fs cp <scratch>/paneles/<clave> \
  dbfs:/Volumes/<catalogo>/<esquema>/chec-simulador/paneles/<clave> -r --overwrite -p <perfil>
```

Then list it back and compare against the `manifiesto.json` inside each folder. `fs cp -r`
drags `.DS_Store` along on macOS (D6) — delete it from the Volume if it appears.

**Upload the `.gz` files too.** They are not a build artifact to strip: the app serves
them directly to any browser that accepts gzip, and compressing on the fly would mean
recompressing 29 MB per request.

## 5. Stage and upload the app source

```
python3 scripts/empacar_app_databricks.py fuente \
  --destino <scratch>/fuente \
  --raiz-paneles /Volumes/<catalogo>/<esquema>/chec-simulador/paneles
```

The app lives in `aplicaciones/databricks/criticidad_chec/` **as real, tested code** — it
is not a block of Python pasted from this file, which is what its four predecessors did.
The script copies the five own files plus `tableros.py` and `paleta.py` from
`aplicaciones/_comun/` (that is how the app shows the same titles and colours as the
desktop menu without writing them twice) and substitutes the resolved Volume path into
`app.yaml`.

Upload with `--format RAW` — `import-dir` has no exclude mechanism and reinterprets `.py`
as notebooks:

```
databricks workspace mkdirs <base> -p <perfil>
for f in app.py catalogo.py pagina.py tableros.py paleta.py; do
  databricks workspace import <base>/$f --file <scratch>/fuente/$f \
    --format RAW --language PYTHON --overwrite -p <perfil>
done
for f in app.yaml requirements.txt; do
  databricks workspace import <base>/$f --file <scratch>/fuente/$f \
    --format RAW --overwrite -p <perfil>
done
```

## 6. Create the App, declaring the Volume as a resource

Create it with a `uc_securable` resource so Databricks applies the volume grant itself,
exactly as the retired commands did. If it fails for lack of `USE CATALOG`, that is **D3**:
create the app **without** the `resources` block, record the restriction as `bloqueante`
naming who can unblock it, and carry on (rule B). The app will answer 502 on every board
route until the grant exists — which is why `/salud` deliberately does not touch the
Volume, and why a missing piece answers 404 and a permission wall answers 502.

## 7. Deploy

Poll `apps get` until `compute_status` is `ACTIVE`, then `apps deploy`. D5 lists the
states that look like failures and are not.

**If the create fails on the app cap**: parse `N` from the error text (there is no quota
API), record `R-CUPO` as `limitante`, and **ask the user before deleting anything** —
naming which app you would delete. Deleting an app is destructive. After a delete, poll
`apps list` until the name is *gone* (~45 s): an app in `DELETING` still counts (D5).

This is also the cutover point. The four old apps this one replaces — whatever they are
called in the target workspace — are now redundant. **Ask before deleting each one**, one
at a time, and record the answer. Do not assume that publishing this one authorises
removing those.

## 8. Verify and report back

```
curl -sS -o /dev/null -w '%{http_code}\n' <url>/salud
curl -sS <url>/tableros
```

`/tableros` returns the routes actually registered and the Volume root they read from —
it is the cheapest way to tell "the app is up but the panels are missing" from "the app
is down". Then fetch each of the four routes and check for a `200`.

Report back:
- **The URL**, and the four routes under it.
- **Which boards published** and which came back `degradado`, with the reason.
- **The bitacora**: its path under `reports/despliegues/` and its final state.
- **Any restriction** recorded, with who can unblock it.
