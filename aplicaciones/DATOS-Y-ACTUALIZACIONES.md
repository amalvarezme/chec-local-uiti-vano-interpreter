# Trabajar con datos nuevos

Qué hacer cuando cambian los datos, el catálogo de variables o el modelo MIL, y qué
hacen las cinco aplicaciones por su cuenta.

La regla corta: **las aplicaciones se dan cuenta solas y se reconstruyen**. Lo que no
pueden hacer es regenerar los artefactos derivados — eso lo tienes que correr tú, y en
un orden que importa. Todo lo de abajo está medido en este repositorio.

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
| `data/derived/geometrias_014.json` | la geometría KMeans | **sale del cuaderno `04_uiti_vano_trayectorias_vano.ipynb`** |

Los tres últimos son **derivados**: salen del CSV pasando por un cuaderno. Esa es toda
la dificultad de este documento.

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

⁽¹⁾ El cuaderno 02 no abre ningún shapefile, pero se vigilan igual. Vigilar de más cuesta
una reconstrucción de 3 s el día que alguien cambie un shapefile; vigilar de menos cuesta
un tablero que dibuja datos viejos sin dar ningún error. La asimetría es deliberada.

**Un guion `—` no es un descuido: esa aplicación no lee ese archivo.** Solo el simulador
usa el modelo MIL; los otros cuatro calculan todo en su cuaderno.

---

## 3. Los tres casos

### A. Llegó un `Indicadores_vano_v3.csv` nuevo

Es el caso que más trabajo pide, porque **tres artefactos derivan de él**. En orden:

1. Deja el CSV nuevo en `data/` (o `git lfs pull` si venía del repositorio).
2. Corre `notebooks/05_mil_vano_ventana.ipynb` → regenera `bolsas_mil_full.joblib` y
   `mil_vano_ventana_v1.pt`.
3. Corre `04_uiti_vano_trayectorias_vano.ipynb` → de ahí sale `geometrias_014.json`.
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

## 4. Lo único que la huella NO puede detectar

La huella responde *«¿cambió algún insumo?»*. No responde *«¿siguen siendo coherentes
entre sí?»*. Y hay un desajuste que **no da ningún error**:

> **Un CSV nuevo con bolsas viejas.**
>
> El tablero del simulador dibuja dos cosas a la vez: los eventos **observados**, que
> salen del CSV, y la criticidad **simulada**, que sale del modelo puntuando las bolsas.
> Si actualizas el CSV sin volver a correr el cuaderno 05, el simulador se reconstruye
> — la huella del CSV cambió —, muestra los eventos nuevos, y los puntúa con las bolsas
> anteriores. Las dos mitades del tablero hablan de meses distintos y **nada lo dice**.

Por eso el orden de la sección 3.A no es una formalidad. Dos desajustes vecinos sí se
detectan y avisan a gritos, y conviene saber cuáles son para no confundirlos con éste:

| Desajuste | Qué pasa |
|---|---|
| modelo ≠ bolsas | falla al arrancar, nombrando cuántas features tiene cada uno |
| `geometrias_014.json` ≠ modelo | falla al arrancar: *«La geometría del modelo MIL difiere de la de 01.4…»* |
| **CSV ≠ bolsas** | **no falla. Nadie avisa.** |

---

## 5. Forzar una reconstrucción a mano

Casi nunca hace falta — para eso están las huellas —, pero si dudas:

```bash
# un tablero estático (01, 02, 03, 04)
cd aplicaciones/01_clima && python3 ../_comun/gestor.py construir

# el simulador
cd aplicaciones/06_simulador && python3 ../_comun/gestor.py iniciar --reconstruir
```

Detén antes cualquier instancia abierta: el simulador tiene su paquete mapeado en
memoria.

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

## 7. Dos trampas de Git LFS

1. **`Indicadores_vano_v3.csv` de 130 bytes.** Es el puntero de LFS sin descargar, no los
   datos. Las aplicaciones lo detectan y lo dicen con esas palabras; la salida es
   `git lfs pull` en la raíz.
2. **Un `git lfs pull` puede provocar una reconstrucción de más.** Los archivos pesados se
   vigilan por bytes + fecha, y LFS reescribe la fecha aunque el contenido sea idéntico.
   Es deliberado: una marca de tiempo falla del lado seguro. Cuesta unos segundos una vez.

Lo mismo vale para un `git checkout` que mueva fechas: por eso los archivos pequeños —
cuadernos y catálogos, ~1 MB — se vigilan por **contenido** (sha1) y no por fecha.

---

## 8. Si agregas un insumo nuevo

Si un cuaderno pasa a leer un archivo que antes no leía, **agrégalo a la lista de
vigilados en el mismo commit**:

- tableros estáticos → `_DATOS` o `_CODIGO` en `aplicaciones/_comun/construccion.py`
- simulador → `INSUMOS_POR_CONTENIDO` o `INSUMOS_POR_MARCA` en
  `aplicaciones/06_simulador/preparar.py`

Contenido (sha1) para lo pequeño, marca (bytes + fecha) para lo pesado.

Olvidarlo ya pasó dos veces, las dos en silencio: con `Variables_simular.xlsx` primero y
con `Variables_seleccion.xlsx` después. Hay una prueba
(`test_todo_insumo_que_el_simulador_exige_esta_ademas_vigilado`) que compara la lista de
lo que se exige para construir contra la de lo que se vigila, para que no haya un tercero.
