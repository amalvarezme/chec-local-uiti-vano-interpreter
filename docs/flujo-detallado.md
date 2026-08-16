# Flujo detallado del proyecto — CHEC UITI_VANO Interpreter

> Versión HTML: [`flujo-detallado.html`](./flujo-detallado.html) (mismo contenido). Actualizado 2026-08-13.
>
> Audiencia: ingeniería / mantenimiento del repo. Para una versión sin jerga técnica, ver [`flujo-resumen.md`](./flujo-resumen.md) / [`flujo-resumen.html`](./flujo-resumen.html).
>
> Este documento describe el flujo esencial del proyecto. La publicación de la página web de
> presentación queda fuera a propósito: es un canal interno de divulgación, no una pieza del flujo.

## 1. Panorama

Todo parte de una sola fuente de verdad — el CSV `data/Indicadores_vano_v3.csv`, un histórico de
eventos por vano — y se ramifica en **cuatro planos** que no comparten runtime:

| Plano | Qué es | Dónde corre |
|---|---|---|
| **El modelo MIL** | El motor predictivo: aprende sobre bolsas *vano × ventana* y estima el UITI acumulado | Cuaderno `05`, local o Kaggle |
| **Los agentes** | Cuatro roles LLM que leen contexto ya seleccionado y redactan JSON validado | Claude Code, local |
| **Los reportes** | La familia `/report`: convierte modelo + datos + PDFs expertos en un HTML por circuito | Local |
| **Las aplicaciones** | Seis tableros interactivos, en el escritorio o publicados como Databricks Apps | macOS/Windows, o Databricks |

Los planos se tocan en un punto y solo uno: **el archivo del modelo**,
`data/models/mil_vano_ventana_v1.pt`. El cuaderno `05` lo escribe; el pipeline de reportes y el
simulador lo cargan en **solo lectura**, nunca lo reentrenan. Esa asimetría es un invariante
vigilado por pruebas (`tests/test_frozen_model_guard.py`), no una convención.

## 2. El modelo MIL (cuaderno `05_mil_vano_ventana`)

### 2.1 Qué aprende

Multiple Instance Learning sobre **bolsas**: una bolsa es un vano dentro de una ventana de tiempo,
y sus instancias son los eventos que cayeron ahí. El modelo estima el **UITI acumulado** de la
bolsa y, en paralelo, su clase de criticidad. El número de eventos NO es una salida del modelo:
es contexto observado.

| | |
|---|---|
| Artefacto | `data/models/mil_vano_ventana_v1.pt` |
| Configuración | `fusion="film"`, `LAMBDA_CLASE=1.0`, `TEMPERATURA_CLASE=0.01`, 30 épocas |
| macro-F1 (CV agrupada, 62.114 bolsas) | 0,870982 |
| Referencia RandomForest estructural | 0,881231 |
| **Veredicto de la barra pre-registrada A1** | **NEGATIVO** (−1,02 puntos) |

El veredicto negativo está publicado a propósito: el modelo **ordena** bien (correlaciona 0,950
con el UITI observado sobre 599 bolsas) pero su **nivel** corre +34%, con error relativo mediano
del 39,4%. Por eso todo lo que lo consume publica su incertidumbre en vez de presentar la
predicción como una medición. El detalle completo está en
[`mil-vano-ventana-estado-y-mejoras.md`](./mil-vano-ventana-estado-y-mejoras.md).

### 2.2 Cómo se corre

El cuaderno arranca por defecto como **visor** (`EJECUCION="visualizacion"`): carga el modelo ya
entrenado y dibuja, en segundos. Reentrenar es explícito — `EJECUCION="entrenamiento"`, unos 40
minutos. Nadie reentrena por accidente al abrir el cuaderno.

El grafo experto de variables **no se lee de disco**: `construir_matriz_adyacencia_mgcecdl` lo
construye en código y el `.pt` lo guarda dentro, junto con las aristas preservadas. El modelo y su
grafo viajan juntos, que es lo que impide reconstruir uno con el otro desfasado.

Para experimentos con GPU sin tocar la máquina local está `/experimento-kaggle`: propone diagrama
de bloques y cuaderno, **exige aprobación explícita** y recién ahí ejecuta remoto vía la CLI de
Kaggle.

## 3. Los agentes

Cuatro roles, cada uno con su skill, su esquema JSON y su contrato de citación. Ninguno inventa
datos: reciben contexto **ya seleccionado** por código determinista y solo pueden citar lo que
viene en su sobre.

