"""RED/GREEN tests for `simulador_variables`, the catalogue behind notebook
06's "which variables are worth simulating" table.

The simulator answers ONE question: what happens to a vano's criticality if
this variable changes. Not every model feature can answer it. Some are
levers CHEC actually pulls (vegetation risk, grounding, conductor); some are
scenarios nobody controls but that are exactly the point of a what-if
(weather, lightning density, demand growth); some describe what the vano IS
rather than anything that could be done to it (its coordinates, its
taxonomy); and at least one is recorded AFTER the failure it would be used
to predict, which makes simulating it circular.

Leaving that distinction as prose in a markdown cell means every reader
re-derives it, and the panel happily offers all of them as if they were
equivalent. This module makes it data: one verdict per knob, joined against
the live knob catalogue so a feature added to the model without a verdict
fails loudly instead of quietly appearing as a legitimate lever.

Verdicts are grounded in `data/Variables_seleccion.xlsx`, the project's own
column dictionary, not in guesses from the variable names.
"""

from __future__ import annotations

import pandas as pd
import pytest

from chec_local_interpreter.simulador_variables import (
    JUICIO_SIMULACION,
    UNIDADES,
    VEREDICTOS,
    abreviatura,
    ancho_px,
    columnas_panel,
    definicion_de_knob,
    descripciones_de_variables,
    iniciales,
    knobs_bloqueados,
    knobs_simulables,
    rotulo_en_barra,
    SIN_EVALUAR,
    tabla_variables_simulables,
)
from chec_local_interpreter.vano_controls import Knob


def _knob(knob_id, kind="numeric", bounds=(0.0, 10.0), categories=None, label=None,
          feature_names=None):
    return Knob(
        id=knob_id,
        label=label or knob_id,
        kind=kind,
        feature_names=tuple(feature_names or (knob_id,)),
        bounds=bounds,
        categories=categories,
        default=None,
        step=None,
    )


def _catalogo(veredictos: dict) -> dict:
    """Un catalogo minimo `{knob_id: VariableSimulable}` para las pruebas de reparto."""
    from chec_local_interpreter.simulador_variables import VariableSimulable

    return {
        knob_id: VariableSimulable(
            knob_id=knob_id, variable=knob_id, controla=1, tipo="numeric",
            vmin=None, vmax=None, unidad="", opciones=(), veredicto=v, motivo="x")
        for knob_id, v in veredictos.items()
    }


def test_the_table_carries_the_declared_range_of_every_numeric_knob():
    """vmin/vmax come from `data/Variables_simular.xlsx`, not from the knob's
    observed bounds.

    This reverses an earlier decision, on purpose. The knob's bounds are what
    `build_knobs` SAW in the data; the file declares what is worth simulating,
    and the two are not the same question: `NR_T` reaches 116 in the file and a
    given selection of bags may only span 0 to 3. Reading the table from one
    source and the slider from another is exactly how they end up disagreeing,
    so both now read the file. A knob the file does not mention keeps its own
    bounds in the control and is reported as `Sin evaluar`.

    `Control` also comes from the file's `Tipo`: `NR_T` is declared
    `numeric-entero` -- every value it takes in the base is a whole number,
    measured over the 288.632 instances -- so the panel gives it an `IntSlider`.
    """
    tabla = tabla_variables_simulables([_knob("NR_T", bounds=(0.0, 3.0))])

    assert list(tabla.columns) == [
        "Variable", "Controla", "Tipo", "Control", "vmin", "vmax", "Unidad",
        "Opciones", "Sentido de simular", "Por que",
    ]
    fila = tabla.iloc[0]
    assert fila["Variable"] == "NR_T"
    # 116 es lo que declara el archivo; 3.0 era el limite observado del knob.
    assert (fila["vmin"], fila["vmax"]) == (0.0, 116.0)
    assert fila["Controla"] == 1
    assert fila["Control"] == "deslizador-entero"


