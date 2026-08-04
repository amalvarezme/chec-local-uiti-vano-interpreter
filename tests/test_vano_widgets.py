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
