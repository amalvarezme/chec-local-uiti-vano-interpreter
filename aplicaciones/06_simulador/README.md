# 06 — Simulador de riesgo por vano

Simulador de `src/chec_tableros/simulador/`, como aplicación local para macOS y
Windows: el mapa histórico y el de criticidad simulada, la selección de hasta 15 vanos,
las 26 variables simulables, el top de variables por vano, el grafo de relevancia y el
costo del plan.

Son dos módulos porque son dos ciclos de vida: `derivacion.py` corre al **construir** el
paquete y `tablero.py` corre en **cada apertura**, dentro de un kernel vivo.

Es la única de las tres que necesita **Python en ejecución**. El botón *Simular* corre
el modelo MIL de PyTorch sobre los vanos marcados y con los valores escritos: 26
variables sobre hasta 15 vanos no es un espacio precomputable.

## Uso

| macOS | Windows | qué hace |
|---|---|---|
| nada: `Iniciar.app` lo hace solo | `instalar.bat` (doble clic) | una sola vez: crea el entorno e instala las dependencias |
| **`Iniciar.app`** (doble clic) | **`iniciar.bat`** (doble clic) | construye si hace falta y sirve el simulador |

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
`--reconstruir`.

`iniciar` **reconstruye por su cuenta** si cambió cualquiera de sus insumos: usar un
paquete viejo con insumos nuevos es la única forma de que el tablero dibuje datos que ya
no corresponden sin dar error. El manifiesto guarda una huella por insumo bajo
`insumos` — sha1 para los cuatro archivos que viajan dentro del paquete y para todo
`src/` como un solo árbol, bytes + fecha para los pesados (el CSV de 540 MB, las bolsas
y los tres shapefiles) —, y al arrancar dice cuál se movió. La comprobación cuesta 1 ms.

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

Derivar abre el CSV de 540 MB, lee 180 MB de shapefiles y carga 190 MB de bolsas, para
terminar con objetos dos órdenes de magnitud más pequeños. Eso vive en
`chec_tableros.simulador.derivacion`, con dos caminos que devuelven el **mismo** objeto:
`derivar()` lo calcula y `cargar(paquete)` lo lee congelado. El constructor llama al
primero y la aplicación al segundo, y por eso el tablero no sabe cuál corrió.

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

El tablero son ~3.200 líneas de `ipywidgets` sobre un `go.FigureWidget`. Voila hace
falta porque `ipywidgets` necesita un kernel al otro lado; reescribirlo en Dash o
Streamlit obligaría a mantener dos tableros que tendrían que coincidir para siempre.

## El cuaderno que se sirve tiene una celda

Vive en `cuaderno/06_simulador.ipynb`, lo escribe `preparar.py` en cada construcción y
no se versiona. Entero:

```python
PAQUETE = Path(os.environ['PAQUETE_06']).resolve()
...
display(tablero.construir(
    derivacion.cargar(PAQUETE),
    costos=PAQUETE / 'Actividades_mantenimiento_costos_2026.xlsx',
    encabezado=[cierre.barra()],
))
```

**Antes eran seis parches de texto** sobre el cuaderno 06 —una copia de veinte celdas
donde se reescribían la ruta de la geometría, la llamada de arranque, el botón de
cerrar y un silenciador de `print` y `display`—, cada uno exigiendo que su marca
apareciera exactamente una vez. Funcionaba, y el precio era que cambiar una línea del
cuaderno rompiera la aplicación en un archivo que no lo mencionaba.

Lo que aquellos parches distinguían —de dónde salen los datos y dónde están los
catálogos— son hoy los parámetros de `construir()`. Lo que silenciaban ya no existe:
un módulo no imprime.

La comprobación de que **ningún camino reabre el CSV ni los shapefiles** sigue en pie y
sigue mirando el código y no los comentarios; lo que cambió es dónde mira
(`tests/test_simulador_cuaderno_generado.py`).

El cuaderno generado declara su **propio kernel** (`chec-simulador-vano`), registrado
dentro del entorno de la aplicación. `python3` es el nombre que usa todo el mundo y
Voila lo resuelve contra los kernels instalados en la máquina: sin un kernel propio, se
le vio arrancar el intérprete de otro proyecto ya borrado y responder 500.

## Verificación

El paquete se compara **byte a byte** contra un golden congelado antes de que existiera
`derivacion.py` (`tests/test_simulador_derivacion.py`): un dtype, un orden de columnas o
un redondeo de coordenada distinto se propagaría al simulador sin dar ningún error.

| | original | con el paquete |
|---|---|---|
| celdas vano×ventana | 111.231 | 111.231 |
| matriz de instancias | (288.632, 80) `float32` | idéntica |
| controles | 26 | 26 |
| circuitos | 208 | 208 |
| una simulación real | `u_base` y `u_simulado` | **idénticos a 10 decimales** |

Y el tablero **conducido de verdad**: Voila en un puerto propio y Chrome por CDP,
cambiando de circuito, marcando vanos, aplicando lo sugerido y simulando
(`tests/test_simulador_flujo_vivo.py`, 20 pruebas, ~8 min). Lo que afirman no es que
las trazas tengan datos sino que **lo dibujado se vea**: el fallo que las motivó tenía
las trazas llenas y el 4,2 % dentro del recuadro visible.

```
SIMULADOR_VIVO=1 pytest tests/test_simulador_flujo_vivo.py -q
```

Necesitan Chrome, el entorno de esta aplicación instalado y el paquete construido. Si
se piden y falta algo, **fallan al recolectar en vez de saltarse**: unas pruebas que se
saltan en silencio se leen igual que unas que pasan, y así una de ellas afirmó durante
semanas un título de panel que ya se había acortado.

## Requisitos

Python 3.10+ y, para **construir**, el repositorio con:

- `data/Indicadores_vano_v3.csv` (`git lfs pull`)
- `data/GEO/MVLINSEC.shp` y compañía
- `data/models/mil_vano_ventana_v1.pt` y `data/derived/bolsas_mil_full.joblib`
  — los produce `05_mil_vano_ventana.ipynb`
- `data/geometria_kmeans_014_v1.json` — versionado, lo produce
  `scripts/exportar_geometria.py`

Una vez construido el paquete, la aplicación no vuelve a abrir ninguno de ellos, con
**una excepción anotada**: `data/Variables_seleccion.xlsx`, que el tablero lee en cada
apertura para nombrar las variables del panel. No viaja dentro del paquete.

---

# Cómo leer este tablero

Lo que sigue venía de las celdas de texto del cuaderno
`notebooks/base_apps/06_uiti_vano_explicabilidad_simulador.ipynb`, que era la fuente
del tablero hasta que su código pasó a `src/chec_tableros/simulador/tablero.py`. Es la
parte que no está en ningún otro sitio: la pregunta que responde cada panel, la
matemática del ranking y de qué exactamente son los números que se ven.

Se traslada tal cual, con una salvedad honesta: **la sección final habla de
«violines»**, y esos dos paneles son hoy **barras** —una medida y una simulada por
vano—. Lo que dice sobre *de dónde salen los dos números* sigue siendo exacto: son las
mismas dos pasadas del modelo sobre las mismas bolsas. Lo que ya no aplica es la forma
del dibujo y el `points='all'` que la acompañaba. Se marca en vez de reescribirse
porque reescribir 800 líneas de prosa que nadie ha vuelto a verificar es la forma de
convertir una salvedad conocida en varias desconocidas.

## El tablero

Todo lo de arriba es preparacion; **lo que se usa es esto**. Al ejecutar la
celda siguiente aparece el tablero completo y ya no hace falta volver a subir.

**Por donde empezar**

1. Elige **circuito** y **ventana**. El deslizador arranca en la ventana mas
   reciente con eventos de ese circuito y solo recorre las que ese circuito
   tiene. En cuanto eliges circuito, el **perfil del circuito** -- la fila que
   va debajo de los mapas -- ya te dice donde esta concentrado el riesgo, sin
   tocar nada mas.
