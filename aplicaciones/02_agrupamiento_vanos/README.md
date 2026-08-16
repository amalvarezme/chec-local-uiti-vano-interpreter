# 02 — Agrupamiento de vanos por UITI acumulado

Tablero de **vanos** de `src/chec_tableros/agrupamiento.py`, como aplicación local
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

---

# Cómo leer este tablero

> Rescatado de `notebooks/base_apps/02_uiti_vano_kmeans.ipynb` el 2026-08-15, cuando ese
> cuaderno se borró. El código del tablero vive en `src/chec_tableros/`; esto es lo
> único que el cuaderno tenía y que el módulo no podía heredar, porque no es código:
> es la explicación de qué se está mirando.

# Agrupamiento de circuitos por UITI acumulado y numero de eventos

Cuaderno autosuficiente y de una sola figura. Carga `data/Indicadores_vano_v3.csv`, acumula por
`CIRCUITO` el UITI (`UITI_VANO`) y el numero de eventos, y segmenta los circuitos con K-Means en
**4 grupos** (`Bajo`, `Medio`, `Medio-Alto`, `Alto`) sobre el espacio ajustado.

La figura viene con un panel de dos controles independientes:

- **Desde / Hasta**: calendarios que acotan el periodo sobre el que se acumulan UITI y eventos.
  Por defecto, el rango completo de la base.
- **Descargar etiquetas (CSV)**: baja la tabla de circuitos etiquetados con el periodo que este
  a la vista. La ultima celda hace lo mismo desde Python, con `tabla_etiquetas()` /
  `guardar_etiquetas()`: mismo esquema y mismo orden, para que los dos caminos no diverjan.

**El espacio de agrupamiento es fijo**: eje x lineal, eje y en `log10` y escalador `minmax`. Se
aplica *antes* de correr K-Means, asi que decide la particion y no solo como se dibuja. Antes se
elegia desde el panel, con dos casillas de log y un selector de preproceso; se quitaron para que
un grupo `Alto` signifique siempre lo mismo, sin depender de en que combinacion quedo el tablero
la ultima vez que alguien lo movio. Cambiar el periodo actualiza a la vez el scatter, los
contornos de membresia, las densidades marginales y el conteo de circuitos por grupo, sobre una
particion que no se mueve.

Los grupos no se nombran por el id que devuelve K-Means (que es arbitrario) sino por el **ranking
de la mediana del UITI acumulado**: `Bajo` es el de menor mediana y `Alto` el de mayor.

> **Los calendarios ajustan a mes completo.** El menor grano precomputable es el mes: un rango
> diario exacto daria 16.471 combinaciones, imposible de embeber. La alternativa seria reimplementar
> K-Means en JavaScript, y entonces la particion que ves dejaria de ser la que calcula scikit-learn.
> El panel avisa cual es el rango efectivo cada vez que cambias una fecha.

> **Por que el panel sale de una celda de codigo y no de markdown.** JupyterLab sanitiza las celdas
> de markdown: `<input>` y `<button>` estan en su lista de tags permitidos, pero `<script>` no, y
> tampoco ningun atributo `on*`. Un calendario puesto en markdown se dibujaria y quedaria muerto.
> En la salida de una celda de codigo si corre JavaScript -- es el mismo mecanismo por el que se
> dibuja Plotly. Requiere que el cuaderno este *trusted*, igual que la figura.

## Como leerlo

- Un punto es un **circuito**, no un vano: el eje x es cuantos eventos registro en el periodo
  elegido y el eje y cuanto UITI acumulo en ese mismo periodo.
- Las **regiones sombreadas** son la particion del plano, no un contorno de densidad: marcan
  que grupo le tocaria a un circuito segun donde caiga. Son celdas de Voronoi de los cuatro
  centroides, dibujadas en el espacio ajustado. Como ese espacio es fijo, las fronteras son
  siempre las mismas: cambiar el periodo mueve los circuitos, no la particion.
- **Los titulos de las barras y de los violines dicen cuantas muestras resumen** (`n = ...`).
  Sin ese numero, dos rangos con reparto parecido se leen igual aunque uno tenga la mitad de
  circuitos con eventos. Aca el conteo va en el titulo del EJE, porque este tablero no lleva
  titulos de subplot.
- Los **violines** muestran la distribucion completa de cada variable dentro de cada grupo,
  con su caja y su mediana. Son la contraparte por grupo de los KDE marginales: aquellos
  proyectan todos los grupos sobre un mismo eje, estos los separan.
