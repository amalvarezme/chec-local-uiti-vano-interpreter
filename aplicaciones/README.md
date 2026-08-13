# Aplicaciones locales

Cinco aplicaciones de escritorio que corren en macOS y en Windows, sin servidor y sin
conexión, sobre los cuadernos de `notebooks/` — más un menú que las gobierna.

## Empieza por aquí

| carpeta | qué es |
|---|---|
| [`00_criticidad_chec/`](00_criticidad_chec/) | **CriticidadCHEC** — el menú: abre, vigila y cierra las otras cinco desde una sola ventana |

Se puede usar cualquiera de las cinco por su cuenta, exactamente igual que antes. El
menú no las reemplaza: usa sus mismos puertos, así que reconoce una que ya estuviera
abierta a mano en vez de duplicarla.

## Los cinco tableros

| carpeta | qué abre | cuaderno |
|---|---|---|
| [`01_clima/`](01_clima/) | nube por vano sobre el mapa, con las 6 variables, la serie de doble eje y los 6 violines | `01_uiti_vano_clima.ipynb` |
| [`02_agrupamiento_vanos/`](02_agrupamiento_vanos/) | agrupamiento de vanos por UITI acumulado y número de eventos | `02_uiti_vano_kmeans.ipynb` |
| [`03_trayectorias_circuitos/`](03_trayectorias_circuitos/) | trayectoria y agrupamiento de circuitos con ventana deslizante | `03_uiti_vano_trayectorias_circuitos.ipynb` |
| [`04_trayectorias_vanos/`](04_trayectorias_vanos/) | lo mismo un nivel más abajo: agrupamiento y evolución por vano | `04_uiti_vano_trayectorias_vano.ipynb` |
| [`06_simulador/`](06_simulador/) | simulador de riesgo por vano: *qué pasaría si* sobre el modelo MIL | `06_uiti_vano_explicabilidad_simulador.ipynb` |

## Cómo se usan

Cada carpeta trae los mismos cuatro lanzadores. En **macOS** doble clic sobre el
`.command`; en **Windows**, sobre el `.bat`.

1. `instalar` — una sola vez. Crea el entorno de esa aplicación e instala sus
   dependencias.
2. `iniciar` — cada vez que quieras abrirla. Construye lo que falte y abre el
   navegador. `Ctrl+C` en la ventana la detiene.

La primera vez, `iniciar` tarda: tiene que ejecutar el cuaderno. Después arranca en
menos de un segundo.

### Requisitos

- **Python 3.10 o superior** en la máquina. macOS: `brew install python@3.11`.
  Windows: <https://www.python.org/downloads/> marcando *Add Python to PATH*.
- El repositorio completo, con `data/` descargado (`git lfs pull`). Las cinco
  aplicaciones **construyen** desde los datos del repositorio; solo la 06 los sigue
  necesitando después.
- Un navegador. No hace falta Jupyter, ni VS Code, ni conexión a internet.

## Por qué 01, 02, 03 y 04 son livianas y 06 no

No es una decisión de estilo, es lo que cada tablero necesita.

**01, 02, 03 y 04 no necesitan Python en ejecución.** Sus cuadernos precomputan todo y
entregan un documento HTML donde la interacción entera vive en JavaScript: cambiar de
circuito, mover la ventana deslizante o cambiar de variable no vuelve a llamar a nadie.
La aplicación es entonces un **constructor** (se corre una vez) y un **servidor
estático** (biblioteca estándar, sin dependencias).

Los K-Means de 03 y 04 no son una excepción: se ajustan **al construir**, en Python, y
lo que viaja al navegador son las coordenadas y las etiquetas ya resueltas. Mover la
ventana reordena opacidades sobre puntos que ya existen.

**06 sí.** Su botón *Simular* corre el modelo MIL de PyTorch sobre los vanos que el
usuario marcó y con los valores que escribió: 26 variables sobre hasta 15 vanos. No
hay respuesta precomputable. Necesita un intérprete vivo, y por eso su entorno pesa
lo que pesa.

## Qué se optimizó, y cuánto

Todos los números están medidos en esta máquina, no estimados.

### 01, 02, 03 y 04 — el problema era el peso del documento

