# Rendimiento y requisitos de las aplicaciones

Qué tarda cada aplicación, cuánta máquina pide y qué cambia entre macOS, Windows y
Databricks.

Todos los números de la sección local están **medidos en este repositorio**, no estimados.
La máquina de referencia es un Apple Silicon con `.venv` ya creado y los datos presentes.
Los de Databricks salen de las mediciones que guardan los comandos de despliegue.

> Esta página cubre **las aplicaciones**. Para el equipo mínimo del proyecto completo
> —incluyendo el reentrenamiento del cuaderno `mil_vano` y la generación de informes con
> agentes— ver [`docs/REQUISITOS-MINIMOS.md`](../docs/REQUISITOS-MINIMOS.md).

> **Cómo leer una cifra de aquí.** Un tiempo de construcción vale para tu máquina si tiene
> disco SSD y los datos locales; sobre un disco de red se multiplica. Un tiempo de dibujo
> depende del navegador y de la resolución. Lo que no cambia entre máquinas es el ORDEN de
> magnitud y qué aplicación es la cara.

---

## 1. Las cinco aplicaciones

| # | Aplicación | Qué es | Python vivo |
|---|---|---|---|
| 01 | Nube por vano y clima | HTML estático + Plotly | no |
| 02 | Agrupamiento de vanos | HTML estático + Plotly | no |
| 03 | Trayectorias de circuitos | HTML estático + Plotly | no |
| 04 | Trayectorias de vanos | HTML estático + Plotly | no |
| 06 | Simulador de riesgo por vano | Voila + `ipywidgets` + PyTorch | **sí** |

`00_criticidad_chec` es el menú: no es un tablero, es el proceso que levanta y apaga a los
otros cinco.

La división importa más que cualquier número de esta página. Las cuatro primeras calculan
todo por adelantado y dejan que el navegador filtre; la sexta corre el modelo MIL sobre los
vanos y valores que el usuario escriba, y no hay respuesta que precomputar para 26 variables
sobre hasta 15 vanos. Por eso pesa lo que pesa.

---

## 2. Tiempos medidos — tableros estáticos (01–04)

### 2.1 Construcción

Ocurre una sola vez, la primera vez que se abre la aplicación o cuando cambian sus insumos.

| Aplicación | Construcción | Pico de memoria | Panel en disco | HTML |
|---|---|---|---|---|
| 01 Clima | **6,6 s** | 1.401 MB | 35,8 MB | 74 KB |
| 02 Agrupamiento | **2,7 s** | 487 MB | 8,2 MB | 54 KB |
| 03 Trayectorias circuitos | **3,7 s** | 628 MB | 14,2 MB | 71 KB |
| 04 Trayectorias vanos | **3,8 s** | 662 MB | 14,9 MB | 151 KB |

El 01 cuesta el doble que los demás porque lee el CSV de 540 MB por bloques; los otros
parten de derivados más pequeños.

### 2.2 Arranque y dibujo

Con el panel ya construido, que es el caso normal:

| Aplicación | Puerto listo | Primera página | **Dibujado en pantalla** | Trazas | Puntos |
|---|---|---|---|---|---|
| 01 Clima | 0,07 s | 0,07 s | **1,4 s** | 16 | 21.607 |
| 02 Agrupamiento | 0,05 s | 0,05 s | **2,1 s** | 17 | 55.125 |
| 03 Trayectorias circuitos | 0,06 s | 0,06 s | **1,6 s** | 25 | 3.246 |
| 04 Trayectorias vanos | 0,06 s | 0,06 s | **2,4 s** | 124 | 113.079 |

El servidor contesta en 60 milisegundos: **el tiempo que el usuario percibe es del
navegador**, no del servidor. Y lo gobierna el número de LLAMADAS a Plotly, no el de datos
— el 03 dibuja 25 trazas con 3.246 puntos y tarda más que el 01 con 21.607.

### 2.3 Interacción

Cada control del panel dispara un `restyle` de Plotly, que cuesta del orden de **350 ms por
llamada** con independencia del tamaño del payload. Los paneles agrupan las llamadas y se
saltan las familias que no cambian; por eso mover un deslizador se siente inmediato aunque
la figura tenga cien mil puntos.