2. **Diagnostico** responde *por donde empiezo*: estudia los vanos que
   hayas marcado y, si no llegan a quince, completa con los de mayor UITI
   de la ventana activa. Sin nada marcado toma directamente ese top. Deja
   marcados los que eligio y lista que los bajaria de grupo.
3. **Aplicar intervencion** o **Aplicar escenario** abre los controles de esos
   vanos en el valor sugerido. Cada boton trae **solo su mitad**; presiona los
   dos si quieres ver las dos juntas.
4. **Simular** puntua la seleccion y llena el mapa de la derecha, las series,
   los violines y el costo.
5. **Guardar** archiva esa corrida; **Cargar** vuelve a ella. Ver mas abajo.

Tambien se puede marcar vanos con las casillas o haciendo clic sobre el mapa
base, y mover a mano cualquier variable sin pasar por el diagnostico.

## Guardar una corrida y volver a ella

Debajo de *Simular* y *Limpiar*, el panel trae **Guardar** y **Cargar**.

**Guardar** solo se habilita con una simulacion en pantalla -- guardar antes
archivaria un tablero vacio -- y escribe **dos** archivos con el mismo nombre
base:

| archivo | tamanio | para que |
|---|---|---|
| `<circuito>_<ventana>_<fecha>.html` | ~6 MB | el **informe**: las ocho figuras y las tres tablas |
| `<circuito>_<ventana>_<fecha>.simchec.json.gz` | ~1-20 KB | el **registro** con el que *Cargar* vuelve a esa corrida |

El informe se abre con doble clic y no necesita nada instalado: plotly.js viaja
dentro. Lleva la tabla de **vanos y variables simuladas** con el valor fijado de
cada una, una tabla **por vano** con las actividades del contrato -- numero de
intervenciones, costo unitario, descripcion y costo total --, y la tabla que
contrasta el **UITI medido contra el simulado** vano por vano con su porcentaje
de mejora o de subida y el total de las dos columnas. Lo unico que pide por red
es el mapa de fondo de las dos primeras figuras; los vanos se dibujan igual sin
internet.

**Donde quedan.** En `~/CriticidadCHEC/simulaciones` -- o sea
`/Users/<tu-usuario>/CriticidadCHEC/simulaciones` en macOS y
`C:\Users\<tu-usuario>\CriticidadCHEC\simulaciones` en Windows. Cuelgan de tu
carpeta personal y **no** de esta aplicacion a proposito: la aplicacion se
reconstruye sola cuando cambian los datos, y en Windows hay un `.bat` que la
traslada a una ruta corta.

No hay que recordarla: el panel la publica **siempre**, en el renglon que va justo
debajo de la lista desplegable, desde que el tablero abre y aunque no se haya
guardado nada todavia. Al guardar, debajo aparecen los nombres de los dos archivos
que acaba de escribir.

### Por que el registro pesa kilobytes y no megabytes

Porque **no guarda las figuras**. Lo que hay en pantalla se deriva entero de
correr el modelo MIL sobre las entradas, asi que congelarlo seria guardar el
valor de retorno de una funcion al lado de sus argumentos: dos versiones de lo
mismo que se separan en cuanto alguien reentrena. El registro guarda las
ENTRADAS -- circuito, ventana, vanos, el valor de cada variable y las
actividades con sus repeticiones -- y *Cargar* las repone y **vuelve a simular**.

El precio de esa decision es que un modelo reentrenado devuelve otros numeros, y
se paga diciendolo: el registro lleva la firma de los artefactos con los que
corrio, y al cargar el panel avisa si no coinciden. El informe HTML que se
guardo ese dia sigue siendo el registro fiel de lo que se decidio entonces.

Es ademas `gzip` de JSON, no un formato propio: quien audite una decision dentro
de dos anios puede abrirlo sin este programa.

### En Databricks

El mismo tablero, con los mismos dos botones. Alli las corridas van al **Volume**
de Unity Catalog -- `/Volumes/<catalogo>/<esquema>/chec-simulador/simulaciones` --
y no al disco del contenedor, que es efimero y que el usuario no puede alcanzar.
Se bajan desde **Catalog → Volumes** en la interfaz del workspace. La carpeta la
crea `/subir-a-databricks`, y la app necesita `WRITE_VOLUME` sobre ese Volume;
sin ese permiso el tablero simula igual y solo falla al pulsar *Guardar*.

> El codigo de las celdas esta plegado. Para leerlo, despliega la celda desde
> el margen izquierdo; lo que hace cada pieza esta explicado en las celdas de
> texto de arriba y de abajo.

## La matematica del ranking: como se busca el grupo Bajo

Esta celda describe lo que calcula la fila 3, columnas 3-4 del tablero de abajo, y el
plan que aparece bajo el panel. Va **antes** del tablero a proposito: sin ella, las
barras se leen como "importancia" generica, que es justo lo que NO son.

### La pregunta

No es *que variable explica el UITI de este vano* -- esa es la pregunta de SHAP -- sino
**que muevo, y a que valor, para que este vano baje al grupo Bajo**. Son preguntas
distintas y sus respuestas no coinciden: sobre un vano real, el ranking por sensibilidad
y el ranking por caida alcanzable **no comparten ni una** de sus cinco primeras
variables.

### La meta, que si existe

La clase de una bolsa sale de la geometria KMeans de 01.4 sobre
$\zeta_b=(n_b,\ \log_{10}\hat u_b)$, y $n_b$ -- los eventos observados -- **no se simula
nunca**. Con $n_b$ fijo, la clase solo depende de $\hat u$, asi que existe un umbral:

$$u^{\star}(n_b)=\max\{\,u>0 \;:\; \arg\min_k\lVert\zeta(n_b,u)-c_k\rVert = 0\,\}$$

Se resuelve por **rejilla** y no por biseccion: nada garantiza que al subir $u$ con $n_b$
fijo se recorran los grupos en orden, y una biseccion asume esa monotonia.

Medido sobre la geometria real, $u^{\star}$ existe en todo el rango de eventos observado,
pero **se desploma** al acumularse eventos:

| $n_b$ | 1 | 5 | 10 | 20 | 30 | 46 |
|---|---|---|---|---|---|---|
| $u^{\star}$ | 4,41 | 3,93 | 3,37 | 1,15 | 0,114 | 0,0029 |

Un vano con muchos eventos necesita un UITI casi nulo para bajar de grupo. Es una
propiedad del espacio de criticidad, no del simulador.

### El ranking: una variable a la vez

Para cada control $\kappa$ que el panel ofrece se recorre su conjunto de candidatos
$\mathcal{G}_\kappa$ -- una rejilla de $G=9$ valores si es numerico, **sus categorias** si
es categorico -- moviendo sus columnas $F(\kappa)$ a la vez, y se guarda el valor que
**minimiza** el UITI de cada bolsa:

$$v^{\star}_{b,\kappa}=\arg\min_{v\in\mathcal{G}_\kappa}\hat u_b\!\left(X^{\kappa\to v}\right),
\qquad
\hat u^{\star}_{b,\kappa}=\min_{v\in\mathcal{G}_\kappa}\hat u_b\!\left(X^{\kappa\to v}\right)$$

La barra mide la **caida en ordenes de magnitud**, que es el eje que usa la geometria, y
el hover trae la fraccion del camino que cubre:

$$c_{b,\kappa}=\log_{10}\hat u_b(X)-\log_{10}\hat u^{\star}_{b,\kappa},
\qquad
\text{avance}_{b,\kappa}=\frac{c_{b,\kappa}}{\log_{10}\hat u_b(X)-\log_{10}u^{\star}(n_b)}$$

En unidades de UITI el ranking de un vano caro seria incomparable con el de uno barato;
en ordenes de magnitud, dos barras de la misma altura significan lo mismo en cualquier
grupo. La barra se pinta **verde** cuando $\hat u^{\star}_{b,\kappa}\le u^{\star}(n_b)$:
esa sola variable cambia de grupo.

