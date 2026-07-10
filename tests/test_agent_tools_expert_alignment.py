from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from chec_local_interpreter.agent_tools import _atomic_io
from chec_local_interpreter.agent_tools import batch as batch_module
from chec_local_interpreter.agent_tools import expert_alignment as agent_tools_module
from chec_local_interpreter.agent_tools.expert_alignment import (
    TOOL_VERSION,
    build_context,
    validate,
)
from chec_local_interpreter.circuit_identity import canonical_circuit_identity
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
    return _run_cli_raw(verb, json.dumps(payload, ensure_ascii=False), cwd)


def _run_cli_raw(verb: str, raw_stdin: str, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "chec_local_interpreter.agent_tools.expert_alignment", verb],
        input=raw_stdin,
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


def test_build_context_allowed_derives_from_the_compacted_context_not_the_full_one():
    """`fechas_informe` truncates to the top 20 entries in the compacted
    context that is actually used for the prompt and for `validate()`
    (`compactar_contexto_expert_alignment_para_prompt`). The advertised
    `envelope["allowed"]["dates"]` must be computed from that SAME compacted
    context, not the full untruncated one — otherwise the envelope would
    advertise a date as "allowed" that `validate()` (which only ever sees
    the compacted context) actually rejects, failing a genuinely correct
    agent response purely due to this internal inconsistency."""
    payload = _sample_context_payload()
    payload["fechas_informe"] = [
        {
            "source": "critical_point",
            "fecha_inicio": f"2026-03-{i + 1:02d}",
            "fecha_fin": f"2026-03-{i + 1:02d}",
            "descripcion": f"cp{i}",
            "peso": 1.0,
        }
        for i in range(25)
    ]

    envelope = build_context(payload)

    # The compacted context (used for the prompt and validate()) keeps only
    # the top 20 fechas_informe records.
    assert len(envelope["context"]["fechas_informe"]) == 20

    # The full, untruncated context would have advertised the truncated-out
    # date too — this is the bug's shape, asserted here before the fix check.
    full_context = _reference_context(payload)
    truncated_out_date = "2026-03-25"  # the 25th entry (index 24), outside the top 20
    assert truncated_out_date in _allowed_dates(full_context)

    # The fix: allowed.dates must match the compacted context exactly, so a
    # truncated-out date is consistently rejected up front — never
    # advertised as allowed and then rejected by validate().
    assert sorted(envelope["allowed"]["dates"]) == sorted(_allowed_dates(envelope["context"]))
    assert truncated_out_date not in envelope["allowed"]["dates"]


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


def _valid_response_with_provenance_for(envelope: dict) -> dict:
    response = _valid_response_for(envelope)
    response["coincidencias"][0]["provenance"] = {
        "data_ref": ["2026-01-10", "CNT_TRF", "pdf_row_index:3"],
        "agent": "expert-alignment",
        "rule": "02_predictive_variable_prioritization",
    }
    response["variables_a_priorizar"][0]["provenance"] = {
        "data_ref": ["CNT_TRF"],
        "agent": "expert-alignment",
        "rule": "02_predictive_variable_prioritization",
    }
    return response


def test_validate_cli_accepts_valid_response_with_provenance(tmp_path):
    payload = _sample_context_payload()
    envelope = build_context(payload)
    response = _valid_response_with_provenance_for(envelope)

    validate_payload = {"response_text": json.dumps(response, ensure_ascii=False), "context": envelope["context"]}
    result = _run_cli("validate", validate_payload, tmp_path)

    assert result.returncode == 0, result.stderr
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is True


def test_validate_cli_rejects_response_with_invalid_provenance(tmp_path):
    """A response that otherwise passes the base validator must still fail the gate
    when its provenance cites a data_ref outside the allowed universe."""
    payload = _sample_context_payload()
    envelope = build_context(payload)
    response = _valid_response_with_provenance_for(envelope)
    response["coincidencias"][0]["provenance"]["data_ref"] = ["9999-12-31"]

    validate_payload = {"response_text": json.dumps(response, ensure_ascii=False), "context": envelope["context"]}
    result = _run_cli("validate", validate_payload, tmp_path)

    assert result.returncode == 1
    assert '"ok": true' not in result.stdout
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert any("9999-12-31" in error for error in stdout_data["errors"])

    artifact_dir = tmp_path / "reports" / "interpretability" / "artifacts" / "DON23L13"
    assert artifact_dir.is_dir()
    assert list(artifact_dir.glob("*.json")), "expected a failure artifact for the provenance violation"


def test_validate_verb_backwards_compatible_without_provenance_keys(tmp_path):
    """Responses predating the provenance contract (no provenance keys at all)
    must still validate exactly as before WU2."""
    payload = _sample_context_payload()
    envelope = build_context(payload)
    response = _valid_response_for(envelope)
    assert "provenance" not in response["coincidencias"][0]
    assert "provenance" not in response["variables_a_priorizar"][0]

    validate_payload = {"response_text": json.dumps(response, ensure_ascii=False), "context": envelope["context"]}
    result = _run_cli("validate", validate_payload, tmp_path)

    assert result.returncode == 0, result.stderr
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is True


