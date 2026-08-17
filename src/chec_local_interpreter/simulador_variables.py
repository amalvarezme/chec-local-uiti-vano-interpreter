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
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
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
_MOTIVO_SIN_JUICIO = ("Sin veredicto en `data/Variables_simular.xlsx`: agregarlo antes de ofrecer "
                      "esta variable como palanca.")

# Veredicto y motivo por variable. La descripcion entre comillas de cada motivo es
# la del diccionario del proyecto, `data/Variables_seleccion.xlsx`.
# --------------------------------------------------------------------------------
# El catalogo de simulacion: que variables se ofrecen, con que rango y como
# --------------------------------------------------------------------------------
# Antes esto eran ~150 lineas de diccionario escrito a mano aqui mismo. Ahora sale de
# `data/Variables_simular.xlsx`, y por dos razones concretas:
#
#  1. **Es una decision del negocio, no del codigo.** Cambiar el veredicto de una
#     variable -- o el rango en que tiene sentido moverla -- no deberia exigir editar
#     Python ni volver a desplegar nada.
#  2. **Trae los valores posibles.** El modelo ve `ALTURA` como un numero entre 4 y 25,
#     pero el inventario solo tiene apoyos de 12, 16 y 18 metros. Sin esa lista, el
#     panel ofrecia un deslizador continuo e invitaba a simular un apoyo de 17,3 m que
#     no existe. Con ella, se ofrece un selector cerrado.
#
# UNA sola fuente. No se conserva ninguna copia en el codigo: dos listas que tienen que
# coincidir para siempre terminan no coincidiendo, y el dia que se separan nadie sabe
# cual manda.

RUTA_VARIABLES_SIMULAR = "data/Variables_simular.xlsx"
HOJA_VARIABLES_SIMULAR = "Variables a simular ajustado"

# La aplicacion del cuaderno 06 sirve un paquete congelado y no abre `data/`. Esta
# variable de entorno es como se le dice donde quedo su copia del archivo.
VARIABLE_ENTORNO_RUTA = "RUTA_VARIABLES_SIMULAR"

_COLUMNAS_REQUERIDAS = (
    "Variable", "Controla", "Tipo", "vmin", "vmax", "Unidad", "Opciones",
    "Sentido de simular", "Por que",
)

# El archivo nombra las familias climaticas en palabras -- son cuatro controles de 12
# rezagos cada uno --, y el catalogo de knobs las llama `clima:<codigo>`. Sin esta
# traduccion las cuatro quedarian fuera y el panel las trataria como `Sin evaluar`,
# que es justo lo contrario de lo que dice el archivo.
_ID_POR_NOMBRE = {
    "Precipitacion (12 lags)": "clima:prep",
    "Temperatura (12 lags)": "clima:temp",
    "Rafaga de viento (12 lags)": "clima:wind_gust_spd",
    "Viento (12 lags)": "clima:wind_spd",
}

CONTROL_SELECTOR = "selector"
CONTROL_DESLIZADOR = "deslizador"
CONTROL_DESLIZADOR_ENTERO = "deslizador-entero"

#: Los nombres con los que el archivo ha declarado una variable ENTERA. `int` es el
#: vigente; `numeric-entero` es el anterior y se sigue entendiendo porque la aplicacion
#: empaquetada sirve SU copia del archivo y puede ir por detras del repositorio. No
#: entenderlo no falla: degrada en silencio a deslizador continuo, que es exactamente
#: como se colo este defecto al renombrarse la columna.
TIPOS_ENTEROS = ("int", "numeric-entero")