**Se recorren todos los controles del panel, tambien los categoricos.** El barrido
anterior los saltaba, y con ellos se caian del ranking el conductor, el calibre del
neutro y el tipo de proteccion -- tres obras que CHEC ejecuta. Ademas el top **reserva
sitio para los dos grupos**, intervencion y escenario: sin la reserva, las cuatro
familias climaticas copan la lista y no queda ni una palanca que una cuadrilla pueda
ejecutar.

### Por que dejo de ser un barrido min-max

Los dos defectos, los dos medidos sobre este modelo:

- $s=\max(|\Delta^-|,|\Delta^+|)$ **no lleva signo**: una variable que dispara el riesgo
  en los dos extremos encabezaba el ranking, y la cabeza de la lista se llenaba de
  palancas que no hay que tocar.
- Solo miraba los **dos extremos**. **10 de los 15** controles numericos tienen su optimo
  en el INTERIOR del rango para alguna bolsa (`DDT` para todas): la funcion no es
  monotona y los extremos son los dos puntos equivocados.

### El plan: la combinacion, porque una variable casi nunca basta

Medido sobre **59 bolsas de 40 circuitos**:

| Grupo | Bolsas | Alcanzan Bajo con UNA variable | Avance de la mejor (mediana) |
|---|---|---|---|
| Medio | 33 | 20 / 33 (**61%**) | 100% |
| Medio-Alto | 18 | **0 / 18 (0%)** | 60% |
| Alto | 8 | **0 / 8 (0%)** | 49% |

En Medio-Alto y Alto **ninguna variable sola alcanza jamas**. No es la rareza de un vano:
es el caso normal justo en los grupos donde la pregunta de mantenimiento pesa. Por eso el
plan combinado no es un adorno del ranking, es su continuacion.

Es un **descenso por coordenadas, goloso**. Partiendo del estado observado $X^{(0)}=X$, en
cada ronda se prueban todos los candidatos de todos los controles que ese vano no haya
usado todavia, y se aplica el que mas baja su UITI:

$$(\kappa_t,v_t)=\arg\min_{\kappa\notin\mathcal{U}_{t-1},\,v\in\mathcal{G}_\kappa}
\hat u_b\!\left(X^{(t-1),\,\kappa\to v}\right),
\qquad
\mathcal{U}_t=\mathcal{U}_{t-1}\cup\{\kappa_t\}$$

Se detiene al cumplir $\hat u_b\le u^{\star}(n_b)$, al agotar los $T=4$ pasos, o cuando
ningun candidato mejora. Cada control entra **como mucho una vez**: un plan que reajusta
dos veces la misma variable no es una orden de trabajo mas barata, es la misma obra
contada dos veces.

**Goloso y no exhaustivo, dicho de frente.** Con 18 controles y 9 valores, dos cambios
simultaneos ya son 13 mil combinaciones y cuatro son 26 millones -- fuera del presupuesto
de un boton que debe sentirse inmediato. El plan es **bueno, no demostrablemente el
minimo**. Y cuando ni moviendolo todo se llega, se reporta lo conseguido y se dice que no
alcanza, que vale mas que un plan que insinua lo contrario.

### Lo que cuesta

| Paso | Pasadas de bolsas |
|---|---|
| Mapa simulado (base + simulado) | 2 |
| Compuertas para el grafo | 1 |
| Ranking (base compartida + rejilla) | $1+G\,K$ |
| Plan (por ronda, hasta agotar los pendientes) | $\le T\,G\,K$ |

$K$ son los controles que el panel ofrece y $G$ sus candidatos. Las rondas del plan se
**comparten entre vanos**: un candidato se aplica a la vez sobre el estado propio de cada
bolsa y la pasada devuelve un $\hat u$ por bolsa, asi que cada vano elige su mejor paso
sin que la ronda cueste una tanda por vano.

## Como leerlo

**Los dos mapas.** A la izquierda, la criticidad historica; a la derecha, la simulada.
Van lado a lado y no apilados: la unica comparacion que justifica que haya dos mapas es la
del mismo vano antes y despues de simular, y apilados obligaba a mover la vista de arriba
a abajo para hacerla. Nunca comparten leyenda ni titulo, porque mezclarlos invita a leer
una prediccion como un hecho observado.

Arrancan con el mismo encuadre, pero **al simular el mapa de la derecha se acerca a los
vanos marcados**. Se paga a sabiendas que los dos dejen de mirar la misma geografia: una
vez que el modelo corrio, la pregunta ya no es donde queda el circuito sino que le paso a
ESOS vanos, y buscarlos otra vez dentro del garabato completo es trabajo que el tablero
puede ahorrar. El de la izquierda conserva SIEMPRE el encuadre del circuito, que queda
como la referencia contra la cual se lee el acercamiento; y desmarcar todo devuelve al de
la derecha a esa misma vista.

**El perfil del circuito.** Los quince vanos que mas UITI acumulan en TODA la serie, de
mayor a menor. Es el unico panel que no depende ni de la ventana ni de lo que este
marcado: se dibuja en cuanto eliges circuito y no vuelve a moverse hasta que elijas otro.
Contesta la pregunta con la que se aterriza en un circuito y que ningun otro panel
contesta -- los dos mapas y la serie de tiempo miran UNA ventana a la vez, y averiguar si
el riesgo esta repartido o concentrado obligaba a recorrer las once con el deslizador.

El titulo publica la lectura, que es lo que no cabe en una barra: *"15 de 47 vanos con
eventos concentran el 88,3% del UITI del periodo"*. Ese numero es el panel. Un circuito
de 47 vanos donde quince se llevan el 88% se interviene por lista corta; uno de 362 donde
los quince primeros suman el 22,5% -- AMR23L13, medido -- no tiene lista corta que valga,
y saberlo antes de marcar vanos ahorra la ronda entera.

**El total NO es la suma de las once ventanas, y esa es la trampa.** Las ventanas se
traslapan: seis son meses calendario y cinco son cortes del 15 al 15 hacia el mes
siguiente, asi que casi todo evento cae en DOS y sumarlas lo cuenta dos veces.
`perfil_uiti_por_vano` suma solo sobre el subconjunto que embaldosa el periodo una vez.
Lo que costaria equivocarse esta medido sobre las 111.231 celdas: la suma ingenua infla
el total de un vano entre 1,00 y 2,09 veces, y como el factor **no es constante tampoco
se cancela al ordenar** -- 74 de los 208 circuitos cambian su top 15. El panel seguiria
dibujando quince barras perfectamente plausibles, solo que de los vanos equivocados.

Las barras van de un solo color a proposito. En el top de variables la rampa de opacidad
separa diez barras que miden lo mismo; aqui el LARGO ya dice la posicion, y una rampa
encima seria el mismo dato dos veces. El detalle -- eventos, en cuantas ventanas aparece,
que fraccion del circuito se lleva -- viaja en la etiqueta del mouse.

**Una sola leyenda, horizontal y debajo de los mapas.** Vertical y a la derecha se
llevaba 196 px medidos de ancho -- una columna entera de la fila 3 -- para decir siete
nombres. Y es UNA sola para los dos mapas: usan la misma geometria KMeans de 01.4, asi
que las cuatro clases significan exactamente lo mismo en los dos y repetirlas era decir
dos veces la misma escala.

**El rango de un control sale de valores reales.** `ALTURA` usa 99 como codigo de "sin
dato" -- 327 registros, y el siguiente valor real es 25; un poste de 99 m no existe en
una red de distribucion. Se excluye del rango y del valor inicial, asi que el deslizador
va de 4 a 25 y no de 4 a 99, donde 74 de sus 95 puntos de recorrido caian en un tramo
que ningun vano puede ocupar. Se declara variable por variable en
`vano_controls.VALORES_NO_VALIDOS`: una regla automatica del tipo "los nueves son
relleno" tumbaria el 9 de `LONG_CRUCETA` y el 10 de `VAL_CRIT_APOYO`, que son reales.

