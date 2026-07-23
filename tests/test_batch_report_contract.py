from __future__ import annotations

import io
import json

import pandas as pd
import pytest

import chec_local_interpreter.batch_report_contract as batch_contract
from chec_local_interpreter.batch_report_contract import (
    ALL_GROUPS_SLUG,
    BatchReportOutcome,
    GROUP_SLUG_TO_LABEL,
    normalize_request,
    preflight_batch,
    write_manifest,
)
from chec_local_interpreter.circuit_clustering_contract import _dataset_date_range


def _rows_for_circuit(circuit: str, n_events: int, total_uiti: float, start: str = "2026-01-01") -> pd.DataFrame:
    """Build `n_events` distinct-date rows for `circuit` whose UITI_VANO sums to `total_uiti`."""
    dates = pd.date_range(start, periods=n_events, freq="D").strftime("%Y-%m-%d").tolist()
    per_event = total_uiti / n_events
    return pd.DataFrame(
        {
            "CIRCUITO": [circuit] * n_events,
            "FECHA": dates,
            "UITI_VANO": [per_event] * n_events,
        }
    )


def _four_tier_raw_df() -> pd.DataFrame:
    """Same deterministic 4-tier fixture proven in `tests/test_plotting.py`."""
    frames = [
        _rows_for_circuit("MUYALTA_1", n_events=40, total_uiti=50000.0),
        _rows_for_circuit("MUYALTA_2", n_events=40, total_uiti=55000.0),
        _rows_for_circuit("ALTA_1", n_events=10, total_uiti=5000.0),
        _rows_for_circuit("ALTA_2", n_events=10, total_uiti=5500.0),
        _rows_for_circuit("MEDIA_1", n_events=10, total_uiti=500.0),
        _rows_for_circuit("MEDIA_2", n_events=10, total_uiti=550.0),
        _rows_for_circuit("BAJA_1", n_events=4, total_uiti=40.0),
        _rows_for_circuit("BAJA_2", n_events=4, total_uiti=45.0),
    ]
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# normalize_request (task 3.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug,expected_label",
    [
        ("muy-alta", "Riesgo Muy Alto"),
        ("alta", "Riesgo Alto"),
        ("medio-alta", "Riesgo Medio-Alto"),
        ("medio-baja", "Riesgo Medio-Bajo"),
        ("baja", "Riesgo Bajo"),
    ],
)
def test_normalize_request_maps_slug_to_label(slug, expected_label):
    request = normalize_request(slug)

    assert request.grupo == slug
    assert request.criticidad == expected_label
    assert GROUP_SLUG_TO_LABEL[slug] == expected_label


def test_normalize_request_todos_has_no_label():
    request = normalize_request(ALL_GROUPS_SLUG)

    assert request.grupo == ALL_GROUPS_SLUG
    assert request.criticidad is None


def test_normalize_request_rejects_unknown_grupo():
    with pytest.raises(ValueError, match="grupo desconocido"):
        normalize_request("critica")


def test_normalize_request_rejects_lone_fecha_inicio():
    with pytest.raises(ValueError, match="provided together"):
        normalize_request("medio-alta", "2026-01-01")


def test_normalize_request_rejects_lone_fecha_fin():
    with pytest.raises(ValueError, match="provided together"):
        normalize_request("medio-alta", None, "2026-01-02")


# ---------------------------------------------------------------------------
# preflight_batch (task 3.3)
# ---------------------------------------------------------------------------


def test_preflight_resolves_dataset_wide_range_when_dates_omitted(monkeypatch):
    frame = _four_tier_raw_df()
    monkeypatch.setattr(batch_contract, "load_dataset", lambda path: frame)

    outcome = preflight_batch(normalize_request("todos", runtime="claude"), data_path="data.csv")

    assert outcome.status == "awaiting_confirmation"
    assert outcome.resolved_window == dict(zip(("fecha_inicio", "fecha_fin"), _dataset_date_range(frame)))


