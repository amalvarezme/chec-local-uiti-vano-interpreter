# 04 — Agrupamiento y evolución por vano

Tablero del cuaderno `04_uiti_vano_trayectorias_vano.ipynb`, como aplicación local para
macOS y Windows. Es el mismo tablero que la 03 un nivel más abajo: donde aquélla ubica
circuitos, ésta ubica vanos dentro del circuito elegido, con su mapa, su nube agrupada
por K-Means y la ventana deslizante que gobierna las dos vistas a la vez.

## Uso

| macOS | Windows | qué hace |
|---|---|---|
| `instalar.command` | `instalar.bat` | una sola vez: crea el entorno e instala las dependencias |
| `iniciar.command` | `iniciar.bat` | construye si hace falta, sirve el tablero y abre el navegador |

`Ctrl+C` en la ventana lo detiene, y el botón **Cerrar tablero** de arriba a la derecha
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

## No limpies la salida de este cuaderno

`04_uiti_vano_trayectorias_vano.ipynb` es el único de los cinco cuya **salida guardada
en el `.ipynb` es un insumo**: `scripts/extract_geometrias_014.py` lee de ahí la
geometría K-Means que comparten los cuadernos 05 y 06. Limpiar sus salidas «para que el
diff no haga ruido» rompe la criticidad aguas abajo.

Construir esta aplicación **no** la toca — `_comun/cuaderno.py` lee el documento y
ejecuta las fuentes con `exec`, sin escribir nunca de vuelta —, y está comprobado:
después de construir, `git status --porcelain notebooks/` sale vacío.

## Advertencia

`index.html` **no funciona con doble clic**. Los datos se cargan aparte y el navegador
bloquea esa lectura sobre `file://`. Si alguien lo intenta, la página lo dice en un
recuadro rojo en vez de quedarse muda.

## Requisitos

Python 3.10+ y el repositorio con `data/Indicadores_vano_v3.csv` y `data/GEO/`
descargados (`git lfs pull`). Solo para **construir**: una vez construido, el tablero no
vuelve a tocar los datos.
