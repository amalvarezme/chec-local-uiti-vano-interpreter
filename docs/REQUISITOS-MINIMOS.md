# Requisitos mínimos: qué equipo hace falta para correr esto en local

Qué máquina se necesita, desglosado por las **tres partes** que se usan por separado:
las aplicaciones de CriticidadCHEC (los cuatro tableros y el simulador), el
reentrenamiento del cuaderno `mil_vano` y la generación de informes con agentes
(`/report`, `/reporte-lote`, `/informe-gerencial`).

Casi todo lo que sigue está **medido en este repositorio** los días 2026-08-13 y
2026-08-17, no estimado. Lo que no está medido se dice en la sección 9, para que nadie
lo dé por medido.

> **La máquina de referencia.** Apple M4 Max, 14 núcleos, 36 GB de RAM, disco SSD,
> macOS 26.5.2 (Darwin 25.5), Python 3.11.15, con `.venv` creado y los datos
> presentes. Cuando una cifra depende de la máquina —y varias dependen— se dice de qué
> depende.

> **Cómo leer una cifra de aquí.** Lo que no cambia entre máquinas es el **orden de
> magnitud** y **qué parte es la cara**. Un tiempo sobre disco de red se multiplica; un
> tiempo de dibujo lo manda el navegador; un tiempo de entrenamiento lo manda el
> núcleo, no el número de núcleos (sección 5.3, que es contraintuitiva y está medida).

---

## 1. La respuesta corta

| Si vas a usar…                            | RAM             | CPU               | Disco libre      | Red                        | GPU |
| ------------------------------------------ | --------------- | ----------------- | ---------------- | -------------------------- | --- |
| Solo los cuatro tableros estáticos        | **4 GB**  | 2 núcleos        | **3,5 GB** | instalar y`git lfs pull` | no  |
| Además el simulador                       | **8 GB**  | 4 núcleos        | **6 GB**   | instalar y`git lfs pull` | no  |
| Además reentrenar el cuaderno`mil_vano` | **8 GB**  | 2 núcleos bastan | **+3 GB**  | git-lfs, una vez           | no  |
| Además generar informes con agentes       | **8 GB**  | 4 núcleos        | **+1 GB**  | **permanente**       | no  |
| **Todo, con holgura**                | **16 GB** | 4–8 núcleos     | **20 GB**  | permanente                 | no  |

**Ninguna parte de este proyecto necesita GPU.** Ni una. En la única que podría usarse
—el reentrenamiento— la GPU del propio chip (MPS) resultó **6 veces más lenta** y pidió
**3,4 veces más memoria** que la CPU del mismo equipo. Está medido en la sección 5.3.

**Pantalla:** 1.280 × 800 como mínimo para los tableros. Por debajo siguen siendo
usables —no desbordan— pero las figuras se dibujan por debajo de su tamaño de diseño.

---

## 2. Las tres partes, y por qué se piden por separado

| Parte                | Qué corre**en tu máquina**                                                                                                      | Qué**no** corre en tu máquina                                                     |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Aplicaciones         | Los cuatro tableros: nada, son HTML ya construido. El simulador: el modelo MIL completo, en CPU                                         | —                                                                                        |
| Cuaderno`mil_vano` | En visualización, leer un artefacto de 691 KB. Al reentrenar,**todo**: 159.470 eventos, 111.233 bolsas, 30 épocas × 5 pliegues | —                                                                                        |
| Informes con agentes | La preparación de datos, las figuras y el HTML                                                                                         | **El modelo de lenguaje.** Corre en Anthropic; tu máquina prepara, envía y espera |

Esa última fila es la que más cambia el presupuesto de hardware, y se malinterpreta
seguido: **un informe no pide máquina, pide cuota de suscripción y conexión**. Mientras
los tres agentes piensan, el equipo está ocioso.

Y la primera fila explica por qué cuatro de las cinco aplicaciones casi no piden nada:
calculan todo por adelantado y el navegador solo filtra. La quinta —el simulador— corre
el modelo sobre lo que el usuario escriba, y no hay respuesta que precomputar para 26
variables sobre hasta 15 vanos.

---

## 3. Software: la lista completa, por parte