| Agente | Qué produce | Entrada |
|---|---|---|
| `historical` | El diagnóstico descriptivo del comportamiento del UITI_VANO en la ventana | `run_dir/historical.bc.json` |
| `inference` | La interpretación del modelo MIL: relevancia por vano hacia el UITI mínimo, diagnóstico del vano crítico con su plan, coherencia con el grafo | `run_dir/inference.bc.json` |
| `expert-alignment` | La comparación contra la discusión experta extraída de los PDFs | `run_dir/expert_alignment.bc.json` |
| `pdf-discussion-extraction` | Decide qué secciones de un PDF técnico se vuelven filas de la tabla de discusión | Un PDF por corrida |

Reglas duras, en `.claude/agents/rules/invariants.md`:

- **Cada agente valida su propio JSON contra un esquema antes de aceptarlo.** Un JSON inválido se
  reintenta o se guarda como fallo explícito; nunca se publica sin validar.
- **Ningún agente entrena ni reentrena nada.** Una prueba escanea los `.md` de roles y skills
  buscando vocabulario de entrenamiento, en español y en inglés, y falla si aparece.
- **`historical` e `inference` son independientes** y se despachan en paralelo obligatoriamente.
  Correrlos en serie no compra seguridad: no comparten estado.

La arquitectura de cuatro capas (Skills vs. roles vs. playbooks de prompt) está en
[`agents-guide.md`](./agents-guide.md).

## 4. El flujo de reportes

### 4.1 Los comandos

| Comando | Uso | Qué produce |
|---|---|---|
| `/report` | `/report CIRCUITO [fecha_inicio fecha_fin]` | El HTML de un circuito, 9 pasos |
| `/reporte-lote` | `/reporte-lote grupo=alta` | Un reporte por circuito del grupo + el scatter de agrupamiento |
| `/informe-gerencial` | `/informe-gerencial grupo=media` | Un HTML gerencial cross-circuito sobre los representativos del grupo |
| `/agrupamiento-circuitos` | `/agrupamiento-circuitos` | Solo el scatter de agrupamiento, sin reporte |
| `/clima` | `/clima` | Enriquece los datos con clima de Open-Meteo (3 compuertas interactivas) |
| `/limpiar-corridas` | `/limpiar-corridas` | Borra artefactos desechables de corridas previas (dry-run primero, confirmación explícita) |

`reporte-lote` e `informe-gerencial` **nunca reimplementan** el razonamiento: reinvocan
`.claude/skills/report/SKILL.md` por referencia. Esa cita cruzada es lo que mantiene a la familia
sincronizada en vez de a la deriva.

### 4.2 Las nueve etapas de `/report`

El orquestador es `src/chec_local_interpreter/report_pipeline.py`.

1. **Validar y confirmar.** Se rechaza una fecha suelta, se comprueba que el circuito exista y que
   la ventana tenga eventos — todo antes de crear el `run_dir`. Un circuito inexistente o una
   ventana vacía es una alerta y una parada, nunca una repregunta. Aquí va el **único** punto de
   confirmación del usuario en toda la corrida.
2. **`prepare`.** Escribe los tres sobres (`historical.bc.json`, `inference.bc.json`,
   `l1_state.json`) y arma la capa de inferencia MIL en solo lectura: carga el `.pt` y la caché de
   bolsas, y resuelve el catálogo de controles. Construirlo desde cero cuesta 3,40 s y 2.257 MB
   de pico —medido— para 18 perillas; la caché lo recarga en 0,80 s y 182 MB. Una caché corrupta o
   sin permiso de escritura **degrada** a "esta corrida lo paga completo", nunca a una corrida
   que falla.
   El reporte se ancla a la **ventana**: hasta tres por circuito, y cada una produce su propio
   escenario con la relevancia por vano, el diagnóstico del vano crítico (≤15) y la simulación de
   intervención. Un circuito sin bolsas en una ventana simplemente no produce escenario — un
   circuito tranquilo es un resultado real, no un fallo.
3. **`historical`** y 4. **`inference`**, en paralelo. Cada uno lee su sobre y escribe su
   `*.out.json`.
5. **`prepare_expert_alignment`** — cuando los dos anteriores terminan.
6. **`expert-alignment`** — compara contra la discusión experta en PDF.
7. **`render`** — el HTML del circuito.
8. **Reportar la ruta al usuario.** `/report` es local: no publica nada por su cuenta.
9. **Nota de vault + graphify** (alerta-y-continúa). La skill `vault-circuito` proyecta los tres
   JSON validados a `reports/vault/*.md` y encadena `graphify --update`. Si esto falla, el HTML del
   paso 7 ya existe y no se revierte.