def test_a_categorical_knob_reports_its_options_instead_of_a_range():
    """A range over a category code is meaningless -- the codes are labels,
    not magnitudes, so `vmin`/`vmax` would invite reading 2 as "twice 1".

    `TIPO_TAX` and not `NG_RED`: the file gives NG_RED a real 0..1 range,
    because it is a numeric flag presented as a closed selector. The variables
    that carry no range are the textual ones.
    """
    tabla = tabla_variables_simulables([
        _knob("TIPO_TAX", kind="categorical", bounds=None,
              categories=("Ramal", "Troncal_linea")),
    ])

    fila = tabla.iloc[0]
    assert pd.isna(fila["vmin"]) and pd.isna(fila["vmax"])
    assert fila["Opciones"] == "Ramal | Troncal_linea"


def test_a_climate_family_is_one_row_that_declares_its_twelve_lags():
    """A climate family is ONE control that moves 12 features at once, and the
    table has to say so: otherwise "Precipitacion" reads as a single feature
    and its weight in the model looks twelve times smaller than it is."""
    tabla = tabla_variables_simulables([
        _knob("clima:prep", label="Precipitacion (12 lags)", bounds=(0.0, 40.0),
              feature_names=tuple(f"prep_{i}" for i in range(12))),
    ])

    fila = tabla.iloc[0]
    assert fila["Controla"] == 12
    assert fila["Sentido de simular"] == "Si -- escenario"


def test_every_verdict_is_one_of_the_four_declared_levels():
    """Free-text verdicts drift into synonyms and stop being sortable. Four
    levels, and the reason column carries everything else."""
    assert set(VEREDICTOS) == {
        "Si -- intervencion", "Si -- escenario", "Limitado", "No",
    }
    for variable, (veredicto, motivo) in JUICIO_SIMULACION.items():
        assert veredicto in VEREDICTOS, variable
        assert motivo and motivo[0].isupper(), variable


def test_the_post_event_count_is_refused_as_circular():
    """`CNT_TRF` is, per the project's own dictionary, "cantidad de trafos
    afectados EN LA FALLA": it is measured after the failure the model is
    trying to anticipate. Offering it as a lever invites concluding that
    fewer affected transformers cause less criticality, which reverses the
    arrow of the whole analysis."""
    veredicto, motivo = JUICIO_SIMULACION["CNT_TRF"]

    assert veredicto == "No"
    assert "falla" in motivo.lower()


def test_the_coordinates_are_refused_because_they_are_identity():
    """Moving X2/Y2 does not correspond to any intervention, and it silently
    breaks the climate coupling: the weather series were fetched AT those
    coordinates, so a moved vano would keep another place's weather."""
    for variable in ("X2", "Y2"):
        veredicto, motivo = JUICIO_SIMULACION[variable]
        assert veredicto == "No", variable
        assert "clima" in motivo.lower(), variable


def test_vegetation_risk_is_the_lever_the_utility_actually_pulls():
    veredicto, _motivo = JUICIO_SIMULACION["NR_T"]

    assert veredicto == "Si -- intervencion"


def test_a_knob_without_a_verdict_is_reported_and_never_silently_allowed():
    """A feature added to the model must force a decision. Defaulting to
    "yes" would put an unvetted lever in the panel; defaulting to "no" would
    hide a real one. It is flagged instead, so the table itself shows the
    gap."""
    tabla = tabla_variables_simulables([_knob("VARIABLE_NUEVA")])

    fila = tabla.iloc[0]
    assert fila["Sentido de simular"] == "Sin evaluar"
    assert "sin veredicto" in fila["Por que"].lower()


def test_constant_knobs_are_left_out_of_the_table():
    """A constant knob has nothing to move -- one observed value, or a single
    category. The panel already hides them, and listing them here would pad
    the table with rows whose range is a point."""
    tabla = tabla_variables_simulables([
        _knob("FIJA", kind="constant", bounds=(2.0, 2.0)),
        _knob("NR_T", bounds=(0.0, 3.0)),
    ])

    assert list(tabla["Variable"]) == ["NR_T"]


