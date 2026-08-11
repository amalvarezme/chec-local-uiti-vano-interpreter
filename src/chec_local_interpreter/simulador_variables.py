"""Which of the model's variables are worth simulating, and why.

Notebook 06's simulator answers one question: *what happens to a vano's
criticality if this variable changes*. The knob catalogue
(`vano_controls.build_knobs`) offers every non-constant model feature as a
control, because it is built from the feature list and knows nothing about
what any of them mean. That is the right separation, but it leaves the panel
presenting a lever CHEC pulls every week -- vegetation risk -- next to the
vano's own coordinates, as if moving a vano were a maintenance option.

This module supplies the missing half: one verdict per variable, with the
reason attached, so the notebook can print a table instead of asking every
reader to re-derive the distinction. The verdicts come from the project's own
column dictionary (`data/Variables_seleccion.xlsx`), quoted in each reason,
not from reading the variable names.

Four levels, and the reason column carries the nuance:

``Si -- intervencion``
    CHEC can change it in the field. Simulating it is costing an actual work
    order: pruning, grounding, a conductor swap, a bigger transformer.

``Si -- escenario``
    Nobody controls it, but that is precisely the what-if the simulator
    exists for -- the weather, the lightning density of the site, the growth
    of the load. The answer is not "do this", it is "expect this".

``Limitado``
    Only meaningful under one specific reading, stated in the reason. Moving
    it outside that reading produces a number with no interpretation.

``No``
    Simulating it is either circular -- the variable is recorded after the
    failure the model is meant to anticipate -- or it describes what the vano
    IS rather than anything that could be done to it.

A knob with no entry here is reported as ``Sin evaluar`` rather than assumed
either way: defaulting to yes puts an unvetted lever in the panel, defaulting
to no hides a real one.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from .vano_controls import Knob

VEREDICTOS: tuple[str, ...] = (
    "Si -- intervencion",
    "Si -- escenario",
    "Limitado",
    "No",
)

# El orden en que se lee la tabla: primero lo que se puede hacer, al final lo que
# no hay que tocar, donde se lee como una lista de advertencias.
_ORDEN = {veredicto: i for i, veredicto in enumerate(VEREDICTOS)}
SIN_EVALUAR = "Sin evaluar"

# Veredicto y motivo por variable. La descripcion entre comillas de cada motivo es
# la del diccionario del proyecto, `data/Variables_seleccion.xlsx`.
JUICIO_SIMULACION: Mapping[str, tuple[str, str]] = {
    # --- palancas: obra o mantenimiento que CHEC ejecuta -----------------------------
    "NR_T": (
        "Si -- intervencion",
        "Es el nivel de riesgo por vegetacion asociada al vano, y bajarlo ES el plan "
        "de poda. De todas las variables del modelo, es la que se mueve con la "
        "cuadrilla de la semana entrante.",
    ),
    "CANTIDAD_TIERRA": (
        "Si -- intervencion",
        "Dice si el apoyo tiene puesta a tierra. Instalarla es una obra concreta y "
        "acotada, asi que la simulacion se lee directamente como su beneficio "
        "esperado.",
    ),
    "NG_RED": (
        "Si -- intervencion",
        "Indica si el vano posee guarda o neutro. Tenderlo es una obra de red "
        "habitual, y el simulador estima que le pasa a la criticidad si se hace.",
    ),
    "CONDUCTOR": (
        "Si -- intervencion",
        "Es el conductor de fases del vano. Cambiarlo es un recambio programable, y "
        "comparar dos conductores es una decision real de diseno.",
    ),
    "CALIBRE_NEUTRO": (
        "Si -- intervencion",
        "Es el calibre del neutro. Igual que el conductor, se cambia con obra y el "
        "escenario se lee como la ganancia de subir de calibre.",
    ),
    "ALTURA": (
        "Si -- intervencion",
        "Es la altura del apoyo final del vano. Cambiar el apoyo por uno mas alto es "
        "obra de red, y aleja el conductor de la vegetacion.",
    ),
    "LONG_CRUCETA": (
        "Si -- intervencion",
        "Es la longitud de la cruceta del apoyo final. Se cambia con la misma obra "
        "que el apoyo y modifica la separacion entre fases.",
    ),
    "CNT_FASES": (
        "Si -- intervencion",
        "Es la cantidad de fases del vano. Cambiarla es una repotenciacion mayor, "
        "pero es una decision de expansion que la empresa efectivamente toma.",
    ),
    "CAPACIDAD_NOMINAL": (
        "Si -- intervencion",
        "Es la capacidad del trafo del apoyo final. Cambiar el transformador es la "
        "respuesta tipica a la sobrecarga y esta en el alcance del mantenimiento.",
    ),
    "TIPO": (
        "Si -- intervencion",
        "Es el tipo de equipo que protege al vano. Cambiar el esquema de proteccion "
        "es una decision de operacion, no una propiedad fija del vano.",
    ),
    "VAL_CRIT_APOYO": (
        "Si -- intervencion",
        "Es la calificacion de criticidad por clase de apoyo, y la clase de apoyo se "
        "cambia reponiendo la estructura. Cuidado con leerlo al reves: es una "
        "clasificacion del activo, no la criticidad que el modelo predice.",
    ),
    # --- escenarios: nadie los controla, y ese es justamente el what-if --------------
    "clima:prep": (
        "Si -- escenario",
        "Precipitacion acumulada en la hora previa, en los 12 rezagos a la vez. No se "
        "interviene, pero preguntar que pasa bajo un aguacero es exactamente para lo "
        "que existe el simulador.",
    ),
    "clima:temp": (
        "Si -- escenario",
        "Temperatura del aire a 2 m, en los 12 rezagos. Escenario ambiental: no es "
        "una obra, es la condicion bajo la que se quiere anticipar la criticidad.",
    ),
    "clima:wind_gust_spd": (
        "Si -- escenario",
        "Velocidad maxima de rafaga a 10 m, en los 12 rezagos. Es el escenario de "
        "vendaval, el mas util de la familia climatica para planear contingencias.",
    ),
    "clima:wind_spd": (
        "Si -- escenario",
        "Velocidad instantanea del viento a 10 m, en los 12 rezagos. Mismo caso que "
        "la rafaga, en regimen sostenido en vez de pico.",
    ),
    "DDT": (
        "Si -- escenario",
        "Es la densidad de descargas a tierra promedio al ano del sitio. No se "
        "interviene, pero describe la exposicion atmosferica y sirve para comparar "
        "un vano con otro bajo la misma pregunta.",
    ),
    "PROMEDIO_KWH_TRF": (
        "Si -- escenario",
        "Es el consumo mensual promedio del trafo. Subirlo es el escenario de "
        "crecimiento de demanda, que se proyecta y no se decide.",
    ),
    "PROMEDIO_KWH_VANO": (
        "Si -- escenario",
        "Es la energia mensual promedio que circula por el vano. Mismo escenario de "
        "crecimiento de carga, medido sobre el vano en vez del trafo.",
    ),
    # --- limitados: una sola lectura los hace interpretables -------------------------
    "FECHA_OPERACION_VANO": (
        "Limitado",
        "Es la fecha de entrada en operacion del vano, o sea su edad. Solo tiene "
        "sentido en una direccion y con una lectura: adelantarla equivale a reponer "
        "el activo. Atrasarla no corresponde a nada que se pueda hacer.",
    ),
    "FECHA_OPERACION_TRF": (
        "Limitado",
        "Es la fecha de entrada en operacion del trafo. Misma lectura unica que la "
        "del vano: solo se interpreta como el recambio del transformador.",
    ),
    "LONGITUD": (
        "Limitado",
        "Es la longitud del vano. Solo cambia reconfigurando la red -- moviendo "
        "apoyos --, asi que fuera de un proyecto de repotenciacion es geometria fija "
        "y el escenario no corresponde a ninguna decision del dia a dia.",
    ),
    "CNT_VN": (
        "Limitado",
        "Es la cantidad de vanos que hay hasta el equipo que lo protege. Cambia solo "
        "reubicando la proteccion, y esa obra mueve a la vez a todos los vanos del "
        "tramo: simularlo para un vano aislado describe algo que no puede ocurrir "
        "solo.",
    ),
    "TIPO_TAX": (
        "Limitado",
        "Es el tipo de taxonomia del vano. Describe lo que el vano ES y no una "
        "palanca; solo se lee como comparar dos disenos distintos, nunca como una "
        "intervencion sobre este vano.",
    ),
    # --- refutadas -------------------------------------------------------------------
    "CNT_TRF": (
        "No",
        "El diccionario del proyecto lo define como la cantidad de trafos afectados "
        "EN LA FALLA: se mide despues del evento que el modelo intenta anticipar. "
        "Simularlo es circular, e invita a concluir que menos trafos afectados causan "
        "menos criticidad, que es la flecha del analisis al reves.",
    ),
    "X2": (
        "No",
        "Es la coordenada X final del vano: su identidad geografica. Moverla no "
        "corresponde a ninguna intervencion y ademas rompe en silencio el acople con "
        "el clima, porque las series climaticas se consultaron EN esas coordenadas y "
        "el vano movido se quedaria con el clima de otro lugar.",
    ),
    "Y2": (
        "No",
        "Es la coordenada Y final del vano: su identidad geografica. Mismo problema "
        "que X2 -- no es una obra, y desacopla el vano del clima que se consulto en "
        "ese punto.",
    ),
}


UNIDADES: Mapping[str, str] = {
    # Las CUATRO con unidad escrita en `data/Variables_seleccion.xlsx`. Se copian de
    # ahi tal cual; no se deducen del nombre.
    "clima:prep": "mm",
    "clima:temp": "\u00b0C",
    "clima:wind_gust_spd": "km/h",
    "clima:wind_spd": "km/h",
    # Derivadas sin ambiguedad de la descripcion del diccionario mas el rango medido.
    "LONGITUD": "m",              # "Longitud del vano": 0,4 a 2.807
    "ALTURA": "m",                # "Altura del apoyo final": 4 a 25 una vez fuera el 99
    "LONG_CRUCETA": "m",          # "Longitud de la cruceta": misma familia de longitudes
    "CAPACIDAD_NOMINAL": "kVA",   # "Capacidad del trafo": 0 a 400
    "PROMEDIO_KWH_TRF": "kWh/mes",    # "Promedio mensual energia consumo trafo"
    "PROMEDIO_KWH_VANO": "kWh/mes",   # "Promedio mensual energia que circula por el vano"
    "FECHA_OPERACION_VANO": "a\u00f1o",
    "FECHA_OPERACION_TRF": "a\u00f1o",
    "X2": "grados",               # coordenada geografica, como X1/Y1
    "Y2": "grados",
    # Conteos: la unidad es lo que se cuenta, que es mas util que "unidades".
    "CNT_VN": "vanos",
    "CNT_TRF": "trafos",
    "CNT_FASES": "fases",
}
"""Unidad de medida de cada variable, cuando aplique.