> **Lección aprendida — aislamiento de graphify.** El `--update` queda acotado **siempre** al grafo
> propio de `reports/vault`, nunca al del proyecto. Viene de un incidente real: una actualización
> con alcance mal delimitado podó ~271 archivos no relacionados.

### 4.3 Qué distingue una predicción de una medición

En el reporte y en el simulador conviven dos clases de número y nunca se mezclan en silencio: lo
que dice la base de datos (medido) y lo que dice el modelo (simulado). Donde se comparan —las
barras del cuaderno `06`, el `±` del título— la diferencia se publica con el desfase del modelo en
la base de ese mismo vano, que es la única cantidad local y medible que hay.

## 5. Las aplicaciones locales

Seis carpetas en `aplicaciones/`, para macOS y Windows, **sin servidor y sin conexión**. Cinco
tableros y un menú que los gobierna.

| Carpeta | Puerto | Qué abre | Módulo |
|---|---|---|---|
| `00_criticidad_chec/` | 8800 | **CriticidadCHEC**: el menú. Abre, vigila y cierra las otras cinco | — |
| `01_clima/` | 8801 | Nube por vano sobre el mapa, 6 variables, serie de doble eje y 6 violines | `chec_tableros.clima` |
| `02_agrupamiento_vanos/` | 8802 | Agrupamiento de vanos por UITI acumulado y número de eventos | `chec_tableros.agrupamiento` |
| `03_trayectorias_circuitos/` | 8803 | Trayectoria y agrupamiento de circuitos con ventana deslizante | `chec_tableros.trayectorias_circuitos` |
| `04_trayectorias_vanos/` | 8804 | Lo mismo un nivel más abajo: agrupamiento y evolución por vano | `chec_tableros.trayectorias_vanos` |
| `06_simulador/` | 8866 | Simulador de riesgo por vano: *qué pasaría si*, sobre el modelo MIL | `chec_tableros.simulador` |

Cada carpeta trae los mismos cuatro lanzadores: `instalar` (una vez, crea el entorno) e `iniciar`
(cada vez). En macOS hay además un `Iniciar.app` para el doble clic — un bundle de verdad y no un
`.command`, porque si el usuario tiene otra terminal instalada, LaunchServices se queda el
`.command` y no lo ejecuta.

Sus comandos: `/app-local-criticidadCHEC`, `/app-local-clima`,
`/app-local-agrupamiento-circuitos`, `/app-local-trayectorias-circuitos`,
`/app-local-trayectorias-vanos`, `/app-local-simulador`. El contrato compartido —puerto fijo,
comprobación de "ya está corriendo", preflight, arranque en segundo plano— vive en
[`_contrato-apps-locales.md`](../.claude/commands/_contrato-apps-locales.md).

### 5.1 Por qué `01`-`04` son livianas y `06` no

No es estilo: es lo que cada tablero necesita.

- **`01`-`04` no necesitan Python en ejecución.** Sus cuadernos precomputan todo y entregan un
  HTML donde la interacción entera vive en JavaScript. La aplicación es un **constructor** (se
  corre una vez) y un **servidor estático** de biblioteca estándar. Los K-Means de `03` y `04` no
  son excepción: se ajustan al construir, y lo que viaja al navegador son coordenadas y etiquetas
  ya resueltas.
- **`06` necesita un kernel vivo.** Todo su panel es `ipywidgets` y cada "Simular" vuelve a llamar
  al modelo, así que se sirve con **Voila** sobre un kernel real. Para no pagar el CSV de 540 MB
  en cada arranque, congela un **paquete** con lo que las celdas de arranque derivan; el arranque
  baja de 2.867 MB a 579 MB.

### 5.2 Reaccionan a los datos, no a la fecha

Las seis vigilan sus insumos por **huella** (sha1 de lo pequeño, tamaño+fecha de lo pesado) y se
reconstruyen solas cuando algo cambia: el CSV, los shapefiles, el modelo, `Variables_simular.xlsx`
o el propio cuaderno. Un `git checkout` mueve la fecha de todo sin cambiar nada, y por eso lo
pequeño se mira por contenido. El detalle está en
[`../aplicaciones/DATOS-Y-ACTUALIZACIONES.md`](../aplicaciones/DATOS-Y-ACTUALIZACIONES.md).

## 6. La subida a Databricks

Tres comandos de sincronización y cinco de publicación, todos en `.claude/commands/`, todos
reutilizando por referencia cruzada el mismo contrato compartido
([`_contrato-despliegue-databricks.md`](../.claude/commands/_contrato-despliegue-databricks.md)):
bitácora obligatoria, regla de no-abortar y resolución del catálogo en runtime.

