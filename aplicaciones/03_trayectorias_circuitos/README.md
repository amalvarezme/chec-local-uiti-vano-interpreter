# 03 — Trayectoria y agrupamiento de circuitos

Tablero de `src/chec_tableros/trayectorias_circuitos.py`, como aplicación local
para macOS y Windows: la nube de circuitos agrupada por K-Means, la serie de doble eje
con el punto de la ventana activa a triple tamaño, y el mapa de circuitos — todo
gobernado por una ventana deslizante que reordena las opacidades en vivo.

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

`Ctrl+C` en la ventana lo detiene, y el botón **Cerrar** de arriba a la derecha
hace lo mismo desde el navegador.

Opciones de `iniciar`: `--no-abrir` (no abre el navegador), `--puerto N`,
`--reconstruir` (vuelve a ejecutar el cuaderno), `--verboso` (registra cada petición).

## Qué tarda y cuánto pesa

Medido en esta máquina:

| | |
|---|---|
| construcción (una vez) | **71,0 s** — de los cuales 58,7 s son la celda 2, que lee el CSV de 540 MB |
| arranque posterior | **menos de 1 s** — el tablero ya es un documento estático |
| entorno virtual | 633 MB |
| tablero construido | 10,5 MB en disco |
| primera apertura | **3,05 MB** transferidos |
| aperturas siguientes | **18 KB** |

## Cómo está optimizado

El cuaderno produce un HTML de 10,5 MB con todo dentro. El constructor lo parte en tres
piezas y el servidor las entrega comprimidas desde disco:

| pieza | crudo | comprimido | caché |
|---|---|---|---|
| `index.html` | 0,07 MB | 18 KB | revalida con ETag |
| `plotly-3.7.0.<hash>.js` | 4,63 MB | 1,40 MB | `immutable`, un año |
| `datos.<hash>.json` | 5,77 MB | 1,64 MB | `immutable`, un año |

**`plotly.js` es literalmente el mismo archivo que sirven 01, 02 y 04**: mismo nombre,
mismo hash `8ef4c6ab13`, verificado. Abrir cualquiera de las otras deja ésta con 1,40 MB
ya en caché, y la primera apertura baja de 3,05 MB a 1,65 MB. Eso es exactamente lo que
compra fijar `plotly==6.9.0` en vez de un mínimo, y por eso subirla hay que subirla en
las cuatro a la vez.

## Advertencia

`index.html` **no funciona con doble clic**. Los datos se cargan aparte y el navegador
bloquea esa lectura sobre `file://`. Si alguien lo intenta, la página lo dice en un
recuadro rojo en vez de quedarse muda.

## Requisitos

Python 3.10+ y el repositorio con `data/Indicadores_vano_v3.csv` y `data/GEO/`
descargados (`git lfs pull`). Solo para **construir**: una vez construido, el tablero no
vuelve a tocar los datos.

---

# Cómo leer este tablero

> Rescatado de `notebooks/base_apps/03_uiti_vano_trayectorias_circuitos.ipynb` el 2026-08-15, cuando ese
> cuaderno se borró. El código del tablero vive en `src/chec_tableros/`; esto es lo
> único que el cuaderno tenía y que el módulo no podía heredar, porque no es código:
> es la explicación de qué se está mirando.

# Trayectoria y agrupamiento de circuitos con ventana deslizante

Cuaderno hermano de `02_uiti_vano_kmeans.ipynb`, con el mismo esquema: todo se precomputa en
Python y un panel HTML+JS maneja la figura sin recalcular nada.

La unidad de analisis no es el circuito sino el par **circuito x ventana**. Cada mes aporta dos
ventanas -- el **mes calendario completo** y la **cruzada**, del dia 15 de ese mes al 15 del
siguiente -- y al ordenarlas por fecha de inicio quedan alternadas, con paso efectivo de medio
mes:

| ventana | periodo | que cubre |
|---|---|---|
| V1 | 2025-11-01 a 2025-11-30 | mes 1 completo |
| V2 | 2025-11-15 a 2025-12-14 | cruzada: mes 1 del 15 a fin + mes 2 del 1 al 14 |
| V3 | 2025-12-01 a 2025-12-31 | mes 2 completo |
| V4 | 2025-12-15 a 2026-01-14 | cruzada |
| V5 | 2026-01-01 a 2026-01-31 | mes 3 completo |
| ... | ... | ... |

