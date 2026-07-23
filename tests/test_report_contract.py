from __future__ import annotations

import json

import pytest

import chec_local_interpreter.report_contract as report_contract
from chec_local_interpreter.agent_output import ReportPipelineError
from chec_local_interpreter.report_contract import (
    UNKNOWN_MODEL_LABEL,
    ReportOutcome,
    normalize_request,
    preflight_report,
    prepare_alignment,
    prepare_report,
    render_report,
)


def test_normalize_request_requires_circuito():
    with pytest.raises(ValueError, match="circuito is required"):
        normalize_request("")


def test_normalize_request_rejects_lone_fecha_inicio():
    with pytest.raises(ValueError, match="provided together"):
        normalize_request("C1", "2026-01-01")


def test_normalize_request_rejects_lone_fecha_fin():
    with pytest.raises(ValueError, match="provided together"):
        normalize_request("C1", None, "2026-01-02")


def test_normalize_request_preserves_paired_dates_and_runtime_metadata():
    request = normalize_request(
        " C1 ",
        "2026-01-01",
        "2026-01-02",
        runtime="pi",
        provider="openai",
        model="gpt-5.6-terra",
    )

    assert request.to_json() == {
        "circuito": "C1",
        "fecha_inicio": "2026-01-01",
        "fecha_fin": "2026-01-02",
        "runtime": {
            "runtime": "pi",
            "provider": "openai",
            "model": "gpt-5.6-terra",
            "model_known": True,
        },
    }


def test_unknown_model_is_explicit_not_invented():
    request = normalize_request("C1", runtime="unknown-runtime")

    assert request.runtime.to_json()["model"] == UNKNOWN_MODEL_LABEL
    assert request.runtime.to_json()["model_known"] is False


def test_outcome_json_shape_is_stable_and_hides_non_success_report_html():
    request = normalize_request("C1")
    outcome = ReportOutcome(
        status="ready_for_roles",
        request=request,
        run_dir="/tmp/run",
        report_html="/tmp/report.html",
        next_actions=["run_roles"],
        degradations=["optional stage skipped"],
        errors=[],
    )

    assert outcome.to_json() == {
        "schema_version": "report-contract/v1",
        "status": "ready_for_roles",
        "request": request.to_json(),
        "run_dir": "/tmp/run",
        "report_html": None,
        "resolved_window": None,
        "next_actions": ["run_roles"],
        "degradations": ["optional stage skipped"],
        "errors": [],
    }


def test_success_outcome_exposes_report_html():
    request = normalize_request("C1")
    outcome = ReportOutcome(status="success", request=request, report_html="/tmp/report.html")

    assert outcome.to_json()["report_html"] == "/tmp/report.html"


def test_preflight_report_delegates_to_canonical_preflight(monkeypatch):
    def fake_preflight(circuito, fecha_inicio=None, fecha_fin=None, *, data_path=None):
        assert (circuito, fecha_inicio, fecha_fin, data_path) == (
            "C1",
            "2026-01-01",
            "2026-01-02",
            "data.csv",
        )
        return report_contract.report_pipeline.ReportPreflight(
            circuito="C1",
            fecha_inicio="2026-01-01",
            fecha_fin="2026-01-02",
            event_count=2,
        )

    monkeypatch.setattr(report_contract.report_pipeline, "preflight", fake_preflight)
    request = normalize_request("C1", "2026-01-01", "2026-01-02")

    outcome = preflight_report(request, data_path="data.csv")

    assert outcome.status == "awaiting_confirmation"
    assert outcome.resolved_window == {
        "circuito": "C1",
        "fecha_inicio": "2026-01-01",
        "fecha_fin": "2026-01-02",
        "event_count": 2,
    }