def test_the_table_is_ordered_by_verdict_then_by_name():
    """The levers come first because they are what the panel is for; the
    refused ones last, where they read as a warning list."""
    tabla = tabla_variables_simulables([
        _knob("X2", bounds=(0.0, 1.0)),
        _knob("NR_T", bounds=(0.0, 3.0)),
        _knob("clima:temp", label="Temperatura (12 lags)", bounds=(0.0, 40.0),
              feature_names=tuple(f"temp_{i}" for i in range(12))),
    ])

    assert list(tabla["Sentido de simular"]) == [
        "Si -- intervencion", "Si -- escenario", "No",
    ]


def test_every_variable_the_project_selected_carries_a_verdict():
    """The dictionary is the contract: every column marked `SELECCION = 1` in
    `Variables_seleccion.xlsx` -- minus the target itself -- reaches the panel
    as a knob, so every one of them needs a verdict here. This is the test
    that fails when the project selects a new variable."""
    seleccionadas = {
        "CNT_VN", "CNT_TRF", "TIPO", "LONGITUD", "CNT_FASES", "CONDUCTOR",
        "CALIBRE_NEUTRO", "NG_RED", "FECHA_OPERACION_VANO", "X2", "Y2", "ALTURA",
        "CANTIDAD_TIERRA", "VAL_CRIT_APOYO", "CAPACIDAD_NOMINAL", "FECHA_OPERACION_TRF",
        "PROMEDIO_KWH_TRF", "TIPO_TAX", "NR_T", "LONG_CRUCETA", "PROMEDIO_KWH_VANO",
        "DDT", "clima:prep", "clima:temp", "clima:wind_gust_spd", "clima:wind_spd",
    }

    assert seleccionadas <= set(JUICIO_SIMULACION), seleccionadas - set(JUICIO_SIMULACION)
    # UITI_VANO es el OBJETIVO y no puede aparecer como palanca: simular el
    # objetivo es preguntarle al modelo por su propia respuesta.
    assert "UITI_VANO" not in JUICIO_SIMULACION


@pytest.mark.parametrize("variable", sorted(JUICIO_SIMULACION))
def test_no_verdict_is_left_without_a_reason_a_reader_can_check(variable):
    """The verdict alone is an opinion; the reason is what lets a CHEC
    engineer disagree with it on evidence."""
    _veredicto, motivo = JUICIO_SIMULACION[variable]

    assert len(motivo) > 25, variable


# --- Unidades de medida ---------------------------------------------------------------


def test_the_table_carries_a_unit_column():
    """Un rango sin unidad no se puede juzgar: 25 puede ser una altura razonable o
    un disparate segun si son metros o pies, y quien mueve el deslizador tiene que
    poder decidirlo sin ir a buscar el diccionario."""
    tabla = tabla_variables_simulables([_knob("ALTURA", bounds=(4.0, 25.0))])

    assert "Unidad" in tabla.columns
    assert tabla.iloc[0]["Unidad"] == "m"


def test_the_climate_units_are_the_ones_the_project_dictionary_states():
    """Las unicas cuatro con unidad ESCRITA en `Variables_seleccion.xlsx`. Se copian
    de ahi y no se deducen del nombre."""
    esperado = {
        "clima:prep": "mm",
        "clima:temp": "°C",
        "clima:wind_gust_spd": "km/h",
        "clima:wind_spd": "km/h",
    }

    for variable, unidad in esperado.items():
        assert UNIDADES[variable] == unidad, variable


def test_a_variable_without_a_meaningful_unit_leaves_the_cell_empty():
    """`NG_RED` es un si/no y `TIPO` una categoria: una unidad ahi seria ruido. El
    encargo pedia la columna "cuando aplique", y aplicar no es siempre."""
    tabla = tabla_variables_simulables([
        _knob("NG_RED", kind="categorical", bounds=None, categories=("Si", "No")),
    ])

    assert tabla.iloc[0]["Unidad"] == ""


def test_counts_declare_what_they_count_instead_of_a_physical_unit():
    tabla = tabla_variables_simulables([_knob("CNT_VN", bounds=(1.0, 120.0))])

    assert tabla.iloc[0]["Unidad"] == "vanos"


