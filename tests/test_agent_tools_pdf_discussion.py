"""Batch-contract tests for the pdf-discussion-extraction L2 CLI (design D5).

Design D5 revises `agent_tools/pdf_discussion.py` from a per-fragment
primitive to a per-PDF BATCH contract: `build-context` takes a whole-PDF
payload with multiple `secciones` and renders ONE prompt; `validate` takes a
`{filas, descartes}` agent response and validates each `filas[]` entry
independently via the existing, UNCHANGED `validate_pdf_discussion_row`
(imported, never redefined), force-setting `Circuito` on every accepted row.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from chec_local_interpreter.agent_tools.pdf_discussion import (
    TOOL_VERSION,
    build_context,
    validate,
)
from chec_local_interpreter.circuit_identity import canonical_circuit_identity
from chec_local_interpreter.pdf_discussion_pipeline import (
    assemble_discussion_xlsx_from_run,
    prepare_pdf_discussion_batch,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_TOOLS_MODULE = PROJECT_ROOT / "src" / "chec_local_interpreter" / "agent_tools" / "pdf_discussion.py"


def _sample_batch_payload() -> dict:
    return {
        "fecha_inicio_usuario": "2026-01-01",
        "fecha_fin_usuario": "2026-01-31",
        "nombre_pdf": "DON23L13.pdf",
        "circuito_pdf": "DON23L13",
        "periodo_general_informe": "enero 2026",
        "secciones": [
            {
                "indice": 1,
                "pagina_inicio": 3,
                "pagina_fin": 3,
                "markdown": "El dia 2026-01-10 se presento una falla asociada a vegetacion en el tramo cabecera.",
            },
            {
                "indice": 2,
                "pagina_inicio": 4,
                "pagina_fin": 4,
                "markdown": "El dia 2026-01-15 hubo mantenimiento preventivo en el ramal.",
            },
        ],
    }


def _row(circuito: str = "OTHER_CIRCUIT", fecha_inicio: str = "2026-01-10", fecha_fin: str = "2026-01-10") -> dict:
    # Deliberately claims a different Circuito than circuito_pdf by default,
    # to exercise the "never trust the LLM's own Circuito" forcing invariant.
    return {
        "include": True,
        "Circuito": circuito,
        "Fecha inicio": fecha_inicio,
        "Fecha fin": fecha_fin,
        "Análisis": "Falla asociada a vegetacion en el tramo cabecera.",
        "Evidencia": "El dia 2026-01-10 se presento una falla asociada a vegetacion.",
    }


def _run_cli(verb: str, payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    return _run_cli_raw(verb, json.dumps(payload, ensure_ascii=False), cwd)


def _run_cli_raw(verb: str, raw_stdin: str, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "chec_local_interpreter.agent_tools.pdf_discussion", verb],
        input=raw_stdin,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        timeout=30,
    )


# --- build-context: one prompt per whole-PDF payload ------------------------


def test_build_context_envelope_shape():
    payload = _sample_batch_payload()
    envelope = build_context(payload)

    assert set(envelope.keys()) == {"meta", "context", "prompt"}
    assert set(envelope["meta"].keys()) == {"nombre_pdf", "circuito_pdf", "num_secciones", "tool_version"}
    assert envelope["meta"]["nombre_pdf"] == "DON23L13.pdf"
    assert envelope["meta"]["circuito_pdf"] == "DON23L13"
    assert envelope["meta"]["num_secciones"] == 2
    assert envelope["meta"]["tool_version"] == TOOL_VERSION
    assert envelope["context"] == payload


def test_build_context_produces_exactly_one_prompt_covering_all_sections():
    payload = _sample_batch_payload()
    envelope = build_context(payload)
    prompt = envelope["prompt"]

    assert payload["secciones"][0]["markdown"] in prompt
    assert payload["secciones"][1]["markdown"] in prompt
    assert "{secciones}" not in prompt
    assert "{circuito_pdf}" not in prompt
    assert "{nombre_pdf}" not in prompt


def test_build_context_cli_matches_in_process_call(tmp_path):
    payload = _sample_batch_payload()
    result = _run_cli("build-context", payload, tmp_path)
    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["meta"]["circuito_pdf"] == "DON23L13"
    assert envelope == build_context(payload)


def test_cli_build_context_missing_secciones_key_is_malformed_not_a_crash(tmp_path):
    payload = _sample_batch_payload()
    del payload["secciones"]

    result = _run_cli("build-context", payload, tmp_path)

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
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


# --- validate: mixed-validity batch, anti-spoofing, descartes vs rejected ---


def test_validate_mixed_batch_accepts_valid_row_and_rejects_only_bad_date_row():
    good_row = _row()
    bad_row = _row(fecha_inicio="not-a-date", fecha_fin="not-a-date")
    response = {"filas": [good_row, bad_row], "descartes": []}
    payload = {
        "response_text": json.dumps(response, ensure_ascii=False),
        "circuito_pdf": "DON23L13",
        "fecha_inicio_usuario": "2026-01-01",
        "fecha_fin_usuario": "2026-01-31",
    }

    result, exit_code = validate(payload)

    assert exit_code == 0, result
    assert result["ok"] is True
    assert len(result["rows"]) == 1
    assert len(result["rejected"]) == 1
    assert result["rows"][0]["Fecha inicio"] == "2026-01-10"
    assert result["rejected"][0]["errors"]


def test_validate_forces_circuito_to_circuito_pdf_on_every_accepted_row():
    response = {"filas": [_row(circuito="SOME_OTHER_CIRCUIT")], "descartes": []}
    payload = {
        "response_text": json.dumps(response, ensure_ascii=False),
        "circuito_pdf": "DON23L13",
        "fecha_inicio_usuario": "2026-01-01",
        "fecha_fin_usuario": "2026-01-31",
    }

    result, exit_code = validate(payload)

    assert exit_code == 0, result
    assert result["ok"] is True
    assert result["rows"][0]["Circuito"] == "DON23L13"


def test_validate_circuito_pdf_none_rejects_every_row_in_the_batch():
    response = {"filas": [_row(), _row()], "descartes": []}
    payload = {
        "response_text": json.dumps(response, ensure_ascii=False),
        "circuito_pdf": None,
        "fecha_inicio_usuario": "2026-01-01",
        "fecha_fin_usuario": "2026-01-31",
    }

    result, exit_code = validate(payload)

    assert exit_code == 0, result  # the batch response itself parsed fine
    assert result["ok"] is True
    assert result["rows"] == []
    assert len(result["rejected"]) == 2


def test_validate_descartes_are_persisted_but_never_counted_as_rejected(tmp_path):
    response = {
        "filas": [],
        "descartes": [{"seccion_indice": 2, "reason": "sin evidencia suficiente"}],
    }
    payload = {
        "response_text": json.dumps(response, ensure_ascii=False),
        "circuito_pdf": "DON23L13",
        "fecha_inicio_usuario": "2026-01-01",
        "fecha_fin_usuario": "2026-01-31",
    }

    result = _run_cli("validate", payload, tmp_path)
    assert result.returncode == 0, result.stderr
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is True
    assert stdout_data["rows"] == []
    assert stdout_data["rejected"] == []
    assert stdout_data["artifact_path"]

    saved = json.loads(Path(stdout_data["artifact_path"]).read_text())
    assert saved["descartes"] == [{"seccion_indice": 2, "reason": "sin evidencia suficiente"}]
    assert saved["rejected"] == []


def test_validate_malformed_json_response_exits_one():
    payload = {
        "response_text": "not valid json {{",
        "circuito_pdf": "DON23L13",
        "fecha_inicio_usuario": "2026-01-01",
        "fecha_fin_usuario": "2026-01-31",
    }
    result, exit_code = validate(payload)
    assert exit_code == 1
    assert result["ok"] is False
    assert result["errors"]


def test_validate_non_object_json_response_exits_one():
    payload = {
        "response_text": "[1, 2, 3]",
        "circuito_pdf": "DON23L13",
        "fecha_inicio_usuario": "2026-01-01",
        "fecha_fin_usuario": "2026-01-31",
    }
    result, exit_code = validate(payload)
    assert exit_code == 1
    assert result["ok"] is False
    assert result["errors"]


def test_cli_validate_missing_response_text_is_malformed_not_a_crash(tmp_path):
    result = _run_cli(
        "validate",
        {"circuito_pdf": "DON23L13", "fecha_inicio_usuario": "2026-01-01", "fecha_fin_usuario": "2026-01-31"},
        tmp_path,
    )

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]


def test_cli_validate_empty_stdin_is_malformed_not_a_crash(tmp_path):
    result = _run_cli_raw("validate", "", tmp_path)

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]


def test_validate_writes_rejected_rows_artifact_under_artifacts_root(tmp_path):
    bad_row = _row(fecha_inicio="not-a-date", fecha_fin="not-a-date")
    response = {"filas": [bad_row], "descartes": []}
    payload = {
        "response_text": json.dumps(response, ensure_ascii=False),
        "circuito_pdf": "DON23L13",
        "fecha_inicio_usuario": "2026-01-01",
        "fecha_fin_usuario": "2026-01-31",
    }
    result = _run_cli("validate", payload, tmp_path)

    assert result.returncode == 0, result.stderr  # batch as a whole is not rejected wholesale
    stdout_data = json.loads(result.stdout)
    assert stdout_data["ok"] is True
    assert stdout_data["rejected"]
    assert stdout_data["artifact_path"]

    safe_name = canonical_circuit_identity("DON23L13")
    artifact_dir = tmp_path / "reports" / "interpretability" / "artifacts" / "pdf-discussion-extraction" / safe_name
    assert artifact_dir.is_dir()
    artifact_files = list(artifact_dir.glob("*.json"))
    assert artifact_files
    saved = json.loads(artifact_files[0].read_text())
    assert saved["rejected"]


# --- Integration: batch payload -> canned response -> validate -> xlsx -----


class _FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self):
        return self._text

    def extract_tables(self):
        return []


class _FakePDF:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages

    def __enter__(self) -> "_FakePDF":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def test_batch_pipeline_integration_prepare_validate_assemble(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """2-page synthetic PDF -> prepare_pdf_discussion_batch -> canned agent
    response -> validate -> assemble_discussion_xlsx_from_run (design D5's
    full batch runbook, task 3.6)."""
    import chec_local_interpreter.pdf_discussion_pipeline as pipeline_module

    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    (pdf_dir / "DON23L13.pdf").write_bytes(b"%PDF-1.4 fake\n")

    pages = [
        _FakePage(
            "El dia 2026-01-10 se presento una falla asociada a vegetacion en el "
            "tramo cabecera del circuito DON23L13."
        ),
        _FakePage(
            "El dia 2026-01-15 hubo mantenimiento preventivo en el ramal del "
            "circuito DON23L13."
        ),
    ]
    monkeypatch.setattr(pipeline_module.pdfplumber, "open", lambda _path: _FakePDF(pages))

    run_dir = tmp_path / "run"
    written = prepare_pdf_discussion_batch(pdf_dir, "2026-01-01", "2026-01-31", run_dir)
    assert len(written) == 1
    payload = json.loads(written[0].read_text())
    assert payload["secciones"], "expected at least one candidate section"

    envelope = build_context(payload)
    assert envelope["meta"]["circuito_pdf"] == "DON23L13"

    canned_rows = [
        {
            "include": True,
            "Circuito": "DON23L13",
            "Fecha inicio": "2026-01-10",
            "Fecha fin": "2026-01-10",
            "Análisis": "Falla asociada a vegetacion.",
            "Evidencia": "El dia 2026-01-10 se presento una falla asociada a vegetacion.",
        }
    ]
    response_text = json.dumps({"filas": canned_rows, "descartes": []}, ensure_ascii=False)
    validate_payload = {
        "response_text": response_text,
        "circuito_pdf": payload["circuito_pdf"],
        "fecha_inicio_usuario": payload["fecha_inicio_usuario"],
        "fecha_fin_usuario": payload["fecha_fin_usuario"],
    }
    result, exit_code = validate(validate_payload)
    assert exit_code == 0, result
    assert result["rows"]

    rows_path = run_dir / "DON23L13.rows.json"
    rows_path.write_text(json.dumps(result["rows"], ensure_ascii=False), encoding="utf-8")

    output_xlsx = tmp_path / "tabla_pdfs_intervalo_test.xlsx"
    df = assemble_discussion_xlsx_from_run(run_dir, output_xlsx)

    assert output_xlsx.exists()
    assert list(df.columns) == pipeline_module.COLUMNAS_FINALES
    assert len(df) == 1
    assert df.iloc[0]["Circuito"] == "DON23L13"


# --- Static guards -----------------------------------------------------------


def test_validate_verb_reuses_validate_pdf_discussion_row_unmodified():
    """No duplicate/forked validator -- the pdf-discussion CLI must import
    `validate_pdf_discussion_row` from `llm_validation`, not define its own
    copy, and must apply it per row."""
    source = AGENT_TOOLS_MODULE.read_text()
    tree = ast.parse(source)
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "chec_local_interpreter.llm_validation":
            imported_names.update(alias.name for alias in node.names)
    assert "validate_pdf_discussion_row" in imported_names
    assert "def validate_pdf_discussion_row(" not in source


def test_pdf_discussion_agent_tools_never_references_frozen_model_boundary():
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
