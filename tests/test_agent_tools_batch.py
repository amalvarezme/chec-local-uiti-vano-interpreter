"""Headless per-circuit batch runner (design's Failure handling section / WU4).

Every test stubs the subprocess boundary (`subprocess.run`) — no real
`claude` process is ever invoked. Each test also chdirs into `tmp_path` so
published reports and failure artifacts never touch the real repo.
"""

from __future__ import annotations

import json
from pathlib import Path

from chec_local_interpreter.agent_tools import batch as batch_module
from chec_local_interpreter.agent_tools.expert_alignment import TOOL_VERSION


def _sample_payload(circuito: str = "DON23L13") -> dict:
    return {
        "circuito": circuito,
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
                "Circuito": circuito,
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


def _valid_response(circuito: str = "DON23L13") -> dict:
    return {
        "contexto": {
            "circuito": circuito,
            "periodo": {"inicio": "2026-01-01", "fin": "2026-01-31"},
            "n_filas_expertas_comparadas": 1,
        },
        "coincidencias": [
            {
                "tema": "UITI_VANO alto",
                "fechas_relacionadas": ["2026-01-10"],
                "fuentes": ["Agente Descriptor", "Agente predictivo", f"{circuito}.pdf"],
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


def _invalid_response(circuito: str = "DON23L13") -> dict:
    response = _valid_response(circuito)
    del response["sintesis_final"]
    return response


class _FakeCompletedProcess:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = ""


def test_run_circuit_success_is_one_isolated_invocation_and_publishes_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    response_text = json.dumps(_valid_response(), ensure_ascii=False)
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return _FakeCompletedProcess(stdout=response_text)

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    entry = batch_module.run_circuit(_sample_payload())

    assert len(calls) == 1, "success on the first attempt must be exactly one isolated invocation"
    assert calls[0][:2] == list(batch_module.DEFAULT_AGENT_COMMAND)

    assert entry["circuito"] == "DON23L13"
    assert entry["status"] == "ok"
    assert entry["tool_version"] == TOOL_VERSION
    assert entry["retries"] == 0
    assert entry["artifact_paths"], "expected the published report path to be recorded"

    published_path = Path(entry["artifact_paths"][0])
    assert published_path.is_file()
    published_data = json.loads(published_path.read_text())
    assert published_data["sintesis_final"]


def test_run_circuit_retries_then_fails_and_never_publishes_invalid_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invalid_text = json.dumps(_invalid_response(), ensure_ascii=False)
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return _FakeCompletedProcess(stdout=invalid_text)

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    entry = batch_module.run_circuit(_sample_payload(), max_retries=2)

    assert len(calls) == 3, "expected the first attempt plus 2 retries (MAX_VALIDATION_RETRIES default)"
    # The repair pattern must feed validator errors back — later prompts differ from the first.
    assert calls[1][-1] != calls[0][-1]
    assert "sintesis_final" in calls[1][-1] or "Errores de validaci" in calls[1][-1]

    assert entry["status"] == "FAILED"
    assert entry["retries"] == 2
    assert entry["artifact_paths"], "expected failure artifact paths to be recorded"
    for artifact_path in entry["artifact_paths"]:
        assert Path(artifact_path).is_file()

    published_dir = tmp_path / "reports" / "interpretability" / "published"
    assert not published_dir.exists(), "invalid output must never be written to the published report path"


def test_run_batch_continues_after_one_circuit_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    responses = {
        "FAILCKT": json.dumps(_invalid_response("FAILCKT"), ensure_ascii=False),
        "OKCKT": json.dumps(_valid_response("OKCKT"), ensure_ascii=False),
    }

    def fake_run(command, **kwargs):
        prompt = command[-1]
        for circuito, text in responses.items():
            if circuito in prompt:
                return _FakeCompletedProcess(stdout=text)
        raise AssertionError("unexpected prompt, no fixture match")

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    manifest = batch_module.run_batch([
        _sample_payload("FAILCKT"),
        _sample_payload("OKCKT"),
    ])

    statuses = {entry["circuito"]: entry["status"] for entry in manifest["circuits"]}
    assert statuses == {"FAILCKT": "FAILED", "OKCKT": "ok"}
    assert manifest["tool_version"] == TOOL_VERSION
    assert len(manifest["circuits"]) == 2, "the batch must not abort after the first circuit fails"


def test_run_circuit_degrades_cleanly_when_claude_is_not_on_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def fake_run(command, **kwargs):
        raise FileNotFoundError("claude not found")

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    entry = batch_module.run_circuit(_sample_payload())

    assert entry["status"] == "FAILED"
    assert "error" in entry
    assert "not found" in entry["error"].lower()
    # No traceback surface — the manifest entry is the only reported error.
    assert entry["retries"] == 0


def test_run_circuit_manifest_entry_has_the_required_shape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    response_text = json.dumps(_valid_response(), ensure_ascii=False)
    monkeypatch.setattr(
        batch_module.subprocess, "run", lambda command, **kwargs: _FakeCompletedProcess(stdout=response_text)
    )

    entry = batch_module.run_circuit(_sample_payload())

    for key in ("circuito", "status", "artifact_paths", "tool_version", "timestamp"):
        assert key in entry
    assert "retries" in entry  # additive, per design's failure-handling section


def test_cli_main_exit_code_reflects_batch_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    circuits_file = tmp_path / "circuits.json"
    circuits_file.write_text(json.dumps([_sample_payload("FAILCKT")], ensure_ascii=False))

    monkeypatch.setattr(
        batch_module.subprocess,
        "run",
        lambda command, **kwargs: _FakeCompletedProcess(stdout=json.dumps(_invalid_response("FAILCKT"), ensure_ascii=False)),
    )

    exit_code = batch_module.main(["--circuits", str(circuits_file)])

    assert exit_code == 1


def test_cli_main_exit_code_zero_when_all_circuits_ok(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    circuits_file = tmp_path / "circuits.json"
    circuits_file.write_text(json.dumps([_sample_payload("OKCKT")], ensure_ascii=False))

    monkeypatch.setattr(
        batch_module.subprocess,
        "run",
        lambda command, **kwargs: _FakeCompletedProcess(stdout=json.dumps(_valid_response("OKCKT"), ensure_ascii=False)),
    )

    exit_code = batch_module.main(["--circuits", str(circuits_file)])

    assert exit_code == 0


def test_cli_accepts_a_manifest_file_containing_a_list_of_payloads(tmp_path, monkeypatch):
    """`--circuits` accepts a single JSON file containing a list of payloads (the "file" half
    of "list-or-file"); multiple --circuits arguments (the "list" half) are exercised implicitly
    by _load_circuit_payloads concatenating them, covered at the unit level below."""
    monkeypatch.chdir(tmp_path)
    circuits_file = tmp_path / "circuits.json"
    circuits_file.write_text(
        json.dumps([_sample_payload("OKCKT"), _sample_payload("OKCKT2")], ensure_ascii=False)
    )

    # Route the canned response by circuit id embedded in the built prompt.
    def fake_run(command, **kwargs):
        prompt = command[-1]
        circuito = "OKCKT2" if "OKCKT2" in prompt else "OKCKT"
        return _FakeCompletedProcess(stdout=json.dumps(_valid_response(circuito), ensure_ascii=False))

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    exit_code = batch_module.main(["--circuits", str(circuits_file)])

    assert exit_code == 0


def test_load_circuit_payloads_concatenates_multiple_file_arguments(tmp_path):
    file_a = tmp_path / "a.json"
    file_b = tmp_path / "b.json"
    file_a.write_text(json.dumps(_sample_payload("CKTA"), ensure_ascii=False))
    file_b.write_text(json.dumps([_sample_payload("CKTB"), _sample_payload("CKTC")], ensure_ascii=False))

    payloads = batch_module._load_circuit_payloads([str(file_a), str(file_b)])

    assert [p["circuito"] for p in payloads] == ["CKTA", "CKTB", "CKTC"]
