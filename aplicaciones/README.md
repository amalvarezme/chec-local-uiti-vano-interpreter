# Aplicaciones locales

Cinco aplicaciones de escritorio que corren en macOS y en Windows, sin servidor y sin
conexión, sobre los cuadernos de `notebooks/` — más un menú que las gobierna.

## A qué le doy doble clic

Entra en **`00_criticidad_chec/`** y haz doble clic:

| Sistema | Archivo |
|---|---|
| **macOS** | **`Iniciar.app`** |
| **Windows** | **`instalar.bat`** la primera vez, y después **`iniciar.bat`** siempre |

Eso abre **CriticidadCHEC**, el menú desde el que se abren y se cierran los cinco
tableros. No hace falta entrar en las otras carpetas: traen los mismos lanzadores por si
quieres abrir una suelta, pero el camino normal es el menú.

> **No le des doble clic a `abrir-en-terminal.command`.** Es para escribirlo a mano en
> una terminal ya abierta, y es el camino de Linux. En macOS un doble clic ahí puede no
> ejecutar nada — el porqué está en «La regla de Ghostty», al final.

## Empieza por aquí

| carpeta | qué es |
|---|---|
| [`00_criticidad_chec/`](00_criticidad_chec/) | **CriticidadCHEC** — el menú: abre, vigila y cierra las otras cinco desde una sola ventana |

Se puede usar cualquiera de las cinco por su cuenta, exactamente igual que antes. El
menú no las reemplaza: usa sus mismos puertos, así que reconoce una que ya estuviera
abierta a mano en vez de duplicarla.

## Los cinco tableros

| carpeta | qué abre | módulo |
|---|---|---|
| [`01_clima/`](01_clima/) | nube por vano sobre el mapa, con las 6 variables, la serie de doble eje y los 6 violines | `chec_tableros.clima` |
| [`02_agrupamiento_vanos/`](02_agrupamiento_vanos/) | agrupamiento de vanos por UITI acumulado y número de eventos | `chec_tableros.agrupamiento` |
| [`03_trayectorias_circuitos/`](03_trayectorias_circuitos/) | trayectoria y agrupamiento de circuitos con ventana deslizante | `chec_tableros.trayectorias_circuitos` |
| [`04_trayectorias_vanos/`](04_trayectorias_vanos/) | lo mismo un nivel más abajo: agrupamiento y evolución por vano | `chec_tableros.trayectorias_vanos` |
| [`06_simulador/`](06_simulador/) | simulador de riesgo por vano: *qué pasaría si* sobre el modelo MIL | `chec_tableros.simulador` |

Los cinco tableros vivían dentro de un `.ipynb` que cada aplicación ejecutaba con
`exec()`. Desde agosto de 2026 su código está en `src/chec_tableros/` y las
aplicaciones lo **importan**.

## Cómo se usan — y por qué el doble clic es ese y no otro

Cada carpeta trae los mismos cinco lanzadores: `Iniciar.app`, `iniciar.bat`,
`instalar.bat`, `abrir-en-terminal.command` e `instalar-en-terminal.command`. La tabla
de arriba dice a cuál darle; esta dice qué hace cada camino, y vale igual para el menú y
para las cinco aplicaciones:

| Sistema | Instalar (una sola vez) | Abrir (cada vez) |
|---|---|---|
| **macOS** | nada: `Iniciar.app` instala solo si hace falta | doble clic en **`Iniciar.app`** |
| **Windows** | doble clic en **`instalar.bat`** | doble clic en **`iniciar.bat`** |
| Linux | `./instalar-en-terminal.command` desde una terminal | `./abrir-en-terminal.command` desde una terminal |

**En macOS el único doble clic es `Iniciar.app`.** Junto a él hay un
`abrir-en-terminal.command` que hace lo mismo, y aun así no es el destino del doble clic:
a un `.command` lo abre la aplicación que LaunchServices tenga atada a esa extensión, y
eso lo fija cada máquina y se cambia sin querer desde el «Abrir con» del Finder. En una
máquina con Ghostty le toca Ghostty, que se declara *editor* de `.command` y entonces el
doble clic **no ejecuta nada**: abre el archivo en un editor. `Iniciar.app` no se puede
desviar así — LaunchServices no lo abre con otra aplicación, lo **lanza**. Ver «La regla
de Ghostty», más abajo.