Un rango sin unidad no se puede juzgar: 25 puede ser una altura razonable o un
disparate segun si son metros o pies, y quien mueve el deslizador tiene que poder
decidirlo sin ir a buscar el diccionario.

Quedan DELIBERADAMENTE fuera:

- las categoricas y las binarias (`TIPO`, `CONDUCTOR`, `CALIBRE_NEUTRO`, `TIPO_TAX`,
  `NG_RED`, `CANTIDAD_TIERRA`): una unidad sobre una categoria es ruido;
- los indices y calificaciones (`NR_T`, `VAL_CRIT_APOYO`): son puntajes, no magnitudes;
- `DDT`. Su descripcion -- "densidad de descargas a tierra promedio ano" -- implica una
  unidad por area, pero no dice cual, y el rango medido (0 a 658) no cuadra con las
  descargas por km2 y ano que usa la norma. Antes que estampar una unidad equivocada
  en un tablero que van a leer ingenieros, la celda queda vacia. Si alguien confirma
  la unidad, este es el unico sitio donde agregarla.
"""


# --- El rotulo que va DENTRO de la barra del top de variables --------------------------

ABREVIATURAS: Mapping[str, str] = {
    # Las familias climaticas: el "(12 lags)" es informacion de la tabla, no del rotulo.
    "Precipitacion (12 lags)": "Precip.",
    "Temperatura (12 lags)": "Temp.",
    "Rafaga de viento (12 lags)": "Rafaga",
    "Viento (12 lags)": "Viento",
    # Las estaticas llegan con el nombre de columna crudo como etiqueta.
    "PROMEDIO_KWH_TRF": "kWh trafo",
    "PROMEDIO_KWH_VANO": "kWh vano",
    "CAPACIDAD_NOMINAL": "Capacidad",
    "LONG_CRUCETA": "Cruceta",
    "VAL_CRIT_APOYO": "Crit. apoyo",
    "FECHA_OPERACION_VANO": "Edad vano",
    "FECHA_OPERACION_TRF": "Edad trafo",
    "CNT_FASES": "Fases",
    "CNT_VN": "Vanos",
    "CANTIDAD_TIERRA": "Tierra",
    "CALIBRE_NEUTRO": "Neutro",
    "LONGITUD": "Longitud",
    "ALTURA": "Altura",
    "CONDUCTOR": "Conductor",
}
"""Nombre corto de cada variable, para escribirlo DENTRO de su barra.

