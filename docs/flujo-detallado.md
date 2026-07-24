# Flujo detallado del proyecto — CHEC UITI_VANO Interpreter

> Versión HTML: [`flujo-detallado.html`](./flujo-detallado.html) (mismo contenido). Para diagramas Mermaid interactivos y el historial de correcciones en vivo, ver [`project-flow-review.html`](./project-flow-review.html). Actualizado 2026-07-24, rama `databricks-integration`.
>
> Audiencia: ingeniería / mantenimiento del repo. Para una versión sin jerga técnica, ver [`flujo-resumen.md`](./flujo-resumen.md) / [`flujo-resumen.html`](./flujo-resumen.html).

## 1. Panorama

El proyecto sostiene **dos flujos** que comparten la misma fuente de verdad — el CSV `Indicadores_vano_v3.csv` y la función real `compute_circuit_criticality_groups` — pero terminan en destinos distintos y **no comparten runtime ni credenciales**:

- **Flujo A — pipeline local de reportes.** Genera HTML por circuito (o por lote) usando agentes LLM de Claude Code, publicado opcionalmente a un vault Obsidian indexado con `graphify`.
- **Flujo B — despliegue a Databricks.** Replica el mismo dominio (circuitos, vanos, clustering de criticidad, evolución diaria) como un dashboard AI/BI de Databricks Lakeview respaldado por tablas/vistas Delta, y opcionalmente migra datos crudos, paquetes fuente, los 9 notebooks de investigación y los reportes de interpretabilidad.

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

Los cuatro agentes que hacen el razonamiento LLM (`historical`, `inference`, `auto-simulator`, `expert-alignment`) son los mismos en los tres comandos de reporte — `reporte-lote` e `informe-gerencial` nunca los reimplementan, solo re-invocan `.claude/skills/report/SKILL.md` por referencia.

### 2.2 Orquestación de `/report` (motor: `report_pipeline.py`)

1. `prepare()` — detección de puntos críticos + contexto estructurado + simulador MGCECDL-SHAP + escaneo automático min/max.
2. Despacho paralelo obligatorio: `historical` (diagnóstico descriptivo) e `inference` (SHAP/MGCECDL) corren en paralelo, no dependen entre sí. `auto-simulator` corre junto pero degrada solo (opcional) si falta `bc.json`.
3. Join — cuando `historical` + `inference` terminan: `prepare_expert_alignment()` → agente `expert-alignment` (compara contra la discusión experta en PDF).
4. `render()` → HTML del circuito.
5. Paso 9 (alert-and-continue): skill `vault-circuito` proyecta 3 JSON validados a `reports/vault/*.md`, luego `graphify --update` indexa — **siempre aislado**, nunca `--update` sobre el manifiesto amplio (ver lección aprendida abajo).

Cada agente valida su propio JSON contra un esquema antes de aceptarlo; un JSON inválido se reintenta o se guarda como fallo explícito, nunca se publica sin validar.

> **Lección aprendida — aislamiento de graphify.** El paso 2.5 de `informe-gerencial` reconstruye el grafo del vault de forma completamente aislada después de un incidente de producción donde una actualización con alcance mal delimitado podó ~271 archivos no relacionados. `vault-circuito` sigue el mismo principio: su `/graphify --update` queda acotado únicamente a `reports/vault/graphify-out/graph.json`.

### 2.3 Los 9 notebooks de investigación (`notebooks/project_flow/`)

Estos notebooks **no** son el punto de entrada del proyecto — son el pipeline offline de entrenamiento/investigación que produce el modelo MGCECDL y sus artefactos de soporte, consumidos en modo solo-lectura por `report_pipeline.py`. Ver [`notebooks-project-flow.md`](./notebooks-project-flow.md) para el detalle celda por celda de cada uno (dependencias reales, gotchas, dónde caen los artefactos).

Resumen de orden real de ejecución (no estrictamente lineal pese a la numeración 01-09):

```
01_climate (enriquece CSV) → 02_optuna (búsqueda HP) → 03_training (modelo final)
                                                              ├→ 04_performance (métricas + SHAP)
                                                              ├→ 05_circuit_analysis (SHAP por circuito, ancestro de report_pipeline.py)
                                                              ├→ 06_document_replication (export CSV masivo)
                                                              └→ 09_simulador (interactivo, ipywidgets)
07_graph_preserved_connections (grafo experto, cache opcional para 03, no bloqueante)
08_geo_network_exploration (standalone, solo shapefiles + CSV)
```

## 3. Flujo B — despliegue a Databricks

Cuatro comandos cooperan, todos en `.claude/commands/`, todos reutilizando por referencia cruzada la misma resolución de perfil CLI / SQL warehouse (nunca duplicada):

| Comando | Qué migra | Toca tablas/dashboard |
|---|---|---|
| `/deploy-databricks-dashboard` | Nada de `data/`/notebooks — solo construye/reconstruye tablas + vistas + publica el dashboard | Sí |
| `/subir-datos-databricks` | `data/` completo + `site/data/variables.json` (única excepción fuera de `data/`) al Volume | No |
| `/subir-notebooks-databricks` | Ambos paquetes fuente (`chec_local_interpreter`, `chec_impacto`) + los 9 notebooks (copias adaptadas) | No |
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