---

## 3. Tiempos medidos — simulador (06)

| | |
|---|---|
| Puerto en escucha | **8,7 s** |
| Primera página servida | **13,0 s** |
| Procesos vivos | 3 (menú de Voila, servidor, kernel) |
| RSS sumado del árbol | 3.167 MB |
| Página HTML | 27 KB |

**Sobre el RSS.** La suma de los tres procesos cuenta dos veces las bibliotecas compartidas
—PyTorch pesa lo mismo esté mapeado en uno o en tres—, así que el consumo físico real es
menor. Como cifra de planificación, cuenta **~1 GB por sesión de navegador abierta**: Voila
le da a cada pestaña su propio kernel.

Dos consecuencias operativas:

- **Una pestaña olvidada retiene su kernel.** Voila los recicla a los 180 s de inactividad
  (`cull_idle_timeout=180`), pero mientras la pestaña esté viva no hay reciclado.
- **El botón «Simular» corre el modelo en CPU**, deliberadamente. Sobre una selección grande
  el número de núcleos se nota directamente en el tiempo de respuesta.

El arranque **no** usa `--preheat_kernel`, y es una decisión medida: precalentar dejaba
1.694 MB en tres procesos frente a 931 MB en dos, y la espera de la primera página no
mejoraba (4,78 s con precalentado contra 4,45 s sin él). El menú abre la pestaña de
inmediato, así que el kernel caliente nunca llega a tiempo. En el despliegue de servidor el
trato es el contrario y allí sí se enciende.

---

## 4. Requisitos mínimos del PC

### 4.1 Disco

Cada aplicación instala **solo sus dependencias**, en su propio `.venv`. No comparten.

| Aplicación | Entorno | Paquetes directos |
|---|---|---|
| 00 Menú | 15 MB | 0 (solo la biblioteca estándar) |
| 01 Clima | 484 MB | 6 |
| 02 Agrupamiento | 530 MB | 7 |
| 03 Trayectorias circuitos | 633 MB | 8 |
| 04 Trayectorias vanos | 633 MB | 8 |
| 06 Simulador | **1,6 GB** (1,4 GB en instalación nueva) | 19 (incluye PyTorch) |
| | **≈ 3,9 GB** | |

Más los datos (`data/Indicadores_vano_v3.csv` son 540 MB) y los paneles construidos
(73 MB entre los cuatro). El simulador añade su paquete precalculado: 96 MB.

**El entorno del simulador adelgazó 186 MB el 2026-08-17.** Declaraba `shap` y `optuna`
por una justificación que había dejado de ser cierta —que `mil_persistencia` los
arrastraba al importarse—, y con ellos entraban `llvmlite` (125 MB), `numba` (30 MB),
`sqlalchemy` (19 MB) y `alembic` (2,6 MB). Medido construyendo el tablero de verdad,
ninguno de los dos aparece en `sys.modules`. El ahorro se ve en una instalación limpia:
quitarlos de la lista no desinstala nada del entorno que ya existe.

**Total realista en disco: 5 GB** si se usan las cinco. **2,4 GB** si solo se usan las
cuatro estáticas más el menú — que es lo que suma esta misma tabla al quitarle el
simulador (3,9 − 1,6), más los paneles. La cifra que estuvo aquí antes, 1,5 GB,
contradecía a su propia tabla.

### 4.2 Memoria

| Escenario | RAM |
|---|---|
| Solo tableros estáticos (01–04), uno a la vez | **4 GB** |
| Los cuatro estáticos abiertos a la vez | **8 GB** |
| Con el simulador, una sesión | **8 GB mínimo** |
| Con el simulador, varias pestañas o varias personas | **16 GB** |

El pico de construcción del 01 (1.401 MB) es el momento más exigente de las estáticas, y
ocurre una sola vez.

### 4.3 Requisitos por sistema

| | macOS | Windows |
|---|---|---|
| Python | 3.11 o superior | 3.11 o superior (`py -3`) |
| Arranque | doble clic en `Iniciar.app` | doble clic en `iniciar.bat` |
| Instalación | `instalar-en-terminal.command` | `instalar.bat` |
| Navegador | cualquiera moderno | cualquiera moderno |
| CPU | 4 núcleos; 8 para el simulador | igual |