def test_prepare_report_delegates_to_canonical_pipeline(monkeypatch, tmp_path):
    calls = []
    run_dir = tmp_path / "run"

    def fake_prepare(circuito, fecha_inicio=None, fecha_fin=None, *, data_path=None, runs_root=None):
        calls.append((circuito, fecha_inicio, fecha_fin, data_path, runs_root))
        return run_dir

    monkeypatch.setattr(report_contract.report_pipeline, "prepare", fake_prepare)
    request = normalize_request("C1", "2026-01-01", "2026-01-02")

    outcome = prepare_report(request, data_path="data.csv", runs_root="runs")

    assert calls == [("C1", "2026-01-01", "2026-01-02", "data.csv", "runs")]
    assert outcome.status == "ready_for_roles"
    assert outcome.run_dir == str(run_dir)
    assert outcome.next_actions == ["run_historical_inference_and_auto_simulator_roles"]


def test_preflight_report_returns_execution_error_without_run_dir_on_pipeline_failure(monkeypatch):
    def fake_preflight(*args, **kwargs):
        raise ReportPipelineError("No events found")

    monkeypatch.setattr(report_contract.report_pipeline, "preflight", fake_preflight)
    outcome = preflight_report(normalize_request("C1"))

    assert outcome.status == "execution_error"
    assert outcome.run_dir is None
    assert outcome.report_html is None
    assert outcome.errors == ["No events found"]


def test_prepare_report_returns_execution_error_on_pipeline_failure(monkeypatch):
    def fake_prepare(*args, **kwargs):
        raise ReportPipelineError("Circuit not found")

    monkeypatch.setattr(report_contract.report_pipeline, "prepare", fake_prepare)
    outcome = prepare_report(normalize_request("missing"))

    assert outcome.status == "execution_error"
    assert outcome.report_html is None
    assert outcome.errors == ["Circuit not found"]


def test_prepare_alignment_delegates_to_canonical_pipeline(monkeypatch, tmp_path):
    run_dir = tmp_path / "run"
    alignment_path = run_dir / "expert-alignment.bc.json"

    def fake_prepare_expert_alignment(received_run_dir, *, pdf_discussions_path=None):
        assert received_run_dir == run_dir
        assert pdf_discussions_path == "table.xlsx"
        return alignment_path

    monkeypatch.setattr(
        report_contract.report_pipeline,
        "prepare_expert_alignment",
        fake_prepare_expert_alignment,
    )

    outcome = prepare_alignment(normalize_request("C1"), run_dir, pdf_discussions_path="table.xlsx")

    assert outcome.status == "ready_for_alignment"
    assert outcome.run_dir == str(run_dir)
    assert outcome.next_actions == ["run_expert_alignment_role"]


def test_prepare_alignment_required_stage_failure_is_execution_error(monkeypatch, tmp_path):
    def fake_prepare_expert_alignment(*args, **kwargs):
        raise ReportPipelineError("historical output missing")

    monkeypatch.setattr(
        report_contract.report_pipeline,
        "prepare_expert_alignment",
        fake_prepare_expert_alignment,
    )
    run_dir = tmp_path / "run"

    outcome = prepare_alignment(normalize_request("C1"), run_dir)

    assert outcome.status == "execution_error"
    assert outcome.run_dir == str(run_dir)
    assert outcome.report_html is None
    assert outcome.errors == ["historical output missing"]


def test_render_report_failure_hides_report_html(monkeypatch, tmp_path):
    def fake_render(*args, **kwargs):
        raise ReportPipelineError("expert alignment output missing")

    monkeypatch.setattr(report_contract.report_pipeline, "render", fake_render)
    run_dir = tmp_path / "run"

    outcome = render_report(normalize_request("C1"), run_dir)

    assert outcome.status == "execution_error"
    assert outcome.report_html is None
    assert outcome.errors == ["expert alignment output missing"]