def test_preflight_execution_error_when_explicit_window_has_no_events(monkeypatch):
    frame = _four_tier_raw_df()
    monkeypatch.setattr(batch_contract, "load_dataset", lambda path: frame)

    outcome = preflight_batch(
        normalize_request("todos", "2030-01-01", "2030-01-02"),
        data_path="data.csv",
    )

    assert outcome.status == "execution_error"
    assert outcome.errors == ["No events found in window '2030-01-01'..'2030-01-02'"]


def _known_tier_df_coords() -> pd.DataFrame:
    """A controlled `compute_circuit_criticality_groups`-shaped result covering
    all 5 labels with one distinct circuit each -- deterministic label-to-
    circuit membership, independent of real K-Means's known instability on
    the *middle* tiers (only the top/bottom tiers are empirically robust;
    see `tests/test_plotting.py::_four_tier_raw_df`'s own docstring)."""
    return pd.DataFrame(
        {
            "criticidad": [
                "Riesgo Muy Alto", "Riesgo Alto", "Riesgo Medio-Alto",
                "Riesgo Medio-Bajo", "Riesgo Bajo",
            ]
        },
        index=pd.Index(
            ["MUYALTA_1", "ALTA_1", "MEDIOALTA_1", "MEDIOBAJA_1", "BAJA_1"], name="CIRCUITO"
        ),
    )


@pytest.mark.parametrize(
    "slug,expected_circuitos",
    [
        ("muy-alta", {"MUYALTA_1"}),
        ("alta", {"ALTA_1"}),
        ("medio-alta", {"MEDIOALTA_1"}),
        ("medio-baja", {"MEDIOBAJA_1"}),
        ("baja", {"BAJA_1"}),
    ],
)
def test_preflight_happy_path_resolves_each_tier(monkeypatch, slug, expected_circuitos):
    frame = pd.DataFrame(
        {"CIRCUITO": ["C"], "FECHA": ["2026-01-01"], "UITI_VANO": ["1"]}
    )
    monkeypatch.setattr(batch_contract, "load_dataset", lambda path: frame)
    monkeypatch.setattr(
        batch_contract, "compute_circuit_criticality_groups", lambda filtered_df: _known_tier_df_coords()
    )

    outcome = preflight_batch(normalize_request(slug, runtime="claude"), data_path="data.csv")

    assert outcome.status == "awaiting_confirmation"
    assert outcome.group["slug"] == slug
    assert outcome.group["circuit_count"] == 1
    assert set(outcome.group["circuitos"]) == expected_circuitos
    assert outcome.next_actions == ["confirm_batch"]


def test_preflight_happy_path_resolves_real_four_tier_fixture_top_and_bottom_tiers(monkeypatch):
    """Real (non-monkeypatched) clustering. Only asserts that the tier's own
    circuits are MEMBERS of the resolved group -- the exact same, weaker
    containment assertion `tests/test_plotting.py::test_four_tiers_all_labels
    _present_and_correctly_ranked` itself relies on, since K-Means may pull a
    neighboring-magnitude circuit into the extreme rank clusters too."""
    frame = _four_tier_raw_df()
    monkeypatch.setattr(batch_contract, "load_dataset", lambda path: frame)

    muy_alta = preflight_batch(normalize_request("muy-alta"), data_path="data.csv")
    assert muy_alta.status == "awaiting_confirmation"
    assert {"MUYALTA_1", "MUYALTA_2"} <= set(muy_alta.group["circuitos"])

    baja = preflight_batch(normalize_request("baja"), data_path="data.csv")
    assert baja.status == "awaiting_confirmation"
    assert {"BAJA_1", "BAJA_2"} <= set(baja.group["circuitos"])


