# Flujo detallado del proyecto — CHEC UITI_VANO Interpreter

> Versión HTML: [`flujo-detallado.html`](./flujo-detallado.html) (mismo contenido). Actualizado 2026-07-25, rama `main` (única rama del proyecto desde la consolidación de ramas de esa fecha).
>
> Audiencia: ingeniería / mantenimiento del repo. Para una versión sin jerga técnica, ver [`flujo-resumen.md`](./flujo-resumen.md) / [`flujo-resumen.html`](./flujo-resumen.html).

## 1. Panorama

El proyecto sostiene **dos flujos** que comparten la misma fuente de verdad — el CSV `Indicadores_vano_v3.csv` y la función real `compute_circuit_criticality_groups` — pero terminan en destinos distintos y **no comparten runtime ni credenciales**:

- **Flujo A — pipeline local de reportes.** Genera HTML por circuito (o por lote) usando agentes LLM de Claude Code, publicado opcionalmente a un vault Obsidian indexado con `graphify`.
- **Flujo B — despliegue a Databricks.** Sube al Volume los datos que consumen los cuadernos `01`-`06` y el comando `/report`, importa el cuaderno `05` al Workspace y publica los demás como Databricks Apps. **No crea tablas Delta, vistas ni dashboards**: el stack Lakeview (`/deploy-databricks-dashboard`, `notebooks/databricks/`) se retiró.

Un cambio en `plotting.py` no se refleja en Databricks hasta que se re-ejecuta `uiti_vano_tables.py` — son copias de datos independientes, no una vista en vivo del mismo backend.

## 2. Flujo A — pipeline local de reportes

### 2.1 Comandos

| Comando | Uso | Qué produce |
|---|---|---|
| `/report` | `/report CIRCUITO [fecha_inicio fecha_fin]` | HTML de un circuito, 9 pasos completos |
| `/reporte-lote` | `/reporte-lote grupo=alta` | Un reporte por circuito del grupo + scatter de clustering |
| `/informe-gerencial` | `/informe-gerencial grupo=media` | Un HTML gerencial cross-circuito (12 representativos) |
| `/agrupamiento-circuitos` | `/agrupamiento-circuitos` | Solo el scatter de clustering, sin reporte |
| `/limpiar-corridas` | `/limpiar-corridas` (dry-run primero, confirmación explícita) | Borra artefactos desechables de corridas previas |

Los tres agentes que hacen el razonamiento LLM (`historical`, `inference`, `expert-alignment`) son los mismos en los tres comandos de reporte — `reporte-lote` e `informe-gerencial` nunca los reimplementan, solo re-invocan `.claude/skills/report/SKILL.md` por referencia.

### 2.2 Orquestación de `/report` (motor: `report_pipeline.py`)

1. `prepare()` — detección de puntos críticos + contexto estructurado + simulador MGCECDL-SHAP + escaneo automático min/max.
2. Despacho paralelo obligatorio: `historical` (diagnóstico descriptivo) e `inference` (SHAP/MGCECDL) corren en paralelo, no dependen entre sí. `auto-simulator` corre junto pero degrada solo (opcional) si falta `bc.json`.
3. Join — cuando `historical` + `inference` terminan: `prepare_expert_alignment()` → agente `expert-alignment` (compara contra la discusión experta en PDF).
4. `render()` → HTML del circuito.
5. Paso 9 (alert-and-continue): skill `vault-circuito` proyecta 3 JSON validados a `reports/vault/*.md`, luego `graphify --update` indexa — **siempre aislado**, nunca `--update` sobre el manifiesto amplio (ver lección aprendida abajo).

Cada agente valida su propio JSON contra un esquema antes de aceptarlo; un JSON inválido se reintenta o se guarda como fallo explícito, nunca se publica sin validar.

> **Lección aprendida — aislamiento de graphify.** El paso 2.5 de `informe-gerencial` reconstruye el grafo del vault de forma completamente aislada después de un incidente de producción donde una actualización con alcance mal delimitado podó ~271 archivos no relacionados. `vault-circuito` sigue el mismo principio: su `/graphify --update` queda acotado únicamente a `reports/vault/graphify-out/graph.json`.

### 2.3 Los cuadernos de `notebooks/`

La carpeta se renumeró el 2026-08-04 y se reorganizó el 2026-08-13: `project_flow/` desapareció y su
contenido subió a `notebooks/`. Hoy quedan **`05` y `07`** sueltos y una subcarpeta `old_version/` con
**13**: los cinco tableros `uiti_vano` (`01`-`04` y `06`, que siguen siendo la fuente de las tres
aplicaciones de `aplicaciones/`) y los 8 del pipeline MGCECDL original.

Ninguno de los dos grupos es el punto de entrada del proyecto — ese es `/report`. El detalle celda
por celda de los archivados vive en los cuadernos mismos: cada uno conserva sus comentarios y sus
salidas guardadas.

**Activos** (`notebooks/`):

