# 06 — Simulador de riesgo por vano

Simulador del cuaderno `06_uiti_vano_explicabilidad_simulador.ipynb`, como aplicación
local para macOS y Windows: el mapa histórico y el de criticidad simulada, la
selección de hasta 15 vanos, las 26 variables simulables, el top de variables por
vano, el grafo de relevancia y el costo del plan.

Es la única de las tres que necesita **Python en ejecución**. El botón *Simular* corre
el modelo MIL de PyTorch sobre los vanos marcados y con los valores escritos: 26
variables sobre hasta 15 vanos no es un espacio precomputable.

## Uso

| macOS | Windows | qué hace |
|---|---|---|
| `instalar.command` | `instalar.bat` | una sola vez: crea el entorno e instala las dependencias |
| `Iniciar.app` (doble clic) o `iniciar.command` | `iniciar.bat` | construye si hace falta y sirve el simulador |

> **En macOS haz doble clic en `Iniciar.app`, no en `iniciar.command`.** Un `.command` lo
> abre la aplicación que LaunchServices tenga atada a esa extensión, y eso lo fija cada
> máquina: con Ghostty instalado, el doble clic se lleva el foco a la sesión que ya
> tuvieras abierta y **no ejecuta nada** (Ghostty se declara *editor* de `.command`, no
> *shell*). `Iniciar.app` no se puede desviar así, abre siempre una ventana nueva de
> Terminal y la cierra sola cuando cierras el tablero. `iniciar.command` sigue ahí para
> lanzarlo desde una terminal a propósito, y es el camino de Linux.

`Ctrl+C` lo detiene. Opciones de `iniciar`: `--no-abrir`, `--puerto N`,
`--reconstruir`.

`iniciar` **reconstruye por su cuenta** si cambió cualquiera de sus insumos: usar un
paquete viejo con insumos nuevos es la única forma de que el tablero dibuje datos que ya
no corresponden sin dar error. El manifiesto guarda una huella por insumo bajo
`insumos` — sha1 para el cuaderno y los cuatro archivos que viajan dentro del paquete,
bytes + fecha para los pesados (el CSV de 540 MB, las bolsas y los tres shapefiles) —, y
al arrancar dice cuál se movió. La comprobación cuesta 1 ms.

## Qué tarda y cuánto pesa

Medido en esta máquina:

| | |
|---|---|
| construcción del paquete (una vez) | **7,3 s**, con un pico de 3,01 GB |
| paquete resultante | **95,2 MB** en 8 archivos |
| primera carga de la página | **~4,5 s** (arranca el kernel) |
| cargas siguientes, con el kernel vivo | inmediatas |
| memoria en reposo, antes de abrir la página | **96 MB** |
| memoria tras servir la página | **931 MB** |
| entorno virtual | 1,6 GB (PyTorch es casi todo) |

## Qué variables se pueden simular

Sale de **`data/Variables_simular.xlsx`**, no de una lista escrita en el código. El
archivo declara, por variable: el veredicto (si simularla significa algo y por qué), el
rango, la unidad y — cuando existe — la **lista cerrada de valores posibles**.

Esa última columna es la que decide el control:

| en el archivo | en el panel | ejemplo |
|---|---|---|
| trae valores posibles | **selector** | `ALTURA` → 12, 16 o 18 m |
| `numeric-entero` | **deslizador de enteros** | `CNT_FASES` → 1, 2 o 3 |
| `numeric` | **deslizador continuo** | `DDT`, las cuatro familias climáticas |

Medido sobre el archivo actual: **8 selectores, 3 deslizadores de enteros y 15
continuos**. Antes, `ALTURA` se ofrecía como un deslizador continuo entre 4 y 25 e
invitaba a simular un apoyo de 17,3 m que no existe en el inventario.

Para cambiar un veredicto o un rango se edita el `.xlsx` y se reconstruye. No hay que
tocar Python.

> **Una fila del archivo está mal y el panel lo dice.** `CALIBRE_NEUTRO` lista
> valores de `CONDUCTOR` (`2-ACSR-CUBIERTO`…), que el codificador del modelo no sabe
> convertir. Ofrecerlos rompería la simulación, o peor, los codificaría como otra cosa
> sin avisar. El cuaderno imprime el aviso y el panel usa las 20 categorías reales.

La aplicación **no lee `data/`**: el archivo viaja dentro del paquete y `app.py` lo
apunta por variable de entorno.

## Cómo está optimizado

### 1. El arranque se congela en un paquete