def test_no_declared_unit_is_invented_for_the_two_that_are_not_documented():
    """`DDT` es una densidad y su descripcion no dice sobre que area; el rango
    medido (0 a 658) no cuadra con la densidad de descargas por km2 y ano que se
    usa por norma. Antes que estampar una unidad equivocada en un tablero que van
    a leer ingenieros, la celda queda vacia."""
    assert "DDT" not in UNIDADES


def test_every_declared_unit_belongs_to_a_variable_that_exists():
    """Una unidad huerfana es una variable que se renombro y dejo su unidad atras,
    lista para pegarse a la siguiente que se llame igual."""
    assert set(UNIDADES) <= set(JUICIO_SIMULACION)


# --- Que llega al panel ----------------------------------------------------------------


def test_the_panel_only_offers_knobs_that_mean_something_to_simulate():
    """Las refutadas salen del panel. No es cosmetica: mientras esten ahi, el
    tablero las presenta como equivalentes a la poda o a la puesta a tierra, y
    alguien va a mover las coordenadas de un vano creyendo que eso es un
    escenario."""
    knobs = [_knob("NR_T"), _knob("X2"), _knob("CNT_TRF"), _knob("LONGITUD"),
             _knob("DDT")]

    ofrecidos = knobs_simulables(knobs)

    # NR_T es una obra y DDT un escenario. X2 y CNT_TRF estan refutadas; LONGITUD es
    # "Limitado" y tampoco se ofrece -- un deslizador no puede transmitir la condicion
    # bajo la cual esa lectura vale.
    assert [k.id for k in ofrecidos] == ["NR_T", "DDT"]


def test_the_removed_knobs_are_reported_so_the_panel_can_name_them():
    """Desaparecer sin decir nada se lee como que faltan. El panel las nombra y
    dice que conservan su valor observado."""
    knobs = [_knob("NR_T"), _knob("X2"), _knob("CNT_TRF"), _knob("LONGITUD")]

    bloqueados = knobs_bloqueados(knobs)

    assert [k.id for k in bloqueados] == ["CNT_TRF", "LONGITUD", "X2"]


def test_a_limited_knob_no_longer_reaches_the_panel():
    """El panel ofrece solo lo que se puede llevar a una decision: una obra
    (intervencion) o un escenario que se quiera anticipar. "Limitado" significa que
    hay UNA lectura bajo la cual se interpreta, y un deslizador no puede transmitir
    esa condicion -- quien lo mueve no ve el motivo, solo el numero. Siguen entrando
    a la simulacion con su valor observado; lo unico que se pierde es moverlas."""
    knobs = [_knob("FECHA_OPERACION_VANO"), _knob("LONGITUD"), _knob("TIPO_TAX")]

    assert knobs_simulables(knobs) == []
    assert len(knobs_bloqueados(knobs)) == 3


def test_an_unevaluated_knob_stays_in_the_panel_but_is_not_hidden():
    """Sin veredicto no hay motivo para quitarla, y quitarla en silencio ocultaria
    justo el caso que hay que revisar. La tabla ya la marca "Sin evaluar"."""
    assert len(knobs_simulables([_knob("VARIABLE_NUEVA")])) == 1


# --- Las cuatro columnas del selector de variables --------------------------------------


def test_the_panel_is_laid_out_as_four_columns_two_per_group():
    """Dos columnas para lo que se puede hacer y dos para lo que se quiere
    anticipar. Una lista corrida de 18 casillas obliga a leer el veredicto de cada
    una para saber en cual de las dos preguntas esta; en columnas, la posicion ya
    lo dice."""
    knobs = [_knob(f"I{i}") for i in range(5)] + [_knob(f"E{i}") for i in range(3)]
    juicio = _catalogo({f"I{i}": "Si -- intervencion" for i in range(5)}
                       | {f"E{i}": "Si -- escenario" for i in range(3)})

    columnas = columnas_panel(knobs, catalogo=juicio)

    assert len(columnas) == 4
    assert [len(k) for _titulo, k in columnas] == [3, 2, 2, 1]
    assert [k.id for k in columnas[0][1]] == ["I0", "I1", "I2"]
    assert [k.id for k in columnas[1][1]] == ["I3", "I4"]
    assert [k.id for k in columnas[2][1]] == ["E0", "E1"]
    assert [k.id for k in columnas[3][1]] == ["E2"]