@dataclass(frozen=True)
class VariableSimulable:
    """Una fila del archivo, ya interpretada."""

    knob_id: str
    variable: str
    controla: int
    tipo: str
    vmin: float | None
    vmax: float | None
    unidad: str
    opciones: tuple[str, ...]
    veredicto: str
    motivo: str

    @property
    def control(self) -> str:
        """Que control le corresponde en el panel.

        La lista de valores posibles manda sobre el tipo: si el archivo declara cuales
        son, el control es cerrado aunque el modelo vea un numero continuo. Es la
        diferencia entre ofrecer los apoyos que existen y ofrecer cualquier altura.
        Por eso `ALTURA`, declarada `categorical` con `12|16|18`, sale como selector y no
        como deslizador aunque sus tres valores sean numeros.

        Sin lista, manda el tipo: entero -> deslizador de enteros, y lo demas ->
        deslizador continuo. Se comparan contra `TIPOS_ENTEROS` y no contra una sola
        cadena porque el archivo ya renombro ese tipo una vez.
        """
        if self.opciones:
            return CONTROL_SELECTOR
        if self.tipo in TIPOS_ENTEROS:
            return CONTROL_DESLIZADOR_ENTERO
        return CONTROL_DESLIZADOR

    @property
    def opciones_numericas(self) -> bool:
        """Si las opciones son numeros -- `12|16|18` -- y no texto -- `Ramal|Troncal`.

        Decide que viaja al modelo: un numero tal cual, o una categoria que hay que
        codificar antes.
        """
        if not self.opciones:
            return False
        return all(_es_numero(v) for v in self.opciones)

    @property
    def valores_numericos(self) -> tuple[float, ...]:
        return tuple(float(v) for v in self.opciones) if self.opciones_numericas else ()


def _es_numero(texto: str) -> bool:
    try:
        float(texto)
    except (TypeError, ValueError):
        return False
    return True


def _texto(valor: object) -> str:
    return "" if valor is None or (isinstance(valor, float) and math.isnan(valor)) \
        else str(valor).strip()


def _numero(valor: object) -> float | None:
    if valor is None:
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(numero) else numero


def ruta_variables_simular() -> Path:
    """La ruta del archivo: la del entorno si esta puesta, o la del repositorio."""
    del_entorno = os.environ.get(VARIABLE_ENTORNO_RUTA)
    return Path(del_entorno) if del_entorno else Path(RUTA_VARIABLES_SIMULAR)


# Cache por (ruta, fecha de modificacion). Leer el .xlsx cuesta decenas de
# milisegundos, y `widget_for_knob` lo consulta una vez por control y por vano: sin
# cache serian cientos de lecturas para pintar un panel. La fecha entra en la clave
# para que editar el archivo se note sin reiniciar nada.
_CACHE: dict[tuple[str, int], dict[str, VariableSimulable]] = {}


def catalogo_simulacion(path: str | Path | None = None) -> dict[str, VariableSimulable]:
    """`knob_id -> VariableSimulable`, leido de `Variables_simular.xlsx`."""
    ruta = Path(path) if path is not None else ruta_variables_simular()
    if not ruta.exists():
        raise FileNotFoundError(
            f"No se encontro {ruta}. Es el archivo que dice que variables se pueden "
            "simular, con que rango y con que valores posibles; sin el, el panel no "
            "sabe que ofrecer. Deberia estar en data/Variables_simular.xlsx."
        )
    clave = (str(ruta.resolve()), ruta.stat().st_mtime_ns)
    if clave not in _CACHE:
        _CACHE[clave] = _leer_catalogo(ruta)
    return _CACHE[clave]


