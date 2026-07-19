from __future__ import annotations

import json

import pandas as pd
import pytest

import chec_local_interpreter.informe_gerencial_contract as informe_contract
from chec_local_interpreter.informe_gerencial_contract import (
    detect_missing_runs,
    load_circuit_content,
    resolve_group_dataframe,
    sample_representatives,
)
from chec_local_interpreter.circuit_identity import canonical_circuit_identity


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


def _df_coords(names: list[str], distances: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"centroid_distance": distances},
        index=pd.Index(names, name="CIRCUITO"),
    )


# ---------------------------------------------------------------------------
# sample_representatives (Phase 2, tasks 2.1-2.3)
# ---------------------------------------------------------------------------


def test_sample_representatives_under_threshold_returns_all_circuits():
    names = [f"C{i:02d}" for i in range(14)]
    distances = list(range(14))
    df_coords = _df_coords(names, distances)

    result = sample_representatives(df_coords)

    assert len(result) == 14
    assert set(result.index) == set(names)


def test_sample_representatives_over_threshold_returns_exactly_20_smallest():
    names = [f"C{i:02d}" for i in range(37)]
    distances = list(range(37))  # C00 has smallest distance, C36 the largest
    df_coords = _df_coords(names, distances)

    result = sample_representatives(df_coords)

    assert len(result) == 20
    assert set(result.index) == {f"C{i:02d}" for i in range(20)}
    assert result["centroid_distance"].max() == 19


def test_sample_representatives_deterministic_tie_break_by_ascending_name():
    # 19 circuits with unique, strictly-smaller distances are certain top-19.
    names = [f"C{i:02d}" for i in range(19)]
    distances = list(range(19))
    # Two circuits tied at the boundary distance (19): only one fits in the
    # top-20. Alphabetically earlier name ("AAA_TIE" < "ZZZ_TIE") must win.
    names += ["ZZZ_TIE", "AAA_TIE"]
    distances += [19, 19]
    df_coords = _df_coords(names, distances)

    result = sample_representatives(df_coords)
    result_again = sample_representatives(df_coords)

    assert len(result) == 20
    assert "AAA_TIE" in result.index
    assert "ZZZ_TIE" not in result.index
    # Reproducible: identical input produces the identical 20-circuit set.
    assert list(result.index) == list(result_again.index)


# ---------------------------------------------------------------------------
# resolve_group_dataframe (Phase 2, tasks 2.4, 2.6)
# ---------------------------------------------------------------------------


def _five_tier_raw_df(per_tier: int = 2) -> pd.DataFrame:
    tiers = [
        ("MUYALTA", 40, 50000.0),
        ("ALTA", 20, 5000.0),
        ("MEDIA", 10, 500.0),
        ("BAJA", 4, 40.0),
        ("MUYBAJA", 2, 2.0),
    ]
    frames = []
    for label, n_events, total in tiers:
        for i in range(per_tier):
            frames.append(_rows_for_circuit(f"{label}_{i}", n_events=n_events, total_uiti=total + i))
    return pd.concat(frames, ignore_index=True)


def test_resolve_group_dataframe_named_group_filters_by_criticidad():
    raw_df = _five_tier_raw_df(per_tier=2)

    result = resolve_group_dataframe(raw_df, "muy-alta", "Muy Alta")

    assert set(result.index) <= {"MUYALTA_0", "MUYALTA_1"}
    assert (result["criticidad"] == "Muy Alta").all()


def test_resolve_group_dataframe_todos_returns_full_universe_all_80_circuits():
    raw_df = _five_tier_raw_df(per_tier=16)  # 16 circuits x 5 tiers = 80

    result = resolve_group_dataframe(raw_df, "todos", None)

    assert len(result) == 80
    assert set(result["criticidad"]) == {"Muy Alta", "Alta", "Media", "Baja", "Muy Baja"}

    sampled = sample_representatives(result)
    assert len(sampled) == 20