Ese archivo se llamaba `iniciar.command`, y el nombre era el fallo: llamándose `iniciar`
y estando al lado de `Iniciar.app`, el doble clic caía ahí una y otra vez. Se renombró a
`abrir-en-terminal.command` (y `instalar.command` a `instalar-en-terminal.command`)
justo por eso. Sigue sirviendo para lanzarlo **a mano** desde una terminal ya abierta, y
es el camino de Linux.

**En Windows el doble clic va sobre los `.bat` y no hay nada equivalente que resolver:**
un `.bat` lo ejecuta el intérprete de órdenes del sistema, no una aplicación asociada que
cada máquina pueda cambiar. No existe ningún `Iniciar.app` allí, y no hace falta.

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

Lo que queda de los 3,3 s son 2,0 s de importar PyTorch y compañía, que se pagan cuando
llega la primera petición: **la página tarda ~4,5 s en aparecer la primera vez**, y las
siguientes son inmediatas mientras el kernel siga vivo.

> El simulador local **ya no precalienta kernel**. Medido A/B pidiendo la página como la
> pide el menú —de inmediato, en cuanto el puerto contesta—, el precalentado no mejoraba
> la espera (4,78 s contra 4,45 s): el puerto queda atado a los 0,77 s y el kernel de
> reserva no llega a tiempo, así que Voilà levanta uno nuevo igual. Lo único que dejaba
> era ese kernel sin usar: **1.694 MB contra 931 MB** tras servir la primera página. En
> el despliegue de servidor sigue encendido, donde el trato es el contrario.

La matriz de instancias (88 MB) se mapea en memoria en vez de cargarse, así que vive
en la caché del sistema operativo y no en la memoria del proceso.

**Verificado contra el cuaderno original**: mismas 111.231 celdas vano×ventana, misma
matriz de 288.632×80, los mismos 26 controles, los mismos 208 circuitos, la misma
interfaz (59 trazas) y una simulación real idéntica hasta el décimo decimal.

## Puertos y redes de empresa

Los puertos **son fijos y siempre lo han sido**. No se negocian al arrancar ni se
buscan libres: cada aplicación pide el suyo y, si no lo consigue, no se levanta en otro.
Esa es la condición para que el menú reconozca una aplicación abierta a mano y para que
la URL del marcador siga sirviendo mañana.

| aplicación | puerto |
|---|---|
| CriticidadCHEC (el menú) | **8800** |
| 01 Clima | **8801** |
| 02 Agrupamiento de vanos | **8802** |
| 03 Trayectorias por circuito | **8803** |
| 04 Trayectorias por vano | **8804** |
| 06 Simulador | **8866** |

Todos escuchan **solo en `127.0.0.1`**. No se publica nada a la red de la oficina: no
hay que abrir ningún puerto en el firewall perimetral, y otra máquina no puede conectarse
aunque quiera.

### Un puerto bloqueado no es un puerto ocupado

Son dos problemas distintos y tienen arreglos distintos:

* **Ocupado** — hay otro programa escuchando ahí. Se arregla cerrándolo, y la aplicación
  dice cuál con `netstat -ano | findstr :8801`.
* **Bloqueado** — no hay *nadie* escuchando y aun así el sistema se niega a dar el
  puerto. En Windows lo hacen los rangos que reservan **Hyper-V, WSL y Docker Desktop**
  al arrancar; el `bind` sale con `WSAEACCES` (10013). Esto **no se arregla desde la
  máquina del usuario**.

Hasta el 2026-08-18 los dos casos se leían igual, y el bloqueado ni siquiera se
detectaba: la conexión de sondeo rebota igual que en un puerto libre, así que la
aplicación seguía adelante hasta reventar al atarse. Desde el menú eso eran **180 s de
tarjeta en «preparando»** y un «el servidor no respondió» que no nombraba ni el puerto ni
la causa; por doble clic, la aplicación arrancaba **en un puerto al azar** donde el menú
no la vigila y el marcador no la encuentra. Las dos cosas se ven igual desde la silla:
*se queda cargando*.

Ahora se comprueba antes de instalar, construir o lanzar nada, y la tarjeta dice
`puerto 8801 bloqueado por el sistema (rango reservado 8850-8949)`.

### Qué pedirle a quien administra la máquina