Se DECLARA y no se deduce recortando la cadena: `"PROMEDIO_KWH_TRF"[:8]` da
`"PROMEDIO"`, que es la mitad del nombre de tres variables distintas y las
vuelve indistinguibles justo en el panel que existe para diferenciarlas.

Quedan fuera a proposito las que ya son cortas y reconocibles tal cual --
`NR_T`, `DDT`, `TIPO`, `TIPO_TAX`, `NG_RED`, `X2`, `Y2` --: un resumen que no
acorta solo agrega un nombre mas que aprender.
"""

# Ancho de caracter a 8 px con la pila de fuentes de Plotly (`"Open Sans", verdana,
# arial, sans-serif`), MEDIDO con `measureText` en el navegador y no estimado:
#
#   kWh trafo   39,42 px -> 4,38 /car      NR_T   21,56 px -> 5,39 /car
#   Precip.     27,18 px -> 3,88 /car      DDT    17,06 px -> 5,69 /car
#   Crit. apoyo 44,18 px -> 4,02 /car      NR     11,55 px -> 5,77 /car
#
# Son dos familias y no una: las iniciales van en MAYUSCULA sostenida, que es medio
# caracter mas ancha que el texto mixto de los resumenes. Un solo promedio le queda
# corto a una y le sobra a la otra -- con 5,6 para todo, "kWh trafo" pedia 58 px de
# barra para un texto que mide 39. Cada constante es el maximo medido de su familia,
# asi que el rotulo nunca se sale; el error cae siempre del lado de escribir de menos,
# que es el que no rompe nada porque el nombre completo esta en el hover.
PX_POR_CARACTER_MAYUSCULAS = 5.8
PX_POR_CARACTER_MIXTO = 4.7
# El aire en las dos puntas, para que el rotulo no toque el borde de su barra.
HOLGURA_PX = 6.0
# Estas medidas valen para 8 px. Cambiar el tamanio de fuente del panel obliga a
# volver a medir; el cuaderno lo fija en `TAM_FUENTE_BARRA`.
TAM_FUENTE_MEDIDO = 8


def ancho_px(texto: str) -> float:
    """Cuanto mide `texto` escrito dentro de una barra, a `TAM_FUENTE_MEDIDO` px."""
    por_caracter = (PX_POR_CARACTER_MAYUSCULAS if texto.isupper()
                    else PX_POR_CARACTER_MIXTO)
    return len(texto) * por_caracter


def abreviatura(label: str) -> str:
    """El nombre corto de la variable, o el suyo propio si no tiene uno declarado."""
    return ABREVIATURAS.get(label, label)


def iniciales(label: str) -> str:
    """La ultima parada antes de no escribir nada: las iniciales del RESUMEN.

    Del resumen y no del nombre crudo porque es el rotulo que el lector ya vio
    escrito completo en las barras largas del mismo grupo, asi que `KT` se
    reconstruye desde `kWh trafo` sin tener que adivinar.
    """
    palabras = [p for p in re.split(r"[^0-9A-Za-z]+", abreviatura(label)) if p]
    return "".join(p[0].upper() for p in palabras[:3])


def rotulo_en_barra(
    label: str,
    largo_px: float,
    *,
    holgura_px: float = HOLGURA_PX,
) -> str:
    """Que escribir dentro de una barra de `largo_px` de largo: el resumen, sus
    iniciales, o nada.

    La barra lleva el nombre encima porque con cinco vanos por diez posiciones
    no hay leyenda que alcance -- cincuenta entradas no se leen -- y el rotulo
    pegado al dato ahorra el cruce. Pero el nombre completo no cabe en una barra
    corta, y Plotly no sabe achicarlo a media palabra: o lo escribe entero o lo
    esconde. Elegir el rotulo aqui es lo que convierte ese todo-o-nada en una
    cascada, y el nombre completo sigue estando en la etiqueta del mouse, que es
    donde se resuelve la duda.

    Vacio antes que cortado: un texto que se sale de su barra se monta sobre la
    vecina y termina rotulando a la variable equivocada.
    """
    for texto in (abreviatura(label), iniciales(label)):
        if texto and largo_px >= ancho_px(texto) + holgura_px:
            return texto
    return ""


def _fila(knob: Knob) -> dict[str, object]:
    veredicto, motivo = JUICIO_SIMULACION.get(
        knob.id, (SIN_EVALUAR, "Sin veredicto en `JUICIO_SIMULACION`: agregarlo antes "
                               "de ofrecer esta variable como palanca.")
    )
    limites = knob.bounds if knob.kind == "numeric" else None
    return {
        "Variable": knob.label,
        # Una familia climatica es UN control que mueve 12 features. Sin esta columna
        # "Precipitacion" se lee como una sola feature y su peso en el modelo parece
        # doce veces menor de lo que es.
        "Controla": len(knob.feature_names),
        "Tipo": knob.kind,
        "vmin": None if limites is None else float(limites[0]),
        "vmax": None if limites is None else float(limites[1]),
        "Unidad": UNIDADES.get(knob.id, ""),
        "Opciones": " | ".join(knob.categories) if knob.categories else "",
        "Sentido de simular": veredicto,
        "Por que": motivo,
        "_orden": _ORDEN.get(veredicto, len(VEREDICTOS)),
    }


def tabla_variables_simulables(knobs: Iterable[Knob]) -> pd.DataFrame:
    """Notebook 06's variable table: one row per knob the panel can actually
    move, with its range and the verdict on whether simulating it means
    anything.

    Constant knobs are left out -- they have a single observed value or a
    single category, the panel already hides them, and a row whose range is a
    point pads the table without telling anyone anything.

    Numeric knobs carry `vmin`/`vmax` from the knob's OWN bounds, which
    `build_knobs` derives from the observed data. Reading them from a second
    hand-written source could disagree with what the slider actually allows.
    Categorical knobs leave the range empty and list their options instead: a
    range over category codes invites reading 2 as "twice 1".
    """
    filas = [_fila(knob) for knob in knobs if knob.kind != "constant"]
    columnas = ["Variable", "Controla", "Tipo", "vmin", "vmax", "Unidad", "Opciones",
                "Sentido de simular", "Por que"]
    if not filas:
        return pd.DataFrame(columns=columnas)
    tabla = pd.DataFrame(filas).sort_values(
        ["_orden", "Variable"], kind="stable"
    ).reset_index(drop=True)
    return tabla[columnas]


# Los DOS veredictos que el panel ofrece como controles, y el orden de sus columnas.
VEREDICTOS_OFRECIDOS: tuple[str, ...] = ("Si -- intervencion", "Si -- escenario")
_NOMBRE_GRUPO = {"Si -- intervencion": "Intervencion", "Si -- escenario": "Escenario"}


GRUPO_POR_KNOB: Mapping[str, str] = {
    knob_id: _NOMBRE_GRUPO[veredicto]
    for knob_id, (veredicto, _motivo) in JUICIO_SIMULACION.items()
    if veredicto in _NOMBRE_GRUPO
}
"""`knob_id -> "Intervencion" | "Escenario"` para los controles que el panel ofrece.