|               | Tableros 01–04               | Simulador 06                  | Cuaderno 05        | Informes                        |
| ------------- | ----------------------------- | ----------------------------- | ------------------ | ------------------------------- |
| Python        | 3.11+ (medido en 3.14.6)                         | 3.11+ (medido en 3.14.6)                         | 3.11+ (medido en 3.11.15)              | 3.11+ (medido en 3.11.15)                           |
| Entorno       | uno por app                   | el suyo                       | `.venv` raíz    | `.venv` raíz                 |
| Navegador     | cualquiera moderno            | cualquiera moderno            | —                 | —                              |
| Git LFS       | **sí, para construir** | **sí, para construir** | solo al reentrenar | **sí**                   |
| Claude Code   | no                            | no                            | no                 | **sí**, con suscripción |
| Google Chrome | no                            | no                            | no                 | solo para la suite de pruebas   |

**Python 3.11 es un piso real, no una preferencia.** `pandas>=3.0` y `numpy>=2.4` no
publican ruedas por debajo de 3.11. El rango está ejercitado en los dos extremos y no
supuesto: el entorno raíz corre en **3.11.15** y los seis de `aplicaciones/` en
**3.14.6**, que es el `python3` del sistema en la máquina de referencia.

**Ninguna dependencia pide compilador.** Las ruedas binarias grandes —`torch`,
`geopandas`, `pyarrow`, `scipy`— existen para macOS y para Windows.

Las listas viven en cuatro sitios y no se mezclan: `requirements.txt` (raíz: pruebas,
cuadernos, reentrenamiento e informes) y `aplicaciones/<app>/requirements.txt`, uno por
aplicación. El aislamiento es deliberado: el menú de CriticidadCHEC pesa 15 MB porque no
importa a nadie; si importara a sus cinco hijas necesitaría la unión de sus listas
—`torch` incluido— solo para abrir un menú.

---

## 4. Parte 1 — Las aplicaciones de CriticidadCHEC

Los tiempos completos están en
[`aplicaciones/RENDIMIENTO-Y-REQUISITOS.md`](../aplicaciones/RENDIMIENTO-Y-REQUISITOS.md).
Aquí va solo lo que decide **qué equipo comprar**.

### 4.1 Disco

Cada aplicación instala **solo sus dependencias**, en su propio `.venv`. No comparten.
Medido hoy sobre los entornos reales:

| Aplicación                  | Entorno             | Tablero construido           |
| ---------------------------- | ------------------- | ---------------------------- |
| 00 Menú                     | 15 MB               | —                           |
| 01 Clima                     | 484 MB              | 35,8 MB                      |
| 02 Agrupamiento              | 530 MB              | 8,2 MB                       |
| 03 Trayectorias de circuitos | 633 MB              | 14,2 MB                      |
| 04 Trayectorias de vanos     | 633 MB              | 14,9 MB                      |
| 06 Simulador                 | **1,6 GB**; 1,4 GB en instalación nueva    | 96 MB (paquete precalculado) |
|                              | **≈ 3,9 GB** | **≈ 166 MB**          |

Con las cuatro estáticas y el menú: **2,4 GB**. Con las cinco: **4,1 GB**.

**Por qué el simulador tiene dos cifras.** El entorno que existe hoy pesa 1,6 GB; una
instalación limpia pesa 1,4. La diferencia son 186 MB de `shap` y `optuna` con lo que
arrastran —`llvmlite` 125 MB, `numba` 30 MB, `sqlalchemy` 19 MB, `alembic` 2,6 MB—, que
se declaraban por una justificación que había dejado de ser cierta. Se midió
construyendo el tablero de verdad: ninguno de los dos entra en `sys.modules`. Quitarlos
de la lista no desinstala nada de lo ya instalado, así que el ahorro solo se ve al
instalar de nuevo.

**Falta un sumando que se olvida.** Un tablero se construye una vez, y para construirlo
hacen falta los datos: `data/Indicadores_vano_v3.csv` (540 MB) y `data/GEO/` (180 MB),
que **viajan por git-lfs**. Sin `git lfs pull` el clon trae punteros de texto y la
construcción falla. Servir el tablero ya construido no los vuelve a necesitar, pero
borrarlos deja al usuario sin poder reconstruir. Por eso la tabla de la sección 1 pide
3,5 GB y no 2,4.