Para ver los rangos reservados, en una consola cualquiera:

```
netsh interface ipv4 show excludedportrange protocol=tcp
```

Si alguno de los seis puertos de la tabla cae dentro de un rango, la petición es
exactamente esta: **liberar ese puerto TCP en `127.0.0.1`**. No sirve mudarse a otro —
la URL es fija por diseño.

### El proxy: pip no lee Opciones de Internet

En una máquina recién clonada, lo primero que hace el menú al abrir un tablero es crear
su entorno con pip. Y ahí aparece el otro *«se queda cargando»*, que **no tiene nada que
ver con los puertos**: detrás de un proxy corporativo, pip no llega a PyPI y se queda
reintentando. El menú lo lanza con la salida capturada y sin plazo, así que la tarjeta se
queda en «creando el entorno» sin cambiar nunca.

La causa es que el proxy de la empresa suele estar puesto en **Opciones de Internet**
(WinINET) — que es lo que usa el navegador — y **pip no lo lee**. Solo lee variables de
entorno:

```
setx HTTPS_PROXY http://usuario:clave@proxy.de.la.empresa:8080
setx HTTP_PROXY  http://usuario:clave@proxy.de.la.empresa:8080
```

Hay que abrir una consola **nueva** después de ponerlas. El menú ahora lo comprueba antes
de lanzar pip y lo dice en la tarjeta.

> Esto también descarta una sospecha razonable: que el proxy esté estorbando al
> **navegador**. No puede ser: la página del menú se sirve por `127.0.0.1:8800` y carga
> bien, así que ese camino ya está despejado. Si el menú se ve, el navegador llega a
> loopback.

## La regla de Ghostty — léela antes de tocar cualquier lanzador

Este fallo ha vuelto tres veces y siempre por el mismo sitio: **algo entrega un archivo
a macOS y deja que LaunchServices decida quién lo abre.** Medido con `lsregister -dump`
en la máquina donde pasa:

| Aplicación | Reclama | Rol |
|---|---|---|
| Ghostty | `.command`, `.tool`, `.sh`, `.zsh`, `.csh`, `.pl` | **Editor** |
| Terminal.app | `com.apple.terminal.shell-script` (los `.command`) | Shell |
| Terminal.app | `com.apple.terminal.settings` (los `.terminal`) | Editor |

Un `.command` que le toque a Ghostty **no se ejecuta**: solo se lleva el foco a la sesión
que ya estuviera abierta. Y lo que hace este fallo tan caro es dónde deja el arreglo — si
el script no llega a correr, nada de lo que se escriba **dentro** del script puede
salvarlo. El síntoma es un parpadeo, o directamente nada, sin ningún sitio donde leerlo.

> **La regla, en una línea:** todo camino que abra una ventana de terminal tiene que
> **nombrar a Terminal.app** — `open -a Terminal <perfil.terminal>`, con
> `open -b com.apple.Terminal` de respaldo. Nunca un `open <archivo>` a secas, y nunca un
> `.command` como destino de doble clic.

`-a` no es una preferencia: es una orden, y LaunchServices no consulta ninguna atadura.
El formato `.terminal` además no lo reclama nadie más que Terminal.app, así que es el
hueco por el que se pasa. Todo eso vive en **un solo sitio**, `_comun/terminal.py`, y los
seis `Iniciar.app` hacen lo mismo en shell porque corren antes de que exista ningún
Python.

**Y nunca `osascript`.** Pedirle a Terminal por AppleScript que abra o cierre una ventana
exige el permiso de Automatización. Sin él la llamada *no falla*: se queda **colgada**
esperando un diálogo que puede salir detrás de otra ventana (medido: 19 s y subiendo).
Por eso la ventana se cierra sola con `shellExitAction` del perfil y no mandándole nada a
Terminal.

`tests/test_terminal_nueva.py` fija las tres reglas leyendo los lanzadores como texto, y
falla si alguien vuelve a dejar un `open` sin destinatario. El último salto — el doble
clic de verdad — solo lo puede probar una persona delante de la pantalla: `open` sobre un
bundle desde un entorno sin interfaz devuelve `-10669`.

## Los botones de cerrar

Un tablero abierto **por su cuenta** trae arriba un botón *Cerrar* que detiene su
servidor — no los otros, que corren en su propio proceso y su propio puerto.

