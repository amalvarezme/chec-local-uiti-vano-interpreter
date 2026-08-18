# Flujo detallado del proyecto — CHEC UITI_VANO Interpreter

> Versión HTML: [`flujo-detallado.html`](./flujo-detallado.html) (mismo contenido). Actualizado 2026-08-18.
>
> Audiencia: ingeniería / mantenimiento del repo. Para una versión sin jerga técnica, ver [`flujo-resumen.md`](./flujo-resumen.md) / [`flujo-resumen.html`](./flujo-resumen.html).
>
> Este documento describe el flujo esencial del proyecto. La publicación de la página web de
> presentación queda fuera a propósito: es un canal interno de divulgación, no una pieza del flujo.
> Lo que queda fuera, y por qué, está inventariado en
> [`inventario-de-lo-suelto.md`](./inventario-de-lo-suelto.md).

## 1. Panorama — los tres pilares

Todo parte de una sola fuente de verdad — el CSV `data/Indicadores_vano_v3.csv`, un histórico de
eventos por vano — y se ramifica en **tres pilares**. No comparten runtime, no se llaman entre sí,
y cada uno se puede usar sin los otros dos:

| Pilar | Qué entrega | Quién lo usa | Dónde corre |
|---|---|---|---|
| **1 · IA descriptiva y predictiva** | Seis aplicaciones: cinco tableros de CriticidadCHEC (descriptivos) y el simulador *qué pasaría si* sobre el modelo MIL (predictivo) | Quien explora los datos con el ratón | macOS/Windows, sin servidor |
| **2 · Los comandos** | Captura de clima, reportes por circuito, informes gerenciales y la limpieza de corridas — con agentes LLM y sus arneses de validación | Quien necesita un documento redactado | Claude Code, local |
| **3 · La migración a Databricks** | Un solo comando que sube datos, publica las aplicaciones como Databricks Apps y deja el cuaderno del modelo en el Workspace | Quien publica para toda CHEC | Databricks, en la nube |

Los tres se tocan en un punto y solo uno: **el archivo del modelo**,
`data/models/mil_vano_ventana_v1.pt`. El cuaderno `05` lo escribe; el simulador del pilar 1 y el
pipeline de reportes del pilar 2 lo cargan en **solo lectura**, nunca lo reentrenan. Esa asimetría
es un invariante vigilado por pruebas (`tests/test_frozen_model_guard.py`), no una convención.

```
data/Indicadores_vano_v3.csv
   │
   ├─→ cuaderno 05 ──→ data/models/mil_vano_ventana_v1.pt  (se escribe UNA vez)
   │                        │
   │                        ├─→ PILAR 1 · simulador (solo lectura)
   │                        └─→ PILAR 2 · agente `inference` (solo lectura)
   │
   ├─→ PILAR 1 · los cinco tableros descriptivos
   ├─→ PILAR 2 · /clima, /report, /reporte-lote, /informe-gerencial, /limpiar-corridas
   └─→ PILAR 3 · /subir-a-databricks  (copia los tres a la nube)
```

---

# Pilar 1 — IA descriptiva y predictiva

Seis carpetas en `aplicaciones/`, para macOS y Windows, **sin servidor y sin conexión**. Cinco
tableros descriptivos, un menú que los gobierna, y un simulador que es lo único predictivo del
pilar.

## 2. El modelo MIL (cuaderno `05_mil_vano_ventana`)

Es el motor del lado predictivo. Vive en un cuaderno, produce un archivo, y ese archivo es todo lo
que el resto del proyecto ve de él.

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

Reentrenar corre **más rápido en CPU que en GPU**: medido sobre un pliegue real de 88.987 bolsas
en un M4 Max, la CPU con 2 hilos gana 6× a MPS y usa 3,4× menos memoria. El valor `auto` elige
justamente el peor de los dos.