Es lo que permite que el ranking de relevancia RESERVE sitio para los dos grupos. Sin
la reserva, un ranking copado por las cuatro familias climaticas no deja ni una palanca
que una cuadrilla pueda ejecutar, y el panel existe para sostener una orden de trabajo.
"""


def _veredicto(knob: Knob, juicio: Mapping[str, tuple[str, str]] | None = None) -> str:
    tabla = JUICIO_SIMULACION if juicio is None else juicio
    return tabla.get(knob.id, (SIN_EVALUAR, ""))[0]


def knobs_simulables(knobs: Iterable[Knob]) -> list[Knob]:
    """Los controles que el panel PUEDE ofrecer: todos menos los refutados.

    No es cosmetica. Mientras una variable refutada siga en la lista, el tablero la
    presenta como equivalente a la poda o a la puesta a tierra, y tarde o temprano
    alguien mueve las coordenadas de un vano creyendo que eso es un escenario -- o
    baja los trafos afectados en la falla y lee el resultado como una causa.

    Quitarlas del panel NO las saca de la simulacion: un override solo se escribe si
    el usuario lo fija, asi que estas variables entran al modelo con el valor
    OBSERVADO de cada vano, que es exactamente lo que corresponde. Lo unico que se
    pierde es la posibilidad de moverlas.

    `Limitado` TAMPOCO se ofrece. Significa que hay una lectura unica bajo la cual la
    variable se interpreta, y un deslizador no puede transmitir esa condicion: quien lo
    mueve ve el numero, no el motivo. Recibe el mismo trato que las refutadas -- entra
    con su valor observado y no se puede mover -- y la tabla explica por que.

    `Sin evaluar` SI se queda: esconder en silencio justo el caso que hay que revisar
    es la peor de las opciones, y la tabla ya lo marca.
    """
    return [knob for knob in knobs
            if _veredicto(knob) in VEREDICTOS_OFRECIDOS or _veredicto(knob) == SIN_EVALUAR]


def knobs_bloqueados(knobs: Iterable[Knob]) -> list[Knob]:
    """Los que `knobs_simulables` deja fuera, en el orden en que se nombran.

    El panel los NOMBRA en vez de dejarlos desaparecer: una lista que se acorta sin
    explicacion se lee como que faltan variables, no como una decision.
    """
    ofrecidos = {k.id for k in knobs_simulables(knobs)}
    return sorted((k for k in knobs if k.id not in ofrecidos), key=lambda k: k.id)


def columnas_panel(
    knobs: Iterable[Knob],
    *,
    por_grupo: int = 2,
    juicio: Mapping[str, tuple[str, str]] | None = None,
) -> list[tuple[str, list[Knob]]]:
    """Las columnas del selector de variables: `por_grupo` por cada veredicto que el
    panel ofrece, o sea cuatro -- dos de intervencion y dos de escenario.

    Una lista corrida de dieciocho casillas obliga a recordar el veredicto de cada
    una para saber a cual de las dos preguntas pertenece: "que obra hago" y "que pasa
    si". En columnas eso lo dice la posicion, y el titulo de la primera columna de
    cada grupo lo confirma.

    El reparto deja la mitad MAYOR primero -- con 11 controles, 6 y 5 --, porque una
    columna corta a la izquierda deja un escalon que se lee como si faltara algo.

    Los cuatro huecos existen siempre, aunque un grupo quede vacio: el selector se
    arma una sola vez y una columna que aparece y desaparece correria a las demas de
    sitio cada vez que cambia el catalogo.
    """
    columnas: list[tuple[str, list[Knob]]] = []
    knobs = list(knobs)
    for veredicto in VEREDICTOS_OFRECIDOS:
        delgrupo = [k for k in knobs if _veredicto(k, juicio) == veredicto]
        nombre = _NOMBRE_GRUPO[veredicto]
        # `-(-n // p)` es el techo de la division: la primera columna se queda con el
        # sobrante en vez de arrastrarlo hasta la ultima.
        tam = -(-len(delgrupo) // por_grupo) if delgrupo else 0
        for i in range(por_grupo):
            trozo = delgrupo[i * tam:(i + 1) * tam] if tam else []
            titulo = f"{nombre} ({len(delgrupo)})" if i == 0 else f"{nombre} (cont.)"
            columnas.append((titulo, trozo))
    return columnas


# --- Fila 4 del cuaderno 06: UITI medido contra UITI simulado -------------------------

ETIQUETA_CIRCUITO_COMPLETO = "TODOS los vanos"

# Un grado de holgura al decidir de que lado se ancla el rotulo de un nodo. Es el
# ancho del borde donde `cos` no da cero exacto; ver `rotacion_radial`.
_TOLERANCIA_ANGULO = 1e-6


def barras_uiti_por_vano(
    tabla_simulada,
    *,
    observados: Mapping[str, float],
    total_circuito: float,
    etiqueta_total: str = ETIQUETA_CIRCUITO_COMPLETO,
) -> dict[str, Any]:
    """The grouped bars of row 4: for each simulated vano, the `uiti_acumulado`
    MEASURED in the active window against the UITI the model predicts after the
    intervention, plus a last group for the whole circuit.

    The base bar is the measured value and not the model's own base, because that
    is the number the user compares against -- it is what the database says
    happened. The consequence has to be read with care and is why the `+-` exists:
    the two bars are different KINDS of quantity, so their naked difference carries
    the model's level error.

    That error was measured rather than guessed. Over 599 real bags the model
    correlates 0,950 with the observed UITI -- it ranks well -- but its median
    relative error is 39,4% (p90 104%) and its total runs +34,0% high. So each
    bar's error is `|u_base - observado|`: what the model got wrong on the BASE of
    that same vano, which is a local, directly measured quantity and needs no extra
    model call.

    The rejected alternative is recorded because it looks more principled and is
    not: bootstrapping each bag's own events and re-predicting gives a relative
    standard deviation of 0,000 (measured at 50 and 200 replicas). The prediction
    does not depend on which events fell in the bag, so that error bar would have
    been decoration over the real uncertainty, which is two orders of magnitude
    larger.

    The total group's error is the SUM of the offsets and not their quadrature:
    the bias is systematic (+34% across the board), so combining them in quadrature
    would assert a cancellation that does not happen.

    A scored vano with no measured cell in the active window is LEFT OUT: there is
    no measured value to compare it against, and giving it a zero base would assert
    an observed UITI of zero, which is exactly what nobody measured.
    """
    vacio = {
        "x": [], "observado": [], "simulado": [], "error": [], "hover": [],
        "etiqueta_total": etiqueta_total, "reduccion": None, "desviacion": None,
    }
    if tabla_simulada is None or len(tabla_simulada) == 0:
        return vacio

    x: list[str] = []
    observado: list[float] = []
    simulado: list[float] = []
    error: list[float] = []
    hover: list[str] = []
    for fid, u_base, u_sim in zip(tabla_simulada["FID_VANO"],
                                  tabla_simulada["u_base"],
                                  tabla_simulada["u_simulado"]):
        fid = str(fid)
        if fid not in observados:
            continue
        medido = float(observados[fid])
        desfase = abs(float(u_base) - medido)
        x.append(fid)
        observado.append(medido)
        simulado.append(float(u_sim))
        error.append(desfase)
        hover.append(
            f"<b>Vano {fid}</b>"
            f"<br>UITI medido en la ventana: {medido:,.2f}"
            f"<br>UITI simulado: {float(u_sim):,.2f}"
            f"<br>Base del modelo: {float(u_base):,.2f}"
            f"<br>Desfase del modelo en la base: {desfase:,.2f}"
        )

    if not x:
        return vacio

    total_circuito = float(total_circuito)
    # Los vanos que nadie simulo se quedan como estan: el total simulado cambia solo
    # en lo que cambiaron los simulados.
    total_simulado = total_circuito - sum(observado) + sum(simulado)
    error_total = float(sum(error))
    x.append(etiqueta_total)
    observado.append(total_circuito)
    simulado.append(total_simulado)
    error.append(error_total)
    hover.append(
        f"<b>{etiqueta_total}</b>"
        f"<br>UITI medido del circuito en la ventana: {total_circuito:,.2f}"
        f"<br>Con la intervencion: {total_simulado:,.2f}"
        f"<br>Los {len(x) - 1} vanos simulados aportan "
        f"{sum(observado[:-1]):,.2f} de ese total"
        f"<br>Desfase acumulado del modelo: {error_total:,.2f}"
    )
    return {
        "x": x, "observado": observado, "simulado": simulado, "error": error,
        "hover": hover, "etiqueta_total": etiqueta_total,
        "reduccion": float(sum(observado[:-1]) - sum(simulado[:-1])),
        "desviacion": error_total,
    }


def rotacion_radial(x: float, y: float) -> tuple[float, str]:
    """`(textangle, xanchor)` so a circular graph's node label runs ALONG its own
    radius, pointing away from the centre.

    With every label horizontal, the names of neighbouring nodes sit on top of each
    other around the ring -- the crowding is worst at the top and bottom, where the
    circle is flattest. Along the radius they fan out with the nodes themselves, so
    the spacing between labels grows with the distance from the centre.

    Two conventions are baked in. Plotly's `textangle` turns CLOCKWISE, hence the
    negated angle. And on the left half a radial label would read upside down, so
    it is turned another half turn and anchored on its other side -- which keeps it
    growing outward while still reading left to right.

    A node exactly at the centre has no radius to follow and stays horizontal: an
    `atan2(0, 0)` would hand back an angle that means nothing.

    Labels have to be `layout.annotations` and not the trace's own `text`: a
    `Scatter` cannot rotate its text at all (checked against plotly 6.8.0 -- only
    `Bar` and annotations carry `textangle`).
    """
    if x == 0.0 and y == 0.0:
        return 0.0, "left"
    grados = math.degrees(math.atan2(y, x))
    # La comparacion lleva tolerancia porque el borde cae justo donde `cos` no da cero
    # exacto: en la base del circulo `cos(270 grados)` vale -1,8e-16, negativo, y sin
    # la holgura el rotulo de ese nodo salta de un anclaje al otro por ruido de punto
    # flotante. Arriba y abajo el texto queda vertical y los dos anclajes se ven igual;
    # lo que no puede pasar es que la eleccion dependa del decimal diecisiete.
    if -90.0 - _TOLERANCIA_ANGULO <= grados <= 90.0 + _TOLERANCIA_ANGULO:
        return -grados, "left"
    # Media vuelta y anclaje al otro lado: el rotulo sigue saliendo hacia afuera.
    return -(grados - 180.0) if grados > 90.0 else -(grados + 180.0), "right"