Con seis meses de base salen **11 ventanas**. Para cada par circuito x ventana se acumula el UITI
(`UITI_VANO`) y se cuenta el numero de eventos dentro de esa ventana.

Sobre ese plano corre un **K-Means a 4 grupos**, igual que en `02`: la unidad que se agrupa es el
par circuito x ventana, de modo que un mismo circuito puede caer en grupos distintos segun la
ventana. El espacio en que se agrupa es **fijo**: eje x lineal, eje y en `log10` y escalador
`minmax`. No se elige desde el panel, asi que la particion es la misma en cada apertura del
tablero y dos lecturas de la misma ventana son comparables. Los grupos se nombran por el **ranking de la mediana del UITI acumulado**
(`Bajo`, `Medio`, `Medio-Alto`, `Alto`).

El panel trae:

- **Circuito**: al elegir uno, sus ventanas se resaltan y se **conectan con flechas** en orden
  cronologico, dibujando su trayectoria. El tooltip de cada punto indica el rango de fechas de su
  ventana y el grupo en que cayo.
- **Ventana**: slider sobre las once ventanas. Repinta el mapa y recalcula el reparto por grupo.

Ademas del mapa, el tablero muestra por grupo el **numero de vanos unicos** que lo componen y los
**violines** del UITI acumulado y del numero de eventos.

Al ejecutar, el mismo tablero se escribe como HTML autocontenido en `reports/paneles/` y se abre
en el navegador, donde usa todo el ancho de la pantalla. Se desactiva con
`ABRIR_EN_NAVEGADOR = False`.

> **Todas las ventanas consecutivas se solapan**, entre 14 y 17 dias segun el largo del mes. Ese
> solape hace que la trayectoria se mueva de forma suave: dos puntos vecinos comparten cerca de la
> mitad de sus datos, de modo que un salto grande entre ellos indica un evento fuerte concentrado
> en los dias que **no** comparten. Las 11 ventanas cubren el 100% de los eventos de la base.

> **Huecos.** Alrededor del 76% de los pares circuito x ventana registra algun evento. La **tabla**
> lleva la grilla completa, con ceros donde no hubo eventos, para que sea regular aguas abajo. El
> **mapa y el agrupamiento** usan solo las celdas con al menos un evento, porque un cero no tiene
> lugar en un eje logaritmico; cuando un circuito omite una ventana, la flecha une las dos
> presentes mas cercanas.

## Como leerlo

- Un punto es un par **circuito x ventana**, no un circuito: el mismo circuito aparece hasta 11
  veces, una por ventana, y **puede caer en grupos distintos** segun la ventana. Eso es lo que
  hace legible la trayectoria: se ve a un circuito pasar de `Bajo` a `Alto` y volver.
- Las ventanas **se solapan de a 14 a 17 dias** a proposito. Dos puntos consecutivos comparten
  cerca de la mitad de sus datos, de modo que la trayectoria se mueve de forma suave por
  construccion: un salto grande entre ventanas vecinas senala un evento fuerte concentrado en los
  dias que no comparten. La contracara es que los puntos consecutivos **no son independientes**.
- La secuencia alterna **mes calendario completo** y **cruzada** (del 15 al 15). Las de mes
  completo son las comparables entre si mes a mes; las cruzadas revelan si un pico quedo partido
  entre dos meses.
- Las **flechas** apuntan siempre de la ventana mas antigua a la mas reciente, y el color de cada
  marcador es el del grupo en que cayo esa ventana.
- El **conteo de vanos unicos** no es proporcional al de celdas: un grupo con pocas celdas puede
  contener circuitos grandes y sumar mas vanos que otro con muchas celdas pequenas. Un vano se
  cuenta una sola vez por grupo aunque aparezca en varias de sus ventanas.
- Las **barras y los violines describen SOLO la ventana elegida en el slider**, no las once. Son
  la foto del reparto en ese periodo: al mover el slider cambian los conteos, los porcentajes y la
  forma de cada violin. Sus escalas quedan FIJAS sobre el total, para que una ventana con menos
  circuitos se vea efectivamente mas baja y no reencuadrada.