def _leer_catalogo(ruta: Path) -> dict[str, VariableSimulable]:
    tabla = pd.read_excel(ruta, sheet_name=HOJA_VARIABLES_SIMULAR)
    columnas = {str(c).strip(): c for c in tabla.columns}
    faltan = [c for c in _COLUMNAS_REQUERIDAS if c not in columnas]
    if faltan:
        raise ValueError(
            f"A {ruta.name} le faltan columnas: {faltan}. Se esperan "
            f"{list(_COLUMNAS_REQUERIDAS)}."
        )

    catalogo: dict[str, VariableSimulable] = {}
    for _, fila in tabla.iterrows():
        nombre = _texto(fila[columnas["Variable"]])
        if not nombre:
            continue
        knob_id = _ID_POR_NOMBRE.get(nombre, nombre)
        crudas = _texto(fila[columnas["Opciones"]])
        # El separador es `|`, y en el archivo real hay espacios alrededor en unas
        # filas y no en otras (`1CC | 1CFR` contra `12|16|18`). Se normaliza aqui para
        # que la comparacion contra las categorias del modelo no falle por un espacio.
        opciones = tuple(o.strip() for o in crudas.split("|") if o.strip()) if crudas else ()
        controla = _numero(fila[columnas["Controla"]])
        catalogo[knob_id] = VariableSimulable(
            knob_id=knob_id,
            variable=nombre,
            controla=int(controla) if controla else 1,
            tipo=_texto(fila[columnas["Tipo"]]) or "numeric",
            vmin=_numero(fila[columnas["vmin"]]),
            vmax=_numero(fila[columnas["vmax"]]),
            unidad=_texto(fila[columnas["Unidad"]]),
            opciones=opciones,
            veredicto=_texto(fila[columnas["Sentido de simular"]]) or SIN_EVALUAR,
            motivo=_texto(fila[columnas["Por que"]]),
        )
    return catalogo


def incoherencias_del_catalogo(
    knobs: Iterable[Knob],
    catalogo: Mapping[str, VariableSimulable] | None = None,
) -> list[str]:
    """Opciones que el archivo ofrece y el modelo no sabe codificar.

    No es un detalle de forma. Una categoria que el codificador no conoce falla en
    mitad de una simulacion -- o, peor, se codifica como otra cosa sin aviso --, y el
    usuario lee un resultado que corresponde a un vano distinto del que pidio.

    Devuelve avisos en vez de lanzar: el panel sigue funcionando con las categorias que
    el modelo si conoce, y el aviso queda a la vista de quien mantiene el archivo.
    """
    catalogo = catalogo_simulacion() if catalogo is None else catalogo
    avisos: list[str] = []
    for knob in knobs:
        entrada = catalogo.get(knob.id)
        if entrada is None or not entrada.opciones or knob.kind != "categorical":
            continue
        conocidas = set(knob.categories or ())
        desconocidas = [o for o in entrada.opciones if o not in conocidas]
        if desconocidas:
            avisos.append(
                f"{knob.id}: {len(desconocidas)} de {len(entrada.opciones)} opciones de "
                f"{RUTA_VARIABLES_SIMULAR} no estan entre las categorias que el modelo "
                f"sabe codificar y NO se ofrecen -- {desconocidas[:4]}"
                f"{' ...' if len(desconocidas) > 4 else ''}. "
                f"El panel usa las {len(conocidas)} categorias reales."
            )
    return avisos


def opciones_ofrecidas(knob: Knob,
                       entrada: VariableSimulable | None) -> tuple[str, ...]:
    """Las opciones que el panel puede ofrecer de verdad para `knob`.

    Es la interseccion entre lo que el archivo propone y lo que el modelo sabe
    codificar. Si no queda ninguna -- el archivo se equivoco de variable entera --, se
    cae a las categorias del modelo: quedarse sin control es peor que ofrecer la lista
    completa, y `incoherencias_del_catalogo` ya lo reporto.
    """
    conocidas = tuple(knob.categories or ())
    if entrada is None or not entrada.opciones:
        return conocidas
    if knob.kind != "categorical":
        return entrada.opciones
    validas = tuple(o for o in entrada.opciones if o in conocidas)
    return validas or conocidas




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
# El alto del RENGLON de ese texto. El rotulo va girado -90, asi que este numero se
# compara contra el GROSOR de la barra y no contra su largo: es lo que decide si el
# texto se queda dentro o se monta sobre la barra vecina. Un renglon mide mas que el
# tamanio de la fuente -- ascendentes y descendentes -- y se redondea hacia arriba, del
# mismo lado que el resto de las constantes de aqui: escribir de menos no rompe nada
# porque el nombre completo esta en el hover.
ALTO_RENGLON_PX = 11.0


