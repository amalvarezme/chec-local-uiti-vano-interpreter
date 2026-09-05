from __future__ import annotations

import html as html_lib
import json
import re
from pathlib import Path

import pandas as pd
import pytest

import chec_local_interpreter.intervention_graph as intervention_graph
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


def _known_tier_df_coords_with_distance() -> pd.DataFrame:
    names = [f"ALTO_{i}" for i in range(25)]
    distances = list(range(25))
    df = _df_coords(names, distances)
    df["criticidad"] = "Riesgo Alto"
    return df


_RADIAL_HTML = "<html><body>grafo radial de causas</body></html>"
_RESUMEN = {
    "schema_version": "informe-gerencial-grafo-intervencion/v1",
    "causas": [{"concepto": "clima/atmosférico", "soporte": 2, "circuitos": ["ALTO_0", "ALTO_1"]}],
    "estrategias": [
        {
            "concepto": "Inspección en campo · CNT_TRF",
            "soporte": 2,
            "prioridad": "alta",
            "circuitos": ["ALTO_0", "ALTO_1"],
        }
    ],
    "circuitos_sin_corrida": [],
}


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


def _df_coords(names: list[str], vanos_criticos: list[float]) -> pd.DataFrame:
    """El marco que devuelve `resolve_group_dataframe`: columnas del ranking."""
    n = len(names)
    return pd.DataFrame(
        {
            "vanos_criticos": [int(v) for v in vanos_criticos],
            "vanos_medio_alto": [int(v) for v in vanos_criticos],
            "vanos_alto": [0] * n,
            "vanos_con_eventos": [int(v) + 10 for v in vanos_criticos],
            "uiti_total": [float(v) * 10 for v in vanos_criticos],
            "eventos_total": [int(v) * 3 for v in vanos_criticos],
            "posicion": list(range(1, n + 1)),
        },
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


def test_sample_representatives_over_threshold_returns_exactly_12_worst():
    names = [f"C{i:02d}" for i in range(37)]
    # C36 es el peor: mas vanos criticos.
    df_coords = _df_coords(names, list(range(37)))

    result = sample_representatives(df_coords)

    assert len(result) == 12
    assert set(result.index) == {f"C{i:02d}" for i in range(25, 37)}
    assert result["vanos_criticos"].min() == 25


def test_sample_representatives_deterministic_tie_break_by_ascending_name():
    # 11 circuitos estrictamente peores son los 11 seguros.
    names = [f"C{i:02d}" for i in range(20, 31)]
    criticos = list(range(20, 31))
    # Dos empatados en el borde: solo uno cabe en los 12. Gana el nombre menor.
    names += ["ZZZ_TIE", "AAA_TIE"]
    criticos += [19, 19]
    df_coords = _df_coords(names, criticos)

    result = sample_representatives(df_coords)
    result_again = sample_representatives(df_coords)

    assert len(result) == 12
    assert "AAA_TIE" in result.index
    assert "ZZZ_TIE" not in result.index
    # Reproducible: la misma entrada elige exactamente los mismos doce.
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
    raw_df = _ranking_raw_df({f"C{i:02d}": i * 8 for i in range(1, 13)}, vanos_por_circuito=110)

    result = resolve_group_dataframe(raw_df, "alto", "Riesgo Alto")

    assert not result.empty
    assert (result["criticidad"] == "Riesgo Alto").all()


def test_resolve_group_dataframe_todos_returns_full_universe():
    raw_df = _ranking_raw_df({f"C{i:02d}": i * 4 for i in range(1, 21)}, vanos_por_circuito=90)

    result = resolve_group_dataframe(raw_df, "todos", None)

    # Entran TODOS los circuitos de la base, incluidos los que quedan en cero.
    assert len(result) == 20
    assert set(result["criticidad"]) <= {
        "Riesgo Bajo", "Riesgo Medio", "Riesgo Medio-Alto", "Riesgo Alto",
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


def test_resolve_awaiting_confirmation_with_missing_runs(monkeypatch, tmp_path):
    frame = _four_tier_raw_df(per_tier=2)
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    monkeypatch.setattr(
        informe_contract, "resolve_group_dataframe", lambda *a, **k: _known_tier_df_coords_with_distance()
    )
    runs_root = tmp_path / "runs"  # empty -- every sampled circuit is missing a run

    request = informe_contract.normalize_request("alto", runtime="claude")
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
    for circuito in df_coords.sort_index().nlargest(20, "vanos_criticos").index:
        _write_valid_run(runs_root, circuito, timestamp="20260101T000000000000")

    request = informe_contract.normalize_request("alto", runtime="claude")
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

    request = informe_contract.normalize_request("alto", runtime="claude")
    outcome = informe_contract.resolve(request, data_path="data.csv", runs_root=tmp_path / "runs")

    assert outcome.status == "awaiting_confirmation"


def test_resolve_empty_group_status(monkeypatch):
    frame = pd.DataFrame({"CIRCUITO": ["C1"], "FECHA": ["2026-01-01"], "UITI_VANO": ["1"]})
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    empty_df = pd.DataFrame({"criticidad": []}, index=pd.Index([], name="CIRCUITO"))
    monkeypatch.setattr(informe_contract, "resolve_group_dataframe", lambda *a, **k: empty_df)

    request = informe_contract.normalize_request("bajo")
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
        ["resolve", "alto", "--data-path", "data.csv", "--runs-root", str(runs_root)]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "awaiting_confirmation"


def _known_tier_df_coords_full() -> pd.DataFrame:
    """La misma forma que `render_and_write` necesita de punta a punta: las columnas del
    RANKING junto a `criticidad`."""
    df = _df_coords([f"ALTO_{i}" for i in range(3)], [180, 190, 175])
    df["criticidad"] = "Riesgo Alto"
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

    request = informe_contract.normalize_request("alto", "2026-01-01", "2026-01-02", runtime="claude")
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
            "alto",
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
    """`specs` = [(circuito, eventos_total, uiti_total, criticidad), ...].

    El esquema es el del RANKING. `vanos_criticos` se deriva del UITI para que el orden
    por criticidad sea coherente con el que tendria una corrida real.
    """
    return [
        {
            "circuito": circuito,
            "vanos_criticos": int(uiti_total // 100),
            "vanos_medio_alto": int(uiti_total // 150),
            "vanos_alto": int(uiti_total // 300),
            "vanos_con_eventos": int(eventos_total),
            "uiti_total": uiti_total,
            "eventos_total": int(eventos_total),
            "criticidad": criticidad,
            "posicion": i + 1,
        }
        for i, (circuito, eventos_total, uiti_total, criticidad) in enumerate(specs)
    ]


def test_synthesize_returns_all_required_sections_with_real_content():
    sampled_records = _sampled_records(
        [
            ("C01", 40, 50000.0, "Riesgo Alto"),
            ("C02", 42, 52000.0, "Riesgo Alto"),
            # C03 is a genuine numeric outlier: UITI_VANO far above the
            # group median AND event_count far below it (high risk, sparse
            # activity) -- the exact cross-circuit pattern synthesize()
            # must surface.
            ("C03", 5, 500000.0, "Riesgo Alto"),
        ]
    )
    loaded_content = [
        {"circuito": "C01", "source": "vault_note", "content": "Texto narrativo C01 sobre riesgo alto."},
        {"circuito": "C02", "source": "raw_json", "content": "Texto narrativo C02."},
        None,  # missing content even after auto-trigger (edge case)
    ]
    group = {"slug": "alto", "label": "Riesgo Alto", "circuit_count": 3}

    result = synthesize(sampled_records, loaded_content, group)

    # resumen_ejecutivo is now a list of 5-7 short items (never a single
    # descriptive paragraph), and real (derived from the inputs, not
    # hardcoded placeholders).
    resumen = result["resumen_ejecutivo"]
    assert isinstance(resumen, list)
    assert 5 <= len(resumen) <= 7
    assert any("Riesgo Alto" in item for item in resumen)
    # Never cites the internal JSON/markdown artifacts -- only the circuit's
    # own HTML report or PDF base documents are citable.
    assert not any(".json" in item.lower() or ".md" in item.lower() for item in resumen)

    assert result["patrones_comunes"]
    assert any("Riesgo Alto" in p for p in result["patrones_comunes"])
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
    sampled_records = _sampled_records([("C01", 40, 50000.0, "Riesgo Alto")])
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
    group = {"slug": "alto", "label": "Riesgo Alto", "circuit_count": 1}

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
    sampled_records = _sampled_records([("C01", 40, 50000.0, "Riesgo Alto")])
    loaded_content = [
        {"circuito": "C01", "source": "vault_note", "content": "x", "cause_hypothesis_note": short_cause}
    ]
    group = {"slug": "alto", "label": "Riesgo Alto", "circuit_count": 1}

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
    sampled_records = _sampled_records([("C01", 40, 50000.0, "Riesgo Alto")])
    loaded_content = [
        {"circuito": "C01", "source": "vault_note", "content": "x", "cause_hypothesis_note": long_cause}
    ]
    group = {"slug": "alto", "label": "Riesgo Alto", "circuit_count": 1}

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
    sampled_records = _sampled_records([("C01", 40, 50000.0, "Riesgo Alto")])
    loaded_content = [
        {"circuito": "C01", "source": "vault_note", "content": "x", "cause_hypothesis_note": cause_with_newlines}
    ]
    group = {"slug": "alto", "label": "Riesgo Alto", "circuit_count": 1}

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
            "criticidad": "Riesgo Alto",
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
    sampled_records = _sampled_records([("C01", 40, 50000.0, "Riesgo Alto")])
    loaded_content = [{"circuito": "C01", "source": "raw_json", "content": long_text}]
    group = {"slug": "alto", "label": "Riesgo Alto", "circuit_count": 1}

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
    group = {"slug": "medio-alto", "label": "Riesgo Medio-Alto", "circuit_count": 3}

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
    group = {"slug": "medio-alto", "label": "Riesgo Medio-Alto", "circuit_count": 2}

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
            ("F01", 40, 50000.0, "Riesgo Alto"),
            ("F02", 41, 51000.0, "Riesgo Alto"),
            ("F03", 39, 49000.0, "Riesgo Alto"),
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
    group = {"slug": "alto", "label": "Riesgo Alto", "circuit_count": 3}

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


def test_render_managerial_report_embebe_la_figura_y_las_secciones_que_quedan():
    raw_df = _four_tier_raw_df(per_tier=2)
    sampled_records = _sampled_records(
        [
            ("ALTO_0", 40, 50000.0, "Riesgo Alto"),
            ("ALTO_1", 41, 51000.0, "Riesgo Alto"),
        ]
    )
    loaded_content = [
        {"circuito": "ALTO_0", "source": "vault_note", "content": "Narrativa ALTO_0."},
        None,
    ]
    group = {"slug": "alto", "label": "Riesgo Alto", "circuit_count": 2}
    synthesis = synthesize(sampled_records, loaded_content, group)

    html = render_managerial_report(
        raw_df,
        synthesis=synthesis,
        group=group,
        resolved_window={"fecha_inicio": "2026-01-01", "fecha_fin": "2026-12-31"},
        sampled=["ALTO_0", "ALTO_1"],
    )

    assert "<title>Informe Gerencial: Circuitos en Riesgo Alto</title>" in html
    assert "<h1>Informe Gerencial: Circuitos en Riesgo Alto</h1>" in html
    assert "Panorama del grupo" in html
    assert "Resumen ejecutivo" in html
    assert "Riesgo agregado" in html
    assert "Acciones recomendadas" in html
    assert "Anexo por circuito" in html
    # La figura del panorama es real: la llamada de arranque de Plotly esta ahi, no una
    # cadena de relleno.
    assert "Plotly.newPlot" in html
    # Real synthesis content actually lands in the page (HTML-escaped, since
    # narrative text may contain user-influenced characters), not just headings
    # -- resumen_ejecutivo/riesgo_agregado are itemized lists now, so every
    # item must land individually.
    for item in synthesis["resumen_ejecutivo"]:
        assert html_lib.escape(item) in html
    for item in synthesis["riesgo_agregado"]["items"]:
        assert html_lib.escape(item) in html


def test_las_barras_del_panorama_cubren_la_flota_completa():
    """La invariante de "nunca se esconde nada" sobrevive al traslado: el ranking se dibuja
    ahora UNA vez, dentro del panorama, y sigue trayendo la flota entera aunque el informe
    hable de una sola banda."""
    raw_df = _ranking_raw_df({f"C{i:02d}": i * 8 for i in range(1, 13)}, vanos_por_circuito=110)
    sampled_records = _sampled_records([("C12", 40, 50000.0, "Riesgo Alto")])
    group = {"slug": "alto", "label": "Riesgo Alto", "circuit_count": 1}

    html = render_managerial_report(
        raw_df,
        synthesis=synthesize(sampled_records, [None], group),
        group=group,
        resolved_window={"fecha_inicio": "2026-01-01", "fecha_fin": "2026-12-31"},
        sampled=["C12"],
    )

    # Los doce circuitos de la flota siguen en la figura, no solo el de la banda.
    for circuito in (f"C{i:02d}" for i in range(1, 13)):
        assert circuito in html
    # Y se dibuja una sola vez: el mapa del final se retiro por ser la misma figura.
    assert "Mapa de agrupamiento" not in html

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
        [(name, 40, 50000.0, "Riesgo Alto") for name in sampled]
    )
    loaded_content = [None] * len(sampled)
    group = {"slug": "alto", "label": "Riesgo Alto", "circuit_count": len(sampled)}
    synthesis = synthesize(sampled_records, loaded_content, group)
    return render_managerial_report(
        raw_df,
        synthesis=synthesis,
        group=group,
        resolved_window={"fecha_inicio": "2026-01-01", "fecha_fin": "2026-12-31"},
        sampled=sampled,
        graph_patterns=graph_patterns,
    )


def test_la_seccion_de_intervencion_nombra_las_causas_y_las_estrategias():
    html = informe_contract._intervention_graph_html(_RADIAL_HTML, _RESUMEN, n_sampled=2)

    assert "Causas y estrategias de intervención" in html
    # El rotulo se capitaliza al DIBUJARSE; la clave de agrupacion sigue en
    # minuscula (es la identidad que junta la causa entre circuitos).
    assert "Clima/atmosférico" in html
    assert "(CNT_TRF)" in html
    assert "prioridad alta" in html
    assert 'class="grafo-conceptos"' in html


def test_la_seccion_de_intervencion_se_omite_si_no_hay_figura():
    assert informe_contract._intervention_graph_html(None, _RESUMEN, n_sampled=2) == ""


def test_la_seccion_de_intervencion_se_omite_con_un_solo_circuito():
    assert informe_contract._intervention_graph_html(_RADIAL_HTML, _RESUMEN, n_sampled=1) == ""


def test_la_figura_se_dibuja_aunque_no_haya_resumen_legible():
    html = informe_contract._intervention_graph_html(_RADIAL_HTML, None, n_sampled=2)

    assert 'class="grafo-conceptos"' in html
    assert "Causas compartidas" not in html


def test_el_grafo_radial_no_depende_del_paso_de_graphify(monkeypatch, tmp_path):
    """Es el punto de todo el cambio: con el paso de graphify caído
    (`graph_patterns_path=None`, `graph_view_path=None`) la figura radial
    sigue en el informe. El toggle anterior la habría perdido junto con él.
    """
    frame = _four_tier_raw_df(per_tier=2)
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    monkeypatch.setattr(
        informe_contract, "resolve_group_dataframe", lambda *a, **k: _known_tier_df_coords_full()
    )
    monkeypatch.setattr(
        informe_contract,
        "load_circuit_content",
        lambda circuito, **kwargs: {"circuito": circuito, "source": "vault_note", "content": "x"},
    )
    figura = tmp_path / "grafo-intervencion.html"
    figura.write_text(_RADIAL_HTML, encoding="utf-8")

    request = informe_contract.normalize_request("alto", "2026-01-01", "2026-01-02")
    outcome = informe_contract.render_and_write(
        request,
        data_path="data.csv",
        output_root=tmp_path / "html",
        graph_intervencion_path=figura,
    )

    assert outcome.status == "success"
    written = Path(outcome.output_html).read_text(encoding="utf-8")
    assert "grafo radial de causas" in written
    # El grafo radial se dibuja aunque graphify no haya corrido nunca: no hay ninguna
    # seccion que dependa de el, y este paso lee los artefactos de los agentes.
    assert "Causas y estrategias de intervención" in written


def test_el_contrato_y_el_constructor_derivan_el_mismo_archivo_de_resumen(tmp_path):
    """Los dos calculan la ruta del `.resumen.json` por separado para no cerrar
    un ciclo de imports; si se separan, el informe deja de nombrar las causas
    sin que nada falle.
    """
    figura = tmp_path / "grafo-intervencion.muy-alta.html"

    assert informe_contract._intervention_summary_path(figura) == intervention_graph.summary_path(
        figura
    )
    assert informe_contract._intervention_summary_path(None) is None


def test_e2e_el_constructor_real_alimenta_el_informe(monkeypatch, tmp_path):
    """Cadena completa con código de producción, sin stubs de HTML: artefactos
    de agentes en disco -> `intervention_graph build` -> `render_and_write`.
    """
    runs_root = tmp_path / "runs"
    sampled = ["ALTO_0", "ALTO_1", "ALTO_2"]
    for circuito in sampled:
        run_dir = runs_root / canonical_circuit_identity(circuito) / "20260101T000000000000"
        run_dir.mkdir(parents=True)
        (run_dir / "historical.out.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "cause_hypothesis_note": "rafagas de viento elevadas sobre vanos recurrentes",
                        "key_findings": [],
                        "recommended_actions": [],
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (run_dir / "expert-alignment.out.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "variables_a_priorizar": [
                            {
                                "variable": "CNT_TRF",
                                "prioridad": "alta",
                                "justificacion": "mayor peso",
                                "tipo_de_validacion_sugerida": "Revisar en campo los transformadores.",
                            }
                        ],
                        "coincidencias": [],
                        "diferencias": [],
                        "sintesis_final": "s",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    figura = tmp_path / "grafo-intervencion.muy-alta.2026-01-01_2026-01-02.html"
    resultado = intervention_graph.build_intervention_graph(sampled, figura, runs_root=runs_root)
    assert resultado.status == "success"
    assert resultado.causa_count >= 1 and resultado.estrategia_count >= 1
    assert intervention_graph.summary_path(figura).is_file()

    frame = _four_tier_raw_df(per_tier=2)
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    monkeypatch.setattr(
        informe_contract, "resolve_group_dataframe", lambda *a, **k: _known_tier_df_coords_full()
    )
    monkeypatch.setattr(
        informe_contract,
        "load_circuit_content",
        lambda circuito, **kwargs: {"circuito": circuito, "source": "vault_note", "content": "x"},
    )

    request = informe_contract.normalize_request("alto", "2026-01-01", "2026-01-02")
    outcome = informe_contract.render_and_write(
        request,
        data_path="data.csv",
        output_root=tmp_path / "html",
        graph_intervencion_path=figura,
    )

    assert outcome.status == "success"
    written = Path(outcome.output_html).read_text(encoding="utf-8")
    # El grafo va INLINE, así que ya no se compara el documento ESCAPADO contra el
    # informe: lo que viaja es su cuerpo, sin `<!DOCTYPE>` ni cabeza. Meter un documento
    # completo dentro de otro es HTML inválido, y el navegador lo repara como quiera.
    assert 'class="grafo-conceptos"' in written
    assert "<!DOCTYPE html>" not in written.split('class="grafo-conceptos"', 1)[1]
    assert "plotly" in written.lower()
    # El resumen escrito por el constructor real es el que nombra la sección, y la nombra
    # con el NOMBRE de la variable y su código entre paréntesis, igual que la figura.
    from chec_local_interpreter.glosario_variables import nombre_con_codigo

    assert html_lib.escape(f"Inspección en campo · {nombre_con_codigo('CNT_TRF')}") in written


def test_cli_render_acepta_grafo_de_intervencion(monkeypatch, capsys, tmp_path):
    frame = _four_tier_raw_df(per_tier=2)
    monkeypatch.setattr(informe_contract, "load_dataset", lambda path: frame)
    monkeypatch.setattr(
        informe_contract, "resolve_group_dataframe", lambda *a, **k: _known_tier_df_coords_full()
    )
    monkeypatch.setattr(
        informe_contract,
        "load_circuit_content",
        lambda circuito, **kwargs: {"circuito": circuito, "source": "vault_note", "content": "x"},
    )
    figura = tmp_path / "grafo-intervencion.html"
    figura.write_text(_RADIAL_HTML, encoding="utf-8")

    exit_code = informe_contract.main(
        [
            "render",
            "alto",
            "2026-01-01",
            "2026-01-02",
            "--data-path",
            "data.csv",
            "--output-root",
            str(tmp_path / "html"),
            "--graph-intervencion",
            str(figura),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    assert "grafo radial de causas" in Path(payload["output_html"]).read_text(encoding="utf-8")


def test_los_temas_de_causa_ignoran_los_acentos():
    """El agente histórico escribe unas notas con acentos y otras sin ellos
    para el mismo corpus; el bucketing no puede depender de eso.
    """
    assert informe_contract.cause_themes("condiciones atmosféricas") == informe_contract.cause_themes(
        "condiciones atmosfericas"
    )


def test_la_prosa_y_la_figura_nombran_las_mismas_causas():
    nota = "falla fisica en linea de media tension con rafagas elevadas"
    contenido = [{"circuito": "A", "cause_hypothesis_note": nota}]

    de_la_prosa = set(informe_contract._cause_theme_counter(contenido))
    de_la_figura = set(intervention_graph.cause_themes(nota))

    assert de_la_prosa == de_la_figura
    assert "línea MT / falla física" in de_la_prosa


# ---------------------------------------------------------------------------
# Las bandas del RANKING (cuaderno 02 / tablero de agrupamiento), no el K-Means
# ---------------------------------------------------------------------------


# Cuatro perfiles de VANO, separados en eventos y UITI para que el K-Means de
# `geometria_vanos` encuentre sus cuatro grupos. Ordenados por mediana de UITI, asi que
# los indices 2 y 3 -- los dos ultimos -- son los que el ranking cuenta como criticos.
_PERFILES_VANO = ((2, 1.0), (6, 10.0), (20, 100.0), (60, 1000.0))


def _ranking_raw_df(spec: dict[str, int], vanos_por_circuito: int = 400) -> pd.DataFrame:
    """Una base con `FID_VANO` real, para que `ranking_circuitos` pueda contar vanos.

    `spec` da, por circuito, cuantos de sus vanos caen en los grupos criticos
    (Medio-Alto + Alto). El resto se reparte entre los dos perfiles bajos, que tienen
    que estar presentes: con menos de cuatro perfiles distintos el K-Means de vanos
    converge a menos grupos y los indices criticos quedan VACIOS -- todos los circuitos
    salen en cero y en "Riesgo Bajo", que es un fixture que no prueba nada.
    """
    filas = []
    for circuito, criticos in spec.items():
        for v in range(vanos_por_circuito):
            if v < criticos:
                perfil = _PERFILES_VANO[2 + (v % 2)]
            else:
                perfil = _PERFILES_VANO[v % 2]
            n_eventos, uiti = perfil
            for e in range(n_eventos):
                filas.append({
                    "CIRCUITO": circuito,
                    "FID_VANO": f"{circuito}_{v}",
                    "FECHA": f"2026-01-{(e % 28) + 1:02d}",
                    "UITI_VANO": uiti,
                })
    return pd.DataFrame(filas)


def test_slugs_del_gerencial_son_las_cuatro_bandas_del_ranking():
    """Guarda anti-deriva: el vocabulario sale de `ranking_circuitos.NOMBRES_RANGO`,
    que es el MISMO que pinta la barra del tablero y el que cita /report."""
    from chec_local_interpreter.ranking_circuitos import NOMBRES_RANGO

    assert informe_contract.RANKING_GROUP_SLUGS == ("bajo", "medio", "medio-alto", "alto")
    assert tuple(informe_contract.RANKING_SLUG_TO_LABEL.values()) == NOMBRES_RANGO
    assert informe_contract.VALID_GROUP_SLUGS == (
        "bajo", "medio", "medio-alto", "alto", "todos"
    )


def test_normalize_request_traduce_el_slug_a_la_banda_del_ranking():
    request = informe_contract.normalize_request("alto", runtime="claude")

    assert request.grupo == "alto"
    assert request.criticidad == "Riesgo Alto"


def test_normalize_request_rechaza_los_slugs_viejos_del_kmeans():
    """`muy-alta` y `medio-baja` son bandas que el ranking NO tiene: aceptarlas
    devolveria un grupo vacio en vez de decir que el vocabulario cambio."""
    for slug in ("muy-alta", "alta", "medio-alta", "medio-baja", "baja"):
        with pytest.raises(ValueError, match="grupo desconocido"):
            informe_contract.normalize_request(slug)


def test_los_dos_comandos_comparten_un_solo_vocabulario():
    """`/reporte-lote` y `/informe-gerencial` migraron JUNTOS al ranking. Una sola
    definicion del allowlist es lo que impide que se vuelvan a separar: mientras
    coexistieron los dos, la cadena "Riesgo Alto" nombraba 16 circuitos en un comando y
    7 en el otro, con solo 3 en comun."""
    from chec_local_interpreter import batch_report_contract

    assert batch_report_contract.VALID_GROUP_SLUGS == informe_contract.VALID_GROUP_SLUGS
    assert batch_report_contract.GROUP_SLUG_TO_LABEL == informe_contract.RANKING_SLUG_TO_LABEL
    for slug in ("muy-alta", "alta", "medio-alta", "medio-baja", "baja"):
        assert slug not in batch_report_contract.VALID_GROUP_SLUGS


def test_resolve_group_dataframe_usa_el_ranking_y_no_el_kmeans():
    raw_df = _ranking_raw_df({f"C{i:02d}": i * 8 for i in range(1, 13)}, vanos_por_circuito=110)

    result = informe_contract.resolve_group_dataframe(raw_df, "todos", None)

    # Las columnas son las del ranking, no las del K-Means de circuitos.
    assert "vanos_criticos" in result.columns
    assert "posicion" in result.columns
    assert "centroid_distance" not in result.columns
    assert set(result["criticidad"]) <= {
        "Riesgo Bajo", "Riesgo Medio", "Riesgo Medio-Alto", "Riesgo Alto"
    }


def test_resolve_group_dataframe_filtra_por_la_banda_del_ranking():
    raw_df = _ranking_raw_df({f"C{i:02d}": i * 8 for i in range(1, 13)}, vanos_por_circuito=110)

    result = informe_contract.resolve_group_dataframe(raw_df, "alto", "Riesgo Alto")

    assert not result.empty
    assert (result["criticidad"] == "Riesgo Alto").all()


def test_sample_representatives_toma_los_12_peores_por_vanos_criticos():
    """El criterio deja de ser `centroid_distance` -- que el ranking no tiene -- y pasa
    a ser el puesto: 1 = el peor, el mismo numero que /report cita en prosa."""
    df = pd.DataFrame(
        {"vanos_criticos": list(range(20, 0, -1))},
        index=pd.Index([f"C{i:02d}" for i in range(20)], name="circuito"),
    )

    sampled = informe_contract.sample_representatives(df)

    assert len(sampled) == 12
    assert list(sampled.index) == [f"C{i:02d}" for i in range(12)]
    assert sampled["vanos_criticos"].tolist() == list(range(20, 8, -1))


def test_sample_representatives_desempata_por_nombre_ascendente():
    df = pd.DataFrame(
        {"vanos_criticos": [50] * 14},
        index=pd.Index([f"C{i:02d}" for i in range(13, -1, -1)], name="circuito"),
    )

    sampled = informe_contract.sample_representatives(df)

    assert list(sampled.index) == [f"C{i:02d}" for i in range(12)]


def test_sample_representatives_bajo_el_umbral_devuelve_todos():
    df = pd.DataFrame(
        {"vanos_criticos": [9, 4, 7]},
        index=pd.Index(["C1", "C2", "C3"], name="circuito"),
    )

    assert len(informe_contract.sample_representatives(df)) == 3


def test_plot_ranking_circuitos_acepta_varios_circuitos_destacados():
    """La figura del gerencial resalta los 12 muestreados, no uno solo."""
    from chec_local_interpreter.plotting import plot_ranking_circuitos

    raw_df = _ranking_raw_df({f"C{i:02d}": i * 8 for i in range(1, 9)}, vanos_por_circuito=70)

    fig = plot_ranking_circuitos(raw_df, ["C08", "C07", "C06"])
    anchos = list(fig.data[0].marker.line.width)

    assert sum(1 for w in anchos if w >= 3.0) == 3


def test_plot_ranking_circuitos_sigue_aceptando_un_solo_nombre():
    """Compatibilidad: /report lo llama con un `str` y no se toca."""
    from chec_local_interpreter.plotting import plot_ranking_circuitos

    raw_df = _ranking_raw_df({f"C{i:02d}": i * 8 for i in range(1, 9)}, vanos_por_circuito=70)

    fig = plot_ranking_circuitos(raw_df, "C08")
    anchos = list(fig.data[0].marker.line.width)

    assert sum(1 for w in anchos if w >= 3.0) == 1
    assert "C08" in fig.layout.title.text


def test_el_contrato_no_conserva_ninguna_via_de_vuelta_a_la_nube():
    """El modulo ya ni siquiera importa la nube de K-Means ni su calculo de grupos: no
    queda camino por el que volver a ella."""
    assert not hasattr(informe_contract, "plot_interactive_circuit_clustering")
    assert not hasattr(informe_contract, "compute_circuit_criticality_groups")


def test_perfil_de_banda_cuenta_vanos_por_grupo_y_su_parte_de_la_flota():
    """El preambulo responde 'cuantos vanos de la flota estan en esta banda', que es la
    magnitud que justifica el informe. Se calcula sobre la geometria de vanos del ranking,
    no re-agrupando por circuito."""
    raw_df = _ranking_raw_df({f"C{i:02d}": i * 8 for i in range(1, 13)}, vanos_por_circuito=110)

    perfil = informe_contract.perfil_de_banda(raw_df, ["C12"], None, None)

    assert perfil["circuitos"] == ["C12"]
    # Los cuatro grupos de VANO del ranking, en su orden.
    assert [g["grupo"] for g in perfil["grupos"]] == [
        "Bajo", "Medio", "Medio-Alto", "Alto"
    ]
    # Cada grupo trae el conteo de la banda, su porcentaje DENTRO de la banda, y el
    # conteo de la flota entera para poder decir que parte se lleva.
    for g in perfil["grupos"]:
        assert {"grupo", "vanos", "pct_banda", "vanos_flota", "uiti"} <= set(g)
    assert sum(g["vanos"] for g in perfil["grupos"]) == perfil["vanos_banda"]
    assert abs(sum(g["pct_banda"] for g in perfil["grupos"]) - 100.0) < 0.01
    assert perfil["vanos_flota"] > perfil["vanos_banda"]


def test_perfil_de_banda_la_parte_critica_se_mide_contra_la_flota():
    raw_df = _ranking_raw_df({f"C{i:02d}": i * 8 for i in range(1, 13)}, vanos_por_circuito=110)

    perfil = informe_contract.perfil_de_banda(raw_df, ["C11", "C12"], None, None)

    criticos_banda = sum(g["vanos"] for g in perfil["grupos"] if g["grupo"] in ("Medio-Alto", "Alto"))
    criticos_flota = sum(g["vanos_flota"] for g in perfil["grupos"] if g["grupo"] in ("Medio-Alto", "Alto"))
    assert perfil["vanos_criticos_banda"] == criticos_banda
    assert perfil["vanos_criticos_flota"] == criticos_flota
    assert perfil["pct_criticos_de_la_flota"] == pytest.approx(
        100.0 * criticos_banda / criticos_flota, abs=0.01
    )


def test_perfil_de_banda_trae_el_uiti_por_vano_para_los_violines():
    """El violin necesita la DISTRIBUCION, no un resumen: un promedio no distingue una
    banda con muchos vanos medianos de una con pocos extremos."""
    raw_df = _ranking_raw_df({f"C{i:02d}": i * 8 for i in range(1, 13)}, vanos_por_circuito=110)

    perfil = informe_contract.perfil_de_banda(raw_df, ["C12"], None, None)

    con_uiti = [g for g in perfil["grupos"] if g["uiti"]]
    assert con_uiti, "ningun grupo trajo valores de UITI"
    for g in con_uiti:
        assert len(g["uiti"]) == g["vanos"]
        assert all(v > 0 for v in g["uiti"])


def test_perfil_de_banda_nunca_revienta_con_un_marco_vacio():
    perfil = informe_contract.perfil_de_banda(pd.DataFrame(), ["C1"], None, None)

    assert perfil["vanos_banda"] == 0
    assert perfil["grupos"] == []


def test_figura_preambulo_trae_las_tres_lecturas_del_tablero_2():
    """Barras de ranking, barras de porcentaje y violines: las mismas tres del tablero de
    agrupamiento, para que el gerencial y el tablero se lean como una sola cosa."""
    raw_df = _ranking_raw_df({f"C{i:02d}": i * 8 for i in range(1, 13)}, vanos_por_circuito=110)
    perfil = informe_contract.perfil_de_banda(raw_df, ["C12"], None, None)

    fig = informe_contract.figura_preambulo(raw_df, ["C12"], perfil, None, None)

    tipos = [t.type for t in fig.data]
    assert "bar" in tipos
    assert "violin" in tipos
    # El ranking de la flota entera sigue siendo una barra por circuito.
    barras_ranking = [t for t in fig.data if t.type == "bar" and len(t.x or []) == 12]
    assert barras_ranking, "no esta el ranking de la flota completa"


def test_preambulo_html_nombra_los_circuitos_y_sus_magnitudes():
    perfil = {
        "circuitos": ["C11", "C12"],
        "vanos_banda": 184, "vanos_flota": 1320,
        "vanos_criticos_banda": 184, "vanos_criticos_flota": 624,
        "pct_criticos_de_la_flota": 29.49,
        "pct_vanos_de_la_flota": 13.94,
        "grupos": [
            {"grupo": "Bajo", "vanos": 0, "pct_banda": 0.0, "vanos_flota": 400, "uiti": []},
            {"grupo": "Medio", "vanos": 0, "pct_banda": 0.0, "vanos_flota": 296, "uiti": []},
            {"grupo": "Medio-Alto", "vanos": 92, "pct_banda": 50.0, "vanos_flota": 312, "uiti": [1.0]},
            {"grupo": "Alto", "vanos": 92, "pct_banda": 50.0, "vanos_flota": 312, "uiti": [2.0]},
        ],
    }

    html = informe_contract._preambulo_html(perfil, "<div>FIGURA</div>", "Riesgo Alto", 2)

    assert "FIGURA" in html
    assert "C11" in html and "C12" in html
    assert "184" in html          # vanos de la banda
    assert "29,5" in html or "29.5" in html   # la parte critica de la flota
    assert "Medio-Alto" in html


def test_preambulo_html_dice_cuantos_circuitos_y_de_cuantos():
    perfil = {
        "circuitos": ["C12"], "vanos_banda": 92, "vanos_flota": 1320,
        "vanos_criticos_banda": 92, "vanos_criticos_flota": 624,
        "pct_criticos_de_la_flota": 14.7, "pct_vanos_de_la_flota": 7.0,
        "grupos": [{"grupo": "Alto", "vanos": 92, "pct_banda": 100.0, "vanos_flota": 312, "uiti": [1.0]}],
    }

    html = informe_contract._preambulo_html(perfil, "", "Riesgo Alto", 1)

    assert "1" in html and "Riesgo Alto" in html


def test_el_preambulo_va_ANTES_del_resumen_ejecutivo(monkeypatch):
    """Es un preambulo: si cae despues de la sintesis deja de serlo."""
    raw_df = _ranking_raw_df({f"C{i:02d}": i * 8 for i in range(1, 13)}, vanos_por_circuito=110)
    recs = _sampled_records([("C12", 40, 50000.0, "Riesgo Alto")])
    group = {"slug": "alto", "label": "Riesgo Alto", "circuit_count": 1}

    html = render_managerial_report(
        raw_df,
        synthesis=synthesize(recs, [None], group),
        group=group,
        resolved_window={"fecha_inicio": "2026-01-01", "fecha_fin": "2026-02-01"},
        sampled=["C12"],
    )

    assert "Panorama del grupo" in html
    assert html.index("Panorama del grupo") < html.index("Resumen ejecutivo del grupo")


def test_perfil_de_banda_cuenta_los_circuitos_de_la_FLOTA_no_los_de_la_banda():
    """"7 circuitos de los 7" no dice nada. El denominador es la flota."""
    raw_df = _ranking_raw_df({f"C{i:02d}": i * 8 for i in range(1, 13)}, vanos_por_circuito=110)

    perfil = informe_contract.perfil_de_banda(raw_df, ["C12"], None, None)

    assert perfil["circuitos_flota"] == 12


def test_preambulo_html_destaca_el_grupo_donde_la_banda_mas_concentra():
    """La parte que la banda se lleva de CADA grupo es lo accionable: un 22,8% del grupo
    Alto con solo un 10,5% de los vanos es el argumento, y en el agregado se diluye."""
    perfil = {
        "circuitos": ["C1"], "circuitos_flota": 208,
        "vanos_banda": 2882, "vanos_flota": 27390,
        "vanos_criticos_banda": 1563, "vanos_criticos_flota": 11679,
        "pct_criticos_de_la_flota": 13.4, "pct_vanos_de_la_flota": 10.5,
        "grupos": [
            {"grupo": "Bajo", "vanos": 387, "pct_banda": 13.4, "vanos_flota": 4236, "uiti": [1.0]},
            {"grupo": "Medio", "vanos": 932, "pct_banda": 32.3, "vanos_flota": 11475, "uiti": [1.0]},
            {"grupo": "Medio-Alto", "vanos": 1236, "pct_banda": 42.9, "vanos_flota": 10243, "uiti": [1.0]},
            {"grupo": "Alto", "vanos": 327, "pct_banda": 11.3, "vanos_flota": 1436, "uiti": [1.0]},
        ],
    }

    html = informe_contract._preambulo_html(perfil, "", "Riesgo Alto", 1)

    assert "208" in html                      # el denominador correcto
    assert "22,8" in html                     # la concentracion en el grupo Alto
    assert html.count("Alto") >= 2


# ---------------------------------------------------------------------------
# El informe adelgaza: fuera patrones, atipicos, grafo cross-circuito y el mapa
# ---------------------------------------------------------------------------


def _html_del_informe(sampled=("C12",)):
    raw_df = _ranking_raw_df({f"C{i:02d}": i * 8 for i in range(1, 13)}, vanos_por_circuito=110)
    recs = _sampled_records([(c, 40, 50000.0, "Riesgo Alto") for c in sampled])
    group = {"slug": "alto", "label": "Riesgo Alto", "circuit_count": len(sampled)}
    return render_managerial_report(
        raw_df,
        synthesis=synthesize(recs, [None] * len(sampled), group),
        group=group,
        resolved_window={"fecha_inicio": "2026-01-01", "fecha_fin": "2026-02-01"},
        sampled=list(sampled),
    )


def test_el_informe_ya_no_trae_patrones_atipicos_ni_grafo_cross_circuito():
    html = _html_del_informe()

    assert "<h2>Patrones comunes</h2>" not in html
    assert "Circuitos atípicos" not in html
    assert "Patrones cross-circuito" not in html


def test_el_mapa_de_agrupamiento_sale_porque_ya_esta_arriba():
    """Las barras del ranking abren el informe en el Panorama. Repetirlas al final es la
    MISMA figura dos veces, y la de abajo llega sin la prosa que la explica."""
    html = _html_del_informe()

    assert "Mapa de agrupamiento" not in html
    # Pero el ranking sigue, arriba, dentro del panorama.
    assert "Panorama del grupo" in html
    # El subtitulo de la fila del ranking. Decia "Ranking de la flota"; la revision
    # unifico el vocabulario con el informe de circuito, que ya decia "circuitos
    # totales". Lo que la prueba afirma no cambia: que la figura del ranking sigue
    # ahi arriba, dentro del panorama.
    assert "Ranking de todos los circuitos" in html


def test_las_secciones_que_quedan_van_en_este_orden():
    """`Concentración por ventana` y `Causas y estrategias` dependen de corridas en disco;
    con el fixture vacio degradan y no aparecen, que es lo correcto. Lo que se afirma aqui
    es el ORDEN de las que si estan y que ninguna de las retiradas vuelva."""
    html = _html_del_informe()
    orden = [
        "Panorama del grupo",
        "Resumen ejecutivo del grupo",
        "Concentración por ventana",
        "Causas y estrategias de intervención",
        "Riesgo agregado",
        "Acciones recomendadas",
        "Anexo por circuito",
    ]
    presentes = [s for s in orden if f"<h2>{s}</h2>" in html]
    assert presentes[0] == "Panorama del grupo"
    assert presentes[-1] == "Anexo por circuito"
    posiciones = [html.index(f"<h2>{s}</h2>") for s in presentes]
    assert posiciones == sorted(posiciones)
    for retirada in ("Patrones comunes", "Circuitos atípicos", "Patrones cross-circuito",
                     "Mapa de agrupamiento"):
        assert retirada not in html


def test_el_anexo_nombra_la_variable_con_su_codigo():
    from chec_local_interpreter.glosario_variables import nombre_con_codigo

    contenido = {
        "circuito": "C01", "source": "vault_note", "content": "x",
        "variables_a_priorizar": [{"variable": "NR_T", "prioridad": "alta"}],
    }
    lineas = informe_contract._annex_summary_lines(contenido)
    texto = " ".join(str(l) for l in lineas)

    assert nombre_con_codigo("NR_T") in texto
    assert "(NR_T)" in texto


def test_el_resumen_ejecutivo_nombra_la_variable_con_su_codigo():
    recs = _sampled_records([("C01", 40, 50000.0, "Riesgo Alto")])
    contenido = [{
        "circuito": "C01", "source": "vault_note", "content": "x",
        "variables_a_priorizar": [{"variable": "NR_T", "prioridad": "alta"}],
    }]
    group = {"slug": "alto", "label": "Riesgo Alto", "circuit_count": 1}

    resumen = synthesize(recs, contenido, group)["resumen_ejecutivo"]

    assert any("(NR_T)" in item for item in resumen)
    assert any("vegetaci" in item.lower() for item in resumen)


def test_la_prosa_determinista_del_informe_va_acentuada():
    """El preambulo lo escribo yo, no un agente, y llego al informe con `estan` y
    `criticos` sin tilde.

    La guarda de tildes solo corre sobre las respuestas de los AGENTES -- ahi es donde
    puede rechazar --, asi que la prosa que este modulo arma a mano no la revisaba nadie.
    Es justo la que abre el informe.

    Mide el HTML RENDERIZADO y no el fuente: los comentarios de este repo van sin tilde a
    proposito, y una prueba sobre el fuente los marcaria a todos.
    """
    from chec_local_interpreter.ortografia import palabras_sin_tilde

    perfil = {
        "circuitos": ["C11", "C12"],
        "vanos_banda": 184, "vanos_flota": 1320,
        "vanos_criticos_banda": 184, "vanos_criticos_flota": 624,
        "pct_criticos_de_la_flota": 29.49,
        "pct_vanos_de_la_flota": 13.94,
        "grupos": [
            {"grupo": "Bajo", "vanos": 0, "pct_banda": 0.0, "vanos_flota": 400, "uiti": []},
            {"grupo": "Medio", "vanos": 0, "pct_banda": 0.0, "vanos_flota": 296, "uiti": []},
            {"grupo": "Medio-Alto", "vanos": 92, "pct_banda": 50.0, "vanos_flota": 312, "uiti": [1.0]},
            {"grupo": "Alto", "vanos": 92, "pct_banda": 50.0, "vanos_flota": 312, "uiti": [2.0]},
        ],
    }
    html = informe_contract._preambulo_html(perfil, "<div></div>", "Riesgo Alto", 2)
    plano = re.sub(r"<[^>]+>", " ", html)
    faltas = {escrita for escrita, _ in palabras_sin_tilde(plano)}

    assert not faltas, f"prosa sin tilde en el preambulo: {sorted(faltas)}"


def _marco_de_bandas(por_banda: dict[str, int]) -> pd.DataFrame:
    """Un marco de circuitos ya clasificado, con `vanos_criticos` decreciente por banda.

    Va directo contra `sample_representatives` en vez de pasar por `ranking_circuitos`:
    aqui lo que se prueba es la CUOTA, no el corte de percentiles, y fabricar una flota
    real que caiga en las cuatro bandas con los tamanos que cada caso necesita hace la
    prueba sobre el K-Means de vanos y no sobre el muestreo.
    """
    filas = []
    for banda, cuantos in por_banda.items():
        for i in range(cuantos):
            filas.append({
                "CIRCUITO": f"{banda[:4].replace(' ', '')}{i:02d}",
                "criticidad": banda,
                # Decreciente: el indice 0 es el peor de su banda.
                "vanos_criticos": (cuantos - i) * 10,
            })
    return pd.DataFrame(filas).set_index("CIRCUITO")


def test_todos_reparte_por_cuota_de_banda_y_no_se_lo_lleva_todo_el_alto():
    """`todos` no es "los 12 peores de la flota".

    Con el criterio anterior -- los 12 mayores `vanos_criticos` de la flota entera -- los
    doce salian de Riesgo Alto y Medio-Alto y el informe de la flota nunca miraba un
    circuito de Riesgo Medio. La cuota fuerza que las tres bandas esten representadas.
    """
    marco = _marco_de_bandas({
        "Riesgo Alto": 7, "Riesgo Medio-Alto": 40, "Riesgo Medio": 60, "Riesgo Bajo": 101,
    })

    muestra = informe_contract.sample_representatives(
        marco, grupo=informe_contract.ALL_GROUPS_SLUG
    )
    por_banda = muestra["criticidad"].value_counts().to_dict()

    assert por_banda == {"Riesgo Alto": 5, "Riesgo Medio-Alto": 5, "Riesgo Medio": 2}
    assert len(muestra) == 12
    assert "Riesgo Bajo" not in por_banda


def test_dentro_de_cada_banda_la_cuota_toma_los_peores():
    marco = _marco_de_bandas({
        "Riesgo Alto": 7, "Riesgo Medio-Alto": 40, "Riesgo Medio": 60, "Riesgo Bajo": 101,
    })

    muestra = informe_contract.sample_representatives(
        marco, grupo=informe_contract.ALL_GROUPS_SLUG
    )

    for banda, cuota in (("Riesgo Alto", 5), ("Riesgo Medio-Alto", 5), ("Riesgo Medio", 2)):
        de_la_banda = marco[marco["criticidad"] == banda]
        peores = list(de_la_banda.nlargest(cuota, "vanos_criticos").index)
        elegidos = list(muestra[muestra["criticidad"] == banda].index)
        assert sorted(elegidos) == sorted(peores), banda


def test_una_banda_corta_no_se_rellena_con_otra():
    """Si Riesgo Alto trae 3 circuitos, entran 3 y la muestra queda en 10, no en 12.

    Rellenar desde otra banda para llegar a doce cambiaria en silencio la composicion que
    el informe dice tener, y el lector no tendria como notarlo.
    """
    marco = _marco_de_bandas({
        "Riesgo Alto": 3, "Riesgo Medio-Alto": 40, "Riesgo Medio": 60, "Riesgo Bajo": 101,
    })

    muestra = informe_contract.sample_representatives(
        marco, grupo=informe_contract.ALL_GROUPS_SLUG
    )
    por_banda = muestra["criticidad"].value_counts().to_dict()

    assert por_banda == {"Riesgo Alto": 3, "Riesgo Medio-Alto": 5, "Riesgo Medio": 2}
    assert len(muestra) == 10


def test_una_banda_concreta_sigue_tomando_los_peores_sin_cuota():
    """La cuota es SOLO de `todos`. Pedir una banda sigue devolviendo su cola peor."""
    marco = _marco_de_bandas({"Riesgo Medio-Alto": 40})

    muestra = informe_contract.sample_representatives(marco, grupo="medio-alto")

    assert len(muestra) == 12
    assert set(muestra["criticidad"]) == {"Riesgo Medio-Alto"}


def test_en_todos_el_panorama_cubre_la_flota_entera_y_no_los_doce():
    """La primera parte del informe de `todos` discute la criticidad COMPLETA.

    Las barras por grupo de vano y los violines son la lectura del tablero de agrupamiento,
    y ahi el universo son todos los circuitos y todos sus vanos. Calculadas solo sobre los
    doce muestreados decian "el 100% de los vanos de la banda" sobre una banda que era la
    muestra, no la flota, y el porcentaje de la flota salia de comparar la muestra consigo
    misma.
    """
    raw_df = _ranking_raw_df({f"C{i:02d}": i * 4 for i in range(1, 21)}, vanos_por_circuito=90)
    todos = sorted(raw_df["CIRCUITO"].unique())
    doce = todos[:12]

    perfil_flota = informe_contract.perfil_de_banda(raw_df, todos, None, None)
    perfil_muestra = informe_contract.perfil_de_banda(raw_df, doce, None, None)

    assert perfil_flota["vanos_banda"] > perfil_muestra["vanos_banda"]
    assert perfil_flota["vanos_banda"] == perfil_flota["vanos_flota"]
    assert perfil_flota["pct_vanos_de_la_flota"] == pytest.approx(100.0)
    assert perfil_flota["pct_criticos_de_la_flota"] == pytest.approx(100.0)


def test_render_de_todos_usa_el_universo_completo_en_el_preambulo():
    """Guarda de cableado: `render_managerial_report` recibe los circuitos del GRUPO
    aparte de los muestreados, y el preambulo se calcula sobre los primeros."""
    import inspect

    firma = inspect.signature(informe_contract.render_managerial_report)

    assert "circuitos_grupo" in firma.parameters


def _perfil_de_flota() -> dict:
    return {
        "circuitos": [f"C{i:03d}" for i in range(208)],
        "circuitos_flota": 208,
        "vanos_banda": 27390, "vanos_flota": 27390,
        "vanos_criticos_banda": 11650, "vanos_criticos_flota": 11650,
        "pct_criticos_de_la_flota": 100.0,
        "pct_vanos_de_la_flota": 100.0,
        "grupos": [
            {"grupo": "Bajo", "vanos": 9000, "pct_banda": 32.9, "vanos_flota": 9000, "uiti": [1.0]},
            {"grupo": "Medio", "vanos": 6740, "pct_banda": 24.6, "vanos_flota": 6740, "uiti": [9.0]},
            {"grupo": "Medio-Alto", "vanos": 8000, "pct_banda": 29.2, "vanos_flota": 8000, "uiti": [90.0]},
            {"grupo": "Alto", "vanos": 3650, "pct_banda": 13.3, "vanos_flota": 3650, "uiti": [900.0]},
        ],
    }


def test_el_panorama_de_la_flota_no_lista_los_208_ni_dice_el_100_por_ciento_de_si_misma():
    """En `todos` el universo ES la flota, asi que "el 100% de la flota" compara la flota
    consigo misma y no dice nada, y el listado de circuitos son 208 codigos seguidos.

    Lo que si informa es como se reparten SUS vanos entre los cuatro grupos.
    """
    html = informe_contract._preambulo_html(
        _perfil_de_flota(), "<div></div>", "Todos los circuitos", 208,
        bandas={"Riesgo Alto": 7, "Riesgo Medio-Alto": 40, "Riesgo Medio": 60, "Riesgo Bajo": 101},
        muestreados=[f"M{i:02d}" for i in range(12)],
    )
    plano = re.sub(r"<[^>]+>", " ", html)

    assert "100,0%" not in plano
    assert plano.count("C0") < 10, "no debe listar los 208 circuitos"
    assert "11.650" in plano, "tiene que decir cuantos vanos criticos tiene la flota"
    assert "42,5%" in plano, "y que parte de sus vanos son criticos"


def test_el_panorama_de_la_flota_dice_la_composicion_por_banda_y_los_doce():
    html = informe_contract._preambulo_html(
        _perfil_de_flota(), "<div></div>", "Todos los circuitos", 208,
        bandas={"Riesgo Alto": 7, "Riesgo Medio-Alto": 40, "Riesgo Medio": 60, "Riesgo Bajo": 101},
        muestreados=[f"M{i:02d}" for i in range(12)],
    )
    plano = re.sub(r"<[^>]+>", " ", html)

    for banda, cuantos in (("Riesgo Alto", 7), ("Riesgo Medio-Alto", 40), ("Riesgo Bajo", 101)):
        assert banda in plano, banda
        assert str(cuantos) in plano, f"{banda}={cuantos}"
    assert "M00" in plano, "los doce muestreados van nombrados"


def test_una_banda_suelta_conserva_su_prosa_de_siempre():
    """La rama de flota es SOLO de `todos`. Pedir una banda sigue diciendo que parte de la
    flota se lleva, que es donde esa comparacion si informa."""
    perfil = {
        "circuitos": ["C11", "C12"],
        "circuitos_flota": 208,
        "vanos_banda": 184, "vanos_flota": 1320,
        "vanos_criticos_banda": 184, "vanos_criticos_flota": 624,
        "pct_criticos_de_la_flota": 29.49,
        "pct_vanos_de_la_flota": 13.94,
        "grupos": [
            {"grupo": "Bajo", "vanos": 0, "pct_banda": 0.0, "vanos_flota": 400, "uiti": []},
            {"grupo": "Medio", "vanos": 0, "pct_banda": 0.0, "vanos_flota": 296, "uiti": []},
            {"grupo": "Medio-Alto", "vanos": 92, "pct_banda": 50.0, "vanos_flota": 312, "uiti": [1.0]},
            {"grupo": "Alto", "vanos": 92, "pct_banda": 50.0, "vanos_flota": 312, "uiti": [2.0]},
        ],
    }
    plano = re.sub(r"<[^>]+>", " ", informe_contract._preambulo_html(
        perfil, "<div></div>", "Riesgo Alto", 2))

    assert "C11" in plano and "C12" in plano
    assert "29,5%" in plano


def test_el_panorama_de_flota_no_escupe_el_slug_como_prosa():
    """`todos` es un SLUG de la linea de comandos, no una frase.

    La rama de flota lo insertaba tal cual y el informe abria con "Este informe cubre
    **todos**:", que es el argumento que escribio el operador, no una descripcion de la
    poblacion. En la rama por banda el mismo hueco lleva "Riesgo Alto", que si es un
    nombre, y por eso no se habia notado.

    Mira el HTML CRUDO y no el texto sin etiquetas: al quitar `<strong>` quedan dos
    espacios, asi que buscar "cubre todos" en el texto plano no encuentra nada y la
    prueba pasa sin poder fallar. La primera version de esta prueba tenia justo ese
    defecto, y ademas afirmaba una frase que ya estaba en otro parrafo.
    """
    html = informe_contract._preambulo_html(
        _perfil_de_flota(), "<div></div>", "todos", 208,
        bandas={"Riesgo Alto": 7, "Riesgo Medio-Alto": 45, "Riesgo Medio": 52, "Riesgo Bajo": 104},
        muestreados=[f"M{i:02d}" for i in range(12)],
    )

    assert "<strong>todos</strong>" not in html
    # Decia "toda la flota". Mismo alcance, vocabulario unificado con el informe
    # de circuito: quien recibe el informe tiene circuitos, no una flota.
    assert "todos los circuitos</strong>" in html