def test_the_first_column_of_each_group_carries_its_name():
    knobs = [_knob("I0"), _knob("E0")]
    juicio = _catalogo({"I0": "Si -- intervencion", "E0": "Si -- escenario"})

    titulos = [t for t, _k in columnas_panel(knobs, catalogo=juicio)]

    assert titulos[0].startswith("Intervencion")
    assert titulos[2].startswith("Escenario")
    # La segunda columna de cada grupo NO repite el nombre como si fuera otro grupo.
    assert "cont" in titulos[1].lower() or titulos[1] == ""
    assert "cont" in titulos[3].lower() or titulos[3] == ""


def test_the_split_puts_the_bigger_half_first_so_columns_stay_even():
    """Con 11 controles, 6 y 5 -- no 5 y 6. Una columna mas corta a la izquierda
    deja un escalon que se lee como si faltara algo."""
    knobs = [_knob(f"I{i}") for i in range(11)]
    juicio = _catalogo({f"I{i}": "Si -- intervencion" for i in range(11)})

    columnas = columnas_panel(knobs, catalogo=juicio)

    assert [len(k) for _t, k in columnas[:2]] == [6, 5]


def test_an_empty_group_still_produces_its_two_columns():
    """El selector se arma una sola vez con cuatro columnas fijas. Si un grupo
    quedara sin columnas, las demas se correrian de sitio al cambiar de circuito."""
    knobs = [_knob("I0")]
    juicio = _catalogo({"I0": "Si -- intervencion"})

    columnas = columnas_panel(knobs, catalogo=juicio)

    assert len(columnas) == 4
    assert [len(k) for _t, k in columnas] == [1, 0, 0, 0]


# --- El rotulo que va DENTRO de la barra del top de variables --------------------------
#
# La barra lleva el nombre escrito encima porque con cinco vanos por diez posiciones no
# hay leyenda que alcance: cincuenta entradas no se leen. Pero el nombre completo tampoco
# cabe en una barra corta, y Plotly no sabe achicarlo a media palabra: o lo escribe entero
# o lo esconde. Elegir el rotulo del lado de Python es lo que permite la cascada --
# resumen, inicial, nada -- en vez del todo o nada.


def test_the_abbreviation_shortens_the_names_that_do_not_fit():
    """`PROMEDIO_KWH_TRF` dentro de una barra son dieciseis caracteres de un
    nombre que se lee igual de bien resumido. El resumen se DECLARA, no se
    deduce cortando la cadena: "PROMEDIO_KWH_TRF"[:8] da "PROMEDIO", que es la
    mitad de tres variables distintas."""
    assert abreviatura("PROMEDIO_KWH_TRF") == "kWh trafo"
    assert abreviatura("PROMEDIO_KWH_VANO") == "kWh vano"
    assert abreviatura("Precipitacion (12 lags)") == "Precip."


def test_an_unknown_label_keeps_its_own_name():
    """Una variable sin resumen declarado se escribe tal cual. Inventarle una
    abreviatura al vuelo produce rotulos que nadie reconoce, y ese es el unico
    trabajo que el rotulo tiene."""
    assert abreviatura("DDT") == "DDT"
    assert abreviatura("VARIABLE_NUEVA") == "VARIABLE_NUEVA"


def test_the_initials_come_from_the_abbreviation_and_not_from_the_raw_name():
    """La ultima parada antes de no escribir nada. Sale del RESUMEN porque es el
    nombre que el lector ya vio en las barras largas del mismo grupo: "KT" se
    reconstruye desde "kWh trafo", no desde "PROMEDIO_KWH_TRF"."""
    assert iniciales("PROMEDIO_KWH_TRF") == "KT"
    assert iniciales("Precipitacion (12 lags)") == "P"
    assert iniciales("DDT") == "D"


