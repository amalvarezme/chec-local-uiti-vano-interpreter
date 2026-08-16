# 01 — Nube por vano y clima

Tablero de `src/chec_tableros/clima.py`, como aplicación local para macOS y
Windows: la nube por vano sobre el mapa, las 6 variables seleccionables, la serie de
tiempo de doble eje y los 6 violines, con los 208 circuitos dentro y el selector
cambiándolos en vivo.

## Uso

| macOS | Windows | qué hace |
|---|---|---|
| nada: `Iniciar.app` lo hace solo | `instalar.bat` (doble clic) | una sola vez: crea el entorno e instala las dependencias |
| **`Iniciar.app`** (doble clic) | **`iniciar.bat`** (doble clic) | construye si hace falta, sirve el tablero y abre el navegador |

> **A qué le doy doble clic:** en **macOS**, a `Iniciar.app`; en **Windows**, a
> `iniciar.bat`. Hacen lo mismo que el `abrir-en-terminal.command` de al lado, y la
> diferencia es que funcionan **siempre**: a un `.command` lo abre la aplicación que
> LaunchServices tenga atada a esa extensión, y eso lo fija cada máquina — con Ghostty
> instalado le toca Ghostty, que se declara *editor* de `.command`, y entonces el doble
> clic **no ejecuta nada**: abre el archivo en un editor. `Iniciar.app` no se puede
> desviar así: LaunchServices no lo abre con otra aplicación, lo **lanza**, y abre
> siempre una ventana nueva de Terminal que se cierra sola al cerrar el tablero. En
> Windows no hace falta nada de esto: un `.bat` lo ejecuta el intérprete de órdenes del
> sistema.
>
> `abrir-en-terminal.command` se conserva para lanzarlo a mano desde una terminal, y es
> el camino de Linux. Se llamaba `iniciar.command` y se renombró justo por esto: con ese
> nombre, y al lado de `Iniciar.app`, el doble clic caía ahí.

`Ctrl+C` en la ventana lo detiene.

Opciones de `iniciar`: `--no-abrir` (no abre el navegador), `--puerto N`,
`--reconstruir` (vuelve a ejecutar el cuaderno), `--verboso` (registra cada petición).

## Qué tarda y cuánto pesa

Medido en esta máquina:

| | |
|---|---|
| construcción (una vez) | **25,0 s** — 15,5 s de leer el CSV de 540 MB, 7,4 s los shapefiles |
| arranque posterior | **menos de 1 s** — el tablero ya es un documento estático |
| entorno virtual | 484 MB |
| tablero construido | 27,8 MB en disco |
| primera apertura | **6,37 MB** transferidos |
| aperturas siguientes | **17 KB** |

## Cómo está optimizado

El cuaderno produce un HTML de 27,8 MB con todo dentro. El constructor lo parte en
tres piezas y el servidor las entrega comprimidas desde disco:

| pieza | crudo | comprimido | caché |
|---|---|---|---|
| `index.html` | 0,06 MB | 17 KB | revalida con ETag |
| `plotly-3.7.0.<hash>.js` | 4,63 MB | 1,40 MB | `immutable`, un año |
| `datos.<hash>.json` | 23,12 MB | 4,96 MB | `immutable`, un año |

Tres efectos, todos verificados con `curl` contra el servidor real:

1. **La segunda apertura transfiere 17 KB.** Las dos piezas grandes llevan el hash de
   su contenido en el nombre, así que se sirven como `immutable` y el navegador ni
   siquiera pregunta por ellas. Si el cuaderno cambia, cambia el hash y cambia la URL.
2. **`plotly.js` se comparte con la aplicación 02.** Es el mismo archivo con el mismo
   hash: abrir una deja la otra ya cacheada. Por eso `requirements.txt` fija la
   versión exacta de plotly en vez de un mínimo.
3. **Los datos se leen con `JSON.parse`**, no como un literal de JavaScript dentro de
   un `<script>`.

Nada de esto tocó la lógica del tablero. El bloque original se conserva entero y solo
se envuelve en la carga del `.json`.

### Comprobado en un navegador real

Comparando el documento del cuaderno contra el empaquetado en Chrome: **16 trazas y
22.603 puntos en los dos**, los mismos 2 desplegables, 2 campos y 10 botones, los dos
reaccionan al cambiar de circuito, y los mismos avisos de JavaScript que ya emitía el
original (14 `Style is not done loading` de maplibre, propios de ejecutar sin tarjeta
gráfica).

## Advertencia

`index.html` **no funciona con doble clic**. Los datos se cargan aparte y el navegador
bloquea esa lectura sobre `file://`. Si alguien lo intenta, la página lo dice en un
recuadro rojo en vez de quedarse muda.

## Requisitos

Python 3.10+ y el repositorio con `data/Indicadores_vano_v3.csv` y `data/GEO/`
descargados (`git lfs pull`). Solo para **construir**: una vez construido, el tablero
no vuelve a tocar los datos.