**La tabla de variables** dice, de cada control, su rango real y si simularlo significa
algo. No todas las variables del modelo son palancas: unas se mueven con una cuadrilla (la
poda, la puesta a tierra, el conductor), otras son escenarios que nadie controla pero que
son justamente el what-if (el clima, las descargas, el crecimiento de la demanda), otras
describen lo que el vano ES y no algo que se le pueda hacer, y una -- los trafos afectados
EN LA FALLA -- se mide despues del evento que el modelo intenta anticipar, asi que
simularla es circular. El veredicto y su motivo salen del diccionario del propio proyecto
y viven en `simulador_variables.JUICIO_SIMULACION`, con sus pruebas.

La tabla trae la **unidad de medida cuando aplica**: un rango sin unidad no se puede
juzgar -- 25 puede ser una altura razonable o un disparate segun si son metros o pies.
Quedan sin unidad las categoricas, las binarias, los indices como `NR_T` y
`VAL_CRIT_APOYO` -- que son puntajes y no magnitudes -- y `DDT`, cuya descripcion
implica una unidad por area pero no dice cual; antes que estampar una equivocada, la
celda queda vacia.

**Las variables del simulador van en cuatro columnas**: dos para lo que se puede hacer
-- intervencion -- y dos para lo que se quiere anticipar -- escenario. Una lista corrida
de dieciocho casillas obliga a recordar el veredicto de cada una para saber a cual de
las dos preguntas pertenece; en columnas eso lo dice la posicion.

**El panel se alinea con el AREA DE DIBUJO de la figura, no con su borde.** Los dos
ocupan el mismo ancho, pero la figura reserva margen a la izquierda para los rotulos de
los ejes de la primera columna, asi que sus paneles empiezan mas adentro que los
controles. El relleno del panel se deriva de ese margen -- no se escribe a mano -- para
que cambiar uno mueva al otro.

**Las variables refutadas y las de lectura unica ya no aparecen en el panel.** Mientras estuvieran ahi, el
tablero las ofrecia como equivalentes a la poda o a la puesta a tierra. Las "Limitado"
salen por el mismo motivo: hay UNA lectura bajo la cual se interpretan -- adelantar una
fecha equivale a reponer el activo -- y un deslizador no puede transmitir esa condicion,
quien lo mueve ve el numero y no el motivo. Quitarlas NO las
saca de la simulacion: un override solo se escribe si se fija, asi que entran al modelo
con el valor OBSERVADO de cada vano, que es exactamente lo que corresponde -- lo unico
que se pierde es poder moverlas. El panel las nombra debajo de la lista de variables, o
acortarse sin explicacion se leeria como que faltan.

**Negro = sin evento**, en los dos mapas. Un vano sin eventos en la ventana no tiene clase,
y la ausencia no es el grupo mas bajo. En el mapa simulado el negro cubre ademas lo que
quedo fuera de la seleccion.

**La lista de vanos es el CIRCUITO, no la ventana.** Trae los que registraron eventos en
todo el periodo, asi que no cambia al mover el deslizador: lo que cambia es quien esta
marcado. Se recorto a la ventana durante un tiempo, y el precio fue peor que el problema
que resolvia -- las casillas se rehacian en cada paso y un vano que se venia siguiendo
desaparecia al avanzar un mes. Lo que aquel recorte protegia -- pulsar "Simular" y no ver
aparecer nada -- lo dice ahora el renglon de aviso bajo la lista, que cuenta cuantos de los
marcados tienen celda en la ventana activa. Decirlo es mejor que impedirlo: un vano sin
eventos en marzo sigue siendo el vano que interesa, y su serie de tiempo es justo donde se
ve que en febrero si los tuvo.

**La marca automatica tiene dos momentos.** Al elegir circuito se marcan los quince vanos
de mayor UITI acumulado en TODO el periodo -- las mismas quince barras del panel "Perfil
del circuito" --, que es la pregunta con la que se aterriza. Al mover el deslizador se
marcan los quince de mayor UITI en ESA ventana; es un reemplazo y no una suma, porque
acumular ventanas dejaria marcado todo lo que alguna vez tuvo un evento. El boton "Top de
la ventana" rehace esa marca sin tener que mover el deslizador y volver.

**Desde ahi se agrega y se quita sin tope**, con la casilla o tocando el vano en el mapa.
El selector tuvo un tope de quince y lo perdio: lo que protegia era la rejilla de controles
-- una columna por vano --, y eso lo resuelve hoy la paginacion. A cambio hacia dos cosas
que estorbaban: deshabilitaba las casillas sin marcar en cuanto la marca automatica llenaba
el cupo -- o sea, casi siempre -- y el clic en el mapa se rechazaba en silencio. Se dibujan
hasta **treinta** series de tiempo; pasado ese numero el mapa sigue resaltando y el
simulador sigue puntuando, pero la serie no tiene ranuras y el aviso lo dice.

**Cada vano marcado recibe su propia COLUMNA de controles** abajo del panel, rotulada con
el vano que gobierna, y cada control abre en el valor ACTUAL de esa variable para ESE vano
en la ventana activa -- la mediana de sus instancias, o la moda si la variable es
categorica. Eso es lo que permite preguntar "que pasa si podo SOLO este": los demas vanos
quedan exactamente como estaban, no en un valor por defecto. Sin ningun vano marcado el
grano vuelve a ser el circuito completo y hay una sola columna, cuyos valores se aplican a
todo. Un vano marcado SIN eventos en la ventana activa no recibe columna -- no hay valor
actual desde donde arrancar -- y el pie de la rejilla lo nombra en vez de dejarlo
desaparecer en silencio.

**"Diagnostico"** contesta la pregunta con la que se abre una jornada -- por
donde empiezo aqui -- que ninguna otra vista del tablero contesta: el mapa exige mirar
tramo a tramo y el panel exige haber elegido ya los vanos.

**Que vanos estudia.** Lo que hayas marcado manda -- por casilla o tocando el vano en el
mapa --, y si no llega a **quince** la lista se completa con los de **mayor UITI** de la
ventana activa. Sin nada marcado toma directamente ese top, que es como nacio el boton. Un
vano marcado sin eventos en la ventana no entra -- el modelo no lo puede puntuar -- y el
panel lo nombra. Cuando el circuito tiene mas de quince vanos con eventos, el panel dice
cuantos quedaron fuera: la via para llegar a ellos es marcarlos y volver a pedirlo, no un
tope mas alto. Sobre el conjunto elegido reporta las variables de **intervencion** y las
de **escenario** que mas los bajarian.

Tiene disparador propio y no viaja con "Simular": el diagnostico lee lo marcado, pero no
depende de las variables fijadas, y colgarlo del boton obligaria a recalcularlo en cada
escenario que no lo cambia. Se borra al cambiar de circuito o de ventana, porque describe
UNO de cada uno.

El ranking se **agrega sobre el conjunto** y no se da vano por vano: la pregunta es que
obra programar para el grupo, y quince rankings sueltos son quince decisiones. Las dos mitades
van separadas y de tamanios distintos a proposito -- lo que se HACE es lo que se cotiza, y
lo que se ANTICIPA sirve para saber bajo que condiciones esa obra rinde. Mezclarlas
dejaria al clima copando la lista, como ya se midio en el panel.

**Las dos columnas comparten escala, y conviene compararlas.** Medido sobre los
peores vanos de un circuito real: la intervencion promedia entre 0,016 y 0,045 ordenes de
magnitud, y el escenario entre 1,39 y 1,75 -- unas cuarenta veces mas. Lo que dice el
modelo ahi es que en esos vanos **manda el clima y la obra rinde poco**. No invalida la
obra, pero si la expectativa de cuanto va a bajar el riesgo, y es mejor saberlo antes de
costearla que despues.

