# 03 — Trayectoria y agrupamiento de circuitos

Tablero del cuaderno `03_uiti_vano_trayectorias_circuitos.ipynb`, como aplicación local
para macOS y Windows: la nube de circuitos agrupada por K-Means, la serie de doble eje
con el punto de la ventana activa a triple tamaño, y el mapa de circuitos — todo
gobernado por una ventana deslizante que reordena las opacidades en vivo.

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