---

# Cómo leer este tablero

> Rescatado de `notebooks/base_apps/01_uiti_vano_clima.ipynb` el 2026-08-15, cuando ese
> cuaderno se borró. El código del tablero vive en `src/chec_tableros/`; esto es lo
> único que el cuaderno tenía y que el módulo no podía heredar, porque no es código:
> es la explicación de qué se está mirando.

# Nube por vano -- todos los circuitos

Cuaderno hermano de `03_uiti_vano_trayectorias_circuitos.ipynb` y
`04_uiti_vano_trayectorias_vano.ipynb`, con el mismo esquema: todo se precomputa en
Python y un panel HTML+JS maneja la figura sin recalcular nada.

A diferencia de la version anterior de este cuaderno, aqui los ~208 circuitos viajan
TODOS al navegador (como en 03): el selector de **circuito** del panel cambia el
circuito activo EN VIVO -- reescribe geometria, UITI, nube y violines de las mismas 14
trazas para el circuito elegido, sin recargar la pagina ni volver a correr el cuaderno.
Ya no existe el aviso de "este cuaderno arma un circuito por vez" de la version previa.

El mapa colorea cada vano por su UITI diario, en cortes de cuartil fijos PARA ESE
CIRCUITO (mismo estilo que 03/04). Encima va una "nube" translucida: un unico trazo
Scattermap de marcadores, uno por vano con datos ese dia, cuya intensidad (alpha del
color) codifica el valor de la variable elegida. El `<select>` de variable del panel
ofrece **las 6**, en dos grupos:

- **Climaticas (por rezago horario)** -- precipitacion, temperatura, rafaga y velocidad
  del viento. El slider de **horas antes del evento** recorre sus 25 rezagos (0 a 24).
- **Estaticas del vano (sin rezago)** -- riesgo por vegetacion (`NR_T`) y descargas a
  tierra (`DDT`). Son atributos del vano, no series: el slider de hora se deshabilita
  mientras una de ellas este activa.

Un tercer slider elige el **dia** (solo fechas con eventos del circuito activo). Tanto el
hover como el click sobre un punto de la nube muestran el vano, la variable activa y su
valor con unidad EN LA HORA VIGENTE -- ese valor se reconstruye cada vez que se mueve el
slider de hora o se cambia de variable, nunca queda una foto vieja.

Debajo del mapa van **6 violines en 2 filas x 3 columnas**, las mismas 6 variables, para
los vano-eventos del dia elegido y sincronizados al circuito y dia activos. El eje y de
cada violin rotula su **unidad de medida**.

## Como leerlo

- **Cada circuito tiene su propio numero de dias con eventos**, entre 1 y 79 (mediana 14).
  La etiqueta del slider lo dice, y en los 12 circuitos que solo registran un dia el slider
  **se deshabilita**: no hay nada que recorrer, y la serie de tiempo dibuja ese unico punto.
  No es un fallo del tablero, es lo que hay en la base para ese circuito.
- El **circuito** se elige en vivo desde el panel: el `<select>` de circuito lista los
  ~208 disponibles y, al cambiarlo, reescribe geometria, UITI, nube y violines de las
  mismas 14 trazas para el circuito elegido -- sin recargar la pagina ni volver a correr
  el cuaderno. Los dias del slider tambien se actualizan al circuito activo.
- La **variable de la nube** tambien se elige en vivo, entre LAS 6 y sin volver a
  ejecutar Python. `VARIABLE_CLIMA` solo decide con cual arranca el panel. La nube sigue
  siendo LA MISMA traza -- cambiar de variable solo repinta sus puntos (color y hover),
  igual que mover el slider de hora. El `<select>` las separa en dos grupos porque se
  comportan distinto:
  - **Climaticas**: una serie de 25 rezagos por vano; el slider de hora las recorre.
  - **Estaticas del vano** (`NR_T`, `DDT`): un unico valor por vano. Viajan con largo 1
    en vez de repetir 25 veces el mismo numero (eso inflaria el JSON del panel ~50%), el
    JS las indexa con clamp y el slider de hora **se deshabilita** mientras esten
    activas, en vez de quedar mintiendo que mueve algo.
- El **mapa** colorea cada vano por su UITI acumulado del dia elegido, en 4 cuartiles con
  cortes fijos PARA EL CIRCUITO ACTIVO (mismo criterio que 03/04, sobre dias en vez
  de ventanas mensuales). Esa capa va al **doble de ancho** (7 px) y **opaca**, encima de la
  estructura negra de 1,5 px: el color que se ve en el mapa es exactamente el de la muestra
  que el panel imprime en su leyenda, no una mezcla con el fondo. Un vano **sin eventos ese dia, o que no aparece en la
  lista del dia, no recibe NADA de esta capa**: queda solo su linea negra de estructura.