```
01_uiti_vano_clima                     panel climático (violines + nube de rezagos), 208 circuitos
02_uiti_vano_kmeans                    agrupamiento de circuitos y de vanos por UITI acumulado
03_uiti_vano_trayectorias_circuitos    trayectorias de circuito por ventanas deslizantes + mapa
04_uiti_vano_trayectorias_vano         idem a nivel de vano; DUEÑO de la geometría KMeans
   │                                   que 05 y 06 replican (verificada por sha1)
   ├→ 05_mil_vano_ventana              MIL sobre bolsas vano × ventana (generado por
   │                                   scripts/generate_notebook_10.py)
   └→ 06_uiti_vano_explicabilidad_simulador   explicabilidad + simulador de riesgo,
                                       requiere kernel vivo (ipywidgets)
```

Los tres primeros son independientes entre sí. La única dependencia dura es la geometría de `04`:
`05` y `06` la reutilizan a través de `chec_local_interpreter.ventanas_015`, que la extrae del
archivo de `04` y verifica su sha1 — si alguien mueve los centroides de `04`, los dos fallan
ruidosamente en vez de derivar en silencio.

**Archivados** (`notebooks/old_version/`), el pipeline MGCECDL que entrenó el modelo
que `06` y `report_pipeline.py` siguen cargando desde `data/models/`:

```
02_optuna (búsqueda HP) → 03_training (modelo final)
                                 ├→ 04_performance (métricas + SHAP)
                                 ├→ 05_circuit_analysis (SHAP por circuito, ancestro de report_pipeline.py)
                                 ├→ 06_document_replication (export CSV masivo)
                                 └→ 09_simulador (interactivo, ipywidgets)
07_graph_preserved_connections (grafo experto, cache opcional para 03, no bloqueante)
08_geo_network_exploration (standalone, solo shapefiles + CSV)
```

Ojo con la colisión de numeración: `02`/`03`/`04`/`05`/`06` significan cosas distintas según el
grupo. En este documento y en los comandos, un número suelto se refiere siempre al grupo **activo**;
los archivados se nombran con su archivo completo.

El enriquecimiento climático que hacía el viejo `01_climate.ipynb` ya no vive en un cuaderno: lo
hace el comando `/clima`, y `01_uiti_vano_clima` solo lo visualiza.

## 3. Flujo B — despliegue a Databricks

Cuatro comandos cooperan, todos en `.claude/commands/`, todos reutilizando por referencia cruzada la misma resolución de perfil CLI / SQL warehouse (nunca duplicada):

| Comando | Qué migra | Toca tablas/dashboard |
|---|---|---|
| `/subir-datos-databricks` | `data/` completo + `site/data/variables.json` (única excepción fuera de `data/`) al Volume | No |
| `/subir-notebooks-databricks` | Los tres paquetes fuente (`chec_local_interpreter`, `chec_impacto`, `scripts`) + los 6 cuadernos activos (copias adaptadas); `old_version/` NO se sube | No |
| `/subir-a-databricks` | Orquesta los tres anteriores + tablas + reportes de interpretabilidad + dashboard en una sola corrida | Sí |

### 3.1 Objetos de datos (5, todos reproducibles desde este repo)

| Objeto | Tipo | Origen |
|---|---|---|
| `indicadores_vano` | Tabla Delta | CSV tipado con TODAS las columnas (incluida geometría X1/Y1/X2/Y2/FID_VANO/FID_TRAFO/FID_SW), vía `uiti_vano_tables.py` |
| `circuit_clustering` | Tabla Delta | Llama *verbatim* a `plotting.compute_circuit_criticality_groups` — mismos números que `/agrupamiento-circuitos` local |
| `circuit_geo` | Tabla Delta | Shapefile `MVLINSEC.shp` vía geopandas (construida pero no usada por los widgets actuales del dashboard) |
| `circuit_map_lines_equipment` | Vista | UNION de vanos/transformadores/switches sobre `indicadores_vano` |
| `circuit_daily_evolution` | Vista | Serie diaria con ceros, sobre `indicadores_vano` |

> **Corrección 2026-07-24**: una versión anterior de estos documentos listaba una sexta tabla, `indicadores_vano_v_3`, como "prerrequisito externo sin ETL en este repo". Era falso — la vista solo apuntaba al nombre de tabla equivocado; `indicadores_vano` ya trae esas columnas.

### 3.2 Restricción dura: nada de `site/` en Databricks

Ninguno de los cuatro comandos puede crear una ruta con nombre `site/` dentro del Volume de Databricks. La página web del proyecto (`site/`, publicada vía GitHub Actions/Pages) **solo se regenera con una corrida local** contra las rutas reales del repo. De los 6 cuadernos activos, solo `04` y `07` originalmente escriben ahí (figuras PNG y grafos HTML respectivamente); sus copias subidas a Databricks redirigen esa salida a carpetas del Volume sin la palabra "site" (`SITE_RESULTS_DIR = RESULTS_DIR` en `04`; `outputs/graphs/` en `07`).

### 3.3 Notebooks en Databricks — shims y gotchas reales (encontrados en corridas en vivo)

