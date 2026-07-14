from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from chec_local_interpreter.agent_tools.inference import (
    TOOL_VERSION,
    build_context,
    validate,
)
from chec_local_interpreter.inference_validation import (
    allowed_critical_point_ids,
    allowed_dates,
    allowed_scenario_names,
    allowed_variables,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_TOOLS_MODULE = PROJECT_ROOT / "src" / "chec_local_interpreter" / "agent_tools" / "inference.py"

_ESCENARIO_NOMBRE = "Top P97 por UITI_VANO — período completo"


def _sample_context() -> dict:
    return {
        "circuito_interes": "DON23L13",
        "fecha_inicio": "2026-01-01",
        "fecha_fin": "2026-01-31",
        "fechas_interes": ["2026-01-10"],
        "top_n_vanos": 20,
        "top_vanos_percentile": None,
        "top_k_vars": 20,
        "filtro_uiti_max": None,
        "ventana_climatica_horas": 12,
        "modelo": "mgcecdl_clasificacion",
        "modelo_tipo": "mgcecdl_clasificacion",
        "n_eventos": 10,
        "n_vanos": 5,
        "n_features": 2,
        "features": ["NR_T", "DDT"],
        "graph_feature_order": ["NR_T", "DDT"],
        "estimated_graph_source": "reconstruccion_mgcecdl_rbf",
        "estimated_graph_rbf_sigma": 1.0,
        "graph_html_paths": [
            {
                "escenario": _ESCENARIO_NOMBRE,
                "path": "top_uiti_periodo.html",
                "fuente": "reconstruccion_mgcecdl_rbf",
                "pesos": "normalizados_0_1_por_maximo",
            }
        ],
        "escenarios": [
            {
                "nombre": _ESCENARIO_NOMBRE,
                "criterio": "UITI_VANO_PROM",
                "fechas_interes": [],
                "n_eventos": 10,
                "n_vanos_efectivo": 5,
                "top_k_vars": 20,
                "ventana_climatica_horas": 12,
                "top_variables": [{"nombre": "NR_T", "score_normalizado": 0.9}],
                "modos": [{"nombre": "Entorno, riesgo y clima", "score_normalizado": 0.5}],
                "tabla_top_vanos": [],
                "grafo": {
                    "path": "top_uiti_periodo.html",
                    "fuente": "reconstruccion_mgcecdl_rbf",
                    "pesos": "normalizados_0_1_por_maximo",
                },
            }
        ],
        "metadata": {
            "uiti_vano_es_objetivo": True,
            "features_no_incluyen_objetivo": True,
            "grafo_estimado_desde_reconstruccion": True,
        },
    }


def _valid_output(context: dict) -> dict:
    return {
        "contexto": {
            "circuito": context["circuito_interes"],
            "periodo": {"inicio": context["fecha_inicio"], "fin": context["fecha_fin"]},
            "modelo": context["modelo"],
        },
        "entregables": {
            "grafos_html": [
                {
                    "escenario": _ESCENARIO_NOMBRE,
                    "path": "top_uiti_periodo.html",
                    "fuente": "reconstruccion_mgcecdl_rbf",
                    "pesos": "normalizados_0_1_por_maximo",
                }
            ]
        },
        "escenarios": [
            {"nombre": _ESCENARIO_NOMBRE, "interpretacion": "El escenario muestra concentracion en NR_T."}
        ],
        "discusion_grafos": [
            {"seccion": "periodo_completo", "lectura": "NR_T se asocia con COD_CAUSA en el grafo experto."}
        ],
        "coherencia_grafo_modelo": [
            "NR_T es coherente con una hipotesis operativa de riesgo por vegetacion."
        ],
        "hallazgos": ["NR_T aparece como variable relevante en el periodo."],
        "limitaciones": ["Kernel SHAP explica comportamiento del modelo."],
        "inferencias_predictivas": [
            {
                "horizonte": "periodo analizado",
                "riesgo": "moderado",
                "justificacion_modelo": "El modelo sugiere asociacion con NR_T.",
            }
        ],
        "hipotesis_modelo_predictivo": {
            "periodo_completo": ["El modelo es consistente con riesgo por vegetacion."],
            "puntos_criticos": [],
        },
    }


def _valid_output_with_provenance(context: dict) -> dict:
    output = _valid_output(context)
    output["escenarios"][0]["provenance"] = {
        "data_ref": ["NR_T", "2026-01-10", _ESCENARIO_NOMBRE],
        "agent": "inference",
        "rule": "02_circuit_scenario_interpreter",
    }
    return output


def _run_cli(verb: str, payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    return _run_cli_raw(verb, json.dumps(payload, ensure_ascii=False), cwd)


def _run_cli_raw(verb: str, raw_stdin: str, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "chec_local_interpreter.agent_tools.inference", verb],
        input=raw_stdin,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        timeout=30,
    )


def test_build_context_envelope_shape_matches_allowed_helpers():
    context = _sample_context()
    envelope = build_context(context)

    assert set(envelope.keys()) == {"meta", "context", "prompt", "allowed"}
    assert set(envelope["meta"].keys()) == {"circuito", "tool_version"}
    assert envelope["meta"]["circuito"] == "DON23L13"
    assert envelope["meta"]["tool_version"] == TOOL_VERSION
    assert isinstance(envelope["prompt"], str) and envelope["prompt"]
    assert envelope["context"] == context

    assert set(envelope["allowed"].keys()) == {
        "dates",
        "critical_point_ids",
        "variables",
        "scenario_names",
    }
    assert sorted(envelope["allowed"]["dates"]) == sorted(allowed_dates(context))
    assert sorted(envelope["allowed"]["critical_point_ids"]) == sorted(allowed_critical_point_ids(context))
    assert sorted(envelope["allowed"]["variables"]) == sorted(allowed_variables(context))
    assert sorted(envelope["allowed"]["scenario_names"]) == sorted(allowed_scenario_names(context))


def test_build_context_missing_circuito_interes_falls_back_to_unknown():
    context = _sample_context()
    del context["circuito_interes"]
    envelope = build_context(context)
    assert envelope["meta"]["circuito"] == "unknown"


def test_build_context_cli_matches_in_process_call(tmp_path):
    context = _sample_context()
    result = _run_cli("build-context", context, tmp_path)
    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["meta"]["circuito"] == "DON23L13"
    assert envelope == build_context(context)


def test_validate_verb_accepts_valid_response_without_provenance():
    context = _sample_context()
    envelope = build_context(context)
    response = _valid_output(envelope["context"])

    result, exit_code = validate({"response_text": json.dumps(response, ensure_ascii=False), "context": envelope["context"]})
    assert exit_code == 0, result
    assert result["ok"] is True


def test_validate_verb_accepts_valid_response_with_resolving_provenance():
    context = _sample_context()
    envelope = build_context(context)
    response = _valid_output_with_provenance(envelope["context"])

    result, exit_code = validate({"response_text": json.dumps(response, ensure_ascii=False), "context": envelope["context"]})
    assert exit_code == 0, result
    assert result["ok"] is True


def test_validate_cli_rejects_response_missing_required_key_and_writes_artifact_under_inference_namespace(tmp_path):
    context = _sample_context()
    envelope = build_context(context)
    response = _valid_output(envelope["context"])
    del response["limitaciones"]

    validate_payload = {"response_text": json.dumps(response, ensure_ascii=False), "context": envelope["context"]}
    result = _run_cli("validate", validate_payload, tmp_path)

    assert result.returncode == 1
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]

    artifact_dir = tmp_path / "reports" / "interpretability" / "artifacts" / "inference" / "DON23L13"
    assert artifact_dir.is_dir()
    artifact_files = list(artifact_dir.glob("*.json"))
    assert artifact_files, "expected a failure artifact under the inference-namespaced artifacts root"
    saved = json.loads(artifact_files[0].read_text())
    assert saved["errors"]
    assert "response_text" in saved