# ---------------------------------------------------------------------------
# detect_missing_runs / load_circuit_content (Phase 3, tasks 3.1-3.4)
# ---------------------------------------------------------------------------


def _write_valid_run(runs_root, circuito: str, *, timestamp: str, sintesis: str = "sintesis") -> None:
    run_dir = runs_root / canonical_circuit_identity(circuito) / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {"ok": True, "data": {"sintesis_final": sintesis}}
    (run_dir / "expert-alignment.out.json").write_text(json.dumps(payload), encoding="utf-8")


def test_detect_missing_runs_reports_count_and_names_for_missing_circuits(tmp_path):
    runs_root = tmp_path / "runs"
    sampled = [f"C{i:02d}" for i in range(20)]
    # Only the first 15 have a valid prior run; last 5 are missing.
    for circuito in sampled[:15]:
        _write_valid_run(runs_root, circuito, timestamp="20260101T000000000000")

    result = detect_missing_runs(sampled, runs_root=runs_root)

    assert result["count"] == 5
    assert set(result["circuitos"]) == set(sampled[15:])


def test_detect_missing_runs_zero_when_all_sampled_circuits_have_prior_runs(tmp_path):
    runs_root = tmp_path / "runs"
    sampled = [f"C{i:02d}" for i in range(20)]
    for circuito in sampled:
        _write_valid_run(runs_root, circuito, timestamp="20260101T000000000000")

    result = detect_missing_runs(sampled, runs_root=runs_root)

    assert result["count"] == 0
    assert result["circuitos"] == []


def test_load_circuit_content_prefers_vault_note_over_raw_json(tmp_path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    canonical = canonical_circuit_identity("DON23L13")
    (vault_root / f"{canonical}.md").write_text("# Nota bóveda DON23L13", encoding="utf-8")
    # No run artifact exists at all under runs_root -- if the function
    # incorrectly fell through to the JSON path, it would return None here.
    runs_root = tmp_path / "runs"

    result = load_circuit_content("DON23L13", runs_root=runs_root, vault_root=vault_root)

    assert result is not None
    assert result["source"] == "vault_note"
    assert result["content"] == "# Nota bóveda DON23L13"


def test_load_circuit_content_falls_back_to_raw_json_when_vault_note_absent(tmp_path):
    vault_root = tmp_path / "vault"  # never created -- vault note absent
    runs_root = tmp_path / "runs"
    _write_valid_run(runs_root, "DON23L13", timestamp="20260101T000000000000", sintesis="Texto narrativo real")

    result = load_circuit_content("DON23L13", runs_root=runs_root, vault_root=vault_root)

    assert result is not None
    assert result["source"] == "raw_json"
    assert result["content"] == "Texto narrativo real"


# ---------------------------------------------------------------------------
# resolve() status matrix + CLI + path-injection guards (Phase 4, tasks 4.1-4.3)
# ---------------------------------------------------------------------------


def _known_tier_df_coords_with_distance() -> pd.DataFrame:
    names = [f"MUYALTA_{i}" for i in range(25)]
    distances = list(range(25))
    df = _df_coords(names, distances)
    df["criticidad"] = "Muy Alta"
    return df


def test_resolve_awaiting_confirmation_with_missing_runs(monkeypatch, tmp_path):
    frame = _five_tier_raw_df(per_tier=2)
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    monkeypatch.setattr(
        informe_contract, "resolve_group_dataframe", lambda *a, **k: _known_tier_df_coords_with_distance()
    )
    runs_root = tmp_path / "runs"  # empty -- every sampled circuit is missing a run

    request = informe_contract.normalize_request("muy-alta", runtime="claude")
    outcome = informe_contract.resolve(request, data_path="data.csv", runs_root=runs_root)

    assert outcome.status == "awaiting_confirmation"
    assert outcome.next_actions == ["confirm_and_trigger_missing"]
    assert outcome.missing_runs["count"] == len(outcome.sampled)
    assert len(outcome.sampled) == 20


def test_resolve_awaiting_confirmation_without_missing_runs(monkeypatch, tmp_path):
    frame = _five_tier_raw_df(per_tier=2)
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    df_coords = _known_tier_df_coords_with_distance()
    monkeypatch.setattr(informe_contract, "resolve_group_dataframe", lambda *a, **k: df_coords)
    runs_root = tmp_path / "runs"
    for circuito in df_coords.sort_index().nsmallest(20, "centroid_distance").index:
        _write_valid_run(runs_root, circuito, timestamp="20260101T000000000000")

    request = informe_contract.normalize_request("muy-alta", runtime="claude")
    outcome = informe_contract.resolve(request, data_path="data.csv", runs_root=runs_root)

    assert outcome.status == "awaiting_confirmation"
    assert outcome.next_actions == ["confirm"]
    assert outcome.missing_runs["count"] == 0


def test_resolve_empty_group_status(monkeypatch):
    frame = pd.DataFrame({"CIRCUITO": ["C1"], "FECHA": ["2026-01-01"], "UITI_VANO": ["1"]})
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    empty_df = pd.DataFrame({"criticidad": []}, index=pd.Index([], name="CIRCUITO"))
    monkeypatch.setattr(informe_contract, "resolve_group_dataframe", lambda *a, **k: empty_df)

    request = informe_contract.normalize_request("muy-baja")
    outcome = informe_contract.resolve(request, data_path="data.csv")

    assert outcome.status == "empty_group"
    assert outcome.sampled == []


def test_resolve_usage_error_invalid_grupo_rejected_before_computation():
    with pytest.raises(ValueError, match="grupo desconocido"):
        informe_contract.normalize_request("critica")


def test_resolve_execution_error_wraps_value_error(monkeypatch):
    frame = _five_tier_raw_df(per_tier=2)
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)

    request = informe_contract.normalize_request("todos", "2030-01-01", "2030-01-02")
    outcome = informe_contract.resolve(request, data_path="data.csv")

    assert outcome.status == "execution_error"
    assert outcome.errors


