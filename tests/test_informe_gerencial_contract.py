from __future__ import annotations

import html as html_lib
import json
import re
from pathlib import Path

import pandas as pd
import pytest

import chec_local_interpreter.circuit_meta_graph as circuit_meta_graph
import chec_local_interpreter.graph_view_builder as graph_view_builder
import chec_local_interpreter.informe_gerencial_contract as informe_contract
from chec_local_interpreter.informe_gerencial_contract import (
    detect_missing_runs,
    load_circuit_content,
    render_managerial_report,
    resolve_group_dataframe,
    sample_representatives,
    synthesize,
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
    names = [f"C{i:02d}" for i in range(10)]
    distances = list(range(10))
    df_coords = _df_coords(names, distances)

    result = sample_representatives(df_coords)

    assert len(result) == 10
    assert set(result.index) == set(names)


def test_sample_representatives_over_threshold_returns_exactly_12_smallest():
    names = [f"C{i:02d}" for i in range(37)]
    distances = list(range(37))  # C00 has smallest distance, C36 the largest
    df_coords = _df_coords(names, distances)

    result = sample_representatives(df_coords)

    assert len(result) == 12
    assert set(result.index) == {f"C{i:02d}" for i in range(12)}
    assert result["centroid_distance"].max() == 11


def test_sample_representatives_deterministic_tie_break_by_ascending_name():
    # 11 circuits with unique, strictly-smaller distances are certain top-11.
    names = [f"C{i:02d}" for i in range(11)]
    distances = list(range(11))
    # Two circuits tied at the boundary distance (11): only one fits in the
    # top-12. Alphabetically earlier name ("AAA_TIE" < "ZZZ_TIE") must win.
    names += ["ZZZ_TIE", "AAA_TIE"]
    distances += [11, 11]
    df_coords = _df_coords(names, distances)

    result = sample_representatives(df_coords)
    result_again = sample_representatives(df_coords)

    assert len(result) == 12
    assert "AAA_TIE" in result.index
    assert "ZZZ_TIE" not in result.index
    # Reproducible: identical input produces the identical 12-circuit set.
    assert list(result.index) == list(result_again.index)


# ---------------------------------------------------------------------------
# resolve_group_dataframe (Phase 2, tasks 2.4, 2.6)
# ---------------------------------------------------------------------------


def _four_tier_raw_df(per_tier: int = 2) -> pd.DataFrame:
    """4 magnitude tiers, `per_tier` circuits each, fed through the shared
    5-tier `compute_circuit_criticality_groups` (deterministic
    `run_kmeans(..., random_state=42)`). `per_tier=2` gives exact per-circuit
    tier assignment for the top/bottom magnitude tiers (robust under +/-2%
    jitter across 200 trials); `per_tier=16` empirically yields all 5
    `CRITICALITY_GROUP_LABELS` populated across the full 64-circuit universe
    (K-Means splits one of the 4 magnitude tiers in two), which is all
    `test_resolve_group_dataframe_todos_returns_full_universe` requires -- it
    does not assert exact per-circuit membership.
    """
    tiers = [
        ("MUYALTA", 40, 50000.0),
        ("ALTA", 10, 5000.0),
        ("MEDIA", 10, 500.0),
        ("BAJA", 2, 40.0),
    ]
    frames = []
    for label, n_events, total in tiers:
        for i in range(per_tier):
            frames.append(_rows_for_circuit(f"{label}_{i}", n_events=n_events, total_uiti=total + i))
    return pd.concat(frames, ignore_index=True)


def test_resolve_group_dataframe_named_group_filters_by_criticidad():
    raw_df = _four_tier_raw_df(per_tier=2)

    result = resolve_group_dataframe(raw_df, "muy-alta", "Riesgo Muy Alto")

    assert set(result.index) <= {"MUYALTA_0", "MUYALTA_1"}
    assert (result["criticidad"] == "Riesgo Muy Alto").all()


def test_resolve_group_dataframe_todos_returns_full_universe_all_64_circuits():
    raw_df = _four_tier_raw_df(per_tier=16)  # 16 circuits x 4 tiers = 64

    result = resolve_group_dataframe(raw_df, "todos", None)

    assert len(result) == 64
    assert set(result["criticidad"]) == {
        "Riesgo Muy Alto", "Riesgo Alto", "Riesgo Medio-Alto", "Riesgo Medio-Bajo", "Riesgo Bajo",
    }

    sampled = sample_representatives(result)
    assert len(sampled) == 12


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


def test_load_circuit_content_vault_note_with_run_dir_populates_structured_fields(tmp_path):
    """Bugfix (task 1.1): when a vault note is used AND a prior run_dir is
    resolvable, `cause_hypothesis_note`/`variable_groups_used`/
    `variables_a_priorizar` must be sourced from the run's own JSONs (same
    completeness as the raw_json path) -- never hardcoded to `None`/`[]`.
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    canonical = canonical_circuit_identity("DON23L13")
    (vault_root / f"{canonical}.md").write_text("# Nota bóveda DON23L13", encoding="utf-8")

    runs_root = tmp_path / "runs"
    timestamp = "20260101T000000000000"
    run_dir = runs_root / canonical / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "expert-alignment.out.json").write_text(
        json.dumps(
            {
                "ok": True,
                "data": {
                    "sintesis_final": "Síntesis real de DON23L13.",
                    "variables_a_priorizar": [{"variable": "CNT_VN", "prioridad": "alta"}],
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "historical.out.json").write_text(
        json.dumps(
            {
                "ok": True,
                "data": {
                    "headline": "Evento crítico en DON23L13 el 2026-01-01.",
                    "cause_hypothesis_note": "Compatible con exposición a fauna.",
                    "recommended_actions": ["Verificar en campo."],
                    "key_findings": [
                        {"title": "Fauna en zona de vano", "variable_groups_used": ["Entorno/Riesgo"]}
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    result = load_circuit_content("DON23L13", runs_root=runs_root, vault_root=vault_root)

    assert result is not None
    assert result["source"] == "vault_note"
    assert result["content"] == "# Nota bóveda DON23L13"
    assert result["headline"] == "Evento crítico en DON23L13 el 2026-01-01."
    assert result["key_finding_titles"] == ["Fauna en zona de vano"]
    assert result["cause_hypothesis_note"] == "Compatible con exposición a fauna."
    assert result["variable_groups_used"] == ["Entorno/Riesgo"]
    assert result["variables_a_priorizar"] == [{"variable": "CNT_VN", "prioridad": "alta"}]
    assert result["recommended_actions"] == ["Verificar en campo."]


def test_load_circuit_content_vault_note_without_run_dir_parses_only_cause_hypothesis(tmp_path):
    """Bugfix (task 1.2): when NO prior run_dir is resolvable, only
    `cause_hypothesis_note` may be recovered, parsed directly from the vault
    note's own `### Hipótesis de causa` section -- `variable_groups_used` and
    `variables_a_priorizar` stay empty (the note does not preserve them).
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    canonical = canonical_circuit_identity("DON23L13")
    note = (
        "# Nota bóveda DON23L13\n\n"
        "### Hipótesis de causa\n"
        "Compatible con exposición a fauna en los vanos implicados.\n\n"
        "### Otra sección\n"
        "Contenido no relacionado.\n"
    )
    (vault_root / f"{canonical}.md").write_text(note, encoding="utf-8")
    runs_root = tmp_path / "runs"  # no run dir at all -- find_latest_run returns None

    result = load_circuit_content("DON23L13", runs_root=runs_root, vault_root=vault_root)

    assert result is not None
    assert result["source"] == "vault_note"
    assert result["cause_hypothesis_note"] == "Compatible con exposición a fauna en los vanos implicados."
    assert result["variable_groups_used"] == []
    assert result["variables_a_priorizar"] == []
    assert result["headline"] is None
    assert result["key_finding_titles"] == []


def test_load_circuit_content_falls_back_to_raw_json_when_vault_note_absent(tmp_path):
    vault_root = tmp_path / "vault"  # never created -- vault note absent
    runs_root = tmp_path / "runs"
    _write_valid_run(runs_root, "DON23L13", timestamp="20260101T000000000000", sintesis="Texto narrativo real")

    result = load_circuit_content("DON23L13", runs_root=runs_root, vault_root=vault_root)

    assert result is not None
    assert result["source"] == "raw_json"
    assert result["content"] == "Texto narrativo real"


def test_load_circuit_content_surfaces_technical_fields_and_own_report_html(tmp_path):
    """Beyond `content`, the raw-JSON path must surface the real technical
    signal already produced by the per-circuit `/report` run --
    `variables_a_priorizar` (expert-alignment), `cause_hypothesis_note`/
    `variable_groups_used`/`recommended_actions` (historical) -- plus a
    `report_html` path that is the ONLY file this module may ever cite to the
    user, resolved from the run's own `l1_state.json` and filename
    convention, never the internal JSON/markdown run artifacts.
    """
    vault_root = tmp_path / "vault"  # absent -- forces the raw-JSON path
    runs_root = tmp_path / "runs"
    html_root = tmp_path / "html"
    html_root.mkdir(parents=True, exist_ok=True)

    timestamp = "20260101T000000000000"
    run_dir = runs_root / canonical_circuit_identity("DON23L13") / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "expert-alignment.out.json").write_text(
        json.dumps(
            {
                "ok": True,
                "data": {
                    "sintesis_final": "Síntesis real de DON23L13.",
                    "variables_a_priorizar": [
                        {"variable": "CNT_VN", "prioridad": "alta"},
                        {"variable": "TIPO", "prioridad": "media"},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "historical.out.json").write_text(
        json.dumps(
            {
                "ok": True,
                "data": {
                    "headline": "Falla recurrente de conductor en DON23L13.",
                    "cause_hypothesis_note": "Compatible con exposición a fauna y clima atmosférico.",
                    "recommended_actions": ["Verificar en campo el estado del conductor."],
                    "key_findings": [
                        {"title": "Concentración topológica", "variable_groups_used": ["Topologia", "Entorno/Riesgo"]},
                        {"title": "Recurrencia climática", "variable_groups_used": ["Entorno/Riesgo"]},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "l1_state.json").write_text(
        json.dumps({"circuito": "DON23L13", "fecha_inicio": "2025-11-01", "fecha_fin": "2026-04-30"}),
        encoding="utf-8",
    )
    expected_html = html_root / f"DON23L13_20251101_20260430_{timestamp}.html"
    expected_html.write_text("<html></html>", encoding="utf-8")

    result = load_circuit_content(
        "DON23L13", runs_root=runs_root, vault_root=vault_root, html_root=html_root
    )

    assert result is not None
    assert result["report_html"] == str(expected_html)
    assert result["headline"] == "Falla recurrente de conductor en DON23L13."
    assert result["key_finding_titles"] == ["Concentración topológica", "Recurrencia climática"]
    assert result["cause_hypothesis_note"] == "Compatible con exposición a fauna y clima atmosférico."
    assert result["recommended_actions"] == ["Verificar en campo el estado del conductor."]
    assert result["variable_groups_used"] == ["Topologia", "Entorno/Riesgo", "Entorno/Riesgo"]
    assert result["variables_a_priorizar"] == [
        {"variable": "CNT_VN", "prioridad": "alta"},
        {"variable": "TIPO", "prioridad": "media"},
    ]


def test_load_circuit_content_report_html_none_when_report_never_rendered(tmp_path):
    """If the circuit's own HTML report was never actually rendered (only
    `prepare`/agents ran, `render` never did), `report_html` must be `None`
    -- never a dangling/nonexistent path presented as if it were citable.
    """
    vault_root = tmp_path / "vault"
    runs_root = tmp_path / "runs"
    _write_valid_run(runs_root, "DON23L13", timestamp="20260101T000000000000", sintesis="Texto")
    # No l1_state.json and no html_root file created -- report was never rendered.

    result = load_circuit_content("DON23L13", runs_root=runs_root, vault_root=vault_root)

    assert result is not None
    assert result["report_html"] is None


# ---------------------------------------------------------------------------
# load_graph_patterns (Phase 2, tasks 2.1-2.4)
# ---------------------------------------------------------------------------


def _write_graph_patterns_json(path: Path, patterns: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "informe-gerencial-graph-patterns/v1",
                "query": "temas recurrentes",
                "min_support": 2,
                "patterns": patterns,
            }
        ),
        encoding="utf-8",
    )


def test_load_graph_patterns_drops_patterns_below_min_support(tmp_path):
    path = tmp_path / "graph-patterns.json"
    _write_graph_patterns_json(
        path,
        [
            {"tema": "fauna en vanos", "circuitos": ["DON23L13", "AMA23L12"], "soporte": 2},
            {"tema": "clima aislado", "circuitos": ["HER23L16"], "soporte": 1},
        ],
    )
    sampled = ["DON23L13", "AMA23L12", "HER23L16"]

    result = informe_contract.load_graph_patterns(path, sampled)

    assert result == [{"tema": "fauna en vanos", "circuitos": ["DON23L13", "AMA23L12"], "soporte": 2}]


def test_load_graph_patterns_intersects_circuitos_with_sampled_and_recomputes_soporte(tmp_path):
    """A pattern's `circuitos` may include a circuit that is NOT part of the
    current sampled set (e.g. graph staleness) -- it must be intersected with
    `sampled`, `soporte` recomputed from the intersection, and dropped if the
    recomputed soporte falls below 2.
    """
    path = tmp_path / "graph-patterns.json"
    _write_graph_patterns_json(
        path,
        [
            # 3 circuitos claimed, but only 2 are in the current sample ->
            # recomputed soporte = 2, kept.
            {"tema": "fauna en vanos", "circuitos": ["DON23L13", "AMA23L12", "NOTSAMPLED"], "soporte": 3},
            # 2 circuitos claimed, only 1 is in the current sample ->
            # recomputed soporte = 1, dropped.
            {"tema": "clima aislado", "circuitos": ["HER23L16", "OTHERSTALE"], "soporte": 2},
        ],
    )
    sampled = ["DON23L13", "AMA23L12", "HER23L16"]

    result = informe_contract.load_graph_patterns(path, sampled)

    assert len(result) == 1
    assert result[0]["tema"] == "fauna en vanos"
    assert set(result[0]["circuitos"]) == {"DON23L13", "AMA23L12"}
    assert result[0]["soporte"] == 2


def test_load_graph_patterns_missing_path_returns_none(tmp_path):
    missing_path = tmp_path / "does-not-exist.json"

    result = informe_contract.load_graph_patterns(missing_path, ["DON23L13"])

    assert result is None


def test_load_graph_patterns_none_path_returns_none():
    assert informe_contract.load_graph_patterns(None, ["DON23L13"]) is None


def test_load_graph_patterns_malformed_json_returns_empty_list_never_raises(tmp_path):
    path = tmp_path / "graph-patterns.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json::", encoding="utf-8")

    result = informe_contract.load_graph_patterns(path, ["DON23L13"])

    assert result == []


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
    frame = _four_tier_raw_df(per_tier=2)
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
    assert len(outcome.sampled) == 12


def test_resolve_awaiting_confirmation_without_missing_runs(monkeypatch, tmp_path):
    frame = _four_tier_raw_df(per_tier=2)
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


def test_resolve_never_loads_content_or_writes_output_declined_confirmation_safe(monkeypatch, tmp_path):
    """Task 6.4 (declined-confirmation path): `resolve()` (the SKILL runbook's
    step 1) never calls `load_circuit_content` or writes any file -- it only
    computes and returns the status matrix. If the user declines at the
    single checkpoint, the runbook simply never calls `render`/
    `render_and_write`, so there is nothing to undo: the declined path is
    safe by construction, not by an extra runtime guard.
    """
    frame = _four_tier_raw_df(per_tier=2)
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    monkeypatch.setattr(
        informe_contract, "resolve_group_dataframe", lambda *a, **k: _known_tier_df_coords_with_distance()
    )

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("resolve() must never touch content loading or file writes")

    monkeypatch.setattr(informe_contract, "load_circuit_content", _fail_if_called)
    monkeypatch.setattr(informe_contract, "atomic_write_text", _fail_if_called)

    request = informe_contract.normalize_request("muy-alta", runtime="claude")
    outcome = informe_contract.resolve(request, data_path="data.csv", runs_root=tmp_path / "runs")

    assert outcome.status == "awaiting_confirmation"


def test_resolve_empty_group_status(monkeypatch):
    frame = pd.DataFrame({"CIRCUITO": ["C1"], "FECHA": ["2026-01-01"], "UITI_VANO": ["1"]})
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    empty_df = pd.DataFrame({"criticidad": []}, index=pd.Index([], name="CIRCUITO"))
    monkeypatch.setattr(informe_contract, "resolve_group_dataframe", lambda *a, **k: empty_df)

    request = informe_contract.normalize_request("baja")
    outcome = informe_contract.resolve(request, data_path="data.csv")

    assert outcome.status == "empty_group"
    assert outcome.sampled == []


def test_resolve_usage_error_invalid_grupo_rejected_before_computation():
    with pytest.raises(ValueError, match="grupo desconocido"):
        informe_contract.normalize_request("critica")


def test_resolve_execution_error_wraps_value_error(monkeypatch):
    frame = _four_tier_raw_df(per_tier=2)
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
    frame = _four_tier_raw_df(per_tier=2)
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


def _known_tier_df_coords_full() -> pd.DataFrame:
    """Same shape `render_and_write` needs end to end: `event_count` and
    `uiti_vano_sum` alongside `criticidad`/`centroid_distance`.
    """
    names = [f"MUYALTA_{i}" for i in range(3)]
    df = pd.DataFrame(
        {
            "event_count": [40.0, 41.0, 39.0],
            "uiti_vano_sum": [50000.0, 51000.0, 49000.0],
            "criticidad": ["Muy Alta"] * 3,
            "centroid_distance": [0.0, 1.0, 2.0],
        },
        index=pd.Index(names, name="CIRCUITO"),
    )
    return df


def test_render_and_write_persists_html_and_returns_success(monkeypatch, tmp_path):
    frame = _four_tier_raw_df(per_tier=2)
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    df_coords = _known_tier_df_coords_full()
    monkeypatch.setattr(informe_contract, "resolve_group_dataframe", lambda *a, **k: df_coords)
    monkeypatch.setattr(
        informe_contract,
        "load_circuit_content",
        lambda circuito, **kwargs: {"circuito": circuito, "source": "vault_note", "content": f"Narrativa {circuito}"},
    )
    output_root = tmp_path / "html"

    request = informe_contract.normalize_request("muy-alta", "2026-01-01", "2026-01-02", runtime="claude")
    outcome = informe_contract.render_and_write(request, data_path="data.csv", output_root=output_root)

    assert outcome.status == "success"
    assert outcome.output_html is not None
    written_path = Path(outcome.output_html)
    assert written_path.is_file()
    content = written_path.read_text(encoding="utf-8")
    assert "Plotly.newPlot" in content
    assert "Resumen ejecutivo" in content
    assert len(outcome.sampled) == 3


def test_cli_render_exit_code_matches_status(monkeypatch, capsys, tmp_path):
    frame = _four_tier_raw_df(per_tier=2)
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    df_coords = _known_tier_df_coords_full()
    monkeypatch.setattr(informe_contract, "resolve_group_dataframe", lambda *a, **k: df_coords)
    monkeypatch.setattr(
        informe_contract,
        "load_circuit_content",
        lambda circuito, **kwargs: None,  # still missing -- render must still succeed, annex marks it
    )
    output_root = tmp_path / "html"

    exit_code = informe_contract.main(
        [
            "render",
            "muy-alta",
            "2026-01-01",
            "2026-01-02",
            "--data-path",
            "data.csv",
            "--output-root",
            str(output_root),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    assert payload["output_html"] is not None


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


# ---------------------------------------------------------------------------
# synthesize / render_managerial_report (Phase 5, tasks 5.1-5.3)
# ---------------------------------------------------------------------------


def _sampled_records(specs: list[tuple[str, float, float, str]]) -> list[dict]:
    """`specs` = [(circuito, event_count, uiti_vano_sum, criticidad), ...]."""
    return [
        {
            "circuito": circuito,
            "event_count": event_count,
            "uiti_vano_sum": uiti_vano_sum,
            "criticidad": criticidad,
            "centroid_distance": 0.0,
        }
        for circuito, event_count, uiti_vano_sum, criticidad in specs
    ]


def test_synthesize_returns_all_required_sections_with_real_content():
    sampled_records = _sampled_records(
        [
            ("C01", 40, 50000.0, "Muy Alta"),
            ("C02", 42, 52000.0, "Muy Alta"),
            # C03 is a genuine numeric outlier: UITI_VANO far above the
            # group median AND event_count far below it (high risk, sparse
            # activity) -- the exact cross-circuit pattern synthesize()
            # must surface.
            ("C03", 5, 500000.0, "Muy Alta"),
        ]
    )
    loaded_content = [
        {"circuito": "C01", "source": "vault_note", "content": "Texto narrativo C01 sobre riesgo alto."},
        {"circuito": "C02", "source": "raw_json", "content": "Texto narrativo C02."},
        None,  # missing content even after auto-trigger (edge case)
    ]
    group = {"slug": "muy-alta", "label": "Muy Alta", "circuit_count": 3}

    result = synthesize(sampled_records, loaded_content, group)

    # resumen_ejecutivo is now a list of 5-7 short items (never a single
    # descriptive paragraph), and real (derived from the inputs, not
    # hardcoded placeholders).
    resumen = result["resumen_ejecutivo"]
    assert isinstance(resumen, list)
    assert 5 <= len(resumen) <= 7
    assert any("Muy Alta" in item for item in resumen)
    # Never cites the internal JSON/markdown artifacts -- only the circuit's
    # own HTML report or PDF base documents are citable.
    assert not any(".json" in item.lower() or ".md" in item.lower() for item in resumen)

    assert result["patrones_comunes"]
    assert any("Muy Alta" in p for p in result["patrones_comunes"])
    # patrones_comunes must never name the internal content-sourcing format.
    assert not any("json" in p.lower() or "bóveda" in p.lower() for p in result["patrones_comunes"])

    outlier_names = {item["circuito"] for item in result["circuitos_atipicos"]}
    assert "C03" in outlier_names
    assert "C01" not in outlier_names
    assert "C02" not in outlier_names

    riesgo = result["riesgo_agregado"]
    assert riesgo["uiti_vano_total"] == pytest.approx(50000.0 + 52000.0 + 500000.0)
    assert riesgo["circuitos_sin_contenido"] == 1
    assert isinstance(riesgo["items"], list) and riesgo["items"]

    assert result["acciones_recomendadas"]
    assert any("C03" in action for action in result["acciones_recomendadas"])

    assert len(result["anexo_por_circuito"]) == 3
    missing_entry = next(e for e in result["anexo_por_circuito"] if e["circuito"] == "C03")
    assert missing_entry["fuente"] == "sin_contenido"
    assert missing_entry["report_html"] is None
    present_entry = next(e for e in result["anexo_por_circuito"] if e["circuito"] == "C01")
    assert present_entry["fuente"] == "vault_note"
    assert any("C01" in line or "riesgo alto" in line for line in present_entry["resumen"])


def test_annex_per_circuit_summary_uses_structured_findings_when_available():
    """When headline/key_finding_titles/cause_hypothesis_note are available
    (the normal case -- `load_circuit_content` always populates these via
    `_structured_fields` when a run_dir is resolvable), the annex must show a
    short, human-readable 3-4 line summary built from THOSE fields, never a
    dump of the full raw narrative text.
    """
    long_raw_text = "Frase técnica extensa sobre causas y variables. " * 15  # ~735 chars
    sampled_records = _sampled_records([("C01", 40, 50000.0, "Muy Alta")])
    loaded_content = [
        {
            "circuito": "C01",
            "source": "vault_note",
            "content": long_raw_text,
            "headline": "Pico crítico el 2026-03-02 por falla de transformador.",
            "key_finding_titles": [
                "Concentración de UITI_VANO en un solo evento",
                "Recurrencia de vanos en fallas de línea MT",
            ],
            "cause_hypothesis_note": "Posible degradación del transformador de distribución.",
            "variables_a_priorizar": [{"variable": "CNT_TRF", "prioridad": "alta"}],
        }
    ]
    group = {"slug": "muy-alta", "label": "Muy Alta", "circuit_count": 1}

    result = synthesize(sampled_records, loaded_content, group)

    entry = result["anexo_por_circuito"][0]
    resumen = entry["resumen"]
    assert isinstance(resumen, list)
    assert 3 <= len(resumen) <= 4
    assert any("Pico crítico" in line for line in resumen)
    assert any("Concentración de UITI_VANO" in line for line in resumen)
    # The full raw narrative text must never land verbatim in the summary --
    # that is exactly the unreadable-table bug this behavior replaces.
    assert not any(long_raw_text in line for line in resumen)
    assert "resumen" in entry
    assert "extracto" not in entry


def _hypothesis_entry(resumen: list) -> dict:
    return next(item for item in resumen if isinstance(item, dict) and item.get("label") == "Hipótesis de causa")


def test_annex_hypothesis_shown_as_single_subitem_when_it_fits():
    """A short, single-clause cause_hypothesis_note (the common case) still
    renders as the "Hipótesis de causa" sub-item structure -- one item in
    `items`, COMPLETE, never truncated -- so the shape is the SAME on every
    run regardless of how long a given hypothesis happens to be (design:
    "consistent flow across runs").
    """
    short_cause = "Posible degradación del transformador de distribución."
    sampled_records = _sampled_records([("C01", 40, 50000.0, "Muy Alta")])
    loaded_content = [
        {"circuito": "C01", "source": "vault_note", "content": "x", "cause_hypothesis_note": short_cause}
    ]
    group = {"slug": "muy-alta", "label": "Muy Alta", "circuit_count": 1}

    result = synthesize(sampled_records, loaded_content, group)
    resumen = result["anexo_por_circuito"][0]["resumen"]

    entry = _hypothesis_entry(resumen)
    assert entry == {"label": "Hipótesis de causa", "items": [short_cause]}


def test_annex_hypothesis_split_into_subitems_by_clause_when_long():
    """A long, real-world-shaped hypothesis (multiple ';'/'.'-separated
    points packed into one long sentence, as historical.out.json's agent
    output actually produces) is split into one sub-item PER CLAUSE -- never
    truncated, never an ellipsis, and every word of the original text is
    preserved across the joined sub-items. A manager acting on the annex
    needs the full cause hypothesis presented as scannable points, not a
    partial excerpt or one dense paragraph.
    """
    long_cause = (
        "Dentro de las variables disponibles, el comportamiento del UITI_VANO es compatible "
        "con una combinacion de dos mecanismos: (1) eventos puntuales de alta severidad, como "
        "la falla de linea de media tension y contacto de fauna del 13 de abril de 2026 y el "
        "evento de condiciones atmosfericas del 28 de febrero de 2026, ambos con alta duracion "
        "acumulada segun las variables DURACION y DESC_CAUSA; y (2) una exposicion topologica "
        "recurrente en un subconjunto reducido de vanos, compatible con las variables FID_VANO, "
        "CNT_VN y LVSW del grupo Topologia. Las variables de Entorno/Riesgo, en particular NR_T "
        "y DDT junto con las series de viento y precipitacion, son compatibles con un rol "
        "modulador adicional sobre la frecuencia y severidad, pero el contexto entregado no "
        "permite aislar su contribucion especifica por vano."
    )
    sampled_records = _sampled_records([("C01", 40, 50000.0, "Muy Alta")])
    loaded_content = [
        {"circuito": "C01", "source": "vault_note", "content": "x", "cause_hypothesis_note": long_cause}
    ]
    group = {"slug": "muy-alta", "label": "Muy Alta", "circuit_count": 1}

    result = synthesize(sampled_records, loaded_content, group)
    resumen = result["anexo_por_circuito"][0]["resumen"]

    entry = _hypothesis_entry(resumen)
    items = entry["items"]

    assert len(items) > 1  # actually split into multiple sub-items
    assert not any("…" in item for item in items)
    # No word lost: rejoining every sub-item reproduces the whitespace-
    # collapsed original exactly.
    collapsed_original = " ".join(long_cause.split())
    assert " ".join(items) == collapsed_original


def test_annex_hypothesis_with_newlines_is_whitespace_collapsed_but_complete():
    """A hypothesis containing embedded newlines/extra spacing (as raw agent
    JSON sometimes carries) still lands complete in the annex sub-items, with
    only whitespace collapsed -- not one word of content dropped.
    """
    cause_with_newlines = "Falla de linea de\nmedia tension  rota,   confirmada por dos eventos independientes."
    sampled_records = _sampled_records([("C01", 40, 50000.0, "Muy Alta")])
    loaded_content = [
        {"circuito": "C01", "source": "vault_note", "content": "x", "cause_hypothesis_note": cause_with_newlines}
    ]
    group = {"slug": "muy-alta", "label": "Muy Alta", "circuit_count": 1}

    result = synthesize(sampled_records, loaded_content, group)
    resumen = result["anexo_por_circuito"][0]["resumen"]

    entry = _hypothesis_entry(resumen)
    assert " ".join(entry["items"]) == (
        "Falla de linea de media tension rota, confirmada por dos eventos independientes."
    )
    assert not any("…" in item for item in entry["items"])


def test_annex_html_renders_hypothesis_as_nested_subitem_list():
    """`_annex_html` renders the cause-hypothesis dict entry as a labeled
    `<li>` containing a nested `<ul class='annex-subitems'>`, one `<li>` per
    clause -- not a flat paragraph -- and HTML-escapes each sub-item.
    """
    annex = [
        {
            "circuito": "C01",
            "criticidad": "Muy Alta",
            "fuente": "vault_note",
            "resumen": [
                "Titular breve.",
                {"label": "Hipótesis de causa", "items": ["Primer punto <raro>.", "Segundo punto."]},
            ],
            "report_html": None,
        }
    ]

    html = informe_contract._annex_html(annex)

    assert "<li>Hipótesis de causa<ul class='annex-subitems'>" in html
    assert "<li>Primer punto &lt;raro&gt;.</li><li>Segundo punto.</li>" in html
    assert "<li>Titular breve.</li>" in html


def test_annex_per_circuit_summary_falls_back_to_shortened_raw_content():
    """Without any structured fields (e.g. a vault note whose run_dir is no
    longer resolvable), the annex falls back to a SHORTENED excerpt of the
    raw content rather than showing nothing -- but it must be short, never
    the full unreadable dump.
    """
    long_text = "Frase técnica extensa sobre causas y variables. " * 15  # ~735 chars
    sampled_records = _sampled_records([("C01", 40, 50000.0, "Muy Alta")])
    loaded_content = [{"circuito": "C01", "source": "raw_json", "content": long_text}]
    group = {"slug": "muy-alta", "label": "Muy Alta", "circuit_count": 1}

    result = synthesize(sampled_records, loaded_content, group)

    entry = result["anexo_por_circuito"][0]
    resumen = entry["resumen"]
    assert isinstance(resumen, list) and resumen
    assert all(len(line) <= 240 for line in resumen)
    assert "…" in resumen[0]


def test_synthesize_with_no_outliers_and_full_content_produces_empty_outlier_list():
    sampled_records = _sampled_records(
        [
            ("D01", 40, 50000.0, "Alta"),
            ("D02", 41, 51000.0, "Alta"),
            ("D03", 39, 49000.0, "Alta"),
        ]
    )
    loaded_content = [
        {"circuito": c, "source": "vault_note", "content": f"Narrativa {c}"} for c in ["D01", "D02", "D03"]
    ]
    group = {"slug": "alta", "label": "Alta", "circuit_count": 3}

    result = synthesize(sampled_records, loaded_content, group)

    assert result["circuitos_atipicos"] == []
    assert result["riesgo_agregado"]["circuitos_sin_contenido"] == 0


def test_executive_summary_has_a_floor_of_5_items_even_with_sparse_content():
    """No outliers, no technical fields in loaded_content (old-shaped
    fixtures/edge cases) -- resumen_ejecutivo must still land at exactly the
    5 baseline items derivable from sampled_records alone, never fewer.
    """
    sampled_records = _sampled_records(
        [
            ("E01", 40, 50000.0, "Alta"),
            ("E02", 41, 51000.0, "Alta"),
        ]
    )
    loaded_content = [{"circuito": c, "source": "vault_note", "content": f"Narrativa {c}"} for c in ["E01", "E02"]]
    group = {"slug": "alta", "label": "Alta", "circuit_count": 2}

    result = synthesize(sampled_records, loaded_content, group)

    assert len(result["resumen_ejecutivo"]) == 5


def test_synthesize_surfaces_cross_circuit_technical_patterns_and_causes():
    """With real technical fields present in loaded_content (as
    `load_circuit_content` now surfaces them), the executive summary and
    common-patterns sections must actually mine and aggregate them --
    shared prioritized variables, shared technical domains, and shared
    cause themes -- not just quantitative counts.
    """
    sampled_records = _sampled_records(
        [
            ("F01", 40, 50000.0, "Muy Alta"),
            ("F02", 41, 51000.0, "Muy Alta"),
            ("F03", 39, 49000.0, "Muy Alta"),
        ]
    )
    loaded_content = [
        {
            "circuito": "F01",
            "source": "raw_json",
            "content": "Síntesis F01.",
            "variables_a_priorizar": [{"variable": "CNT_VN", "prioridad": "alta"}],
            "variable_groups_used": ["Entorno/Riesgo"],
            "cause_hypothesis_note": "Compatible con exposición a fauna en los vanos implicados.",
            "recommended_actions": [],
        },
        {
            "circuito": "F02",
            "source": "raw_json",
            "content": "Síntesis F02.",
            "variables_a_priorizar": [{"variable": "CNT_VN", "prioridad": "media"}],
            "variable_groups_used": ["Entorno/Riesgo"],
            "cause_hypothesis_note": "Ráfaga y viento elevados compatibles con estrés atmosférico.",
            "recommended_actions": [],
        },
        {
            "circuito": "F03",
            "source": "raw_json",
            "content": "Síntesis F03.",
            "variables_a_priorizar": [{"variable": "TIPO", "prioridad": "baja"}],
            "variable_groups_used": ["Proteccion"],
            "cause_hypothesis_note": None,
            "recommended_actions": [],
        },
    ]
    group = {"slug": "muy-alta", "label": "Muy Alta", "circuit_count": 3}

    result = synthesize(sampled_records, loaded_content, group)

    resumen_text = " ".join(result["resumen_ejecutivo"])
    assert "CNT_VN" in resumen_text  # shared prioritized variable surfaced
    assert "fauna" in resumen_text.lower() or "atmosf" in resumen_text.lower()  # cause theme surfaced

    patrones_text = " ".join(result["patrones_comunes"])
    assert "CNT_VN (2/3)" in patrones_text
    assert "Entorno/Riesgo (2/3)" in patrones_text


# ---------------------------------------------------------------------------
# render_managerial_report (Phase 5, tasks 5.2-5.3)
# ---------------------------------------------------------------------------


def test_render_managerial_report_embeds_scatter_and_all_sections():
    raw_df = _four_tier_raw_df(per_tier=2)
    sampled_records = _sampled_records(
        [
            ("MUYALTA_0", 40, 50000.0, "Muy Alta"),
            ("MUYALTA_1", 41, 51000.0, "Muy Alta"),
        ]
    )
    loaded_content = [
        {"circuito": "MUYALTA_0", "source": "vault_note", "content": "Narrativa MUYALTA_0."},
        None,
    ]
    group = {"slug": "muy-alta", "label": "Muy Alta", "circuit_count": 2}
    synthesis = synthesize(sampled_records, loaded_content, group)

    html = render_managerial_report(
        raw_df,
        synthesis=synthesis,
        group=group,
        resolved_window={"fecha_inicio": "2026-01-01", "fecha_fin": "2026-12-31"},
        sampled=["MUYALTA_0", "MUYALTA_1"],
    )

    assert "<title>Informe Gerencial: Circuitos con Criticidad Muy Alta</title>" in html
    assert "<h1>Informe Gerencial: Circuitos con Criticidad Muy Alta</h1>" in html
    assert "Resumen ejecutivo" in html
    assert "Patrones comunes" in html
    assert "Circuitos atípicos" in html
    assert "Riesgo agregado" in html
    assert "Acciones recomendadas" in html
    assert "Anexo por circuito" in html
    # The embedded scatter is real -- Plotly's JS bootstrap call is present,
    # not a placeholder string.
    assert "Plotly.newPlot" in html
    # Real synthesis content actually lands in the page (HTML-escaped, since
    # narrative text may contain user-influenced characters), not just headings
    # -- resumen_ejecutivo/riesgo_agregado are itemized lists now, so every
    # item must land individually.
    for item in synthesis["resumen_ejecutivo"]:
        assert html_lib.escape(item) in html
    for item in synthesis["riesgo_agregado"]["items"]:
        assert html_lib.escape(item) in html


def test_render_managerial_report_full_fleet_scatter_with_only_sampled_highlighted(monkeypatch):
    raw_df = _four_tier_raw_df(per_tier=2)  # 8 circuits across all 4 tiers
    sampled_names = ["MUYALTA_0", "ALTA_0"]
    sampled_records = _sampled_records(
        [
            ("MUYALTA_0", 40, 50000.0, "Muy Alta"),
            ("ALTA_0", 20, 5000.0, "Alta"),
        ]
    )
    loaded_content = [None, None]
    group = {"slug": "todos", "label": None, "circuit_count": 8}
    synthesis = synthesize(sampled_records, loaded_content, group)

    calls: dict = {}
    real_plot = informe_contract.plot_interactive_circuit_clustering

    def _spy(df, *args, **kwargs):
        calls["n_rows"] = len(df)
        calls["highlighted"] = kwargs.get("highlighted_circuits")
        return real_plot(df, *args, **kwargs)

    monkeypatch.setattr(informe_contract, "plot_interactive_circuit_clustering", _spy)

    html = render_managerial_report(
        raw_df,
        synthesis=synthesis,
        group=group,
        resolved_window={"fecha_inicio": "2026-01-01", "fecha_fin": "2026-12-31"},
        sampled=sampled_names,
    )

    # The FULL, unfiltered raw_df was passed to the shared clustering plot --
    # never a subset limited to the sampled/highlighted circuits.
    assert calls["n_rows"] == len(raw_df)
    assert calls["highlighted"] == sampled_names
    # Circuits from tiers/groups OUTSIDE the sampled set are still visible in
    # the rendered scatter (nothing hidden -- only highlighting differs).
    assert "MEDIA_0" in html
    assert "BAJA_1" in html


# ---------------------------------------------------------------------------
# Cross-circuit graph-patterns render states + CLI flag (Phase 3, tasks 3.1-3.7)
# ---------------------------------------------------------------------------


def _render_report_html(
    *,
    raw_df=None,
    sampled: list[str],
    graph_patterns=None,
) -> str:
    """Shared helper: render with a minimal single-circuit-per-sample setup,
    varying only `sampled`/`graph_patterns` (the two inputs the graph-section
    render states key off of).
    """
    if raw_df is None:
        raw_df = _four_tier_raw_df(per_tier=2)
    sampled_records = _sampled_records(
        [(name, 40, 50000.0, "Muy Alta") for name in sampled]
    )
    loaded_content = [None] * len(sampled)
    group = {"slug": "muy-alta", "label": "Muy Alta", "circuit_count": len(sampled)}
    synthesis = synthesize(sampled_records, loaded_content, group)
    return render_managerial_report(
        raw_df,
        synthesis=synthesis,
        group=group,
        resolved_window={"fecha_inicio": "2026-01-01", "fecha_fin": "2026-12-31"},
        sampled=sampled,
        graph_patterns=graph_patterns,
    )


def test_render_managerial_report_omits_graph_section_when_fewer_than_2_sampled():
    html = _render_report_html(sampled=["MUYALTA_0"], graph_patterns=[{"tema": "x", "circuitos": ["MUYALTA_0"], "soporte": 2}])

    assert "Patrones cross-circuito" not in html


def test_render_managerial_report_graph_section_muted_when_patterns_none():
    html = _render_report_html(sampled=["MUYALTA_0", "MUYALTA_1"], graph_patterns=None)

    assert "Patrones cross-circuito" in html
    assert "análisis de grafo no disponible en esta corrida" in html


def test_render_managerial_report_graph_section_muted_when_patterns_empty():
    html = _render_report_html(sampled=["MUYALTA_0", "MUYALTA_1"], graph_patterns=[])

    assert "Patrones cross-circuito" in html
    assert "sin patrones recurrentes con soporte" in html


def test_render_managerial_report_graph_section_lists_patterns_with_provenance_badge():
    patterns = [{"tema": "fauna en vanos", "circuitos": ["MUYALTA_0", "MUYALTA_1"], "soporte": 2}]

    html = _render_report_html(sampled=["MUYALTA_0", "MUYALTA_1"], graph_patterns=patterns)

    assert "fauna en vanos" in html
    assert "MUYALTA_0" in html and "MUYALTA_1" in html
    assert "soporte 2" in html
    # Explicit LLM-assisted provenance badge, visibly distinct from the
    # deterministic "Patrones comunes" table (spec: "Provenance labeling").
    assert "Interpretación asistida por LLM (grafo)" in html


def test_render_managerial_report_patrones_comunes_labeled_deterministic():
    html = _render_report_html(sampled=["MUYALTA_0", "MUYALTA_1"], graph_patterns=None)

    assert "Cálculo determinista" in html


def test_cli_render_passes_graph_patterns_path_through_to_output(monkeypatch, capsys, tmp_path):
    frame = _four_tier_raw_df(per_tier=2)
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    df_coords = _known_tier_df_coords_full()
    monkeypatch.setattr(informe_contract, "resolve_group_dataframe", lambda *a, **k: df_coords)
    monkeypatch.setattr(
        informe_contract,
        "load_circuit_content",
        lambda circuito, **kwargs: {"circuito": circuito, "source": "vault_note", "content": f"Narrativa {circuito}"},
    )
    output_root = tmp_path / "html"
    graph_patterns_path = tmp_path / "graph-patterns.json"
    _write_graph_patterns_json(
        graph_patterns_path,
        [{"tema": "fauna en vanos", "circuitos": ["MUYALTA_0", "MUYALTA_1", "MUYALTA_2"], "soporte": 3}],
    )

    exit_code = informe_contract.main(
        [
            "render",
            "muy-alta",
            "2026-01-01",
            "2026-01-02",
            "--data-path",
            "data.csv",
            "--output-root",
            str(output_root),
            "--graph-patterns",
            str(graph_patterns_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    written = Path(payload["output_html"]).read_text(encoding="utf-8")
    assert "fauna en vanos" in written
    assert "Interpretación asistida por LLM (grafo)" in written


# ---------------------------------------------------------------------------
# Graph-view embed: `<ul>/<li>` structural guard + load_graph_view + 3-way
# states + CLI arg (Phase 4, tasks 4.1-4.4)
# ---------------------------------------------------------------------------


_LI_ITEM_RE = re.compile(r"<li>.*?</li>", re.DOTALL)


def test_graph_patterns_html_renders_ul_li_structural():
    """Locks the ALREADY-correct itemized-list rendering: a populated
    pattern list must produce real `<ul>`/`<li>` elements (structural, not
    substring-only), guarding against regression to non-list rendering
    (spec: "Itemized patterns list is structurally verifiable").
    """
    patterns = [
        {"tema": "fauna en vanos", "circuitos": ["MUYALTA_0", "MUYALTA_1"], "soporte": 2},
        {"tema": "clima aislado", "circuitos": ["MUYALTA_0", "MUYALTA_2"], "soporte": 2},
    ]

    html = informe_contract._graph_patterns_html(patterns, None, n_sampled=2)

    ul_match = re.search(r"<ul>(.*?)</ul>", html, re.DOTALL)
    assert ul_match is not None
    li_items = _LI_ITEM_RE.findall(ul_match.group(1))
    assert len(li_items) == 2
    assert "fauna en vanos" in li_items[0]
    assert "clima aislado" in li_items[1]


def test_load_graph_view_missing_or_omitted_path_returns_none(tmp_path):
    assert informe_contract.load_graph_view(None) is None
    assert informe_contract.load_graph_view(tmp_path / "does-not-exist.html") is None


def test_load_graph_view_readable_path_returns_raw_html(tmp_path):
    path = tmp_path / "graph-view.html"
    path.write_text("<html><body>grafo</body></html>", encoding="utf-8")

    result = informe_contract.load_graph_view(path)

    assert result == "<html><body>grafo</body></html>"


def test_load_graph_view_unreadable_path_degrades_to_none(tmp_path):
    directory_as_path = tmp_path / "not-a-file"
    directory_as_path.mkdir()

    result = informe_contract.load_graph_view(directory_as_path)

    assert result is None


@pytest.mark.parametrize(
    "graph_patterns,graph_view_html,expect_ul,expect_figure,expect_muted_no_figure",
    [
        # patterns present + view present -> <ul> list + embedded figure.
        (
            [{"tema": "fauna en vanos", "circuitos": ["MUYALTA_0", "MUYALTA_1"], "soporte": 2}],
            "<html><body>view</body></html>",
            True,
            True,
            False,
        ),
        # patterns present + view None -> list only, muted figure-unavailable indicator.
        (
            [{"tema": "fauna en vanos", "circuitos": ["MUYALTA_0", "MUYALTA_1"], "soporte": 2}],
            None,
            True,
            False,
            True,
        ),
        # patterns None + view present -> existing muted "no data" state, no figure.
        (None, "<html><body>view</body></html>", False, False, False),
        # patterns [] + view present -> existing muted "no pattern" state, no figure.
        ([], "<html><body>view</body></html>", False, False, False),
    ],
)
def test_graph_patterns_html_three_way_graph_embed_states(
    graph_patterns, graph_view_html, expect_ul, expect_figure, expect_muted_no_figure
):
    html = informe_contract._graph_patterns_html(graph_patterns, graph_view_html, n_sampled=2)

    assert ("<ul>" in html) is expect_ul
    assert ("srcdoc=" in html) is expect_figure
    assert ("figura de grafo no disponible en esta corrida" in html) is expect_muted_no_figure


def test_cli_render_accepts_graph_view_arg(monkeypatch, capsys, tmp_path):
    frame = _four_tier_raw_df(per_tier=2)
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    df_coords = _known_tier_df_coords_full()
    monkeypatch.setattr(informe_contract, "resolve_group_dataframe", lambda *a, **k: df_coords)
    monkeypatch.setattr(
        informe_contract,
        "load_circuit_content",
        lambda circuito, **kwargs: {"circuito": circuito, "source": "vault_note", "content": f"Narrativa {circuito}"},
    )
    output_root = tmp_path / "html"
    graph_view_path = tmp_path / "graph-view.html"
    graph_view_path.write_text("<html><body>vista de grafo</body></html>", encoding="utf-8")
    graph_patterns_path = tmp_path / "graph-patterns.json"
    _write_graph_patterns_json(
        graph_patterns_path,
        [{"tema": "fauna en vanos", "circuitos": ["MUYALTA_0", "MUYALTA_1", "MUYALTA_2"], "soporte": 3}],
    )

    exit_code = informe_contract.main(
        [
            "render",
            "muy-alta",
            "2026-01-01",
            "2026-01-02",
            "--data-path",
            "data.csv",
            "--output-root",
            str(output_root),
            "--graph-patterns",
            str(graph_patterns_path),
            "--graph-view",
            str(graph_view_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    written = Path(payload["output_html"]).read_text(encoding="utf-8")
    assert "srcdoc=" in written


# ---------------------------------------------------------------------------
# Dual-graph toggle: circular graph embed + CLI flag (Phase 4-5, PR2)
# ---------------------------------------------------------------------------


_PATTERNS_FOR_TOGGLE = [{"tema": "fauna en vanos", "circuitos": ["MUYALTA_0", "MUYALTA_1"], "soporte": 2}]


def test_graph_patterns_html_both_graphs_available_renders_toggle_circular_default_visible():
    """Spec 'Dual-Graph Toggle', scenario 'Both graphs available': both
    iframe srcdoc blocks embed, a client-side toggle control + inline script
    are present, and the circular graph is the one visible on load (design
    D4 -- circular answers the manager's cross-circuit question at a
    glance; community graph starts hidden, reachable via the toggle).
    """
    view_html = "<html><body>vista de comunidad</body></html>"
    circular_html = "<html><body>vista circular</body></html>"

    html = informe_contract._graph_patterns_html(
        _PATTERNS_FOR_TOGGLE, view_html, circular_html, n_sampled=2
    )

    assert html.count("srcdoc=") == 2
    assert "<script>" in html
    # A visible client-side control (button/tab pair) to switch graphs.
    assert "graph-toggle" in html
    # Circular panel has no inline "display:none" (visible by default);
    # community panel does (hidden until the reader toggles it).
    circular_panel = re.search(r'<div id="graph-toggle-circular"[^>]*>', html)
    community_panel = re.search(r'<div id="graph-toggle-community"[^>]*>', html)
    assert circular_panel is not None and community_panel is not None
    assert "display:none" not in circular_panel.group(0)
    assert "display:none" in community_panel.group(0)


def test_graph_patterns_html_switch_does_not_reload_page():
    """Toggle script mutates DOM (`style.display`) only -- no `location`/
    `href`/form-submit reload anywhere in the emitted script.
    """
    html = informe_contract._graph_patterns_html(
        _PATTERNS_FOR_TOGGLE,
        "<html><body>vista de comunidad</body></html>",
        "<html><body>vista circular</body></html>",
        n_sampled=2,
    )

    assert "location.href" not in html
    assert "location.reload" not in html
    assert "<form" not in html


def test_graph_patterns_html_only_circular_available_single_graph_no_toggle():
    """Spec 'Only one graph available': only the available figure embeds,
    no toggle control shown.
    """
    html = informe_contract._graph_patterns_html(
        _PATTERNS_FOR_TOGGLE, None, "<html><body>vista circular</body></html>", n_sampled=2
    )

    assert html.count("srcdoc=") == 1
    assert "vista circular" in html
    assert "graph-toggle-btn" not in html
    assert "figura de grafo no disponible en esta corrida" not in html


def test_graph_patterns_html_only_community_available_single_graph_no_toggle():
    html = informe_contract._graph_patterns_html(
        _PATTERNS_FOR_TOGGLE, "<html><body>vista de comunidad</body></html>", None, n_sampled=2
    )

    assert html.count("srcdoc=") == 1
    assert "vista de comunidad" in html
    assert "graph-toggle-btn" not in html


def test_graph_patterns_html_neither_graph_available_muted_state_unaffected():
    """Spec 'Neither graph available': same existing muted indicator as
    before this change -- unaffected by the new toggle wiring.
    """
    html = informe_contract._graph_patterns_html(_PATTERNS_FOR_TOGGLE, None, None, n_sampled=2)

    assert "figura de grafo no disponible en esta corrida" in html
    assert "srcdoc=" not in html
    assert "graph-toggle-btn" not in html


def test_render_managerial_report_threads_graph_circular_html():
    """`render_managerial_report` accepts `graph_circular_html` and threads
    it into the assembled graph section alongside the existing
    `graph_view_html`.
    """
    html = _render_report_html(
        sampled=["MUYALTA_0", "MUYALTA_1"], graph_patterns=_PATTERNS_FOR_TOGGLE
    )
    # Baseline (no circular graph passed through the helper): single graph,
    # no toggle -- confirms the parameter is genuinely optional/additive.
    assert "graph-toggle-btn" not in html

    raw_df = _four_tier_raw_df(per_tier=2)
    sampled_records = _sampled_records([("MUYALTA_0", 40, 50000.0, "Muy Alta"), ("MUYALTA_1", 41, 51000.0, "Muy Alta")])
    loaded_content = [None, None]
    group = {"slug": "muy-alta", "label": "Muy Alta", "circuit_count": 2}
    synthesis = synthesize(sampled_records, loaded_content, group)

    html_with_both = render_managerial_report(
        raw_df,
        synthesis=synthesis,
        group=group,
        resolved_window={"fecha_inicio": "2026-01-01", "fecha_fin": "2026-12-31"},
        sampled=["MUYALTA_0", "MUYALTA_1"],
        graph_patterns=_PATTERNS_FOR_TOGGLE,
        graph_view_html="<html><body>vista de comunidad</body></html>",
        graph_circular_html="<html><body>vista circular</body></html>",
    )

    assert html_with_both.count("srcdoc=") == 2
    assert "graph-toggle-btn" in html_with_both


def test_render_and_write_loads_graph_circular_path_and_embeds(monkeypatch, tmp_path):
    """`render_and_write(..., graph_circular_path=...)` loads the circular
    HTML via the reused `load_graph_view` (never a new parser) and threads
    it into the final report.
    """
    frame = _four_tier_raw_df(per_tier=2)
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    df_coords = _known_tier_df_coords_full()
    monkeypatch.setattr(informe_contract, "resolve_group_dataframe", lambda *a, **k: df_coords)
    monkeypatch.setattr(
        informe_contract,
        "load_circuit_content",
        lambda circuito, **kwargs: {"circuito": circuito, "source": "vault_note", "content": f"Narrativa {circuito}"},
    )
    output_root = tmp_path / "html"
    graph_patterns_path = tmp_path / "graph-patterns.json"
    _write_graph_patterns_json(
        graph_patterns_path,
        [{"tema": "fauna en vanos", "circuitos": ["MUYALTA_0", "MUYALTA_1", "MUYALTA_2"], "soporte": 3}],
    )
    graph_circular_path = tmp_path / "graph-circular.html"
    graph_circular_path.write_text("<html><body>vista circular</body></html>", encoding="utf-8")

    request = informe_contract.normalize_request("muy-alta", "2026-01-01", "2026-01-02")
    outcome = informe_contract.render_and_write(
        request,
        data_path="data.csv",
        output_root=output_root,
        graph_patterns_path=graph_patterns_path,
        graph_circular_path=graph_circular_path,
    )

    assert outcome.status == "success"
    written = Path(outcome.output_html).read_text(encoding="utf-8")
    assert "vista circular" in written
    assert "srcdoc=" in written


def test_cli_render_accepts_graph_circular_arg(monkeypatch, capsys, tmp_path):
    frame = _four_tier_raw_df(per_tier=2)
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    df_coords = _known_tier_df_coords_full()
    monkeypatch.setattr(informe_contract, "resolve_group_dataframe", lambda *a, **k: df_coords)
    monkeypatch.setattr(
        informe_contract,
        "load_circuit_content",
        lambda circuito, **kwargs: {"circuito": circuito, "source": "vault_note", "content": f"Narrativa {circuito}"},
    )
    output_root = tmp_path / "html"
    graph_patterns_path = tmp_path / "graph-patterns.json"
    _write_graph_patterns_json(
        graph_patterns_path,
        [{"tema": "fauna en vanos", "circuitos": ["MUYALTA_0", "MUYALTA_1", "MUYALTA_2"], "soporte": 3}],
    )
    graph_view_path = tmp_path / "graph-view.html"
    graph_view_path.write_text("<html><body>vista de comunidad</body></html>", encoding="utf-8")
    graph_circular_path = tmp_path / "graph-circular.html"
    graph_circular_path.write_text("<html><body>vista circular</body></html>", encoding="utf-8")

    exit_code = informe_contract.main(
        [
            "render",
            "muy-alta",
            "2026-01-01",
            "2026-01-02",
            "--data-path",
            "data.csv",
            "--output-root",
            str(output_root),
            "--graph-patterns",
            str(graph_patterns_path),
            "--graph-view",
            str(graph_view_path),
            "--graph-circular",
            str(graph_circular_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    written = Path(payload["output_html"]).read_text(encoding="utf-8")
    assert written.count("srcdoc=") == 2
    assert "graph-toggle-btn" in written


# ---------------------------------------------------------------------------
# Phase 7: integration check -- SKILL step 2.5.5 -> 2.5.6/2.5.7 -> step 3
# real pipeline functions chained together (no mocked graph-patterns/graph-
# circular/graph-view HTML strings), confirming the wiring the SKILL.md
# sub-step 2.5.7 runbook prose describes actually holds end to end.
# ---------------------------------------------------------------------------


def test_e2e_real_circuit_meta_graph_output_threads_into_render_and_write(monkeypatch, tmp_path):
    """The SKILL runbook's 2.5.5 -> 2.5.7 -> step 3 chain, exercised for
    real: a real `graph-patterns.<grupo>.<win>.json` file is fed to the REAL
    `circuit_meta_graph.build_circuit_meta_graph` (production code, not a
    hand-typed HTML stub), and that real output file is then loaded by
    `render_and_write(..., graph_circular_path=...)` via the reused
    `load_graph_view`. Only the circular graph is available this run (no
    `graph_view_path`), so this also exercises the "only one graph
    available -> single embed, no toggle" degrade state (spec "Dual-Graph
    Toggle") using a REAL circular-graph payload instead of a stub string.
    """
    frame = _four_tier_raw_df(per_tier=2)
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    df_coords = _known_tier_df_coords_full()
    monkeypatch.setattr(informe_contract, "resolve_group_dataframe", lambda *a, **k: df_coords)
    monkeypatch.setattr(
        informe_contract,
        "load_circuit_content",
        lambda circuito, **kwargs: {"circuito": circuito, "source": "vault_note", "content": f"Narrativa {circuito}"},
    )
    sampled = ["MUYALTA_0", "MUYALTA_1", "MUYALTA_2"]

    # Sub-step 2.5.5: the graph-patterns JSON the SKILL's own graphify-query
    # parsing step would have written.
    graph_patterns_path = tmp_path / "graph-patterns.muy-alta.2026-01-01_2026-01-02.json"
    _write_graph_patterns_json(
        graph_patterns_path,
        [
            {"tema": "fauna en vanos cercanos", "circuitos": sampled, "soporte": 3},
            {"tema": "vegetacion recurrente", "circuitos": ["MUYALTA_0", "MUYALTA_1"], "soporte": 2},
        ],
    )

    # Sub-step 2.5.7: the REAL circuit_meta_graph CLI/builder, run exactly as
    # the SKILL.md runbook prose describes (module import, not a subprocess
    # -- same production entry point `build_circuit_meta_graph`).
    graph_circular_path = tmp_path / "graph-circular.muy-alta.2026-01-01_2026-01-02.html"
    circular_outcome = circuit_meta_graph.build_circuit_meta_graph(
        graph_patterns_path, sampled, graph_circular_path
    )
    assert circular_outcome.status == "success"
    assert circular_outcome.node_count > 0
    assert graph_circular_path.is_file()

    request = informe_contract.normalize_request("muy-alta", "2026-01-01", "2026-01-02")
    outcome = informe_contract.render_and_write(
        request,
        data_path="data.csv",
        output_root=tmp_path / "html",
        graph_patterns_path=graph_patterns_path,
        graph_circular_path=graph_circular_path,
    )

    assert outcome.status == "success"
    written = Path(outcome.output_html).read_text(encoding="utf-8")
    # The real circular-graph HTML (produced by production code, never a
    # stub) is embedded verbatim inside the report's iframe srcdoc.
    real_circular_html = graph_circular_path.read_text(encoding="utf-8")
    assert html_lib.escape(real_circular_html) in written
    # A real node label from the meta-graph (a sampled circuit id) is
    # present, proving the layout/render actually ran rather than the
    # embed short-circuiting on an empty graph.
    assert "MUYALTA_0" in real_circular_html
    # Only one figure is available this run -> no toggle control, per the
    # 3-way degrade contract.
    assert written.count("srcdoc=") == 1
    assert "graph-toggle-btn" not in written
    assert "fauna en vanos cercanos" in written


def test_e2e_real_circular_and_community_graphs_toggle_and_community_unaffected(monkeypatch, tmp_path):
    """Both figures built for real this time: `circuit_meta_graph` (fully
    real, no external dependency) AND `graph_view_builder.build_graph_view`
    (real seed/bridge filtering; only its own `graphify.export.to_html` leaf
    call is monkeypatched, exactly the same convention
    `tests/test_graph_view_builder.py` already uses to keep this test
    hermetic/fast without a live graphify invocation). Confirms: (1) both
    real outputs thread through `render_and_write` into a toggle with the
    circular graph visible by default, and (2) the community graph's own
    embedded content is BYTE-IDENTICAL to what `build_graph_view` produced
    standalone -- i.e. adding the circular graph never mutates or degrades
    the existing community graph (task 7.2's "existing community graph
    unaffected" acceptance criterion).
    """
    frame = _four_tier_raw_df(per_tier=2)
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    df_coords = _known_tier_df_coords_full()
    monkeypatch.setattr(informe_contract, "resolve_group_dataframe", lambda *a, **k: df_coords)
    monkeypatch.setattr(
        informe_contract,
        "load_circuit_content",
        lambda circuito, **kwargs: {"circuito": circuito, "source": "vault_note", "content": f"Narrativa {circuito}"},
    )
    sampled = ["MUYALTA_0", "MUYALTA_1", "MUYALTA_2"]

    graph_patterns_path = tmp_path / "graph-patterns.muy-alta.2026-01-01_2026-01-02.json"
    _write_graph_patterns_json(
        graph_patterns_path,
        [{"tema": "fauna en vanos cercanos", "circuitos": sampled, "soporte": 3}],
    )

    graph_circular_path = tmp_path / "graph-circular.muy-alta.2026-01-01_2026-01-02.html"
    circular_outcome = circuit_meta_graph.build_circuit_meta_graph(
        graph_patterns_path, sampled, graph_circular_path
    )
    assert circular_outcome.status == "success"

    def _fake_to_html(G, communities, output, **kwargs):
        Path(output).write_text(
            f"<html><body>vista de comunidad ({len(list(G.nodes()))} nodos)</body></html>",
            encoding="utf-8",
        )

    monkeypatch.setattr(graph_view_builder, "to_html", _fake_to_html)

    graph_json_path = tmp_path / "graph.json"
    nodes = [
        {
            "id": f"{canonical_circuit_identity(c)}_node",
            "label": c,
            "source_file": f"reports/vault/{canonical_circuit_identity(c)}.md",
            "community": index,
        }
        for index, c in enumerate(sampled)
    ]
    links = [
        {"source": f"{canonical_circuit_identity(sampled[0])}_node", "target": f"{canonical_circuit_identity(sampled[1])}_node"}
    ]
    graph_json_path.write_text(
        json.dumps({"directed": False, "multigraph": False, "graph": {}, "nodes": nodes, "links": links}),
        encoding="utf-8",
    )

    graph_view_path = tmp_path / "graph-view.muy-alta.2026-01-01_2026-01-02.html"
    view_outcome = graph_view_builder.build_graph_view(graph_json_path, sampled, graph_view_path)
    assert view_outcome.status == "success"
    standalone_view_html = graph_view_path.read_text(encoding="utf-8")

    request = informe_contract.normalize_request("muy-alta", "2026-01-01", "2026-01-02")
    outcome = informe_contract.render_and_write(
        request,
        data_path="data.csv",
        output_root=tmp_path / "html",
        graph_patterns_path=graph_patterns_path,
        graph_view_path=graph_view_path,
        graph_circular_path=graph_circular_path,
    )

    assert outcome.status == "success"
    written = Path(outcome.output_html).read_text(encoding="utf-8")

    # Both real figures embedded, toggle control present.
    assert written.count("srcdoc=") == 2
    assert "graph-toggle-btn" in written

    # Circular graph is visible by default, community graph starts hidden.
    circular_panel = re.search(r'<div id="graph-toggle-circular"[^>]*>', written)
    community_panel = re.search(r'<div id="graph-toggle-community"[^>]*>', written)
    assert circular_panel is not None and "display:none" not in circular_panel.group(0)
    assert community_panel is not None and "display:none" in community_panel.group(0)

    # The community graph's embedded content is UNCHANGED by the circular
    # graph's presence -- the same bytes `build_graph_view` wrote standalone
    # are what ends up escaped inside the report's srcdoc.
    assert html_lib.escape(standalone_view_html) in written
