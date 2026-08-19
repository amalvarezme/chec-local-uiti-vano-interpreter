---
description: Mira si cambio algo de lo que el modelo MIL aprendio -- la base de eventos, el diccionario de variables o el grafo experto -- y rehace en orden lo que haya que rehacer: reentrenar, la geometria, el sello, las aplicaciones y la subida a Databricks. Si lo unico que cambio fue el catalogo de variables a simular, lo dice y NO reentrena: ajusta el panel, sus rangos y el tipo de control de cada variable. Mide primero y pregunta una sola vez.
---

Sigue esta secuencia cuando se invoque `/actualizar`.

## Lo que este comando hace, y lo que no

**Hace**: contestar *"los artefactos derivados salieron de las fuentes que hay hoy?"* y,
si la respuesta es que no, rehacer lo que corresponda en el orden en que las cosas
dependen unas de otras.

**No hace**: reentrenar por si acaso. Reentrenar cuesta **entre 8 y 14 minutos en CPU** —
en CPU a proposito: medido, le gana a MPS por 6x y usa 3,4x menos memoria — y hay una
fuente entera que no lo justifica nunca.

**No habla con Databricks.** Termina entregandole el trabajo a `/subir-a-databricks`,
que es el unico comando que habla con el workspace.

## 0. Mide antes de tocar nada

```
python3 scripts/estado_actualizacion.py --json
```

En Windows, `py -3 scripts/estado_actualizacion.py --json`. En macOS y Linux sirve
igual el Python del entorno raiz.

Ese guion compara por contenido las fuentes y los derivados contra
`data/models/procedencia.json`, que viaja en el repositorio. Devuelve:

- `veredicto`: uno de cuatro, y cada uno manda un camino distinto;
- `fuentes_movidas`, `derivados_movidos`, `faltantes`: los nombres, no un conteo;
- `plan`: los pasos que faltan, **ya ordenados**, cada uno con su `orden` — lo que hay
  que ejecutar — y su `porque`.

**No reimplementes aqui ninguna de esas dos listas.** Las fuentes las declara `FUENTES`
en `scripts/estado_actualizacion.py`, con el motivo de cada una escrito al lado; los
pasos los declara `PASOS`, con su orden exacta. Una segunda copia en este archivo seria
una segunda verdad, y la que se desactualiza es siempre la copia.

Muestrale al usuario el informe legible — el mismo guion sin `--json` — antes de seguir.

### Por que hace falta medir, y no basta con abrir las aplicaciones

Cada aplicacion vigila sus insumos y **se reconstruye sola**. Esa huella contesta
*"cambio algun insumo?"*, no *"siguen siendo coherentes entre si?"*. El caso que se
escapa, y que no da ningun error:

> **`src/chec_impacto/data/graph.py` editado.** El grafo experto declara las aristas,
> pero la adyacencia se congela **dentro del `.pt`** al guardar el modelo y se lee de
> ahi al cargarlo — no se reconstruye del codigo. Editar el grafo no cambia
> absolutamente nada hasta que se reentrena. Mientras tanto las cinco aplicaciones si se
> reconstruyen, porque vigilan `src/` entero como un solo arbol, y sirven un panel nuevo
> sobre un modelo del grafo anterior.

## 1. Los cuatro veredictos

| `veredicto` | Que paso | Que hacer |
|---|---|---|
| `al-dia` | nada se movio | dilo y termina. No hay nada que rehacer |
| `reentrenar` | se movio una fuente que decide **como se entreno** el modelo | el camino largo: la seccion 3 |
| `solo-panel` | se movio `data/Variables_simular.xlsx` y nada mas | el camino corto: la seccion 4 |
| `sin-sellar` | los derivados no corresponden a lo sellado | alguien ya rehizo el trabajo: falta dejarlo escrito. Sigue el `plan` desde donde este |

## 2. Pregunta, una sola vez

Con el veredicto y el plan a la vista, di **cuanto va a costar** y pregunta si se
procede. Con `reentrenar`, di los minutos antes de empezar; con `solo-panel`, di que son
segundos y que **no reentrena nada**.

Y **para. Espera la respuesta.** No se gastan catorce minutos de CPU por suposicion.

## 3. Camino largo: se movio algo que el modelo aprendio

Ejecuta los pasos del `plan` **en el orden en que vienen**, cada uno con su campo
`orden`. No los reordenes ni te saltes ninguno: el orden es la unica parte que no se
puede deducir mirando los archivos.

Lo que hace falta saber de los dos primeros, que el `plan` no puede contar solo:

