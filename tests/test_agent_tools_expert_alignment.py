from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from chec_local_interpreter.agent_tools.expert_alignment import (
    TOOL_VERSION,
    build_context,
    validate,
)
from chec_local_interpreter.expert_alignment import (
    _allowed_dates,
    _allowed_pdf_row_indexes,
    _allowed_variables,
    construir_contexto_expert_alignment,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_TOOLS_MODULE = PROJECT_ROOT / "src" / "chec_local_interpreter" / "agent_tools" / "expert_alignment.py"


def _sample_context_payload() -> dict:
    return {
        "circuito": "DON23L13",
        "periodo_inicio": "2026-01-01",
        "periodo_fin": "2026-01-31",
        "fechas_informe": [
            {
                "source": "critical_point",
                "fecha_inicio": "2026-01-10",
                "fecha_fin": "2026-01-10",
                "descripcion": "cp",
                "peso": 3.0,
            }
        ],
        "validation_data": {"period_synthesis": "UITI_VANO sube en el punto crítico."},
        "inference_validation_data": {"hallazgos": ["El modelo resalta CNT_TRF."]},
        "pdf_expert_matches": [
            {
                "Circuito": "DON23L13",
                "Fecha inicio": "2026-01-09",
                "Fecha fin": "2026-01-11",
                "Análisis": "UITI_VANO alto",
                "Evidencia": "Evidencia experta verificable",
                "pdf_row_index": 3,
            }
        ],
        "variables_modelo_predictivo": ["CNT_TRF"],
        "skill_bundle": "Skill bundle de prueba",
    }


def _run_cli(verb: str, payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "chec_local_interpreter.agent_tools.expert_alignment", verb],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        timeout=30,
    )


def _reference_context(payload: dict) -> dict:
    return construir_contexto_expert_alignment(
        circuito=payload["circuito"],
        periodo_inicio=payload["periodo_inicio"],
        periodo_fin=payload["periodo_fin"],
        fechas_informe=payload["fechas_informe"],
        validation_data=payload["validation_data"],
        inference_validation_data=payload["inference_validation_data"],
        pdf_expert_matches=payload["pdf_expert_matches"],
        variables_modelo_predictivo=payload["variables_modelo_predictivo"],
    )


def test_build_context_envelope_shape_matches_allowed_helpers():
    payload = _sample_context_payload()
    envelope = build_context(payload)

    assert set(envelope.keys()) == {"meta", "context", "prompt", "allowed"}
    assert set(envelope["meta"].keys()) == {"circuito", "periodo", "tool_version"}
    assert envelope["meta"]["circuito"] == "DON23L13"
    assert envelope["meta"]["periodo"] == {"inicio": "2026-01-01", "fin": "2026-01-31"}
    assert envelope["meta"]["tool_version"] == TOOL_VERSION
    assert isinstance(envelope["prompt"], str) and envelope["prompt"]
    assert isinstance(envelope["context"], dict)

    reference_context = _reference_context(payload)
    assert set(envelope["allowed"].keys()) == {"dates", "variables", "pdf_row_indexes", "sources"}
    assert sorted(envelope["allowed"]["dates"]) == sorted(_allowed_dates(reference_context))
    assert sorted(envelope["allowed"]["variables"]) == sorted(_allowed_variables(reference_context))
    assert sorted(envelope["allowed"]["pdf_row_indexes"]) == sorted(_allowed_pdf_row_indexes(reference_context))
    assert envelope["allowed"]["sources"] == reference_context["fuentes_disponibles"]


def test_build_context_cli_matches_in_process_call(tmp_path):
    payload = _sample_context_payload()
    result = _run_cli("build-context", payload, tmp_path)
    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["meta"]["circuito"] == "DON23L13"
    assert envelope == build_context(payload)


def _valid_response_for(envelope: dict) -> dict:
    return {
        "contexto": {
            "circuito": "DON23L13",
            "periodo": {"inicio": "2026-01-01", "fin": "2026-01-31"},
            "n_filas_expertas_comparadas": 1,
        },
        "coincidencias": [
            {
                "tema": "UITI_VANO alto",
                "fechas_relacionadas": ["2026-01-10"],
                "fuentes": ["Agente Descriptor", "Agente predictivo", "DON23L13.pdf"],
                "explicacion": "Coinciden temporalmente en el periodo evaluado.",
                "evidencia_pdf": "Evidencia experta verificable",
            }
        ],
        "diferencias": [],
        "hallazgos_expertos_no_cubiertos": [],
        "hallazgos_modelo_no_respaldados_por_pdf": [],
        "variables_a_priorizar": [
            {
                "variable": "CNT_TRF",
                "prioridad": "alta",
                "fuentes_que_la_respaldan": ["Agente predictivo"],
                "justificacion": "Aparece en las fuentes comparadas.",
                "tipo_de_validacion_sugerida": "Revisar eventos fuente.",
            }
        ],
        "sintesis_final": "La comparación es consistente y requiere validación operacional.",
    }


def test_validate_verb_accepts_valid_response_in_process():
    payload = _sample_context_payload()
    envelope = build_context(payload)
    response = _valid_response_for(envelope)

    result, exit_code = validate({"response_text": json.dumps(response, ensure_ascii=False), "context": envelope["context"]})
    assert exit_code == 0
    assert result["ok"] is True


def test_validate_verb_rejects_invalid_response_and_writes_artifact(tmp_path):
    payload = _sample_context_payload()
    envelope = build_context(payload)
    response = _valid_response_for(envelope)
    del response["sintesis_final"]

    validate_payload = {"response_text": json.dumps(response, ensure_ascii=False), "context": envelope["context"]}
    result = _run_cli("validate", validate_payload, tmp_path)

    assert result.returncode != 0
    assert '"ok": true' not in result.stdout
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]

    artifact_dir = tmp_path / "reports" / "interpretability" / "artifacts" / "DON23L13"
    assert artifact_dir.is_dir()
    artifact_files = list(artifact_dir.glob("*.json"))
    assert artifact_files, "expected a failure artifact file under the circuit's artifacts dir"
    saved = json.loads(artifact_files[0].read_text())
    assert saved["errors"]
    assert "response_text" in saved


def test_validate_cli_valid_response_exits_zero_and_prints_ok_true(tmp_path):
    payload = _sample_context_payload()
    envelope = build_context(payload)
    response = _valid_response_for(envelope)

    validate_payload = {"response_text": json.dumps(response, ensure_ascii=False), "context": envelope["context"]}
    result = _run_cli("validate", validate_payload, tmp_path)

    assert result.returncode == 0, result.stderr
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is True
    assert '"ok": true' in result.stdout


def test_agent_tools_expert_alignment_never_references_frozen_model_boundary():
    source = AGENT_TOOLS_MODULE.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "chec_impacto.training" not in alias.name
                assert "chec_impacto" != alias.name.split(".")[0] or "training" not in alias.name
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "chec_impacto" not in module or "training" not in module
    assert "chec_impacto.training" not in source
    assert "mgcecdl_classifier_best" not in source
