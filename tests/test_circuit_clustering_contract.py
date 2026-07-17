from __future__ import annotations

import json

import pytest

import chec_local_interpreter.circuit_clustering_contract as clustering_contract
from chec_local_interpreter.agent_output import ReportPipelineError
from chec_local_interpreter.circuit_clustering_contract import (
    ClusteringOutcome,
    normalize_request,
    preflight_clustering,
    render_clustering,
)


def test_normalize_request_rejects_lone_fecha_inicio():
    with pytest.raises(ValueError, match="provided together"):
        normalize_request("2026-01-01")


def test_normalize_request_rejects_lone_fecha_fin():
    with pytest.raises(ValueError, match="provided together"):
        normalize_request(None, "2026-01-02")


def test_preflight_resolves_full_dataset_range_when_dates_are_omitted(monkeypatch):
    frame = clustering_contract.pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C2"],
            "FECHA": ["2026-01-02", "2026-01-05"],
            "UITI_VANO": ["1", "2"],
        }
    )
    monkeypatch.setattr(clustering_contract, "load_dataset", lambda path: frame)

    outcome = preflight_clustering(normalize_request(runtime="claude"), data_path="data.csv")

    assert outcome.status == "awaiting_confirmation"
    assert outcome.resolved_window == {
        "fecha_inicio": "2026-01-02",
        "fecha_fin": "2026-01-05",
        "event_count": 2,
    }


def test_preflight_returns_execution_error_when_window_has_no_events(monkeypatch):
    frame = clustering_contract.pd.DataFrame(
        {
            "CIRCUITO": ["C1"],
            "FECHA": ["2026-01-02"],
            "UITI_VANO": ["1"],
        }
    )
    monkeypatch.setattr(clustering_contract, "load_dataset", lambda path: frame)

    outcome = preflight_clustering(
        normalize_request("2026-02-01", "2026-02-02", runtime="pi"),
        data_path="data.csv",
    )

    assert outcome.status == "execution_error"
    assert outcome.errors == ["No events found in window '2026-02-01'..'2026-02-02'"]


def test_render_clustering_reuses_plotting_and_writes_deterministic_html(monkeypatch, tmp_path):
    frame = clustering_contract.pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C2"],
            "FECHA": ["2026-01-02", "2026-01-05"],
            "UITI_VANO": ["1", "2"],
        }
    )
    calls: list[tuple[object, str, str]] = []

    class FigureStub:
        def to_html(self, *, full_html: bool, include_plotlyjs: bool, div_id: str):
            assert full_html is True
            assert include_plotlyjs is True
            assert div_id == "circuit-clustering-chart"
            return "<html><body>chart</body></html>"

    def fake_plot(raw_df, start_date=None, end_date=None, highlighted_circuits=None):
        calls.append((raw_df.copy(), start_date, end_date))
        assert highlighted_circuits is None
        return FigureStub()

    monkeypatch.setattr(clustering_contract, "load_dataset", lambda path: frame)
    monkeypatch.setattr(clustering_contract, "plot_interactive_circuit_clustering", fake_plot)

    outcome = render_clustering(
        normalize_request(runtime="opencode"),
        data_path="data.csv",
        output_root=tmp_path,
    )

    assert outcome.status == "success"
    assert outcome.output_html == str(
        tmp_path / "agrupamiento-circuitos__2026-01-02__2026-01-05.html"
    )
    assert len(calls) == 1
    called_frame, called_start, called_end = calls[0]
    assert called_frame.equals(frame)
    assert (called_start, called_end) == ("2026-01-02", "2026-01-05")
    assert (tmp_path / "agrupamiento-circuitos__2026-01-02__2026-01-05.html").read_text(encoding="utf-8") == "<html><body>chart</body></html>"


def test_render_clustering_reports_pipeline_errors(monkeypatch):
    def fake_load_dataset(path):
        raise ReportPipelineError("Dataset missing")

    monkeypatch.setattr(clustering_contract, "load_dataset", fake_load_dataset)

    outcome = render_clustering(normalize_request(runtime="claude"), data_path="missing.csv")

    assert outcome.status == "execution_error"
    assert outcome.output_html is None
    assert outcome.errors == ["Dataset missing"]


def test_outcome_json_hides_output_path_until_success():
    outcome = ClusteringOutcome(status="awaiting_confirmation", output_html="/tmp/chart.html")

    assert outcome.to_json()["output_html"] is None


def test_cli_parse_outputs_json(capsys):
    exit_code = clustering_contract.main(["parse", "--runtime", "pi"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "awaiting_confirmation"
    assert payload["request"]["runtime"]["runtime"] == "pi"