**Los dos botones de encuadre**, uno sobre cada mapa, devuelven la vista a los vanos
marcados -- o al circuito si no hay ninguno. Existen porque las dos vistas se van de sitio
por caminos legitimos: haciendo zoom para mirar un tramo, o porque el mapa simulado se
acerca solo a los vanos que puntuo. La vista se calcula **en el clic** y no al dibujar:
entre un dibujo y el clic pueden haber cambiado los vanos marcados, y un encuadre
precalculado llevaria a donde estaba la seleccion antes.

**El deslizador de ventana solo recorre las ventanas que ese circuito tiene.** No son las
once para todos: un circuito tranquilo puede no registrar una sola celda en media ventana
del anio, y antes el deslizador lo llevaba igual hasta ahi -- a un mapa sin un solo tramo de
color, que se lee como que el tablero se rompio y no como que no hubo eventos. Al cambiar
de circuito se conserva la ventana vigente si el circuito nuevo tambien la tiene: moverse de
circuito no deberia cambiar el mes que se esta mirando. Si no la tiene, cae en la primera
que si.

**Marcar un vano** se hace con su casilla o tocandolo en el mapa de la izquierda: las dos
vias son el mismo estado, porque el clic alterna la casilla. Solo el mapa base acepta clic;
el de la derecha es la salida del modelo, no un control, y marcar desde ahi mezclaria "lo
que elegi" con "lo que el modelo predijo" sobre la misma superficie. Un vano marcado se dibuja con el
color de SU clase sobre un halo blanco -- no con un color plano de "seleccionado", que
congelaria lo que se ve cuando la ventana cambia la clase por debajo.

**El recuadro** encierra cada vano marcado: es su rectangulo envolvente, translucido y
girado a la direccion del propio vano. Va DEBAJO de las lineas del mapa, asi que no tapa el
color de clase del vano ni se come el clic. Sale de la geometria y no de los datos de la
ventana: **sigue puesto al mover el deslizador**, incluso sobre un vano que en esa ventana
no registro un solo evento. Se apaga de una sola forma -- desmarcando el vano, con su
casilla o volviendo a tocarlo en el mapa --, y al apagarse **no se pierde nada mas**: el
color y el grosor de la linea dependen del grupo KMeans y no de la seleccion, asi que el
vano se queda dibujado exactamente como cualquier otro vano con eventos.

**Su relleno lleva el color del grupo del vano, al 50%.** Fue rojo -- el del tablero, "esto
es lo que estoy mirando" -- y esa pregunta ya la contestan el halo blanco y el trazo un 40%
mas ancho. Con el color del grupo, el recuadro contesta ademas en que nivel cayo: la misma
lectura que su linea, pero en una mancha de unos 50 m de lado que se sigue viendo al zoom
en que la linea deja de distinguirse de sus vecinas. Son CINCO capas y no una porque una
capa del mapa pinta con un solo color: los cuatro grupos mas la del marcado que en esa
ventana no tiene celda, que va gris porque no tiene grupo -- y eso no es el grupo mas bajo,
es la ausencia del dato. El mapa del cuaderno `04` dibuja el mismo recuadro con los mismos
colores y los mismos cuatro valores: los dos tableros senialan el mismo objeto sobre el
mismo mapa, y dos resaltados distintos se leerian como dos cosas distintas.

**En el mapa simulado el mismo recuadro cambia de pregunta**: alli el vano ya esta
identificado a la izquierda, asi que el color dice QUE LE PASO. Verde claro si bajo de
grupo de criticidad, amarillo si se quedo en el mismo, rojo si subio. Los tres colores son
propios y ya no se heredan del mapa base: alli el relleno pasa a ser el grupo del vano, y
heredarlo dejaria a "se quedo igual" del color de un grupo, que es otra lectura. Son tres
capas y no una porque una capa del mapa pinta con un solo color.
Un vano marcado que la simulacion no puntuo -- sin celda en la ventana activa, o marcado
DESPUES de presionar "Simular" -- no recibe recuadro: no tiene grupo base ni simulado, y
pintarlo de amarillo afirmaria que no cambio, que es justo lo que nadie midio.

**La etiqueta del mapa simulado trae los DOS grupos**, el base y el simulado, sobre el
mismo vano. Sin eso, saber si un vano mejoro obliga a cruzar al mapa de al lado y
acordarse del color. El grupo base viaja por punto y no en la plantilla de la traza porque
dentro de una traza -- que es una clase SIMULADA -- el grupo base cambia de vano a vano.

**"Simular" es el unico disparador** y produce las tres salidas en el mismo trabajo,
aplicando solo las variables elegidas en el panel. Cada variable aparece como un control
-- deslizador si es numerica, lista si es categorica -- y una familia climatica
(precipitacion, temperatura, rafaga y viento) mueve sus 12 rezagos horarios de una vez.
El mapa simulado **no existe hasta que se presiona**: antes solo muestra el aviso, porque
un mapa pintado de "aun no simulado" ocupa el mismo lugar y tiene la misma forma que un
resultado.

**Cambiar circuito o ventana descarta la ultima simulacion.** La fila 2, el grafo y la
importancia se vacian: mostrar la corrida de otra seleccion es la misma confusion que
todo lo anterior evita.

**El "Grafo de relevancia"** (fila 4, columnas 1-2) es el grafo experto tal como lo usa la
seleccion: `media_vanos(compuerta) x peso_fijo` por arista, en disposicion circular. Cada
nodo lleva su variable y el color de su modo -- `climaticos` o `estructurales` --, paleta
deliberadamente ajena a la de los grupos KMeans. Se **anula** cuando las compuertas no
varian entre los vanos, lo que incluye por construccion cualquier seleccion de menos de 3
vanos: dibujarlo igual seria presentar el grafo experto fijo como si lo hubiera estimado
esta seleccion.

**"UITI acumulado y eventos por ventana"** (fila 3, columnas 1-2) es la serie de tiempo de
los vanos elegidos, y **solo aparece al elegirlos**: sin ninguno marcado queda vacia a
proposito, por el mismo motivo que los violines de 01.4 -- una serie sobre el circuito
entero y una sobre tres vanos se dibujan igual y no miden lo mismo, asi que caer al
circuito cambiaria el sujeto del panel en silencio.

Conviven DOS codigos de color sobre el mismo punto, separados por canal para que los dos
se lean a la vez: la **linea y el anillo** llevan el color de identidad del vano -- dicen
de QUE vano es la serie -- y el **relleno del punto** lleva el color del grupo de riesgo
en que cayo ese vano en ESA ventana, con la paleta del mapa. Por eso un mismo vano cambia
de relleno a lo largo de su serie: medido, uno pasa de Bajo a Medio-Alto y vuelve a Bajo
en cuatro ventanas. Un relleno gris es una ventana sin celda, que no tiene grupo --
distinto de caer en el mas bajo.

El eje x lleva la **fecha en que empieza cada ventana**, no su etiqueta `V1`, `V2`: un
rotulo `V7` obliga a ir a buscar a que periodo corresponde cada vez que se mira el panel.
Cada celda (vano, ventana) es UNA fila ya agregada, asi que cada punto tiene exactamente
una clase: a este grano no hay un conjunto de etiquetas del que tomar la moda.
Doble eje porque UITI y eventos viven en escalas muy distintas. Una ventana sin celda va
como hueco y no en cero -- no es "no hubo UITI", es "no hubo medicion" -- y la linea se
corta ahi. El punto de la ventana vigente se dibuja al triple y viaja con el deslizador.

**"Top 10: que baja el UITI de cada vano"** (fila 3, columnas 3-4) es un grupo de barras
por vano. Responde la pregunta que sostiene una orden de trabajo: **que muevo, y a que
valor, para que ESTE vano baje**. No mide sensibilidad, mide **caida alcanzable**.

