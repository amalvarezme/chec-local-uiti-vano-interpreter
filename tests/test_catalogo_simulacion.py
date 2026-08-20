"""Que ofrecera el panel despues de editar `Variables_simular.xlsx`, sin abrirlo.

Editar ese archivo cambia tres cosas a la vez -- que variables se ofrecen, con que
rango, y con QUE CONTROL -- y las tres se descubren hoy abriendo el simulador y
mirando. Dos de los tres fallos posibles no se ven mirando:

* una variable entera declarada `numeric` sale con deslizador continuo y deja poner
  "2,37 fases"; el panel no da ningun error, solo ofrece un valor imposible;
* una opcion que el modelo no sabe codificar se cae de la lista en silencio, y quien
  edito el archivo cree que la puso.

Este guion los nombra antes de reconstruir nada. `revisar` es puro -- knobs y catalogo
entran como argumentos -- para que estas pruebas no lean los 566 MB del CSV.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ / "src"))

import catalogo_simulacion as cat  # noqa: E402
from chec_local_interpreter.simulador_variables import VariableSimulable  # noqa: E402
from chec_local_interpreter.vano_controls import Knob  # noqa: E402


def _knob(knob_id: str, kind: str = "numeric", categories=None,
          bounds=(0.0, 10.0)) -> Knob:
    return Knob(id=knob_id, label=knob_id, kind=kind,
                feature_names=(knob_id,), bounds=bounds,
                categories=categories, default=None, step=None)


def _entrada(knob_id: str, tipo: str = "numeric", opciones=(),
             veredicto: str = "Si -- intervencion") -> VariableSimulable:
    return VariableSimulable(knob_id=knob_id, variable=knob_id, controla=1, tipo=tipo,
                             vmin=0.0, vmax=10.0, unidad="", opciones=tuple(opciones),
                             veredicto=veredicto, motivo="un motivo cualquiera")


def _por_id(revision) -> dict:
    return {fila.knob_id: fila for fila in revision.filas}


# ------------------------------------------------------------------ el control elegido

def test_una_lista_de_valores_manda_sobre_el_tipo():
    """`ALTURA` es `categorical` con `12|16|18`: existen apoyos de esas tres alturas y
    de ninguna otra, asi que el control es cerrado aunque sean numeros."""
    revision = cat.revisar([_knob("ALTURA", kind="categorical",
                                  categories=("12", "16", "18"))],
                           {"ALTURA": _entrada("ALTURA", tipo="categorical",
                                               opciones=("12", "16", "18"))})
    assert _por_id(revision)["ALTURA"].control == "selector"


def test_entero_sin_lista_sale_con_deslizador_de_enteros():
    revision = cat.revisar([_knob("CNT_FASES")],
                           {"CNT_FASES": _entrada("CNT_FASES", tipo="int")})
    assert _por_id(revision)["CNT_FASES"].control == "deslizador-entero"


def test_el_nombre_viejo_del_tipo_entero_se_sigue_entendiendo():
    """`numeric-entero` es el nombre anterior. La aplicacion empaquetada sirve SU copia
    del archivo y puede ir por detras del repositorio."""
    revision = cat.revisar([_knob("CNT_FASES")],
                           {"CNT_FASES": _entrada("CNT_FASES", tipo="numeric-entero")})
    assert _por_id(revision)["CNT_FASES"].control == "deslizador-entero"


def test_numerica_continua_sale_con_deslizador():
    revision = cat.revisar([_knob("LONGITUD")],
                           {"LONGITUD": _entrada("LONGITUD", tipo="numeric")})
    assert _por_id(revision)["LONGITUD"].control == "deslizador"


def test_un_knob_constante_no_es_un_control():
    revision = cat.revisar([_knob("NORMA", kind="constant")],
                           {"NORMA": _entrada("NORMA")})
    assert revision.filas == []


# ------------------------------------------------------------------ los tres desajustes

def test_una_opcion_que_el_modelo_no_codifica_se_nombra():
    revision = cat.revisar(
        [_knob("CONDUCTOR", kind="categorical", categories=("ACSR", "AAAC"))],
        {"CONDUCTOR": _entrada("CONDUCTOR", tipo="categorical",
                               opciones=("ACSR", "AAAC", "INVENTADO"))})
    assert revision.incoherencias, "una opcion desconocida se cae de la lista en silencio"
    assert "CONDUCTOR" in revision.incoherencias[0]
    assert "INVENTADO" in revision.incoherencias[0]


def test_un_knob_sin_fila_en_el_archivo_queda_sin_veredicto():
    revision = cat.revisar([_knob("LONGITUD")], {})
    assert revision.sin_veredicto == ["LONGITUD"]


def test_una_fila_OFRECIDA_que_el_modelo_no_tiene_se_nombra():
    revision = cat.revisar([_knob("LONGITUD")],
                           {"LONGITUD": _entrada("LONGITUD"),
                            "YA_NO_EXISTE": _entrada("YA_NO_EXISTE")})
    assert revision.sin_control == ["YA_NO_EXISTE"]


def test_una_fila_declarada_no_simulable_sin_knob_no_es_un_desajuste():
    """Medido sobre el archivo real: ocho filas -- CNT_VN, LONGITUD, X2, Y2,
    TIPO_TAX, CNT_TRF y las dos FECHA_OPERACION -- estan ahi con veredicto `No` o
    `Limitado` y el modelo no les construye ningun control. Es lo correcto, no un
    desajuste: marcarlas serian ocho falsas alarmas permanentes, que es como un
    informe deja de leerse."""
    revision = cat.revisar(
        [_knob("LONGITUD")],
        {"LONGITUD": _entrada("LONGITUD"),
         "X2": _entrada("X2", veredicto="No"),
         "CNT_VN": _entrada("CNT_VN", veredicto="Limitado")})
    assert revision.sin_control == []


def test_sin_desajustes_las_tres_listas_quedan_vacias():
    revision = cat.revisar([_knob("LONGITUD")], {"LONGITUD": _entrada("LONGITUD")})
    assert not revision.incoherencias
    assert not revision.sin_veredicto
    assert not revision.sin_control


# ------------------------------------------------ un selector sobre una variable numerica

def test_una_opcion_numerica_fuera_del_rango_del_modelo_se_nombra():
    """El hueco que abrio `CAPACIDAD_NOMINAL` al pasar de `numeric` a selector.

    `incoherencias_del_catalogo` solo mira los knobs CATEGORICOS: compara la lista del
    archivo contra las categorias que el codificador conoce. Una variable que el modelo
    ve como NUMERO -- kVA, metros, fases -- no tiene categorias que comparar, asi que su
    lista de valores no se contrastaba contra nada. Pedirle al modelo un valor que nunca
    vio en el entrenamiento es extrapolar, y el panel no lo diria.
    """
    revision = cat.revisar(
        [_knob("CAPACIDAD_NOMINAL", kind="numeric", bounds=(0.0, 400.0))],
        {"CAPACIDAD_NOMINAL": _entrada("CAPACIDAD_NOMINAL", tipo="categorical",
                                       opciones=("50", "300", "630"))})
    assert revision.fuera_de_rango, "630 kVA esta fuera de lo que el modelo vio"
    aviso = revision.fuera_de_rango[0]
    assert "CAPACIDAD_NOMINAL" in aviso and "630" in aviso
    assert "400" in aviso, "el aviso tiene que decir contra que rango se juzgo"


def test_las_opciones_dentro_del_rango_no_avisan():
    revision = cat.revisar(
        [_knob("CAPACIDAD_NOMINAL", kind="numeric", bounds=(0.0, 400.0))],
        {"CAPACIDAD_NOMINAL": _entrada("CAPACIDAD_NOMINAL", tipo="categorical",
                                       opciones=("0.5", "50", "300"))})
    assert revision.fuera_de_rango == []


def test_un_selector_de_texto_no_se_juzga_por_rango():
    """`CONDUCTOR` es categorico de verdad: sus opciones no son numeros y el rango no
    significa nada. Lo suyo lo mira `incoherencias`."""
    revision = cat.revisar(
        [_knob("CONDUCTOR", kind="categorical", categories=("ACSR", "AAAC"))],
        {"CONDUCTOR": _entrada("CONDUCTOR", tipo="categorical",
                               opciones=("ACSR", "AAAC"))})
    assert revision.fuera_de_rango == []


def test_una_opcion_fuera_de_rango_sale_distinto_de_cero():
    con_falla = cat.Revision(filas=[], incoherencias=[], sin_veredicto=[],
                             sin_control=[], fuera_de_rango=["algo"])
    assert cat.codigo_de_salida(con_falla) == 1


# ------------------------------------------------------------------ lo que se imprime

def test_el_informe_nombra_cada_control_y_su_veredicto():
    revision = cat.revisar([_knob("CNT_FASES")],
                           {"CNT_FASES": _entrada("CNT_FASES", tipo="int")})
    texto = cat.informe(revision)
    assert "CNT_FASES" in texto
    assert "deslizador-entero" in texto


def test_el_json_trae_una_fila_por_control():
    revision = cat.revisar([_knob("LONGITUD")], {"LONGITUD": _entrada("LONGITUD")})
    volcado = json.loads(json.dumps(revision.como_dict()))
    assert volcado["filas"][0]["knob_id"] == "LONGITUD"
    assert volcado["filas"][0]["control"] == "deslizador"
    assert volcado["incoherencias"] == []


def test_una_incoherencia_sale_distinto_de_cero():
    con_falla = cat.Revision(filas=[], incoherencias=["algo"], sin_veredicto=[],
                             sin_control=[])
    sin_falla = cat.Revision(filas=[], incoherencias=[], sin_veredicto=[], sin_control=[])
    assert cat.codigo_de_salida(con_falla) == 1
    assert cat.codigo_de_salida(sin_falla) == 0
