# 01 — Nube por vano y clima

Tablero del cuaderno `01_uiti_vano_clima.ipynb`, como aplicación local para macOS y
Windows: la nube por vano sobre el mapa, las 6 variables seleccionables, la serie de
tiempo de doble eje y los 6 violines, con los 208 circuitos dentro y el selector
cambiándolos en vivo.

## Uso

| macOS | Windows | qué hace |
|---|---|---|
| `instalar.command` | `instalar.bat` | una sola vez: crea el entorno e instala las dependencias |
| `iniciar.command` | `iniciar.bat` | construye si hace falta, sirve el tablero y abre el navegador |

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