- **Los titulos de las barras y de los violines dicen cuantas muestras resumen** (`n = ...`).
  Es el numero de pares circuito x ventana que cayeron en la ventana elegida, y cambia al mover
  el slider.
- Los **violines** muestran la distribucion completa de cada variable dentro de cada grupo, con su
  caja y su mediana, el estadistico con el que se ordenan los nombres.
- **La opacidad senala el par circuito x ventana elegido, y solo ese.** Un punto de la nube ES
  ese par, asi que el punto del circuito activo en la ventana activa va a opacidad 1 y todo lo
  demas queda en 0.3 -- otro circuito, otra ventana, o las dos cosas. Son dos niveles, no tres:
  con la pregunta reducida a "cual estoy mirando" no queda nada que graduar. En la trayectoria el
  circuito ya se cumple por construccion, asi que ahi solo manda la ventana. Sin circuito elegido
  no hay interseccion posible y manda la ventana sola, o la nube entera quedaria uniforme.
  La nube no se filtra: filtrarla dejaria sin sentido las flechas, que unen ventanas consecutivas.
  La contracara es que las barras y los violines describen un corte de lo dibujado, no todo.
- **Cuidado con los circuitos incompletos.** Un circuito no tiene por que aparecer en las once
  ventanas -- medido, hay circuitos con seis. En las ventanas donde ese circuito no tiene celda no
  hay interseccion, y la nube queda entera en 0.3 sin ningun punto resaltado. Eso es el dato, no
  una falla: la trayectoria y su serie de tiempo muestran de inmediato cuantas ventanas tiene.
- **El punto de la ventana vigente en las dos series de tiempo se dibuja al triple**, igual que el
  dia vigente en la serie del cuaderno `01`, y viaja con el deslizador en vivo. Lo caro -- la
  opacidad de los 1.738 puntos y el reparto por grupo -- se repinta con un retardo de 140 ms, asi
  que al arrastrar el punto grande va adelante y la nube se acomoda al soltar.
- En la **evolucion por ventana** conviven dos codigos de color. La **linea** indica que variable
  es cada serie -- azul el UITI, verde punteado los eventos -- y por eso NO usa la paleta de los
  grupos: si fuera roja competiria con el unico lugar de esa figura donde el color si mide
  criticidad. El **punto** es ese lugar: se pinta con el grupo en que cayo el circuito en esa
  ventana, y el hover lo nombra. Un punto gris es una ventana sin eventos, que no tiene grupo.
- **La estructura del circuito se dibuja siempre, completa y en negro.** Todos sus vanos estan
  ahi, tengan o no eventos en la ventana. El trazo grueso de color va ENCIMA, y solo para los que
  si tuvieron: en una ventana sin eventos el circuito no desaparece, queda su esqueleto negro. El
  mapa no usa opacidad: lo que distingue es presencia y grosor, no transparencia.
- El **mapa comparte la paleta** con el agrupamiento y sus cortes son **unicos para todo el
  conjunto de datos**, no cuantiles del circuito: el mismo color significa el mismo UITI en
  cualquier circuito, y dos mapas se pueden comparar. Antes cada mapa se autonormalizaba, y el
  color mas alto de un circuito tranquilo podia valer menos que el mas bajo de uno critico.
- **Compartir paleta no es compartir criterio.** Aqui el K-Means corre sobre pares circuito x
  ventana, de modo que un vano no tiene grupo propio: su color sale de los cortes fijos de UITI
  que rotula la barra del panel. En `04`, donde la unidad si es el vano, ese mismo color si es la
  membresia de K-Means.
- **El mapa se encuadra sobre el tamano real que tiene en pantalla.** El zoom sale de un
  `fitBounds` en Web Mercator, no del ancho del circuito en grados, y se rehace al cambiar el
  tamano de la ventana: por eso el circuito entra completo tanto en la celda del cuaderno como a
  pantalla completa en el navegador.

**Limitacion.** El corte en el dia 15, el ancho de un mes y `k=4` son decisiones de agregacion, no
algo que impongan los datos. El solape hace que los puntos consecutivos no sean independientes, de
modo que esta figura sirve para leer el recorrido de un circuito, no para estimar tendencias
formales.