### 4.2 Memoria

| Escenario                                            | RAM             |
| ---------------------------------------------------- | --------------- |
| Un tablero estático a la vez                        | **4 GB**  |
| Los cuatro abiertos a la vez                         | **8 GB**  |
| Con el simulador, una sesión                        | **8 GB**  |
| Con el simulador, varias pestañas o varias personas | **16 GB** |

El momento más exigente de las estáticas es la **construcción** del tablero 01 (pico de
1.401 MB), y ocurre una sola vez. El simulador pide del orden de **1 GB por pestaña de
navegador abierta**: Voila le da a cada una su propio kernel, y una pestaña olvidada
retiene el suyo.

### 4.3 CPU

Cuatro núcleos bastan. El único punto donde se notan más es el botón **«Simular»**, que
corre el modelo en CPU a propósito (`device="cpu"` explícito en
`src/chec_tableros/simulador/derivacion.py`, con su comentario). El tiempo de ese clic
no está medido: depende de cuántos vanos y cuántas variables se muevan.

---

## 5. Parte 2 — El cuaderno `mil_vano` (05)

Este cuaderno tiene **dos modos que piden máquinas distintas**, y confundirlos es el
error caro. Lo elige una sola variable en su celda de parámetros:

```python
EJECUCION = "visualizacion"   # por defecto: NO entrena
EJECUCION = "entrenamiento"   # reentrena de cero y SOBREESCRIBE el artefacto
```

### 5.1 Modo visualización — el caso normal

**Medido el 2026-08-17**, corriendo el cuaderno entero con `nbconvert --execute`:

|                         |                                                          |
| ----------------------- | -------------------------------------------------------- |
| Tiempo de punta a punta | **4,7 s**                                          |
| Pico de memoria         | **601 MB**                                         |
| Qué lee                | `data/models/mil_vano_ventana_v1.pt`, **691 KB** |
| Qué escribe            | nada                                                     |

No necesita el CSV, ni `data/derived/`, ni haber corrido ningún otro cuaderno. Todo lo
que el visor muestra viaja dentro del `.pt`: pesos, nombres de las 80 variables,
partición en modalidades, el grafo experto de 64 aristas, la geometría KMeans de 01.4 y
el desglose de desempeño por clase.

**Con 4 GB de RAM alcanza de sobra.**

### 5.2 Modo entrenamiento — lo que de verdad pide máquina

Lo que se reentrena, en números medidos sobre la base actual:

|                                     |                               |
| ----------------------------------- | ----------------------------- |
| Filas de evento en el CSV           | 159.470 (540 MB, por git-lfs) |
| Circuitos                           | 208                           |
| Bolsas`(circuito, vano, ventana)` | **111.233**             |
| Instancias                          | **288.632**             |
| Variables de instancia              | 80                            |
| Parámetros aprendibles             | **150.926**             |
| Validación cruzada                 | 5 pliegues × 30 épocas      |

El costo se reparte así (medido, CPU, 4 hilos):

| Etapa                                              | Tiempo  | Pico de memoria acumulado |
| -------------------------------------------------- | ------- | ------------------------- |
| Importaciones (`torch`, `pandas`, `sklearn`) | 1,8 s   | 400 MB                    |
| Leer el CSV y preprocesar                          | 2,1 s   | 2.411 MB                  |
| Matriz de instancias                               | 0,03 s  | 2.527 MB                  |
| Construir las 111.233 bolsas                       | 6,7 s   | 2.983 MB                  |
| Armar modelo y pérdida                            | 0,2 s   | 3.216 MB                  |
| **Entrenar**                                 | ver 5.3 | **3.288 MB**        |

**El pico de memoria lo fija la preparación de datos, no el entrenamiento.** Leer el
CSV cuesta 2,4 GB y de ahí ya casi no sube: el modelo es diminuto (150.926 parámetros) y
la disposición CSR no rellena nada.

### 5.3 CPU contra GPU, y cuántos núcleos: lo medido, y es al revés

El cuaderno resuelve el dispositivo con `resolve_training_device("auto")`: CUDA si la
hay, si no MPS, si no CPU. Y solo cuando cae en CPU imprime este aviso:

> `AVISO: se entrenara en CPU. Con mode='full' esto puede tardar horas.`

