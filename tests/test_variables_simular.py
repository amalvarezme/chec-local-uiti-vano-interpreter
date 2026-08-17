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
    fases o un nivel de riesgo por vegetacion de 37,42: un escenario que no existe y
    que el modelo puntua igual, sin avisar de nada.

    Cuales son enteras no se opina, se MIDE. Sobre las 159.470 filas del dataset, las
    seis que el archivo declara `int` toman unicamente valores enteros y su rango real
    coincide EXACTAMENTE con el declarado: `NR_T` 0-116, `VAL_CRIT_APOYO` 1-10,
    `CNT_VN` 1-120, `CNT_TRF` 1-401 y las dos fechas de operacion 1950-2026.

    ## Dos vueltas de esta prueba, y por que

    Nacio exigiendo `selector` con lista cerrada para ALTURA, CANTIDAD_TIERRA,
    LONG_CRUCETA y NG_RED. Se cambio a deslizador de enteros con el argumento de que la
    base trae 20 alturas distintas entre 4 y 25 m, no las tres del inventario.

    El archivo volvio a la lista cerrada, y esta vez es una decision tomada a la vista
    del dato: `ALTURA` ofrece 12|16|18 y `LONG_CRUCETA` sus 19 valores, sabiendo que la
    base tiene mas. Ofrecer solo los apoyos que se compran es una restriccion del
    INVENTARIO, no un desacuerdo con la medicion. Lo que esta prueba fija ya no es cual
    de las dos formas es correcta -- eso lo decide el archivo -- sino que la forma
    elegida se respete: con lista, selector; sin lista y entera, deslizador de enteros.
    """
    catalogo = catalogo_simulacion(RUTA_REAL)

    # Sin lista y declaradas enteras: deslizador de enteros, con rango entero. Si `vmin`
    # trajera decimales, `IntSlider(min=int(vmin))` recortaria el limite sin decirlo.
    enteras = ("NR_T", "VAL_CRIT_APOYO", "CNT_VN", "CNT_TRF",
               "FECHA_OPERACION_TRF", "FECHA_OPERACION_VANO")
    for nombre in enteras:
        assert catalogo[nombre].tipo == "int", nombre
        assert catalogo[nombre].control == "deslizador-entero", nombre
        assert float(catalogo[nombre].vmin).is_integer(), nombre
        assert float(catalogo[nombre].vmax).is_integer(), nombre
        assert not catalogo[nombre].opciones, nombre

    # Con lista: selector, sea la lista de numeros o de texto.
    con_lista = ("ALTURA", "CANTIDAD_TIERRA", "CNT_FASES", "NG_RED", "LONG_CRUCETA",
                 "CONDUCTOR", "TIPO", "TIPO_TAX", "CALIBRE_NEUTRO")
    for nombre in con_lista:
        assert catalogo[nombre].opciones, nombre
        assert catalogo[nombre].control == "selector", nombre

    # Continuas de verdad: el dato tiene decimales y no hay lista que lo cierre.
    for nombre in ("CAPACIDAD_NOMINAL", "DDT", "LONGITUD", "PROMEDIO_KWH_VANO"):
        assert catalogo[nombre].control == "deslizador", nombre


def test_ninguna_lista_cerrada_del_archivo_trae_una_opcion_vacia():
    """`LONG_CRUCETA` se escribe `0|0.4|...|9|`, con la barra final colgando.

    Una opcion vacia en un `Dropdown` es una entrada seleccionable que no significa
    nada y que, elegida, manda `''` al codificador.
    """
    catalogo = catalogo_simulacion(RUTA_REAL)

    for variable in catalogo.values():
        assert all(o.strip() for o in variable.opciones), variable.variable


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


def test_el_valor_que_sale_de_cada_control_llega_al_modelo_sin_deformarse():
    """El ultimo tramo: del widget a la columna de la matriz de instancias.

    Tres formas de valor conviven, y cada una tiene su via:

    * el deslizador de enteros entrega un `int` de Python;
    * el selector de opciones numericas entrega un `float` -- por eso viaja como
      `(etiqueta, valor)` y no como la cadena "12";
    * el selector de texto entrega la categoria, que el codificador del modelo tiene
      que convertir en su indice.

    Medido contra el modelo real: `NR_T` 0 y 116 llegan como 0,0 y 116,0 exactos;
    `ALTURA` 12 llega como 12,0; `CONDUCTOR` "2-ACSR-CUBIERTO" llega como 5,0 y `TIPO`
    "1CC" como 0,0. Ninguna deriva, ninguna excepcion.
    """
    pytest.importorskip("torch")
    from pathlib import Path

    from chec_local_interpreter.config import (
        DEFAULT_DATA_PATH,
        DEFAULT_VARIABLES_SELECCION_PATH,
    )
    from chec_local_interpreter.mil_inferencia import catalogo_de_controles
    from chec_local_interpreter.simulator import _coerce_original_value_for_model

    if not Path(DEFAULT_DATA_PATH).exists():
        pytest.skip("el dataset no esta en esta copia")

    controles = catalogo_de_controles(Path(DEFAULT_DATA_PATH),
                                      Path(DEFAULT_VARIABLES_SELECCION_PATH))
    codificadores = dict(controles.label_encoders or {})
    maximos = dict(controles.max_values_imputed or {})
    catalogo = catalogo_simulacion(RUTA_REAL)
    conocidos = {k.id for k in controles.knobs}

    for entrada in catalogo.values():
        if entrada.knob_id not in conocidos or entrada.knob_id.startswith("clima:"):
            continue
        if entrada.control == "selector":
            muestras = (list(entrada.valores_numericos) if entrada.opciones_numericas
                        else list(entrada.opciones))
        elif entrada.control == "deslizador-entero":
            muestras = [int(entrada.vmin), int(entrada.vmax)]
        else:
            muestras = [float(entrada.vmin), float(entrada.vmax)]

        for valor in muestras:
            convertido = _coerce_original_value_for_model(
                entrada.knob_id, valor,
                label_encoders=codificadores, max_values_imputed=maximos)
            assert isinstance(convertido, (int, float)), (entrada.knob_id, valor)
            assert convertido == convertido, (entrada.knob_id, valor)  # nunca NaN
            if isinstance(valor, (int, float)) and not isinstance(valor, bool):
                # Los numeros no pasan por el codificador: tienen que llegar IGUALES.
                assert float(convertido) == pytest.approx(float(valor)), (
                    f"{entrada.knob_id}: el control entrega {valor} y al modelo le "
                    f"llega {convertido}")


def test_las_listas_cerradas_son_de_INVENTARIO_y_por_eso_son_mas_cortas_que_el_dato():
    """Tres listas ofrecen menos de lo que hay en la red, y una ofrece algo que no hay.
    Las cuatro cosas son deliberadas, decididas el 2026-08-17 mirando el cotejo.

    Sin esta prueba el desajuste se vuelve a encontrar cada vez que alguien cruce el
    archivo con el dataset, y se "arregla" -- que es justo lo que no hay que hacer.

    ## Lo medido sobre las 159.470 filas

    * `ALTURA` ofrece 12 | 16 | 18. La red tiene 20 alturas mas, entre 4 y 25 m, ademas
      de un 99 que huele a centinela de dato faltante. La lista es el INVENTARIO DE
      COMPRA: los apoyos que la empresa instala. Ofrecer un apoyo de 21 m porque exista
      uno viejo seria proponer una obra que nadie va a contratar.
    * `CONDUCTOR` deja fuera 13 tipos presentes -- `1/0-AL-DESNUDO`, `6-CU-DESNUDO`,
      `556.5-AL-AISLADO`... -- que son legado y no se vuelven a montar.
    * `TIPO` deja fuera `3IG` y `3RG`, por lo mismo.
    * `LONG_CRUCETA` ofrece 4,5 | 5,2 | 7,6 | 8 m, que HOY no existen en ninguna vano de
      la base. Son crucetas que se compran; simularlas es una pregunta de diseno legitima
      y la extrapolacion se asume a sabiendas.

    Lo que si es contrato duro y esta en
    `test_ninguna_categoria_ofrecida_es_desconocida_para_el_modelo`: que el codificador
    del modelo sepa convertir todo lo que se ofrece. Ofrecer de menos es una decision;
    ofrecer algo que el modelo no sabe codificar es un fallo en mitad de una simulacion.
    """
    catalogo = catalogo_simulacion(RUTA_REAL)

    assert catalogo["ALTURA"].opciones == ("12", "16", "18")
    assert len(catalogo["CONDUCTOR"].opciones) == 17
    assert len(catalogo["TIPO"].opciones) == 10
    assert "3IG" not in catalogo["TIPO"].opciones
    for fuera_de_la_base in ("4.5", "5.2", "7.6", "8"):
        assert fuera_de_la_base in catalogo["LONG_CRUCETA"].opciones


# --------------------------------------------------------------------------------
# El DIAGNOSTICO tiene que proponer lo mismo que el panel deja ejecutar
# --------------------------------------------------------------------------------
def test_los_candidatos_del_diagnostico_salen_del_panel_y_no_del_dato_crudo():
    """El ajuste del archivo no llegaba al diagnostico, y ese es el defecto de fondo.

    `candidatos_de_knob` recorre `knob.bounds` y `knob.categories`, que son lo OBSERVADO
    en la base. El panel, en cambio, ofrece lo que declara `Variables_simular.xlsx`. Con
    el archivo ajustado los dos dejaron de coincidir, y el ranking pasaba a recomendar
    obra que el propio panel no deja pedir. Medido sobre los once controles de
    intervencion:

        ALTURA           proponia 4 | 6,625 | 9,25 ... 25      el panel ofrece 12 | 16 | 18
        CNT_FASES        proponia 1 | 1,25 | 1,5 | 1,75 ...    el panel ofrece 1 | 2 | 3
        CANTIDAD_TIERRA  proponia 0 | 0,125 | 0,25 ...         el panel ofrece 0 | 1
        NG_RED           proponia 0 | 0,125 | 0,25 ...         el panel ofrece 0 | 1
        NR_T             proponia 14,5 | 43,5 | 72,5           la columna es entera
        VAL_CRIT_APOYO   proponia 2,125 | 4,375 | 6,625        la columna es entera
        CONDUCTOR        proponia 30 categorias                el panel ofrece 17
        TIPO             proponia 12                           el panel ofrece 10
        LONG_CRUCETA     proponia una rejilla de 9             el panel ofrece 19 reales

    O sea: recomendaba "2,37 fases" y "media puesta a tierra" -- justo lo que el control
    entero existe para impedir -- y a la vez se perdia las 19 longitudes de cruceta que
    si estan en el contrato.
    """
    from chec_local_interpreter.simulador_variables import candidatos_del_panel

    catalogo = catalogo_simulacion(RUTA_REAL)

    # Lista cerrada de numeros: los tres del inventario, no una rejilla.
    altura = candidatos_del_panel(_knob("ALTURA", "numeric", bounds=(4.0, 25.0)),
                                  catalogo["ALTURA"])
    assert altura == [12.0, 16.0, 18.0]

    # Entera de rango corto: TODOS sus enteros, no nueve puntos con decimales.
    val = candidatos_del_panel(_knob("VAL_CRIT_APOYO", "numeric", bounds=(1.0, 10.0)),
                               catalogo["VAL_CRIT_APOYO"])
    assert val == [float(v) for v in range(1, 11)]

    # Entera de rango largo: una rejilla, pero de ENTEROS.
    nr_t = candidatos_del_panel(_knob("NR_T", "numeric", bounds=(0.0, 116.0)),
                               catalogo["NR_T"])
    assert nr_t, "NR_T se quedo sin candidatos"
    assert all(float(v).is_integer() for v in nr_t), nr_t
    assert min(nr_t) == 0.0 and max(nr_t) == 116.0

    # Continua de verdad: rejilla sobre el rango del ARCHIVO.
    cap = candidatos_del_panel(_knob("CAPACIDAD_NOMINAL", "numeric", bounds=(0.0, 999.0)),
                              catalogo["CAPACIDAD_NOMINAL"])
    assert max(cap) == pytest.approx(400.0), "uso el rango observado y no el declarado"


def test_una_categorica_se_limita_a_lo_que_el_modelo_sabe_codificar():
    """La interseccion, igual que en el panel: una categoria que el codificador no
    conoce falla en mitad de una simulacion."""
    from chec_local_interpreter.simulador_variables import candidatos_del_panel

    catalogo = catalogo_simulacion(RUTA_REAL)
    knob = _knob("TIPO", "categorical", categories=("1CC", "1CFR", "3IG"))

    assert candidatos_del_panel(knob, catalogo["TIPO"]) == ["1CC", "1CFR"]


def test_un_knob_sin_entrada_en_el_archivo_conserva_sus_candidatos_de_siempre():
    """Las cuatro familias climaticas y cualquier control nuevo: sin veredicto no hay
    restriccion que aplicar, y quedarse sin candidatos lo sacaria del ranking."""
    from chec_local_interpreter.mil_simulador_015 import candidatos_de_knob
    from chec_local_interpreter.simulador_variables import candidatos_del_panel

    knob = _knob("INVENTADO", "numeric", bounds=(0.0, 8.0))

    assert candidatos_del_panel(knob, None) == candidatos_de_knob(knob, puntos=9)
