from __future__ import annotations

from pathlib import Path

import pytest

from chec_local_interpreter.report_contract import normalize_request

PROJECT_ROOT = Path(__file__).resolve().parents[1]

ADAPTERS = {
    "claude": PROJECT_ROOT / ".claude" / "skills" / "report" / "SKILL.md",
    "opencode": PROJECT_ROOT / ".opencode" / "agent" / "report.md",
    "codex": PROJECT_ROOT / ".codex" / "skills" / "report" / "SKILL.md",
    "pi": PROJECT_ROOT / ".pi" / "skills" / "report" / "SKILL.md",
}

FORBIDDEN_BUSINESS_MARKERS = (
    "build_daily_series",
    "detect_critical_periods",
    "rank_critical_points",
    "render_llm_analysis(",
    "simulate_automatic_minmax_sensitivity(",
    "export_latest_interpretability_report",
    "cargar_modelo_mgcecdl(",
    "cargar_estudio_optuna_mgcecdl(",
    "site/assets/site/results",
)

FORBIDDEN_DIRECT_IMPORTS = (
    "from chec_local_interpreter.critical_points",
    "from chec_local_interpreter.context_builder",
    "from chec_local_interpreter.simulator",
    "from chec_local_interpreter.plotting",
    "from chec_impacto.training",
    "from chec_impacto.interpretability",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_runtime_adapter_files_exist():
    for runtime, path in ADAPTERS.items():
        assert path.exists(), f"missing {runtime} adapter at {path}"


def test_runtime_adapter_base_name_is_report():
    assert "name: report" in _read(ADAPTERS["claude"])
    assert ADAPTERS["opencode"].stem == "report"
    assert "name: report" in _read(ADAPTERS["codex"])
    assert "name: report" in _read(ADAPTERS["pi"])


def test_runtime_invocation_discovery_is_explicit():
    assert "/report <circuito> [fecha_inicio fecha_fin]" in _read(ADAPTERS["claude"])

    opencode = _read(ADAPTERS["opencode"])
    assert "@report <circuito> [fecha_inicio fecha_fin]" in opencode
    assert "Until verified" in opencode

    codex = _read(ADAPTERS["codex"])
    assert "$report <circuito> [fecha_inicio fecha_fin]" in codex
    assert "Do not document or suggest `/report` for Codex" in codex

    pi = _read(ADAPTERS["pi"])
    assert "/skill:report <circuito> [fecha_inicio fecha_fin]" in pi


def test_adapters_point_to_shared_contract_and_canonical_runbook():
    for runtime, path in ADAPTERS.items():
        content = _read(path)
        assert "report_contract" in content, runtime
        assert "report_pipeline.py" in content, runtime
        if runtime != "claude":
            assert ".claude/skills/report/SKILL.md" in content, runtime


def test_equivalent_runtime_inputs_normalize_to_same_report_request_except_metadata():
    base = normalize_request("C1", "2026-01-01", "2026-01-02")
    runtime_requests = [
        normalize_request("C1", "2026-01-01", "2026-01-02", runtime="claude"),
        normalize_request("C1", "2026-01-01", "2026-01-02", runtime="opencode"),
        normalize_request("C1", "2026-01-01", "2026-01-02", runtime="codex"),
        normalize_request("C1", "2026-01-01", "2026-01-02", runtime="pi"),
    ]

    for request in runtime_requests:
        assert request.circuito == base.circuito
        assert request.fecha_inicio == base.fecha_inicio
        assert request.fecha_fin == base.fecha_fin


@pytest.mark.parametrize(
    "runtime,path",
    [(runtime, path) for runtime, path in ADAPTERS.items() if runtime != "claude"],
)
def test_runtime_adapters_do_not_contain_business_logic(runtime: str, path: Path):
    content = _read(path)

    for marker in FORBIDDEN_BUSINESS_MARKERS:
        assert marker not in content, f"{runtime} adapter duplicates or calls business logic: {marker}"


def test_runtime_adapters_do_not_directly_import_domain_modules():
    for runtime, path in ADAPTERS.items():
        if runtime == "claude":
            continue
        content = _read(path)
        for marker in FORBIDDEN_DIRECT_IMPORTS:
            assert marker not in content, f"{runtime} adapter bypasses report_contract: {marker}"


def test_runtime_adapters_use_shared_preflight_command_shape():
    expected = "python -m chec_local_interpreter.report_contract preflight"
    for runtime, path in ADAPTERS.items():
        normalized = " ".join(_read(path).split())
        assert expected in normalized, runtime


def test_runtime_contract_documentation_matrix_matches_adapters():
    docs = _read(PROJECT_ROOT / "docs" / "report-runtime-contract.md")

    assert "/report <circuito> [fecha_inicio fecha_fin]" in docs
    assert "@report <circuito> [fecha_inicio fecha_fin]" in docs
    assert "$report <circuito> [fecha_inicio fecha_fin]" in docs
    assert "/skill:report <circuito> [fecha_inicio fecha_fin]" in docs
    assert "Codex must not prefer `/report`" in docs
    assert "no automatic publishing" in docs
    assert "no site asset mutation" in docs


def test_pi_adapter_uses_runtime_model_resolution_not_frontmatter():
    pi = _read(ADAPTERS["pi"])
    docs = _read(PROJECT_ROOT / "docs" / "report-runtime-contract.md")

    assert "report_contract render <circuito> --run-dir <run_dir> --runtime pi" in pi
    assert "Pi session history" in docs
    assert "settings.json" in docs
    assert "frontmatter" in docs


def test_runtime_adapters_forbid_ambiguous_generic_worker_dispatch():
    for runtime in ("codex", "opencode", "pi"):
        content = _read(ADAPTERS[runtime])

        assert "one explicit task per role" in content, runtime
        assert "Never launch multiple identical workers" in content, runtime
        assert "historical" in content and "inference" in content and "auto-simulator" in content, runtime


def test_runtime_adapters_reject_read_only_workers_for_role_authoring():
    pi = _read(ADAPTERS["pi"])
    assert "inspect the candidate agent's tool permissions" in pi
    assert "read-only generic worker" in pi
    assert "gentle-ai-worker" in pi
    assert "historical.out.json" in pi and "inference.out.json" in pi
    assert "stalled role" in pi

    for runtime in ("codex", "opencode"):
        content = _read(ADAPTERS[runtime])
        assert "verify that a candidate worker can run" in content, runtime
        assert "read-only/research-only worker" in content, runtime
        assert "historical.out.json" in content and "inference.out.json" in content, runtime
        assert "stalled role" in content, runtime


def test_runtime_adapters_require_measured_token_usage_when_available():
    pi = _read(ADAPTERS["pi"])
    assert "Record Pi subagent usage before render" in pi
    assert "record-usage --run-dir <run_dir> --stage <role> --total <n>" in pi
    assert "verify-usage" in pi
    assert "Do not scrape prose or session history" in pi
    assert '"historical": {"total": 77611}' in pi

    for runtime in ("codex", "opencode"):
        content = _read(ADAPTERS[runtime])
        assert "Token accounting" in content, runtime
        assert "record-usage --run-dir <run_dir> --stage <role>" in content, runtime
        assert "verify-usage" in content, runtime
        assert "actual structured usage" in content, runtime


def test_runtime_adapters_use_project_virtualenv_before_declaring_environment_missing():
    for runtime, path in ADAPTERS.items():
        content = _read(path)
        assert "PYTHONPATH=src .venv/bin/python" in content, runtime
        assert "bare `python`/`python3`" in content, runtime


def test_runtime_docs_state_local_only_no_external_side_effects():
    checked_paths = list(ADAPTERS.values()) + [PROJECT_ROOT / "docs" / "report-runtime-contract.md"]
    for path in checked_paths:
        normalized = " ".join(_read(path).lower().split())
        assert "external llm" in normalized or "no llm call" in normalized or "no live llm call" in normalized
        assert (
            "automatic publishing" in normalized
            or "publish automatically" in normalized
            or "never touches `site/assets/site/results/`" in normalized
        )
        assert "model training" in normalized or "never trains" in normalized or "do not train" in normalized
