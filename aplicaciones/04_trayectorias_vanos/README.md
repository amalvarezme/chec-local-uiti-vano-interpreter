# 04 — Agrupamiento y evolución por vano

Tablero de `src/chec_tableros/trayectorias_vanos.py`, como aplicación local para
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

## El tablero ya no vive en un cuaderno

Desde el 2026-08-15 el código de este tablero está en
`src/chec_tableros/trayectorias_vanos.py`, y esta aplicación lo construye **importándolo**.
El `.ipynb` se borró: lo único que tenía y que el módulo no podía heredar era su
narrativa, que está al final de este mismo documento.

Con eso se retiró la regla «no limpies la salida de este cuaderno», que era la más
repetida del proyecto. Tenía dos motivos y los dos murieron: la geometría K-Means ya no
se extrae de ese HTML —vive versionada en `data/geometria_kmeans_014_v1.json`— y el
tablero ya no se publica desde su salida guardada.

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

> Rescatado de `notebooks/base_apps/04_uiti_vano_trayectorias_vano.ipynb` el 2026-08-15, cuando ese
> cuaderno se borró. El código del tablero vive en `src/chec_tableros/`; esto es lo
> único que el cuaderno tenía y que el módulo no podía heredar, porque no es código:
> es la explicación de qué se está mirando.

# Agrupamiento y evolucion a nivel de vano con ventana deslizante

Hermano de `03_uiti_vano_trayectorias_circuitos.ipynb`, con la unidad un nivel mas abajo: aqui
cada punto es un par **vano x ventana**, no circuito x ventana. Las ventanas son **las mismas**
que en el `03` -- mes calendario completo alternado con la cruzada del 15 al 15, once en total
sobre los seis meses de base.

Sobre ese plano corre un **K-Means a 4 grupos**, ajustado una sola vez sobre todas las celdas,
igual que en el `02`: los centroides y las fronteras de Voronoi no dependen de que circuito o
que vanos se elijan. El espacio es **fijo**: eje x lineal, eje y en `log10` y escalador
`minmax`. No se elige desde el panel, asi que la particion es la misma en cada apertura del
tablero y dos lecturas del mismo vano son comparables.

El panel trae:

- **Circuito**: acota el mapa y la lista de vanos, y **enfoca la nube**: sus celdas quedan sin
  transparencia y las de los otros 207 circuitos se atenuan.
- **Vanos** (lista de casillas): cada vano marcado toma un **color propio**, con su nombre en la
  leyenda de la figura, y ese color lo identifica en las tres vistas a la vez: sus celdas en la
  nube de agrupamiento y su serie en la evolucion. En el **mapa** el color sigue siendo el del
  grupo, siempre: los marcados se resaltan con halo, trazo mas ancho y opacidad, no con otro
  tono. Al marcar, la nube y el resto del circuito se atenuan. En la nube, las celdas de un
  mismo vano se **conectan con flechas** de la ventana mas antigua a la mas reciente, igual que
  la trayectoria del `03`.
- **Ventana del mapa**: slider sobre las once ventanas.

Un vano tambien se marca y se desmarca haciendo clic sobre el en el mapa.

Al ejecutar, el mismo tablero se escribe como HTML autocontenido en `reports/paneles/` y se abre
en el navegador, donde usa todo el ancho de la pantalla. Se desactiva con
`ABRIR_EN_NAVEGADOR = False`.

> **La escala del problema cambia.** Son 111.233 celdas vano x ventana con eventos, contra 1.738
> a nivel de circuito. El agrupamiento gana resolucion pero pierde interpretabilidad operativa:
> un vano con un solo evento fuerte cae en el mismo grupo que uno con muchos eventos pequenos.
> La lectura util es comparar vanos DENTRO de un circuito, que es para lo que sirve la lista.

## Como leerlo

- Un punto es un par **vano x ventana**. El mismo vano aparece hasta once veces, una por
  ventana, y puede caer en grupos distintos segun cuanto acumulo en cada una.
- Los grupos **no son comparables con los de 03**: alli la unidad era el circuito. Un vano
  `Alto` puede vivir en un circuito que a nivel agregado es `Medio`.
- Marcar vanos no reajusta nada: los centroides y las fronteras de Voronoi estan fijos, y la
  seleccion solo cambia que se resalta.