El grafo experto de variables **no se lee de disco**: `construir_matriz_adyacencia_mgcecdl` lo
construye en código y el `.pt` lo guarda dentro, junto con las aristas preservadas. El modelo y su
grafo viajan juntos, que es lo que impide reconstruir uno con el otro desfasado.

## 3. Las seis aplicaciones

| Carpeta | Puerto | Qué abre | Módulo | Lado |
|---|---|---|---|---|
| `00_criticidad_chec/` | 8800 | **CriticidadCHEC**: el menú. Abre, vigila y cierra las otras cinco | — | — |
| `01_clima/` | 8801 | Nube por vano sobre el mapa, 6 variables, serie de doble eje y 6 violines | `chec_tableros.clima` | Descriptivo |
| `02_agrupamiento_vanos/` | 8802 | Agrupamiento de vanos por UITI acumulado y número de eventos | `chec_tableros.agrupamiento` | Descriptivo |
| `03_trayectorias_circuitos/` | 8803 | Trayectoria y agrupamiento de circuitos con ventana deslizante | `chec_tableros.trayectorias_circuitos` | Descriptivo |
| `04_trayectorias_vanos/` | 8804 | Lo mismo un nivel más abajo: agrupamiento y evolución por vano | `chec_tableros.trayectorias_vanos` | Descriptivo |
| `06_simulador/` | 8866 | Simulador de riesgo por vano: *qué pasaría si*, sobre el modelo MIL | `chec_tableros.simulador` | **Predictivo** |

Cada carpeta trae los mismos cuatro lanzadores: `instalar` (una vez, crea el entorno) e `iniciar`
(cada vez). En macOS hay además un `Iniciar.app` para el doble clic — un bundle de verdad y no un
`.command`, porque si el usuario tiene otra terminal instalada, LaunchServices se queda el
`.command` y no lo ejecuta.

Su comando es uno solo: [`/app-local-criticidadCHEC`](../.claude/commands/app-local-criticidadCHEC.md),
que abre el menú en el puerto 8800. **Los cinco tableros se abren desde su página**, no con comandos
propios: cada uno arranca como proceso hijo, en el puerto fijo que le da la tabla de ese archivo, y
el menú los vigila y los cierra. Hasta el 2026-08-17 cada tablero tenía además su propio comando
(`/app-local-clima` y los otros cuatro); seis comandos para una sola aplicación significaban seis
copias del mismo preflight separándose entre sí, y un usuario que tenía que saber cuál de los seis
quería antes de ver nada. El contrato que compartían —puerto fijo, comprobación de "ya está
corriendo", preflight, arranque en segundo plano— quedó absorbido en ese mismo archivo.

### 3.1 Por qué `01`-`04` son livianas y `06` no

No es estilo: es la diferencia entre describir y predecir.

- **`01`-`04` no necesitan Python en ejecución.** Sus módulos precomputan todo y entregan un
  HTML donde la interacción entera vive en JavaScript. La aplicación es un **constructor** (se
  corre una vez) y un **servidor estático** de biblioteca estándar. Los K-Means de `03` y `04` no
  son excepción: se ajustan al construir, y lo que viaja al navegador son coordenadas y etiquetas
  ya resueltas.
- **`06` necesita un kernel vivo**, porque cada "Simular" vuelve a llamar al modelo MIL — eso es
  lo que lo hace predictivo y no descriptivo. Todo su panel es `ipywidgets` y se sirve con
  **Voila** sobre un kernel real. Para no pagar el CSV de 540 MB en cada arranque, congela un
  **paquete** con lo que las celdas de arranque derivan; el arranque baja de 2.867 MB a 579 MB.

Corolario operativo: los cuatro estáticos aguantan casi cualquier cosa; al `06` solo lo mata
perder el kernel, y cuando lo pierde **no lo dice** — se queda mudo.

### 3.2 Reaccionan a los datos, no a la fecha

