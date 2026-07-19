from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import chec_local_interpreter.vault_note_contract as vault_contract
from chec_local_interpreter.vault_note_contract import (
    RunNarratives,
    find_latest_run,
    load_run_narratives,
    render_vault_markdown,
    write_vault_note,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _historical_data(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "headline": "Test headline",
        "executive_summary": ["Resumen 1", "Resumen 2"],
        "key_findings": [
            {
                "title": "Hallazgo A",
                "text": "Texto del hallazgo A",
                "confidence": "alta",
                "evidence": [
                    {
                        "date": "2026-01-01",
                        "critical_point_id": "cp-1",
                        "variable": "UITI_VANO",
                        "summary": "Resumen evidencia 1",
                    }
                ],
            }
        ],
        "circuit_characterization": {
            "text": "Caracterización texto",
            "p97_vanos_uiti_vano": ["V1(U:10)"],
            "p97_vanos_eventos": ["V2(E:5)"],
        },
        "period_synthesis": "Síntesis del período texto",
        "cause_hypothesis_note": "Hipótesis texto",
        "data_gaps": ["Vacío 1"],
        "recommended_actions": ["Acción 1"],
    }
    base.update(overrides)
    return base


def _inference_data(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "contexto": {
            "circuito": "TEST01",
            "periodo": {"inicio": "2026-01-01", "fin": "2026-01-31"},
            "modelo": "TestModel",
        },
        "escenarios": [
            {"nombre": "Escenario 1", "interpretacion": "Interpretación 1"},
        ],
    }
    base.update(overrides)
    return base


def _expert_alignment_data(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "contexto": {"modelo_experto_razon": "Sin discusión experta"},
        "coincidencias": [
            {
                "tema": "Tema A",
                "fuentes": ["Fuente1", "Fuente2"],
                "explicacion": "Explicación A",
            }
        ],
    }
    base.update(overrides)
    return base


def _write_out_json(path: Path, data: dict[str, Any] | None, *, ok: bool = True) -> None:
    payload = {"ok": ok, "data": data if data is not None else {}}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_run_dir(
    tmp_path: Path,
    circuito: str,
    run_id: str,
    *,
    historical: dict[str, Any] | None = None,
    inference: dict[str, Any] | None = None,
    expert_alignment: dict[str, Any] | None = None,
    historical_ok: bool = True,
) -> Path:
    run_dir = tmp_path / circuito / run_id
    run_dir.mkdir(parents=True)
    if historical is not None:
        _write_out_json(run_dir / "historical.out.json", historical, ok=historical_ok)
    if inference is not None:
        _write_out_json(run_dir / "inference.out.json", inference)
    if expert_alignment is not None:
        _write_out_json(run_dir / "expert-alignment.out.json", expert_alignment)
    return run_dir


# ---------------------------------------------------------------------------
# find_latest_run (task 1.1 / 1.2)
# ---------------------------------------------------------------------------


def test_find_latest_run_returns_max_timestamp_subdir(tmp_path):
    circuit_dir = tmp_path / "TEST01"
    (circuit_dir / "20260101T000000000000").mkdir(parents=True)
    (circuit_dir / "20260301T000000000000").mkdir(parents=True)
    (circuit_dir / "20260201T000000000000").mkdir(parents=True)

    latest = find_latest_run("TEST01", runs_root=tmp_path)

    assert latest == circuit_dir / "20260301T000000000000"


def test_find_latest_run_returns_none_when_circuit_dir_missing(tmp_path):
    assert find_latest_run("NOPE", runs_root=tmp_path) is None


def test_find_latest_run_returns_none_when_circuit_dir_empty(tmp_path):
    (tmp_path / "EMPTYCIRC").mkdir()

    assert find_latest_run("EMPTYCIRC", runs_root=tmp_path) is None


# ---------------------------------------------------------------------------
# load_run_narratives (task 1.3 / 1.4)
# ---------------------------------------------------------------------------


def test_load_run_narratives_all_three_present_returns_success(tmp_path):
    run_dir = _make_run_dir(
        tmp_path,
        "X",
        "run1",
        historical=_historical_data(),
        inference=_inference_data(),
        expert_alignment=_expert_alignment_data(),
    )

    narratives = load_run_narratives(run_dir)

    assert narratives.status == "success"
    assert narratives.historical["headline"] == "Test headline"
    assert narratives.inference["escenarios"][0]["nombre"] == "Escenario 1"
    assert narratives.expert_alignment["coincidencias"][0]["tema"] == "Tema A"
    assert narratives.missing_files == []


def test_load_run_narratives_missing_historical_file_skips(tmp_path):
    run_dir = tmp_path / "X" / "run1"
    run_dir.mkdir(parents=True)
    _write_out_json(run_dir / "inference.out.json", _inference_data())

    narratives = load_run_narratives(run_dir)

    assert narratives.status == "skipped_incomplete"
    assert narratives.historical is None
    assert narratives.missing_files == ["historical.out.json"]


def test_load_run_narratives_historical_ok_false_skips(tmp_path):
    run_dir = _make_run_dir(tmp_path, "X", "run1", historical=_historical_data(), historical_ok=False)

    narratives = load_run_narratives(run_dir)

    assert narratives.status == "skipped_incomplete"
    assert narratives.historical is None
    assert narratives.missing_files == ["historical.out.json"]


def test_load_run_narratives_missing_inference_is_partial(tmp_path):
    run_dir = tmp_path / "X" / "run1"
    run_dir.mkdir(parents=True)
    _write_out_json(run_dir / "historical.out.json", _historical_data())
    _write_out_json(run_dir / "expert-alignment.out.json", _expert_alignment_data())

    narratives = load_run_narratives(run_dir)

    assert narratives.status == "partial"
    assert narratives.historical is not None
    assert narratives.inference is None
    assert narratives.missing_files == ["inference.out.json"]


def test_load_run_narratives_missing_expert_alignment_is_partial(tmp_path):
    run_dir = tmp_path / "X" / "run1"
    run_dir.mkdir(parents=True)
    _write_out_json(run_dir / "historical.out.json", _historical_data())
    _write_out_json(run_dir / "inference.out.json", _inference_data())

    narratives = load_run_narratives(run_dir)

    assert narratives.status == "partial"
    assert narratives.expert_alignment is None
    assert narratives.missing_files == ["expert-alignment.out.json"]


# ---------------------------------------------------------------------------
# write_vault_note (task 2.1 threat-matrix / task 2.3 / task 2.4 upsert)
# ---------------------------------------------------------------------------


def test_write_vault_note_traversal_circuito_resolves_under_vault_root(tmp_path):
    target = write_vault_note("../../etc/evil", "# contenido", vault_root=tmp_path)

    assert target.parent == tmp_path.resolve()
    assert target == tmp_path.resolve() / "EVIL.md"
    assert target.read_text(encoding="utf-8") == "# contenido"
    assert not (tmp_path.parent / "evil.md").exists()


def test_write_vault_note_upsert_overwrites_prior_content_no_backup(tmp_path):
    write_vault_note("TEST01", "# primero", vault_root=tmp_path)
    target = write_vault_note("TEST01", "# segundo", vault_root=tmp_path)

    assert target.read_text(encoding="utf-8") == "# segundo"
    siblings = sorted(p.name for p in tmp_path.iterdir())
    assert siblings == ["TEST01.md"]


# ---------------------------------------------------------------------------
# render_vault_markdown (task 2.2 / task 2.3)
# ---------------------------------------------------------------------------


def test_render_vault_markdown_raises_when_historical_missing():
    narratives = RunNarratives(status="skipped_incomplete", historical=None)

    with pytest.raises(ValueError, match="historical"):
        render_vault_markdown("TEST01", "run1", narratives)


def test_render_vault_markdown_happy_path_maps_all_historical_fields():
    narratives = RunNarratives(
        status="success",
        historical=_historical_data(),
        inference=_inference_data(),
        expert_alignment=_expert_alignment_data(),
    )

    markdown = render_vault_markdown("TEST01", "20260301T000000000000", narratives)

    assert "# TEST01" in markdown
    assert "20260301T000000000000" in markdown
    assert "Test headline" in markdown
    assert "Resumen 1" in markdown
    assert "Hallazgo A" in markdown
    assert "alta" in markdown
    assert "Resumen evidencia 1" in markdown
    assert "V1(U:10)" in markdown
    assert "V2(E:5)" in markdown
    assert "Síntesis del período texto" in markdown
    assert "Hipótesis texto" in markdown
    assert "Vacío 1" in markdown
    assert "Acción 1" in markdown
    assert "Escenario 1" in markdown
    assert "Interpretación 1" in markdown
    assert "Tema A" in markdown
    assert "Explicación A" in markdown


def test_render_vault_markdown_empty_coincidencias_falls_back_to_modelo_experto_razon():
    narratives = RunNarratives(
        status="success",
        historical=_historical_data(),
        inference=_inference_data(),
        expert_alignment=_expert_alignment_data(coincidencias=[]),
    )

    markdown = render_vault_markdown("TEST01", "run1", narratives)

    assert "Sin discusión experta" in markdown


def test_render_vault_markdown_partial_narratives_show_placeholder_sections():
    narratives = RunNarratives(
        status="partial",
        historical=_historical_data(),
        inference=None,
        expert_alignment=None,
        missing_files=["inference.out.json", "expert-alignment.out.json"],
    )

    markdown = render_vault_markdown("TEST01", "run1", narratives)

    assert markdown.count("Sección no disponible en esta corrida") == 2


# ---------------------------------------------------------------------------
# render() + CLI (task 2.5 / 2.6)
# ---------------------------------------------------------------------------


def test_render_returns_skipped_incomplete_when_no_runs_exist(tmp_path):
    outcome = vault_contract.render("NOCIRCUIT", runs_root=tmp_path, vault_root=tmp_path / "vault")

    assert outcome.status == "skipped_incomplete"
    assert outcome.errors


def test_cli_render_success_exit_zero(tmp_path, capsys):
    runs_root = tmp_path / "runs"
    _make_run_dir(
        runs_root,
        "TEST01",
        "20260301T000000000000",
        historical=_historical_data(),
        inference=_inference_data(),
        expert_alignment=_expert_alignment_data(),
    )
    vault_root = tmp_path / "vault"

    exit_code = vault_contract.main(
        ["render", "TEST01", "--runs-root", str(runs_root), "--vault-root", str(vault_root)]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    assert payload["circuito"] == "TEST01"
    assert (vault_root / "TEST01.md").exists()


def test_cli_render_partial_exit_zero(tmp_path, capsys):
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "TEST01" / "run1"
    run_dir.mkdir(parents=True)
    _write_out_json(run_dir / "historical.out.json", _historical_data())
    vault_root = tmp_path / "vault"

    exit_code = vault_contract.main(
        ["render", "TEST01", "--runs-root", str(runs_root), "--vault-root", str(vault_root)]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "partial"
    assert (vault_root / "TEST01.md").exists()


def test_cli_render_missing_historical_returns_skipped_incomplete(tmp_path, capsys):
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "TEST01" / "run1"
    run_dir.mkdir(parents=True)
    _write_out_json(run_dir / "inference.out.json", _inference_data())
    vault_root = tmp_path / "vault"

    exit_code = vault_contract.main(
        ["render", "TEST01", "--runs-root", str(runs_root), "--vault-root", str(vault_root)]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "skipped_incomplete"
    assert not (vault_root / "TEST01.md").exists()


def test_cli_render_usage_error_on_blank_circuito(capsys):
    exit_code = vault_contract.main(["render", " "])

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "usage_error"


def test_outcome_json_text_has_sorted_keys():
    outcome = vault_contract.VaultOutcome(status="usage_error")

    text = outcome.to_json_text()
    parsed = json.loads(text)
    assert list(parsed.keys()) == sorted(parsed.keys())