def test_preflight_todos_returns_every_available_circuit_without_label_filter(monkeypatch):
    frame = _four_tier_raw_df()
    monkeypatch.setattr(batch_contract, "load_dataset", lambda path: frame)

    outcome = preflight_batch(normalize_request(ALL_GROUPS_SLUG), data_path="data.csv")

    assert outcome.status == "awaiting_confirmation"
    assert outcome.group["label"] is None
    assert outcome.group["circuit_count"] == 8
    assert set(outcome.group["circuitos"]) == {
        "MUYALTA_1", "MUYALTA_2", "ALTA_1", "ALTA_2", "MEDIA_1", "MEDIA_2",
        "BAJA_1", "BAJA_2",
    }


def test_preflight_empty_group_when_two_circuit_dataset_has_no_baja_tier(monkeypatch):
    frame = pd.concat(
        [
            _rows_for_circuit("MUYALTA_1", n_events=40, total_uiti=50000.0),
            _rows_for_circuit("MUYALTA_2", n_events=40, total_uiti=55000.0),
        ],
        ignore_index=True,
    )
    monkeypatch.setattr(batch_contract, "load_dataset", lambda path: frame)

    outcome = preflight_batch(normalize_request("baja"), data_path="data.csv")

    assert outcome.status == "empty_group"
    assert outcome.group["circuitos"] == []
    assert outcome.group["circuit_count"] == 0


def test_preflight_zero_events_in_window_for_specific_group_returns_empty_group(monkeypatch):
    # Distinct from the dataset-wide execution_error case: the filtered
    # dataset overall is NON-empty (C1 has events in the window), but the
    # specific requested group has zero circuits once clustering runs on
    # that filtered frame.
    frame = pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C2"],
            "FECHA": ["2026-01-01", "2026-03-01"],
            "UITI_VANO": ["1", "2"],
        }
    )
    monkeypatch.setattr(batch_contract, "load_dataset", lambda path: frame)

    def fake_compute(filtered_df, start_date=None, end_date=None):
        # C2's row was already dropped by the window filter before this is
        # even called; only C1 survives, always ranked "Riesgo Alto".
        assert "C2" not in filtered_df["CIRCUITO"].values
        return pd.DataFrame({"criticidad": ["Riesgo Alto"]}, index=pd.Index(["C1"], name="CIRCUITO"))

    monkeypatch.setattr(batch_contract, "compute_circuit_criticality_groups", fake_compute)

    outcome = preflight_batch(
        normalize_request("baja", "2026-01-01", "2026-01-02"),
        data_path="data.csv",
    )

    assert outcome.status == "empty_group"
    assert outcome.group["circuitos"] == []


def test_preflight_single_circuit_group_returns_one_entry_manifest(monkeypatch):
    frame = pd.DataFrame({"CIRCUITO": ["ONLY1"], "FECHA": ["2026-01-01"], "UITI_VANO": ["1"]})
    monkeypatch.setattr(batch_contract, "load_dataset", lambda path: frame)

    def fake_compute(filtered_df, start_date=None, end_date=None):
        return pd.DataFrame({"criticidad": ["Riesgo Muy Alto"]}, index=pd.Index(["ONLY1"], name="CIRCUITO"))

    monkeypatch.setattr(batch_contract, "compute_circuit_criticality_groups", fake_compute)

    outcome = preflight_batch(normalize_request("muy-alta"), data_path="data.csv")

    assert outcome.status == "awaiting_confirmation"
    assert outcome.group["circuitos"] == ["ONLY1"]
    assert outcome.group["circuit_count"] == 1


# ---------------------------------------------------------------------------
# write_manifest (task 3.5)
# ---------------------------------------------------------------------------


