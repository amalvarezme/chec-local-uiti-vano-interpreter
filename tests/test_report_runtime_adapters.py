"""El adaptador CANONICO del report y la matriz que lo documenta.

Los espejos por runtime (OpenCode, VS Code Copilot) los cubre
`tests/test_portabilidad_agentes.py`, que ademas los regenera y compara. Aqui
queda lo que es de este lado y de nadie mas: que el runbook de Claude siga siendo
la fuente, que la normalizacion no dependa del runtime, y que la matriz del
documento nombre los tres caminos que existen de verdad.
"""

from __future__ import annotations

from pathlib import Path

from chec_local_interpreter.report_contract import normalize_request

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CANONICAL_ADAPTER = PROJECT_ROOT / ".claude" / "skills" / "report" / "SKILL.md"
RUNTIME_CONTRACT_DOC = PROJECT_ROOT / "docs" / "report-runtime-contract.md"

# Los runtimes que hoy tienen un camino real hasta el contrato compartido.
RUNTIME_KEYS = ("claude", "opencode", "copilot")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_canonical_adapter_exists_and_is_named_report():
    assert CANONICAL_ADAPTER.exists()
    assert "name: report" in _read(CANONICAL_ADAPTER)


def test_canonical_invocation_is_explicit():
    assert "/report <circuito> [fecha_inicio fecha_fin]" in _read(CANONICAL_ADAPTER)


def test_canonical_adapter_routes_through_the_shared_contract():
    content = _read(CANONICAL_ADAPTER)
    assert "report_contract" in content
    assert "report_pipeline.py" in content


def test_canonical_adapter_uses_the_shared_preflight_command_shape():
    normalized = " ".join(_read(CANONICAL_ADAPTER).split())
    assert "python -m chec_local_interpreter.report_contract preflight" in normalized


def test_canonical_adapter_uses_the_project_virtualenv():
    content = _read(CANONICAL_ADAPTER)
    assert "PYTHONPATH=src .venv/bin/python" in content


def test_equivalent_runtime_inputs_normalize_to_the_same_request_except_metadata():
    """Cambiar de editor no puede cambiar que se le pide al pipeline."""

    base = normalize_request("C1", "2026-01-01", "2026-01-02")

    for runtime in RUNTIME_KEYS:
        request = normalize_request("C1", "2026-01-01", "2026-01-02", runtime=runtime)
        assert request.circuito == base.circuito
        assert request.fecha_inicio == base.fecha_inicio
        assert request.fecha_fin == base.fecha_fin
        assert request.runtime.runtime == runtime


def test_runtime_contract_documentation_matrix_names_every_live_runtime():
    docs = _read(RUNTIME_CONTRACT_DOC)

    assert "/report <circuito> [fecha_inicio fecha_fin]" in docs
    assert ".claude/skills/report/SKILL.md" in docs
    assert ".opencode/command/report.md" in docs
    assert ".github/prompts/report.prompt.md" in docs
    assert "scripts/portabilidad_agentes.py" in docs


def test_runtime_contract_documents_model_resolution_without_session_sniffing():
    docs = _read(RUNTIME_CONTRACT_DOC)

    assert "CHEC_LLM_PROVIDER" in docs and "CHEC_LLM_MODEL" in docs
    assert "Desconocido" in docs
    assert "frontmatter" in docs
    # El resolvedor especifico de Pi se retiro; el documento tiene que explicar por
    # que, no dejar el hueco para que alguien reintroduzca un lector por runtime.
    assert "no per-runtime session sniffing" in docs


def test_runtime_docs_state_local_only_no_external_side_effects():
    normalized = " ".join(_read(RUNTIME_CONTRACT_DOC).lower().split())

    assert "no external llm api calls" in normalized
    assert "no automatic publishing" in normalized
    assert "no model training" in normalized