- El **diagrama de barras** cuenta cuantos circuitos quedaron en cada grupo. El reparto sale
  desbalanceado a proposito: solo el eje del UITI va en `log10`, y esa es la variable que
  ordena los nombres.
- **Solo el eje y se transforma.** Las dos variables no tienen la misma forma: el UITI
  acumulado abarca varios ordenes de magnitud y en lineal los circuitos tranquilos se apilan
  contra el cero, mientras que el numero de eventos ya se reparte de forma legible. Antes las
  dos escalas se elegian desde el panel; ahora la combinacion es una sola.
- El nombre del grupo (`Bajo` a `Alto`) sigue siendo un ranking **relativo al periodo
  elegido**. Al mover los calendarios, cambia que circuitos entran y donde caen, pero no las
  fronteras: no es una etiqueta fija del circuito, aunque ya no dependa del espacio.

**Limitacion.** `k=4` es una decision operativa (cuatro niveles de riesgo para priorizar
mantenimiento), no un valor que estos dos features impongan. Este cuaderno no valida `k`; se
limita a mostrar la particion y a nombrarla de forma consistente.

---

# Segundo tablero: agrupamiento a nivel de vano

Mismo procedimiento y mismas visualizaciones que el tablero de circuitos, pero cambiando la
unidad: aqui cada punto es un **vano** (`FID_VANO`), no un circuito. Son 27.390 vanos contra 208
circuitos, asi que todo lo anterior se repite dos ordenes de magnitud mas denso.

> **Un rango corto vuelve el agrupamiento degenerado.** Sobre el rango completo la mediana es de
> 3 eventos por vano. Sobre **un solo mes**, apenas 10.089 de los 27.390 vanos registran algun
> evento y el **55,8% de esos tiene exactamente uno**, con mediana 1. El eje de eventos se
> aplasta contra el valor 1 y K-Means termina cortando casi solo por UITI. Los rangos cortos
> siguen disponibles, pero conviene leerlos sabiendo esto; el panel avisa cuantos vanos entraron.

> **Como entra tanto dato sin inflar el cuaderno.** Replicar el esquema del primer tablero
> (21 rangos x 8 espacios de coordenadas y etiquetas) pesaria unos 20 MB. En su lugar viaja una
> matriz **vano x mes** de 1,2 MB y el navegador suma los meses del rango elegido, que para una
> suma y un conteo da exactamente lo mismo. Los grupos tampoco viajan: se derivan de los
> centroides con la regla de centroide mas cercano, la misma que dibuja los contornos y que el
> cuaderno verifica contra las etiquetas de scikit-learn.

### Como leerlo

- Un punto es un **vano**, no un circuito. El mismo vano pertenece siempre al mismo circuito,
  que aparece en el tooltip, pero el agrupamiento no lo usa: se decide solo por los eventos y el
  UITI del propio vano.
- **Los titulos de las barras y de los violines dicen cuantas muestras resumen** (`n = ...`).
  El conteo es el de vanos con eventos en el rango elegido, no los 27.390 del total.
- Los grupos **no son comparables con los del primer tablero**, aunque compartan nombre. Son dos
  particiones distintas sobre unidades distintas: un vano `Alto` vive casi siempre en un circuito
  `Alto`, pero un circuito `Alto` contiene vanos de los cuatro grupos.
- El **contorno** es la particion del plano por celdas de Voronoi de los cuatro centroides, igual
  que arriba, y en el mismo espacio fijo: eje x lineal, eje y en `log10` y `minmax`. Las curvas
  marginales son densidades por grupo calculadas en el navegador con el mismo ancho de banda de
  Scott que usa `scipy`; el cuaderno compara ambas antes de embeberlas.

- La nube sale **rayada en vertical** y la densidad marginal de arriba, con picos: no es un
  artefacto de dibujo. A nivel de vano `num_eventos` es un entero pequeno (mediana 3), asi que
  todos los vanos con el mismo conteo caen exactamente en la misma abscisa. Un KDE sobre una
  variable discreta suaviza entre valores que no existen; conviene leer esa curva como la altura
  de cada barra entera, no como una densidad continua.

**Limitacion.** Con la mediana en 3 eventos por vano sobre el rango completo, y en 1 sobre un
mes, la coordenada de eventos aporta poca informacion a nivel de vano: buena parte de la
particion termina decidida por el UITI. Es una diferencia real respecto del tablero de circuitos,
donde las dos coordenadas pesan parecido, y el espacio fijo de este cuaderno -- con `log10` solo
en el UITI -- la acentua: el eje que mas separa es justamente el transformado.