def test_safe_report_filename_rejects_path_traversal_in_grupo():
    with pytest.raises(ValueError, match="grupo desconocido"):
        informe_contract._safe_report_filename(
            grupo="../../etc", fecha_inicio="2026-01-01", fecha_fin="2026-01-02", suffix=".html"
        )


def test_safe_report_filename_rejects_malformed_dates():
    with pytest.raises(ValueError, match="ISO"):
        informe_contract._safe_report_filename(
            grupo="todos", fecha_inicio="../../etc/passwd", fecha_fin="2026-01-02", suffix=".html"
        )


def test_load_circuit_content_rejects_path_traversal_in_circuito(tmp_path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    runs_root = tmp_path / "runs"

    result = load_circuit_content("../../../etc/passwd", runs_root=runs_root, vault_root=vault_root)

    # canonical_circuit_identity strips traversal to "etcpasswd" -- no vault
    # note or run exists under that canonical name, so content is None
    # (never escapes vault_root/runs_root to read an arbitrary filesystem path).
    assert result is None


def test_cli_resolve_exit_code_matches_status(monkeypatch, capsys, tmp_path):
    frame = _five_tier_raw_df(per_tier=2)
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    df_coords = _known_tier_df_coords_with_distance()
    monkeypatch.setattr(informe_contract, "resolve_group_dataframe", lambda *a, **k: df_coords)
    runs_root = tmp_path / "runs"

    exit_code = informe_contract.main(
        ["resolve", "muy-alta", "--data-path", "data.csv", "--runs-root", str(runs_root)]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "awaiting_confirmation"


def test_cli_parse_rejects_unknown_grupo(capsys):
    exit_code = informe_contract.main(["parse", "critica"])

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "usage_error"


def test_outcome_json_text_has_sorted_keys():
    outcome = informe_contract.InformeGerencialOutcome(status="awaiting_confirmation")

    text = outcome.to_json_text()
    parsed = json.loads(text)
    assert list(parsed.keys()) == sorted(parsed.keys())
