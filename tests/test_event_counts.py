from __future__ import annotations

import pandas as pd

from chec_impacto.interpretability.circuit_analysis import agrupar_por_vano
from chec_local_interpreter.event_counts import count_unique_event_dates


def test_count_unique_event_dates_groups_by_distinct_fecha():
    frame = pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1", "C1", "C2"],
            "FECHA": ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-01"],
        }
    )
    counts = count_unique_event_dates(frame, "CIRCUITO")
    assert counts.loc["C1"] == 2
    assert counts.loc["C2"] == 1


def test_agrupar_por_vano_counts_rows_for_n_apariciones():
    frame = pd.DataFrame(
        {
            "FID_VANO": ["V1", "V1", "V1", "V2"],
            "CIRCUITO": ["C1", "C1", "C1", "C1"],
            "FECHA": ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-01"],
            "UITI_VANO": [1.0, 3.0, 5.0, 7.0],
        }
    )
    grouped = agrupar_por_vano(frame).set_index("FID_VANO")
    assert grouped.loc["V1", "N_APARICIONES"] == 3
    assert grouped.loc["V2", "N_APARICIONES"] == 1