def test_a_long_bar_gets_the_abbreviation():
    """Con sitio de sobra se escribe el resumen: es el rotulo que se entiende sin
    pasar el mouse."""
    assert rotulo_en_barra("PROMEDIO_KWH_TRF", 200.0) == "kWh trafo"


def test_a_short_bar_falls_back_to_the_initials():
    """La barra decima de un grupo mide una fraccion de la primera. Ahi el resumen
    no entra y la inicial si -- y el nombre completo sigue estando en la etiqueta
    del mouse, que es donde se resuelve la duda."""
    assert rotulo_en_barra("PROMEDIO_KWH_TRF", 24.0) == "KT"


def test_a_bar_too_short_even_for_the_initials_stays_empty():
    """Antes que un rotulo cortado a la mitad, ninguno. Un texto que se sale de su
    barra se monta sobre la vecina y termina rotulando a la variable equivocada."""
    assert rotulo_en_barra("PROMEDIO_KWH_TRF", 4.0) == ""


def test_a_bar_thinner_than_the_text_line_gets_no_label():
    """El rotulo va girado -90, asi que la barra lo limita por sus DOS lados.

    La cascada solo miraba el LARGO, que es lo que decide si el texto cabe escrito.
    Pero el grosor de la barra es lo que decide si el texto cabe SIN montarse sobre la
    de al lado: el renglon de un texto de 8 px mide unos 11 de alto, y en el panel del
    top -- ocho vanos por diez posiciones -- cada barra mide 3,6 px medidos a 1.280 px
    de ventana. El resultado eran ochenta rotulos verticales unos encima de otros.

    Es la misma regla que el docstring de la funcion ya prometia -- vacio antes que
    montado sobre la vecina -- aplicada al lado que faltaba.
    """
    assert rotulo_en_barra("PROMEDIO_KWH_TRF", 200.0, grosor_px=3.6) == ""
    assert rotulo_en_barra("PROMEDIO_KWH_TRF", 200.0, grosor_px=14.0) == "kWh trafo"


def test_without_a_declared_thickness_nothing_changes():
    """El grosor es opcional: quien no lo sepa sigue decidiendo solo por el largo.

    Importa porque el ancho del panel no se conoce en Python -- la figura es responsive
    y lo fija el contenedor --, asi que solo el sitio que puede estimarlo lo pasa.
    """
    assert rotulo_en_barra("PROMEDIO_KWH_TRF", 200.0) == "kWh trafo"


def test_the_cascade_is_monotone_in_the_available_thickness():
    """Mas grosor nunca puede dar menos rotulo, igual que con el largo."""
    grosores = [rotulo_en_barra("PROMEDIO_KWH_TRF", 200.0, grosor_px=g)
                for g in range(0, 30)]
    assert [len(t) for t in grosores] == sorted(len(t) for t in grosores)


def test_the_cascade_is_monotone_in_the_available_length():
    """Mas barra nunca puede dar menos rotulo. Es la propiedad que hace que mover
    el eje no baraje los rotulos de forma caprichosa."""
    largos = [rotulo_en_barra("PROMEDIO_KWH_TRF", px) for px in range(0, 200, 4)]
    vistos = [len(t) for t in largos]
    assert vistos == sorted(vistos)


def test_the_uppercase_initials_are_measured_wider_than_the_mixed_case_summary():
    """Dos familias de texto y no una: las iniciales van en MAYUSCULA sostenida,
    que es medio caracter mas ancha que el texto mixto de los resumenes. Medido
    con `measureText` a 8 px sobre la pila de fuentes de Plotly -- `NR` mide 11,55
    px en dos caracteres y `Precip.` 27,18 en siete. Un solo promedio le queda
    corto a una familia y le sobra a la otra."""
    assert ancho_px("NR") / 2 > ancho_px("Precip.") / 7
    # Nunca por debajo de lo medido: un rotulo mas ancho de lo que se creyo se sale
    # de su barra y termina rotulando a la vecina.
    assert ancho_px("NR") >= 11.55
    assert ancho_px("kWh trafo") >= 39.42
    assert ancho_px("Crit. apoyo") >= 44.18


