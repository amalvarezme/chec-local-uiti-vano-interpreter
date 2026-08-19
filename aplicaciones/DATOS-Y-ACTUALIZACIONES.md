# Trabajar con datos nuevos

Qué hacer cuando cambian los datos, el catálogo de variables o el modelo MIL, y qué
hacen las cinco aplicaciones por su cuenta.

La regla corta: **las aplicaciones se dan cuenta solas y se reconstruyen**. Lo que no
pueden hacer es regenerar los artefactos derivados — eso lo tienes que correr tú, y en
un orden que importa. Todo lo de abajo está medido en este repositorio.

> **El comando `/actualizar` hace todo lo de este documento.** Mide qué se movió,
> decide si hay que reentrenar o no, y ejecuta el plan en orden. Lo que sigue es lo que
> ese comando sabe, escrito para leerse: sirve para entenderlo, para hacerlo a mano, y
> para saber qué está comprobando.
>
> ```
> python3 scripts/estado_actualizacion.py     # sólo el diagnóstico, sin tocar nada
> ```

---

## 1. Los archivos base

| Archivo | Qué es | De dónde sale |
|---|---|---|
| `data/Indicadores_vano_v3.csv` | la base de eventos, 540 MB | externo, por Git LFS. **No se regenera aquí** |
| `data/GEO/MVLINSEC.{shp,dbf}` | geometría de los vanos | externo. **No se regenera** |
| `data/GEO/GDBCHEC_TRANSFOR.{shp,dbf}` | transformadores | externo. **No se regenera** |
| `data/GEO/SWITCHES.{shp,dbf}` | interruptores | externo. **No se regenera** |
| `data/Variables_seleccion.xlsx` | diccionario de variables | se edita a mano |
| `data/Variables_simular.xlsx` | catálogo de variables simulables | se edita a mano |
| `data/Actividades_mantenimiento_costos_2026.xlsx` | costos del plan | se edita a mano |
| `data/models/mil_vano_ventana_v1.pt` | el modelo MIL | **lo produce `notebooks/05_mil_vano_ventana.ipynb`** |
| `data/derived/bolsas_mil_full.joblib` | las bolsas (vano × ventana) | **lo produce `notebooks/05_mil_vano_ventana.ipynb`** |
| `data/geometria_kmeans_014_v1.json` | la geometría KMeans | **versionada en git**; se reproduce con `python scripts/exportar_geometria.py` |

Los dos derivados de `data/derived/` salen del CSV pasando por el cuaderno 05. Esa es
toda la dificultad de este documento. La geometría KMeans **dejó de ser uno de ellos** el
2026-08-15: antes se extraía de la salida guardada del cuaderno 04, lo que ataba tres
cuadernos entre sí y dejaba a un checkout limpio sin poder asignar clases.

---

## 2. Qué vigila cada aplicación

Cada aplicación guarda, al construirse, la huella de sus insumos en su manifiesto
(`panel/manifiesto.json` o `paquete/manifiesto.json`), y la compara al arrancar. Si algo
se movió, **se reconstruye sola y dice cuál cambió**:

```
Reconstruyendo el tablero: cambio Indicadores_vano_v3.csv desde la ultima construccion.
```

| Insumo | 01 clima | 02 agrupamiento | 03 circuitos | 04 vanos | 06 simulador |
|---|:--:|:--:|:--:|:--:|:--:|
| `Indicadores_vano_v3.csv` | ✅ | ✅ | ✅ | ✅ | ✅ |
| los tres shapefiles | ✅ | ✅ ⁽¹⁾ | ✅ | ✅ | ✅ |
| `Variables_seleccion.xlsx` | — | — | — | — | ✅ |
| `Variables_simular.xlsx` | — | — | — | — | ✅ |
| `Actividades_..._costos_2026.xlsx` | — | — | — | — | ✅ |
| `mil_vano_ventana_v1.pt` | — | — | — | — | ✅ |
| `bolsas_mil_full.joblib` | — | — | — | — | ✅ |
| `geometrias_014.json` | — | — | — | — | ✅ |
| su cuaderno y el código que lo empaqueta | ✅ | ✅ | ✅ | ✅ | ✅ |
| `src/` completo (67 archivos) ⁽²⁾ | ✅ | ✅ | ✅ | ✅ | ✅ |