Un tablero abierto **desde CriticidadCHEC** trae en su lugar dos, y los dos apagan
**solo ese tablero**, con su puerto y todo lo que cuelga de él: *Volver al menú*, que lo
apaga y cierra su pestaña dejando el menú a la vista, y *Cerrar*, que lo apaga y cierra
la pestaña sin volver al menú. El botón suelto desaparece cuando hay menú, porque haría
lo mismo que *Cerrar* pero dejando la pestaña sobre un tablero muerto.

**Ningún botón de un tablero apaga a los demás.** El único apagado general es el botón
*Cerrar todo* de la página del menú, y desde ahí se ve qué se está apagando.

### Cada tablero abre su propia ventana de terminal

*Abrir* en el menú no lanza un proceso mudo: abre una **ventana de Terminal nueva** con
la salida de ese tablero a la vista. Antes las cinco corrían con `stdout=DEVNULL`
colgando del menú, y lo que fuera mal solo dejaba rastro en el detalle de la tarjeta.

*Cerrar todo* cierra los puertos **y** esas ventanas, y son el mismo acto y no dos: el
menú hace **terminar el comando** que sostiene cada ventana, y Terminal la cierra sola
por el `shellExitAction` del perfil. Ir a por la ventana aparte exigiría AppleScript, que
es justo lo que no se puede usar aquí.

Medido de punta a punta con el menú real: `POST /abrir` deja la ventana corriendo y el
puerto sirviendo; `POST /apagar-todo` responde `{"cerrado": true, "vivas": []}`, los dos
puertos quedan libres, la ventana desaparece y no sobrevive ningún kernel de Voila.

Consecuencia que hay que tener presente **al tocar el apagado**: con el tablero en su
ventana, el menú **no tiene su proceso en la mano** — lo lanzó Terminal.app. Lo que el
menú ejecutó fue `open`, que vuelve en cuanto entrega el perfil. Por eso existe
`Aplicacion.en_ventana`, por eso `_esperar` no recibe ese proceso — verlo muerto le haría
rendirse en el acto y toda apertura saldría como *«el servidor no respondió»* con el
tablero levantándose detrás — y por eso el respaldo del apagado va al pid que la
aplicación deja escrito en `.servidor.pid`.

En Linux no hay ventana: no existe un emulador que se pueda dar por instalado, y adivinar
entre `gnome-terminal`, `konsole` y `xterm` es como se termina fallando en la máquina de
alguien. Allí el menú lanza en segundo plano, que es lo que hacía antes. Nunca se deja de
abrir el tablero por no haber podido abrir su ventana.

Cerrar son tres cosas, y las tres están medidas contra el servidor real:

1. **El proceso muere.** El botón manda un `POST` a `/apagar`; el servidor contesta
   `200 cerrando` y se apaga desde otro hilo. El proceso termina con código 0 a los
   **0,56 s**. Es `POST` y no `GET` a propósito: un `GET` que apaga el servidor lo
   dispara el prefetch del propio navegador, y el tablero se cerraría solo.
2. **El puerto queda libre.** Al salir se cierra el socket: `lsof` no devuelve nada y
   el puerto se vuelve a reservar en el acto.
3. **La pestaña se cierra sola**, en el caso normal. Medido abriendo por el mismo
   camino que usa `abrir-en-terminal.command`. La regla del navegador no es «solo se cierra lo
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
│   ├── terminal.py            abre una ventana de terminal NUEVA sin que Ghostty se la quede
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
un módulo y un título, y `_comun/construccion.py` hace el resto. Agregar una quinta
es copiar esos dos valores.

La 06 es la excepción, y por una razón concreta: su tablero no es un HTML sino
`ipywidgets` vivos, así que necesita un kernel. `preparar.py` congela lo caro en
`paquete/` y **genera** un cuaderno de una sola celda que importa el módulo; Voilà
sirve ese cuaderno. Antes ese cuaderno era una copia del 06 con seis parches de texto
encima, y cambiar una línea del original rompía la aplicación en un archivo que no la
mencionaba.

## Qué NO se guarda en el repositorio

Los entornos (`.venv/`), los tableros construidos (`panel/`), el paquete del
simulador (`paquete/`) y el cuaderno generado (`cuaderno/`) son artefactos de cada
máquina: se regeneran con `instalar` e `iniciar`.