Los cuadernos escriben un HTML con todo dentro: la librería de gráficos, los datos y
la lógica. El de clima pesa **27,8 MB** y el navegador lo volvía a bajar y a
reinterpretar entero en cada apertura.

El constructor lo parte en tres piezas con el hash del contenido en el nombre, y el
servidor entrega las versiones comprimidas que quedaron en disco:

| | 01 clima | 02 vanos | 03 circuitos | 04 vanos |
|---|---|---|---|---|
| documento original | 27,80 MB | 6,08 MB | 10,46 MB | 11,13 MB |
| **primera apertura** (comprimido) | **6,37 MB** | **1,77 MB** | **3,05 MB** | **2,81 MB** |
| primera apertura con otra app ya abierta | 4,98 MB | **378 KB** | 1,65 MB | 1,41 MB |
| **aperturas siguientes** | **17 KB** | **16 KB** | **18 KB** | **24 KB** |
| construcción (una vez) | 25,0 s | — | 71,0 s | 71,0 s |

Las aperturas siguientes bajan a decenas de KB porque `plotly.js` y los datos se sirven
como `immutable`: el navegador ni siquiera pregunta por ellos, solo revalida el armazón.
Y `plotly.js` es **el mismo archivo con el mismo hash en las cuatro aplicaciones** —
`plotly-3.7.0.8ef4c6ab13.js`, comprobado byte a byte —, así que abrir cualquiera deja a
las otras tres ya cacheadas. Por eso `requirements.txt` fija la versión exacta de plotly
en las cuatro, en vez de un mínimo: instalarlas en semanas distintas daría cuatro
versiones y cada una se descargaría aparte.

Además, los datos pasan de ser un literal de JavaScript dentro de un `<script>` a un
`.json` que el navegador lee con su analizador nativo.

**Verificado en un Chrome real**, comparando el documento original contra el
empaquetado: mismas trazas (16 y 25), mismos puntos dibujados (22.603 y 55.637),
mismos controles, los dos reaccionan al moverlos, y los mismos avisos de JavaScript
que ya emitía el original.

### 06 — el problema era el arranque

El cuaderno dedicaba sus primeras siete celdas a derivar: abrir el CSV de 540 MB,
leer 180 MB de shapefiles y cargar 190 MB de bolsas, para terminar con objetos dos
órdenes de magnitud más pequeños. La aplicación **congela ese resultado** en un
paquete de 95,2 MB y sirve una copia del cuaderno que lo lee.

| | cuaderno tal cual | con el paquete |
|---|---|---|
| arranque completo | 7,4 s | **3,3 s** |
| memoria pico | 2.933 MB | **700 MB** |
| solo la carga de datos | 4,3 s | **0,2 s** |

Lo que queda de los 3,3 s son 2,0 s de importar PyTorch y compañía, que la aplicación
paga **antes** de que llegue la primera petición: arranca un kernel ya ejecutado y
esperando. Medido contra el servidor real, eso es la diferencia entre **4 ms** y
**6,0 s** en abrir la página.

La matriz de instancias (88 MB) se mapea en memoria en vez de cargarse, así que vive
en la caché del sistema operativo y no en la memoria del proceso.

**Verificado contra el cuaderno original**: mismas 111.231 celdas vano×ventana, misma
matriz de 288.632×80, los mismos 26 controles, los mismos 208 circuitos, la misma
interfaz (59 trazas) y una simulación real idéntica hasta el décimo decimal.

## Los botones de cerrar

Un tablero abierto **por su cuenta** trae arriba un botón *Cerrar tablero* que detiene
su servidor — no los otros, que corren en su propio proceso y su propio puerto.

Un tablero abierto **desde CriticidadCHEC** trae en su lugar dos: *Volver al menú*, que
lo apaga y cierra su pestaña dejando el menú a la vista, y *Cerrar todo*, que apaga las
cinco aplicaciones y el menú. El botón suelto desaparece cuando hay menú, porque haría
lo mismo que *Volver* pero dejando la pestaña sobre un tablero muerto.

Cerrar son tres cosas, y las tres están medidas contra el servidor real:

1. **El proceso muere.** El botón manda un `POST` a `/apagar`; el servidor contesta
   `200 cerrando` y se apaga desde otro hilo. El proceso termina con código 0 a los
   **0,56 s**. Es `POST` y no `GET` a propósito: un `GET` que apaga el servidor lo
   dispara el prefetch del propio navegador, y el tablero se cerraría solo.