# --- La definicion que el panel muestra al pasar el mouse --------------------------------


def test_definicion_de_knob_carries_the_verdict_and_the_reason():
    """La casilla del panel solo tiene sitio para el nombre. El motivo de
    `JUICIO_SIMULACION` es lo unico que dice QUE ES la variable y por que se puede
    -- o no se debe -- mover, y hasta ahora vivia unicamente en la tabla de la
    celda 8, lejos del sitio donde se elige."""
    knob = _knob("NR_T", bounds=(0.0, 3.0))

    texto = definicion_de_knob(knob)

    veredicto, motivo = JUICIO_SIMULACION["NR_T"]
    assert texto.startswith(veredicto)
    assert motivo in texto


def test_definicion_de_knob_adds_the_unit_and_the_range_when_it_has_them():
    knob = _knob("clima:prep", label="Precipitacion", bounds=(0.0, 42.5))

    texto = definicion_de_knob(knob)

    assert UNIDADES["clima:prep"] in texto
    assert "42.5" in texto or "42,5" in texto


def test_definicion_de_knob_says_so_when_the_variable_was_never_judged():
    """Una variable nueva del modelo no puede salir con una definicion en blanco:
    eso se lee como que no tiene nada que explicar, en vez de como que nadie la
    reviso todavia."""
    knob = _knob("VARIABLE_NUEVA", label="Variable nueva", bounds=(0.0, 1.0))

    texto = definicion_de_knob(knob)

    assert SIN_EVALUAR in texto
    assert texto.strip()


# --- El nombre detallado, no la sigla ----------------------------------------------------


def test_the_detailed_name_comes_from_the_project_dictionary(tmp_path):
    """`NR_T` no le dice nada a quien opera la red. El diccionario del proyecto
    (`data/Variables_seleccion.xlsx`) ya tiene el nombre en palabras de cada columna, y
    es el mismo texto que sustenta el veredicto de simulacion: leerlo de ahi evita que
    el panel invente una segunda redaccion que se separa de la primera."""
    import pandas as pd

    ruta = tmp_path / "dic.xlsx"
    pd.DataFrame({
        "COLUMNA": ["NR_T", "prep"],
        "DESCRIPCIÓN_COLUMNA": ["Nivel de riesgo por vegetacion del vano",
                                "Precipitacion acumulada"],
        "SELECCIÓN": [1, 1],
    }).to_excel(ruta, index=False, sheet_name="Variables_análisis")

    mapa = descripciones_de_variables(ruta)

    assert mapa["NR_T"] == "Nivel de riesgo por vegetacion del vano"
    # Las familias climaticas llegan como `clima:prep`; la clave del diccionario es la
    # columna sin el prefijo, y resolverla aqui evita 12 entradas sin nombre.
    assert mapa["clima:prep"] == "Precipitacion acumulada"


def test_the_definition_leads_with_the_detailed_name(tmp_path):
    knob = _knob("NR_T", bounds=(0.0, 3.0))

    texto = definicion_de_knob(knob, nombres={"NR_T": "Nivel de riesgo por vegetacion"})

    assert texto.startswith("Nivel de riesgo por vegetacion"), (
        "el nombre en palabras va primero: es lo que se lee al posar el mouse"
    )
    assert JUICIO_SIMULACION["NR_T"][0] in texto, "el veredicto sigue estando"


def test_without_a_dictionary_the_definition_still_works(tmp_path):
    """El diccionario es un archivo mas del proyecto y puede faltar en una corrida.
    Sin el, la definicion cae al veredicto y el rango -- que es lo que tenia antes --
    en vez de quedarse sin texto."""
    texto = definicion_de_knob(_knob("NR_T", bounds=(0.0, 3.0)), nombres={})

    assert texto.strip() and JUICIO_SIMULACION["NR_T"][0] in texto