Las dos mitades de eso resultaron equivocadas al medirlas, y en direcciones opuestas:

- En un Mac con Apple Silicon `auto` elige **MPS** y **no avisa nada**. Es el camino
  lento, y se toma en silencio.
- En una máquina sin GPU —el caso típico en Windows— sí sale el aviso, y anuncia
  «horas» para el camino que resultó ser **el más rápido de todos**: 8 a 14 minutos.

Medido sobre un pliegue real de 88.987 bolsas: se cronometran 3 épocas y se proyecta la
validación cruzada completa (30 épocas × 5 pliegues).

| Dispositivo                                     | s por época y pliegue | Proyección completa | Pico de memoria     |
| ----------------------------------------------- | ---------------------- | -------------------- | ------------------- |
| CPU, 2 hilos                                    | **3,28**         | **8,2 min**    | 3.293 MB            |
| CPU, 4 hilos                                    | 3,61                   | 9,0 min              | 3.288 MB            |
| CPU, 8 hilos                                    | 4,60                   | 11,5 min             | 3.275 MB            |
| CPU, 14 hilos (todos, por defecto)              | 5,51                   | 13,8 min             | 3.267 MB            |
| **MPS (lo que elige `auto` en un Mac)** | **19,63**        | **49,1 min**   | **11.234 MB** |

Dos lecturas, y ninguna es la esperable:

- **La GPU del propio chip es 6 veces más lenta y pide 3,4 veces más memoria.** El
  modelo es demasiado pequeño para amortizar el viaje de cada lote a la GPU: lo que se
  gana en cómputo se pierde en transferencia. Como en un Mac es lo que `auto` elige,
  conviene salirse a mano — `DEVICE = torch.device("cpu")` justo después de la celda que
  lo resuelve.
- **Más núcleos empeoran el tiempo.** De 2 a 14 hilos el entrenamiento se pone 68 % más
  lento, monótonamente. Con 150.926 parámetros y lotes de 256 bolsas, coordinar hilos
  cuesta más que el trabajo que reparten.

**Consecuencia para elegir equipo: un portátil de 2 o 4 núcleos y 8 GB reentrena este
modelo en unos 10 minutos.** No hace falta una estación de trabajo, y una GPU no compra
nada aquí.

> **La honestidad de esta tabla.** Todos los tiempos son de los núcleos de un M4 Max.
> Que **más** núcleos no ayuden está medido; que un núcleo más lento tarde lo mismo
> **no** lo está. En un portátil de hace cinco años espere el mismo orden de magnitud
> —decenas de minutos, no horas— pero no la misma cifra.

### 5.4 Lo que el reentrenamiento pide además

- **El CSV de 540 MB por git-lfs.** En visualización no hace falta; al reentrenar sí.
- **`data/derived/`**, que no está versionado: el cache de bolsas ocupa **199 MB**.
- **Sobreescribe `data/models/mil_vano_ventana_v1.pt`**, que es el artefacto que
  consumen el simulador, el informe y las aplicaciones. No es una corrida inocua.
- **La proyección de costo es una compuerta, no un aviso.** El cuaderno cronometra un
  pliegue real y, si la proyección supera `COST_CEILING_SECONDS`, **no lanza** la
  validación cruzada completa.

Presupuesto de disco del reentrenamiento: **540 MB** (CSV) + **199 MB** (bolsas) +
**1,9 GB** (`.venv` raíz) ≈ **2,7 GB**.

---

## 6. Parte 3 — Los informes con agentes

`/report` (un circuito), `/reporte-lote` (un grupo de criticidad o la flota) e
`/informe-gerencial` (síntesis entre circuitos).

### 6.1 Lo que pide, y lo que no

**El modelo de lenguaje no corre aquí.** Corre en Anthropic. Lo que corre en la máquina
es el camino determinista —preparar datos, dibujar figuras, armar el HTML— y ese camino
está medido (`.claude/skills/report/SKILL.md`), sobre `VBO23L15`:

| Etapa determinista                                                     | Tiempo           | Pico de memoria    |
| ---------------------------------------------------------------------- | ---------------- | ------------------ |
| `prepare` (modelo + catálogo + 3 ventanas + figuras + mapas)        | 30,2 s           | 1.467 MB           |
| `prepare_expert_alignment`                                           | 0,1 s            | —                 |
| `render` (ranking + secciones por ventana + un mapa GEO por ventana) | 4,8 s            | 1.475 MB           |
| **Total**                                                        | **35,0 s** | **1.475 MB** |

O sea: **1,5 GB de pico y medio minuto de CPU**. El resto del tiempo la máquina espera.

### 6.2 Lo que cuesta de verdad: tiempo de agente y cuota

Medido sobre la corrida real de `DON23L14` del 2026-08-17 (los artefactos siguen en
`reports/reportescircuitos/runs/`):

| Agente               | Duración registrada | Tokens            |
| -------------------- | -------------------- | ----------------- |
| `historical`       | 272,9 s              | 84.414            |
| `inference`        | 499,0 s              | 126.555           |
| `expert-alignment` | 293,4 s              | 107.791           |
| **Total**      | **17,8 min**   | **318.760** |

Reloj de pared de la corrida completa, de la primera escritura a la última: **≈ 15 min**.
Es **menos** que la suma de las tres duraciones, así que esas duraciones no son intervalos
disjuntos —incluyen reintentos de validación y solapes—; se reportan tal como el propio
pipeline las registró, no reconciliadas a la fuerza.

Salida de una corrida: **5,4 MB** de HTML y **2,8 MB** de artefactos JSON y figuras.

**El límite que se toca primero no es el hardware: es la cuota de la suscripción.** Un
circuito son ~319.000 tokens. De ahí sale todo lo demás:

| Comando                       | Circuitos            | Tokens aproximados                                                         | Disco      |
| ----------------------------- | -------------------- | -------------------------------------------------------------------------- | ---------- |
| `/report`                   | 1                    | ~319 k                                                                     | ~8 MB      |
| `/reporte-lote` de un grupo | los del grupo        | ~319 k × n                                                                | ~8 MB × n |
| `/informe-gerencial`        | hasta 12 muestreados | ~319 k × los que**falten**; los que ya tengan corrida no se repiten | ~8 MB × n |

`/informe-gerencial` muestrea un grupo a sus **12 circuitos más representativos** y
reutiliza las corridas previas: si las doce ya existen, su costo de agente es casi todo
el de la síntesis entre circuitos. Si no existe ninguna, son doce `/report`.

### 6.3 Hardware y software para esta parte

|              |                                                                                                                                                                            |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RAM          | **8 GB** (el pico determinista es de 1,5 GB, pero convive con navegador y editor)                                                                                    |
| CPU          | 4 núcleos; no es el cuello de botella                                                                                                                                     |
| Disco        | el`.venv` raíz (1,9 GB) + los datos + ~8 MB por circuito informado                                                                                                      |
| Red          | **permanente durante toda la corrida**: cada turno de agente es una ida y vuelta a Anthropic. Qué pasa exactamente si se corta a mitad de un turno no está probado |
| Node.js      | **no hace falta.** En la máquina de referencia `claude` es un binario nativo bajo `~/.local/share/claude/versions/`, no un paquete de npm                       |
| Claude Code  | v2.1.234 en la máquina de referencia                                                                                                                                      |
| Suscripción | una cuenta con acceso a los modelos; la cuota es el límite real                                                                                                           |

---

## 7. macOS y Windows, lado a lado

|                          | macOS                                         | Windows                                                                |
| ------------------------ | --------------------------------------------- | ---------------------------------------------------------------------- |
| Python                   | 3.11 o superior                               | 3.11 o superior (`py -3`)                                            |
| Arranque de las apps     | doble clic en`Iniciar.app`                  | doble clic en`iniciar.bat`                                           |
| Instalación de las apps | `instalar-en-terminal.command`              | `instalar.bat`                                                       |
| Rueda de`torch`        | trae MPS (y conviene no usarla, sección 5.3) | `win_amd64`, **116 MB, solo CPU**                              |
| `torch` con CUDA       | no aplica                                     | no sale de PyPI:`--index-url https://download.pytorch.org/whl/cu124` |
| Compilador               | no hace falta                                 | no hace falta                                                          |
| RAM y disco              | iguales                                       | iguales                                                                |