| Comando | Qué migra |
|---|---|
| `/subir-datos-databricks` | `data/` completo (más `site/data/variables.json`, única excepción) al Volume |
| `/subir-notebooks-databricks` | Los tres paquetes fuente (`chec_local_interpreter`, `chec_impacto`, `scripts`) y los 6 cuadernos que corren allá, como copias adaptadas |
| `/subir-a-databricks` | Orquesta a los dos anteriores, importa el cuaderno `05` y despliega las apps que quepan |
| `/app-vano-clima` | Publica el cuaderno `01` como Databricks App |
| `/app-agrupamiento-vanos-circuitos` | Publica el `02` |
| `/app-trayectorias-circuitos` | Publica el `03` |
| `/app-trayectorias-vanos` | Publica el `04` |
| `/app-simulador-vano` | Publica el `06` (Voila, kernel vivo) |

Los cinco comandos de app **se autorreparan**: si faltan datos en el Volume encadenan
`/subir-datos-databricks`, y configuran el permiso de lectura de la app sin intervención manual.
Preguntan solo el nombre de la app y la URL del workspace — el destino se pregunta **cada
corrida**, nunca se deduce del perfil con sesión vigente.

### 6.1 Dos reglas del contrato

- **Bitácora obligatoria.** Se abre *antes* de preguntarle nada al usuario, se anota cada paso
  numerado al terminarlo y siempre se cierra. Su ruta y su estado final son parte del reporte.
- **Nunca abortar.** Una restricción se registra y se rodea; el comando corre hasta el final. Es
  lo que hace que una corrida contra un workspace ajeno produzca la lista completa de permisos
  que faltan en vez de morir en el primero.

### 6.2 Restricciones ya conocidas (D1–D10)

Si aparece una de estas, no se rediagnostica: está en el contrato con su rodeo.

- **D1** el catálogo `workspace` no existe y no se puede crear; **D2** el FUSE de `/Volumes`
  responde 403 mientras la Files API sí funciona; **D3/D4** `uc_securable` necesita `USE CATALOG` y
  el `GRANT` está denegado al asistente — solo el dueño del catálogo puede darlo.
- **D5 — cupo de apps: el workspace topa en 3**, y una app en `DELETING` sigue contando.
- **D6** límites de subida: `--format JUPYTER` topa en 10 MB y para este conjunto no es un caso
  borde sino la norma (`01` pesa 81,43 MB con salidas), así que hay que limpiar `outputs` y
  `execution_count` de cada copia. `workspace import` tampoco crea carpetas padre.
- **D8** un cuaderno con `ipywidgets` no corre en Serverless: el `06` necesita cluster clásico.
- **D9 — el estado del workspace no es durable entre sesiones.** Un workspace verificado como
  completo un día apareció vacío al siguiente. Siempre verificar en vivo antes de asumir.
- **D10** `git push` puede fallar por la API de locks de LFS.

### 6.3 El stack Lakeview se retiró

El dashboard AI/BI y el job de tablas Delta que lo respaldaba ya no existen. Lakeview no ejecuta
Python ni JS arbitrario, así que nunca pudo mostrar el análisis real de los cuadernos (K-Means,
Voronoi, los mapas MapLibre). Las Databricks Apps sí, y son el único camino de publicación.

## 7. Los cuadernos

Queda **uno**: `notebooks/05_mil_vano_ventana.ipynb`, el modelo. Es también salida generada
de `scripts/generate_notebook_10.py`, así que editarlo a mano lo borra la próxima
regeneración.

Eran quince hasta el 2026-08-14. Se borraron nueve ese día: `07_relevancia_lote_por_vano` y
los ocho del pipeline MGCECDL original. Ninguno se ejecutaba ni se importaba desde ningún
sitio — solo los nombraba prosa. Están en el historial de git, y los artefactos que
produjeron (el clasificador congelado de `data/models/`, el grafo experto de `data/graphs/`)
siguen en su sitio y siguen usándose; lo que ya no está en el árbol es el código que los
generó.

Los cinco restantes eran los tableros `uiti_vano` (`01`-`04` y `06`), y **eran la fuente de
las cinco aplicaciones**: `aplicaciones/_comun/cuaderno.py` leía el `.ipynb` y ejecutaba sus
celdas con `exec()`. Se migraron a `src/chec_tableros/` entre el 15 y el 16 de agosto de
2026, uno por rebanada y cada uno verificado contra un golden congelado antes de empezar.
`notebooks/base_apps/` y el ejecutor ya no existen; que nadie vuelva a ejecutar un `.ipynb`
lo fija `tests/test_ningun_modulo_ejecuta_un_ipynb.py`.