- **El color del mapa es el GRUPO, y no depende de la marca.** Todo vano con eventos en la
  ventana activa se dibuja con el color de su grupo de K-Means y con el ancho de vano de `01`
  (7 px), este marcado o no. Es la misma paleta de la nube, las barras y los violines, y como
  los centroides son unicos para todo el dataset ese color es comparable entre circuitos.
  Hasta el 2026-08-14 el color grueso era solo de los MARCADOS y el resto caia en la linea
  negra: desmarcar un vano no le quitaba el resaltado, le borraba el grupo, y un vano que
  tuvo eventos se dibujaba igual que uno que no tuvo ninguno.
- **La linea negra fina son los vanos SIN eventos en esa ventana.** Es la estructura del
  circuito, y los dos conjuntos son disjuntos: con celda arriba, sin celda aqui. Un guion
  horizontal marca los dos extremos de cada vano, del color que le toque, que es lo unico que
  distingue dos vanos vecinos del mismo grupo.
- **Marcar agrega, no reemplaza.** Al vano marcado se le suma un halo blanco, un trazo un 40%
  mas ancho y un recuadro; su color y su grosor de grupo siguen siendo los mismos. Al
  desmarcarlo se le quitan las tres cosas y se queda como cualquier otro vano con eventos.
- **El recuadro lleva el color del grupo del vano, al 50%.** Es un rectangulo girado a la
  direccion del propio vano, el mismo que dibuja el simulador del cuaderno `06`, con los
  mismos cuatro valores. "Cual estoy mirando" ya lo dicen el halo y el trazo mas ancho; el
  relleno agrega en que nivel cayo, que es una lectura que sobrevive al zoom en que la linea
  deja de distinguirse de sus vecinas. Un marcado SIN eventos en esa ventana no tiene grupo
  -- y eso no es el grupo mas bajo, es la ausencia del dato -- asi que su recuadro va gris y
  su trazo, negro pero con el ancho del resaltado.
- **El mapa no usa opacidad para nada.** Lo que distingue es color, presencia y grosor. Quien
  es cada vano marcado lo dicen la nube, la evolucion y el tooltip.
- **En la nube, un vano resaltado se pinta con el color de su grupo**, igual que cualquier otra
  celda: el mismo vano cambia de grupo entre ventanas y eso es justamente lo que las flechas
  cuentan. Su identidad se mueve al **anillo** del marcador, que si es fija y es la que lo enlaza
  con su serie de evolucion y con su linea en el mapa.
- **La opacidad plena es para las celdas del circuito elegido EN la ventana elegida.** Van a 1 y
  todo lo demas queda en 0.3: los otros circuitos, las otras ventanas del mismo circuito, y las
  dos cosas a la vez. Son dos niveles, no la cascada de tres de antes. La cascada graduaba nube /
  circuito / vanos marcados en tres tonos, y con el sujeto reducido a una celda no queda nada que
  graduar: un vano marcado se sigue distinguiendo por tamano y por su anillo de color, que es lo
  que dice de que vano es. Sin circuito elegido no hay interseccion y manda la ventana sola, o la
  nube entera quedaria uniforme. El mapa sigue su propia regla y dibuja los marcados un 40% mas
  anchos. Cambiar de circuito o desmarcar un vano recalcula todo, no acumula resaltados viejos.
- **Cuidado con los circuitos incompletos.** Un circuito no tiene por que tener celdas en las once
  ventanas. En las ventanas donde no las tiene no hay interseccion, y la nube queda entera en 0.3
  sin ningun punto resaltado. Eso es el dato, no una falla.
- **El punto de la ventana vigente en la evolucion se dibuja al triple**, igual que el dia vigente
  en la serie del cuaderno `01`, y viaja con el deslizador en vivo. Lo caro -- la opacidad de las
  110 mil celdas y el reparto por grupo -- se repinta con un retardo de 140 ms, asi que al
  arrastrar el punto grande va adelante y la nube se acomoda al soltar.
- **Las flechas viven en esta misma figura**, no en la evolucion: van de la ventana mas vieja a la
  mas nueva, llevan el color de identidad del cupo y solo unen ventanas en que el vano tuvo
  eventos. Un vano presente en las once ventanas dibuja diez tramos. Si dos ventanas consecutivas
  arrojan las mismas coordenadas -- pasa cuando un unico evento cae en el solape de ambas -- el
  tramo queda de longitud cero y no se ve: no es un error, es que el vano no se movio.