El barrido anterior ordenaba por `max(|delta-|, |delta+|)`, y eso tenia dos defectos para
esta pregunta. Primero, la magnitud **no llevaba signo**: una variable que dispara el
riesgo en los dos extremos encabezaba el ranking, y la cabeza de la lista se llenaba de
palancas que no hay que tocar. Segundo, solo miraba los **dos extremos**, cuando --medido
sobre este modelo-- 10 de los 15 controles numericos tienen su mejor valor en el INTERIOR
del rango para alguna bolsa (`DDT` para todas). El modelo es marcadamente no monotono, asi
que los extremos son, simplemente, los dos puntos equivocados. El efecto se ve: sobre un
vano real los dos rankings no comparten **ni una** de sus cinco primeras variables.

Lo que corre ahora recorre cada control en una rejilla de nueve valores, guarda el que
**minimiza** el u-hat de la bolsa, y ordena por cuanto lo baja. La altura de la barra son
**ordenes de magnitud de UITI**, el mismo eje que usa la geometria KMeans; en unidades, el
ranking de un vano caro seria incomparable con el de uno barato. Cada barra trae en el
hover **el valor que lo consigue**, asi que la lista se lee como una instruccion --
"lleva ALTURA a 25 m" -- y no como un puntaje.

Y dice si eso **cambia de grupo**. Con `n_obs` fijo hay un UITI por debajo del cual la
bolsa cae en el grupo Bajo, y esa meta va en el hover. Una barra **verde** es una variable
que, ella sola, lleva al vano hasta ahi -- el mismo verde del recuadro del mapa simulado, y
significa lo mismo. Cuando **ninguna** lo logra, el panel no lo disimula: medido, a un vano
de Medio-Alto con UITI 271 la mejor variable sola lo deja en 57, y hacen falta varias. Y un
vano que **ya esta** en Bajo no pinta nada de verde: no hay adonde bajar, y darlo por
alcanzado presentaria diez variables inertes como palancas decisivas.

Tampoco es SHAP, y ahora por un motivo mas fuerte que antes: SHAP **atribuye** el UITI que
ya hay a las variables que lo explican, y aqui la pregunta es la contraria -- cual, y en que
valor, lo **baja**. Una atribucion alta puede corresponder a una variable que no se puede
mover en la direccion util, y su linea base es una distribucion de datos, no una
intervencion.

El ranking recorre **todos** los controles que el panel ofrece, tambien los
**categoricos** -- su rejilla son sus categorias. El barrido anterior los saltaba, y con
ellos se caian de la lista el conductor, el calibre del neutro y el tipo de proteccion:
tres obras que CHEC efectivamente ejecuta. Y el top **reserva sitio para los dos grupos**,
intervencion y escenario: sin la reserva, las cuatro familias climaticas copan la lista y
no queda ni una palanca que una cuadrilla pueda ejecutar.

**El plan combinado**, debajo del panel, es la continuacion necesaria del ranking. Medido
sobre 59 bolsas de 40 circuitos: en **Medio**, 20 de 33 vanos alcanzan el grupo Bajo con
UNA sola variable; en **Medio-Alto, 0 de 18**; en **Alto, 0 de 8**. Para los dos grupos
donde la pregunta de mantenimiento pesa mas, una variable sola NO basta nunca, asi que el
tablero encadena hasta cuatro cambios por vano -- descenso goloso, cada control como mucho
una vez -- y dice si con eso llega o en que grupo se queda. Es un buen plan, **no el
minimo demostrable**: con 18 controles y 9 valores, dos cambios simultaneos ya son 13 mil
combinaciones y cuatro son 26 millones, fuera del presupuesto de un boton.

Cuesta `1 + 9 x controles` pasadas el ranking, y hasta `4 x 9 x controles` mas el plan,
todo para TODA la seleccion y no una tanda por vano. Medido de punta a punta -- mapa,
grafo, ranking, plan y costos sobre cuatro vanos: **1,3 s**. Pasar de cinco a diez
variables mostradas no cuesta ninguna pasada mas: ya estan todas puntuadas y el top solo
decide cuantas se dibujan.

El rotulo dentro de la barra se elige **barra por barra segun lo que mida**: el nombre
resumido si cabe, sus iniciales si no, y nada antes que un texto cortado que se monte
sobre la barra vecina. Plotly no sabe hacer esa cascada -- o escribe el texto entero o lo
esconde --, asi que la decide el cuaderno con el largo de cada barra en pixeles. **El
nombre completo esta siempre en la etiqueta del mouse**, que es donde se resuelve la duda.
El color de la barra codifica la POSICION en el ranking y nada mas: es una rampa de un
solo color, deliberadamente ajena a la paleta de los grupos, para que una barra no se lea
como un grupo de criticidad.

**"Costo de la intervencion"** (fila 5, columnas 1-3) es la conclusion del tablero: una
barra por vano con lo que vale su plan. Al lado, **"Costo acumulado"** (columna 4) lleva
la barra **TOTAL** con la orden de trabajo completa, en su propio eje. Estaban juntos, y
compartir eje mostraba cuanto pesa cada vano dentro de la suma al precio de que esa suma
-- siempre la barra mas alta -- dejara a los vanos pegados a la base, que es donde se
compara una obra con otra. Es la misma particion de la fila 4 y por la misma razon; sobre
cuantos vanos se reparte el total lo dice su hover. El **desglose por actividad va en el
hover**, ordenado de mayor a menor: la primera linea es la que hay que negociar.

Las actividades salen del contrato de CHEC. Se marcan **una sola vez arriba** y aparecen
como una fila bajo **cada** vano marcado, con su costo unitario y un desplegable de **0 a
5** para decir cuantas veces se ejecutan sobre ESE vano. Una sola lista compartida y no
una por vano: repetir el catalogo cinco veces serian 625 casillas para elegir tres.

El **cero** es lo que hace que esa lista compartida no imponga la misma obra a todos. La
casilla de arriba elige que actividades entran al PLAN; el cero de cada fila dice en cuales
de los vanos marcados esa actividad no se ejecuta. Asi se expresa "podar solo este": se
marca la poda una vez y se pone en cero donde no va. Una actividad en cero no aparece en el
desglose del hover -- no cuesta nada y listarla llenaria el detalle de renglones vacios --,
pero un vano con TODO en cero sigue teniendo su barra: decir "a este no le hago nada" es
una respuesta, distinta de un vano que nunca se marco.

Tres detalles del libro de precios que el cuaderno resuelve y conviene saber. Es una
exportacion de **tabla dinamica**, asi que su ultima fila es el pie `Total general`:
ofrecida como actividad se veria igual que las demas y agregaria 254 mil pesos de puro
artefacto. **Doce actividades no traen costo unitario** y no se ofrecen -- no se puede
costear lo que no tiene precio --, pero el panel las nombra en vez de dejarlas
desaparecer. Y como el archivo **no trae codigo de item**, el nombre es la clave: uno
llegaba ilegible (`CONDUCCIÃ“N`, UTF-8 leido como cp1252) y se repara al cargarlo, porque
una clave que nadie puede leer es una actividad que nadie va a marcar.

El costo se calcula **al presionar "Simular"**, con todo lo demas, y solo sobre los vanos
que el modelo puntuo. Recalcularlo al marcar una casilla dejaria el costo de un plan al
lado del mapa de otro; costear un vano que la simulacion no vio pondria un precio junto a
un riesgo que nadie estimo.

**"UITI de la seleccion: base contra simulado"** (fila 4, columnas 3-4) mide la misma
cantidad dos veces sobre los mismos vanos. Es la lectura que cierra el tablero: si la
simulacion no mueve la distribucion, no la movio, y eso se ve sin comparar dos mapas tramo
a tramo. Con pocos vanos un violin es casi una linea, por eso van tambien los puntos: con
tres o cuatro datos lo honesto es mostrarlos, no dibujar una densidad que no existe.

## La matematica de lo que hace "Simular"

Todo lo de abajo describe UNA pulsacion del boton sobre la seleccion activa
$(c, w, M)$: circuito, ventana y conjunto de vanos marcados.

### 1. Las bolsas de la seleccion

La unidad de prediccion no es el evento: es la **bolsa**, la celda
$(\text{circuito}, \text{vano}, \text{ventana})$. Es la misma unidad en la que 04 define
la criticidad, y por eso el mapa simulado se puede comparar con el historico.

