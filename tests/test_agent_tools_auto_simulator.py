from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from chec_local_interpreter.agent_tools.auto_simulator import (
    TOOL_VERSION,
    build_context,
    validate,
)
from chec_local_interpreter.circuit_identity import canonical_circuit_identity

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_TOOLS_MODULE = PROJECT_ROOT / "src" / "chec_local_interpreter" / "agent_tools" / "auto_simulator.py"


def _sample_context() -> dict:
    return {
        "contexto": {
            "circuito": "DON23L13",
            "periodo": {"inicio": "2026-01-01", "fin": "2026-01-31"},
            "modelo": "MGCECDLClassifier",
        },
        "metadata": {"warnings": []},
        "variables_priorizadas": ["NR_T", "DDT"],
        "variables_bajo_analisis": ["NR_T", "DDT", "CNT_TRF"],
        "tabla_simulador_automatico": [
            {"variable": "NR_T", "escenario": "base", "prob_riesgo": 0.2},
            {"variable": "NR_T", "escenario": "maximo_observado", "prob_riesgo": 0.6},
        ],
        "costos_items_contratos": {"disponible": False, "advertencias": [], "coincidencias": []},
        "curvas_softmax_top_variables": {"variables": [], "metadata": {"warnings": []}},
        "contexto_inferencia_resumen": {"escenarios": []},
    }


def _valid_response() -> dict:
    return {
        "titulo": "Sensibilidad minimo/maximo del circuito",
        "resumen": ["El riesgo aumenta con NR_T en el escenario maximo."],
        "variables_mas_sensibles": ["NR_T"],
        "patrones_minimo_maximo": ["NR_T pasa de 0.2 a 0.6 entre base y maximo."],
        "hallazgos_para_criticidad": ["NR_T es la variable mas sensible en este circuito."],
        "limitaciones": ["Solo se usa la tabla entregada."],
        "contexto_reutilizado": ["tabla_simulador_automatico"],
    }


def _run_cli(verb: str, payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    return _run_cli_raw(verb, json.dumps(payload, ensure_ascii=False), cwd)


def _run_cli_raw(verb: str, raw_stdin: str, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "chec_local_interpreter.agent_tools.auto_simulator", verb],
        input=raw_stdin,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        timeout=30,
    )


def test_build_context_envelope_shape():
    context = _sample_context()
    envelope = build_context(context)

    assert set(envelope.keys()) == {"meta", "context", "prompt"}
    assert set(envelope["meta"].keys()) == {"circuito", "tool_version"}
    assert envelope["meta"]["circuito"] == "DON23L13"
    assert envelope["meta"]["tool_version"] == TOOL_VERSION
    assert isinstance(envelope["prompt"], str) and envelope["prompt"]
    assert envelope["context"] == context


def test_build_context_falls_back_to_unknown_circuito_when_missing():
    context = _sample_context()
    del context["contexto"]
    envelope = build_context(context)
    assert envelope["meta"]["circuito"] == "unknown"

    context2 = _sample_context()
    context2["contexto"] = {}
    envelope2 = build_context(context2)
    assert envelope2["meta"]["circuito"] == "unknown"


def test_build_context_cli_matches_in_process_call(tmp_path):
    context = _sample_context()
    result = _run_cli("build-context", context, tmp_path)
    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["meta"]["circuito"] == "DON23L13"
    assert envelope == build_context(context)


def test_validate_verb_accepts_valid_response_exits_zero():
    response = _valid_response()
    result, exit_code = validate({"response_text": json.dumps(response, ensure_ascii=False)})
    assert exit_code == 0
    assert result["ok"] is True
    assert result["data"] == response


def test_validate_cli_rejects_response_missing_required_key_and_writes_artifact(tmp_path):
    response = _valid_response()
    del response["limitaciones"]

    validate_payload = {"response_text": json.dumps(response, ensure_ascii=False)}
    result = _run_cli("validate", validate_payload, tmp_path)

    assert result.returncode == 1
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]

    artifact_dir = tmp_path / "reports" / "interpretability" / "artifacts" / "auto-simulator" / "run"
    assert artifact_dir.is_dir()
    artifact_files = list(artifact_dir.glob("*.json"))
    assert artifact_files, "expected a failure artifact under the auto-simulator artifacts root"
    saved = json.loads(artifact_files[0].read_text())
    assert saved["errors"]
    assert "response_text" in saved


def test_validate_cli_with_circuito_writes_artifact_under_circuit_subdirectory(tmp_path):
    # Regression: validate() used to write every failure artifact to a
    # single shared "run" subdirectory with no circuit attribution, unlike
    # historical.py/pdf_discussion.py. Passing back the circuito from
    # build-context's meta.circuito should namespace the artifact by circuit.
    response = _valid_response()
    del response["limitaciones"]

    validate_payload = {
        "response_text": json.dumps(response, ensure_ascii=False),
        "circuito": "DON23L13",
    }
    result = _run_cli("validate", validate_payload, tmp_path)

    assert result.returncode == 1
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]

    safe_name = canonical_circuit_identity("DON23L13")
    artifact_dir = tmp_path / "reports" / "interpretability" / "artifacts" / "auto-simulator" / safe_name
    assert artifact_dir.is_dir()
    artifact_files = list(artifact_dir.glob("*.json"))
    assert artifact_files, "expected a failure artifact under the circuit's own subdirectory"
    saved = json.loads(artifact_files[0].read_text())
    assert saved["errors"]
    assert "response_text" in saved

    fallback_dir = tmp_path / "reports" / "interpretability" / "artifacts" / "auto-simulator" / "run"
    assert not fallback_dir.exists()


def test_validate_cli_rejects_malformed_json_response(tmp_path):
    validate_payload = {"response_text": "not valid json {{"}
    result = _run_cli("validate", validate_payload, tmp_path)

    assert result.returncode == 1
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]


def test_cli_build_context_empty_stdin_is_malformed_not_a_crash(tmp_path):
    result = _run_cli_raw("build-context", "", tmp_path)

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]


def test_cli_build_context_missing_contexto_key_is_malformed_not_a_crash(tmp_path):
    context = _sample_context()
    del context["contexto"]

    result = _run_cli("build-context", context, tmp_path)

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]


def test_cli_validate_missing_response_text_is_malformed_not_a_crash(tmp_path):
    result = _run_cli("validate", {}, tmp_path)

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]


def test_validate_verb_reuses_validate_auto_simulator_response_unmodified():
    """No duplicate/forked validator — the auto-simulator CLI must import
    `validate_auto_simulator_response` from `llm_validation`, not define its
    own copy."""
    source = AGENT_TOOLS_MODULE.read_text()
    tree = ast.parse(source)
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "chec_local_interpreter.llm_validation":
            imported_names.update(alias.name for alias in node.names)
    assert "validate_auto_simulator_response" in imported_names
    assert "def validate_auto_simulator_response(" not in source


def test_auto_simulator_agent_tools_never_references_frozen_model_boundary():
    source = AGENT_TOOLS_MODULE.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "chec_impacto.training" not in alias.name
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "chec_impacto" not in module or "training" not in module
    assert "chec_impacto.training" not in source
    assert "mgcecdl_classifier_best" not in source