def test_render_report_delegates_to_canonical_pipeline_and_passes_runtime_metadata(monkeypatch, tmp_path):
    run_dir = tmp_path / "run"
    report_path = tmp_path / "report.html"
    calls = []

    def fake_render(received_run_dir, *, output_dir=None, llm_provider=None, llm_model=None):
        calls.append((received_run_dir, output_dir, llm_provider, llm_model))
        return report_path

    monkeypatch.setattr(report_contract.report_pipeline, "render", fake_render)
    request = normalize_request("C1", runtime="pi", provider="el-gentleman", model="gpt-5.6-terra")

    outcome = render_report(
        request,
        run_dir,
        output_dir="html",
        llm_provider=request.runtime.provider,
        llm_model=request.runtime.model,
    )

    assert calls == [(run_dir, "html", "el-gentleman", "gpt-5.6-terra")]
    assert outcome.status == "success"
    assert outcome.report_html == str(report_path)


def test_render_report_resolves_pi_model_from_settings_fallback(monkeypatch, tmp_path):
    home = tmp_path / "home"
    settings_dir = home / ".pi" / "agent"
    settings_dir.mkdir(parents=True)
    (settings_dir / "settings.json").write_text(
        json.dumps({"defaultProvider": "openai-codex", "defaultModel": "gpt-5.5"}),
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"
    report_path = tmp_path / "report.html"
    calls = []

    def fake_render(received_run_dir, *, output_dir=None, llm_provider=None, llm_model=None):
        calls.append((llm_provider, llm_model))
        return report_path

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CHEC_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("CHEC_LLM_MODEL", raising=False)
    monkeypatch.setattr(report_contract.report_pipeline, "render", fake_render)

    outcome = render_report(normalize_request("C1", runtime="pi"), run_dir)

    assert calls == [("el-gentleman", "openai-codex/gpt-5.5")]
    assert outcome.request is not None
    assert outcome.request.runtime.to_json()["model"] == "openai-codex/gpt-5.5"


def test_render_report_prefers_latest_pi_session_model_over_settings(monkeypatch, tmp_path):
    home = tmp_path / "home"
    settings_dir = home / ".pi" / "agent"
    settings_dir.mkdir(parents=True)
    (settings_dir / "settings.json").write_text(
        json.dumps({"defaultProvider": "openai-codex", "defaultModel": "gpt-5.5"}),
        encoding="utf-8",
    )
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    encoded_cwd = "--" + "-".join(project_dir.resolve().parts[1:]) + "--"
    session_dir = home / ".pi" / "agent" / "sessions" / encoded_cwd
    session_dir.mkdir(parents=True)
    (session_dir / "2026-07-15T00-00-00-000Z_session.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"type": "model_change", "provider": "openai-codex", "modelId": "gpt-5.4"}),
                json.dumps({"type": "message", "message": {"role": "assistant", "provider": "openai-codex", "model": "gpt-5.6-terra"}}),
            ]
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.html"
    calls = []

    def fake_render(received_run_dir, *, output_dir=None, llm_provider=None, llm_model=None):
        calls.append((llm_provider, llm_model))
        return report_path

    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CHEC_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("CHEC_LLM_MODEL", raising=False)
    monkeypatch.setattr(report_contract.report_pipeline, "render", fake_render)

    outcome = render_report(normalize_request("C1", runtime="pi"), tmp_path / "run")

    assert calls == [("el-gentleman", "openai-codex/gpt-5.6-terra")]
    assert outcome.request is not None
    assert outcome.request.runtime.to_json()["model_known"] is True


def test_cli_parse_outputs_json(capsys):
    exit_code = report_contract.main(["parse", "C1", "--runtime", "pi"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "report-contract/v1"
    assert payload["status"] == "awaiting_confirmation"
    assert payload["request"]["circuito"] == "C1"
    assert payload["request"]["runtime"]["runtime"] == "pi"


def test_cli_lone_date_returns_usage_error(capsys):
    exit_code = report_contract.main(["parse", "C1", "2026-01-01"])

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "usage_error"
    assert "provided together" in payload["errors"][0]