---

## 5. Windows: lo que es distinto

Las aplicaciones se desarrollan en macOS y se usan también en Windows. Tres diferencias
causaron fallos reales el 2026-08-13. **Las tres están corregidas**; se documentan porque
la corrección es frágil y hay que saber qué la sostiene.

| # | Diferencia | Cómo está resuelto hoy |
|---|---|---|
| 1 | **`signal.SIGKILL` no existe en Windows.** Nombrarlo revienta con `AttributeError` | `menu.py:133` elige la escalera de señales según el sistema |
| 2 | **`SO_REUSEADDR` significa lo OPUESTO.** En Windows permite que dos procesos se aten al mismo puerto en lugar de impedirlo | `menu.py:740` y `servidor.py:260`: `allow_reuse_address = not ES_WINDOWS` |
| 3 | **Finales de línea de los `.bat`.** Con finales de Unix fallan de formas que no se parecen a un error de sintaxis | Los seis `iniciar.bat` están en CRLF, verificado |

**Ninguno de los tres se ve leyendo el código en un Mac**, y ninguno habría fallado en las
pruebas de aquí. Esa es la fragilidad: hoy están bien porque alguien los encontró en una
máquina real, no porque nada los vigile.

**Ese guardián ya está montado** (`.github/workflows/windows.yml`, 2026-08-19): un job de
GitHub Actions sobre `windows-latest` que corre las pruebas de Windows con `pytest`,
`ipywidgets` y `numpy`, y **ningún dato** —así que el checkout va sin `git lfs pull`—.
Medido sobre un clon real con punteros de LFS: **187 pasan, 4 se saltan, 3 quedan fuera,
en 0,55 s**.

Las cifras de la propuesta original (152 pruebas, «solo `pytest`») eran del 2026-08-13 y
ya no valían: `test_aplicaciones_locales.py` creció hacia el simulador y hoy necesita
`ipywidgets` y `numpy`. Los tres que quedan fuera piden la pila real (`preparar.py` → la
derivación → matplotlib y torch) y se nombran uno a uno en el propio workflow; en la suite
completa de macOS corren enteros.

Un cuarto punto, de criterio y no de fallo: el texto que las aplicaciones escriben en la
**ventana de terminal** se deja sin tildes, mientras que el que va al **navegador** sí las
lleva. El motivo es que la consola de Windows no siempre está en UTF-8, y una tilde se
convierte en un carácter roto justo en el mensaje de error que hay que leer. Es la razón por
la que la revisión de redacción de agosto acentuó los rótulos de figura y los paneles pero
no tocó los `echo` de los `.bat` ni los `print` del gestor.

---

## 6. Databricks

### 6.1 Los cuatro tableros estáticos

Se publican como **una sola Databricks App con cuatro rutas**.

| | |
|---|---|
| Se construyen | **en la máquina local**, con el mismo código que la aplicación de escritorio |
| Cluster necesario | **ninguno** |
| Cuaderno necesario | **ninguno** |
| Se sube | 14,7 MB ya comprimidos |
| Compute | el mínimo, porque solo sirve archivos |

Es el cambio que más costo quitó: antes cada tablero era un job sobre un cluster que se
levantaba para producir un HTML. Construirlos localmente no gasta compute de Databricks.

### 6.2 El simulador

Es el único que necesita un intérprete de Python vivo, y por tanto compute de verdad.

**El paquete precalculado es lo que lo hace caber.** Todo lo que el cuaderno derivaba del
CSV de 540 MB se calcula fuera y se congela:

| | cuaderno tal cual | con el paquete |
|---|---|---|
| bytes leídos al arrancar | **909 MB** (CSV 540 + bolsas 190 + shapefiles 180) | **94,5 MB** |
| datos residentes en RAM | **2.867 MB** | **579 MB** |
| interfaz (figura + widgets) | +69 MB | +69 MB |
| **total por sesión** | **2.936 MB** | **~648 MB** |
| tiempo de carga | 7,1 s | **0,3 s** (más 1,8 s de importaciones) |

