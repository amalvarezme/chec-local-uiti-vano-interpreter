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
    knobs_bloqueados,
    knobs_simulables,
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


def test_the_table_carries_the_range_of_every_numeric_knob():
    """vmin/vmax come from the knob's own bounds, which `build_knobs` already
    derives from the observed data -- not from a second set of limits written
    by hand, which could disagree with what the slider actually allows."""
    tabla = tabla_variables_simulables([_knob("NR_T", bounds=(0.0, 3.0))])

    assert list(tabla.columns) == [
        "Variable", "Controla", "Tipo", "vmin", "vmax", "Unidad", "Opciones",
        "Sentido de simular", "Por que",
    ]
    fila = tabla.iloc[0]
    assert fila["Variable"] == "NR_T"
    assert (fila["vmin"], fila["vmax"]) == (0.0, 3.0)
    assert fila["Controla"] == 1


def test_a_categorical_knob_reports_its_options_instead_of_a_range():
    """A range over a category code is meaningless -- the codes are labels,
    not magnitudes, so `vmin`/`vmax` would invite reading 2 as "twice 1"."""
    tabla = tabla_variables_simulables([
        _knob("NG_RED", kind="categorical", bounds=None, categories=("Si", "No")),
    ])

    fila = tabla.iloc[0]
    assert pd.isna(fila["vmin"]) and pd.isna(fila["vmax"])
    assert fila["Opciones"] == "Si | No"


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
    knobs = [_knob("NR_T"), _knob("X2"), _knob("CNT_TRF"), _knob("LONGITUD")]

    ofrecidos = knobs_simulables(knobs)

    assert [k.id for k in ofrecidos] == ["NR_T", "LONGITUD"]


def test_the_removed_knobs_are_reported_so_the_panel_can_name_them():
    """Desaparecer sin decir nada se lee como que faltan. El panel las nombra y
    dice que conservan su valor observado."""
    knobs = [_knob("NR_T"), _knob("X2"), _knob("CNT_TRF")]

    bloqueados = knobs_bloqueados(knobs)

    assert [k.id for k in bloqueados] == ["CNT_TRF", "X2"]


def test_a_limited_knob_stays_in_the_panel():
    """"Limitado" NO es "sin sentido": significa que hay una lectura bajo la cual
    si se interpreta, y el motivo la dice. Quitarla seria decidir por el usuario
    que esa lectura no le sirve."""
    knobs = [_knob("FECHA_OPERACION_VANO"), _knob("LONGITUD"), _knob("TIPO_TAX")]

    assert len(knobs_simulables(knobs)) == 3


def test_an_unevaluated_knob_stays_in_the_panel_but_is_not_hidden():
    """Sin veredicto no hay motivo para quitarla, y quitarla en silencio ocultaria
    justo el caso que hay que revisar. La tabla ya la marca "Sin evaluar"."""
    assert len(knobs_simulables([_knob("VARIABLE_NUEVA")])) == 1