def test_write_manifest_writes_expected_path_and_shape(tmp_path):
    entries = [
        {"circuito": "C1", "status": "success", "artifact_paths": ["/tmp/c1.html"], "error": None},
        {"circuito": "C2", "status": "failure", "artifact_paths": [], "error": "zero events"},
    ]

    result = write_manifest(
        entries,
        grupo="muy-alta",
        criticidad="Riesgo Muy Alto",
        fecha_inicio="2026-01-01",
        fecha_fin="2026-01-31",
        runs_root=tmp_path,
    )

    assert result["status"] == "success"
    manifest_path = result["manifest_path"]
    assert manifest_path.startswith(str(tmp_path))
    filename = manifest_path.rsplit("/", 1)[-1]
    assert filename.startswith("reporte-lote__muy-alta__2026-01-01__2026-01-31__")
    assert filename.endswith(".json")

    payload = json.loads((tmp_path / filename).read_text(encoding="utf-8"))
    assert payload["tool_version"] == batch_contract.SCHEMA_VERSION
    assert payload["grupo"] == "muy-alta"
    assert payload["criticidad"] == "Riesgo Muy Alto"
    assert payload["fecha_inicio"] == "2026-01-01"
    assert payload["fecha_fin"] == "2026-01-31"
    assert payload["circuits"] == entries
    assert "generated_at" in payload


def test_write_manifest_preserves_mixed_success_and_failure_entries(tmp_path):
    entries = [
        {"circuito": "C1", "status": "failure", "artifact_paths": [], "error": "ReportPipelineError"},
        {"circuito": "C2", "status": "success", "artifact_paths": ["/tmp/c2.html"], "error": None},
        {"circuito": "C3", "status": "failure", "artifact_paths": [], "error": "zero events"},
    ]

    result = write_manifest(
        entries,
        grupo="todos",
        criticidad=None,
        fecha_inicio="2026-01-01",
        fecha_fin="2026-01-02",
        runs_root=tmp_path,
    )

    payload = json.loads((tmp_path / result["manifest_path"].rsplit("/", 1)[-1]).read_text(encoding="utf-8"))
    assert len(payload["circuits"]) == 3
    statuses = [entry["status"] for entry in payload["circuits"]]
    assert statuses == ["failure", "success", "failure"]


def test_write_manifest_rejects_invalid_grupo_slug(tmp_path):
    with pytest.raises(ValueError, match="grupo desconocido"):
        write_manifest(
            [],
            grupo="../../etc",
            criticidad=None,
            fecha_inicio="2026-01-01",
            fecha_fin="2026-01-02",
            runs_root=tmp_path,
        )


def test_write_manifest_rejects_malformed_dates(tmp_path):
    with pytest.raises(ValueError, match="ISO"):
        write_manifest(
            [],
            grupo="todos",
            criticidad=None,
            fecha_inicio="../../etc/passwd",
            fecha_fin="2026-01-02",
            runs_root=tmp_path,
        )


# ---------------------------------------------------------------------------
# CLI (task 3.7)
# ---------------------------------------------------------------------------


def test_cli_parse_outputs_json(capsys):
    exit_code = batch_contract.main(["parse", "muy-alta", "--runtime", "pi"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "awaiting_confirmation"
    assert payload["request"]["grupo"] == "muy-alta"
    assert payload["request"]["runtime"]["runtime"] == "pi"


def test_cli_parse_rejects_unknown_grupo(capsys):
    exit_code = batch_contract.main(["parse", "critica"])

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "usage_error"


def test_cli_preflight_exit_code_matches_status(monkeypatch, capsys):
    frame = _four_tier_raw_df()
    monkeypatch.setattr(batch_contract, "load_dataset", lambda path: frame)

    exit_code = batch_contract.main(["preflight", "muy-alta", "--data-path", "data.csv"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "awaiting_confirmation"


def test_cli_write_manifest_reads_stdin_and_writes_file(monkeypatch, tmp_path, capsys):
    entries = [{"circuito": "C1", "status": "success", "artifact_paths": [], "error": None}]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(entries)))

    exit_code = batch_contract.main(
        [
            "write-manifest",
            "--grupo", "todos",
            "--fecha-inicio", "2026-01-01",
            "--fecha-fin", "2026-01-02",
            "--runs-root", str(tmp_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    assert payload["manifest_path"].startswith(str(tmp_path))


def test_outcome_json_text_has_sorted_keys():
    outcome = BatchReportOutcome(status="awaiting_confirmation")

    text = outcome.to_json_text()
    parsed = json.loads(text)
    assert list(parsed.keys()) == sorted(parsed.keys())