**Tamaño de compute:**

| Tamaño | Recursos | Coste | Cuándo |
|---|---|---|---|
| **MEDIUM** | 2 vCPU / 6 GB | 0,5 DBU/h | El predeterminado. Con 648 MB por sesión caben unas seis a la vez |
| **LARGE** | 4 vCPU / 12 GB | 1 DBU/h | Solo si más de seis personas lo van a usar simultáneamente |

Sin el paquete, **una app MEDIUM no da ni para dos sesiones**: dos necesitarían 5,9 GB antes
de contar el sistema.

LARGE tiene un segundo efecto: sus vCPU adicionales reducen a la mitad el tiempo de un clic
en «Simular» sobre una selección grande, porque el modelo MIL corre en CPU.

### 6.3 Restricciones del entorno

- **Serverless no sirve** para el simulador: `ipywidgets` necesita un cluster clásico en
  ejecución.
- El catálogo `workspace` **no existe** en el workspace de CHEC, y el FUSE de un Volume en
  `default` devuelve 403. La Files API sí funciona.
- El service principal de la app necesita un `USE CATALOG` que **solo puede conceder el
  dueño del catálogo**. Es el bloqueo que más veces ha parado un despliegue.
- Hay un **tope de 3 apps** por workspace, y una app en `DELETING` sigue contando.

---

## 7. Responsive: comportamiento medido

Verificado en Chrome sobre los cuatro paneles construidos, a 1.920×1.080, 1.440×900 y
1.280×800:

| | Desborde horizontal | Panel de control |
|---|---|---|
| 01 Clima | 0 px | 24 % del ancho, estable |
| 02 Agrupamiento | 0 px | 97 %, estable |
| 03 Trayectorias circuitos | 0 px | 97 %, estable |
| 04 Trayectorias vanos | 0 px | 29 %, estable |

El menú de CriticidadCHEC mide 0 de desborde de 1.920 a 1.024 px.

**Qué se adapta y qué no, y por qué.** El ancho de las figuras es proporcional
(`default_width='100%'` más `config.responsive`); el **alto se queda en píxeles fijos**, y
es deliberado. Lo que vive entre dos filas de una figura es TEXTO —rótulos de eje, títulos
de panel— y el texto no encoge con la figura: un alto proporcional junta los rótulos en
cuanto la pantalla es baja. Los paneles de control son cajas flexibles con ajuste de línea,
así que reordenan sus controles en vez de comprimirlos.

**Resolución mínima recomendada: 1.280×800.** Por debajo el tablero sigue siendo usable
—no se desborda— pero las figuras se escalan por debajo de su tamaño de diseño.

---

## 8. Resumen para decidir

| Si quieres… | Necesitas |
|---|---|
| Ver los cuatro tableros en un portátil corriente | 4 GB de RAM, 1,5 GB de disco, Python 3.11 |
| Usar además el simulador | 8 GB de RAM, 5 GB de disco |
| Que lo usen varias personas a la vez, en local | 16 GB de RAM |
| Publicar los cuatro tableros en Databricks | Nada de compute: se construyen aquí |
| Publicar el simulador para hasta seis personas | Una app MEDIUM (2 vCPU / 6 GB, 0,5 DBU/h) |
| Publicar el simulador para más de seis | Una app LARGE (4 vCPU / 12 GB, 1 DBU/h) |

---

## 9. Lo que esta página NO cubre

Se dice para que nadie lo dé por medido:

- **Windows no está medido aquí.** Los tiempos de las secciones 2 y 3 son de macOS sobre
  Apple Silicon. En Windows el orden de magnitud debería ser el mismo, pero la creación del
  entorno es notablemente más lenta y no se ha cronometrado.
- **La primera instalación no está cronometrada.** Crear los seis entornos descarga del
  orden de 3,9 GB; el tiempo lo manda la red, no la máquina.
- **El tiempo de un clic en «Simular»** no está medido: depende de cuántos vanos y cuántas
  variables se muevan, y el espacio es demasiado grande para una cifra única.
- **El coste en DBU de una app de Databricks** se factura por hora de compute encendido, no
  por uso. Una app olvidada encendida cuesta lo mismo que una app en uso.
