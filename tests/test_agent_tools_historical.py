from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from chec_local_interpreter.agent_tools.historical import (
    TOOL_VERSION,
    build_context,
    validate,
)
from chec_local_interpreter.circuit_identity import canonical_circuit_identity
from chec_local_interpreter.llm_contracts import PROMPT_VERSION
from chec_local_interpreter.llm_validation import (
    allowed_critical_point_ids,
    allowed_dates,
    unavailable_columns,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_TOOLS_MODULE = PROJECT_ROOT / "src" / "chec_local_interpreter" / "agent_tools" / "historical.py"


def _sample_context(unavailable: list[str] | None = None) -> dict:
    return {
        "analysis_name": "local_uiti_vano_interpretability",
        "metadata": {
            "v": "test",
            "schema": "test",
            "ts": "2026-01-01T00:00",
            "circuitos": ["DON23L13"],
            "start": "2026-01-01",
            "end": "2026-01-03",
            "unavailable_cols": unavailable or [],
        },
        "selected_context": {"circuitos": ["DON23L13"], "indicator": "UITI_VANO"},
        "summary": {"events": 2, "nonzero_days": 2, "total_uv": 15.0},
        "daily": [
            {"d": "2026-01-01", "uv": 5.0, "n": 1, "dur": 1.0},
            {"d": "2026-01-02", "uv": 10.0, "n": 1, "dur": 2.0},
        ],
        "critical_points": [
            {
                "critical_point_id": "cp-2026-01-02",
                "fecha_dia": "2026-01-02",
                "rank": 1,
                "score": 2.0,
                "types": ["top_contribution_day"],
                "selection_reason": "El dia aporta una fraccion alta del UITI_VANO total.",
                "metrics": {"UITI_VANO": 10.0},
                "daily_aggregates": {"events": 1},
            }
        ],
        "critical_periods": [],
        "domain": {
            "variable_groups": {
                "Entorno/Riesgo": {"variables": ["NR_T", "DDT"]},
                "Evento/Impacto": {"variables": ["UITI_VANO", "CNT_TRF"]},
            },
            "relationship_rules": [],
        },
        "graph_knowledge": "Grafo no disponible en pruebas.",
    }


def _valid_output(context: dict) -> dict:
    point = context["critical_points"][0]
    return {
        "source": "llm",
        "prompt_version": PROMPT_VERSION,
        "headline": "Concentracion de UITI_VANO",
        "section_title": "Hallazgos del periodo",
        "executive_summary": ["La evidencia tabular muestra un punto dominante."],
        "key_findings": [
            {
                "title": "Punto dominante",
                "text": "El punto concentra el comportamiento del periodo.",
                "evidence": [
                    {
                        "date": point["fecha_dia"],
                        "critical_point_id": point["critical_point_id"],
                        "variable": "UITI_VANO",
                        "summary": point["selection_reason"],
                    }
                ],
                "referenced_events": [],
                "variable_groups_used": ["Evento/Impacto"],
                "confidence": "media",
            }
        ],
        "circuit_characterization": {
            "text": "Characterization text.",
            "p97_vanos_uiti_vano": ["V1"],
            "p97_vanos_eventos": ["V2"],
            "top_3_modes_related": ["Mode1"],
            "probable_justifications_rules": ["Rule1"],
        },
        "period_synthesis": "El comportamiento del periodo se concentra en el punto critico.",
        "data_gaps": [],
        "limitations": ["Solo se usa la informacion estructurada disponible."],
        "recommended_actions": ["Revisar los eventos fuente del punto critico."],
    }


def _valid_output_with_provenance(context: dict) -> dict:
    output = _valid_output(context)
    output["key_findings"][0]["provenance"] = {
        "data_ref": ["2026-01-02", "cp-2026-01-02", "UITI_VANO"],
        "agent": "historical",
        "rule": "03_uiti_vano_behavior_explainer",
    }
    return output


def _run_cli(verb: str, payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    return _run_cli_raw(verb, json.dumps(payload, ensure_ascii=False), cwd)


def _run_cli_raw(verb: str, raw_stdin: str, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "chec_local_interpreter.agent_tools.historical", verb],
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

    assert set(envelope["allowed"].keys()) == {"dates", "critical_point_ids", "unavailable_columns"}
    assert sorted(envelope["allowed"]["dates"]) == sorted(allowed_dates(context))
    assert sorted(envelope["allowed"]["critical_point_ids"]) == sorted(allowed_critical_point_ids(context))
    assert sorted(envelope["allowed"]["unavailable_columns"]) == sorted(unavailable_columns(context))


def test_build_context_multi_circuit_join_matches_batch_convention():
    context = _sample_context()
    context["metadata"]["circuitos"] = ["DON23L13", "DON23L14"]
    envelope = build_context(context)
    assert envelope["meta"]["circuito"] == "DON23L13_DON23L14"


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
    assert exit_code == 0
    assert result["ok"] is True


def test_validate_verb_accepts_valid_response_with_resolving_provenance():
    context = _sample_context()
    envelope = build_context(context)
    response = _valid_output_with_provenance(envelope["context"])

    result, exit_code = validate({"response_text": json.dumps(response, ensure_ascii=False), "context": envelope["context"]})
    assert exit_code == 0, result
    assert result["ok"] is True


def test_validate_cli_rejects_response_missing_required_key_and_writes_artifact_under_historical_namespace(tmp_path):
    context = _sample_context()
    envelope = build_context(context)
    response = _valid_output(envelope["context"])
    del response["period_synthesis"]

    validate_payload = {"response_text": json.dumps(response, ensure_ascii=False), "context": envelope["context"]}
    result = _run_cli("validate", validate_payload, tmp_path)

    assert result.returncode == 1
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]

    artifact_dir = tmp_path / "reports" / "interpretability" / "artifacts" / "historical" / "DON23L13"
    assert artifact_dir.is_dir()
    artifact_files = list(artifact_dir.glob("*.json"))
    assert artifact_files, "expected a failure artifact under the historical-namespaced artifacts root"
    saved = json.loads(artifact_files[0].read_text())
    assert saved["errors"]
    assert "response_text" in saved


def test_validate_cli_rejects_response_with_unresolvable_provenance_and_does_not_publish(tmp_path):
    """Schema passes, but provenance data_ref is outside the allowed context — the
    two-stage gate must still fail closed (exit 1), never exit 0."""
    context = _sample_context()
    envelope = build_context(context)
    response = _valid_output_with_provenance(envelope["context"])
    response["key_findings"][0]["provenance"]["data_ref"] = ["9999-12-31"]

    validate_payload = {"response_text": json.dumps(response, ensure_ascii=False), "context": envelope["context"]}
    result = _run_cli("validate", validate_payload, tmp_path)

    assert result.returncode == 1
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert any("9999-12-31" in error for error in stdout_data["errors"])

    artifact_dir = tmp_path / "reports" / "interpretability" / "artifacts" / "historical" / "DON23L13"
    assert artifact_dir.is_dir()
    assert list(artifact_dir.glob("*.json"))


def test_validate_verb_schema_failure_short_circuits_provenance_check():
    """When the schema/guardrail validator fails, the provenance validator must
    not even run — errors reported are schema-only, per the two-stage gate."""
    context = _sample_context()
    envelope = build_context(context)
    response = _valid_output_with_provenance(envelope["context"])
    del response["period_synthesis"]
    # Also make the provenance invalid — if it were (incorrectly) evaluated,
    # this would add a second, distinct error message.
    response["key_findings"][0]["provenance"]["data_ref"] = ["9999-12-31"]

    result, exit_code = validate({"response_text": json.dumps(response, ensure_ascii=False), "context": envelope["context"]})
    assert exit_code == 1
    assert not any("9999-12-31" in error for error in result["errors"]), (
        "provenance must not be evaluated when the schema/guardrail stage already failed"
    )


def test_validate_cli_valid_response_exits_zero_and_prints_ok_true(tmp_path):
    context = _sample_context()
    envelope = build_context(context)
    response = _valid_output(envelope["context"])

    validate_payload = {"response_text": json.dumps(response, ensure_ascii=False), "context": envelope["context"]}
    result = _run_cli("validate", validate_payload, tmp_path)

    assert result.returncode == 0, result.stderr
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is True
    assert '"ok": true' in result.stdout


def test_cli_build_context_empty_stdin_is_malformed_not_a_crash(tmp_path):
    result = _run_cli_raw("build-context", "", tmp_path)

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]


def test_cli_build_context_missing_metadata_is_malformed_not_a_crash(tmp_path):
    context = _sample_context()
    del context["metadata"]

    result = _run_cli("build-context", context, tmp_path)

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


def test_cli_validate_non_dict_context_is_not_a_crash(tmp_path):
    payload = {"response_text": "not json", "context": "not-a-dict"}

    result = _run_cli("validate", payload, tmp_path)

    assert result.returncode == 3
    assert "Traceback" not in result.stdout
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]
    assert "Traceback" in result.stderr


def test_validate_verb_reuses_validate_llm_response_unmodified():
    """No duplicate/forked schema validator — the historical CLI must import
    `validate_llm_response` from `llm_validation`, not define its own copy."""
    source = AGENT_TOOLS_MODULE.read_text()
    tree = ast.parse(source)
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "chec_local_interpreter.llm_validation":
            imported_names.update(alias.name for alias in node.names)
    assert "validate_llm_response" in imported_names
    assert "def validate_llm_response(" not in source


def test_historical_agent_tools_never_references_frozen_model_boundary():
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
