"""RED/GREEN tests for PR2a of notebook 01.5 (widget constructor).

Covers `chec_local_interpreter.vano_widgets.widget_for_knob`, the ONLY
place `ipywidgets` is imported for the Knob catalog -- and it is imported
lazily, inside the function, so `vano_controls` (tested in
`tests/test_vano_controls.py`) never needs ipywidgets installed.

See:
  - spec: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/spec`
    (domain `vano-risk-simulation`, requirement "Control type follows
    variable kind")
  - design: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/design`
    (section B)
"""

from __future__ import annotations

import pytest

pytest.importorskip("ipywidgets")

from chec_local_interpreter.vano_controls import Knob
from chec_local_interpreter.vano_widgets import widget_for_knob


def _numeric_knob(**overrides) -> Knob:
    fields = dict(
        id="LONGITUD",
        label="LONGITUD",
        kind="numeric",
        feature_names=("LONGITUD",),
        bounds=(0.0, 10.0),
        categories=None,
        default=5.0,
        step=0.1,
    )
    fields.update(overrides)
    return Knob(**fields)


def _categorical_knob(**overrides) -> Knob:
    fields = dict(
        id="TIPO",
        label="TIPO",
        kind="categorical",
        feature_names=("TIPO",),
        bounds=None,
        categories=("A", "B", "C"),
        default="B",
        step=None,
    )
    fields.update(overrides)
    return Knob(**fields)


def _constant_knob(**overrides) -> Knob:
    fields = dict(
        id="CNT_FASES",
        label="CNT_FASES",
        kind="constant",
        feature_names=("CNT_FASES",),
        bounds=(3.0, 3.0),
        categories=None,
        default=3.0,
        step=None,
    )
    fields.update(overrides)
    return Knob(**fields)


def test_widget_for_numeric_knob_returns_float_slider():
    import ipywidgets as widgets

    widget = widget_for_knob(_numeric_knob())

    assert isinstance(widget, widgets.FloatSlider)
    assert widget.min == 0.0
    assert widget.max == 10.0
    assert widget.step == pytest.approx(0.1)
    assert widget.value == pytest.approx(5.0)
    assert widget.disabled is False


def test_widget_for_categorical_knob_returns_dropdown():
    import ipywidgets as widgets

    widget = widget_for_knob(_categorical_knob())

    assert isinstance(widget, widgets.Dropdown)
    assert tuple(widget.options) == ("A", "B", "C")
    assert widget.value == "B"


def test_widget_for_constant_knob_returns_disabled_float_text():
    import ipywidgets as widgets

    widget = widget_for_knob(_constant_knob())

    assert isinstance(widget, widgets.FloatText)
    assert widget.disabled is True
    assert widget.value == pytest.approx(3.0)


def test_widget_for_numeric_knob_falls_back_to_bounds_when_default_missing():
    import ipywidgets as widgets

    widget = widget_for_knob(_numeric_knob(default=None))

    assert isinstance(widget, widgets.FloatSlider)
    assert widget.value == pytest.approx(0.0)


def test_widget_for_categorical_knob_falls_back_to_first_option_when_default_missing():
    widget = widget_for_knob(_categorical_knob(default=None))

    assert widget.value == "A"


# --- PR6: selector de vanos por casilla (reemplaza el SelectMultiple) -------


def test_selector_vanos_exposes_a_value_trait_and_one_checkbox_per_vano():
    """01.4 marca vanos con CASILLAS, no con una lista de seleccion
    multiple. El selector expone `value` como trait para que las celdas de
    figura/ranking/simulacion sigan usando `observe(names='value')` sin
    saber que hay casillas detras."""
    from chec_local_interpreter.vano_widgets import construir_selector_vanos

    selector = construir_selector_vanos(["VA", "VB", "VC"])

    assert selector.value == ()
    assert list(selector.casillas) == ["VA", "VB", "VC"]
    assert all(caja.value is False for caja in selector.casillas.values())


def test_selector_vanos_checkbox_and_click_share_one_state():
    """Alternar la casilla y alternar por clic en el mapa tienen que llegar
    al MISMO `value`: si llevaran registros separados, la lista, el mapa y
    el ranking podrian contar cosas distintas (01.4, `marcarPorFid`)."""
    from chec_local_interpreter.vano_widgets import construir_selector_vanos

    selector = construir_selector_vanos(["VA", "VB", "VC"])
    vistos = []
    selector.observe(lambda cambio: vistos.append(cambio["new"]), names="value")

    selector.casillas["VB"].value = True          # por casilla
    assert selector.value == ("VB",)

    selector.alternar("VA")                        # por clic en el mapa
    assert selector.value == ("VA", "VB")

    selector.alternar("VB")                        # el clic tambien desmarca
    assert selector.value == ("VA",)
    assert selector.casillas["VB"].value is False
    assert vistos == [("VB",), ("VA", "VB"), ("VA",)]