⁽¹⁾ El cuaderno 02 no abre ningún shapefile, pero se vigilan igual. Vigilar de más cuesta
una reconstrucción de 3 s el día que alguien cambie un shapefile; vigilar de menos cuesta
un tablero que dibuja datos viejos sin dar ningún error. La asimetría es deliberada.

⁽²⁾ El código de `chec_local_interpreter` y `chec_impacto`, que es lo que los cuadernos
importan y lo que de verdad decide cómo se ve el tablero: el agrupamiento, las capas del
mapa, la construcción de ventanas. **Estuvo sin vigilar y era el hueco más ancho que
tenían las cinco**: se tocaba `clases_para` y el tablero seguía sirviendo el panel
anterior sin dar ningún error — el mismo fallo que ya obligó a vigilar `empaquetar.py`,
un nivel más abajo y 67 archivos más ancho.

Entra como **una sola huella del árbol** y no como 67 sueltas, por dos razones: las
huellas se indexan por nombre de archivo y los dos paquetes tienen su propio
`__init__.py` (sueltas, el segundo pisaría al primero en silencio), y un manifiesto con
67 entradas más es ilegible justo cuando hace falta leerlo. Cuesta **1,4 ms** por
arranque, medidos sobre los 1,3 MB de código, contra los 0,06 s que tarda un visor ya
construido en servirse. Cambiar cualquier archivo de `src/` reconstruye las cinco.

**Un guion `—` no es un descuido: esa aplicación no lee ese archivo.** Solo el simulador
usa el modelo MIL; los otros cuatro calculan todo en su cuaderno.

---

## 3. Los tres casos

### A. Llegó un `Indicadores_vano_v3.csv` nuevo

Es el caso que más trabajo pide, porque **tres artefactos derivan de él**. En orden:

1. Deja el CSV nuevo en `data/` (o `git lfs pull` si venía del repositorio).
2. Corre `notebooks/05_mil_vano_ventana.ipynb` → regenera `bolsas_mil_full.joblib` y
   `mil_vano_ventana_v1.pt`.
3. Corre `python scripts/exportar_geometria.py` → reescribe
   `data/geometria_kmeans_014_v1.json` reajustando el KMeans sobre el CSV nuevo. Antes
   este paso era «corre el cuaderno 04», y por eso el orden importaba tanto.
4. Abre las aplicaciones normalmente. **Se reconstruyen solas**, cada una nombrando lo
   que cambió.

**Si te saltas los pasos 2 y 3**, las aplicaciones se reconstruyen igual — y ahí está el
peligro, explicado en la sección 4.

### B. Cambió `Variables_simular.xlsx` o `Variables_seleccion.xlsx`

Solo afectan al simulador. Edita el `.xlsx` y ábrelo: se reconstruye solo (~9 s) y el
panel ofrece el catálogo nuevo. No hay que correr ningún cuaderno.

> Ojo con el tipo declarado en `Variables_simular.xlsx`: una variable entera marcada como
> `numeric` sale con deslizador continuo y deja poner «2,37 fases».

### C. Se reentrenó el modelo MIL

Corre `notebooks/05_mil_vano_ventana.ipynb`; deja `mil_vano_ventana_v1.pt` y
`bolsas_mil_full.joblib`. Abre el simulador: se reconstruye solo. Los otros cuatro
tableros no se enteran porque no usan el modelo, y está bien así.

**El modelo y las bolsas van juntos, siempre.** Si reemplazas uno sin el otro, el
simulador **falla al arrancar**, con el número de features de cada uno:

```
Las features del artefacto no coinciden con las que construyo quien llama:
80 guardadas vs 74 recibidas. Faltan en la entrada: [...]
```

Eso es bueno: es un error ruidoso y a tiempo, no un mapa equivocado.

---

## 4. Lo que la huella no puede detectar, y cómo se cubre

La huella responde *«¿cambió algún insumo?»*. No responde *«¿siguen siendo coherentes
entre sí?»*. El desajuste de esa segunda clase que importa es:

> **Un CSV nuevo con bolsas viejas.**
>
> El tablero del simulador dibuja dos cosas a la vez: los eventos **observados**, que
> salen del CSV, y la criticidad **simulada**, que sale del modelo puntuando las bolsas.
> Si actualizas el CSV sin volver a correr el cuaderno 05, el simulador se reconstruye
> — la huella del CSV cambió —, muestra los eventos nuevos, y los puntúa con las bolsas
> anteriores. Las dos mitades del tablero hablarían de meses distintos.

Y hay un segundo, que ninguna huella ve y que tampoco falla:

> **El grafo experto editado.** `src/chec_impacto/data/graph.py` declara las aristas,
> pero la adyacencia se congela **dentro del `.pt`** al guardar el modelo y se lee de
> ahí al cargarlo — nunca se reconstruye del código. Editar el grafo no cambia nada
> hasta que se reentrena. Mientras tanto las cinco aplicaciones **sí** se reconstruyen,
> porque vigilan `src/` entero como un solo árbol, y sirven un panel nuevo sobre un
> modelo del grafo anterior.
>
> Eso lo atrapa el sello: `data/models/procedencia.json` guarda el sha256 de las cuatro
> fuentes con las que se entrenó, y `scripts/estado_actualizacion.py` lo compara. Es la
> única de las tres filas de la tabla de abajo que no da ningún error por su cuenta.

**Desde ahora eso también falla a gritos.** `construir_paquete` compara las celdas
`(CIRCUITO, FID_VANO, VENTANA)` de las bolsas contra las de la tabla de eventos antes de
congelar nada, y aborta nombrando el desajuste con un ejemplo:

```
El cache de bolsas no corresponde al CSV: el cache de bolsas no cubre 1 de las
111.232 celdas (vano, ventana) que trae el CSV -- por ejemplo AGU23L12/20130434
en V12. El CSV va por delante del cuaderno 05.
```

Se compara **la celda y lo que cada lado dice de ella**, sin metadatos nuevos, así que
vale también para los artefactos que ya están en disco. Tres reglas, y la asimetría
entre las dos primeras es deliberada:

1. una celda que el CSV trae y las bolsas no → **desajuste**: hay eventos que el modelo
   no puede puntuar;
2. una celda que solo está en las bolsas → **no lo es**. La tabla redondea el UITI a 3
   decimales y descarta lo que quede en cero, así que una celda con UITI diminuto existe
   en las bolsas y no en la tabla. Medido: pasa en 2 celdas de 111.233 —VMA23L16/39520403
   en V7 y V8, con UITI 0,000333—. Marcarlo sería un falso positivo permanente;
3. en las celdas compartidas, el número de eventos tiene que cuadrar **exacto** y el UITI
   dentro de 0,001. Es lo que atrapa un CSV corregido *dentro* de los meses que ya
   existían, donde el conjunto de celdas no se mueve.

Cuesta **23 ms** sobre las 111.231 celdas, y solo al reconstruir. Comprobarlo en cada
arranque obligaría a cargar los 199 MB de bolsas para contestar una pregunta que solo
cambia al reconstruir.

Aun así, **el orden de la sección 3.A sigue sin ser una formalidad**: la comprobación te
frena, pero quien tiene que arreglarlo eres tú, corriendo el cuaderno 05.

| Desajuste | Qué pasa |
|---|---|
| modelo ≠ bolsas | falla al arrancar, nombrando cuántas features tiene cada uno |
| `geometrias_014.json` ≠ modelo | falla al arrancar: *«La geometría del modelo MIL difiere de la de 01.4…»* |
| CSV ≠ bolsas | **falla al construir**, nombrando la celda que no cuadra |
| grafo ≠ modelo | **no falla**: lo detecta el sello, y sólo si se le pregunta |

---

## 5. Forzar una reconstrucción a mano

Casi nunca hace falta — para eso están las huellas —, pero si dudas:

```bash
# macOS y Linux
cd aplicaciones/01_clima     && python3 ../_comun/gestor.py construir   # 01, 02, 03, 04
cd aplicaciones/06_simulador && python3 ../_comun/gestor.py iniciar --reconstruir
```

```bat
REM Windows
cd aplicaciones\01_clima     && py -3 ..\_comun\gestor.py construir
cd aplicaciones\06_simulador && py -3 ..\_comun\gestor.py iniciar --reconstruir
```