def test_validate_verb_sanitizes_path_traversal_in_circuito(tmp_path):
    """A malicious `circuito` must never let the failure-artifact write escape ARTIFACTS_ROOT."""
    payload = _sample_context_payload()
    envelope = build_context(payload)
    response = _valid_response_for(envelope)
    del response["sintesis_final"]

    malicious_context = dict(envelope["context"])
    malicious_context["circuito"] = "../../evil-outside-artifacts"
    validate_payload = {"response_text": json.dumps(response, ensure_ascii=False), "context": malicious_context}

    result = _run_cli("validate", validate_payload, tmp_path)

    assert result.returncode == 1

    escape_dir = tmp_path / "evil-outside-artifacts"
    assert not escape_dir.exists(), "circuito path traversal escaped the artifacts root"

    artifacts_root = (tmp_path / "reports" / "interpretability" / "artifacts").resolve()
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    artifact_path = Path(stdout_data["artifact_path"]).resolve()
    assert artifacts_root in artifact_path.parents


def test_validate_verb_sanitizes_absolute_path_in_circuito(tmp_path):
    """An absolute-path-shaped `circuito` must also be contained under ARTIFACTS_ROOT."""
    payload = _sample_context_payload()
    envelope = build_context(payload)
    response = _valid_response_for(envelope)
    del response["sintesis_final"]

    malicious_context = dict(envelope["context"])
    malicious_context["circuito"] = "/etc/evil-circuit"
    validate_payload = {"response_text": json.dumps(response, ensure_ascii=False), "context": malicious_context}

    result = _run_cli("validate", validate_payload, tmp_path)

    assert result.returncode == 1
    artifacts_root = (tmp_path / "reports" / "interpretability" / "artifacts").resolve()
    stdout_data = json.loads(result.stdout)
    artifact_path = Path(stdout_data["artifact_path"]).resolve()
    assert artifacts_root in artifact_path.parents


def test_cli_build_context_empty_stdin_is_malformed_not_a_crash(tmp_path):
    result = _run_cli_raw("build-context", "", tmp_path)

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]


def test_cli_build_context_invalid_json_is_malformed_not_a_crash(tmp_path):
    result = _run_cli_raw("build-context", "not json at all", tmp_path)

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]


def test_cli_build_context_missing_circuito_is_malformed_not_a_crash(tmp_path):
    payload = _sample_context_payload()
    del payload["circuito"]

    result = _run_cli("build-context", payload, tmp_path)

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


def test_cli_build_context_malformed_nested_periodo_inicio_is_not_a_crash(tmp_path):
    payload = _sample_context_payload()
    payload["periodo_inicio"] = {"a": 1}

    result = _run_cli("build-context", payload, tmp_path)

    assert result.returncode == 3
    assert "Traceback" not in result.stdout
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]
    assert "Traceback" in result.stderr


def test_cli_validate_non_dict_context_is_not_a_crash(tmp_path):
    payload = {"response_text": "not json", "context": "not-a-dict"}

    result = _run_cli("validate", payload, tmp_path)

    assert result.returncode == 3
    assert "Traceback" not in result.stdout
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]
    assert "Traceback" in result.stderr


def test_write_failure_artifact_is_atomic_and_never_leaves_a_partial_file(tmp_path, monkeypatch):
    """A crash mid-write must never leave a truncated/corrupt failure
    artifact: the write goes to a temp file first, then os.replace() swaps
    it into place; if the replace itself fails, no partial file is left."""
    monkeypatch.chdir(tmp_path)

    def failing_replace(*args, **kwargs):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(_atomic_io.os, "replace", failing_replace)

    with pytest.raises(OSError):
        agent_tools_module._write_failure_artifact("ATOMICCKT", "raw response text", ["some error"])

    artifact_dir = tmp_path / "reports" / "interpretability" / "artifacts" / "ATOMICCKT"
    if artifact_dir.exists():
        assert list(artifact_dir.glob("*")) == [], "no partial/truncated artifact file must be left behind"


def test_write_failure_artifact_directory_matches_canonical_publish_identity(tmp_path, monkeypatch):
    """Regression for the fixed divergence: the failure-artifact directory
    (`_write_failure_artifact`, this module) and the published-report
    filename (`agent_tools.batch._publish_report`) must resolve to the SAME
    canonical identity for the same raw `circuito` — previously the failure
    artifact used sanitize-only while the batch publisher used sanitize +
    normalize, so a mixed-case/punctuation `circuito` diverged between the
    two."""
    monkeypatch.chdir(tmp_path)
    raw_circuito = "don-23-l13"

    artifact_path = agent_tools_module._write_failure_artifact(raw_circuito, "raw response text", ["some error"])

    expected_identity = canonical_circuit_identity(raw_circuito)
    assert artifact_path.parent.name == expected_identity

    published_path = batch_module._publish_report(raw_circuito, {"sintesis_final": "ok"})
    assert published_path.stem == expected_identity
    assert artifact_path.parent.name == published_path.stem, (
        "failure-artifact directory and publish filename must use the same canonical identity"
    )


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