def test_selector_vanos_repopulating_clears_the_previous_selection():
    """Cambiar de circuito cambia el universo de vanos: conservar la
    seleccion anterior dejaria marcados fids que ya no existen en el mapa."""
    from chec_local_interpreter.vano_widgets import construir_selector_vanos

    selector = construir_selector_vanos(["VA", "VB"])
    selector.alternar("VA")
    assert selector.value == ("VA",)

    selector.poblar(["VX", "VY"])
    assert selector.value == ()
    assert list(selector.casillas) == ["VX", "VY"]


def test_selector_vanos_exposes_its_inner_box_as_a_public_attribute():
    """`caja` is the seam notebook 01.5's panel cell reaches for
    (`vano_widget.caja.add_class('lista-vanos')`). It was renamed once from
    `_caja` and nothing in this suite noticed -- the breakage only surfaced in a
    live kernel, twice. Pinning it here turns a rename into a RED test."""
    import ipywidgets as widgets

    from chec_local_interpreter.vano_widgets import construir_selector_vanos

    selector = construir_selector_vanos(["VA", "VB"])

    assert isinstance(selector.caja, widgets.Box)
    assert selector.caja in selector.children
    assert tuple(selector.caja.children) == tuple(selector.casillas.values())

    selector.caja.add_class("lista-vanos")  # exactly what the notebook cell does
    assert "lista-vanos" in selector.caja._dom_classes


def test_selector_marcar_todos_ticks_everything_with_a_single_value_event():
    """"Marcar todos" (paridad 01.4) tiene que emitir UN solo cambio de `value`.
    Dejar que cada casilla notifique por su cuenta significaria un repintado del
    mapa por vano -- cientos en un circuito grande."""
    from chec_local_interpreter.vano_widgets import construir_selector_vanos

    selector = construir_selector_vanos(["VA", "VB", "VC"])
    eventos = []
    selector.observe(lambda cambio: eventos.append(cambio["new"]), names="value")

    selector.marcar_todos()

    assert selector.value == ("VA", "VB", "VC")
    assert all(caja.value is True for caja in selector.casillas.values())
    assert eventos == [("VA", "VB", "VC")]


def test_selector_desmarcar_todos_clears_everything_with_a_single_value_event():
    from chec_local_interpreter.vano_widgets import construir_selector_vanos

    selector = construir_selector_vanos(["VA", "VB", "VC"])
    selector.marcar_todos()
    eventos = []
    selector.observe(lambda cambio: eventos.append(cambio["new"]), names="value")

    selector.desmarcar_todos()

    assert selector.value == ()
    assert all(caja.value is False for caja in selector.casillas.values())
    assert eventos == [()]


def test_selector_casillas_accepts_label_value_pairs():
    """El selector de variables del simulador necesita rotulo != clave: la casilla
    muestra "Precipitacion (12 lags)" y `value` devuelve el knob id `clima:prep`.
    El selector de vanos no lo necesitaba porque ahi el rotulo ES el fid."""
    from chec_local_interpreter.vano_widgets import construir_selector_casillas

    selector = construir_selector_casillas(
        [("Precipitacion (12 lags)", "clima:prep"), ("CNT_TRF", "CNT_TRF")],
        titulo="Variables",
    )

    assert list(selector.casillas) == ["clima:prep", "CNT_TRF"]
    assert selector.casillas["clima:prep"].description == "Precipitacion (12 lags)"

    selector.casillas["clima:prep"].value = True
    selector.casillas["CNT_TRF"].value = True

    assert selector.value == ("clima:prep", "CNT_TRF")  # varias a la vez, en orden de opcion


def test_selector_casillas_unticking_leaves_the_other_selections_alone():
    """Es la razon de ser del cambio: con un `SelectMultiple` marcar una variable
    sin ctrl borraba las demas. Con casillas, cada una es independiente."""
    from chec_local_interpreter.vano_widgets import construir_selector_casillas

    selector = construir_selector_casillas([("A", "a"), ("B", "b"), ("C", "c")])
    for clave in ("a", "b", "c"):
        selector.casillas[clave].value = True
    assert selector.value == ("a", "b", "c")

    selector.casillas["b"].value = False

    assert selector.value == ("a", "c")


def test_selector_vanos_keeps_scalar_options_labelled_by_their_own_fid():
    """Regresion: generalizar el selector a pares (rotulo, clave) no debe romper la
    forma escalar que usa el selector de vanos."""
    from chec_local_interpreter.vano_widgets import construir_selector_vanos

    selector = construir_selector_vanos([20130434, "VB"])

    assert list(selector.casillas) == ["20130434", "VB"]
    assert selector.casillas["20130434"].description == "20130434"


def test_selector_vanos_ignores_a_click_on_an_unknown_fid():
    """Un clic puede caer sobre un tramo cuyo fid no esta en la lista (el
    mapa dibuja la geometria del circuito, que no siempre coincide con los
    vanos con eventos). No debe crear una casilla fantasma ni fallar."""
    from chec_local_interpreter.vano_widgets import construir_selector_vanos

    selector = construir_selector_vanos(["VA"])
    selector.alternar("DESCONOCIDO")
    assert selector.value == ()
    assert list(selector.casillas) == ["VA"]