**No hay ningún paquete exclusivo de un sistema**, y por eso `requirements.txt` es uno
solo y no lleva marcadores de entorno. Se verificó paquete por paquete.

**Lo que sí es distinto de verdad son tres comportamientos del sistema operativo**, los
tres corregidos tras fallar en una máquina real el 2026-08-13: `signal.SIGKILL` no
existe en Windows, `SO_REUSEADDR` significa lo contrario, y los `.bat` necesitan finales
de línea CRLF. El detalle y el guardián que falta están en
[`aplicaciones/PROBAR-EN-WINDOWS.md`](../aplicaciones/PROBAR-EN-WINDOWS.md).

Un cuarto punto, de criterio: el texto que las aplicaciones escriben en la **terminal**
va sin tildes, porque la consola de Windows no siempre está en UTF-8 y una tilde rota
aparece justo en el mensaje de error que hay que leer. Lo que va al **navegador** sí las
lleva.

---

## 8. El equipo mínimo, junto

Sumando las tres partes sobre la misma máquina, sin usarlas a la vez:

|             | Mínimo                                             | Recomendado                                   |
| ----------- | --------------------------------------------------- | --------------------------------------------- |
| RAM         | **8 GB**                                      | **16 GB**                               |
| CPU         | 4 núcleos                                          | 4–8 núcleos; más no ayuda al entrenamiento |
| GPU         | ninguna                                             | ninguna                                       |
| Disco libre | **12 GB**                                     | **20 GB**                               |
| Pantalla    | 1.280 × 800                                        | 1.920 × 1.080                                |
| Sistema     | el que soporte Python 3.11 y las ruedas de`torch` | igual                                         |
| Red         | para instalar y para los informes                   | igual                                         |

De dónde salen los 12 GB, medido hoy:

|                                                   |                    |
| ------------------------------------------------- | ------------------ |
| Entornos de las seis aplicaciones                 | 3,9 GB             |
| `.venv` raíz                                   | 1,9 GB             |
| Datos (`data/`)                                 | 913 MB             |
| Repositorio con su historia (`.git`)            | 1,3 GB             |
| Tableros construidos y paquete del simulador      | 166 MB             |
| Derivados del reentrenamiento (`data/derived/`) | 191 MB             |
| Informes generados                                | ~8 MB por circuito |
| **Ocupación real hoy**                     | **8,5 GB**   |

Los 8,5 GB son el `du` del checkout completo, así que incluyen además cosas que no
están en la lista y que no todo el mundo necesita: `node_modules/` del sitio (148 MB),
los informes ya generados (84 MB) y el grafo de conocimiento (38 MB).

Los 20 GB recomendados son esos 8,5 más holgura para informes, derivados y una
actualización de entornos sin borrar la anterior.

---

## 9. Lo que esta página NO cubre

Se dice para que nadie lo dé por medido:

- **Windows no está cronometrado.** Todos los tiempos son de macOS sobre Apple Silicon.
  El orden de magnitud debería ser el mismo; la creación de los entornos es
  notablemente más lenta allí y no se ha medido.
- **No se probó ninguna máquina lenta.** La escala por número de hilos está medida
  (sección 5.3); la escala por velocidad de núcleo, no. Todo salió de un M4 Max.
- **La primera instalación no está cronometrada.** Crear los seis entornos descarga del
  orden de 3,9 GB: el tiempo lo manda la red.
- **No se midió una GPU NVIDIA.** La comparación CPU/GPU de la sección 5.3 es contra
  MPS de Apple. Una NVIDIA de escritorio podría ganarle a la CPU; con un modelo de
  150.926 parámetros no es evidente que lo haga, y no se probó.
- **El tiempo de un clic en «Simular»** no está medido: el espacio de selecciones es
  demasiado grande para una cifra única.
- **La proyección del reentrenamiento es una proyección.** Se cronometraron 3 épocas de
  1 pliegue y se multiplicó por 30 × 5. No incluye el ajuste final sobre todas las
  bolsas ni las líneas base, así que la corrida completa es algo mayor que las cifras
  de la sección 5.3.
- **Las cuotas de las suscripciones no se documentan aquí** porque cambian. Lo que se
  documenta es el consumo medido —319.000 tokens por circuito— para poder compararlo
  contra el plan que cada quien tenga.
