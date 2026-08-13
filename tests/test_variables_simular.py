"""Pruebas del catalogo de variables a simular leido de `Variables_simular.xlsx`.

Hasta ahora, QUE variables se pueden simular y COMO se presentan vivian en dos sitios
distintos y ninguno era un archivo del proyecto: los veredictos estaban escritos a mano
en `simulador_variables.JUICIO_SIMULACION`, y la forma del control la decidia
`vano_widgets` mirando solo si el knob era numerico o categorico. Eso deja dos
problemas:

1. Cambiar un veredicto exigia editar codigo Python, cuando es una decision del negocio.
2. Una variable numerica con tres valores posibles -- la altura del apoyo, que en la
   practica es 12, 16 o 18 metros -- se ofrecia como un deslizador continuo entre 4 y
   25, invitando a simular un apoyo de 17,3 m que no existe en el inventario.

`data/Variables_simular.xlsx` resuelve las dos: trae el veredicto, el motivo, el rango,
la unidad y -- cuando corresponde -- la lista cerrada de valores posibles. Estas pruebas
fijan que el catalogo salga de ahi y que el tipo de control se derive de esa lista.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from chec_local_interpreter.simulador_variables import (
    catalogo_simulacion,
    incoherencias_del_catalogo,
    tabla_variables_simulables,
)
from chec_local_interpreter.vano_controls import Knob

RUTA_REAL = Path(__file__).resolve().parents[1] / "data" / "Variables_simular.xlsx"


# --------------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------------
def _hoja(filas: list[dict]) -> pd.DataFrame:
    columnas = ["Variable", "Controla", "Tipo", "vmin", "vmax", "Unidad", "Opciones",
                "Sentido de simular", "Por que"]
    return pd.DataFrame(filas, columns=columnas)


def _escribir(tmp_path: Path, filas: list[dict]) -> Path:
    destino = tmp_path / "Variables_simular.xlsx"
    _hoja(filas).to_excel(destino, sheet_name="Variables a simular ajustado", index=False)
    return destino


def _knob(id_: str, kind: str, *, label: str | None = None,
          bounds=None, categories=None, n_feats: int = 1) -> Knob:
    return Knob(
        id=id_, label=label or id_, kind=kind,
        feature_names=tuple(f"{id_}_{i}" for i in range(n_feats)),
        bounds=bounds, categories=categories, default=None, step=None,
    )


# --------------------------------------------------------------------------------
# El catalogo sale del archivo
# --------------------------------------------------------------------------------
def test_el_catalogo_lee_las_26_variables_del_archivo_real():
    """El archivo del proyecto es la fuente, no una lista escrita en el codigo."""
    catalogo = catalogo_simulacion(RUTA_REAL)
    assert len(catalogo) == 26
    # Una de cada tipo, para que la prueba falle si el archivo pierde una columna.
    assert catalogo["NR_T"].veredicto == "Si -- intervencion"
    assert catalogo["NR_T"].vmax == pytest.approx(116.0)
    assert catalogo["DDT"].veredicto == "Si -- escenario"
    assert catalogo["X2"].veredicto == "No"
    assert catalogo["CNT_VN"].veredicto == "Limitado"


def test_las_familias_climaticas_se_indexan_por_el_id_del_knob():
    """El Excel las nombra `Precipitacion (12 lags)` y el knob se llama `clima:prep`.

    Sin esta traduccion las cuatro familias climaticas quedarian fuera del catalogo y
    el panel las trataria como `Sin evaluar`, que es justo lo contrario de lo que dice
    el archivo.
    """
    catalogo = catalogo_simulacion(RUTA_REAL)
    for knob_id in ("clima:prep", "clima:temp", "clima:wind_gust_spd", "clima:wind_spd"):
        assert knob_id in catalogo, f"falta {knob_id}"
        assert catalogo[knob_id].veredicto == "Si -- escenario"
        assert catalogo[knob_id].controla == 12


def test_un_archivo_que_no_existe_falla_diciendo_cual(tmp_path):
    """Devolver un catalogo vacio dejaria el panel sin una sola variable simulable y
    sin decir por que. Falla, y con la ruta."""
    with pytest.raises(FileNotFoundError, match="Variables_simular"):
        catalogo_simulacion(tmp_path / "no_existe.xlsx")


def test_una_hoja_sin_las_columnas_esperadas_falla(tmp_path):
    destino = tmp_path / "Variables_simular.xlsx"
    pd.DataFrame({"Cosa": [1]}).to_excel(
        destino, sheet_name="Variables a simular ajustado", index=False)
    with pytest.raises(ValueError, match="columnas"):
        catalogo_simulacion(destino)


# --------------------------------------------------------------------------------
# Deslizador o selector: la decision sale del archivo
# --------------------------------------------------------------------------------
def test_una_variable_con_opciones_se_presenta_como_selector(tmp_path):
    """Aunque el knob sea numerico. `ALTURA` es el caso real: el modelo la ve como un
    numero entre 4 y 25, pero el inventario solo tiene apoyos de 12, 16 y 18 metros."""
    ruta = _escribir(tmp_path, [
        {"Variable": "ALTURA", "Controla": 1, "Tipo": "categorical", "vmin": 4, "vmax": 25,
         "Unidad": "m", "Opciones": "12|16|18",
         "Sentido de simular": "Si -- intervencion", "Por que": "..."},
    ])
    entrada = catalogo_simulacion(ruta)["ALTURA"]
    assert entrada.control == "selector"
    assert entrada.opciones == ("12", "16", "18")
    assert entrada.opciones_numericas is True


def test_una_variable_entera_se_presenta_como_deslizador_de_enteros(tmp_path):
    """`CNT_FASES` va de 1 a 3 fases. Un deslizador continuo ofreceria 2,37 fases."""
    ruta = _escribir(tmp_path, [
        {"Variable": "CNT_FASES", "Controla": 1, "Tipo": "numeric-entero",
         "vmin": 1, "vmax": 3, "Unidad": "fases", "Opciones": None,
         "Sentido de simular": "Si -- intervencion", "Por que": "..."},
    ])
    entrada = catalogo_simulacion(ruta)["CNT_FASES"]
    assert entrada.control == "deslizador-entero"
    assert entrada.opciones == ()


def test_una_variable_continua_se_presenta_como_deslizador(tmp_path):
    ruta = _escribir(tmp_path, [
        {"Variable": "DDT", "Controla": 1, "Tipo": "numeric", "vmin": 0, "vmax": 657.6,
         "Unidad": "", "Opciones": None,
         "Sentido de simular": "Si -- escenario", "Por que": "..."},
    ])
    entrada = catalogo_simulacion(ruta)["DDT"]
    assert entrada.control == "deslizador"


def test_las_opciones_de_texto_no_se_confunden_con_numeros(tmp_path):
    ruta = _escribir(tmp_path, [
        {"Variable": "TIPO_TAX", "Controla": 1, "Tipo": "categorical", "vmin": None,
         "vmax": None, "Unidad": None, "Opciones": "Ramal | Troncal_linea",
         "Sentido de simular": "Limitado", "Por que": "..."},
    ])
    entrada = catalogo_simulacion(ruta)["TIPO_TAX"]
    assert entrada.control == "selector"
    assert entrada.opciones == ("Ramal", "Troncal_linea")
    assert entrada.opciones_numericas is False


def test_el_archivo_real_no_ofrece_ningun_deslizador_continuo_sobre_una_variable_entera():
    """Un deslizador continuo sobre una variable que solo toma enteros ofrece 2,37
    fases o media puesta a tierra: un escenario que no existe y que el modelo puntua
    igual, sin avisar de nada.

    Cuales son enteras no se opina, se MIDE sobre la matriz de instancias del modelo
    (288.632 filas): estas diez toman unicamente valores enteros. `LONG_CRUCETA`
    (0,4 | 2,3 | 3,5 m) y `CAPACIDAD_NOMINAL` (0,5 | 37,5 kVA) no, y por eso siguen
    siendo continuas -- la regla es la evidencia, no el nombre de la variable.

    Sustituye a una prueba que exigia `selector` con lista cerrada para ALTURA,
    CANTIDAD_TIERRA, LONG_CRUCETA y NG_RED. Esa lista la contradicen los datos: la
    base trae 20 alturas distintas entre 4 y 25 m, no las tres del inventario que el
    archivo viejo declaraba.
    """
    catalogo = catalogo_simulacion(RUTA_REAL)
    enteras = ("ALTURA", "CANTIDAD_TIERRA", "CNT_FASES", "NG_RED", "NR_T",
               "VAL_CRIT_APOYO", "CNT_VN", "CNT_TRF", "FECHA_OPERACION_TRF",
               "FECHA_OPERACION_VANO")
    for nombre in enteras:
        assert catalogo[nombre].control == "deslizador-entero", nombre
        # Y su rango declarado tiene que ser entero, o `IntSlider(min=int(vmin))`
        # recortaria el limite sin decirlo.
        assert float(catalogo[nombre].vmin).is_integer(), nombre
        assert float(catalogo[nombre].vmax).is_integer(), nombre
    for nombre in ("LONG_CRUCETA", "CAPACIDAD_NOMINAL", "DDT", "LONGITUD"):
        assert catalogo[nombre].control == "deslizador", nombre


# --------------------------------------------------------------------------------
# Coherencia con lo que el modelo sabe codificar
# --------------------------------------------------------------------------------
def test_una_opcion_que_el_modelo_no_sabe_codificar_se_reporta(tmp_path):
    """El caso real es `CALIBRE_NEUTRO`: el archivo propone valores de CONDUCTOR.

    Ofrecerlos igual produciria un fallo de codificacion en mitad de una simulacion, o
    peor, un valor mal codificado sin aviso. El catalogo los detecta contra las
    categorias que el knob si conoce.
    """
    ruta = _escribir(tmp_path, [
        {"Variable": "CALIBRE_NEUTRO", "Controla": 1, "Tipo": "categorical", "vmin": None,
         "vmax": None, "Unidad": None, "Opciones": "2-ACSR-CUBIERTO|1/0-ACSR-DESNUDO",
         "Sentido de simular": "Si -- intervencion", "Por que": "..."},
    ])
    catalogo = catalogo_simulacion(ruta)
    knob = _knob("CALIBRE_NEUTRO", "categorical", categories=("0", "1/0", "1/4"))

    avisos = incoherencias_del_catalogo([knob], catalogo)
    assert len(avisos) == 1
    assert "CALIBRE_NEUTRO" in avisos[0]
    assert "2-ACSR-CUBIERTO" in avisos[0]


def test_sin_incoherencias_no_hay_avisos(tmp_path):
    ruta = _escribir(tmp_path, [
        {"Variable": "TIPO_TAX", "Controla": 1, "Tipo": "categorical", "vmin": None,
         "vmax": None, "Unidad": None, "Opciones": "Ramal|Troncal_linea",
         "Sentido de simular": "Limitado", "Por que": "..."},
    ])
    knob = _knob("TIPO_TAX", "categorical", categories=("Ramal", "Troncal_linea", "Otro"))
    assert incoherencias_del_catalogo([knob], catalogo_simulacion(ruta)) == []


def test_el_archivo_real_ya_no_tiene_ninguna_incoherencia():
    """Fija el estado del archivo. Si aparece una, esta prueba lo dice en vez de que
    se descubra con una simulacion fallida.

    Las cuatro listas del archivo coinciden EXACTAMENTE con lo que el codificador del
    modelo sabe traducir. Las categorias de abajo no son un ejemplo: son las que trae
    `mil_vano_ventana_v1.pt` a traves de su catalogo de knobs -- 30 conductores, 20
    calibres, 12 tipos de apoyo y 6 taxonomias --, comprobadas contra el modelo real.
    Se escriben aqui y no se cargan del artefacto porque el modelo y su paquete son
    binarios de varios megabytes que no viajan con las pruebas.

    Antes esta prueba fijaba UNA incoherencia conocida en `CALIBRE_NEUTRO`. El archivo
    ajustado la corrigio, asi que lo que se fija ahora es la ausencia: cualquier opcion
    nueva que el modelo no sepa codificar vuelve a poner esta prueba en rojo.
    """
    catalogo = catalogo_simulacion(RUTA_REAL)
    knobs = [
        _knob("CALIBRE_NEUTRO", "categorical",
              categories=("0", "1/0", "1/4", "10", "11", "134.6", "2", "2/0", "250",
                          "266.8", "3/0", "3/8", "336.4", "350", "4", "4/0", "500",
                          "6", "795", "OPGW")),
        _knob("CONDUCTOR", "categorical",
              categories=("1/0-ACSR-CUBIERTO", "1/0-ACSR-DESNUDO", "1/0-AL-AISLADO",
                          "1/0-AL-DESNUDO", "1/0-CU-AISLADO", "2-ACSR-CUBIERTO",
                          "2-ACSR-DESNUDO", "2-AL-AISLADO", "2-AL-DESNUDO",
                          "2-CU-AISLADO", "2/0-ACSR-CUBIERTO", "2/0-ACSR-DESNUDO",
                          "2/0-AL-AISLADO", "2/0-CU-AISLADO", "250-AL-AISLADO",
                          "266.8-ACSR-DESNUDO", "3/0-ACSR-DESNUDO",
                          "336.4-ACSR-DESNUDO", "350-AL-AISLADO", "350-CU-AISLADO",
                          "4-ACSR-DESNUDO", "4/0-ACSR-CUBIERTO", "4/0-ACSR-DESNUDO",
                          "4/0-AL-AISLADO", "4/0-CU-AISLADO", "500-CU-AISLADO",
                          "556.5-AL-AISLADO", "6-ACSR-DESNUDO", "6-CU-DESNUDO",
                          "8-CU-DESNUDO")),
        _knob("TIPO", "categorical",
              categories=("1CC", "1CFR", "2CC", "2CFR", "2CR", "2RL", "3CC", "3CFR",
                          "3CR", "3IG", "3RG", "3RL")),
        _knob("TIPO_TAX", "categorical",
              categories=("Ramal", "Ramal_propuesto", "Troncal_linea",
                          "Troncal_propuesta", "Troncal_ramal",
                          "Troncal_ramal_propuesto")),
    ]
    assert incoherencias_del_catalogo(knobs, catalogo) == []


# --------------------------------------------------------------------------------
# La tabla del cuaderno
# --------------------------------------------------------------------------------
def test_la_tabla_toma_rango_unidad_y_motivo_del_archivo(tmp_path):
    """Antes vmin/vmax salian de los limites observados del knob y la unidad de un
    diccionario en el codigo. Ahora los tres salen del mismo archivo, que es lo que
    impide que la tabla y el control digan cosas distintas."""
    ruta = _escribir(tmp_path, [
        {"Variable": "NR_T", "Controla": 1, "Tipo": "numeric-entero", "vmin": 0,
         "vmax": 116, "Unidad": "indice", "Opciones": None,
         "Sentido de simular": "Si -- intervencion", "Por que": "bajarlo ES la poda"},
    ])
    knob = _knob("NR_T", "numeric", bounds=(0.0, 999.0))

    tabla = tabla_variables_simulables([knob], catalogo=catalogo_simulacion(ruta))
    fila = tabla.iloc[0]
    assert fila["Variable"] == "NR_T"
    assert fila["vmax"] == pytest.approx(116.0)  # del archivo, no del knob (999)
    assert fila["Unidad"] == "indice"
    assert fila["Por que"] == "bajarlo ES la poda"
    assert fila["Control"] == "deslizador-entero"


def test_un_knob_que_el_archivo_no_menciona_sale_como_sin_evaluar(tmp_path):
    """Una feature nueva del modelo no puede aparecer como una palanca mas sin que
    nadie la haya revisado."""
    ruta = _escribir(tmp_path, [
        {"Variable": "NR_T", "Controla": 1, "Tipo": "numeric", "vmin": 0, "vmax": 1,
         "Unidad": "", "Opciones": None, "Sentido de simular": "Si -- intervencion",
         "Por que": "..."},
    ])
    knobs = [_knob("NR_T", "numeric", bounds=(0.0, 1.0)),
             _knob("VARIABLE_NUEVA", "numeric", bounds=(0.0, 5.0))]
    tabla = tabla_variables_simulables(knobs, catalogo=catalogo_simulacion(ruta))
    nueva = tabla[tabla["Variable"] == "VARIABLE_NUEVA"].iloc[0]
    assert nueva["Sentido de simular"] == "Sin evaluar"


# --------------------------------------------------------------------------------
# El control que se construye de verdad
# --------------------------------------------------------------------------------
def _catalogo_de(tmp_path, filas):
    return catalogo_simulacion(_escribir(tmp_path, filas))


def test_una_lista_cerrada_de_numeros_produce_un_selector_no_un_deslizador(tmp_path):
    """El caso que motiva todo esto. `ALTURA` es numerica para el modelo, pero solo
    existen apoyos de 12, 16 y 18: el control tiene que ofrecer esos tres y nada mas."""
    import ipywidgets as widgets

    from chec_local_interpreter.vano_widgets import widget_for_knob

    catalogo = _catalogo_de(tmp_path, [
        {"Variable": "ALTURA", "Controla": 1, "Tipo": "categorical", "vmin": 4,
         "vmax": 25, "Unidad": "m", "Opciones": "12|16|18",
         "Sentido de simular": "Si -- intervencion", "Por que": "..."}])
    control = widget_for_knob(_knob("ALTURA", "numeric", bounds=(4.0, 25.0)),
                              catalogo=catalogo)

    assert isinstance(control, widgets.Dropdown)
    # Los valores viajan como NUMEROS: el modelo espera un numero, no la cadena "12".
    assert [v for _etiqueta, v in control.options] == [12.0, 16.0, 18.0]


def test_una_variable_entera_produce_un_deslizador_de_enteros(tmp_path):
    import ipywidgets as widgets

    from chec_local_interpreter.vano_widgets import widget_for_knob

    catalogo = _catalogo_de(tmp_path, [
        {"Variable": "CNT_FASES", "Controla": 1, "Tipo": "numeric-entero", "vmin": 1,
         "vmax": 3, "Unidad": "fases", "Opciones": None,
         "Sentido de simular": "Si -- intervencion", "Por que": "..."}])
    control = widget_for_knob(_knob("CNT_FASES", "numeric", bounds=(1.0, 3.0)),
                              catalogo=catalogo)

    assert isinstance(control, widgets.IntSlider)
    assert (control.min, control.max, control.step) == (1, 3, 1)


def test_el_deslizador_toma_los_limites_del_archivo_y_no_los_observados(tmp_path):
    """Si el archivo declara un rango, ese es el que se puede simular. Los limites del
    knob son los que se VIERON en los datos, que es otra cosa."""
    from chec_local_interpreter.vano_widgets import widget_for_knob

    catalogo = _catalogo_de(tmp_path, [
        {"Variable": "NR_T", "Controla": 1, "Tipo": "numeric", "vmin": 0, "vmax": 116,
         "Unidad": "", "Opciones": None, "Sentido de simular": "Si -- intervencion",
         "Por que": "..."}])
    control = widget_for_knob(_knob("NR_T", "numeric", bounds=(0.0, 999.0)),
                              catalogo=catalogo)
    assert control.max == pytest.approx(116.0)


def test_una_categorica_solo_ofrece_lo_que_el_modelo_sabe_codificar(tmp_path):
    """Las opciones del archivo que el codificador no conoce NO se ofrecen: elegir una
    romperia la simulacion, o la codificaria como otra cosa sin avisar."""
    from chec_local_interpreter.vano_widgets import widget_for_knob

    catalogo = _catalogo_de(tmp_path, [
        {"Variable": "CONDUCTOR", "Controla": 1, "Tipo": "categorical", "vmin": None,
         "vmax": None, "Unidad": None, "Opciones": "2-ACSR-DESNUDO|NO-EXISTE",
         "Sentido de simular": "Si -- intervencion", "Por que": "..."}])
    control = widget_for_knob(
        _knob("CONDUCTOR", "categorical", categories=("2-ACSR-DESNUDO", "4/0-AL-AISLADO")),
        catalogo=catalogo)
    assert list(control.options) == ["2-ACSR-DESNUDO"]


def test_un_knob_sin_entrada_en_el_archivo_conserva_el_control_de_siempre(tmp_path):
    """Una feature nueva no puede quedarse sin control: se le da el deslizador
    continuo de antes, y la tabla la marca como `Sin evaluar`."""
    import ipywidgets as widgets

    from chec_local_interpreter.vano_widgets import widget_for_knob

    catalogo = _catalogo_de(tmp_path, [
        {"Variable": "NR_T", "Controla": 1, "Tipo": "numeric", "vmin": 0, "vmax": 1,
         "Unidad": "", "Opciones": None, "Sentido de simular": "Si -- intervencion",
         "Por que": "..."}])
    control = widget_for_knob(_knob("NUEVA", "numeric", bounds=(0.0, 7.0)),
                              catalogo=catalogo)
    assert isinstance(control, widgets.FloatSlider)
    assert control.max == pytest.approx(7.0)