def test_validate_cli_rejects_response_with_unresolvable_provenance_and_does_not_publish(tmp_path):
    context = _sample_context()
    envelope = build_context(context)
    response = _valid_output_with_provenance(envelope["context"])
    response["escenarios"][0]["provenance"]["data_ref"] = ["9999-12-31"]

    validate_payload = {"response_text": json.dumps(response, ensure_ascii=False), "context": envelope["context"]}
    result = _run_cli("validate", validate_payload, tmp_path)

    assert result.returncode == 1
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert any("9999-12-31" in error for error in stdout_data["errors"])

    artifact_dir = tmp_path / "reports" / "interpretability" / "artifacts" / "inference" / "DON23L13"
    assert artifact_dir.is_dir()
    assert list(artifact_dir.glob("*.json"))


def test_validate_verb_schema_failure_short_circuits_provenance_check(tmp_path, monkeypatch):
    """Isolates cwd to `tmp_path` first, matching `test_agent_tools_batch.py`'s
    convention: this test deliberately triggers `validate()`'s failure-artifact
    writer, and must never write into the tracked
    `reports/interpretability/artifacts/` tree (subsumed by the autouse
    `conftest.py` fixture, kept explicit here for local readability)."""
    monkeypatch.chdir(tmp_path)
    context = _sample_context()
    envelope = build_context(context)
    response = _valid_output_with_provenance(envelope["context"])
    del response["limitaciones"]
    response["escenarios"][0]["provenance"]["data_ref"] = ["9999-12-31"]

    result, exit_code = validate({"response_text": json.dumps(response, ensure_ascii=False), "context": envelope["context"]})
    assert exit_code == 1
    assert not any("9999-12-31" in error for error in result["errors"]), (
        "provenance must not be evaluated when the schema/guardrail stage already failed"
    )


def test_cli_build_context_empty_stdin_is_malformed_not_a_crash(tmp_path):
    result = _run_cli_raw("build-context", "", tmp_path)

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]


def test_cli_validate_missing_response_text_is_malformed_not_a_crash(tmp_path):
    result = _run_cli("validate", {"context": {}}, tmp_path)

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]


def test_inference_agent_tools_never_references_frozen_model_boundary():
    source = AGENT_TOOLS_MODULE.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "chec_impacto.training" not in alias.name
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "chec_impacto.training" not in module
    assert "chec_impacto.training" not in source
    assert "mgcecdl_classifier_best" not in source