- La **nube** es un unico trazo de puntos translucidos, uno por vano con datos ese dia,
  ubicado en su centroide, del MISMO color que el violin de esa variable. Tanto el hover
  como el panel de **click** muestran el vano, la variable activa y su valor con unidad
  en la hora vigente (o "atributo estatico del vano" si la variable no tiene rezago).
- El valor de cada circulo se codifica con el **COLOR**, no con la opacidad. La
  **opacidad es constante en 0.5** para todos los puntos (`NUBE_OPACIDAD`), lo justo para
  que la red se siga leyendo por debajo de circulos de 78 px que se solapan entre vanos
  vecinos.
  - El **tono base del violin** de cada variable y el de **su serie** en (1,3) salen de
    esa MISMA escala (`TONO_POR_VAR`, la rampa muestreada en 0.72), no de una paleta
    aparte: los tres elementos de una variable hablan el mismo idioma cromatico.
  - Cada variable tiene su **escala secuencial** (`ESCALA_POR_VAR`): Precipitacion
    `Blues`, Temperatura `OrRd`, Rafaga de viento `BuGn`, Velocidad del viento `BuGn`,
    Riesgo por vegetacion `Greens`, Descargas a tierra `Oranges`. Las dos variables de
    viento comparten escala a proposito (asi se pidieron), asi que en el mapa se ven
    iguales; se distinguen por el `<select>` y por el color de sus violines, que si son
    distintos.
  - `cmin`/`cmax` se fijan sobre el **dataset completo** (`RANGO_GLOBAL`, los 208
    circuitos), no sobre el circuito activo: un color significa el mismo valor aunque se
    cambie de circuito. Contrapartida asumida: un circuito con poca variacion en esa
    variable ocupa solo un tramo corto de su escala.
  - El color lo resuelve **Plotly**, no el JS: `marker.color` lleva los valores crudos y
    la escala viaja en el mismo `restyle`, para que un cambio de variable nunca pinte un
    instante los valores nuevos con la escala vieja.
  - La tira "Escala de la nube" del panel muestra 5 muestras de la escala activa, con la
    misma opacidad que el mapa para no prometer un color mas saturado del que se ve.
- El slider de **horas antes del evento** va de 0 (la hora del evento) a 24; mover solo
  este slider repinta la nube (color + hover) sin tocar el mapa ni los violines.
- La **grilla** es de **4 filas x 3 columnas**: el **mapa** ocupa un bloque 2x2 en las
  posiciones (1,1), (1,2), (2,1) y (2,2); en **(1,3)** va la serie de tiempo de doble eje;
  la posicion **(2,3) queda vacia** a proposito; y los **6 violines** llenan las tres
  columnas de las filas 3 y 4.
- La **serie de tiempo** de (1,3) cruza dos cosas sobre los dias con eventos del circuito:
  - Eje **izquierdo** (rojo oscuro, continuo): el **UITI total del circuito ese dia**, o
    sea la suma sobre todos sus vanos. Es un total POR DIA, no una suma corrida: sube y
    baja, y por eso se puede leer contra la otra serie.
  - Eje **derecho** (color de la variable activa, punteado): la **mediana diaria de la
    variable elegida**, calculada sobre los MISMOS valores por vano-evento que alimentan
    su violin. No depende del slider de hora a proposito -- una serie por dias no deberia
    saltar al mover un slider que no le compete. El rotulo, el color y la unidad de este
    eje cambian con el `<select>` de variable.
  - Al mover el slider de **dia**, el punto de ese dia se pinta al **triple** de tamaño
    (9 -> 27 px) en AMBAS series, para ubicar de un vistazo donde esta el resto del panel.
  - Los dias sin eventos no existen en el eje: la serie solo tiene los dias del circuito.
- Todo el texto -- panel y figura -- va al **doble** del tamaño previo, para leerse en
  pantalla grande y a pantalla completa en el navegador. Las cuatro constantes
  (`FUENTE_BASE`, `FUENTE_SUBTITULO`, `FUENTE_EJE_TITULO`, `FUENTE_TITULO`) son la unica
  fuente de verdad de la figura; el CSS del panel replica esos mismos valores.
- Los **violines** muestran, para el circuito y dia elegidos, la distribucion entre los
  vano-eventos de ese dia:
  - Fila 1 -- **Precipitacion** (mm), **Temperatura** (°C) y **Rafaga de viento**
    (km/h): cada evento aporta su propio promedio de 12h (`_0`..`_11`), no un promedio
    por vano.
  - Fila 2 -- **Velocidad del viento** (km/h, misma media de 12h), **Riesgo por
    vegetacion** `NR_T` (indice) y **Descargas a tierra** `DDT` (descargas/km²/año):
    estas dos ultimas son atributos ESTATICOS del vano, asi que cada evento aporta el
    valor del vano donde ocurrio -- la distribucion refleja que vanos fallaron ese dia,
    no una variacion temporal.
  - Cada panel tiene su propio eje y, rotulado con la **unidad de medida** de su
    variable, y se actualiza junto con el circuito y el dia.