El cuaderno dedica sus primeras siete celdas a derivar: abre el CSV de 540 MB, lee
180 MB de shapefiles y carga 190 MB de bolsas, para terminar con objetos dos órdenes
de magnitud más pequeños. El constructor **ejecuta esas mismas celdas** y congela el
resultado; la aplicación sirve una copia del cuaderno que lo lee.

| | cuaderno tal cual | con el paquete |
|---|---|---|
| arranque completo | 7,4 s | **3,3 s** |
| memoria pico | 2.933 MB | **700 MB** |
| solo la carga de datos | 4,3 s | **0,2 s** |

De los 3,3 s que quedan, 2,0 s son importar PyTorch y compañía, y se pagan cuando llega
la primera petición: la página aparece a los ~4,5 s y a partir de ahí es inmediata.

**Ya no se precalienta kernel**, y es una decisión medida. `--preheat_kernel` deja uno
ya ejecutado esperando, pero pidiendo la página como la pide el menú —de inmediato, en
cuanto el puerto contesta— no ganaba nada: 4,78 s contra 4,45 s de espera. El puerto
queda atado a los 0,77 s y el kernel de reserva no llega a tiempo, así que Voilà levanta
uno nuevo igual. Lo único que quedaba era ese kernel sin usar, y se nota: **1.694 MB
contra 931 MB** tras servir la primera página.

### 2. La matriz de instancias se mapea, no se carga

`X_inst.npy` son 88 MB. Se abre con `mmap_mode='r'`, así que vive en la caché de
páginas del sistema operativo y no en la memoria del proceso.

Esto **depende** de que `mil_simulador_015` indexe antes de promover a `float64`
(`np.asarray(X_inst[filas], ...)` y no `np.asarray(X_inst, ...)[filas]`). La forma
vieja leía los 88 MB enteros en cada clic y convertía el mapeo en copia privada. Hay
36 pruebas que fijan eso:

```
.venv/bin/python -m pytest tests/test_mil_simulador_015.py -q
```

Si fallan, los números de arriba dejan de valer.

### 3. Voila, no una reescritura

El tablero son ~1.900 líneas de `ipywidgets` sobre un `go.FigureWidget`. Voila sirve
**ese** cuaderno, así que sigue siendo la única fuente de verdad. Reescribirlo en Dash
o Streamlit obligaría a mantener dos tableros que tendrían que coincidir para siempre.

## El cuaderno del repositorio no se toca

La copia parcheada vive en `cuaderno/06_simulador.ipynb`. Se genera aplicando parches
acotados, y **cada parche exige que su marca aparezca exactamente una vez**: si el
cuaderno 06 cambia en esa zona, la construcción se detiene con el motivo en vez de
producir un cuaderno que muere dentro del servidor sin dejar rastro útil.

Al terminar, una comprobación exige que la copia no ejecute `context_df`, `Xdf`,
`procesar_dataset_completo` ni `geopandas` — que es la prueba de que ningún camino
reabre el CSV o los shapefiles. La comprobación mira el código, no los comentarios:
los parches dejan explicado por qué esos objetos ya no están.

La copia también declara su **propio kernel** (`chec-simulador-vano`), registrado
dentro del entorno de la aplicación. El cuaderno declara `python3`, y Voila resuelve
ese nombre contra los kernels instalados en la máquina: sin un kernel propio, se le vio
arrancar el intérprete de otro proyecto ya borrado y responder 500.

## Verificación contra el cuaderno original

| | original | con el paquete |
|---|---|---|
| celdas vano×ventana | 111.231 | 111.231 |
| matriz de instancias | (288.632, 80) `float32` | idéntica |
| controles | 26 | 26 |
| circuitos | 208 | 208 |
| interfaz | `VBox` de 4 hijos, 59 trazas | idéntica |
| una simulación real | `u_base` y `u_simulado` | **idénticos a 10 decimales** |

Y servido con Voila, en un Chrome real: **619 widgets, 5 lienzos de mapa, 241
casillas de vano, 177 botones, el botón *Simular* presente y cero errores de
JavaScript**.

## Requisitos

Python 3.10+ y, para **construir**, el repositorio con:

- `data/Indicadores_vano_v3.csv` (`git lfs pull`)
- `data/GEO/MVLINSEC.shp` y compañía
- `data/models/mil_vano_ventana_v1.pt` y `data/derived/bolsas_mil_full.joblib`
  — los produce `05_mil_vano_ventana.ipynb`
- `data/derived/geometrias_014.json` — sale del cuaderno 04

Una vez construido el paquete, la aplicación no vuelve a abrir ninguno de ellos.