def ancho_px(texto: str, tam_fuente: float = TAM_FUENTE_MEDIDO) -> float:
    """Cuanto mide `texto` escrito dentro de una barra, al tamanio de fuente que se pida.

    Las dos constantes de px por caracter se MIDIERON a `TAM_FUENTE_MEDIDO` (8 px). El
    avance de un caracter escala con el tamanio de la fuente en la misma tipografia, asi
    que se escala en vez de fingir una segunda medicion. Importa: el panel del top pasa a
    9 px para igualar sus marcas de eje, y usar los numeros de 8 tal cual subestimaria el
    ancho un 12,5% y meteria dentro de la barra un rotulo que se sale por las dos puntas.
    """
    por_caracter = (PX_POR_CARACTER_MAYUSCULAS if texto.isupper()
                    else PX_POR_CARACTER_MIXTO)
    return len(texto) * por_caracter * (tam_fuente / TAM_FUENTE_MEDIDO)


def alto_renglon_px(tam_fuente: float = TAM_FUENTE_MEDIDO) -> float:
    """El alto del renglon al tamanio que se pida, escalado desde el medido.

    Es lo que se compara contra el GROSOR de la barra, porque el rotulo va girado -90.
    """
    return ALTO_RENGLON_PX * (tam_fuente / TAM_FUENTE_MEDIDO)


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
    grosor_px: float | None = None,
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

    Y la barra lo limita por sus DOS lados. `largo_px` decide si el texto cabe
    escrito; `grosor_px` -- el ancho de la barra, contra el que se apoya el
    RENGLON del texto girado -- decide si cabe sin invadir a la de al lado. Con
    ocho vanos por diez posiciones cada barra mide 3,6 px medidos a 1.280 px de
    ventana, y ahi no cabe ningun rotulo: eran ochenta textos verticales unos
    encima de otros. Es opcional porque el ancho del panel no se conoce en
    Python -- la figura es responsive y lo fija el contenedor --, asi que solo
    lo pasa quien puede estimarlo.
    """
    if grosor_px is not None and grosor_px < ALTO_RENGLON_PX:
        return ""
    for texto in (abreviatura(label), iniciales(label)):
        if texto and largo_px >= ancho_px(texto) + holgura_px:
            return texto
    return ""


def rotulo_y_posicion(
    label: str,
    largo_px: float,
    *,
    hueco_px: float,
    holgura_px: float = HOLGURA_PX,
    grosor_px: float | None = None,
) -> tuple[str, str]:
    """El rotulo y DONDE va: `('kWh trafo', 'inside')`, `('KT', 'outside')` o `('', ...)`.

    `rotulo_en_barra` resuelve el dentro y acababa en vacio cuando ni las iniciales
    cabian. Ese ultimo escalon perdia informacion sin necesidad: dentro de una barra el
    sitio lo da la BARRA, que en ese caso es corta, pero encima de ella lo da el HUECO
    hasta el techo del eje -- y en una barra corta ese hueco es casi todo el panel. Los
    dos espacios no son el mismo y no tienen por que decidirse juntos.

    `hueco_px` es esa distancia entre la punta de la barra y el techo del eje. Se pide y
    no se calcula aqui porque depende del rango del eje y del alto de la figura, que este
    modulo no conoce.

    Dentro se prefiere a encima: el rotulo pegado al dato no obliga a cruzar la vista, y
    encima compite con la barra siguiente del grupo.

    El GROSOR manda por encima de todo y no lo arregla mudar el rotulo. Girado -90 el
    renglon se apoya contra el ancho de la barra tanto dentro como fuera, asi que con
    barras de 3,6 px -- ocho vanos por diez posiciones, medido a 1.280 -- los ochenta
    rotulos se montan unos sobre otros esten donde esten.

    La posicion que acompania a un rotulo vacio es `'inside'` y da igual cual sea: Plotly
    no dibuja nada. Se devuelve una fija para que el llamador no tenga que ramificar.
    """
    if grosor_px is not None and grosor_px < ALTO_RENGLON_PX:
        return "", "inside"
    dentro = rotulo_en_barra(label, largo_px, holgura_px=holgura_px, grosor_px=grosor_px)
    if dentro:
        return dentro, "inside"
    # La misma cascada, contra el otro espacio. No hay razon para decidir distinto arriba
    # que abajo: lo unico que cambia es cuanto sitio hay.
    for texto in (abreviatura(label), iniciales(label)):
        if texto and hueco_px >= ancho_px(texto) + holgura_px:
            return texto, "outside"
    return "", "inside"


#: Cuantas posiciones del top llevan el CODIGO de columna escrito. Las demas se quedan
#: sin rotulo: con diez por vano no hay panel que las sostenga, y las cinco primeras son
#: donde se decide una obra.
TOP_POSICIONES_ROTULADAS = 5


def rotulo_de_codigo(
    codigo: str,
    largo_px: float,
    *,
    hueco_px: float,
    holgura_px: float = HOLGURA_PX,
    tam_fuente: float = TAM_FUENTE_MEDIDO,
) -> tuple[str, str]:
    """El codigo de columna y DONDE va: `('NR_T', 'inside')` o `('NR_T', 'outside')`.

    Nunca devuelve vacio, y ahi esta toda la diferencia con `rotulo_y_posicion`. Aquella
    baja por una cascada -- resumen, abreviatura, iniciales, nada -- porque escribe el
    nombre en palabras y un nombre cortado no dice nada que el hover no diga mejor. Este
    escribe el CODIGO DE LA COLUMNA, que es lo que permite cruzar la barra con la tabla
    de vanos: sin el, la barra es anonima y no hay hover que la cruce por el usuario.

    Asi que solo se decide el sitio. Dentro se prefiere a encima -- pegado al dato, sin
    competir con la barra siguiente del grupo --, y encima es la salida cuando el largo
    de la barra no da.

    Un codigo que tampoco cabe en el hueco de arriba se escribe IGUAL, encima. Es lo
    pedido y es defendible aqui: en este panel vale mas un codigo que se sale de su hueco
    que una barra sin identificar.

    Lo que este modulo NO puede decidir es el traslape entre barras VECINAS: el rotulo va
    girado -90, asi que su renglon se apoya contra el GROSOR de la barra, y ese numero
    depende del ancho del panel y de cuantos vanos hay marcados. Medido sobre el panel
    mas estrecho que el tablero soporta (719 px) y a fuente 9: la barra mide 12,81 px con
    cuatro vanos marcados contra 12,38 de renglon, y 10,25 px con cinco. Con cuatro o
    menos los cinco rotulos no se tocan; de cinco en adelante si.
    """
    if not codigo:
        return "", "inside"
    if largo_px >= ancho_px(codigo, tam_fuente) + holgura_px:
        return codigo, "inside"
    return codigo, "outside"


RUTA_DICCIONARIO = "data/Variables_seleccion.xlsx"
HOJA_DICCIONARIO = "Variables_análisis"


def descripciones_de_variables(path: str | Path | None = None) -> dict[str, str]:
    """`knob_id -> nombre en palabras`, del diccionario del proyecto.

    `NR_T` no le dice nada a quien opera la red. `Variables_seleccion.xlsx` ya trae el
    nombre en palabras de cada columna -- y es el MISMO documento que sustenta los
    veredictos de `Variables_simular.xlsx` --, asi que leerlo de ahi evita que el panel
    invente una segunda redaccion que se separa de la primera en cuanto alguien edita
    una sola.

    Devuelve `{}` si el archivo no esta: el diccionario es un archivo mas del proyecto
    y puede faltar en una corrida, y quedarse sin panel de informacion es peor que
    quedarse sin el nombre largo.
    """
    from pathlib import Path as _Path

    ruta = _Path(path) if path is not None else _Path(RUTA_DICCIONARIO)
    if not ruta.exists():
        return {}
    tabla = pd.read_excel(ruta, sheet_name=HOJA_DICCIONARIO)
    columnas = {str(c).strip(): c for c in tabla.columns}
    if "COLUMNA" not in columnas or "DESCRIPCIÓN_COLUMNA" not in columnas:
        return {}

    mapa: dict[str, str] = {}
    for col, desc in zip(tabla[columnas["COLUMNA"]], tabla[columnas["DESCRIPCIÓN_COLUMNA"]]):
        if pd.isna(col) or pd.isna(desc):
            continue
        clave = str(col).strip()
        texto = str(desc).strip()
        mapa[clave] = texto
        # Las familias climaticas llegan como `clima:prep`; la clave del diccionario es
        # la columna pelada. Sin esta linea, las doce entradas de clima salen sin nombre.
        mapa[f"clima:{clave}"] = texto
    return mapa


def definicion_de_knob(knob: Knob, *, nombres: Mapping[str, str] | None = None) -> str:
    """Que ES esta variable, en una linea, para el tooltip de su casilla.

    El panel del cuaderno 06 ofrece las variables como casillas, y en una casilla
    solo cabe el nombre. El veredicto y el motivo de `Variables_simular.xlsx` -- lo unico
    que dice si mover esa variable representa una obra, un escenario o nada --
    vivian solo en la tabla de la celda 8, arriba y lejos del sitio donde se elige.
    Al pasar el mouse por la casilla se lee ahi mismo.

    Se arma de la MISMA fuente que esa tabla y no de un texto aparte: dos redacciones
    de la misma decision se separan en cuanto alguien edita una sola.
    """
    entrada = catalogo_simulacion().get(knob.id)
    veredicto = entrada.veredicto if entrada is not None else SIN_EVALUAR
    motivo = entrada.motivo if entrada is not None else _MOTIVO_SIN_JUICIO
    # El nombre en palabras VA PRIMERO: es lo que se lee al posar el mouse, y la sigla
    # ya esta escrita en la propia casilla.
    detallado = (nombres or {}).get(knob.id, "")
    partes = [f"{detallado}." if detallado else "", f"{veredicto}. {motivo}"]
    partes = [p for p in partes if p]
    unidad = UNIDADES.get(knob.id, "")
    if knob.kind == "numeric" and knob.bounds is not None:
        rango = f"Rango observado: {float(knob.bounds[0]):,.4g} a {float(knob.bounds[1]):,.4g}"
        partes.append(f"{rango} {unidad}".strip() + ".")
    elif unidad:
        partes.append(f"Unidad: {unidad}.")
    if knob.categories:
        partes.append("Opciones: " + " | ".join(knob.categories) + ".")
    # Una familia climatica es UN control que mueve doce columnas del modelo. Sin
    # decirlo, "Precipitacion" se lee como una sola variable.
    if len(knob.feature_names) > 1:
        partes.append(f"Controla {len(knob.feature_names)} columnas del modelo.")
    return " ".join(partes)


def definiciones_de_knobs(knobs: Iterable[Knob], *,
                          nombres: Mapping[str, str] | None = None) -> dict[str, str]:
    """`knob_id -> definicion`, tal como lo consume el selector de casillas."""
    return {knob.id: definicion_de_knob(knob, nombres=nombres) for knob in knobs}


def _fila(knob: Knob, entrada: VariableSimulable | None) -> dict[str, object]:
    veredicto = entrada.veredicto if entrada is not None else SIN_EVALUAR
    motivo = entrada.motivo if entrada is not None else _MOTIVO_SIN_JUICIO
    opciones = opciones_ofrecidas(knob, entrada)
    return {
        "Variable": knob.label,
        # Una familia climatica es UN control que mueve 12 features. Sin esta columna
        # "Precipitacion" se lee como una sola feature y su peso en el modelo parece
        # doce veces menor de lo que es.
        "Controla": entrada.controla if entrada is not None else len(knob.feature_names),
        "Tipo": entrada.tipo if entrada is not None else knob.kind,
        # Como se ofrece en el panel. Es la columna que explica por que `ALTURA` sale
        # con tres opciones y no con un deslizador de 4 a 25.
        "Control": entrada.control if entrada is not None else CONTROL_DESLIZADOR,
        "vmin": None if entrada is None else entrada.vmin,
        "vmax": None if entrada is None else entrada.vmax,
        "Unidad": entrada.unidad if entrada is not None else "",
        "Opciones": " | ".join(opciones),
        "Sentido de simular": veredicto,
        "Por que": motivo,
        "_orden": _ORDEN.get(veredicto, len(VEREDICTOS)),
    }


def tabla_variables_simulables(
    knobs: Iterable[Knob],
    catalogo: Mapping[str, VariableSimulable] | None = None,
) -> pd.DataFrame:
    """La tabla de variables del cuaderno 06: una fila por control que el panel puede
    mover, con su rango, como se ofrece y el veredicto sobre si simularlo significa
    algo.

    Los knobs constantes se dejan fuera -- tienen un unico valor observado o una unica
    categoria, el panel ya los esconde, y una fila cuyo rango es un punto engorda la
    tabla sin decirle nada a nadie.

    **El rango, la unidad y las opciones salen de `Variables_simular.xlsx`, no del
    knob.** Es deliberado y es un cambio respecto de como estaba: los limites que
    `build_knobs` deriva de los datos son los OBSERVADOS, y el archivo declara los que
    tienen sentido simular. `NR_T` llega a 116 en la base y el archivo lo confirma; la
    `ALTURA` va de 4 a 25 en los datos pero solo existen apoyos de 12, 16 y 18. Leer
    las dos cosas de sitios distintos es como la tabla y el control terminan diciendo
    cosas diferentes.
    """
    catalogo = catalogo_simulacion() if catalogo is None else catalogo
    filas = [_fila(knob, catalogo.get(knob.id))
             for knob in knobs if knob.kind != "constant"]
    columnas = ["Variable", "Controla", "Tipo", "Control", "vmin", "vmax", "Unidad",
                "Opciones", "Sentido de simular", "Por que"]
    if not filas:
        return pd.DataFrame(columns=columnas)
    tabla = pd.DataFrame(filas).sort_values(
        ["_orden", "Variable"], kind="stable"
    ).reset_index(drop=True)
    return tabla[columnas]


# Los DOS veredictos que el panel ofrece como controles, y el orden de sus columnas.
VEREDICTOS_OFRECIDOS: tuple[str, ...] = ("Si -- intervencion", "Si -- escenario")
_NOMBRE_GRUPO = {"Si -- intervencion": "Intervencion", "Si -- escenario": "Escenario"}


def grupo_por_knob(
    catalogo: Mapping[str, VariableSimulable] | None = None,
) -> dict[str, str]:
    """`knob_id -> "Intervencion" | "Escenario"` para los controles que el panel ofrece.

    Es lo que permite que el ranking de relevancia RESERVE sitio para los dos grupos.
    Sin la reserva, un ranking copado por las cuatro familias climaticas no deja ni una
    palanca que una cuadrilla pueda ejecutar, y el panel existe para sostener una orden
    de trabajo.
    """
    catalogo = catalogo_simulacion() if catalogo is None else catalogo
    return {knob_id: _NOMBRE_GRUPO[e.veredicto]
            for knob_id, e in catalogo.items() if e.veredicto in _NOMBRE_GRUPO}


def juicio_simulacion(
    catalogo: Mapping[str, VariableSimulable] | None = None,
) -> dict[str, tuple[str, str]]:
    """`knob_id -> (veredicto, motivo)`, la forma que consumia el codigo anterior."""
    catalogo = catalogo_simulacion() if catalogo is None else catalogo
    return {knob_id: (e.veredicto, e.motivo) for knob_id, e in catalogo.items()}


def __getattr__(nombre: str):
    """`GRUPO_POR_KNOB` y `JUICIO_SIMULACION` siguen existiendo como nombres del modulo.

    Se resuelven en el PRIMER ACCESO y no al importar, que es lo que permite que el
    archivo sea la unica fuente sin convertir un `import` en una lectura de disco: hay
    procesos que importan este modulo por sus utilidades de rotulado y no tienen por
    que exigir el .xlsx.
    """
    if nombre == "GRUPO_POR_KNOB":
        return grupo_por_knob()
    if nombre == "JUICIO_SIMULACION":
        return juicio_simulacion()
    raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")


def _veredicto(knob: Knob,
               catalogo: Mapping[str, VariableSimulable] | None = None) -> str:
    catalogo = catalogo_simulacion() if catalogo is None else catalogo
    entrada = catalogo.get(knob.id)
    return entrada.veredicto if entrada is not None else SIN_EVALUAR


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
    catalogo: Mapping[str, VariableSimulable] | None = None,
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
        delgrupo = [k for k in knobs if _veredicto(k, catalogo) == veredicto]
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
        "clase_observado": [], "clase_simulado": [],
        "etiqueta_total": etiqueta_total, "reduccion": None, "desviacion": None,
    }
    if tabla_simulada is None or len(tabla_simulada) == 0:
        return vacio

    x: list[str] = []
    observado: list[float] = []
    simulado: list[float] = []
    error: list[float] = []
    hover: list[str] = []
    # La clase de cada barra viaja al lado del valor para que el tablero la pinte con
    # el color de su grupo -- el mismo semaforo del mapa y del agrupamiento. Viaja la
    # CLASE y no el color porque esta funcion es pura sobre datos y cada tablero
    # declara su propia paleta.
    clase_observado: list[int | None] = []
    clase_simulado: list[int | None] = []
    for fid, u_base, u_sim, k_base, k_sim in zip(tabla_simulada["FID_VANO"],
                                                 tabla_simulada["u_base"],
                                                 tabla_simulada["u_simulado"],
                                                 tabla_simulada["base_clase_idx"],
                                                 tabla_simulada["simulado_clase_idx"]):
        fid = str(fid)
        if fid not in observados:
            continue
        medido = float(observados[fid])
        desfase = abs(float(u_base) - medido)
        x.append(fid)
        observado.append(medido)
        simulado.append(float(u_sim))
        error.append(desfase)
        clase_observado.append(_clase_o_nada(k_base))
        clase_simulado.append(_clase_o_nada(k_sim))
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
    # El circuito entero NO tiene clase: el KMeans clasifica vanos. Darle la de alguno
    # -- o la mas alta de todos -- afirmaria una criticidad que nadie le asigno.
    clase_observado.append(None)
    clase_simulado.append(None)
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
        "clase_observado": clase_observado, "clase_simulado": clase_simulado,
        "reduccion": float(sum(observado[:-1]) - sum(simulado[:-1])),
        "desviacion": error_total,
    }


def _clase_o_nada(valor: Any) -> int | None:
    """La clase como entero, o `None` si la celda no trae una.

    Una tabla simulada puede traer `NaN` donde el artefacto no expone su geometria, y
    `int(nan)` levanta `ValueError`. Caer a la clase 0 ahi pintaria de verde -- el
    grupo mas bajo -- un vano que simplemente no se pudo clasificar.
    """
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


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