**Reentrenar** es el cuaderno `notebooks/05_mil_vano_ventana.ipynb` con
`EJECUCION = "entrenamiento"` y `mode = "full"`. El cuaderno es **salida generada** de
`scripts/generate_notebook_10.py`: si hay que tocar una celda, se toca el generador y se
regenera, nunca el `.ipynb`. Escribe las bolsas y el `.pt`, y no se puede hacer con un
job de Databricks — el job necesitaria primero los 909 MB espejados en el Volume.

**La geometria KMeans** solo depende de la base de eventos. Si el `plan` no la trae, es
porque la base no se movio, y rehacerla seria trabajo sin motivo.

Despues del reentrenamiento, **antes de sellar**, corre el paso `catalogo` de la
seccion 4: valida contra el modelo **que acaba de salir**. Sellar un estado que el
catalogo rechaza dejaria escrito que todo cuadra justo cuando no cuadra.

### Sellar no es opcional

El paso `sellar` graba las fuentes y los derivados **y reescribe
`data/models/manifest.sha256.json`**, el manifiesto del modelo congelado. Reentrenar sin
sellar deja en rojo la guarda que compara ese sha, con un fallo que no apunta hasta
aqui. Corre la suite despues de sellar, no antes.

## 4. Camino corto: solo cambio que se puede simular

`data/Variables_simular.xlsx` **no reentrena nada**. Solo decide que ofrece el panel del
simulador, y tres cosas a la vez: que variables, con que rango, y con que control.

```
python3 scripts/catalogo_simulacion.py
```

Cruza el catalogo del archivo con los controles que el modelo sabe mover, y contesta lo
que hoy solo se ve abriendo el simulador:

- **que control le toca a cada variable**: `selector` si el archivo declara la lista de
  valores posibles — manda la lista, aunque sean numeros: existen apoyos de 12, 16 y 18
  metros y de ninguna otra altura —, `deslizador-entero` si el tipo es entero, y
  `deslizador` continuo en lo demas;
- **el rango y la unidad** con que se ofrece, que salen del archivo y no de lo observado
  en la base;
- **los tres desajustes** que no dan error: una opcion que el modelo no sabe codificar y
  se cae de la lista en silencio; un control del modelo sin veredicto en el archivo; y
  una fila ofrecida que ya no corresponde a ningun control.

Sale distinto de cero solo por el primero. **Si aparece, no sigas**: reconstruir el
panel con el archivo asi ofrece opciones que la simulacion no puede honrar.

> El fallo mas caro de este archivo es de una sola celda: una variable **entera**
> declarada `numeric` sale con deslizador continuo, y el panel deja pedir 2,37 fases y
> media puesta a tierra. El guion lo muestra en la columna del control.

Con el catalogo limpio, sigue el resto del `plan`: sellar, reconstruir las aplicaciones
y subir.

## 5. Las aplicaciones locales

El paso `aplicaciones` del `plan` fuerza la reconstruccion del simulador. Las cinco se
reconstruyen solas al abrirlas, pero forzarlo aqui deja el fallo a la vista ahora y no
delante de quien las abra manana.

Dos cosas que valen en las dos plataformas y cambian de forma:

| | macOS | Windows |
|---|---|---|
| interprete | `python3` | `py -3` |
| entorno de cada aplicacion | `.venv/bin/` | `.venv\Scripts\` |

Cierra antes cualquier instancia abierta: el simulador tiene su paquete mapeado en
memoria. Si algo quedo colgado, `/app-local-criticidadCHEC` sabe cerrarlo.

Reconstruir **no ensucia el repositorio**: `panel/`, `paquete/`, `cuaderno/` y `.venv/`
de cada aplicacion estan en `.gitignore`.

## 6. Entrega a Databricks

El ultimo paso del `plan` es siempre `/subir-a-databricks`. **Nada en Databricks se
entera solo**: el Volume y las dos apps siguen sirviendo los artefactos anteriores hasta
que se suban.

Dile al usuario, con nombre y peso, que es lo que va a viajar distinto — el modelo, las
bolsas, la geometria o el catalogo de simulacion — y que el sello nuevo
(`data/models/procedencia.json`) viaja con ellos: es lo que le permite a la etapa 3 de
ese comando distinguir "ya esta" de "esta, pero es el de antes".

## 7. Reporta

En un parrafo corto: que se movio, que se rehizo, cuanto costo, y que quedo pendiente.
Si algo fallo, nombralo con su salida — no lo resumas como "hubo un problema".

Si el usuario pidio `/actualizar` y el veredicto era `al-dia`, esa **tambien es una
respuesta completa**: los artefactos que hay salieron de las fuentes que hay.