Las seis vigilan sus insumos por **huella** (sha1 de lo pequeño, tamaño+fecha de lo pesado) y se
reconstruyen solas cuando algo cambia: el CSV, los shapefiles, el modelo, `Variables_simular.xlsx`
o el propio módulo del tablero. Un `git checkout` mueve la fecha de todo sin cambiar nada, y por
eso lo pequeño se mira por contenido. El detalle está en
[`../aplicaciones/DATOS-Y-ACTUALIZACIONES.md`](../aplicaciones/DATOS-Y-ACTUALIZACIONES.md), y los
tiempos y la memoria medidos en
[`../aplicaciones/RENDIMIENTO-Y-REQUISITOS.md`](../aplicaciones/RENDIMIENTO-Y-REQUISITOS.md).

---

# Pilar 2 — Los comandos

Cinco comandos. Uno captura datos, tres redactan documentos con agentes LLM, y el quinto borra lo
que esos tres dejaron.

| Comando | Uso | Qué produce |
|---|---|---|
| `/clima` | `/clima` | Enriquece los datos con clima de Open-Meteo (3 compuertas interactivas) |
| `/report` | `/report CIRCUITO [fecha_inicio fecha_fin]` | El HTML de un circuito, 9 pasos |
| `/reporte-lote` | `/reporte-lote <grupo> [fecha_inicio fecha_fin]` | Un reporte por circuito de la banda |
| `/informe-gerencial` | `/informe-gerencial <grupo> [fecha_inicio fecha_fin]` | Un HTML gerencial cross-circuito sobre los representativos de la banda |
| `/limpiar-corridas` | `/limpiar-corridas` | Borra artefactos desechables de corridas previas (dry-run primero, confirmación explícita) |

`<grupo>` es una de las **cuatro bandas del ranking de circuitos** —
`bajo | medio | medio-alto | alto`— o `todos`. Cualquier otro valor es un error de uso rechazado
antes de tocar el dataset; en particular los cinco niveles del K-Means retirado
(`muy-alta`, `alta`, …) se rechazan **a propósito**, porque si no resolverían a una banda vacía sin
decir que el vocabulario cambió. La lista vive una sola vez, en
`batch_report_contract.GROUP_SLUGS`, y `informe_gerencial_contract` la reexporta: los dos comandos
no pueden separarse.

`reporte-lote` e `informe-gerencial` **nunca reimplementan** el razonamiento: reinvocan
`.claude/skills/report/SKILL.md` por referencia. Esa cita cruzada es lo que mantiene a la familia
sincronizada en vez de a la deriva.

## 4. `/clima` — la captura de datos

Enriquece las tablas del proyecto con clima horario de Open-Meteo. Es totalmente interactivo: tres
compuertas de decisión antes de tocar la red (qué ubicaciones, API gratuita o de pago, qué límites
de consumo) y después uno de dos modos — **A**, actualizar las columnas de clima de
`Indicadores_vano_v3`; **B**, consultar puntos por día o por rango sobre una tabla que el usuario
elige de `data/`.

El motor es `src/chec_local_interpreter/clima_engine.py` y la invocación canónica es
`.claude/skills/clima/assets/runbook.py`. **No toca ninguno de los agentes LLM**: es captura de
datos, no redacción. Lleva su propio limitador persistente de presupuesto diario y mensual, así que
una corrida interrumpida se reanuda sin volver a pagar lo ya traído.

## 5. Los agentes y su arnés

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

Sobre el arnés hay dos cosas aprendidas en corridas reales que conviene no repetir:

- **El sobre importa.** Un agente debe escribir `{"ok": true, "data": {…}}`, no el objeto pelado.
  Cuando el requisito no se enunciaba en el despacho, 4 de 14 agentes escribían el JSON sin
  envoltorio **y reportaban éxito**; enunciarlo llevó la conformidad a 36 de 36.
- **Los nombres de variable se expanden al RENDER, nunca al guardar.** El `.out.json` es lo que el
  `validate` del propio agente aceptó; reescribirlo lo separaría de su validación. Por eso un
  informe se puede regenerar desde corridas existentes y recoge el cambio sin relanzar agentes.

