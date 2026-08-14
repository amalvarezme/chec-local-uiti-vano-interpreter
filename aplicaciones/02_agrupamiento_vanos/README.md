# 02 — Agrupamiento de vanos por UITI acumulado

Tablero de **vanos** del cuaderno `02_uiti_vano_kmeans.ipynb`, como aplicación local
para macOS y Windows: los 27.390 vanos agrupados en 4 clases por UITI acumulado y
número de eventos, con calendarios de rango, las densidades marginales, los violines
por grupo y la descarga de etiquetas en CSV.

> El cuaderno muestra **dos** tableros: circuitos arriba y vanos abajo. Esta
> aplicación publica el de **vanos**, que es el que responde la pregunta operativa —
> qué vanos y de qué circuitos concentran la criticidad. El de circuitos se lee dentro
> del cuaderno.

## Uso

| macOS | Windows | qué hace |
|---|---|---|
| `instalar.command` (doble clic) | `instalar.bat` (doble clic) | una sola vez: crea el entorno e instala las dependencias |
| **`Iniciar.app`** (doble clic) | **`iniciar.bat`** (doble clic) | construye si hace falta, sirve el tablero y abre el navegador |

> **A qué le doy doble clic:** en **macOS**, a `Iniciar.app`; en **Windows**, a
> `iniciar.bat`. Los dos hacen lo mismo que `iniciar.command`, y la diferencia es que
> funcionan **siempre**: a un `.command` lo abre la aplicación que LaunchServices tenga
> atada a esa extensión, y eso lo fija cada máquina — con Ghostty instalado puede tocarle
> Ghostty, que se declara *editor* de `.command`, y entonces el doble clic **no ejecuta
> nada**. `Iniciar.app` no se puede desviar así: LaunchServices no lo abre con otra
> aplicación, lo **lanza**, y abre siempre una ventana nueva de Terminal que se cierra
> sola al cerrar el tablero. En Windows no hace falta nada de esto: un `.bat` lo ejecuta
> el intérprete de órdenes del sistema. `iniciar.command` se conserva para lanzarlo a
> mano desde una terminal, y es el camino de Linux.

`Ctrl+C` lo detiene. Opciones de `iniciar`: `--no-abrir`, `--puerto N`,
`--reconstruir`, `--verboso`.

## Qué tarda y cuánto pesa

Medido en esta máquina:

| | |
|---|---|
| construcción (una vez) | **51,4 s** — el cuaderno lee el CSV de 540 MB **dos veces**, una por circuito y otra por vano |
| arranque posterior | **menos de 1 s** |
| entorno virtual | 530 MB |
| tablero construido | 6,1 MB en disco |
| primera apertura | **1,77 MB** transferidos |
| aperturas siguientes | **16 KB** |

## Cómo está optimizado

| pieza | crudo | comprimido | caché |
|---|---|---|---|
| `index.html` | 0,05 MB | 16 KB | revalida con ETag |
| `plotly-3.7.0.<hash>.js` | 4,63 MB | 1,40 MB | `immutable`, un año |
| `datos.<hash>.json` | 1,41 MB | 0,35 MB | `immutable`, un año |

Aquí la librería de gráficos pesa **tres veces más que los datos del tablero**, así
que sacarla del documento es casi todo el ahorro. Y como es byte por byte la misma que
usa la aplicación 01 — mismo hash en el nombre —, quien ya abrió aquella no la vuelve
a descargar: la primera apertura baja entonces a **378 KB**.

El cuaderno ya venía optimizado por dentro y esta aplicación no lo cambió: K-Means se
ajusta **una sola vez** por tablero (no una por rango de fechas), las etiquetas no se
embeben sino que el navegador las deriva por centroide más cercano, y la matriz
vano×mes viaja con los ceros como enteros y los nombres de circuito como paleta.

### Comprobado en un navegador real

Comparando el documento del cuaderno contra el empaquetado en Chrome: **25 trazas y
55.637 puntos en los dos**, los mismos 2 calendarios y 10 botones, los dos reaccionan
al mover el rango de fechas, y **cero errores de JavaScript** en ambos.

## Advertencia

`index.html` **no funciona con doble clic** — los datos se cargan aparte y el
navegador bloquea esa lectura sobre `file://`. La página lo dice en pantalla si
alguien lo intenta.

## Requisitos

Python 3.10+ y `data/Indicadores_vano_v3.csv` descargado (`git lfs pull`). Solo para
construir. Este tablero no usa shapefiles: no dibuja mapa.