$$\mathcal{B}(c,w,M)=\{\,b=(c,v,w)\;:\;v\in M\,\},\qquad M=\varnothing\;\Rightarrow\;M:=V(c,w)$$

donde $V(c,w)$ son todos los vanos del circuito con al menos un evento en esa ventana:
sin vanos marcados el grano es el circuito completo, no un panel vacio.

Cada bolsa $b$ agrupa sus instancias $I_b$ -- las filas de evento de ese vano dentro de
esa ventana -- y trae dos cosas que **no se predicen nunca**:

$$n_b=|I_b|\quad(\text{eventos OBSERVADOS}),\qquad x_i\in\mathbb{R}^{p},\;p=80$$

Las $p=80$ columnas son 22 estructurales + 48 rezagos de clima + `COD_CAUSA` y sus 9
indicadores. Conviene no confundir esa cuenta con la **particion por modalidades** que usa
el modelo, que no es la misma: `climaticos` son las 50 columnas de los 48 rezagos **mas
`DDT` y `NR_T`** (descargas y nivel de tormenta son clima, aunque viajen como columnas
estaticas), y `estructurales` son las 30 restantes -- las otras 20 estructurales mas
`COD_CAUSA` y sus 9 indicadores. El almacenamiento es CSR (`offsets`, `counts`), no una matriz rellenada:
el 52,7% de las bolsas son de un solo evento y el maximo es 46, asi que rellenar
desperdiciaria mas de 40x en la mitad de los datos. Al seleccionar, el indice de bolsa se
**renumera** desde 0, porque el modelo toma `n_bags = max(instance_bag)+1` y los ids
originales reservarian una bolsa vacia por cada celda no seleccionada.

**Los controles del simulador** actuan sobre las instancias, no sobre las bolsas. Un
control $\kappa$ gobierna un conjunto de columnas $F(\kappa)$ -- una sola para una
variable estructural, las 12 de una familia climatica -- y aplicarlo es

$$x_{i,j}\;\leftarrow\;\phi_j(\text{valor}),\qquad \forall\, i\in\textstyle\bigcup_b I_b,\;\forall\, j\in F(\kappa)$$

con $\phi_j$ la coercion a espacio de modelo (categoria por su codificador, fecha a
epoch, NaN a su centinela). No hay escalador despues: la matriz de instancias del MIL es
espacio crudo. **$n_b$ jamas se toca**: es un eje del espacio que define la clase, y
moverlo desplazaria al vano por una dimension que el modelo no predice.

### 2. La prediccion de clase de cada vano

El modelo hace **dos pasadas** sobre el mismo codificador. La primera existe solo para
producir las compuertas del grafo.

**(a) Codificacion y atencion.** Cada instancia se codifica por modalidad
(30 estructurales, 50 climaticas, segun la particion de arriba) y se concatena en
$z_i^{(1)}$. La bolsa se resume con
atencion tipo Ilse, normalizada dentro de la bolsa:

$$e_i=\mathbf{w}^{\top}\tanh(V z_i^{(1)}),\qquad
a_i=\frac{\exp(e_i)}{\sum_{i'\in I_b}\exp(e_{i'})},\qquad
z_b^{(1)}=\sum_{i\in I_b}a_i\,z_i^{(1)}$$

Esto es **invariante a la cardinalidad por construccion**: duplicar cada instancia de una
bolsa no cambia ningun $e_i$, el denominador se duplica, cada copia recibe $a_i/2$ y la
suma queda igual.

**(b) Compuertas del grafo experto.** Un decodificador lee el resumen de la bolsa y
produce una compuerta por arista:

$$g_b=2\,\sigma(W_g\,z_b^{(1)})\;\in\;(0,2)^{E},\qquad E=64$$

Se inicializa en cero, de modo que $g_b=\mathbf{1}$ al arrancar y el grafo aprendido
**parte exactamente del grafo experto fijo**.

**(c) Propagacion.** El grafo experto es una adyacencia fija $W\in\mathbb{R}^{80\times 80}$
con soporte en $E$ aristas. Cada instancia recibe, en la columna destino de cada arista:

$$x'_{i,j}\;=\;x_{i,j}\;+\;\alpha\!\!\sum_{e\,:\,\mathrm{dst}(e)=j}\!\! g_{b(i),e}\;w_e\;x_{i,\mathrm{src}(e)},
\qquad \alpha=0{,}2$$

Una columna que no es destino de ninguna arista queda intacta, exactamente.

**(d) Segunda pasada y fusion FiLM.** El MISMO codificador procesa $x'$, se vuelve a
agrupar con la MISMA atencion y las dos modalidades se fusionan modulando la
estructural con la climatica (`film_modulated_modality = estructurales`, del artefacto):

$$\hat z_b=z_b^{\text{est}}\odot\bigl(1+\gamma(z_b^{\text{clim}})\bigr)+\beta(z_b^{\text{clim}}),
\qquad p_b=h(\hat z_b),\qquad \hat u_b=\mathrm{expm1}(p_b)$$

La concatenacion es aditiva entre modalidades y no puede representar un producto entre una
variable estructural y una climatica; FiLM hace que el clima **reescale** lo estructural,
que es tambien la afirmacion de dominio: una rafaga pesa mas sobre un apoyo alto, viejo y
degradado. El modelo aprende en $\log(1+u)$ y se devuelve a UITI con `expm1`.

**(e) Clase.** Con el UITI predicho y los eventos observados, la clase sale de la
geometria KMeans de 04 -- **la misma que pinta el mapa base**, verificada al cargar el
modelo. En el espacio canonico `2` el eje de eventos es lineal y el de UITI logaritmico:

$$\zeta_b=\left(\frac{n_b-\mu_0}{s_0},\;\frac{\log_{10}\max(\hat u_b,\varepsilon)-\mu_1}{s_1}\right),
\qquad \hat k_b=\arg\min_{k\in\{0,1,2,3\}}\lVert \zeta_b-c_k\rVert^2$$

El mapa pinta $\hat k_b$ con la paleta de los cuatro grupos; lo que no tiene bolsa en la
ventana, o quedo fuera de la seleccion, va en negro. El simulador corre esto **dos veces**
-- sin y con los controles aplicados -- y $\Delta_b=\hat k_b^{\text{sim}}-\hat k_b^{\text{base}}$
es cuantos vanos cambian de clase.

### 3. Que variables bajan el UITI de cada vano

**No es SHAP**, y no por costumbre: SHAP *atribuye* el $\hat u$ que ya hay a las variables
que lo explican, y la pregunta del panel es la contraria -- cual, y en que valor, lo
**baja**. Tampoco es ya un barrido min-max; por que dejo de serlo esta al final.

**La meta.** Con $n_b$ fijo -- nunca se simula --, la clase solo depende de $\hat u$, asi
que existe un umbral por debajo del cual la bolsa cae en el grupo mas bajo:

$$u^{\star}(n_b)=\max\{\,u>0 \;:\; \arg\min_k\lVert\zeta(n_b,u)-c_k\rVert = 0\,\}$$

Se resuelve por rejilla y no por biseccion: nada garantiza que al subir $u$ con $n_b$ fijo
se recorran los grupos en orden, y una biseccion asume esa monotonia. Medido sobre la
geometria real, $u^{\star}$ se desploma cuando se acumulan eventos -- **4,41** con un
evento, **0,0029** con cuarenta y seis --, asi que un vano con muchos eventos necesita un
UITI casi nulo para bajar de grupo. Es una propiedad del espacio, no del panel.

**El barrido.** Para cada control **numerico** $\kappa$ se recorre una rejilla de $G=9$
valores sobre su rango observado, moviendo sus columnas $F(\kappa)$ a la vez, y se guarda
el valor que MINIMIZA el UITI de cada bolsa:

$$v^{\star}_{b,\kappa}=\arg\min_{v\in\mathcal{G}_\kappa}\hat u_b\!\left(X^{\kappa\to v}\right),
\qquad
\hat u^{\star}_{b,\kappa}=\min_{v\in\mathcal{G}_\kappa}\hat u_b\!\left(X^{\kappa\to v}\right)$$

y se ordena por la **caida en ordenes de magnitud**, que es el eje que usa la geometria:

$$c_{b,\kappa}=\log_{10}\hat u_b(X)-\log_{10}\hat u^{\star}_{b,\kappa},
\qquad
\text{avance}_{b,\kappa}=\frac{c_{b,\kappa}}{\log_{10}\hat u_b(X)-\log_{10}u^{\star}(n_b)}$$

En unidades de UITI el ranking de un vano caro seria incomparable con el de uno barato; en
ordenes de magnitud, dos barras de la misma altura significan lo mismo en cualquier grupo.
El avance dice que fraccion del camino al grupo Bajo cubre esa sola variable, y
$\hat u^{\star}_{b,\kappa}\le u^{\star}(n_b)$ es la condicion que pinta la barra de verde.

**Por que dejo de ser min-max.** Dos defectos, los dos medidos:

- $s=\max(|\Delta^-|,|\Delta^+|)$ **no lleva signo**. Una variable que dispara el riesgo
  en los dos extremos encabezaba el ranking. Sobre un vano real, los dos rankings no
  comparten **ni una** de sus cinco primeras variables.
- Solo miraba los **dos extremos**. En este modelo, **10 de los 15** controles numericos
  tienen su optimo en el INTERIOR del rango para alguna bolsa (`DDT` para todas): la
  funcion no es monotona y los extremos son los dos puntos equivocados.

Los controles **categoricos y constantes se omiten**: sin limites numericos no hay rejilla,
e inventarles un rango seria puntuar un escenario que nadie pidio. Los que el panel no
ofrece -- refutados y de lectura unica -- tampoco entran: no se puede rankear por
relevancia lo que no se deja mover.

### 4. El grafo inferido

Las compuertas de la parte (b) son lo unico del grafo que depende de la seleccion. Se
juntan en una matriz $G\in\mathbb{R}^{|\mathcal{B}|\times E}$, con $G_{b,e}=g_{b,e}$.

Antes de reconstruir nada se mide si esas compuertas **varian** entre vanos. Con
$\tilde G$ la matriz centrada por columnas y $\sigma_1,\dots$ sus valores singulares:

$$\mathrm{var}=\frac{1}{E}\sum_e \mathrm{Var}_b(G_{b,e}),\qquad
\mathrm{rank}_{\text{ef}}=\frac{\bigl(\sum_r\sigma_r^2\bigr)^2}{\sum_r\sigma_r^4},\qquad
\text{colapso}\iff \max_e \mathrm{std}_b(G_{b,e})<10^{-6}\;\lor\;\mathrm{rank}_{\text{ef}}\le 1$$

El rango efectivo es el cociente de participacion: vale $\approx 1$ cuando toda la
variacion vive en una sola direccion, es decir, cuando todos los vanos estan compuertados
igual. Un colapso **anula** el grafo y el panel lo dice, en vez de dibujar el grafo
experto fijo como si lo hubiera estimado esta seleccion. De ahi sale un limite duro:
con $|\mathcal{B}|<3$ la matriz centrada tiene rango 1 por construccion, asi que **menos
de 3 vanos nunca producen grafo**.

Si no hay colapso, el peso reconstruido de cada arista es el peso experto fijo tal como lo
usa esta familia de vanos:

$$\bar g_e=\frac{1}{|\mathcal{B}|}\sum_{b}G_{b,e},\qquad
A_{\mathrm{src}(e),\,\mathrm{dst}(e)}=\bar g_e\cdot w_e,\qquad A_{ij}=0 \text{ fuera del soporte}$$

El panel lo dibuja en disposicion circular sobre las variables que participan de al menos
una arista, con $A_{ij}$ en un marcador sobre el punto medio de cada arista.

### Presupuesto de una pulsacion

| Paso | Pasadas de bolsas |
|---|---|
| Mapa simulado (base + simulado) | 2 |
| Compuertas para el grafo | 1 |
| Relevancia (base compartida + rejilla de $G$ por control) | $1+GK$ |

$K$ son los controles **numericos que el panel ofrece** y $G=9$ los puntos de la rejilla.
De ahi sale la propiedad que sostiene el panel: subir el top de cinco a diez variables **no
cuesta una sola pasada mas**. El barrido ya calculo $\hat u^{\star}_{b,\kappa}$ para todos
los controles y todas las bolsas; el top solo decide cuantos de esos numeros se dibujan.

Medido sobre el modelo real: **0,20 s** con la rejilla de nueve, contra 0,05 s del barrido
min-max de dos puntos. Cuatro veces mas pasadas y sigue siendo instantaneo, que es lo que
permite pagar la rejilla en vez de conformarse con los extremos.

## De donde sale el UITI de los violines

Los dos violines de la fila 4 miden **la misma cantidad dos veces sobre los mismos vanos**.
Vale la pena decir con precision cual, porque el nombre "UITI acumulado" tambien es el de
una columna del historico y **no es esa** la que se dibuja aqui.

### La unidad es la bolsa, no el evento

Cada punto de un violin es **una bolsa**: la celda $(\text{vano}, \text{ventana})$ de la
seleccion activa. Con la ventana fija y hasta cinco vanos marcados, un violin tiene como
maximo cinco puntos -- por eso van dibujados uno por uno (`points='all'`) y no solo como
densidad: con tres o cuatro datos, lo honesto es mostrarlos.

### Los dos numeros

Las bolsas de la seleccion aportan su matriz de instancias $X$ -- una fila por evento --
y su mapa instancia $\to$ bolsa. De ahi salen los dos vectores, con **una pasada del
modelo cada uno**:

$$\hat u^{\text{base}}_b=f_\theta\bigl(X,\;\text{bolsa}\bigr)_b,
\qquad
\hat u^{\text{sim}}_b=f_\theta\bigl(X',\;\text{bolsa}\bigr)_b$$

donde $f_\theta$ es el modelo MIL del cuaderno 05 -- el mismo que pinta los dos mapas -- y
$X'$ es **exactamente $X$** con las columnas de los controles fijados sobreescritas, cada
vano en sus propias filas. Todo lo que no se toco en el panel entra a $X'$ con su valor
**observado**: un control que no se fija no escribe nada.

### Lo que hay que tener claro al leerlos

- **El violin "Base" tambien es una prediccion**, no el historico. Es el modelo puntuando
  los mismos vanos con sus valores observados. Se compara prediccion contra prediccion a
  proposito: asi lo unico que separa a los dos violines es lo que se movio en el panel.
  Contra el UITI medido se estaria midiendo otra cosa -- el efecto de la simulacion mas el
  error del modelo, mezclados y sin forma de separarlos.
- **La escala es $\hat u$, el UITI acumulado predicho de la bolsa**, la misma cantidad que
  entra al eje vertical de la geometria KMeans -- por eso mover un violin y ver cambiar de
  grupo un vano en el mapa son la misma cosa vista dos veces.
- **$n_b$, los eventos observados, jamas se simula**. Es el otro eje del espacio que define
  la clase. De ahi que toda la diferencia entre los dos violines venga de $\hat u$ y de
  nada mas.
- **Si los dos violines se superponen, la simulacion no movio nada.** Es la lectura que
  cierra el tablero y se hace de un vistazo, sin comparar dos mapas tramo a tramo.
- Los violines describen a los **vanos marcados**. Sin ninguno marcado el grano es el
  circuito completo, y entonces cada punto es un vano del circuito con eventos en la
  ventana: mas puntos y otra pregunta.

### Lo que cuesta

**Dos pasadas de bolsas en total**, nunca una por vano: los valores de cada vano se
escriben en la MISMA matriz y se puntuan juntos. Es la misma corrida que produce el mapa
simulado -- los violines no vuelven a llamar al modelo, leen la tabla que ya devolvio.