Detén antes cualquier instancia abierta: el simulador tiene su paquete mapeado en
memoria.

Todo lo de este documento vale igual en Windows; lo único que cambia son las órdenes.
El doble clic allí es `iniciar.bat` — `Iniciar.app` es de macOS — y el entorno virtual
vive en `.venv\Scripts\` en vez de `.venv/bin/`.

Costos medidos en esta máquina:

| Aplicación | Reconstruir | Arrancar ya construida |
|---|---|---|
| 01 clima | 8 s | < 1 s |
| 02 agrupamiento | 3 s | < 1 s |
| 03 circuitos | 5 s | < 1 s |
| 04 vanos | 4 s | < 1 s |
| 06 simulador | ~9 s, pico de 3,01 GB de RAM | ~2 s |

La comprobación de huellas en sí cuesta **milisegundos**: lo pesado se compara por bytes
y fecha, no leyendo los 909 MB.

---

## 6. Dónde vive lo construido

`panel/`, `paquete/`, `cuaderno/` y `.venv/` de cada aplicación están en `.gitignore`.
Son locales: un clon nuevo no trae ningún tablero construido y lo construye en la primera
apertura. Nunca hay que commitear nada de eso.

Consecuencia práctica: **una reconstrucción no ensucia el repositorio**. Puedes forzarla
sin miedo.

---

## 7. Tres trampas de Git

1. **`Indicadores_vano_v3.csv` de 130 bytes.** Es el puntero de LFS sin descargar, no los
   datos. Las aplicaciones lo detectan y lo dicen con esas palabras; la salida es
   `git lfs pull` en la raíz.
2. **Un `git lfs pull` puede provocar una reconstrucción de más.** Los archivos pesados se
   vigilan por bytes + fecha, y LFS reescribe la fecha aunque el contenido sea idéntico.
   Es deliberado: una marca de tiempo falla del lado seguro. Cuesta unos segundos una vez.
3. **`data/derived/` no está en git, y preguntar por él con la herramienta equivocada
   miente.** `.gitignore` lleva la línea `data/*` y ningún `!` rescata `derived/`, así que
   `bolsas_mil_full.joblib` —199 MB— **no está rastreado**. `git ls-files`, `git status` y
   cualquier búsqueda que respete el gitignore lo reportan como inexistente aunque esté en
   el disco. El 2026-08-19 una corrida de `/subir-a-databricks` lo dio por ausente por eso
   y dejó el despliegue degradado. La única pregunta que contesta la verdad es al sistema
   de archivos:

   ```
   ls -l data/derived/bolsas_mil_full.joblib
   ```

   Y la consecuencia real, que no es la del despliegue: **un checkout limpio tiene el CSV
   de 566 MB (viaja por LFS) pero no tiene las bolsas**. Hay que correr
   `notebooks/05_mil_vano_ventana.ipynb` antes de construir el simulador. El orden es
   CSV → 05 → 04 → abrir las aplicaciones.

Lo mismo vale para un `git checkout` que mueva fechas: por eso los archivos pequeños —
cuadernos y catálogos, ~1 MB — se vigilan por **contenido** (sha1) y no por fecha.

---

## 8. Si agregas un insumo nuevo

Si un cuaderno pasa a leer un archivo que antes no leía, **agrégalo a la lista de
vigilados en el mismo commit**:

- tableros estáticos → `_DATOS` o `_CODIGO` en `aplicaciones/_comun/construccion.py`
- simulador → `INSUMOS_POR_CONTENIDO` o `INSUMOS_POR_MARCA` en
  `aplicaciones/06_simulador/preparar.py`
- y si además decide **cómo se entrenó** el modelo — no sólo qué lee un cuaderno —,
  `FUENTES` en `scripts/estado_actualizacion.py`, con el motivo escrito al lado

Contenido (sha1) para lo pequeño, marca (bytes + fecha) para lo pesado.

Olvidarlo ya pasó dos veces, las dos en silencio: con `Variables_simular.xlsx` primero y
con `Variables_seleccion.xlsx` después. Hay una prueba
(`test_todo_insumo_que_el_simulador_exige_esta_ademas_vigilado`) que compara la lista de
lo que se exige para construir contra la de lo que se vigila, para que no haya un tercero.