- **Las barras y los violines describen UNICAMENTE los vanos marcados en la ventana elegida.**
  Sin marcas quedan vacios a proposito: elegir circuito no los puebla. Un reparto de 27.390 vanos
  y otro de tres se dibujan igual pero no miden lo mismo, y sin nada que los distinga se leerian
  como si fueran la misma medida. Sus escalas se fijan sobre todas las ventanas de esa misma
  seleccion, para que mover el slider muestre un cambio real y no un reencuadre. La nube de fondo
  si lleva las once ventanas y todos los vanos: el reparto es un corte de lo dibujado, no su
  resumen.
- En la **evolucion** la linea lleva el color del vano y el **punto el color de su grupo en esa
  ventana**, con la paleta del agrupamiento, igual que en 03. Un punto gris es una ventana sin
  eventos, que no tiene grupo -- distinto de caer en el mas bajo. La linea punteada vertical
  marca el cambio de ano, que los rotulos del eje no muestran.
- Las **flechas** de la nube van siempre de la ventana mas vieja a la mas nueva y solo unen
  ventanas en que el vano tuvo eventos: si el vano omite una, la flecha une las dos ventanas con
  dato, no pasa por el cero.
- **La lista de casillas es el CIRCUITO, no la ventana.** Trae los vanos que registraron
  eventos en todo el periodo, asi que no cambia al mover el deslizador: lo que cambia es
  quien esta marcado. Antes la lista se rehacia en cada paso, y las casillas se movian bajo
  la mano justo mientras se estaba eligiendo.
- **La marca automatica tiene dos momentos.** Al elegir circuito se marcan los quince vanos
  de mayor UITI acumulado en TODO el periodo -- la misma lista que dibuja el panel "Perfil
  del circuito" del cuaderno `06` --, que es la pregunta con la que se aterriza: donde esta
  concentrado el riesgo. Al mover el deslizador se marcan los quince de mayor UITI en ESA
  ventana. Es un reemplazo y no una suma: acumular ventanas dejaria marcado todo lo que
  alguna vez tuvo un evento. Ese top puede concentrarse en un mes y dejar a los quince sin un
  solo evento en la ventana con la que abre el tablero -- pasa en AGU23L12, cuyo top del
  periodo vive en V3-V4 y no comparte ni un vano con V1 --: ahi van todos en negro con el
  ancho del resaltado, y el aviso del panel lo dice.
- **Un vano se marca y se desmarca tambien haciendo clic sobre el en el mapa**, sobre su linea
  negra o sobre su trazo de color. El clic no lleva un registro propio: alterna la misma
  casilla de la lista, asi que lista, mapa, nube y reparto no pueden contar cosas distintas.
  La casilla se trae a la vista al cambiar, porque en un circuito de cientos de vanos suele
  quedar fuera del scroll.
- **Los titulos de las barras y de los violines dicen cuantas muestras resumen** (`n = ...`).
  Es el numero de celdas contadas: vanos marcados CON eventos en la ventana elegida. Con cero
  marcados los tres paneles quedan vacios y el `n` lo dice.
- **Se identifican hasta treinta vanos a la vez**, el mismo tope del simulador del cuaderno
  `06`. Son dos numeros encadenados: la marca automatica pone hasta quince y desde ahi se
  puede seguir agregando a mano, con la casilla o tocando el vano en el mapa, sin tope. El
  doble deja sitio a los quince automaticos mas quince elegidos. La paleta tiene quince tonos
  -- no hay quince mas que sean de verdad distinguibles --, asi que se recorre en circulo y
  la segunda vuelta va con la linea discontinua. Marcar mas de treinta no se ignora: los que
  sobran se resaltan igual en el mapa, en gris, pero sin color propio, sin flechas y sin
  serie de evolucion, y el aviso del panel dice cuantos quedaron asi.

- **El mapa se encuadra sobre el tamano real que tiene en pantalla.** El zoom sale de un
  `fitBounds` en Web Mercator, no del ancho del circuito en grados, y se rehace al cambiar el
  tamano de la ventana: por eso el circuito entra completo tanto en la celda del cuaderno como
  a pantalla completa en el navegador.

**Limitacion.** A nivel de vano la mediana es de pocos eventos por ventana, asi que la
coordenada de eventos aporta poca informacion y buena parte de la particion la decide el UITI.
La lectura util es comparar vanos dentro de un mismo circuito, no leer los grupos como una
clasificacion absoluta.