Ninguno de los cuatro comandos puede crear una ruta con nombre `site/` dentro del Volume de Databricks. La página web del proyecto (`site/`, publicada vía GitHub Actions/Pages) **solo se regenera con una corrida local** contra las rutas reales del repo. De los 9 notebooks, solo `04` y `07` originalmente escriben ahí (figuras PNG y grafos HTML respectivamente); sus copias subidas a Databricks redirigen esa salida a carpetas del Volume sin la palabra "site" (`SITE_RESULTS_DIR = RESULTS_DIR` en `04`; `outputs/graphs/` en `07`).

### 3.3 Notebooks en Databricks — shims y gotchas reales (encontrados en corridas en vivo)

`/subir-notebooks-databricks` sube cada uno de los 9 notebooks como una **copia modificada** (nunca el original del repo) con solo su celda de resolución de rutas reescrita (alias a variables del Volume, no reemplazo total de la celda). Hallazgos empíricos, no teóricos:

- **Cada copia necesita su propia celda `%pip install -q -r requirements.txt`** como primera celda. El entorno local pre-configurado no existe en Databricks; sin esto, cualquier notebook que importe `chec_impacto`/`chec_local_interpreter` puede fallar con `ModuleNotFoundError` para cualquier paquete de esa cadena de imports (confirmado con `optuna` en `09`). El `requirements.txt` subido excluye `jupyter`/`ipykernel`/`pytest`/`python-dotenv`/`pydantic` (0 referencias en `src/` o en los notebooks, verificado por auditoría AST de imports).
- **`workspace import`/`import-dir` no crean carpetas padre** — hace falta `databricks workspace mkdirs` explícito antes de subir archivos sueltos o notebooks.
- **`--format JUPYTER` tiene un límite de 10MB** — un notebook con salidas locales embebidas (ej. mapas folium de `08`) puede superarlo aunque su código sea pequeño; hay que limpiar `outputs`/`execution_count` de las 9 copias antes de subir.
- **Los SQL Warehouse no pueden ejecutar notebooks** — solo celdas SQL. Un notebook debe adjuntarse a un cluster o a Serverless (compute Python), nunca a un Warehouse.
- **`09_simulador.ipynb` necesita un cluster clásico ("all-purpose"), no Serverless** — su interfaz final usa `ipywidgets`, y la documentación de Databricks es explícita: *"A notebook using ipywidgets must be attached to a running cluster"*, excluyendo Serverless. Los otros 8 notebooks sí funcionan en Serverless.
- **El Volume `chec-simulador` no persiste entre sesiones garantizado** — un workspace verificado como completamente poblado un día apareció vacío (0 tablas, sin Volume) al día siguiente. Siempre verificar en vivo (`SHOW TABLES`, `databricks fs ls`) antes de asumir estado previo.

### 3.4 Widgets del dashboard publicado y limitaciones conocidas de Lakeview

`clustering_scatter` (dispersión log-log por criticidad) · `circuit_detail_table` · `daily_line` (combo: eventos diarios + UITI_VANO) · `events_map` / `uiti_map` (mapas Vega-Lite en capas). Limitaciones permanentes de la plataforma (no bugs de este repo):

- **Sin basemap** en los mapas geo — Lakeview's `custom-vega-viz` solo soporta specs Vega-Lite, no Vega crudo (necesario para basemaps con proyección mercator).
- **Sin controles `bind` (sliders)** — Lakeview no renderiza los controles interactivos `bind: scales`/`bind` de Vega-Lite pese a aceptar el spec sin error.

## 4. Referencia rápida — todos los comandos

| Comando | Flujo | Uso |
|---|---|---|
| `/report` | A | `/report CIRCUITO [fecha_inicio fecha_fin]` |
| `/reporte-lote` | A | `/reporte-lote grupo=alta` |
| `/informe-gerencial` | A | `/informe-gerencial grupo=media` |
| `/agrupamiento-circuitos` | A | `/agrupamiento-circuitos` |
| `/limpiar-corridas` | A | `/limpiar-corridas` |
| `/deploy-databricks-dashboard` | B | pide nombre + URL del workspace |
| `/subir-datos-databricks` | B | pide URL del workspace |
| `/subir-notebooks-databricks` | B | pide URL del workspace |
| `/subir-a-databricks` | B | pide URL del workspace |

## 5. Más detalle

- [`notebooks-project-flow.md`](./notebooks-project-flow.md) — detalle celda por celda de los 9 notebooks.
- [`agents-guide.md`](./agents-guide.md) — arquitectura de 4 capas del framework de agentes (Skills vs. roles vs. playbooks de prompt).
- [`report-runtime-contract.md`](./report-runtime-contract.md) — contrato de invocación de `/report` entre runtimes.
- [`flujo-detallado.html`](./flujo-detallado.html) — este mismo documento en HTML.
- [`project-flow-review.html`](./project-flow-review.html) — misma información con diagramas Mermaid interactivos y el historial de correcciones en vivo.
- [`project-workflow.mmd`](./project-workflow.mmd) / [`report-family-workflow.mmd`](./report-family-workflow.mmd) — diagramas fuente de detalle (ingestión de datos → modelado ML → interpretación local → publicación; familia de comandos `/report`, respectivamente).