La geometría KMeans era del `04`, y `05` y `06` la extraían de su salida guardada. Desde el
2026-08-15 vive versionada en `data/geometria_kmeans_014_v1.json`.

```
chec_tableros.clima                    panel climático (violines + nube de rezagos)
chec_tableros.agrupamiento             agrupamiento de circuitos y de vanos
chec_tableros.trayectorias_circuitos   trayectorias de circuito por ventanas + mapa
chec_tableros.trayectorias_vanos       idem a nivel de vano
   │
data/geometria_kmeans_014_v1.json      la geometría KMeans, versionada y verificada por sha1
   ├→ 05_mil_vano_ventana              el modelo MIL sobre bolsas vano × ventana
   └→ chec_tableros.simulador          explicabilidad + simulador, kernel vivo
```

La geometría KMeans **dejó de ser una dependencia entre cuadernos** el 2026-08-15. Era de `04`,
y `05` y `06` la extraían de su salida guardada: tres artefactos atados, y un checkout limpio
que no podía asignar clases. Ahora es `data/geometria_kmeans_014_v1.json`, versionada y
reproducible con `scripts/exportar_geometria.py`.
`chec_local_interpreter.ventanas_015.cargar_clases_criticidad` la lee de ahí y **verifica su
sha1**, de modo que mover los centroides falla ruidosamente en vez de derivar en silencio.

Ojo con la colisión de numeración: `02`-`06` significan cosas distintas en cada generación y ahora
comparten carpeta. Un número suelto se refiere siempre al grupo `uiti_vano`; los MGCECDL se nombran
con su archivo completo.

## 8. Referencia rápida — todos los comandos

| Comando | Plano | Uso |
|---|---|---|
| `/report` | Reportes | `/report CIRCUITO [fecha_inicio fecha_fin]` |
| `/reporte-lote` | Reportes | `/reporte-lote grupo=alta` |
| `/informe-gerencial` | Reportes | `/informe-gerencial grupo=media` |
| `/agrupamiento-circuitos` | Reportes | `/agrupamiento-circuitos` |
| `/clima` | Datos | enriquecimiento Open-Meteo |
| `/limpiar-corridas` | Mantenimiento | dry-run y confirmación explícita |
| `/experimento-kaggle` | Modelo | experimento remoto con compuerta de aprobación |
| `/app-local-criticidadCHEC` | Aplicaciones | el menú, puerto 8800 |
| `/app-local-clima` | Aplicaciones | tablero `01`, puerto 8801 |
| `/app-local-agrupamiento-circuitos` | Aplicaciones | tablero `02`, puerto 8802 |
| `/app-local-trayectorias-circuitos` | Aplicaciones | tablero `03`, puerto 8803 |
| `/app-local-trayectorias-vanos` | Aplicaciones | tablero `04`, puerto 8804 |
| `/app-local-simulador` | Aplicaciones | simulador `06` con Voila, puerto 8866 |
| `/subir-datos-databricks` | Databricks | pide la URL del workspace |
| `/subir-notebooks-databricks` | Databricks | pide la URL del workspace |
| `/subir-a-databricks` | Databricks | orquesta datos → cuaderno `05` → apps → bitácora |
| `/app-vano-clima` | Databricks | publica el `01` |
| `/app-agrupamiento-vanos-circuitos` | Databricks | publica el `02` |
| `/app-trayectorias-circuitos` | Databricks | publica el `03` |
| `/app-trayectorias-vanos` | Databricks | publica el `04` |
| `/app-simulador-vano` | Databricks | publica el `06` |

## 9. Más detalle

- [`agents-guide.md`](./agents-guide.md) — arquitectura de 4 capas del framework de agentes.
- [`report-runtime-contract.md`](./report-runtime-contract.md) — contrato de invocación de `/report` entre runtimes.
- [`mil-vano-ventana-estado-y-mejoras.md`](./mil-vano-ventana-estado-y-mejoras.md) — estado del modelo MIL y mejoras pendientes.
- [`../aplicaciones/README.md`](../aplicaciones/README.md) — las seis aplicaciones, con sus requisitos.
- [`flujo-detallado.html`](./flujo-detallado.html) — este mismo documento en HTML.
- Los diagramas del flujo end-to-end y de la familia `/report` viven en el `README.md`, en Mermaid
  y en línea.
