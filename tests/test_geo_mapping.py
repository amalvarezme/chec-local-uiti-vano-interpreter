from __future__ import annotations

import pandas as pd
import pytest

from chec_local_interpreter.geo.mapping import (
    available_columns,
    norm_id,
    popup_html,
    safe_text,
    style_line,
)


def test_norm_id_strips_decimal_suffix_and_empty_values():
    result = norm_id(pd.Series([" 123.0 ", "", "nan", None, "ABC"]))

    assert result.tolist()[0] == "123"
    assert pd.isna(result.tolist()[1])
    assert pd.isna(result.tolist()[2])
    assert pd.isna(result.tolist()[3])
    assert result.tolist()[4] == "ABC"


def test_style_line_uses_red_for_positive_uiti():
    assert style_line({"properties": {"uiti_vano_total": 1}}) == {
        "color": "#dc2626",
        "weight": 4,
        "opacity": 0.75,
    }
    assert style_line({"properties": {"uiti_vano_total": 0}}) == {
        "color": "#2563eb",
        "weight": 2,
        "opacity": 0.75,
    }


def test_available_columns_filters_missing_columns():
    df = pd.DataFrame({"A": [1], "C": [3]})

    assert available_columns(df, ["A", "B", "C"]) == ["A", "C"]


def test_safe_text_handles_missing_values():
    assert safe_text(None) == ""
    assert safe_text(float("nan")) == ""
    assert safe_text("ok") == "ok"


def test_popup_html_includes_only_present_values():
    row = pd.Series({"FID": "V1", "EMPTY": None})

    html = popup_html(row, [("FID", "FID"), ("EMPTY", "Empty")], "Title")

    assert "<strong>Title</strong>" in html
    assert "V1" in html
    assert "Empty" not in html
