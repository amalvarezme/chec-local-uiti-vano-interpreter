from __future__ import annotations

import pandas as pd

from chec_local_interpreter.simulation.simulator import (
    categorical_values_for_variable,
    circuit_options,
    context_dates,
    context_filter_mask,
    prioritized_circuit_default,
    risk_class_labels,
    values_grid_for_variable,
    variable_options_for_mode,
    vano_options_for_circuit,
)


class FakeEncoder:
    classes_ = ["A", "B"]


def test_risk_class_labels_supports_common_class_counts():
    assert risk_class_labels(2) == ["Riesgo bajo", "Riesgo alto"]
    assert risk_class_labels(5)[-1] == "Riesgo ordinal 4"


def test_prioritized_circuit_default_returns_first_available_circuit():
    prioritized = pd.DataFrame({"circuito": ["NOPE", "C2"]})
    context = pd.DataFrame({"CIRCUITO": ["C1", "C2"]})

    assert prioritized_circuit_default(prioritized, context) == "C2"


def test_filter_options_and_context_mask():
    context = pd.DataFrame(
        {
            "CIRCUITO": ["C2", "C1", "C2"],
            "FID_VANO": ["V2", "V1", "V3"],
            "FECHA": ["2026-01-01", "2026-01-02", "2026-02-01"],
        }
    )
    dates = context_dates(context)

    assert circuit_options(context) == ["Todos", "C1", "C2"]
    assert vano_options_for_circuit(context, "C2") == ["Todos", "V2", "V3"]
    assert context_filter_mask(context, circuito="C2", fecha_fin="2026-01-15", parsed_dates=dates).tolist() == [True, False, False]


def test_variable_and_value_options():
    xdf = pd.DataFrame({"num": [1.0, 2.0, 3.0], "cat": ["b", "a", None], "encoded": [0, 1, 0]})

    assert variable_options_for_mode("Variables priorizadas", ["num"], ["num", "cat"]) == ["num"]
    assert categorical_values_for_variable("cat", xdf) == ["a", "b"]
    assert categorical_values_for_variable("encoded", xdf, label_encoders={"encoded": FakeEncoder()}) == ["A", "B"]
    assert values_grid_for_variable("num", xdf, selected_value=10.0, max_values=3) == [1.0, 2.0, 3.0, 10.0]