2. **El puerto queda libre.** Al salir se cierra el socket: `lsof` no devuelve nada y
   el puerto se vuelve a reservar en el acto.
3. **La pestaña se cierra sola**, en el caso normal. Medido abriendo por el mismo
   camino que usa `iniciar.command`. La regla del navegador no es «solo se cierra lo
   que abrió un script» sino que Chrome lo permite mientras la pestaña no tenga
   historial propio — y una recién abierta por el lanzador no lo tiene.

Esa tercera condición se pierde fácil: basta con haber navegado dentro de la pestaña, y
Firefox lo rechaza por defecto. Cuando pasa, la página lo dice en pantalla en vez de
quedarse con un tablero que parece vivo. El servidor murió igual.

## La paleta

Los cinco cuadernos emiten su propio CSS y todos usan los mismos ocho colores: fondo
blanco, texto casi negro y una familia rosa/roja que sale de la escala `Reds` con la
que se pintan los datos. Un botón de acción y el extremo caliente de un mapa son
literalmente el mismo rojo.

| token | valor | papel |
|---|---|---|
| `FONDO` | `#fff` | fondo de página |
| `TEXTO` | `#2b2b2b` | texto principal (no `#000`: sobre blanco cansa) |
| `ACENTO` | `rgb(203,24,29)` | botones, filo izquierdo de los paneles |
| `ACENTO_OSCURO` | `rgb(165,15,21)` | sólo `:hover` |
| `PANEL` | `#fdf7f6` | fondo de los bloques de control |
| `BORDE` | `#e4c4c0` | bordes de bloque |
| `BORDE_FUERTE` | `#c9a9a5` | bordes de controles que se tocan |
| `TENUE` | `#7a5c58` | avisos y notas al pie |

Lo que se agrega **después** de los cuadernos —el botón de cerrar, la barra del menú, la
página de CriticidadCHEC— no sale de ellos, así que puede desentonar sin que nadie lo
note: cada pieza se ve bien por separado y sólo canta cuando están juntas. Por eso vive
en `_comun/paleta.py`, y por eso hay dos pruebas: una comprueba que cada token aparece
de verdad en el CSS que emiten los cuadernos, y otra que esas tres piezas no usan ni un
color de su cosecha.

El menú **no** sigue `prefers-color-scheme`. Los tableros fijan fondo blanco y lo
ignoran; un menú que se pusiera oscuro de noche mandaría al usuario a un tablero blanco
de un clic.

## Estructura

```
aplicaciones/
├── _comun/                    motor compartido, solo biblioteca estándar
│   ├── gestor.py              arranque: crea el entorno y lanza la aplicación
│   ├── entorno.py             entorno virtual por aplicación, macOS y Windows
│   ├── cuaderno.py            ejecuta las celdas de un cuaderno sin kernel
│   ├── empaquetar.py          parte el HTML en piezas cacheables
│   ├── construccion.py        construcción compartida de los cuatro visores estáticos
│   ├── servidor.py            servidor estático con compresión y caché
│   ├── menu.py                servidor de control: lanza y apaga las otras cinco
│   ├── menu_pagina.py         la página del menú, sin dependencias
│   ├── paleta.py              los ocho colores que comparten los tableros
│   ├── huellas.py             huellas de los insumos, para saber cuándo reconstruir
│   └── raiz.py                localización del repositorio
├── 00_criticidad_chec/
├── 01_clima/
├── 02_agrupamiento_vanos/
├── 03_trayectorias_circuitos/
├── 04_trayectorias_vanos/
└── 06_simulador/
```

Las cuatro aplicaciones estáticas son casi sólo declaración: su `construir.py` nombra
un cuaderno y un título, y `_comun/construccion.py` hace el resto. Agregar una quinta
es copiar esos dos valores.

Ninguna aplicación modifica su cuaderno. La 06 trabaja sobre una copia parcheada que
vive dentro de su propia carpeta.

## Qué NO se guarda en el repositorio

Los entornos (`.venv/`), los tableros construidos (`panel/`), el paquete del
simulador (`paquete/`) y la copia parcheada del cuaderno (`cuaderno/`) son artefactos
de cada máquina: se regeneran con `instalar` e `iniciar`.