`/subir-notebooks-databricks` sube cada uno de los 6 cuadernos activos como una **copia modificada** (nunca el original del repo) con solo su celda de resolución de rutas reescrita (alias a variables del Volume, no reemplazo total de la celda). Hallazgos empíricos, no teóricos:

- **Cada copia necesita su propia celda `%pip install -q -r requirements.txt`** como primera celda. El entorno local pre-configurado no existe en Databricks; sin esto, cualquier notebook que importe `chec_impacto`/`chec_local_interpreter` puede fallar con `ModuleNotFoundError` para cualquier paquete de esa cadena de imports (confirmado con `optuna` en el archivado `09_simulador`; `05` y `06` importan el mismo paquete y heredan el riesgo). El `requirements.txt` subido excluye `jupyter`/`ipykernel`/`pytest`/`python-dotenv`/`pydantic` (0 referencias en `src/` o en los notebooks, verificado por auditoría AST de imports).
- **`workspace import`/`import-dir` no crean carpetas padre** — hace falta `databricks workspace mkdirs` explícito antes de subir archivos sueltos o notebooks.
- **`--format JUPYTER` tiene un límite de 10MB**, y para este conjunto no es un caso borde sino la norma: medido, `01` pesa **81,43 MB** con salidas (0,05 MB sin), `03` 11,58 MB y `04` 12,31 MB — tres de seis pasan el techo. Hay que limpiar `outputs`/`execution_count` de las 6 copias antes de subir.
- **Los SQL Warehouse no pueden ejecutar notebooks** — solo celdas SQL. Un notebook debe adjuntarse a un cluster o a Serverless (compute Python), nunca a un Warehouse.
- **`06_uiti_vano_explicabilidad_simulador.ipynb` necesita un cluster clásico ("all-purpose"), no Serverless** — todo su panel es `ipywidgets`, y la documentación de Databricks es explícita: *"A notebook using ipywidgets must be attached to a running cluster"*, excluyendo Serverless. Los otros 5 activos sí funcionan en Serverless. La regla se descubrió con el archivado `09_simulador`, que la hereda.
- **El Volume `chec-simulador` no persiste entre sesiones garantizado** — un workspace verificado como completamente poblado un día apareció vacío (0 tablas, sin Volume) al día siguiente. Siempre verificar en vivo (`SHOW TABLES`, `databricks fs ls`) antes de asumir estado previo.

### 3.4 El stack Lakeview se retiró

El dashboard AI/BI "Explorador de circuito UITI_VANO" y el job de tablas Delta que lo respaldaba
ya no existen: se borraron `/deploy-databricks-dashboard` y `notebooks/databricks/`. Lakeview no
ejecuta Python ni JS arbitrario, así que nunca pudo mostrar el análisis real de los cuadernos
(K-Means, contornos de Voronoi, los mapas MapLibre); las Databricks Apps sí, y son ahora el
único camino de publicación.

Lo único que sobrevivió de ese comando es la resolución del perfil de CLI y del SQL warehouse,
que media familia reutilizaba: viven en las secciones **E1** y **E2** de
[`_contrato-despliegue-databricks.md`](../.claude/commands/_contrato-despliegue-databricks.md).

## 4. Referencia rápida — todos los comandos

| Comando | Flujo | Uso |
|---|---|---|
| `/report` | A | `/report CIRCUITO [fecha_inicio fecha_fin]` |
| `/reporte-lote` | A | `/reporte-lote grupo=alta` |
| `/informe-gerencial` | A | `/informe-gerencial grupo=media` |
| `/agrupamiento-circuitos` | A | `/agrupamiento-circuitos` |
| `/limpiar-corridas` | A | `/limpiar-corridas` |
| `/subir-datos-databricks` | B | pide URL del workspace |
| `/subir-notebooks-databricks` | B | pide URL del workspace |
| `/subir-a-databricks` | B | pide URL del workspace; orquesta datos → cuaderno `05` → apps → commit |
| `/app-vano-clima` | B | publica el cuaderno `01` como app |
| `/app-agrupamiento-vanos-circuitos` | B | publica el cuaderno `02` como app |
| `/app-trayectorias-circuitos` | B | publica el cuaderno `03` como app |
| `/app-trayectorias-vanos` | B | publica el cuaderno `04` como app |
| `/app-simulador-vano` | B | publica el cuaderno `06` como app (Voila, kernel vivo) |

## 5. Más detalle

- [`agents-guide.md`](./agents-guide.md) — arquitectura de 4 capas del framework de agentes (Skills vs. roles vs. playbooks de prompt).
- [`report-runtime-contract.md`](./report-runtime-contract.md) — contrato de invocación de `/report` entre runtimes.
- [`flujo-detallado.html`](./flujo-detallado.html) — este mismo documento en HTML.
- Los diagramas del flujo end-to-end y de la familia `/report` viven en el `README.md`, en Mermaid
  y en línea. Los `.mmd`/`.svg` sueltos de esta carpeta se retiraron: se quedaban atrás del flujo
  cada vez que este cambiaba.
