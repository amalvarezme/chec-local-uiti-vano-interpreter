"""Committed generator for notebook 10 -- multiple-instance learning (MIL)
over 01.4's vano x window bags.

Follows the convention recovered from commit `28e8dfe`
(`scripts/generate_notebook_12.py`, since deleted alongside notebooks
02.1/11/12): this module is the single source of truth for
`notebooks/05_*.ipynb`. The notebook itself is GENERATED
OUTPUT, never hand-edited.

Pipeline (`main`): build the in-memory notebook -> assign deterministic cell
ids -> reject forbidden literals -> `ast.parse` every code cell ->
`nbformat.validate` -> write to disk. Running the notebook (smoke or full)
is a separate, MANUAL step this module never launches -- doing so trains the
MIL model on 288,632 instance rows, and no MIL training has ever been timed
on this machine (design #530's Cost section). The generated notebook itself
carries a mandatory self-timing forecast cell for exactly that reason.

References:
  - spec: sdd/notebook-10-mil-vano-ventana/spec
  - design: sdd/notebook-10-mil-vano-ventana/design (revision 2)
  - PR1: src/chec_impacto/data/bags.py
  - PR2: src/chec_impacto/models/criticality_assignment.py
  - geometry re-sourcing: sdd/retire-base-apps-notebooks/design (D3, D3b) --
    the KMeans geometry is a tracked artifact
    (data/geometria_kmeans_014_v1.json, produced by
    scripts/exportar_geometria.py), no longer extracted from a notebook
  - PR3: src/chec_impacto/models/mgcecdl_mil.py
  - PR4: src/chec_impacto/interpretability/mil_vano_ventana.py
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_10_PATH = REPO_ROOT / "notebooks" / "05_mil_vano_ventana.ipynb"

# `p` (instance feature count) must never be hardcoded -- it is always
# derived at runtime from `CodCausaEncoding`/`X_inst_bolsas.shape[1]` (obs
# #536 corrected an earlier design-time estimate of "81-85"; the real,
# pinned-threshold value is 80, and this generator must never spell it out).
# `E == 64` is the OPPOSITE case: design's Assertion Placement table requires
# it printed and asserted literally, so 64 is deliberately NOT forbidden.
FORBIDDEN_LITERALS = ("80", "81", "82", "83", "84", "85")

_KERNELSPEC = {
    "display_name": "Python 3 (ipykernel)",
    "language": "python",
    "name": "python3",
}
_LANGUAGE_INFO = {
    "name": "python",
    "pygments_lexer": "ipython3",
    "codemirror_mode": {"name": "ipython", "version": 3},
    "file_extension": ".py",
    "mimetype": "text/x-python",
    "nbconvert_exporter": "python",
    "version": "3.11",
}


# ---------------------------------------------------------------------------
# Cell source constants -- every cell body below uses `'''...'''` at the
# Python level (this file); no cell body contains a Python docstring, which
# would terminate the outer raw string (same GOTCHA as notebook 12's
# generator).
# ---------------------------------------------------------------------------


_MD_ENTRENAMIENTO = '''\
---

# Reentrenamiento desde cero

Todo lo que sigue corre SOLO con `EJECUCION = "entrenamiento"`. Con el valor
por defecto (`"visualizacion"`) cada celda de aqui en adelante no hace nada, y
el cuaderno termina en segundos.

Reentrenar con `mode = "full"` toma alrededor de 40 minutos y SOBREESCRIBE
`data/models/mil_vano_ventana_v1.pt`, que es el artefacto que consume el
simulador de 01.5.
'''

_MD_ARQUITECTURA = '''\
## Arquitectura

Cada **bolsa** es una celda `(CIRCUITO, FID_VANO, ventana)`; cada **instancia**
es un evento de falla dentro de ella. El modelo predice un escalar por bolsa,
`p_bag ~ log1p(uiti_acumulado)`, y la **clase de criticidad se deriva** con la
regla de vecino mas cercano que 01.4 ya calculo -- nunca se reajusta aqui.

```mermaid
flowchart TD
    X["x_inst (n_inst x p)<br/>+ instance_bag (CSR)"] --> E1
    subgraph PASO1["Paso 1 -- fuente de la compuerta"]
        E1["encoders por modalidad<br/>estructural (30) | climatica (50)"] --> Z1["z1 (n_inst x 128)"]
        Z1 --> AP["SegmentAttentionPool<br/>invariante a cardinalidad"]
        AP --> ZB["z_bag (n_bags x 128)"]
        ZB --> GD["PerSampleEdgeGateDecoder<br/>g = 2*sigmoid(W z_bag)"]
    end
    GD --> PROP["propagacion sobre el grafo experto FIJO<br/>x' = x + alpha * g * A^T x"]
    X --> PROP
    PROP --> E2
    subgraph PASO2["Paso 2 -- el MISMO modulo base"]
        E2["encoders + decoders"] --> Z2["z2 (n_inst x 128)"]
        E2 --> REC["reconstructed_features"]
        Z2 --> AP2["la MISMA atencion<br/>(pesos compartidos)"]
        AP2 --> ZB2["z_bag_2 (n_bags x 128)"]
    end
    ZB2 --> FUS{"fusion"}
    FUS -->|concat| H1["Linear(128 -> 1)"]
    FUS -->|film| H2["z_est * (1 + gamma(z_clim)) + beta(z_clim)<br/>Linear(64 -> 1)"]
    FUS -->|reliability| H3["sum_m r_m * p_m"]
    H1 --> P["p_bag"]
    H2 --> P
    H3 --> P
    P --> CLS["asignar_clase(n_obs OBSERVADO, expm1(p_bag), geometria de 01.4)<br/>-> Bajo | Medio | Medio-Alto | Alto"]
```

**Tres propiedades que no son detalles:**

- **Invariancia de cardinalidad.** Duplicar todas las instancias de una bolsa
  deja `p_bag` identico. Sin eso el modelo podria leer `num_eventos` por la
  puerta de atras, y `num_eventos` es exactamente el target que se descarto.
- **`n_obs` es OBSERVADO, nunca predicho.** De las dos coordenadas que deciden
  la clase, el modelo solo aporta `u`.
- **El grafo es fijo y las columnas de grado 0 quedan intactas.** `index_add`
  solo escribe en `edge_cols`; los indicadores `COD_CAUSA_*` sin aristas pasan
  sin tocarse.
'''

_MD_PERDIDA = '''\
## Funcion de costo

Se lee en cuatro pasos, y el orden importa: primero **como se produce
$\\hat{p}_b$**, porque sin eso ninguna formula se sostiene; despues el **termino
general**; despues **donde entra el grafo fijo**, que es la pregunta que mas se
malinterpreta; y al final **cada termino** con su motivo.

### 1. De la bolsa a la prediccion

Se arma en dos pasadas sobre la MISMA base, con atencion por segmento (una
distribucion por bolsa, no por lote):

$$
e_i = w^{\\top} \\tanh(V z_i), \\qquad
a_i = \\frac{\\exp(e_i)}{\\sum_{j \\in b(i)} \\exp(e_j)}, \\qquad
z_b = \\sum_{i \\in b} a_i\\, z_i
$$

La compuerta por bolsa $g_b = 2\\,\\sigma(W z_b) \\in (0,2)^E$ modula el grafo fijo
y propaga sobre las instancias, escribiendo SOLO en las columnas destino de las
$E$ aristas:

$$
x'_i = x_i + \\alpha \\sum_{(r \\to c) \\in \\mathcal{E}} g_{b(i),\\,rc}\\; A_{rc}\\; x_{i,r}\\; \\mathbf{e}_c
$$

La segunda pasada re-codifica $x'$, re-agrupa con la MISMA atencion (pesos
compartidos) y produce $z_b^{(2)}$. Bajo `fusion="film"` -- la del artefacto
guardado -- la modalidad climatica RE-ESCALA a la estructural en vez de
concatenarse con ella:

$$
z^{\\mathrm{film}}_b = z^{\\mathrm{est}}_b \\odot (1 + \\gamma(z^{\\mathrm{clim}}_b)) + \\beta(z^{\\mathrm{clim}}_b),
\\qquad \\hat{p}_b = \\mathrm{head}(z^{\\mathrm{film}}_b)
$$

Por que FiLM y no concatenar: una cabeza lineal sobre el latente concatenado es
EXACTAMENTE aditiva entre modalidades, asi que no puede representar un producto
entre una feature estructural y una climatica. Medido, el unico camino cruzado del
modelo eran las pocas aristas cruzadas del grafo, escaladas por $\\alpha$ y por la
compuerta. FiLM hace que el contexto climatico reescale lo estructural, que es
ademas la afirmacion de dominio: una rafaga pesa mas sobre un apoyo alto, viejo y
degradado. Las dos capas de FiLM se inicializan en cero, de modo que en el paso 0
la fusion es la IDENTIDAD y el entrenamiento arranca desde el camino puramente
estructural -- que es justo lo que usa la linea base que hay que superar.

### 2. Termino general

Sobre un lote de $B$ bolsas, con $\\hat{p}_b$ la prediccion de la bolsa $b$ y
$t_b = \\log(1 + u_b)$ su objetivo:

$$
\\mathcal{L}
= \\lambda_{\\mathrm{sup}}\\,\\mathcal{L}_{\\mathrm{sup}}
+ \\lambda_{\\mathrm{rec}}\\,\\tilde{\\mathcal{L}}_{\\mathrm{rec}}
+ \\lambda_{\\mathrm{MI}}\\,\\mathcal{L}_{\\mathrm{MI}}
+ \\lambda_{g}\\,\\mathcal{L}_{g}
+ \\lambda_{\\mathrm{mod}}\\,\\mathcal{L}_{\\mathrm{mod}}
+ \\lambda_{\\mathrm{cl}}\\,\\mathcal{L}_{\\mathrm{cl}}
$$

Los valores con los que se entreno el artefacto guardado son
$\\lambda_{\\mathrm{sup}} = 1$, $\\lambda_{\\mathrm{rec}} = \\lambda_{\\mathrm{MI}} = 0.01$,
$\\lambda_{g} = 0$, $\\lambda_{\\mathrm{mod}} = 0$ (inerte fuera de
`fusion="reliability"`) y $\\lambda_{\\mathrm{cl}} = 1$.

### 3. Donde entra el grafo fijo predefinido

El grafo experto $A$ es **fijo**: se registra como buffer, no como parametro, asi
que ninguna arista se aprende. `alpha` tambien es un escalar fijo. Lo unico
aprendible en todo el camino del grafo es la compuerta $g_b$, que ESCALA por
bolsa las aristas que ya existen -- nunca crea ni borra ninguna.

Los seis terminos no lo usan igual, y la diferencia importa al leer resultados:

| termino | usa el grafo fijo | como |
|---|---|---|
| supervisado | **indirecto** | no aparece en la formula; entra porque $\hat{p}_b$ se calcula sobre $x'$, y $x'$ es $x$ propagado por $A$ |
| reconstruccion | **no** | a proposito: el objetivo es el $x$ ORIGINAL, no $x'$ |
| informacion mutua | **si, como REFERENCIA** | $K_g$ se construye una sola vez desde $[A \;\\lvert\; A^{\\top}]$ y es el patron contra el que se compara la representacion aprendida |
| desviacion de compuertas | **si, como SOPORTE** | el vector $g_b$ tiene una entrada por arista de $A$; $g = 1$ significa "el grafo tal cual" |
| supervision por modalidad | **no** | opera sobre predicciones por modalidad |
| clase | **no** | usa la GEOMETRIA KMeans de 04, otro artefacto fijo distinto del grafo |

La confusion facil es la ultima fila: en este cuaderno conviven dos objetos
congelados -- el **grafo** experto de variables y la **geometria** de centroides
de 04 -- y solo el primero es "el grafo".

### 4. Cada termino

**1. Supervisado** — MSE ponderado por densidad inversa del objetivo:

$$
\\mathcal{L}_{\\mathrm{sup}} = \\frac{1}{B}\\sum_{b} \\tilde{w}(t_b)\\,(\\hat{p}_b - t_b)^2,
\\qquad
w(t) = \\frac{1}{\\max(\\hat{f}_{\\mathrm{KDE}}(t),\\, \\varepsilon)},
\\qquad
\\tilde{w} = \\frac{w}{\\bar{w}}
$$

*Grafo fijo: **indirecto**.* La formula no lo menciona, pero $\\hat{p}_b$ ya viene
de la segunda pasada, es decir de $x'$ -- y $x'$ es $x$ propagado por $A$. Si se
apagara la propagacion ($\\alpha = 0$), este termino seguiria siendo calculable y
el grafo desapareceria por completo del gradiente.

$\\hat{f}_{\\mathrm{KDE}}$ es una gaussiana ajustada UNA vez sobre los $t$ del
pliegue de ENTRENAMIENTO, evaluada en una grilla e interpolada por lote (no hay
evaluacion kernel de $O(B \\times n_{\\mathrm{train}})$ por paso). La
renormalizacion $\\tilde{w} = w/\\bar{w}$ deja la media de pesos en 1 por lote,
asi que la escala es comparable con un MSE plano.

**2. Reconstruccion** — sobre la entrada ESTANDARIZADA $z = (x - \\mu)/\\sigma$:

$$
\\mathcal{L}^{\\mathrm{raw}}_{\\mathrm{rec}} = \\frac{1}{n\\,p}\\sum_{i,j} (\\hat{x}_{ij} - z_{ij})^2,
\\qquad
\\tilde{\\mathcal{L}}_{\\mathrm{rec}} = \\frac{\\mathcal{L}^{\\mathrm{raw}}_{\\mathrm{rec}}}{1 + \\mathcal{L}^{\\mathrm{raw}}_{\\mathrm{rec}}} \\in [0, 1)
$$

*Grafo fijo: **no lo usa**, y es deliberado.* El objetivo es el $x$ ORIGINAL,
nunca $x'$: con $x'$ la compuerta -- lo unico aprendible del camino del grafo --
controlaria su propio objetivo y podria bajar la perdida simplificandolo en vez
de mejorar la representacion. Es el unico termino que se define EXPLICITAMENTE
por fuera del grafo. La forma $\\mathrm{raw}/(1+\\mathrm{raw})$ acota en $[0,1)$
sin matar el gradiente, a diferencia de un recorte duro, que arriba de 1 tiene
derivada exactamente cero.

**3. Informacion mutua** — entropia cuadratica de Renyi entre dos kernels sobre
variables (no sobre muestras):

$$
H_2(K) = -\\log \\sum_{i,j} \\left(\\frac{K}{\\mathrm{tr}\\,K}\\right)^2_{ij},
\\qquad
I_2(K_r, K_g) = H_2(K_r) + H_2(K_g) - H_2(K_r \\odot K_g)
$$

$$
\\mathcal{L}_{\\mathrm{MI}} = 1 - \\mathrm{clip}\\!\\left(\\frac{I_2(K_r, K_g)}{\\log p},\\, 0,\\, 1\\right)
$$

*Grafo fijo: **si, y aca es la REFERENCIA del termino**.* $K_r$ es un RBF sobre
los perfiles de variable RECONSTRUIDOS (las COLUMNAS de $\\hat{X}$, con la
distancia dividida por la dimension del perfil). $K_g$ es un RBF sobre los
perfiles del grafo $[A \\;\\lvert\\; A^{\\top}]$ -- cada variable descrita por sus
aristas de salida y de entrada -- con ancho igual a la mediana de las distancias
entre perfiles; se calcula UNA sola vez al construir la perdida y queda como
buffer constante. El gradiente NO llega a $A$: el termino empuja la
representacion aprendida hacia la estructura experta, jamas al reves. Es el unico
termino que ata las dos cosas.

**$K_g$ no se estima de los datos: son las relaciones conceptuales
predefinidas.** Vale la pena decirlo sin rodeos porque "kernel" suena a algo
ajustado. La matriz $A$ se reconstruye identica usando SOLO la lista de nombres
de las features -- sin CSV, sin $y$, sin modelo -- y sus pesos
($0.60, 0.70, 0.75, 0.80, 0.85, 0.90$) son literales escritos a mano en
`chec_impacto/data/graph.py`, del tipo `("ALTURA", "NR_T", 0.75)`: juicio
experto, no correlaciones medidas. Ademas $K_g$ se calcula en el CONSTRUCTOR de
la perdida, no en el `forward`, y se guarda como buffer -- es una constante de
todo el entrenamiento, no se recalcula por lote y no recibe gradiente.

Lo unico que los datos deciden es **cuales nodos existen**: si un codigo de causa
no alcanza el 1%, su columna no esta y las aristas que lo tocaban no se
proyectan. Los datos eligen el conjunto de nodos; nunca las aristas ni sus pesos.

| | $K_g$ | $K_r$ |
|---|---|---|
| origen | aristas conceptuales del experto | features reconstruidas del lote |
| depende de los datos | no | si |
| depende de los pesos del modelo | no | si |
| recibe gradiente | no | si |

Ese contraste es lo que le da sentido al termino: el lado experto es inmovil por
construccion, asi que $1 - \\bar{I}_2(K_r, K_g)$ solo puede empujar la
representacion aprendida hacia la estructura del grafo, nunca el grafo hacia los
datos.

**4. Desviacion de compuertas** — ancla al grafo sin compuerta:

$$
\\mathcal{L}_{g} = \\frac{1}{B\\,E}\\sum_{b,e} \\lvert g_{be} - 1 \\rvert
$$

*Grafo fijo: **si, como soporte y como ancla**.* El vector $g_b$ tiene
exactamente una entrada por arista de $A$ -- el grafo fija la dimension $E$ del
decodificador de compuertas -- y el valor 1 al que este termino ancla ES el grafo
predefinido sin modificar. Lo que penaliza es apartarse de $A$ tal cual fue
declarado; no mira los pesos $A_{rc}$, solo su conjunto de aristas.

Con $g = 2\\,\\sigma(\\cdot)$, la identidad $g = 1$ se alcanza en el cero del
logit, que es la inicializacion. Apagado ($\\lambda_g = 0$).

**5. Supervision por modalidad** — el mismo MSE ponderado, aplicado a la
prediccion propia de cada modalidad:

$$
\\mathcal{L}_{\\mathrm{mod}} = \\frac{1}{M}\\sum_{m=1}^{M} \\mathcal{L}_{\\mathrm{sup}}(\\hat{p}^{(m)}, t)
$$

*Grafo fijo: **no lo usa**.*

Es lo que mantiene LEGIBLES las confiabilidades $r_m$ bajo
`fusion="reliability"`: sin el, $r_m$ y $\\hat{p}^{(m)}$ se coadaptan y una
modalidad puede predecir ruido mientras su confiabilidad colapsa a cero para
compensar. Bajo `concat`/`film` no hay predicciones por modalidad que
supervisar: el termino es inerte, no un error.

**6. Clase** — entropia cruzada sobre las fronteras de 04, diferenciable a
traves de $\\hat{p}_b$:

$$
c^{*}_b = \\arg\\min_k d^2_k(n^{\\mathrm{obs}}_b,\\, u^{\\mathrm{obs}}_b),
\\qquad
\\hat{u}_b = \\mathrm{softplus}\\!\\left(\\mathrm{expm1}(\\hat{p}_b)\\right)
$$

$$
\\mathcal{L}_{\\mathrm{cl}} = \\mathrm{CE}\\!\\left(-\\frac{d^2(n^{\\mathrm{obs}}_b,\\, \\hat{u}_b)}{T},\\; c^{*}_b\\right)
$$

*Grafo fijo: **no lo usa**.* Lo fijo que aparece aca es la GEOMETRIA de
centroides de 04 (verificada por sha1), un artefacto distinto del grafo de
variables. Ningun $A$ interviene.

La clase objetivo se DERIVA aca de lo observado con la misma geometria, nunca se
recibe por parametro: asi es imposible pasar por accidente un objetivo
inconsistente con `asignar_clase`. El piso sobre la rama predicha es `softplus`
y no un `clamp`: en la inicializacion $\\hat{p}_b \\approx 0$, y un recorte duro
ahi tiene gradiente exactamente cero -- el termino estaria muerto justo cuando
mas importa.

### 5. Resumen operativo

```
total = 1.00 * supervisado
      + 0.01 * reconstruccion_suave
      + 0.01 * perdida_informacion_mutua
      + 0.00 * desviacion_de_compuertas
      + LAMBDA_CLASE * perdida_de_clase
```

| termino | que mide | por que esta |
|---|---|---|
| **supervisado** | `KernelDensityWeightedMSELoss(p_bag, log1p(u))` | MSE ponderado por densidad INVERSA. El KDE se ajusta SOLO sobre el pliegue de entrenamiento (higiene de pliegue) y los pesos se normalizan a media 1 por lote, para que la cola alta de UITI no se ahogue bajo la masa central |
| **reconstruccion** | `raw/(1+raw)` con `raw = MSE(reconstruido, entrada estandarizada)` | Se calcula contra el `x_inst` ORIGINAL, nunca contra `x'`: si no, la compuerta podria bajar la perdida simplificando su propio objetivo en vez de mejorar la representacion. La forma `raw/(1+raw)` acota en [0,1) SIN matar el gradiente, a diferencia de un recorte |
| **informacion mutua** | MI cuadratica de Renyi entre un kernel RBF sobre los perfiles de variables reconstruidas y el kernel del grafo fijo, normalizada por `log(p)`; la perdida es `1 - MI_norm` | Ata la representacion aprendida a la estructura del grafo experto |
| **desviacion de compuertas** | `lambda * media(abs(g - 1))` | Ancla las compuertas a la identidad. Apagado (`lambda = 0`) |
| **clase** | entropia cruzada sobre `softmax(-d^2 / T)` contra la clase observada, diferenciable a traves de `u_hat` | Sin el, nada en el costo sabe donde estan las fronteras entre centroides -- que es exactamente lo que mide la metrica |

**Dos advertencias medidas, no teoricas:**

- `TEMPERATURA_CLASE` **no** hereda el `1.0` de `distribucion_suave`. Con
  distancias de mediana 0.038, esa temperatura deja la softmax 99,9% uniforme
  (entropia 1.3850 contra `ln(4) = 1.3863`) y el termino queda en su piso desde
  la primera epoca, aportando una constante y ningun gradiente. `T = 0.01` es
  el valor medido sobre la geometria real.
- Los terminos del grafo estan acotados en [0,1] y pesan 0.01 cada uno: entre
  los dos pueden mover el total como maximo 0.02, contra un termino supervisado
  que se movio entre 0.35 y 6.8. Con estos lambda, el grafo casi no participa
  del gradiente.
'''

_MD_BOLSAS_DOC = '''\
## Como se construyen las bolsas

La unidad de aprendizaje no es el evento: es la celda **(circuito, vano,
ventana)**. Cada bolsa es el conjunto de eventos de UN vano dentro de UNA
ventana, y el modelo predice el UITI acumulado de esa celda.

- **Ventanas.** Las mismas 11 de 04, reconstruidas aqui con el mismo corte: cada
  mes calendario mas su cruce del 15 al 15 del mes siguiente, ordenados. No son
  meses, asi que no se pueden sumar entre si.
- **Solapamiento a proposito.** Las ventanas se pisan. Un evento que cae en dos
  ventanas del mismo vano genera DOS instancias, una en cada bolsa. Es la
  duplicacion ~1.81x del diseno: se documenta, no se filtra. Filtrarla cambiaria
  el soporte de las ventanas y romperia la comparabilidad con 04.
- **Solo celdas con eventos.** Una celda sin eventos nunca se convierte en
  bolsa. El numero de bolsas es exactamente el de celdas pobladas: no hay bolsas
  vacias que el modelo tenga que aprender a ignorar.
- **Instancia = fila de evento.** Cada instancia es una fila del CSV, con sus
  $p$ features de instancia; la bolsa no promedia nada antes de entrar.
- **Etiqueta de la bolsa.** $u_b = \\sum_{i \\in b} \\mathrm{UITI\\_VANO}_i$ --
  SUMA, no promedio. El objetivo optimizado es $t_b = \\log(1 + u_b)$.
- **Disposicion CSR, no tensor rellenado.** Una matriz plana `(n_inst, p)` mas
  un indice de segmento `instance_bag` y sus `offsets`/`counts`. Un tensor
  `(n_bags, max, p)` era la alternativa obvia y se descarto con numeros: 52,7%
  de las bolsas son de un solo evento y el maximo es 46, asi que rellenar
  desperdiciaria mas de 40x en computo y memoria sobre mas de la mitad de los
  datos.
- **Agrupacion para validacion cruzada.** Cada bolsa lleva `group =
  CIRCUITO|FID_VANO`. Los pliegues se arman por grupo, de modo que un mismo vano
  jamas queda partido entre entrenamiento y prueba -- sin eso, la persistencia
  del vano se filtraria como si fuera capacidad predictiva.
- **Lo que NO puede ser feature de instancia.** Dos exclusiones, ambas
  verificadas al construir la matriz y no por convencion: fuga algebraica
  (`DURACION`, `TOT_USUS`, `UITI`, `PORC_APORTE_VANO`, `UITI_VANO` -- el
  objetivo se reconstruye a partir de ellas) y senal de cardinalidad
  (`num_eventos`, `counts` -- cuentan cuantas instancias tiene la bolsa, que es
  justamente lo que la bolsa no debe poder mirar).

Los tamanos medidos sobre el dataset actual se imprimen en la celda de
construccion, y estan fijados con asserts para que un cambio silencioso de datos
falle en vez de deslizarse.
'''

_MD_VISOR = '''\
## Modelo entrenado: carga y verificacion

Lee el artefacto guardado y las predicciones fuera de pliegue de la corrida
base. El artefacto lleva sus propios nombres de features y el cargador RECHAZA
un desajuste: puntuar columnas equivocadas no lanza error por si solo, solo
devuelve un mapa creible y falso.
'''

_CODE_VISOR = '''\
RUTA_MODELO = PROJECT_ROOT / "data" / "models" / "mil_vano_ventana_v1.pt"
RUTA_OOF = DERIVED_DIR / "oof_mil_full_film_clase1.0.npz"

if ENTRENAR:
    print("Modo entrenamiento: el visor se salta y el modelo se reentrena mas abajo.")
    predictor_guardado = None
    oof = None
else:
    predictor_guardado = cargar_modelo_mil(RUTA_MODELO, device=str(DEVICE))
    meta = predictor_guardado.metadatos
    # El desglose viaja DENTRO del artefacto: `data/models/**` esta versionado
    # y `data/derived/*` no, asi que depender del .npz haria que el visor
    # fallara en cualquier checkout limpio. El .npz queda como extra opcional
    # para analisis mas profundos.
    oof = np.load(RUTA_OOF) if RUTA_OOF.exists() else None
    print(f"Modelo: {RUTA_MODELO.name}")
    print(f"  fusion={meta.get('fusion')!r} lambda_clase={meta.get('lambda_clase')} "
          f"temperatura_clase={meta.get('temperatura_clase')} epocas={meta.get('epochs')}")
    print(f"  p (features de instancia) = {len(predictor_guardado.feature_names)}")
    print(f"  macro-F1 en validacion cruzada = {meta.get('macro_f1_cv')}")
    print(f"  referencia RandomForest       = {meta.get('macro_f1_randomforest_referencia')}")
    print(f"  NOTA: {meta.get('macro_f1_cv_nota')}")
    print(f"  bolsas evaluadas              = {meta['desglose_por_clase']['modelo']['n']:,}")
    print(f"Predicciones fuera de pliegue (.npz, opcional): "
          f"{'presentes' if oof is not None else 'ausentes -- el desglose sale del artefacto'}")
'''

_MD_VARIABLES = '''\
## Variables de entrada

Una fila por variable: su **modo** tematico, su **definicion**, su **origen**, su
modalidad y su papel en el grafo experto fijo.

- **Modo** es la clasificacion tematica experta (A-F) de `variables.json`, la
  misma que colorea el grafo de variables. **Modalidad** es otra cosa: la
  particion en dos ramas -- estructural y climatica -- que el modelo usa para
  codificar por separado. Un modo no implica una modalidad.
- **Origen** distingue las tres procedencias: `base` (columna del CSV
  seleccionada en `Variables_seleccion.xlsx`), `rezago climatico` (expansion
  horaria `_0.._11` de una familia) y `derivada de COD_CAUSA` (ver abajo).
- `grado_entrada` es lo que la propagacion puede CAMBIAR de esa variable, asi que
  grado de entrada 0 significa que pasa por el grafo intacta.
  `aristas_cruzadas` cuenta las aristas que unen las dos modalidades -- el unico
  camino cruzado que el grafo aporta.

### Las derivadas de COD_CAUSA

`COD_CAUSA` es un codigo categorico y entra por dos caminos a la vez, no por
uno:

1. **`COD_CAUSA` (frecuencia relativa).** El codigo crudo se reemplaza por su
   frecuencia relativa en el dataset COMPLETO, calculada solo a partir de la
   propia columna: nunca mira el objetivo. Conserva EXACTAMENTE ese nombre
   porque es el nodo del grafo experto -- renombrarla borra sus aristas de
   entrada.
2. **Indicadores con colapso de raras.** Un `COD_CAUSA_<codigo>` binario por
   cada codigo con frecuencia $\\geq$ 1%, mas un `COD_CAUSA_OTRAS` que absorbe
   toda la cola. Ninguno tiene aristas: pasan por el grafo intactos.

La frecuencia sola perderia la identidad del codigo (dos causas distintas con la
misma frecuencia serian indistinguibles); los indicadores solos perderian el
orden de magnitud. Por eso van los dos.

### Variables descartadas

La segunda tabla lista lo que NO entra, con su razon. Son tres grupos: las que
el experto no selecciono en `Variables_seleccion.xlsx`, las que se excluyen por
**fuga algebraica** (el objetivo se reconstruye a partir de ellas) y las que se
excluyen por **senal de cardinalidad** (cuentan las instancias de la bolsa).
'''

_CODE_VARIABLES = '''\
if not ENTRENAR:
    _payload = torch.load(RUTA_MODELO, map_location="cpu", weights_only=False)
    tabla_vars = tabla_variables(
        _payload["features"], _payload["modalidades"], _payload["adjacency"],
    )
    resumen_modalidad = (
        tabla_vars.groupby("modalidad")
        .agg(variables=("variable", "size"),
             en_grafo=("en_grafo", "sum"),
             aristas_cruzadas=("aristas_cruzadas", "sum"))
        .reset_index()
    )
    print(f"p = {len(tabla_vars)} variables de instancia")
    print(resumen_modalidad.to_string(index=False))
    print()
    print("Variables que el grafo NO toca (grado de entrada 0):")
    _sin = tabla_vars.loc[tabla_vars["grado_entrada"] == 0, "variable"].tolist()
    print(f"  {len(_sin)} de {len(tabla_vars)}: {_sin}")
    print()

    # --- modo tematico + definicion + origen -------------------------------------
    # El modo sale de variables.json (la clasificacion experta A-F que colorea el
    # grafo de variables); la definicion, de Variables_seleccion.xlsx. Se buscan en
    # las dos ubicaciones posibles -- el checkout local y el Volume de Databricks --
    # y si falta alguna la columna queda vacia en vez de romper la celda.
    import json as _json
    import re as _re

    def _primero_que_exista(*rutas):
        for _r in rutas:
            if _r.exists():
                return _r
        return None

    _ruta_modos = _primero_que_exista(
        PROJECT_ROOT / "site" / "data" / "variables.json", DATA_DIR / "variables.json"
    )
    _modo_de, _nombre_modo = {}, {}
    if _ruta_modos is not None:
        _catalogo = _json.loads(_ruta_modos.read_text(encoding="utf-8"))
        for _m in _catalogo["modos"]:
            _nombre_modo[_m["id"]] = _m["nombre"]
            for _clave in ("variables", "variablesEstaticas", "familiasClimaticas"):
                for _v in _m.get(_clave, []):
                    _modo_de[_v] = _m["id"]

    _ruta_defs = _primero_que_exista(DATA_DIR / "Variables_seleccion.xlsx")
    _definicion_de, _seleccion_de = {}, {}
    if _ruta_defs is not None:
        _sel = pd.read_excel(_ruta_defs)
        _definicion_de = dict(zip(_sel["COLUMNA"], _sel["DESCRIPCIÓN_COLUMNA"]))
        _seleccion_de = dict(zip(_sel["COLUMNA"], _sel["SELECCIÓN"]))

    def _raiz(nombre):
        """Familia climatica de un rezago (`prep_7` -> `prep`), o el nombre tal cual."""
        return _re.sub(r"_\\d+$", "", nombre)

    def _origen(nombre):
        if nombre.startswith("COD_CAUSA_"):
            return "derivada de COD_CAUSA (indicador)"
        if nombre == "COD_CAUSA":
            return "derivada de COD_CAUSA (frecuencia)"
        # Un sufijo `_<digitos>` solo aparece en los rezagos horarios: las columnas
        # base que terminan en digito no llevan guion bajo (`X2`, `Y2`), asi que el
        # `_` de la expresion las excluye. Comparar contra el xlsx NO sirve aca: la
        # familia (`prep`, `temp`, ...) SI esta en el xlsx, y eso clasificaria sus
        # 12 rezagos como base.
        if _re.search(r"_\\d+$", nombre):
            return "rezago climatico"
        return "base"

    def _modo(nombre):
        # Los indicadores heredan el modo de COD_CAUSA: son la misma variable
        # expandida, no variables nuevas.
        if nombre.startswith("COD_CAUSA"):
            return _modo_de.get("COD_CAUSA", "")
        return _modo_de.get(nombre, _modo_de.get(_raiz(nombre), ""))

    def _definicion(nombre):
        if nombre == "COD_CAUSA":
            return "Frecuencia relativa del codigo de causa (target-free, nodo del grafo)"
        if nombre == "COD_CAUSA_OTRAS":
            return "Indicador: el codigo de causa cae en la cola de baja frecuencia"
        if nombre.startswith("COD_CAUSA_"):
            return f"Indicador: el codigo de causa es {nombre.rsplit('_', 1)[1]}"
        if _origen(nombre) == "rezago climatico":
            _fam, _h = _raiz(nombre), nombre.rsplit("_", 1)[1]
            _base = _definicion_de.get(_fam, f"Variable climatica {_fam}")
            return f"{_base} -- rezago de {_h} h antes del evento"
        return _definicion_de.get(nombre, "")

    tabla_vars.insert(1, "modo", [_modo(v) for v in tabla_vars["variable"]])
    tabla_vars.insert(2, "nombre_modo", [_nombre_modo.get(m, "") for m in tabla_vars["modo"]])
    tabla_vars.insert(3, "origen", [_origen(v) for v in tabla_vars["variable"]])
    tabla_vars.insert(4, "definicion", [_definicion(v) for v in tabla_vars["variable"]])

    resumen_modo = (
        tabla_vars.assign(_n=1)
        .groupby(["modo", "nombre_modo"], dropna=False)
        .agg(variables=("_n", "sum"),
             estructurales=("modalidad", lambda s: int((s == "estructurales").sum())),
             climaticas=("modalidad", lambda s: int((s == "climaticos").sum())),
             en_grafo=("en_grafo", "sum"))
        .reset_index()
        .sort_values("modo")
    )
    print("Modos tematicos (A-F de variables.json) sobre las features de instancia:")
    print(resumen_modo.to_string(index=False))
    print()
    print("Origen de las features:")
    print(tabla_vars["origen"].value_counts().to_string())
    print()
    display(tabla_vars)

    # --- lo que NO entra, con su razon -------------------------------------------
    FUGA_ALGEBRAICA = ("DURACION", "TOT_USUS", "UITI", "PORC_APORTE_VANO", "UITI_VANO")
    CARDINALIDAD = ("num_eventos", "counts")
    _usadas = set(tabla_vars["variable"]) | {_raiz(v) for v in tabla_vars["variable"]}

    _filas_descartes = []
    for _v in FUGA_ALGEBRAICA:
        _filas_descartes.append({
            "variable": _v, "modo": _modo_de.get(_v, ""),
            "definicion": _definicion_de.get(_v, ""),
            "razon": "fuga algebraica: el objetivo se reconstruye a partir de ella",
        })
    for _v in CARDINALIDAD:
        _filas_descartes.append({
            "variable": _v, "modo": _modo_de.get(_v, ""),
            "definicion": "Numero de eventos de la celda vano x ventana",
            "razon": "senal de cardinalidad: cuenta las instancias de la bolsa",
        })
    for _v, _s in sorted(_seleccion_de.items()):
        if _v in _usadas or _v in FUGA_ALGEBRAICA or _v in CARDINALIDAD:
            continue
        _filas_descartes.append({
            "variable": _v, "modo": _modo_de.get(_v, ""),
            "definicion": _definicion_de.get(_v, ""),
            "razon": ("no seleccionada por el experto (SELECCION=0)" if _s != 1
                      else "seleccionada pero no disponible como feature de instancia"),
        })
    tabla_descartes = pd.DataFrame(_filas_descartes)
    print(f"{len(tabla_descartes)} variables descartadas:")
    print(tabla_descartes["razon"].value_counts().to_string())
    display(tabla_descartes)
'''

_MD_GRAFO_INTERACTIVO = '''\
### El grafo experto fijo, interactivo

El MISMO grafo con el que se entreno el artefacto: se lee del `.pt`, no se
reconstruye, asi que lo que se ve es lo que el modelo uso. Es fijo -- el
entrenamiento no aprende aristas, solo la compuerta $g_b$ que las escala por
bolsa.

Como leerlo: el color es la modalidad, el tamano es el grado total, y el hover
trae modo, definicion y grados. Los nodos aislados a un costado son las
variables de grado 0, las que la propagacion no toca. `COD_CAUSA` es el sumidero
-- solo aristas de entrada -- y por eso concentra el flujo.
'''

_CODE_GRAFO_INTERACTIVO = '''\
if not ENTRENAR:
    import networkx as nx
    import plotly.graph_objects as go

    # Se recarga el artefacto en vez de depender de `_payload`: asi la celda
    # corre sola aunque la de variables no se haya ejecutado en esta sesion.
    _art = torch.load(RUTA_MODELO, map_location="cpu", weights_only=False)
    _A = np.asarray(_art["adjacency"])
    _feats = list(_art["features"])
    _mod_de = {f: "estructurales" for f in _feats}
    for _i in _art["modalidades"]["climaticos"]:
        _mod_de[_feats[_i]] = "climaticos"

    # Modo y definicion vienen de la celda anterior; si no corrio, el hover se
    # degrada a solo grados en vez de romper.
    _modo_txt = globals().get("_modo", lambda _n: "")
    _nombres_modo = globals().get("_nombre_modo", {})
    _def_txt = globals().get("_definicion", lambda _n: "")

    G = nx.DiGraph()
    for _i, _f in enumerate(_feats):
        G.add_node(_f, modalidad=_mod_de[_f])
    _filas, _cols = np.nonzero(_A)
    for _r, _c in zip(_filas, _cols):
        G.add_edge(_feats[_r], _feats[_c], peso=float(_A[_r, _c]))

    _grado_ent = dict(G.in_degree())
    _grado_sal = dict(G.out_degree())
    _con_aristas = [n for n in G.nodes if _grado_ent[n] + _grado_sal[n] > 0]
    _aislados = [n for n in G.nodes if _grado_ent[n] + _grado_sal[n] == 0]

    # Layout solo sobre el subgrafo conectado: mezclar los aislados en el mismo
    # spring los empuja al borde y comprime la parte que interesa. Van despues, en
    # una columna aparte, que ademas es como se leen: "estas no las toca el grafo".
    _pos = nx.spring_layout(G.subgraph(_con_aristas).to_undirected(), seed=RANDOM_STATE, k=0.9)
    _x_borde = max(p[0] for p in _pos.values()) + 0.35
    for _k, _n in enumerate(sorted(_aislados)):
        _pos[_n] = (_x_borde + 0.16 * (_k % 3), -1.0 + 0.14 * (_k // 3))

    _ejes_x, _ejes_y = [], []
    for _u, _v in G.edges():
        _ejes_x += [_pos[_u][0], _pos[_v][0], None]
        _ejes_y += [_pos[_u][1], _pos[_v][1], None]

    # Punto medio de cada arista: Plotly no da hover sobre una linea, asi que el
    # peso viaja en un marcador invisible en el medio.
    _mx, _my, _mtxt = [], [], []
    for _u, _v, _d in G.edges(data=True):
        _mx.append((_pos[_u][0] + _pos[_v][0]) / 2)
        _my.append((_pos[_u][1] + _pos[_v][1]) / 2)
        _mtxt.append(f"{_u} &#8594; {_v}<br>peso {_d['peso']:.2f}")

    COLOR_MODALIDAD = {"estructurales": "#b45309", "climaticos": "#2b6e71"}
    _trazas = [
        go.Scatter(x=_ejes_x, y=_ejes_y, mode="lines", hoverinfo="skip",
                   line=dict(width=0.9, color="#b8bcb6"), showlegend=False),
        go.Scatter(x=_mx, y=_my, mode="markers", hovertext=_mtxt, hoverinfo="text",
                   marker=dict(size=7, color="rgba(0,0,0,0)"), showlegend=False),
    ]
    for _modalidad, _color in COLOR_MODALIDAD.items():
        _ns = [n for n in G.nodes if _mod_de[n] == _modalidad]
        if not _ns:
            continue
        _trazas.append(go.Scatter(
            x=[_pos[n][0] for n in _ns], y=[_pos[n][1] for n in _ns],
            mode="markers+text", name=_modalidad,
            text=[n if _grado_ent[n] + _grado_sal[n] > 0 else "" for n in _ns],
            textposition="top center", textfont=dict(size=8),
            marker=dict(
                size=[9 + 2.6 * (_grado_ent[n] + _grado_sal[n]) for n in _ns],
                color=_color, line=dict(width=1, color="white"), opacity=0.9,
            ),
            hovertext=[
                f"<b>{n}</b><br>modalidad: {_modalidad}"
                f"<br>modo: {_modo_txt(n)} {_nombres_modo.get(_modo_txt(n), '')}"
                f"<br>grado entrada: {_grado_ent[n]} | salida: {_grado_sal[n]}"
                f"<br>{_def_txt(n)}"
                for n in _ns
            ],
            hoverinfo="text",
        ))

    fig_grafo = go.Figure(_trazas)
    fig_grafo.update_layout(
        title=(f"Grafo experto fijo del artefacto -- {G.number_of_nodes()} variables, "
               f"{G.number_of_edges()} aristas "
               f"({len(_aislados)} de grado 0, a la derecha)"),
        template="plotly_white", height=760, width=1180,
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        legend=dict(title="modalidad", orientation="h", y=1.02, x=0),
        margin=dict(l=20, r=20, t=70, b=20),
    )
    _pos_cc = _feats.index("COD_CAUSA")
    print(f"COD_CAUSA: {int((_A[:, _pos_cc] != 0).sum())} aristas de entrada, "
          f"{int((_A[_pos_cc, :] != 0).sum())} de salida (sumidero)")
    fig_grafo.show()
'''

_MD_DESEMPENO = '''\
## Desempeno del modelo base

Matriz de confusion en CONTEO y en PORCENTAJE por fila observada, mas el
desempeno por grupo y global. El porcentaje se normaliza por fila para que
cada una responda "de las bolsas que ERAN de este grupo, a donde fueron" --
la vista de recall, que es en la que una clase abandonada aparece como una
fila con la diagonal en cero.
'''

_CODE_DESEMPENO = '''\
if not ENTRENAR:
    _desglose = predictor_guardado.metadatos["desglose_por_clase"]

    for _nombre in ("modelo", "estructural (RandomForest)"):
        _d = _desglose[_nombre]
        print(f"===== {_nombre} =====")
        _conteo = pd.DataFrame(np.asarray(_d["matriz_confusion"]), index=GRUPOS, columns=GRUPOS)
        _conteo.index.name = "OBSERVADA \\ PREDICHA"
        print("\\nMatriz de confusion (conteo)")
        display(_conteo)
        _pct = pd.DataFrame(
            matriz_confusion_porcentaje(np.asarray(_d["matriz_confusion"])).round(2),
            index=GRUPOS, columns=GRUPOS,
        )
        _pct.index.name = "OBSERVADA \\ PREDICHA (%)"
        print("Matriz de confusion (% por fila observada)")
        display(_pct)
        print("Desempeno por grupo")
        display(pd.DataFrame(_d["por_clase"])[
            ["grupo", "precision", "recall", "f1", "soporte"]
        ].round(4))
        print(f"GLOBAL: accuracy={_d['accuracy']:.4f}  macro-F1={_d['macro_f1']:.4f}  "
              f"n={_d['n']:,}  clases nunca predichas={_d['clases_abandonadas']}")
        print()

    _resumen = pd.DataFrame([
        {"arm": k, "accuracy": v["accuracy"], "macro_f1": v["macro_f1"], "n": v["n"]}
        for k, v in _desglose.items()
    ]).sort_values("macro_f1", ascending=False)
    print("Comparacion global de todos los brazos")
    display(_resumen.round(6))
'''

_MD_GUARDADO = '''\
## Guardado del modelo (solo al reentrenar)

Persiste el modelo ajustado con sus nombres de features, su grafo y la
geometria, para que 01.5 pueda cargarlo. Sin esto, el modelo final vivia solo
en memoria y el simulador no tenia nada que levantar.
'''

_CODE_GUARDADO = '''\
if ENTRENAR and PROCEDER_CON_ENTRENAMIENTO_COMPLETO and mode == "full":
    ruta_modelo = guardar_modelo_mil(
        PROJECT_ROOT / "data" / "models" / "mil_vano_ventana_v1.pt",
        modelo=resultado_final["model"],
        features=features_inst,
        modalidades=modality_indices,
        adjacency=A_adyacencia,
        edges=preserved_edges,
        geometria=geometria,
        hiperparametros={
            "hidden_dim": HIDDEN_DIM, "embed_dim": EMBED_DIM, "dropout": DROPOUT,
            "alpha": ALPHA, "attn_dim": ATTN_DIM,
        },
        metadatos={
            "fusion": FUSION,
            "film_modulated_modality": FILM_MODULATED_MODALITY if FUSION == "film" else None,
            "lambda_clase": LAMBDA_CLASE,
            "temperatura_clase": TEMPERATURA_CLASE,
            "epochs": EPOCHS,
            "seed": RANDOM_STATE,
            "macro_f1_cv": float(tabla_arms.loc[tabla_arms["arm"] == "modelo", "macro_f1"].iloc[0]),
            "macro_f1_randomforest_referencia": float(
                tabla_arms.loc[tabla_arms["arm"] == "estructural", "macro_f1"].iloc[0]
            ),
            "ventana_climatica_horas": 12,
            "min_frecuencia_relativa_cod_causa": 0.01,
        },
    )
    print(f"Modelo guardado en: {ruta_modelo}")
else:
    print("Guardado OMITIDO -- solo se guarda al reentrenar con mode='full'.")
'''


_MD_TITLE = '''\
# 10. Aprendizaje de instancias multiples (MIL) sobre bolsas vano x ventana de 01.4

Cada **bolsa** es una celda `(CIRCUITO, FID_VANO, ventana)` de
`01.4_uiti_vano_trayectorias_vano.ipynb`; cada **instancia** es un evento de
falla dentro de esa celda. Las 11 ventanas de 01.3/01.4 se solapan (mes
calendario mas la cruzada del 15 al 15), asi que un mismo evento puede caer
en dos bolsas del mismo vano -- se duplica, nunca se filtra.

El modelo codifica cada instancia con `MGCECDLRegressor._encode_modalities`
(reutilizado sin cambios), agrupa las instancias de una bolsa con atencion
invariante a cardinalidad, decodifica UNA compuerta de arista por bolsa sobre
el grafo experto fijo (`PerSampleEdgeGateDecoder`, tambien reutilizado),
propaga esa compuerta hacia las instancias, vuelve a codificar y a agrupar, y
lee un escalar por bolsa `p_bag ~ log1p(uiti_acumulado)`. La clase de
criticidad reportada es la regla de vecino-mas-cercano que 01.4 ya calculo
con KMeans -- no se reajusta aqui.

Generado por `scripts/generate_notebook_10.py` (COMMITTED, reproducible).
Ver `sdd/notebook-10-mil-vano-ventana/{spec,design}` para el contrato
completo.

**Este cuaderno se genera SIN ejecutar el entrenamiento.** Ninguna corrida
MIL se ha cronometrado nunca en esta maquina -- la celda 6 mide UNA corrida
corta y proyecta el costo total antes de proponer lanzar la validacion
cruzada completa; la decision de correrla queda en manos de quien ejecute
este cuaderno.
'''

_MD_DIAGRAM = '''\
## Diagrama del flujo de datos

```mermaid
flowchart TD
    A["procesar_dataset_completo (seleccion compartida)"] --> B["codificar_cod_causa (D4)"]
    B --> C["construir_matriz_instancias -> X_inst, p features"]
    C --> D["construir_matriz_adyacencia_mgcecdl -> A, E aristas"]
    A --> E["construir_indice_bolsas (11 ventanas de 01.4) -> BagIndex"]
    F["data/geometria_kmeans_014_v1.json (versionado)"] --> G["cargar_geometria_014 + verificar_sha1_geometrias"]
    C --> H["X_inst_bolsas = X_inst[bag_index.instance_rows]"]
    E --> H
    H --> I["StratifiedGroupKFold(groups=CIRCUITO|FID_VANO)"]
    I --> J["MILBagRegressor + MILBagLoss (por pliegue)"]
    J --> K["BagPredictor -> u_hat, clase (nearest-centroid con G)"]
    K --> L["evaluar_arms vs 3 baselines, subconjunto de variacion intra-vano"]
```
'''

_CODE_PARAMETERS = '''\
# Celda de parametros (papermill). Sobrescribir con `-p mode full` para la corrida real.
# El default es "smoke" a proposito, mismo patron que la libreta 12.
mode = "smoke"

# COMO se ejecuta este cuaderno:
#   "visualizacion" (default) -> NO entrena. Lee el modelo guardado y las
#        predicciones fuera de pliegue, y reporta arquitectura, costo,
#        variables y desempeno. Corre en segundos.
#   "entrenamiento"           -> reentrena de cero (~40 min con mode="full")
#        y sobreescribe el artefacto.
EJECUCION = "visualizacion"

# Diales de BRAZO. Viven aqui, y no en la celda de configuracion, para que
# papermill pueda fijarlos con -p: atribuir un cambio exige una corrida por
# brazo, y tres cuadernos generados por separado se desincronizan solos.
#   "concat"      -> head lineal sobre el latente concatenado (brazo original)
#   "film"        -> el clima MODULA la representacion estructural
#   "reliability" -> fusion ponderada por confiabilidad a grano de bolsa
FUSION = "film"
FILM_MODULATED_MODALITY = "estructurales"
# Peso de la entropia cruzada sobre las clases de 01.4. 0.0 la apaga.
LAMBDA_CLASE = 1.0
# NO se hereda el 1.0 de distribucion_suave: con d^2 de mediana 0.038 esa
# temperatura deja la softmax 99,9% uniforme (entropia 1.3850 contra
# ln(4) = 1.3863) y el termino queda en su piso desde la primera epoca.
TEMPERATURA_CLASE = 0.01
'''

_MD_BOOTSTRAP = '''\
## Bootstrap: raiz del repo, `sys.path` y guarda de precondiciones

Falla rapido y con un mensaje accionable si los modulos de PR1-4 no son
importables. Ninguno de ellos se re-exporta desde `chec_impacto.data`,
`chec_impacto.models` o `chec_impacto.interpretability` -- se importan por
ruta completa, igual que en sus propios tests.
'''

_CODE_BOOTSTRAP = '''\
import sys
from pathlib import Path


def resolve_project_root():
    cwd = Path.cwd().resolve()
    for candidate in [cwd, *cwd.parents]:
        if (candidate / "src" / "chec_impacto").exists() and (candidate / "data").exists():
            return candidate
    raise FileNotFoundError(
        "No se encontro la raiz del proyecto (se busco un directorio con src/chec_impacto/ "
        "y data/ subiendo desde el cwd). Ejecuta este cuaderno desde el checkout."
    )


PROJECT_ROOT = resolve_project_root()
SRC_DIR = PROJECT_ROOT / "src"
DATA_DIR = PROJECT_ROOT / "data"
DERIVED_DIR = DATA_DIR / "derived"

for path_to_add in (PROJECT_ROOT, SRC_DIR):
    if str(path_to_add) not in sys.path:
        sys.path.insert(0, str(path_to_add))
DERIVED_DIR.mkdir(parents=True, exist_ok=True)

print("PROJECT_ROOT:", PROJECT_ROOT)
print("DATA_DIR:    ", DATA_DIR)

try:
    from chec_impacto.data.bags import (
        CodCausaEncoding,
        cachear_bolsas,
        codificar_cod_causa,
        construir_indice_bolsas,
        construir_matriz_instancias,
    )
    from chec_impacto.models.criticality_assignment import (
        GEOMETRIAS_SHA1_ESPERADO,
        asignar_clase,
        cargar_geometria_014,
        distribucion_suave,
        GRUPOS,
        verificar_sha1_geometrias,
    )
    from chec_impacto.models.mgcecdl_mil import MILBagLoss, MILBagRegressor, entrenar_mil
    from chec_impacto.models.mil_persistencia import cargar_modelo_mil, guardar_modelo_mil
    from chec_impacto.interpretability.mil_vano_ventana import (
        BARRA_ACEPTACION_A1_PUNTOS,
        BagPredictor,
        baseline_estructural,
        baseline_mayoritaria,
        baseline_persistencia,
        construir_folds_agrupados,
        desglose_por_circuito,
        desglose_por_clase,
        contraste_u,
        predecir_u_estructural,
        formatear_desglose_por_clase,
        matriz_confusion_porcentaje,
        tabla_variables,
        evaluar_arms,
        evaluar_diagnostico_temporal,
        grafo_por_grupo_si_no_colapsado,
        guardia_proxy_univariante_mil,
        particion_bloque_temporal,
        predict_fn,
        subconjunto_variacion_intravano,
    )
    from chec_impacto.data import construir_matriz_adyacencia_mgcecdl, procesar_dataset_completo
    from chec_impacto.models import GraphEdgeIndex, construir_edge_index
    from chec_impacto.models.mgcecdl import KernelDensityWeightedMSELoss, MGCECDLRegressor
    from chec_impacto.training import (
        calcular_estadisticas_reconstruccion_mgcecdl,
        construir_modalidades_mgcecdl,
        resolve_training_device,
    )
except ImportError as exc:
    raise SystemExit(
        "Los modulos de PR1-4 (data/bags.py, models/criticality_assignment.py, "
        "models/mgcecdl_mil.py, interpretability/mil_vano_ventana.py) no son importables "
        f"desde {SRC_DIR}. Verifica que corres desde el checkout y que el entorno tiene "
        "torch/scikit-learn/shap instalados (pip install -r requirements.txt)."
    ) from exc

print("Guarda OK: modulos PR1-4 importables.")
'''

_CODE_IMPORTS = '''\
import time

import numpy as np
import pandas as pd
import shap
import torch
from sklearn.ensemble import RandomForestRegressor

RANDOM_STATE = 42
DEVICE = resolve_training_device("auto")
print("Dispositivo de entrenamiento resuelto:", DEVICE)
if DEVICE.type == "cpu":
    print("AVISO: se entrenara en CPU. Con mode='full' esto puede tardar horas.")
'''

_MD_CONFIG = '''\
## Configuracion del presupuesto (`smoke` vs `full`)

`N_SPLITS = 5` (D8, `StratifiedGroupKFold`) es fijo en ambos modos. Los demas
hiperparametros del modelo (`HIDDEN_DIM`, `EMBED_DIM`, `ALPHA`, los `LAMBDA_*`)
son valores fijos razonables -- este cuaderno no corre una busqueda de
hiperparametros (a diferencia de la libreta 12, aqui no hay un objetivo de
Optuna definido en el diseno).
'''

_CODE_CONFIG = '''\
if EJECUCION not in ("visualizacion", "entrenamiento"):
    raise ValueError(
        f"EJECUCION desconocida: {EJECUCION!r} -- se esperaba 'visualizacion' o 'entrenamiento'."
    )
ENTRENAR = EJECUCION == "entrenamiento"
print(f"EJECUCION={EJECUCION!r} -> "
      + ("REENTRENA de cero y sobreescribe el artefacto."
         if ENTRENAR else "solo LEE el modelo guardado; no entrena nada."))

if FUSION not in ("concat", "film", "reliability"):
    raise ValueError(f"FUSION desconocida: {FUSION!r}")
if mode not in ("smoke", "full"):
    raise ValueError(f"mode desconocido: {mode!r} -- se esperaba 'smoke' o 'full'.")

N_SPLITS = 5
HIDDEN_DIM = 128
EMBED_DIM = 64
DROPOUT = 0.1
ALPHA = 0.2
ATTN_DIM = 64
LAMBDA_RECONSTRUCTION = 0.01
LAMBDA_MUTUAL_INFORMATION = 0.01
LAMBDA_GATE_DEVIATION = 0.0
# "reliability": la fusion ocurre a grano de BOLSA y revive
# base.modality_regressors / base.modality_reliability_heads, que bajo
# "concat" reciben gradiente cero. Expone `reliabilities` por bolsa.
# Supervisa la prediccion de cada modalidad por separado; es lo que
# mantiene legibles las confiabilidades (ver MILBagLoss.compute_components).
LAMBDA_MODALITY_SUPERVISED = 0.0
LR = 1e-3
WEIGHT_DECAY = 1e-5
BAG_BATCH_SIZE = 256

if mode == "smoke":
    EPOCHS = 2
    COST_CEILING_SECONDS = 900.0
else:
    EPOCHS = 30
    # Techo declarado por quien ejecuta el cuaderno para la fase costosa (validacion
    # cruzada completa): si la proyeccion de la celda de pronostico lo supera, NO se
    # lanza el entrenamiento completo.
    COST_CEILING_SECONDS = 6.0 * 3600.0

print(f"mode={mode!r} | N_SPLITS={N_SPLITS} | EPOCHS={EPOCHS} | "
      f"COST_CEILING_SECONDS={COST_CEILING_SECONDS}")
print(f"fusion={FUSION!r} | LAMBDA_MODALITY_SUPERVISED={LAMBDA_MODALITY_SUPERVISED} | "
      f"LAMBDA_CLASE={LAMBDA_CLASE} | TEMPERATURA_CLASE={TEMPERATURA_CLASE}")
'''

_MD_DATA_LOAD = '''\
### Datos e instancias

`procesar_dataset_completo` + `codificar_cod_causa` (umbral 1,0%) ->
`construir_matriz_instancias` agrega la frecuencia de `COD_CAUSA` y sus
indicadores. `p` se deriva en tiempo de ejecucion, nunca se escribe a mano.
'''

_CODE_DATA_LOAD = '''\
resultado = procesar_dataset_completo(
    path_clima=DATA_DIR / "Indicadores_vano_v3.csv",
    path_variables_seleccion=DATA_DIR / "Variables_seleccion.xlsx",
    use_sampling=False,
    target="UITI_VANO",
    filtro_uiti_max=None,
    ventana_climatica_horas=12,
)
df_identidad = resultado["df_original_copy"].reset_index(drop=True)

df_causa, encoding = codificar_cod_causa(df_identidad, min_frecuencia_relativa=0.01)
print(f"Codigos propios (frecuencia >= 1.0%): {len(encoding.codigos_propios)} "
      f"-> {encoding.codigos_propios}")
print(f"Indicadores COD_CAUSA_*: {encoding.nombres_indicadores}")

X_inst_original, features_inst = construir_matriz_instancias(
    resultado, df_causa, encoding, resultado["features"],
)
p_derivado = len(features_inst)
assert p_derivado == X_inst_original.shape[1], "p debe coincidir con el ancho de X_inst_original."
print(f"p (features de instancia, derivado en tiempo de ejecucion) = {p_derivado}")
assert features_inst.count("COD_CAUSA") == 1, (
    "'COD_CAUSA' debe aparecer exactamente una vez -- cualquier otro nombre borra el "
    "nodo del grafo experto (D4)."
)
'''

_MD_GRAPH = '''\
### Grafo experto fijo

`construir_matriz_adyacencia_mgcecdl` sobre las features de instancia.
`COD_CAUSA` debe quedar como sumidero (aristas de entrada, ninguna de salida).
'''

_CODE_GRAPH = '''\
A_adyacencia, preserved_edges = construir_matriz_adyacencia_mgcecdl(
    features_inst, ventana_climatica_horas=12,
)
edge_index = construir_edge_index(A_adyacencia, features_inst, preserved_edges)
print(f"p={len(features_inst)}  E={edge_index.n_edges}")
assert edge_index.n_edges == 64, (
    f"E={edge_index.n_edges} pero el diseno D4 deriva 64 (56 base + 8 de entrada a "
    "COD_CAUSA) para el grafo experto fijo mas la seleccion de variables actual."
)

pos_cod_causa = features_inst.index("COD_CAUSA")
in_edges_cod_causa = int((A_adyacencia[:, pos_cod_causa] != 0).sum())
out_edges_cod_causa = int((A_adyacencia[pos_cod_causa, :] != 0).sum())
print(f"COD_CAUSA: {in_edges_cod_causa} aristas de entrada, {out_edges_cod_causa} de salida")
assert in_edges_cod_causa == 8 and out_edges_cod_causa == 0, (
    "COD_CAUSA debe ser un sumidero puro (8 entradas, 0 salidas) -- D4."
)

modality_indices = construir_modalidades_mgcecdl(features_inst)
print("Modalidad estructural:", len(modality_indices["estructurales"]), "features")
print("Modalidad climatica:  ", len(modality_indices["climaticos"]), "features")
'''

_MD_GEOMETRIA = '''\
### Geometria de 01.4

Se reutiliza la geometria KMeans, congelada como artefacto versionado
(`data/geometria_kmeans_014_v1.json`) y verificada por sha1. La clase de
criticidad NO se reajusta aqui.
'''

_CODE_GEOMETRIA = '''\
geometria = cargar_geometria_014(RUTA_GEOMETRIA_KMEANS)

geometrias_sha1_real, geometrias_sha1_coincide = verificar_sha1_geometrias(RUTA_GEOMETRIA_KMEANS)
print(f"sha1 esperado de 'geometrias': {GEOMETRIAS_SHA1_ESPERADO}")
print(f"sha1 real de 'geometrias':     {geometrias_sha1_real}")
assert geometrias_sha1_coincide, (
    "La geometria KMeans versionada cambio de VALORES respecto al pin original "
    f"(esperado={GEOMETRIAS_SHA1_ESPERADO}, real={geometrias_sha1_real}). Esto "
    "significa que data/geometria_kmeans_014_v1.json fue editado -- las clases de "
    "criticidad se correrian en silencio si se continua sin revisar. Deten la "
    "corrida y reconcilia contra sdd/retire-base-apps-notebooks/design antes de "
    "seguir."
)
'''

_MD_BAGS = '''\
### Bolsas vano x ventana

Las 11 ventanas de 01.4 se solapan: un evento puede caer en dos bolsas del
mismo vano y se duplica, nunca se filtra.
'''

_CODE_BAGS = '''\
_meses = pd.period_range(df_causa["FECHA"].min(), df_causa["FECHA"].max(), freq="M")
_fin = _meses[-1].to_timestamp(how="end").normalize() + pd.Timedelta(days=1)
_cortes = []
for _k, _m in enumerate(_meses):
    _ini = _m.to_timestamp()
    _f = _meses[_k + 1].to_timestamp() if _k + 1 < len(_meses) else _fin
    _cortes.append((_ini, _f))
    _cortes.append((_ini + pd.Timedelta(days=14), _f + pd.Timedelta(days=14)))
_cortes = sorted(c for c in _cortes if c[1] <= _fin)
print(f"{len(_cortes)} ventanas (esperado: 11, identico a 01.4)")

ventanas_bolsas = [
    (f"V{k + 1}", ((df_causa["FECHA"] >= a) & (df_causa["FECHA"] < b)).to_numpy())
    for k, (a, b) in enumerate(_cortes)
]
bag_index = construir_indice_bolsas(df_causa, ventanas_bolsas, target_col="UITI_VANO")

n_bags = len(bag_index.offsets) - 1
n_inst = len(bag_index.instance_bag)
fraccion_singleton = float((bag_index.counts == 1).mean())
n_bolsas_uiti_cero = int((bag_index.y == 0).sum())

print(f"bolsas={n_bags:,}  instancias={n_inst:,}  singleton={fraccion_singleton:.3%}  "
      f"bolsas con uiti_acumulado==0: {n_bolsas_uiti_cero}")
assert n_bags == 111233, f"n_bags={n_bags}, esperado 111233 (obs #524)."
assert n_inst == 288632, f"n_inst={n_inst}, esperado 288632 (obs #524)."
assert abs(fraccion_singleton - 0.527) < 0.001, f"fraccion singleton={fraccion_singleton}"
assert n_bolsas_uiti_cero == 0, "0 bolsas deben tener uiti_acumulado == 0 (obs #524)."

X_inst_bolsas = X_inst_original[bag_index.instance_rows]
assert X_inst_bolsas.shape == (n_inst, p_derivado)

cache_path = DERIVED_DIR / f"bolsas_mil_{mode}.joblib"
cachear_bolsas(cache_path, X_inst_bolsas, bag_index, features_inst, encoding)
print("Bolsas cacheadas en:", cache_path)
'''

_MD_CLASE_OBSERVADA = '''\
### Clase observada

`n_obs` es SIEMPRE observado; `u` es observado en la verdad y predicho (`u_hat`)
para el modelo.
'''

_CODE_CLASE_OBSERVADA = '''\
n_obs_observado = bag_index.counts.astype(np.float64)
u_observado = bag_index.y.astype(np.float64)
clase_observada, n_clamped_observado = asignar_clase(n_obs_observado, u_observado, geometria)
print(f"Distribucion de clase observada: "
      f"{pd.Series(clase_observada).value_counts().sort_index().to_dict()}")
assert n_clamped_observado == 0, (
    "El camino OBSERVADO nunca debe clampar (0 de 111.233 bolsas tienen "
    "uiti_acumulado == 0, obs #524)."
)

circuito_por_bolsa = bag_index.keys["CIRCUITO"].to_numpy()
'''

_MD_HELPERS = '''\
### Utilidades de pliegue

Subindices de bolsas, promedio por bolsa y el ciclo ajustar-evaluar que cada
pliegue reutiliza.
'''

_CODE_HELPERS = '''\
from chec_impacto.data.bags import BagIndex


def format_duration(seconds):
    seconds = int(max(seconds, 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def construir_subindice_bolsas(bag_index, X_bolsas, indices_bolsa):
    # Reconstruye un BagIndex sobre SOLO `indices_bolsa`, remapeado a un layout CSR
    # denso 0..len(indices_bolsa)-1, junto con la matriz de instancias correspondiente.
    indices_bolsa = np.asarray(indices_bolsa, dtype=np.int64)
    counts_sub = bag_index.counts[indices_bolsa]
    offsets_sub = np.zeros(len(indices_bolsa) + 1, dtype=np.int64)
    offsets_sub[1:] = np.cumsum(counts_sub)
    tramos = [
        np.arange(int(bag_index.offsets[b]), int(bag_index.offsets[b + 1]), dtype=np.int64)
        for b in indices_bolsa
    ]
    filas = np.concatenate(tramos) if tramos else np.array([], dtype=np.int64)
    instance_bag_sub = np.repeat(np.arange(len(indices_bolsa), dtype=np.int64), counts_sub)

    bag_index_sub = BagIndex(
        keys=bag_index.keys.iloc[indices_bolsa].reset_index(drop=True),
        instance_bag=instance_bag_sub,
        offsets=offsets_sub,
        counts=counts_sub,
        y=bag_index.y[indices_bolsa],
        group=bag_index.group[indices_bolsa],
        instance_rows=bag_index.instance_rows[filas],
    )
    return bag_index_sub, X_bolsas[filas]


def promedio_por_bolsa(X_bolsas, bag_index, columnas=None):
    Xc = X_bolsas if columnas is None else X_bolsas[:, columnas]
    n_bags_local = len(bag_index.offsets) - 1
    suma = np.zeros((n_bags_local, Xc.shape[1]), dtype=np.float64)
    np.add.at(suma, bag_index.instance_bag, Xc)
    return suma / bag_index.counts.reshape(-1, 1).astype(np.float64)


def construir_modelo_y_perdida(feature_mean, feature_std, kernel_loss):
    base = MGCECDLRegressor(
        modality_feature_indices=modality_indices,
        hidden_dim=HIDDEN_DIM, embed_dim=EMBED_DIM, dropout=DROPOUT,
    )
    modelo = MILBagRegressor(
        base=base, adjacency=A_adyacencia, edge_index=edge_index, alpha=ALPHA, attn_dim=ATTN_DIM,
        fusion=FUSION,
        film_modulated_modality=FILM_MODULATED_MODALITY if FUSION == "film" else None,
    ).to(DEVICE)
    perdida = MILBagLoss(
        feature_mean=feature_mean, feature_std=feature_std, adjacency_matrix=A_adyacencia,
        kernel_loss=kernel_loss, lambda_reconstruction=LAMBDA_RECONSTRUCTION,
        lambda_mutual_information=LAMBDA_MUTUAL_INFORMATION,
        lambda_gate_deviation=LAMBDA_GATE_DEVIATION,
        lambda_modality_supervised=LAMBDA_MODALITY_SUPERVISED,
        lambda_clase=LAMBDA_CLASE, geometria=geometria,
        temperatura_clase=TEMPERATURA_CLASE,
        reconstruction_normalization="soft",
    ).to(DEVICE)
    return modelo, perdida


def evaluar_lote_completo(modelo, X_bolsas_sub, bag_index_sub):
    # Corre el modelo una vez sobre TODAS las bolsas de `bag_index_sub` y devuelve
    # tanto u_hat como las compuertas por bolsa (para A4 mas abajo).
    modelo.eval()
    with torch.no_grad():
        x_tensor = torch.as_tensor(X_bolsas_sub, dtype=torch.float32, device=DEVICE)
        bag_tensor = torch.as_tensor(bag_index_sub.instance_bag, dtype=torch.long, device=DEVICE)
        n_bags_sub = len(bag_index_sub.offsets) - 1
        salida = modelo(x_tensor, bag_tensor, n_bags_sub)
    u_hat = np.expm1(salida["p_bag"].detach().cpu().numpy())
    gates = salida["edge_gates"].detach().cpu().numpy()
    return u_hat, gates


def ajustar_y_evaluar_pliegue(train_idx, test_idx, *, epochs, seed):
    bag_index_train, X_train_bag = construir_subindice_bolsas(bag_index, X_inst_bolsas, train_idx)
    bag_index_test, X_test_bag = construir_subindice_bolsas(bag_index, X_inst_bolsas, test_idx)

    feature_mean, feature_std = calcular_estadisticas_reconstruccion_mgcecdl(X_train_bag)
    kernel_loss = KernelDensityWeightedMSELoss.from_targets(np.log1p(bag_index_train.y))
    modelo, perdida = construir_modelo_y_perdida(feature_mean, feature_std, kernel_loss)

    resultado_fit = entrenar_mil(
        modelo, perdida, X_train_bag, bag_index_train, epochs=epochs,
        bag_batch_size=BAG_BATCH_SIZE, lr=LR, weight_decay=WEIGHT_DECAY, seed=seed, device=DEVICE,
        verbose=True,
    )
    modelo_ajustado = resultado_fit["model"]

    u_hat_test, gates_test = evaluar_lote_completo(modelo_ajustado, X_test_bag, bag_index_test)
    n_obs_test = bag_index_test.counts.astype(np.float64)
    clase_test, _ = asignar_clase(n_obs_test, u_hat_test, geometria)
    return modelo_ajustado, u_hat_test, clase_test, gates_test
'''

_MD_COST_FORECAST = '''\
### Pronostico de costo (compuerta obligatoria)

Cronometra un pliegue de referencia y proyecta la validacion cruzada completa
contra `COST_CEILING_SECONDS` antes de lanzarla.
'''

_CODE_COST_FORECAST = '''\
_pliegues_referencia = construir_folds_agrupados(bag_index, clase_observada, n_splits=N_SPLITS, seed=RANDOM_STATE)
_train_idx_ref, _test_idx_ref = _pliegues_referencia[0]

_forecast_t0 = time.time()
ajustar_y_evaluar_pliegue(_train_idx_ref, _test_idx_ref, epochs=EPOCHS, seed=RANDOM_STATE)
single_run_seconds = time.time() - _forecast_t0

N_RUNS = N_SPLITS
projected_total_seconds = single_run_seconds * N_RUNS

print(f"Un pliegue MIL de dos pasadas (epochs={EPOCHS}): "
      f"{single_run_seconds:.2f}s ({format_duration(single_run_seconds)})")
print(f"Proyeccion para los {N_RUNS} pliegues de la validacion cruzada completa: "
      f"{format_duration(projected_total_seconds)}")
print(f"Techo declarado (COST_CEILING_SECONDS): {format_duration(COST_CEILING_SECONDS)}")

PROCEDER_CON_ENTRENAMIENTO_COMPLETO = projected_total_seconds <= COST_CEILING_SECONDS
if PROCEDER_CON_ENTRENAMIENTO_COMPLETO:
    print("GO: la proyeccion cabe dentro del techo declarado -- se procede con la "
          "validacion cruzada completa.")
else:
    print("NO-GO: la proyeccion EXCEDE el techo declarado -- la validacion cruzada "
          "completa NO se lanza. Sube COST_CEILING_SECONDS o reduce EPOCHS/N_SPLITS "
          "conscientemente para continuar.")
'''

_MD_CV_LOOP = '''\
### Validacion cruzada agrupada + subconjunto intra-vano

`StratifiedGroupKFold(groups=bag_index.group)` evita que las bolsas de un mismo
vano crucen pliegues. El subconjunto de variacion intra-vano se congela ANTES
de la validacion.
'''

_CODE_CV_LOOP = '''\
folds = construir_folds_agrupados(bag_index, clase_observada, n_splits=N_SPLITS, seed=RANDOM_STATE)
subconjunto_variacion = subconjunto_variacion_intravano(bag_index, clase_observada)
print(f"Bolsas en el subconjunto de variacion intra-vano: {int(subconjunto_variacion.sum()):,} "
      f"de {n_bags:,}")

oof_clase_modelo = np.full(n_bags, -1, dtype=int)
oof_u_hat = np.full(n_bags, np.nan, dtype=np.float64)
oof_gates = np.full((n_bags, edge_index.n_edges), np.nan, dtype=np.float64)
oof_clase_mayoritaria = np.full(n_bags, -1, dtype=int)
oof_clase_estructural = np.full(n_bags, -1, dtype=int)
oof_u_estructural = np.full(n_bags, np.nan, dtype=np.float64)
oof_clase_persistencia = np.full(n_bags, -1, dtype=int)
oof_tiene_persistencia = np.zeros(n_bags, dtype=bool)

X_bag_estructural = promedio_por_bolsa(X_inst_bolsas, bag_index, modality_indices["estructurales"])

if PROCEDER_CON_ENTRENAMIENTO_COMPLETO:
    segundos_acumulados_pliegues = 0.0
    for fold_i, (train_idx, test_idx) in enumerate(folds):
        print(f"--- pliegue {fold_i + 1}/{N_SPLITS} ---")
        _pliegue_t0 = time.perf_counter()
        _, u_hat_test, clase_test, gates_test = ajustar_y_evaluar_pliegue(
            train_idx, test_idx, epochs=EPOCHS, seed=RANDOM_STATE + fold_i,
        )
        segundos_pliegue = time.perf_counter() - _pliegue_t0
        segundos_acumulados_pliegues += segundos_pliegue
        pliegues_completados = fold_i + 1
        pliegues_restantes = N_SPLITS - pliegues_completados
        segundos_restantes_pliegues = pliegues_restantes * (
            segundos_acumulados_pliegues / pliegues_completados
        )
        print(f"    pliegue {pliegues_completados}/{N_SPLITS} completado en "
              f"{format_duration(segundos_pliegue)} | ETA pliegues restantes: "
              f"{format_duration(segundos_restantes_pliegues)}")
        oof_clase_modelo[test_idx] = clase_test
        oof_u_hat[test_idx] = u_hat_test
        oof_gates[test_idx] = gates_test

        oof_clase_mayoritaria[test_idx] = baseline_mayoritaria(
            clase_observada[train_idx], len(test_idx),
        )
        # UN solo ajuste del RandomForest, dos salidas: la clase que publica la
        # linea base y la `u` con que la calcula. Llamar a baseline_estructural
        # ademas de esto lo ajustaria dos veces por pliegue.
        u_est_test = predecir_u_estructural(
            X_bag_estructural[train_idx], bag_index.y[train_idx], X_bag_estructural[test_idx],
            seed=RANDOM_STATE,
        )
        oof_u_estructural[test_idx] = u_est_test
        oof_clase_estructural[test_idx], _ = asignar_clase(
            bag_index.counts[test_idx].astype(np.float64), u_est_test, geometria,
        )

        test_mask_fold = np.zeros(n_bags, dtype=bool)
        test_mask_fold[test_idx] = True
        pred_persistencia_fold, tiene_persistencia_fold = baseline_persistencia(
            bag_index, clase_observada, test_mask_fold,
        )
        test_idx_ordenado = np.flatnonzero(test_mask_fold)
        oof_clase_persistencia[test_idx_ordenado] = pred_persistencia_fold
        oof_tiene_persistencia[test_idx_ordenado] = tiene_persistencia_fold

    print("Validacion cruzada completa: OK.")
else:
    print("Validacion cruzada completa OMITIDA (compuerta de costo NO-GO en la celda 7).")
'''

_MD_A1_BASELINES = '''\
### Compuerta A1 contra la mejor linea base

El modelo debe superar por >= 5,0 puntos de macro-F1 a la MEJOR linea base, no
solo a persistencia. No cumplirla se reporta como resultado negativo explicito.
'''

_CODE_A1_BASELINES = '''\
if PROCEDER_CON_ENTRENAMIENTO_COMPLETO:
    predicciones_arms = {
        "modelo": oof_clase_modelo[subconjunto_variacion],
        "mayoritaria": oof_clase_mayoritaria[subconjunto_variacion],
        "estructural": oof_clase_estructural[subconjunto_variacion],
    }
    subconjunto_con_persistencia = subconjunto_variacion & oof_tiene_persistencia
    tabla_arms = evaluar_arms(
        clase_observada, {
            "modelo": oof_clase_modelo[subconjunto_con_persistencia],
            "mayoritaria": oof_clase_mayoritaria[subconjunto_con_persistencia],
            "estructural": oof_clase_estructural[subconjunto_con_persistencia],
            "persistencia": oof_clase_persistencia[subconjunto_con_persistencia],
        },
        subconjunto_con_persistencia,
    )
    print(tabla_arms)
    print()
    print(tabla_arms.attrs["veredicto"])
else:
    print("Evaluacion A1 OMITIDA -- requiere las predicciones out-of-fold de la celda 8.")
'''

_MD_POR_CLASE = '''\
## 9.1 Desglose por clase (matriz de confusion, precision/recall/F1, accuracy)

macro-F1 no distingue "mediocre parejo" de "abandono una clase", y aqui esa
es la pregunta: `Alto` es el 10,21% del subconjunto de variacion intra-vano
(6.342 de 62.114 bolsas) y es la clase que le importa a CHEC. Un brazo que
acierte perfecto las otras tres y NUNCA prediga `Alto` saca 89,8% de
accuracy y 0,75 de macro-F1 -- y el modelo observado saca 0,7704, lo bastante
cerca de 3/4 como para que la pregunta no se pueda esquivar.

`accuracy` se reporta al lado, nunca como titular: la linea base mayoritaria
ya saca 0,4384 de accuracy contra 0,1524 de macro-F1.

Esta celda ademas PERSISTE las predicciones fuera de pliegue. Sin eso, de una
corrida de 40 minutos solo sobrevive un escalar y texto impreso, y cualquier
diagnostico posterior obliga a reentrenar.
'''

_CODE_POR_CLASE = '''\
if PROCEDER_CON_ENTRENAMIENTO_COMPLETO:
    desglose_clases = desglose_por_clase(
        clase_observada, {
            "modelo": oof_clase_modelo[subconjunto_con_persistencia],
            "estructural": oof_clase_estructural[subconjunto_con_persistencia],
            "persistencia": oof_clase_persistencia[subconjunto_con_persistencia],
            "mayoritaria": oof_clase_mayoritaria[subconjunto_con_persistencia],
        },
        subconjunto_con_persistencia,
    )
    print(formatear_desglose_por_clase(desglose_clases))

    # Las predicciones fuera de pliegue son el unico artefacto reutilizable de
    # la corrida: sin ellas, re-leer el resultado con otra metrica cuesta otro
    # entrenamiento completo. El nombre lleva el brazo para que dos corridas
    # con distinta configuracion no se pisen.
    # Contraste en espacio de `u`: los dos brazos regresan la MISMA cantidad y
    # pasan por la MISMA regla de centroide mas cercano, asi que una brecha de
    # macro-F1 vive en la regresion o en el mapeo. Comparar clases no los separa.
    print(contraste_u(
        bag_index.y,
        {
            "modelo": oof_u_hat[subconjunto_con_persistencia],
            "estructural": oof_u_estructural[subconjunto_con_persistencia],
        },
        subconjunto_con_persistencia,
    ).to_string(index=False))
    print()

    ruta_oof = DERIVED_DIR / f"oof_mil_{mode}_{FUSION}_clase{LAMBDA_CLASE}.npz"
    np.savez_compressed(
        ruta_oof,
        clase_observada=clase_observada,
        oof_clase_modelo=oof_clase_modelo,
        oof_u_hat=oof_u_hat,
        oof_clase_estructural=oof_clase_estructural,
        oof_u_estructural=oof_u_estructural,
        oof_clase_persistencia=oof_clase_persistencia,
        oof_clase_mayoritaria=oof_clase_mayoritaria,
        oof_tiene_persistencia=oof_tiene_persistencia,
        subconjunto_variacion=subconjunto_variacion,
        subconjunto_con_persistencia=subconjunto_con_persistencia,
        n_obs=bag_index.counts,
        y_uiti=bag_index.y,
    )
    print(f"Predicciones fuera de pliegue guardadas en: {ruta_oof}")
else:
    print("Desglose por clase OMITIDO -- requiere las predicciones out-of-fold.")
'''

_MD_DESGLOSE = '''\
## 10. Desglose por circuito (reporte, nunca un piso de aceptacion)

La unidad de decision es el agregado global de la celda 9; este desglose
informa, no condiciona -- se reporta pase o no pase la barra A1.
'''

_CODE_DESGLOSE = '''\
if PROCEDER_CON_ENTRENAMIENTO_COMPLETO:
    tabla_desglose = desglose_por_circuito(
        clase_observada,
        {
            "modelo": oof_clase_modelo[subconjunto_con_persistencia],
            "persistencia": oof_clase_persistencia[subconjunto_con_persistencia],
        },
        subconjunto_con_persistencia,
        circuito_por_bolsa,
    )
    print(f"{len(tabla_desglose)} circuitos en el desglose.")
    print(tabla_desglose.head(10))
else:
    print("Desglose por circuito OMITIDO -- requiere la celda 8/9.")
'''

_MD_A3 = '''\
### A3: guarda de proxy univariante

Comprueba si alguna feature observada funciona como proxy univariante de la
clase observada. No depende del modelo.
'''

_CODE_A3 = '''\
X_bag_completo = promedio_por_bolsa(X_inst_bolsas, bag_index)
tabla_proxy = guardia_proxy_univariante_mil(
    clase_observada, X_bag_completo, features_inst, seed=RANDOM_STATE,
)
print(tabla_proxy.head(10))
print("anulado:", tabla_proxy.attrs["voided"], "| max_ari:", tabla_proxy.attrs["max_ari"])
if tabla_proxy.attrs["voided"]:
    print("GUARDIA DE PROXY DISPARADA: una sola variable reproduce la clase observada.")
'''

_MD_A4 = '''\
### A4: colapso de compuertas

Si las compuertas no colapsaron, reconstruye un grafo por grupo de criticidad.
'''

_CODE_A4 = '''\
if PROCEDER_CON_ENTRENAMIENTO_COMPLETO:
    resultado_a4 = grafo_por_grupo_si_no_colapsado(
        oof_gates, edge_index, clase_observada, len(features_inst),
    )
    print("Colapso de compuerta:", resultado_a4["colapso"]["is_collapsed"])
    if resultado_a4["voided"]:
        print("A4: compuerta colapsada -- el grafo por grupo de criticidad se reporta VACIO.")
    else:
        print(f"A4: compuerta NO colapsada -- {len(resultado_a4['grafos_por_grupo'])} "
              "grafos por grupo de criticidad reconstruidos.")
else:
    print("A4 OMITIDO -- requiere las compuertas out-of-fold de la celda 8.")
'''

_MD_A6 = '''\
### A6: split temporal (diagnostico secundario)

Bloque de ventanas de entrenamiento -> bloque de prueba. Nunca reselecciona la
metrica principal; se reporta al lado.
'''

_CODE_A6 = '''\
train_mask_temporal, test_mask_temporal = particion_bloque_temporal(
    bag_index, ["V1", "V2", "V3", "V4", "V5", "V6", "V7"], ["V8", "V9", "V10", "V11"],
)
print(f"Bloque temporal: {int(train_mask_temporal.sum()):,} bolsas de entrenamiento, "
      f"{int(test_mask_temporal.sum()):,} de prueba.")

if PROCEDER_CON_ENTRENAMIENTO_COMPLETO:
    _, _, clase_temporal, _ = ajustar_y_evaluar_pliegue(
        np.flatnonzero(train_mask_temporal), np.flatnonzero(test_mask_temporal),
        epochs=EPOCHS, seed=RANDOM_STATE,
    )
    predicciones_temporal_completo = np.full(n_bags, -1, dtype=int)
    predicciones_temporal_completo[test_mask_temporal] = clase_temporal
    tabla_temporal = evaluar_diagnostico_temporal(
        clase_observada,
        {"modelo": predicciones_temporal_completo[test_mask_temporal]},
        test_mask_temporal,
    )
    print(tabla_temporal)
    print(tabla_temporal.attrs["nota"])
else:
    print("A6 OMITIDO -- requiere la compuerta de costo GO de la celda 7.")
'''

_MD_SHAP = '''\
### Kernel SHAP -> ranking Borda

Relevancias por bolsa agregadas por (circuito, vano, ventana), en formato largo
con la nota de exposicion/severidad por variable.
'''

_CODE_SHAP = '''\
from chec_impacto.interpretability.circuit_analysis import KernelShapTopVarsExtractor
from chec_impacto.interpretability.mil_vano_ventana import construir_ranking_borda

# La cola SHAP -> Borda vive en la libreria, con tests
# (tests/test_mil_ranking_borda.py). Estuvo aqui como codigo suelto de celda y
# acumulo dos defectos que solo se ejecutaban con mode='full': tratar la lista
# que devuelve `calcular_top_vars` como si fuera un dict, y colgar la nota de
# exposicion/severidad de una columna `_var` que `agregar_borda` no emite.

TOP_N_VANOS = 97

if PROCEDER_CON_ENTRENAMIENTO_COMPLETO and mode == "full":
    modelo_final, _ = construir_modelo_y_perdida(
        *calcular_estadisticas_reconstruccion_mgcecdl(X_inst_bolsas),
        KernelDensityWeightedMSELoss.from_targets(np.log1p(bag_index.y)),
    )
    resultado_final = entrenar_mil(
        modelo_final, MILBagLoss(
            *calcular_estadisticas_reconstruccion_mgcecdl(X_inst_bolsas), A_adyacencia,
            kernel_loss=KernelDensityWeightedMSELoss.from_targets(np.log1p(bag_index.y)),
            lambda_reconstruction=LAMBDA_RECONSTRUCTION,
            lambda_mutual_information=LAMBDA_MUTUAL_INFORMATION,
            lambda_gate_deviation=LAMBDA_GATE_DEVIATION, reconstruction_normalization="soft",
        ), X_inst_bolsas, bag_index, epochs=EPOCHS, bag_batch_size=BAG_BATCH_SIZE,
        lr=LR, weight_decay=WEIGHT_DECAY, seed=RANDOM_STATE, device=DEVICE,
        verbose=True,
    )
    predictor_final = BagPredictor(resultado_final["model"], features_inst, geometria, device=str(DEVICE))

    rng_shap = np.random.default_rng(RANDOM_STATE)
    indices_muestra = rng_shap.choice(n_bags, size=min(TOP_N_VANOS, n_bags), replace=False)
    extractor = KernelShapTopVarsExtractor(predictor_final, X_bag_completo, features_inst)
    top_vars_por_bolsa = extractor.calcular_top_vars(indices_muestra)

    ranking_borda = construir_ranking_borda(bag_index.keys, indices_muestra, top_vars_por_bolsa)
    print(f"Ranking Borda: {len(ranking_borda)} filas (grupo x variable) "
          f"sobre {len(indices_muestra)} bolsas muestreadas.")
    print(ranking_borda.head(15))
    n_anotadas = int((ranking_borda["nota_exposicion_severidad"] != "").sum())
    print(f"Filas marcadas como exposicion/severidad por construccion: {n_anotadas}")
else:
    print("SHAP OMITIDO -- solo corre con mode='full' y la compuerta de costo en GO.")
'''

_MD_SIMULATOR = '''\
## 15. Contrato del simulador (`predict_fn`), sin correr el simulador

`predict_fn` fija el contrato `{"fused_probs": (n, 4), "predicted_classes":
(n,)}` que `chec_local_interpreter/simulator.py` espera -- el simulador en si
NO se construye ni se corre aqui.
'''

_CODE_SIMULATOR = '''\
if PROCEDER_CON_ENTRENAMIENTO_COMPLETO and mode == "full":
    salida_simulador = predict_fn(predictor_final, X_bag_completo[:5])
    assert salida_simulador["fused_probs"].shape == (5, 4)
    assert salida_simulador["predicted_classes"].shape == (5,)
    print("Contrato predict_fn verificado sobre 5 filas de ejemplo:", salida_simulador["predicted_classes"])
else:
    print("Verificacion de predict_fn OMITIDA -- requiere un modelo final ajustado (celda 14).")
'''

_MD_LIMITACION = '''\
## 16. Techo interpretativo honesto

El techo teorico de este problema es la varianza intra-vano medida por 01.4:
39.1% de la varianza de clase vive DENTRO del vano, el 60.9% restante lo
explica la identidad del vano por si sola (obs #524) -- cualquier metrica
global hereda gratis ese 60.9%, que es exactamente lo que la linea base de
persistencia captura con ventaja informacional. Este cuaderno NO reclama
haber superado esa varianza intra-vano mas alla de lo que la barra A1
efectivamente mida.
'''

_MD_SUMMARY = '''\
## 17. Resumen final

Cantidades DERIVADAS en tiempo de ejecucion (nunca literales, salvo las
poblacionales pineadas y verificadas en la celda 4): `p`, `E`, `K`
(indicadores COD_CAUSA), tamano de poblacion, resultado A1, y el sha1 de la
geometria de 01.4.
'''

_CODE_SUMMARY = '''\
if ENTRENAR:
    resumen_final = {
        "ejecucion": EJECUCION,
        "mode": mode,
        "p": p_derivado,
        "E": edge_index.n_edges,
        "K_indicadores_cod_causa": len(encoding.codigos_propios) + 1,
        "n_bolsas": n_bags,
        "n_instancias": n_inst,
        "fraccion_singleton": fraccion_singleton,
        "geometrias_sha1_coincide": geometrias_sha1_coincide,
        "entrenamiento_completo_ejecutado": bool(PROCEDER_CON_ENTRENAMIENTO_COMPLETO),
    }
else:
    _m = predictor_guardado.metadatos
    resumen_final = {
        "ejecucion": EJECUCION,
        "modelo": RUTA_MODELO.name,
        "p": len(predictor_guardado.feature_names),
        "fusion": _m.get("fusion"),
        "lambda_clase": _m.get("lambda_clase"),
        "temperatura_clase": _m.get("temperatura_clase"),
        "macro_f1_cv": _m.get("macro_f1_cv"),
        "macro_f1_randomforest": _m.get("macro_f1_randomforest_referencia"),
        "bolsas_evaluadas": _m["desglose_por_clase"]["modelo"]["n"],
        "entrenamiento_completo_ejecutado": False,
    }
for key, value in resumen_final.items():
    print(f"{key}: {value}")
'''



_MD_AUTOCONTENIDO = '''\
## Que tan autocontenido es este cuaderno, y que alternativas hay

"Autocontenido" no es una sola cosa. Son tres grados distintos, y este cuaderno
esta en el segundo a proposito.

| grado | que significa | estado |
|---|---|---|
| 1. de datos | no necesita ningun archivo derivado por otro cuaderno | **si** en visualizacion; **no** al reentrenar |
| 2. de ejecucion | corre de punta a punta en un checkout limpio, sin correr nada antes | **si** en visualizacion |
| 3. de codigo | no importa nada del repositorio: todo vive en sus celdas | **no**, y no conviene |

**Lo medido, no lo supuesto.** Con `EJECUCION = "visualizacion"` este cuaderno
corre completo sobre un checkout recien clonado -- sin `data/derived/`, sin
haber ejecutado 01.4, sin entrenar -- en unos pocos segundos. La celda que sigue
lo verifica archivo por archivo en vez de afirmarlo.

Funciona por una decision concreta: **todo lo que el visor necesita viaja dentro
de `data/models/mil_vano_ventana_v1.pt`**, que si esta versionado. El artefacto
no guarda solo los pesos. Lleva los nombres de las features, la particion en
modalidades, la matriz del grafo experto, la lista de aristas con su camino, la
geometria KMeans de 01.4 y el desglose de desempeno por clase. Las predicciones
fuera de pliegue (`.npz`) quedaron como extra OPCIONAL justamente para que el
visor no dependa de `data/derived/`, que `.gitignore` excluye.

### Que rompe la autocontencion, y por que

- **Reentrenar.** `EJECUCION = "entrenamiento"` necesita el CSV de eventos (que
  viaja por git-lfs), la seleccion experta y la geometria KMeans de 01.4. Ese
  camino depende de 01.4 POR DISENO: la clase de criticidad no se reajusta aqui,
  se hereda. Ademas SOBREESCRIBE el artefacto que consume el simulador.
- **La descripcion de la base.** Mostrar como se ven los datos crudos exige
  abrir el CSV. No hay forma de describir una base sin mirarla; lo que si se
  puede es mirarla barata (ver la celda de vista preliminar).
- **El codigo.** Los modulos de `src/chec_impacto/` y `scripts/` se importan por
  ruta. Es la unica dependencia que NO conviene eliminar: son miles de lineas con
  pruebas propias.

### Las alternativas, con lo que cuesta cada una

| alternativa | que resolveria | que cuesta | veredicto |
|---|---|---|---|
| Copiar la libreria dentro de celdas | grado 3 completo | duplica miles de lineas ya probadas; las pruebas dejan de cubrir lo que corre; el cuaderno se desincroniza del paquete a la primera correccion | **descartada** |
| Empaquetar `src/` como wheel e instalarlo con `%pip install` | quita el `sys.path` manual | agrega un paso de construccion y un pin de version; el cuaderno deja de leer el arbol de trabajo, asi que editar `src/` ya no llega | **solo para Databricks**, donde `/subir-notebooks-databricks` ya hace el equivalente |
| Versionar `data/derived/` | grado 1 en los dos modos | cientos de MB de `joblib` en git para archivos que cualquier corrida reproduce | **descartada** (`.gitignore` ya lo decidio) |
| Leer la geometria KMeans del `.pt` en vez de un artefacto versionado | grado 1 para el visor | ninguno: la geometria ya viaja dentro del artefacto | **adoptada para visualizacion** -- las celdas de visualizacion la leen del `.pt`; el camino de entrenamiento lee `data/geometria_kmeans_014_v1.json` (versionado, productor `scripts/exportar_geometria.py`), sin extraer de ninguna notebook (`sdd/retire-base-apps-notebooks/design`, D3b) |
| Congelar tambien una vista de la base dentro del `.pt` | quitaria el CSV de las celdas descriptivas | el artefacto dejaria de ser un modelo y pasaria a ser un cache de datos; habria que regenerarlo con cada base | **descartada**: la vista preliminar cuesta menos que el problema que crea |

**Regla que queda escrita.** Ninguna celda del camino de visualizacion escribe
en disco ni depende de `data/derived/`. Si una celda nueva necesita un derivado,
va al camino de entrenamiento o se lee del artefacto.
'''

_CODE_INSUMOS = '''\
# De donde lee este cuaderno cada cosa. Se resuelve contra el checkout ACTUAL y no
# contra una lista escrita a mano: un archivo que se movio aparece aqui como ausente,
# en vez de reventar tres celdas mas abajo con un FileNotFoundError sin contexto.
import hashlib as _hashlib
import re


def _huella(ruta, tope=4 * 1024 * 1024):
    """sha1 de los primeros `tope` bytes. Sobre el CSV de eventos el hash completo
    cuesta segundos en CADA apertura y no responde nada que el tamano no responda ya;
    sobre los artefactos pequenos cubre el archivo entero."""
    if not ruta.exists() or ruta.is_dir():
        return ""
    h = _hashlib.sha1()
    with open(ruta, "rb") as fh:
        h.update(fh.read(tope))
    return h.hexdigest()[:12]


def _mb(ruta):
    if not ruta.exists():
        return None
    if ruta.is_dir():
        return sum(f.stat().st_size for f in ruta.rglob("*") if f.is_file()) / 1e6
    return ruta.stat().st_size / 1e6


RUTA_CSV_EVENTOS = DATA_DIR / "Indicadores_vano_v3.csv"
RUTA_SELECCION = DATA_DIR / "Variables_seleccion.xlsx"
RUTA_ARTEFACTO = DATA_DIR / "models" / "mil_vano_ventana_v1.pt"
RUTA_GEOMETRIA_KMEANS = DATA_DIR / "geometria_kmeans_014_v1.json"
RUTA_VARIABLES_JSON = PROJECT_ROOT / "site" / "data" / "variables.json"
RUTA_SIMULAR = DATA_DIR / "Variables_simular.xlsx"
# El mismo nombre que declara la celda del visor. Se repite aqui en vez de importarse
# de mas abajo para que el inventario corra ANTES de intentar cargar nada.
RUTA_OOF_DECLARADA = DERIVED_DIR / "oof_mil_full_film_clase1.0.npz"

_INSUMOS = [
    (RUTA_ARTEFACTO, "git", "visualizacion",
     "pesos, features, modalidades, grafo experto, aristas, geometria KMeans y desglose"),
    (RUTA_VARIABLES_JSON, "git", "opcional",
     "modos tematicos A-F que colorean el grafo de variables"),
    (RUTA_SELECCION, "git", "entrenamiento",
     "seleccion experta (SELECCION=1) y la definicion de cada columna"),
    (RUTA_CSV_EVENTOS, "git-lfs", "entrenamiento",
     "una fila por evento de falla: es la base de la que salen las instancias"),
    (RUTA_GEOMETRIA_KMEANS, "git", "entrenamiento",
     "geometria KMeans congelada y versionada (productor: scripts/exportar_geometria.py)"),
    (RUTA_OOF_DECLARADA, "derivado, NO versionado", "opcional",
     "predicciones fuera de pliegue de la corrida base"),
    (RUTA_SIMULAR, "git", "no lo usa este cuaderno",
     "catalogo de controles del simulador; se lista porque describe las MISMAS features"),
    (PROJECT_ROOT / "src" / "chec_impacto", "git", "los dos modos",
     "bolsas, grafo, modelo MIL, perdida, asignacion de clase y persistencia"),
]

tabla_insumos = pd.DataFrame([
    {
        "insumo": str(r.relative_to(PROJECT_ROOT)) if PROJECT_ROOT in r.parents else str(r),
        "existe": r.exists(),
        "MB": None if _mb(r) is None else round(_mb(r), 2),
        "sha1_12": _huella(r),
        "procedencia": proc,
        "hace_falta_en": cuando,
        "que_aporta": aporta,
    }
    for r, proc, cuando, aporta in _INSUMOS
])

_modo_actual = "entrenamiento" if ENTRENAR else "visualizacion"
_requeridos = tabla_insumos[tabla_insumos["hace_falta_en"].isin((_modo_actual, "los dos modos"))]
_faltan = _requeridos.loc[~_requeridos["existe"], "insumo"].tolist()

print(f"Modo actual: {_modo_actual!r}")
print(f"Insumos requeridos presentes: {int(_requeridos['existe'].sum())} de {len(_requeridos)}")
if _faltan:
    print("FALTAN (este modo no correra completo):")
    for _f in _faltan:
        print("  -", _f)
else:
    print("No falta ninguno: el cuaderno corre de punta a punta en este checkout.")
# Las celdas DESCRIPTIVAS -- la vista preliminar de la base y los modos tematicos --
# leen archivos que este modo no exige. Se degradan a un aviso en vez de fallar, asi
# que su ausencia no aparece arriba: se dice aqui para que no se lea como que sobran.
_desc_faltan = [n for n, e in zip(tabla_insumos["insumo"], tabla_insumos["existe"])
                if not e and n not in _faltan]
if _desc_faltan:
    print("Ausentes pero NO requeridos en este modo (las celdas que los usan avisan y siguen):")
    for _f in _desc_faltan:
        print("  -", _f)
print()
display(tabla_insumos)
'''

_MD_BASE_CRUDA = '''\
## La base cruda: una vista preliminar de `Indicadores_vano_v3.csv`

Antes de hablar de features conviene ver de que se parte. La base tiene **una
fila por evento de falla** -- no por vano y no por dia --, y arrastra en esa
misma fila todo lo que se sabe del vano, del apoyo, del transformador, del
equipo que lo protege y del clima de las 12 horas previas.

La celda que sigue **no carga la base**. Abre el primer bloque con
`pyarrow.csv.open_csv` y se detiene ahi: para una vista preliminar hacen falta el
encabezado, los tipos y unas filas, no los cientos de MB. Leerla entera con
`pandas.read_csv` cuesta decenas de segundos y un pico de memoria de varios
cientos de MB, y no responderia nada mas de lo que responde el primer bloque.

Los tipos que se reportan son los que **infiere pyarrow del texto del CSV**, no
los que tendra la matriz del modelo: todo lo que entra al modelo termina en
`float32`, y como llega ahi es justamente lo que explica la seccion siguiente.
'''

_CODE_VISTA_PREVIA = '''\
# Vista preliminar SIN cargar la base. `pyarrow.csv.open_csv` devuelve el primer
# bloque y se detiene; `pandas.read_csv` leeria el archivo entero para responder lo
# mismo. El bloque se pide pequeno a proposito: la vista previa no mejora con mas
# filas, y el costo si crece.
FILAS_VISTA_PREVIA = 8

try:
    import pyarrow.csv as _pacsv
except ImportError:
    _pacsv = None

if _pacsv is None or not RUTA_CSV_EVENTOS.exists():
    print("Vista preliminar OMITIDA: falta el CSV de eventos o pyarrow no esta instalado.")
    print(f"  CSV: {RUTA_CSV_EVENTOS} (existe: {RUTA_CSV_EVENTOS.exists()})")
    tipos_csv = {}
else:
    _lector = _pacsv.open_csv(
        RUTA_CSV_EVENTOS, read_options=_pacsv.ReadOptions(block_size=1 << 20)
    )
    _bloque = _lector.read_next_batch()
    tipos_csv = {c: str(t) for c, t in zip(_bloque.schema.names, _bloque.schema.types)}
    _muestra = _bloque.slice(0, FILAS_VISTA_PREVIA).to_pandas()

    print(f"{_bloque.num_columns:,} columnas | primer bloque leido: "
          f"{_bloque.num_rows:,} filas | la base completa NO se carga")
    print()

    # Que hace cada columna del CSV en este cuaderno. Las tres respuestas posibles son
    # distintas y conviene no mezclarlas: entrar al modelo, definir la bolsa (clave o
    # etiqueta) o quedarse fuera.
    _features_art = list(globals().get("_features_artefacto", []))
    if not _features_art and RUTA_ARTEFACTO.exists():
        _features_art = list(
            torch.load(RUTA_ARTEFACTO, map_location="cpu", weights_only=False)["features"]
        )
        _features_artefacto = _features_art
    _familias_usadas = {re.sub(r"_\\d+$", "", f) for f in _features_art}
    _CLAVES_BOLSA = {"CIRCUITO": "clave de bolsa", "FID_VANO": "clave de bolsa",
                     "FECHA": "define la ventana", "UITI_VANO": "objetivo de la bolsa"}

    def _papel_columna(col):
        if col in _CLAVES_BOLSA:
            return _CLAVES_BOLSA[col]
        if col == "COD_CAUSA":
            return "entra derivada (frecuencia + indicadores)"
        if col in _features_art or col in _familias_usadas:
            return "entra como feature de instancia"
        return "no entra"

    tabla_columnas = pd.DataFrame({
        "columna": list(tipos_csv),
        "tipo_en_el_csv": [tipos_csv[c] for c in tipos_csv],
        "papel_en_este_cuaderno": [_papel_columna(c) for c in tipos_csv],
    })
    print("Tipos que infiere pyarrow del texto del CSV:")
    print(tabla_columnas["tipo_en_el_csv"].value_counts().to_string())
    print()
    print("Papel de cada columna:")
    print(tabla_columnas["papel_en_este_cuaderno"].value_counts().to_string())
    print()
    print(f"Primeras {FILAS_VISTA_PREVIA} filas (columnas que definen la bolsa y su objetivo):")
    _cols_clave = [c for c in ("CIRCUITO", "FID_VANO", "FECHA", "COD_CAUSA",
                               "DURACION", "TOT_USUS", "UITI", "UITI_VANO")
                   if c in _muestra.columns]
    display(_muestra[_cols_clave])
    print("Catalogo completo de columnas:")
    display(tabla_columnas)
'''

_MD_PREPROCESOS = '''\
## Los preprocesos, variable por variable, y que significa cada uno

Entre el CSV y la matriz que ve el modelo hay una cadena fija. Ninguno de sus
pasos ajusta nada contra el objetivo: la unica estadistica que se calcula sobre
los datos es la frecuencia de `COD_CAUSA`, y depende solo de esa columna.

**1. Seleccion experta.** Se conservan las columnas con `SELECCION = 1` en
`Variables_seleccion.xlsx`. El objetivo (`UITI_VANO`) se salta explicitamente: es
lo que se predice, no una entrada.

**2. Expansion climatica.** Una familia climatica no es una columna sino doce.
`prep` se convierte en `prep_0 .. prep_11`, donde `_0` es la hora del evento y
`_11` doce horas antes. Por eso una sola fila de `Variables_seleccion.xlsx`
puede aportar doce features, y por eso el simulador trata la familia entera como
UN control y no como doce.

**3. Fechas a numero.** Una columna con tipo de fecha pasa a segundos desde 1970 y
luego a `float32`. Con la base actual **ninguna feature toma ese camino**: la
unica columna de fecha del CSV es `FECHA`, que no es una feature -- define la
ventana de la bolsa. Las dos columnas que suenan a fecha y si son features,
`FECHA_OPERACION_VANO` y `FECHA_OPERACION_TRF`, vienen como el ANO en entero, asi
que siguen la ruta numerica. El paso queda descrito igual porque una base futura
puede traer una fecha real y el resultado cambiaria sin aviso. La celda siguiente
resuelve la ruta de cada variable contra el tipo REAL del CSV, no contra su
nombre.

**4. Imputacion numerica: un centinela, no una media.** Un faltante en una
columna numerica se reemplaza por `-10 * max(columna)`. No es un valor plausible
y no pretende serlo: cae MUY fuera del rango observado, siempre del mismo lado, y
a una distancia proporcional a la escala propia de la variable. La consecuencia
practica es doble. A favor: "no se sabe" queda distinguible y el modelo puede
aprenderlo como una condicion mas. En contra: **cualquier promedio de esa columna
deja de ser interpretable**, porque los faltantes lo arrastran. Es la razon por la
que el simulador guarda `max_values_imputed` -- sin ese diccionario no hay como
volver del centinela al valor legible.

**5. Categoricas a entero.** Cada columna de texto pasa por un `LabelEncoder`,
con los faltantes convertidos antes en la categoria `"no aplica"`. El codigo
resultante es ORDINAL sin que el orden signifique nada: `CONDUCTOR = 7` no esta
"entre" 6 y 8 en ningun sentido fisico. Es una simplificacion deliberada y tiene
consecuencia directa en el simulador: mover un control categorico exige su
`label_encoders`, y sin el la variable se salta EN SILENCIO.

**6. `COD_CAUSA`, por dos caminos a la vez.** No esta seleccionada en el Excel;
entra por su propio codificador. El codigo crudo se reemplaza por su frecuencia
relativa en la base completa -- calculada solo desde esa columna, nunca desde el
objetivo -- y ademas se abre en un indicador binario por cada codigo con
frecuencia mayor o igual al 1%, mas un `COD_CAUSA_OTRAS` que absorbe la cola. La
frecuencia sola perderia la identidad del codigo; los indicadores solos perderian
el orden de magnitud. La columna de frecuencia conserva EXACTAMENTE el nombre
`COD_CAUSA` porque es el nodo del grafo experto: renombrarla borra sus aristas.

**7. Lo que NO se hace, y conviene saberlo.** No hay estandarizacion global de la
entrada. El encoder ve `x` tal cual y se apoya en `LayerNorm` por instancia; la
media y la desviacion por columna (`feature_mean`, `feature_std`) se calculan
sobre el pliegue de ENTRENAMIENTO y se usan SOLO dentro del termino de
reconstruccion de la perdida. Tampoco hay imputacion por vecinos, ni recorte de
atipicos, ni balanceo de clases: el desbalance se trata en la perdida, con pesos
de densidad inversa, no tocando los datos.

**8. Exclusiones verificadas, no convenidas.** Dos familias no pueden ser feature
de instancia y la construccion de la matriz lo comprueba en vez de confiar en la
convencion: **fuga algebraica** (`DURACION`, `TOT_USUS`, `UITI`,
`PORC_APORTE_VANO`, `UITI_VANO` -- el objetivo se reconstruye a partir de ellas) y
**senal de cardinalidad** (`num_eventos`, `counts` -- cuentan cuantas instancias
tiene la bolsa, que es justo lo que la bolsa no debe poder mirar).
'''

_CODE_PREPROCESOS = '''\
# La cadena de preproceso, resuelta variable por variable sobre las features REALES
# del artefacto. Se deriva de los nombres y del tipo original en el CSV, no de una
# lista escrita a mano: una feature nueva aparece aqui sola.
_art_pre = torch.load(RUTA_ARTEFACTO, map_location="cpu", weights_only=False)
_features_artefacto = list(_art_pre["features"])
_climaticas = {_features_artefacto[i] for i in _art_pre["modalidades"]["climaticos"]}

_tipos_csv = globals().get("tipos_csv", {})
_defs = {}
if RUTA_SELECCION.exists():
    # La columna de descripcion lleva tilde en el archivo. Se toma por POSICION y no
    # por nombre: dos codificaciones distintas del mismo Excel dan dos cadenas
    # distintas, y el fallo seria una columna de definiciones vacia sin ningun error.
    _sel_df = pd.read_excel(RUTA_SELECCION)
    _defs = dict(zip(_sel_df[_sel_df.columns[0]], _sel_df[_sel_df.columns[1]]))


def _familia(nombre):
    return re.sub(r"_\\d+$", "", nombre)


def _cadena_de_preproceso(nombre):
    """Los pasos que atraviesa ESTA variable, en orden, como una sola cadena."""
    if nombre == "COD_CAUSA":
        return ["frecuencia relativa (solo desde su propia columna)"]
    if nombre.startswith("COD_CAUSA_"):
        return ["indicador binario (umbral 1% + cola en OTRAS)"]

    pasos = ["seleccion experta (SELECCION=1)"]
    fam = _familia(nombre)
    if fam != nombre:
        pasos.append(f"expansion climatica de '{fam}' a 12 rezagos horarios")
    tipo = _tipos_csv.get(nombre, _tipos_csv.get(fam, ""))
    if "timestamp" in tipo or "date" in tipo:
        pasos.append("fecha -> segundos epoch -> float32")
    elif tipo.startswith("string") or tipo.startswith("large_string"):
        pasos.append("faltantes -> 'no aplica'; LabelEncoder (entero SIN orden real)")
    else:
        pasos.append("faltantes -> centinela -10*max(columna)")
    return pasos


def _significado(nombre):
    if nombre == "COD_CAUSA":
        return "Que tan comun es la causa de la falla, en la base completa"
    if nombre == "COD_CAUSA_OTRAS":
        return "La causa cae en la cola de codigos poco frecuentes"
    if nombre.startswith("COD_CAUSA_"):
        return f"La causa de la falla es el codigo {nombre.rsplit('_', 1)[1]}"
    fam = _familia(nombre)
    if fam != nombre:
        base = _defs.get(fam, f"Variable climatica {fam}")
        return f"{base} -- {nombre.rsplit('_', 1)[1]} h antes del evento"
    return _defs.get(nombre, "")


tabla_preprocesos = pd.DataFrame([
    {
        "variable": v,
        "modalidad": "climaticos" if v in _climaticas else "estructurales",
        "tipo_en_el_csv": _tipos_csv.get(v, _tipos_csv.get(_familia(v), "(sin CSV a la vista)")),
        "pasos": " -> ".join(_cadena_de_preproceso(v)),
        "significado": _significado(v),
    }
    for v in _features_artefacto
])

print(f"{len(tabla_preprocesos)} features de instancia, todas en float32 al final de la cadena.")
print()
print("Cuantas variables sigue cada cadena de preproceso:")
print(tabla_preprocesos["pasos"].value_counts().to_string())
print()
print("AVISO sobre el centinela de imputacion: en las columnas que lo usan, un promedio")
print("de la variable NO es interpretable -- los faltantes lo arrastran hacia abajo.")
print()
display(tabla_preprocesos)
'''

_MD_COSTO_COMPUTO = '''\
## Costo del modelo: parametros, buffers y pasadas

La seccion anterior describe QUE calcula la perdida. Esta describe CUANTO cuesta
calcularla, que es la otra mitad de la pregunta y la que decide si el
reentrenamiento cabe en la maquina que se tenga.

**Tres cantidades que no se deben mezclar:**

- **Parametros aprendibles.** Lo que el optimizador mueve. Casi todo vive en los
  codificadores y decodificadores por modalidad; el resto -- atencion, decodificador
  de compuertas, las dos capas de FiLM y la cabeza -- es una fraccion pequena.
- **Buffers fijos.** La matriz de adyacencia y los indices de arista se registran
  como buffers, no como parametros: **ocupan memoria y no reciben gradiente**. Es
  la forma tecnica de la afirmacion "el grafo es fijo".
- **Pasadas por lote.** El regresor hace **dos** pasadas de codificacion sobre el
  MISMO modulo base, no una: la primera produce la compuerta, la segunda produce la
  prediccion. Un lote cuesta aproximadamente el doble que un codificador simple, y
  esa duplicacion es estructural, no un desperdicio que se pueda optimizar.

**Donde crece el costo.** Con la disposicion CSR el trabajo es proporcional al
numero de INSTANCIAS, no al de bolsas ni al maximo de instancias por bolsa. Era
exactamente el argumento contra el tensor rellenado: mas de la mitad de las bolsas
tienen un solo evento y el maximo esta en decenas, asi que rellenar habria
multiplicado el computo por mas de cuarenta sobre la mayor parte de los datos.

**La propagacion sobre el grafo es barata y no escala con `p`.** Cuesta una
operacion por arista y por instancia, no `p x p`: `index_add` escribe unicamente
en las columnas destino. Un grafo de decenas de aristas sobre decenas de features
es despreciable frente a los codificadores.

**El presupuesto del reentrenamiento es una compuerta, no una estimacion.** La
celda de pronostico del camino de entrenamiento cronometra UN pliegue real y
proyecta la validacion cruzada completa contra `COST_CEILING_SECONDS`. Si la
proyeccion no cabe, el entrenamiento completo NO se lanza. Ninguna corrida MIL se
cronometro nunca al escribir este cuaderno, y por eso el numero se mide en vez de
declararse.
'''

_CODE_COSTO_COMPUTO = '''\
if not ENTRENAR:
    _art_costo = torch.load(RUTA_MODELO, map_location="cpu", weights_only=False)
    _sd = _art_costo["state_dict"]
    _BUFFERS_FIJOS = ("adjacency", "edge_rows", "edge_cols", "edge_values")

    _por_bloque, _n_param, _n_buffer = {}, 0, 0
    for _clave, _tensor in _sd.items():
        if not hasattr(_tensor, "numel"):
            continue
        _n = int(_tensor.numel())
        if _clave in _BUFFERS_FIJOS:
            _por_bloque[f"[buffer fijo] {_clave}"] = _por_bloque.get(
                f"[buffer fijo] {_clave}", 0) + _n
            _n_buffer += _n
            continue
        _partes = _clave.split(".")
        _bloque = ".".join(_partes[:2]) if _partes[0] == "base" else _partes[0]
        _por_bloque[_bloque] = _por_bloque.get(_bloque, 0) + _n
        _n_param += _n

    tabla_costo = (
        pd.DataFrame([{"bloque": b, "valores": n} for b, n in _por_bloque.items()])
        .sort_values("valores", ascending=False)
        .reset_index(drop=True)
    )
    tabla_costo["% del total aprendible"] = [
        "" if b.startswith("[buffer") else f"{100.0 * n / _n_param:.1f}%"
        for b, n in zip(tabla_costo["bloque"], tabla_costo["valores"])
    ]

    _hp = _art_costo["hiperparametros"]
    _n_edges = int(len(_art_costo["edges"]))
    _p = len(_art_costo["features"])
    print(f"Parametros aprendibles: {_n_param:,}")
    print(f"Buffers fijos (el grafo, sin gradiente): {_n_buffer:,} valores")
    print(f"Hiperparametros de forma: {_hp}")
    print(f"Latente concatenado por instancia: n_modalidades x embed_dim = "
          f"2 x {_hp['embed_dim']} = {2 * _hp['embed_dim']}")
    print(f"Compuerta por bolsa: un valor por arista del grafo fijo -> {_n_edges}")
    print(f"Propagacion: {_n_edges} operaciones por instancia, NO {_p} x {_p}")
    print("Pasadas de codificacion por lote: 2 (fuente de la compuerta, y prediccion)")
    print()
    display(tabla_costo)
'''

_MD_GRAFO_COMPOSICION = '''\
## Composicion del grafo: que variables entran a la propagacion y cuales no

La figura de arriba muestra el grafo; esta seccion responde la pregunta que la
figura no contesta sola: **de las variables de entrada, cuales usa el grafo y
cuales no**. Hay que separar tres afirmaciones que suenan parecidas.

1. **Todas las features son entrada del MODELO.** Los codificadores por modalidad
   ven las `p` columnas. Ninguna variable esta "fuera del modelo".
2. **Solo algunas son entrada de la PROPAGACION.** La propagacion lee las columnas
   que son ORIGEN de alguna arista y escribe unicamente en las que son DESTINO.
3. **Una variable con grado de entrada 0 pasa intacta.** El `index_add` solo toca
   las columnas destino, asi que los indicadores `COD_CAUSA_*`, por ejemplo,
   atraviesan el grafo sin modificarse. Eso no las excluye del modelo: las excluye
   del grafo.

**De donde salen las aristas.** No se estiman. Son una lista escrita a mano en
`chec_impacto/data/graph.py`, con pesos que son juicio experto -- valores como
`("ALTURA", "NR_T", 0.75)` --, no correlaciones medidas. Los datos deciden UNA
sola cosa: **cuales nodos existen**. Si un codigo de causa no alcanza el umbral de
frecuencia, su columna no esta y las aristas que lo tocaban no se proyectan.

**Aristas directas y aristas virtuales.** El grafo experto describe la red
completa, incluidas variables que la seleccion no conserva. Cuando una arista pasa
por un nodo eliminado, la conectividad se PRESERVA: se crea una arista virtual
entre los extremos que si sobreviven, con el peso minimo del camino, y el camino
original queda registrado. Sin eso, quitar una variable intermedia cortaria en
silencio una relacion que el experto si declaro.

**El unico camino cruzado entre modalidades.** La fusion `film` y las aristas que
unen la rama estructural con la climatica son los dos unicos lugares donde las dos
modalidades se encuentran. Cuantas aristas cruzadas hay, y cuales, lo imprime la
celda siguiente -- es un numero pequeno, y por eso la fusion `film` existe.

**`COD_CAUSA` es el sumidero.** Recibe aristas y no emite ninguna. Es el nodo
donde converge el flujo del grafo, y es tambien la razon de que su nombre no se
pueda cambiar.
'''

_CODE_GRAFO_COMPOSICION = '''\
if not ENTRENAR:
    _art_comp = torch.load(RUTA_MODELO, map_location="cpu", weights_only=False)
    _A_comp = np.asarray(_art_comp["adjacency"])
    _feats_comp = list(_art_comp["features"])
    _clim_comp = {_feats_comp[i] for i in _art_comp["modalidades"]["climaticos"]}
    _aristas = list(_art_comp["edges"])

    _ent = (_A_comp != 0).sum(axis=0)
    _sal = (_A_comp != 0).sum(axis=1)

    def _papel_en_la_propagacion(i):
        emite, recibe = _sal[i] > 0, _ent[i] > 0
        if emite and recibe:
            return "emite y recibe"
        if emite:
            return "solo emite (la propagacion la lee, no la cambia)"
        if recibe:
            return "solo recibe (la propagacion la cambia)"
        return "ni emite ni recibe (fuera del grafo)"

    tabla_papeles = pd.DataFrame([
        {
            "variable": f,
            "modalidad": "climaticos" if f in _clim_comp else "estructurales",
            "grado_salida": int(_sal[i]),
            "grado_entrada": int(_ent[i]),
            "papel_en_la_propagacion": _papel_en_la_propagacion(i),
        }
        for i, f in enumerate(_feats_comp)
    ])

    tabla_aristas = pd.DataFrame([
        {
            "origen": a["source"],
            "destino": a["target"],
            "peso": float(a["weight"]),
            "tipo": "virtual (a traves de nodos descartados)" if a["is_virtual"] else "directa",
            "cruza_modalidad": (a["source"] in _clim_comp) != (a["target"] in _clim_comp),
            "camino": " -> ".join(a["path"]),
        }
        for a in _aristas
    ]).sort_values(["cruza_modalidad", "peso"], ascending=[False, False]).reset_index(drop=True)

    print(f"{len(_feats_comp)} variables de entrada al modelo | "
          f"{len(_aristas)} aristas en el grafo experto fijo")
    print()
    print("Papel de cada variable DENTRO de la propagacion:")
    print(tabla_papeles["papel_en_la_propagacion"].value_counts().to_string())
    # Las dos tablas de este cuaderno cuentan cosas distintas y deben cuadrar. La de
    # variables lista las de GRADO DE ENTRADA 0 -- las que la propagacion no cambia --
    # y esa cifra es la suma de dos filas de aqui. Sin esta linea las dos parecen
    # contradecirse, y quien lee no tiene como saber cual mirar.
    _sin_entrada = int((tabla_papeles["grado_entrada"] == 0).sum())
    _fuera = int((tabla_papeles["papel_en_la_propagacion"]
                  == "ni emite ni recibe (fuera del grafo)").sum())
    print(f"  cuadre con la tabla de variables: grado de entrada 0 = {_sin_entrada} "
          f"= 'solo emite' ({_sin_entrada - _fuera}) + 'fuera del grafo' ({_fuera})")
    print()
    print("Aristas por tipo:")
    print(tabla_aristas["tipo"].value_counts().to_string())
    print(f"Aristas que cruzan de una modalidad a la otra: "
          f"{int(tabla_aristas['cruza_modalidad'].sum())} de {len(tabla_aristas)}")
    print()
    print("Las aristas que cruzan modalidad (el unico camino cruzado del grafo):")
    display(tabla_aristas[tabla_aristas["cruza_modalidad"]].drop(columns="cruza_modalidad"))
    print("Todas las aristas:")
    display(tabla_aristas)
    print("Todas las variables y su papel en la propagacion:")
    display(tabla_papeles)
'''

_MD_ETIQUETAS = '''\
## De donde salen las etiquetas: el agrupamiento de vanos y el ranking

Este cuaderno **no decide las clases de criticidad**. Las hereda. Vale la pena
seguir la cadena completa porque es la fuente de confusion mas comun al leer los
resultados.

### El mismo procedimiento que el tablero 02, sobre tres unidades

El tablero de agrupamiento (`02_uiti_vano_kmeans`) hace exactamente lo mismo dos
veces, sobre unidades distintas:

- **A nivel de circuito.** Un punto es un circuito. El eje x es cuantos eventos
  registro en el periodo y el eje y su UITI acumulado.
- **A nivel de vano.** Un punto es un vano, con las mismas dos coordenadas.

Y `04_uiti_vano_trayectorias_vano` repite el procedimiento una tercera vez, sobre
la celda `(circuito, vano, ventana)`. Esa tercera es la que importa aqui.

En los tres casos: K-Means a **4 grupos** sobre un espacio FIJO -- eje x lineal,
eje y en `log10`, escalador `minmax` -- ajustado **una sola vez sobre la ventana
temporal completa**. Cambiar el rango de fechas reevalua a que grupo cae cada
punto, pero **no mueve las fronteras**. Sin eso, `Alto` significaria una cosa
distinta en cada rango y dos tableros no se podrian comparar.

### La regla que convierte un id arbitrario en una etiqueta

K-Means devuelve ids sin orden. El nombre del grupo se asigna por el **ranking de
la MEDIANA del UITI acumulado**, de menor a mayor: `Bajo`, `Medio`, `Medio-Alto`,
`Alto`. Ese es todo el contenido del ranking, y es lo que hace que el indice del
centroide SEA el id final de la clase, sin remapeos posteriores.

Un aviso que el tablero 02 documenta y que aplica igual aqui: con centroides
fijos, el orden por mediana esta garantizado sobre la ventana completa, no sobre
cualquier subrango. En un rango corto un grupo puede quedar con pocos puntos y
cruzarse con su vecino.

### Que hereda este cuaderno, exactamente

Cuidado con un detalle que decide si la herencia es legitima o no: **02 y 04
aplican el mismo procedimiento sobre agregaciones distintas, y sus centroides NO
son intercambiables**. El tablero 02 acumula por vano sobre todo el rango elegido;
01.4 ajusta sobre la celda `(circuito, vano, ventana)`.

Lo que este cuaderno hereda es la geometria de **01.4**, y su unidad es
exactamente la celda `(circuito, vano, ventana)` -- que es, letra por letra, la
definicion de una bolsa. Por eso la herencia funciona: la regla de clase se aplica
sobre la misma unidad sobre la que se ajusto. Tomar en su lugar los centroides del
nivel de vano de 02 asignaria clases con fronteras ajustadas a otra poblacion, y
nada en el resultado lo delataria.

Del artefacto viajan los `logs`, el `offset`, la `scale` y los cuatro centroides.
Con eso se aplica la regla de **centroide mas cercano** sobre el par `(n_obs
OBSERVADO, u ESTIMADO)`.

De las dos coordenadas que deciden la clase, **el modelo solo aporta una**. El
numero de eventos es observado siempre, en la verdad y en la prediccion; lo unico
que el modelo predice es el UITI acumulado. Es la razon por la que el contexto del
informe declara explicitamente que el conteo de eventos NO es una salida del
modelo: un lector razonable supondria lo contrario.

**Los grupos de circuito y los de vano NO son comparables aunque compartan
nombre.** Son particiones sobre unidades distintas. Un vano `Alto` casi siempre
vive en un circuito `Alto`, pero un circuito `Alto` contiene vanos de los cuatro
grupos. El mismo aviso vale entre el nivel de vano y el de celda vano-ventana: un
vano puede ser `Alto` en el acumulado del periodo y `Bajo` en una ventana
tranquila.

La celda siguiente dibuja esa particion con la geometria REAL del artefacto, y
verifica el ranking en vez de repetirlo.
'''

_CODE_ETIQUETAS = '''\
if not ENTRENAR:
    import plotly.graph_objects as _go_km

    # La geometria se lee del ARTEFACTO, no de data/derived/geometrias_014.json: ya
    # viaja dentro del .pt y asi esta celda no depende de un derivado que no se
    # versiona ni escribe nada en disco.
    _art_km = torch.load(RUTA_MODELO, map_location="cpu", weights_only=False)
    _geo_km = _art_km["geometria"]
    _logs = [bool(b) for b in _geo_km["logs"]]
    _off = np.asarray(_geo_km["offset"], dtype=float)
    _esc = np.asarray(_geo_km["scale"], dtype=float)
    _cent = np.asarray(_geo_km["centroides"], dtype=float)

    def _a_unidades_originales(z, eje):
        crudo = z * _esc[eje] + _off[eje]
        return 10.0 ** crudo if _logs[eje] else crudo

    tabla_centroides = pd.DataFrame({
        "grupo": list(GRUPOS),
        "indice": range(len(GRUPOS)),
        "n_eventos_del_centroide": [_a_unidades_originales(c[0], 0) for c in _cent],
        "uiti_del_centroide": [_a_unidades_originales(c[1], 1) for c in _cent],
    })

    _u_cent = tabla_centroides["uiti_del_centroide"].to_numpy()
    _ranking_ok = bool(np.all(np.diff(_u_cent) > 0))
    print(f"Espacio KMeans heredado de 01.4: log en x = {_logs[0]}, log en y = {_logs[1]}")
    print(f"Ranking por UITI del centroide estrictamente creciente: {_ranking_ok}")
    print("  (es la regla que convierte el id arbitrario de KMeans en Bajo..Alto)")
    print()
    display(tabla_centroides.round(4))

    # Particion de Voronoi sobre el plano, en las MISMAS unidades en que se leen los
    # datos. Se evalua la regla de centroide mas cercano sobre una grilla: es la misma
    # `asignar_clase` que usa el modelo, no una aproximacion para dibujar.
    _n_grilla = 260
    _n_eje = np.linspace(_a_unidades_originales(_cent[:, 0].min(), 0) * 0.2,
                         _a_unidades_originales(_cent[:, 0].max(), 0) * 1.6, _n_grilla)
    _u_eje = np.logspace(np.log10(_u_cent.min() * 0.05), np.log10(_u_cent.max() * 8.0), _n_grilla)
    _NN, _UU = np.meshgrid(_n_eje, _u_eje)
    _clase_grilla, _ = asignar_clase(_NN.ravel(), _UU.ravel(), predictor_guardado.geometria)
    _clase_grilla = _clase_grilla.reshape(_NN.shape)

    COLOR_GRUPO = ["#7fa8c9", "#e8c468", "#e08a4b", "#c1443b"]
    fig_km = _go_km.Figure()
    fig_km.add_trace(_go_km.Heatmap(
        x=_n_eje, y=_u_eje, z=_clase_grilla, showscale=False, opacity=0.32,
        colorscale=[[i / 3.0, c] for i, c in enumerate(COLOR_GRUPO)],
        hoverinfo="skip", zmin=0, zmax=3,
    ))
    # Si las predicciones fuera de pliegue estan a mano, se dibuja una muestra de las
    # bolsas reales encima. Es OPCIONAL a proposito: el .npz no se versiona y la
    # particion se entiende igual sin el.
    if oof is not None and "n_obs" in oof and "y_uiti" in oof:
        _rng_km = np.random.default_rng(RANDOM_STATE)
        _n_obs_oof = np.asarray(oof["n_obs"], dtype=float)
        _idx = _rng_km.choice(len(_n_obs_oof), size=min(4000, len(_n_obs_oof)), replace=False)
        fig_km.add_trace(_go_km.Scatter(
            x=_n_obs_oof[_idx], y=np.asarray(oof["y_uiti"], dtype=float)[_idx],
            mode="markers", name="bolsas observadas (muestra)",
            marker=dict(size=3, color="#3f3f3f", opacity=0.35),
            hovertemplate="n_obs %{x}<br>uiti %{y:.2f}<extra></extra>",
        ))
    for _k, _grupo in enumerate(GRUPOS):
        fig_km.add_trace(_go_km.Scatter(
            x=[tabla_centroides["n_eventos_del_centroide"][_k]],
            y=[tabla_centroides["uiti_del_centroide"][_k]],
            mode="markers+text", name=_grupo, text=[_grupo], textposition="top center",
            marker=dict(size=15, color=COLOR_GRUPO[_k], symbol="x-thin",
                        line=dict(width=3, color=COLOR_GRUPO[_k])),
            hovertemplate=f"{_grupo}<br>n_obs %{{x:.2f}}<br>uiti %{{y:.2f}}<extra></extra>",
        ))
    fig_km.update_layout(
        title=("Particion heredada de 01.4 -- centroide mas cercano sobre "
               "(eventos observados, UITI estimado)"),
        template="plotly_white", height=560, width=980,
        xaxis=dict(title="numero de eventos de la bolsa (OBSERVADO)"),
        yaxis=dict(title="UITI acumulado (el modelo estima ESTE eje)", type="log"),
        legend=dict(orientation="h", y=1.02, x=0),
        margin=dict(l=70, r=20, t=90, b=60),
    )
    fig_km.show()

    print("Como leer la figura: el color de fondo es la clase que asigna la regla de")
    print("centroide mas cercano en cada punto del plano. El modelo mueve un punto solo")
    print("en VERTICAL -- el eje de eventos es observado y no lo predice nadie.")
'''

_MD_ENTRENAMIENTO_GUIA = '''\
## Como se genera el entrenamiento, y que produce

Antes de las celdas conviene el mapa, porque el orden no es arbitrario: cada
etapa existe para que la siguiente sea legitima.

**1. De la base a las instancias.** Se lee el CSV, se aplica la seleccion experta
y la expansion climatica, se codifica `COD_CAUSA` y se arma la matriz de
instancias. `p` se deriva en tiempo de ejecucion; escribirlo a mano seria la forma
mas facil de que una feature nueva pase inadvertida.

**2. El grafo experto.** Se construye sobre las features que quedaron, con la
preservacion de conectividad a traves de los nodos descartados. Se verifica que
`COD_CAUSA` sea un sumidero puro y que el numero de aristas sea el que el diseno
deriva.

**3. La geometria de 01.4.** Se reutiliza, nunca se reajusta, y se verifica por
sha1. Si los centroides se movieron, la corrida se detiene: las clases se correrian
en silencio y ningun resultado lo diria.

**4. Las bolsas.** Se reconstruyen las 11 ventanas con el mismo corte de 01.4 y se
agrupan los eventos por celda `(circuito, vano, ventana)`. Los tamanos quedan
fijados con asserts contra los valores poblacionales medidos.

**5. La compuerta de costo.** Se cronometra UN pliegue real y se proyecta la
validacion cruzada completa. Si la proyeccion excede el techo declarado, el
entrenamiento completo NO se lanza. Es una compuerta, no un aviso.

**6. La validacion cruzada agrupada.** `StratifiedGroupKFold` con
`groups = CIRCUITO|FID_VANO`: un mismo vano nunca queda partido entre entrenamiento
y prueba. Sin eso, la persistencia del vano se colaria como si fuera capacidad
predictiva -- y la linea base de persistencia existe justamente para medir cuanta
de esa "capacidad" es solo memoria.

**7. Las barras y las guardas.** El modelo se compara contra las tres lineas base y
debe superar a la MEJOR, no solo a la mas debil. Ademas corren la guarda de proxy
univariante (A3), la deteccion de colapso de compuertas (A4) y el diagnostico de
particion temporal (A6), que se reporta al lado y nunca reselecciona la metrica
principal.

**8. El modelo final y sus artefactos.** Un ajuste sobre TODAS las bolsas produce
el modelo que se guarda -- distinto de los cinco modelos por pliegue, que solo
existen para medir. De ahi salen las relevancias por Kernel SHAP agregadas en un
ranking Borda, y la verificacion del contrato que el simulador espera.

**Lo que este cuaderno NO hace.** No busca hiperparametros: los valores son fijos
y razonables, y no hay un objetivo de Optuna definido para este modelo. Tampoco
construye ni corre el simulador; solo verifica el contrato que el simulador exige.
'''

_MD_SIMULADOR = '''\
## Que hace el simulador con lo que sale de aqui

El simulador (`06_uiti_vano_explicabilidad_simulador`, servido como aplicacion)
carga el artefacto de este cuaderno y responde tres preguntas distintas. Ninguna
de las tres se calcula aqui, pero las tres dependen de decisiones que si se toman
aqui.

### 1. Prediccion de grupo

Es la misma cadena que el visor: dos pasadas del modelo sobre las bolsas de la
seleccion -- una con los valores observados y otra con los valores intervenidos --
y sobre cada una la regla de centroide mas cercano con `(n_obs OBSERVADO, u
estimado)`. Cuesta exactamente **dos** pasadas para toda la seleccion, nunca una
por vano: los valores por vano se escriben en UNA matriz y se puntuan juntos.

El indicador que compara escenarios es la **clase esperada**, es decir la
distribucion suave de clases por su indice, promediada. La clase REPORTADA sigue
siendo el argmin duro; la version suave existe solo para que la diferencia entre
dos escenarios sea un numero continuo en vez de un escalon. Su `argmax` coincide
siempre con la clase dura, porque la softmax es monotona en la distancia negativa.

### 2. El grafo de inferencia

No es el grafo experto tal cual, y tampoco es un grafo aprendido. Es **el grafo
experto tal como ESTA seleccion de vanos lo usa**: para cada arista, el peso fijo
multiplicado por la compuerta media que el modelo decodifico para esas bolsas. Las
compuertas salen de la misma pasada que ya se hizo para predecir, asi que no
cuesta nada extra.

Dos decisiones importan al leerlo:

- **Se anula si las compuertas colapsan.** Una compuerta que no varia entre vanos
  no lleva estructura propia de la seleccion, y dibujarla presentaria el grafo
  experto fijo como si la seleccion lo hubiera producido. Con muy pocos vanos se
  anula por construccion.
- **El panel muestra la DIFERENCIA, no el grafo.** Como el grafo es casi todo peso
  experto fijo, el antes y el despues se ven iguales lado a lado y el efecto de la
  intervencion -- que es el punto del panel -- queda invisible. Se muestra
  `|base - simulado|` en valor absoluto: la pregunta es cuanto se movio cada
  relacion, no en que direccion. Una matriz toda en cero es un RESULTADO, no un
  panel vacio: dice que la intervencion no movio ninguna relacion.

### 3. Analisis de sensibilidad de variables relevantes

Un barrido de minimo y maximo por control. Para cada control numerico se fija toda
su familia en su valor minimo, luego en su maximo, y se mide cuanto se movio la
clase esperada respecto de la base. La relevancia de un control es la magnitud
mayor de las dos, y se reporta ademas hacia donde empuja cada extremo.

- **Cuesta `1 + 2 x controles_numericos` pasadas**, no una tanda por vano: cada
  pasada ya devuelve un valor por bolsa, asi que basta con no promediarlo para
  obtener el ranking de CADA vano en el mismo barrido.
- **Una familia climatica es UN control, no doce.** Sus doce rezagos se mueven
  juntos. Es la razon de ser del catalogo de controles.
- **Los controles sin limites numericos se saltan.** Inventarles un rango
  puntuaria un escenario que nadie pidio.

### Lo que decide este cuaderno y el simulador solo obedece

Que features existen y en que orden, que aristas tiene el grafo y cuanto pesan,
cual es la geometria de clases, y el contrato de salida. Un cambio en cualquiera de
esos cuatro obliga a reentrenar: el cargador RECHAZA un desajuste de nombres de
features, y con razon -- puntuar columnas equivocadas no lanza error por si solo,
solo devuelve un mapa creible y falso.
'''

_MD_ARTEFACTOS = '''\
## Que archivos salen de aqui, y quien los consume

Este cuaderno escribe solo al reentrenar. En modo visualizacion no toca el disco.

| archivo | cuando se escribe | versionado | quien lo consume |
|---|---|---|---|
| `data/models/mil_vano_ventana_v1.pt` | al reentrenar con `mode="full"` | **si** | el visor de este cuaderno, el simulador, el informe y las aplicaciones locales y de Databricks |
| `data/derived/oof_mil_{mode}_{fusion}_clase{lambda}.npz` | tras la validacion cruzada | no | analisis posteriores; **opcional** para el visor, que lee el desglose desde el `.pt` |
| `data/derived/bolsas_mil_{mode}.joblib` | al construir las bolsas | no | el simulador, para no rehacer la construccion en cada arranque |
| `data/derived/geometrias_014.json` | si falta, se extrae de 01.4 | no | la asignacion de clase en todos los caminos |

Hay ademas dos derivados que este cuaderno NO escribe pero que dependen del mismo
artefacto: el catalogo de controles del simulador y el cache de relevancias por
circuito y ventana, ambos bajo `data/derived/`. Se invalidan por las huellas de sus
archivos fuente, de modo que un artefacto nuevo no queda descrito por un cache
viejo.

**Por que el desglose de desempeno viaja DENTRO del `.pt`.** `data/models/` esta
versionado y `data/derived/` no. Si el visor dependiera del `.npz`, fallaria en
cualquier checkout limpio -- que es exactamente el escenario en el que alguien abre
el cuaderno por primera vez.

**La advertencia que importa.** Reentrenar SOBREESCRIBE el artefacto que el
simulador y el informe ya estan usando. La copia que sirve cada aplicacion se
reconstruye por huella de sus insumos, asi que un artefacto nuevo dispara la
reconstruccion de los paquetes -- pero los reportes ya emitidos siguen citando
numeros del modelo anterior.
'''

_CODE_ARTEFACTOS = '''\
# El mapa de archivos, resuelto contra el checkout actual. Las rutas de salida se
# construyen con los MISMOS nombres que usan las celdas de guardado, para que este
# resumen no pueda describir un archivo que el cuaderno nunca escribiria.
_SALIDAS = [
    (DATA_DIR / "models" / "mil_vano_ventana_v1.pt",
     'al reentrenar con mode="full"', "si",
     "visor, simulador, informe y aplicaciones"),
    (DERIVED_DIR / f"oof_mil_{mode}_{FUSION}_clase{LAMBDA_CLASE}.npz",
     "tras la validacion cruzada", "no",
     "analisis posteriores (opcional para el visor)"),
    (DERIVED_DIR / f"bolsas_mil_{mode}.joblib",
     "al construir las bolsas", "no",
     "el simulador, para no rehacer la construccion"),
    (DERIVED_DIR / "geometrias_014.json",
     "si falta, se extrae de 01.4", "no",
     "la asignacion de clase en todos los caminos"),
]

tabla_salidas = pd.DataFrame([
    {
        "archivo": str(r.relative_to(PROJECT_ROOT)) if PROJECT_ROOT in r.parents else str(r),
        "existe_ahora": r.exists(),
        "MB": round(r.stat().st_size / 1e6, 2) if r.exists() else None,
        "cuando_se_escribe": cuando,
        "versionado": versionado,
        "quien_lo_consume": consumidor,
    }
    for r, cuando, versionado, consumidor in _SALIDAS
])

print("En modo visualizacion este cuaderno NO escribe ninguno de estos archivos.")
print(f"Modo actual: {'entrenamiento' if ENTRENAR else 'visualizacion'}")
print()
display(tabla_salidas)
'''


def _solo_entrenamiento(codigo: str) -> str:
    """Indenta el cuerpo de una celda bajo `if ENTRENAR:`.

    El cuaderno corre por defecto sin entrenar, asi que toda la tuberia cara
    -- cargar el CSV, construir bolsas, la validacion cruzada -- queda detras
    de una sola bandera en vez de repartida en guardas por celda que se
    desincronizan.
    """
    lineas = codigo.rstrip("\n").split("\n")
    cuerpo = "\n".join(f"    {linea}" if linea.strip() else "" for linea in lineas)
    return "if ENTRENAR:\n" + cuerpo + "\n"


def _cell(kind: str, source: str, *, tags: list[str] | None = None) -> nbformat.NotebookNode:
    if kind == "markdown":
        return new_markdown_cell(source)
    cell = new_code_cell(source)
    if tags:
        cell["metadata"]["tags"] = list(tags)
    return cell


def build_notebook() -> nbformat.NotebookNode:
    """Assemble the (unexecuted) notebook-10 skeleton -- pure, no training."""
    cells = [
        _cell("markdown", _MD_TITLE),
        _cell("code", _CODE_PARAMETERS, tags=["parameters"]),
        _cell("markdown", _MD_BOOTSTRAP),
        _cell("code", _CODE_BOOTSTRAP),
        _cell("code", _CODE_IMPORTS),
        _cell("markdown", _MD_CONFIG),
        _cell("code", _CODE_CONFIG),
        # ---- de donde sale todo: insumos, base cruda y preprocesos ----
        _cell("markdown", _MD_AUTOCONTENIDO),
        _cell("code", _CODE_INSUMOS),
        _cell("markdown", _MD_BASE_CRUDA),
        _cell("code", _CODE_VISTA_PREVIA),
        _cell("markdown", _MD_PREPROCESOS),
        _cell("code", _CODE_PREPROCESOS),
        # ---- documentacion: siempre visible, no depende de EJECUCION ----
        _cell("markdown", _MD_ARQUITECTURA),
        _cell("markdown", _MD_BOLSAS_DOC),
        _cell("markdown", _MD_PERDIDA),
        # ---- visor: lee el modelo guardado ----
        _cell("markdown", _MD_VISOR),
        _cell("code", _CODE_VISOR),
        _cell("markdown", _MD_COSTO_COMPUTO),
        _cell("code", _CODE_COSTO_COMPUTO),
        _cell("markdown", _MD_VARIABLES),
        _cell("code", _CODE_VARIABLES),
        _cell("markdown", _MD_GRAFO_INTERACTIVO),
        _cell("code", _CODE_GRAFO_INTERACTIVO),
        _cell("markdown", _MD_GRAFO_COMPOSICION),
        _cell("code", _CODE_GRAFO_COMPOSICION),
        _cell("markdown", _MD_ETIQUETAS),
        _cell("code", _CODE_ETIQUETAS),
        _cell("markdown", _MD_DESEMPENO),
        _cell("code", _CODE_DESEMPENO),
        # ---- entrenamiento: solo con EJECUCION="entrenamiento" ----
        _cell("markdown", _MD_ENTRENAMIENTO),
        _cell("markdown", _MD_ENTRENAMIENTO_GUIA),
        _cell("markdown", _MD_DIAGRAM),
        _cell("markdown", _MD_DATA_LOAD),
        _cell("code", _solo_entrenamiento(_CODE_DATA_LOAD)),
        _cell("markdown", _MD_GRAPH),
        _cell("code", _solo_entrenamiento(_CODE_GRAPH)),
        _cell("markdown", _MD_GEOMETRIA),
        _cell("code", _solo_entrenamiento(_CODE_GEOMETRIA)),
        _cell("markdown", _MD_BAGS),
        _cell("code", _solo_entrenamiento(_CODE_BAGS)),
        _cell("markdown", _MD_CLASE_OBSERVADA),
        _cell("code", _solo_entrenamiento(_CODE_CLASE_OBSERVADA)),
        _cell("markdown", _MD_HELPERS),
        _cell("code", _solo_entrenamiento(_CODE_HELPERS)),
        _cell("markdown", _MD_COST_FORECAST),
        _cell("code", _solo_entrenamiento(_CODE_COST_FORECAST)),
        _cell("markdown", _MD_CV_LOOP),
        _cell("code", _solo_entrenamiento(_CODE_CV_LOOP)),
        _cell("markdown", _MD_A1_BASELINES),
        _cell("code", _solo_entrenamiento(_CODE_A1_BASELINES)),
        _cell("markdown", _MD_POR_CLASE),
        _cell("code", _solo_entrenamiento(_CODE_POR_CLASE)),
        _cell("markdown", _MD_DESGLOSE),
        _cell("code", _solo_entrenamiento(_CODE_DESGLOSE)),
        _cell("markdown", _MD_A3),
        _cell("code", _solo_entrenamiento(_CODE_A3)),
        _cell("markdown", _MD_A4),
        _cell("code", _solo_entrenamiento(_CODE_A4)),
        _cell("markdown", _MD_A6),
        _cell("code", _solo_entrenamiento(_CODE_A6)),
        _cell("markdown", _MD_SHAP),
        _cell("code", _solo_entrenamiento(_CODE_SHAP)),
        _cell("markdown", _MD_GUARDADO),
        _cell("code", _CODE_GUARDADO),
        _cell("markdown", _MD_SIMULATOR),
        _cell("code", _solo_entrenamiento(_CODE_SIMULATOR)),
        _cell("markdown", _MD_LIMITACION),
        # ---- que sale de aqui y quien lo usa ----
        _cell("markdown", _MD_SIMULADOR),
        _cell("markdown", _MD_ARTEFACTOS),
        _cell("code", _CODE_ARTEFACTOS),
        _cell("markdown", _MD_SUMMARY),
        _cell("code", _CODE_SUMMARY),
    ]
    notebook = new_notebook(cells=cells)
    notebook["metadata"]["kernelspec"] = _KERNELSPEC
    notebook["metadata"]["language_info"] = _LANGUAGE_INFO
    return notebook


def assign_deterministic_cell_ids(notebook: nbformat.NotebookNode) -> None:
    """Assign stable, index-derived ids -- required by nbformat >= 4.5, and
    deterministic so re-generation never produces a spurious diff on ids alone."""
    for index, cell in enumerate(notebook.cells):
        cell["id"] = f"cell-{index:03d}"


def _ensure_no_forbidden_literals(notebook: nbformat.NotebookNode) -> None:
    pattern = re.compile(r"(?<![\w.])(" + "|".join(FORBIDDEN_LITERALS) + r")(?![\w])")
    for cell in notebook.cells:
        if cell.cell_type != "code":
            continue
        match = pattern.search(cell.source)
        if match:
            raise ValueError(
                f"Forbidden literal {match.group(0)!r} found in a generated code cell -- "
                "'p' (instance feature count) must always be derived at runtime."
            )


def _ensure_code_cells_parse(notebook: nbformat.NotebookNode) -> None:
    for cell in notebook.cells:
        if cell.cell_type == "code":
            ast.parse(cell.source)


def generate(out_path: Path) -> nbformat.NotebookNode:
    notebook = build_notebook()
    assign_deterministic_cell_ids(notebook)
    _ensure_no_forbidden_literals(notebook)
    _ensure_code_cells_parse(notebook)
    nbformat.validate(notebook)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(notebook, out_path)
    return notebook


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=NOTEBOOK_10_PATH,
        help="Output path for the generated notebook (defaults to notebooks/05_*.ipynb).",
    )
    args = parser.parse_args()

    notebook = generate(args.out)
    print(f"Notebook 10 written to {args.out} ({len(notebook.cells)} cells).")


if __name__ == "__main__":
    main()
