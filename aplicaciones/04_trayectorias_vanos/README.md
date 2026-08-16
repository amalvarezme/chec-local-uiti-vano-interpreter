# 04 — Agrupamiento y evolución por vano

Tablero del cuaderno `04_uiti_vano_trayectorias_vano.ipynb`, como aplicación local para
macOS y Windows. Es el mismo tablero que la 03 un nivel más abajo: donde aquélla ubica
circuitos, ésta ubica vanos dentro del circuito elegido, con su mapa, su nube agrupada
por K-Means y la ventana deslizante que gobierna las dos vistas a la vez.

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
| construcción (una vez) | **71,0 s** — de los cuales 67,2 s son la celda 2, que lee el CSV de 540 MB |
| arranque posterior | **menos de 1 s** — el tablero ya es un documento estático |
| entorno virtual | 633 MB |
| tablero construido | 11,1 MB en disco |
| primera apertura | **2,81 MB** transferidos |
| aperturas siguientes | **24 KB** |

## Cómo está optimizado

| pieza | crudo | comprimido | caché |
|---|---|---|---|
| `index.html` | 0,09 MB | 24 KB | revalida con ETag |
| `plotly-3.7.0.<hash>.js` | 4,63 MB | 1,40 MB | `immutable`, un año |
| `datos.<hash>.json` | 6,41 MB | 1,39 MB | `immutable`, un año |

**`plotly.js` es literalmente el mismo archivo que sirven 01, 02 y 03**: mismo nombre,
mismo hash `8ef4c6ab13`, verificado. Abrir cualquiera de las otras deja ésta con 1,40 MB
ya en caché, y la primera apertura baja de 2,81 MB a 1,41 MB. Por eso `requirements.txt`
fija `plotly==6.9.0` en vez de un mínimo, y por eso subirla hay que subirla en las
cuatro a la vez.

## El tablero ya no vive en el cuaderno

Desde el 2026-08-15 el código de este tablero está en
`src/chec_tableros/trayectorias_vanos.py`, y esta aplicación lo construye **importándolo**,
no ejecutando celdas. El cuaderno queda como envoltorio delgado con su narrativa.

Con eso se retiró la regla «no limpies la salida de este cuaderno», que era la más
repetida del proyecto. Tenía dos motivos y los dos murieron: la geometría K-Means ya no
se extrae de ese HTML —vive versionada en `data/geometria_kmeans_014_v1.json`— y el
tablero ya no se publica desde su salida guardada. El `.ipynb` bajó de 7.707 a 239
líneas y de 12,3 MB a unos pocos KB.

## Advertencia

`index.html` **no funciona con doble clic**. Los datos se cargan aparte y el navegador
bloquea esa lectura sobre `file://`. Si alguien lo intenta, la página lo dice en un
recuadro rojo en vez de quedarse muda.

## Requisitos

Python 3.10+ y el repositorio con `data/Indicadores_vano_v3.csv` y `data/GEO/`
descargados (`git lfs pull`). Solo para **construir**: una vez construido, el tablero no
vuelve a tocar los datos.