La arquitectura de cuatro capas (Skills vs. roles vs. playbooks de prompt) está en
[`agents-guide.md`](./agents-guide.md).

## 6. Las nueve etapas de `/report`

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

> **Lección aprendida — el anclaje de graphify.** El `--update` se encadena **desde la raíz del
> proyecto**, nunca acotado a `reports/vault`. El manifiesto guarda sus claves relativas a la raíz,
> así que escanear desde la carpeta estrecha las re-ancla contra ella, las resuelve a rutas que
> nunca existieron y graphify las reporta como borradas: 426 borrados fantasma sobre un grafo de
> 6.479 nodos. Eso es pérdida de datos, no gasto de tokens. Antes de encadenar se corre la guarda
> `python -m chec_local_interpreter.graphify_guarda`, que comprueba **dónde** ancla el manifiesto
> —no si los archivos existen— y solo se sigue si sale con código 0. La regla anterior ("abortar si
> algún borrado reportado no existe en disco") bloqueaba también los borrados legítimos, porque un
> borrado de verdad tampoco existe en disco: protegía el grafo congelándolo.

## 7. `/informe-gerencial` — la síntesis cross-circuito

Produce **un solo** HTML que sintetiza varios circuitos a la vez, en vez de uno por circuito. Vive
en `reports/informesgerenciales/`, su propia raíz.

- Con una banda (`alto`, `medio-alto`, …) toma los **12 circuitos con más vanos críticos** de esa
  banda. Sesgo conocido, y hay que decirlo al leer: los 12 quedan contra el borde superior, así que
  el informe describe la **cola peor** de la banda, no la banda.
- Con `todos` reparte por **cuota**: 5 de `Riesgo Alto`, 5 de `Riesgo Medio-Alto` y 2 de
  `Riesgo Medio`. El panorama de apertura, en cambio, mira **la flota entera** — todos los
  circuitos y todos los vanos— y solo después baja a los 12 representativos.
- El denominador de circuitos siempre es la **flota**, nunca la propia banda: "7 de 7" no dice
  nada, "7 de 208" sí.

## 8. `/limpiar-corridas` — la limpieza

Borra los artefactos desechables que dejan los tres comandos de reporte. Es irreversible, así que
el contrato es rígido: **dry-run siempre primero**, se muestra el resumen completo al usuario sin
truncar, se espera una confirmación explícita en el chat, y solo entonces se corre con
`--confirm "BORRAR TODO"` y exactamente los mismos filtros `--only`/`--skip` que el usuario aprobó.
Nunca se pasa `--confirm` de forma especulativa.

Ojo con un efecto de segundo orden: una nota de bóveda borrada aquí **no vuelve sola**. Se
reproyecta la próxima vez que ese circuito pase por `/report`.

## 9. Qué distingue una predicción de una medición

En el reporte y en el simulador conviven dos clases de número y nunca se mezclan en silencio: lo
que dice la base de datos (medido) y lo que dice el modelo (simulado). Donde se comparan —las
barras del simulador, el `±` del título— la diferencia se publica con el desfase del modelo en
la base de ese mismo vano, que es la única cantidad local y medible que hay.

Toda variable que ve un lector se escribe **`Nombre natural (CODIGO)`** —"densidad de descargas a
tierra (DDT)"— en prosa y en tablas. En figuras (barras, violines, nodos del grafo) se queda el
código pelado: no cabe el nombre y el eje ya dice de qué se habla.

---

# Pilar 3 — La migración automática a Databricks

## 10. Un solo comando, tres etapas

Es **un solo comando**, `/subir-a-databricks`, que reutiliza por referencia cruzada el contrato
compartido ([`_contrato-despliegue-databricks.md`](../.claude/commands/_contrato-despliegue-databricks.md)):
bitácora obligatoria, regla de no-abortar y resolución del catálogo en runtime.

Cada etapa le pregunta primero a Databricks qué hay ya y solo sube lo que falta — sin eso, una
corrida de rutina vuelve a mover 566 MB de CSV que ya estaban y redespliega una app sana, que en el
simulador son diez minutos de `pip install torch` a cambio de nada.

| Etapa | Qué verifica | Qué sube si falta |
|---|---|---|
| **Datos** | El Volume, el CSV con su tamaño real (~566 MB, no un puntero de LFS) y el juego completo de shapefiles con sus sidecars | `data/` entero, más `site/data/variables.json` (única excepción fuera de `data/`) |
| **Aplicaciones** | Que las dos apps existan, estén `ACTIVE`/`RUNNING`/`SUCCEEDED` y sirvan contenido al día | `criticidad-chec` (los cuatro tableros en cuatro rutas) y `simulador-vano` (Voila, kernel vivo) |
| **Cuaderno del modelo** | Que el cuaderno esté en el Workspace y no sea más viejo que su generador | `notebooks/05_mil_vano_ventana.ipynb`, como cuaderno y deliberadamente sin app |

El orden es el del pilar 1 al revés: primero los datos que todo necesita, después las aplicaciones
que los consumen, y de último el cuaderno del modelo, que es el único que no se publica como app.

Eran ocho comandos. Cuatro (`/app-vano-clima`, `/app-agrupamiento-vanos-circuitos`,
`/app-trayectorias-circuitos`, `/app-trayectorias-vanos`) publicaban un tablero cada uno parcheando
un `.ipynb` que ya no existe: ese código vive en `src/chec_tableros/`. Los otros cuatro
(`/subir-datos-databricks`, `/subir-notebooks-databricks`, `/app-criticidad-chec`,
`/app-simulador-vano`) seguían siendo correctos y se absorbieron el 2026-08-17, porque repartidos
en cuatro invocaciones dejaban cuatro reportes parciales y obligaban a recordar el orden.

El comando **se autorrepara**: crea el Volume si falta, configura el permiso de lectura de la app
declarando el Volume como recurso, y no aborta ante un muro de permisos —lo anota y sigue, para que
el reporte salga con la lista completa de lo que bloquea el despliegue.

## 11. Las dos reglas del contrato

- **Bitácora obligatoria.** Se abre *antes* de preguntarle nada al usuario, se anota cada paso
  numerado al terminarlo y siempre se cierra. Su ruta y su estado final son parte del reporte.
- **Nunca abortar.** Una restricción se registra y se rodea; el comando corre hasta el final. Es
  lo que hace que una corrida contra un workspace ajeno produzca la lista completa de permisos
  que faltan en vez de morir en el primero.

Y una tercera que se paga cara si se olvida: **el workspace se pregunta en cada corrida**, nunca se
deduce del perfil con sesión vigente. El catálogo, en cambio, se descubre en runtime. Equivocarse
de workspace no da error: sube todo, al sitio equivocado, en silencio.

## 12. Restricciones ya conocidas (D1–D10)

Si aparece una de estas, no se rediagnostica: está en el contrato con su rodeo.

- **D1** el catálogo `workspace` no existe y no se puede crear; **D2** el FUSE de `/Volumes`
  responde 403 mientras la Files API sí funciona; **D3/D4** `uc_securable` necesita `USE CATALOG` y
  el `GRANT` está denegado al asistente — solo el dueño del catálogo puede darlo.
- **D5 — cupo de apps: el workspace topa en 3**, y una app en `DELETING` sigue contando. Además, el
  `create` deja el stdout vacío cuando la app queda en `ERROR`.
- **D6** límites de subida: `--format JUPYTER` topa en 10 MB y para este conjunto no es un caso
  borde sino la norma, así que hay que limpiar `outputs` y `execution_count` de cada copia.
  `workspace import` tampoco crea carpetas padre.
- **D8** un cuaderno con `ipywidgets` no corre en Serverless: el simulador necesita cluster clásico.
- **D9 — el estado del workspace no es durable entre sesiones.** Un workspace verificado como
  completo un día apareció vacío al siguiente. Siempre verificar en vivo antes de asumir.
- **D10** `git push` puede fallar por la API de locks de LFS.

## 13. El stack Lakeview se retiró

El dashboard AI/BI y el job de tablas Delta que lo respaldaba ya no existen. Lakeview no ejecuta
Python ni JS arbitrario, así que nunca pudo mostrar el análisis real de los tableros (K-Means,
Voronoi, los mapas MapLibre). Las Databricks Apps sí, y son el único camino de publicación.

---

## 14. Los cuadernos

Queda **uno**: `notebooks/05_mil_vano_ventana.ipynb`, el modelo del pilar 1. Es también salida
generada de `scripts/generate_notebook_10.py`, así que editarlo a mano lo borra la próxima
regeneración.

Eran quince hasta el 2026-08-14. Se borraron nueve ese día: `07_relevancia_lote_por_vano` y
los ocho del pipeline MGCECDL original. Ninguno se ejecutaba ni se importaba desde ningún
sitio — solo los nombraba prosa. Están en el historial de git, y los artefactos que
produjeron (el grafo experto de `data/graphs/`) siguen en su sitio y siguen usándose; lo que ya no
está en el árbol es el código que los generó.

Los cinco restantes eran los tableros `uiti_vano` (`01`-`04` y `06`), y **eran la fuente de
las cinco aplicaciones**: `aplicaciones/_comun/cuaderno.py` leía el `.ipynb` y ejecutaba sus
celdas con `exec()`. Se migraron a `src/chec_tableros/` entre el 15 y el 16 de agosto de
2026, uno por rebanada y cada uno verificado contra un golden congelado antes de empezar.
`notebooks/base_apps/` y el ejecutor ya no existen; que nadie vuelva a ejecutar un `.ipynb`
lo fija `tests/test_ningun_modulo_ejecuta_un_ipynb.py`.

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

## 15. Referencia rápida — todos los comandos

| Comando | Pilar | Uso |
|---|---|---|
| `/app-local-criticidadCHEC` | 1 · IA descriptiva y predictiva | el menú en el puerto 8800; los cinco tableros se abren desde su página |
| `/clima` | 2 · Comandos | enriquecimiento Open-Meteo, 3 compuertas interactivas |
| `/report` | 2 · Comandos | `/report CIRCUITO [fecha_inicio fecha_fin]` |
| `/reporte-lote` | 2 · Comandos | `/reporte-lote <grupo> [fecha_inicio fecha_fin]` |
| `/informe-gerencial` | 2 · Comandos | `/informe-gerencial <grupo> [fecha_inicio fecha_fin]` |
| `/limpiar-corridas` | 2 · Comandos | dry-run y confirmación explícita |
| `/subir-a-databricks` | 3 · Databricks | datos → apps → cuaderno, verificando antes de subir cada uno; deja bitácora |

## 16. Más detalle

- [`agents-guide.md`](./agents-guide.md) — arquitectura de 4 capas del framework de agentes.
- [`report-runtime-contract.md`](./report-runtime-contract.md) — contrato de invocación de `/report` entre runtimes.
- [`mil-vano-ventana-estado-y-mejoras.md`](./mil-vano-ventana-estado-y-mejoras.md) — estado del modelo MIL y mejoras pendientes.
- [`REQUISITOS-MINIMOS.md`](./REQUISITOS-MINIMOS.md) — qué equipo hace falta, por pilar y medido.
- [`inventario-de-lo-suelto.md`](./inventario-de-lo-suelto.md) — qué archivos y funciones NO participan en ninguno de los tres pilares.
- [`../aplicaciones/README.md`](../aplicaciones/README.md) — las seis aplicaciones, con sus requisitos.
- [`flujo-detallado.html`](./flujo-detallado.html) — este mismo documento en HTML.
- Los diagramas del flujo end-to-end y de la familia `/report` viven en el `README.md`, en Mermaid
  y en línea.
