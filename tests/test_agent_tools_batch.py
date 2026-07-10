"""Headless per-circuit batch runner (design's Failure handling section / WU4).

Every test stubs the subprocess boundary (`subprocess.run`) — no real
`claude` process is ever invoked. Each test also chdirs into `tmp_path` so
published reports and failure artifacts never touch the real repo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from chec_local_interpreter.agent_tools import _atomic_io, batch as batch_module
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
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


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


def test_run_circuit_reports_agent_error_on_nonzero_returncode(tmp_path, monkeypatch):
    """A hard subprocess failure (auth error, crash, non-zero exit) must be
    reported distinctly from a normal validation failure, with the real
    infrastructure error (stderr) surfaced instead of a generic
    "validation failed" message."""
    monkeypatch.chdir(tmp_path)

    def fake_run(command, **kwargs):
        return _FakeCompletedProcess(stdout="", returncode=1, stderr="authentication error: invalid API key")

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    entry = batch_module.run_circuit(_sample_payload())

    assert entry["status"] == "AGENT_ERROR"
    assert "authentication error" in entry["error"]


def test_run_batch_marks_duplicate_circuito_and_keeps_first_run_only(tmp_path, monkeypatch):
    """Running the same circuito twice in one batch must not silently
    overwrite the first run's published report — the second+ occurrence is
    marked SKIPPED_DUPLICATE instead of being re-run."""
    monkeypatch.chdir(tmp_path)
    calls: list[str] = []

    def fake_run(command, **kwargs):
        calls.append(command[-1])
        return _FakeCompletedProcess(stdout=json.dumps(_valid_response("DUPCKT"), ensure_ascii=False))

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    manifest = batch_module.run_batch([_sample_payload("DUPCKT"), _sample_payload("DUPCKT")])

    statuses = [entry["status"] for entry in manifest["circuits"]]
    assert statuses == ["ok", "SKIPPED_DUPLICATE"]
    assert len(calls) == 1, "the duplicate must never trigger a second agent invocation"

    published_path = tmp_path / "reports" / "interpretability" / "published" / "DUPCKT.json"
    assert published_path.is_file()
    assert json.loads(published_path.read_text())["sintesis_final"]


def test_run_batch_dedup_catches_raw_values_that_sanitize_to_the_same_filename(tmp_path, monkeypatch):
    """Two distinct raw `circuito` values that both sanitize to the same
    on-disk publish filename (a path-separator-suffix collision, e.g.
    "AAA/BBB" and "CCC/BBB" both become "BBB.json") must be caught by the
    dedup check — raw-string equality alone would miss this and the second
    run would silently overwrite the first's published report."""
    monkeypatch.chdir(tmp_path)
    calls: list[str] = []

    def fake_run(command, **kwargs):
        calls.append(command[-1])
        return _FakeCompletedProcess(stdout=json.dumps(_valid_response("AAA/BBB"), ensure_ascii=False))

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    manifest = batch_module.run_batch([_sample_payload("AAA/BBB"), _sample_payload("CCC/BBB")])

    statuses = [entry["status"] for entry in manifest["circuits"]]
    assert statuses == ["ok", "SKIPPED_DUPLICATE"]
    assert len(calls) == 1, "the sanitize-collision duplicate must never trigger a second agent invocation"

    published_dir = tmp_path / "reports" / "interpretability" / "published"
    assert [p.name for p in published_dir.glob("*.json")] == ["BBB.json"]


def test_run_batch_dedup_catches_case_different_circuito_values(tmp_path, monkeypatch):
    """`DON23L13` and `don23l13` are the same circuit per the codebase's own
    `normalizar_circuito` case/punctuation-insensitive identity — the second
    occurrence must be flagged as a duplicate, not run twice."""
    monkeypatch.chdir(tmp_path)
    calls: list[str] = []

    def fake_run(command, **kwargs):
        calls.append(command[-1])
        return _FakeCompletedProcess(stdout=json.dumps(_valid_response("DON23L13"), ensure_ascii=False))

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    manifest = batch_module.run_batch([_sample_payload("DON23L13"), _sample_payload("don23l13")])

    statuses = [entry["status"] for entry in manifest["circuits"]]
    assert statuses == ["ok", "SKIPPED_DUPLICATE"]
    assert len(calls) == 1, "case-different duplicates must never trigger a second agent invocation"


def test_run_batch_does_not_false_positive_dedup_on_truly_distinct_circuits(tmp_path, monkeypatch):
    """Confirm the smarter dedup key does not over-match: two circuits whose
    normalized/sanitized identities are genuinely different must both run."""
    monkeypatch.chdir(tmp_path)
    calls: list[str] = []

    def fake_run(command, **kwargs):
        prompt = command[-1]
        calls.append(prompt)
        circuito = "AAA/CCC" if "AAA/CCC" in prompt else "AAA/DDD"
        return _FakeCompletedProcess(stdout=json.dumps(_valid_response(circuito), ensure_ascii=False))

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    manifest = batch_module.run_batch([_sample_payload("AAA/CCC"), _sample_payload("AAA/DDD")])

    statuses = [entry["status"] for entry in manifest["circuits"]]
    assert statuses == ["ok", "ok"], "genuinely distinct circuits must never be falsely deduped"
    assert len(calls) == 2


def test_run_batch_dedup_and_publish_share_the_same_canonical_filename_identity(tmp_path, monkeypatch):
    """`DON23L13` and `don23l13` are the same circuit for dedup purposes
    (`_dedupe_key` uses `normalizar_circuito`); `_publish_report` must derive
    the on-disk filename with the SAME identity function, so the manifest's
    SKIPPED_DUPLICATE claim ("to avoid overwriting the first run's published
    report") stays factually true — a case-only difference in the raw value
    must not silently produce two different-case filenames that would never
    actually collide on a case-sensitive filesystem."""
    monkeypatch.chdir(tmp_path)

    def fake_run(command, **kwargs):
        return _FakeCompletedProcess(stdout=json.dumps(_valid_response("don23l13"), ensure_ascii=False))

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    manifest = batch_module.run_batch([_sample_payload("don23l13"), _sample_payload("DON23L13")])

    statuses = [entry["status"] for entry in manifest["circuits"]]
    assert statuses == ["ok", "SKIPPED_DUPLICATE"]

    published_dir = tmp_path / "reports" / "interpretability" / "published"
    published_files = list(published_dir.glob("*.json"))
    assert len(published_files) == 1

    expected_canonical = batch_module._dedupe_key("DON23L13")
    assert published_files[0].stem == expected_canonical, (
        "the published filename must be governed by the same canonical identity "
        "function as the dedup key, not a narrower sanitize-only transform"
    )


def test_run_circuit_canonicalizes_falsy_circuito_consistently_across_context_and_manifest(tmp_path, monkeypatch):
    """A falsy-but-non-empty `circuito` (None here) must resolve to the SAME
    canonical string everywhere: `context["circuito"]` (seen by `validate`),
    the manifest entry's `circuito`, and the failure artifact's on-disk
    directory name — never two independently-derived values that can
    disagree (e.g. context landing on the literal string "None" while the
    manifest/artifact path says "unknown")."""
    monkeypatch.chdir(tmp_path)
    captured_contexts: list[Any] = []
    real_validate = batch_module.validate

    def spy_validate(payload):
        captured_contexts.append(payload.get("context", {}).get("circuito"))
        return real_validate(payload)

    monkeypatch.setattr(batch_module, "validate", spy_validate)
    monkeypatch.setattr(
        batch_module.subprocess,
        "run",
        lambda command, **kwargs: _FakeCompletedProcess(stdout=json.dumps(_invalid_response(), ensure_ascii=False)),
    )

    payload = _sample_payload()
    payload["circuito"] = None

    entry = batch_module.run_circuit(payload, max_retries=0)

    assert entry["status"] == "FAILED"
    assert entry["circuito"] == "unknown"
    assert captured_contexts == ["unknown"], "context['circuito'] must match the manifest's canonical circuito"

    # The manifest keeps the raw/fallback circuito string ("unknown") for
    # human-readable reporting; the on-disk failure-artifact directory uses
    # the shared `canonical_circuit_identity` (sanitize + normalize, same as
    # the publish path) — for this literal that means an upper-cased
    # "UNKNOWN" directory, not a literal string match against the manifest
    # field. What must never diverge is the SAME canonical identity being
    # used for both the artifact directory and the publish filename.
    artifact_path = Path(entry["artifact_paths"][0])
    expected_identity = batch_module.canonical_circuit_identity(entry["circuito"])
    assert artifact_path.parent.name == expected_identity, (
        "the failure artifact's on-disk directory must match the canonical identity of the manifest's circuito"
    )


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


def test_run_circuit_applies_default_timeout_when_omitted(tmp_path, monkeypatch):
    """`timeout` must be wired through with a sane, non-None default so a hung
    `claude -p` cannot block the batch indefinitely (subprocess.TimeoutExpired
    handling would otherwise be dead code)."""
    monkeypatch.chdir(tmp_path)
    response_text = json.dumps(_valid_response(), ensure_ascii=False)
    captured_kwargs: dict = {}

    def fake_run(command, **kwargs):
        captured_kwargs.update(kwargs)
        return _FakeCompletedProcess(stdout=response_text)

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    batch_module.run_circuit(_sample_payload())

    assert captured_kwargs.get("timeout") == batch_module.DEFAULT_AGENT_TIMEOUT_SECONDS
    assert captured_kwargs["timeout"] is not None


def test_run_circuit_passes_through_a_custom_timeout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    response_text = json.dumps(_valid_response(), ensure_ascii=False)
    captured_kwargs: dict = {}

    def fake_run(command, **kwargs):
        captured_kwargs.update(kwargs)
        return _FakeCompletedProcess(stdout=response_text)

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    batch_module.run_circuit(_sample_payload(), timeout=7.5)

    assert captured_kwargs.get("timeout") == 7.5


def test_run_batch_passes_timeout_through_to_run_circuit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    response_text = json.dumps(_valid_response(), ensure_ascii=False)
    captured_kwargs: dict = {}

    def fake_run(command, **kwargs):
        captured_kwargs.update(kwargs)
        return _FakeCompletedProcess(stdout=response_text)

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    batch_module.run_batch([_sample_payload()], timeout=3.0)

    assert captured_kwargs.get("timeout") == 3.0


def test_cli_main_default_timeout_is_applied_when_flag_omitted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    circuits_file = tmp_path / "circuits.json"
    circuits_file.write_text(json.dumps([_sample_payload("OKCKT")], ensure_ascii=False))
    captured_kwargs: dict = {}

    def fake_run(command, **kwargs):
        captured_kwargs.update(kwargs)
        return _FakeCompletedProcess(stdout=json.dumps(_valid_response("OKCKT"), ensure_ascii=False))

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    batch_module.main(["--circuits", str(circuits_file)])

    assert captured_kwargs.get("timeout") == batch_module.DEFAULT_AGENT_TIMEOUT_SECONDS


def test_cli_main_custom_timeout_flag_is_passed_through(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    circuits_file = tmp_path / "circuits.json"
    circuits_file.write_text(json.dumps([_sample_payload("OKCKT")], ensure_ascii=False))
    captured_kwargs: dict = {}

    def fake_run(command, **kwargs):
        captured_kwargs.update(kwargs)
        return _FakeCompletedProcess(stdout=json.dumps(_valid_response("OKCKT"), ensure_ascii=False))

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    batch_module.main(["--circuits", str(circuits_file), "--timeout", "45"])

    assert captured_kwargs.get("timeout") == 45.0


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


def test_run_circuit_null_byte_circuito_does_not_crash_and_is_failed(tmp_path, monkeypatch):
    """A `circuito` value with an embedded null byte must never propagate an
    uncaught ValueError out of run_circuit (e.g. from Path.resolve()/mkdir()/
    write_text() inside `_write_failure_artifact`, exercised here via an
    invalid response) — it must be captured as a FAILED manifest entry
    instead, never a crash."""
    monkeypatch.chdir(tmp_path)
    invalid_text = json.dumps(_invalid_response("BAD\x00CKT"), ensure_ascii=False)
    monkeypatch.setattr(
        batch_module.subprocess, "run", lambda command, **kwargs: _FakeCompletedProcess(stdout=invalid_text)
    )

    entry = batch_module.run_circuit(_sample_payload("BAD\x00CKT"), max_retries=0)

    assert entry["status"] == "FAILED"
    assert "error" in entry


def test_run_circuit_malformed_periodo_inicio_does_not_crash_and_is_failed(tmp_path, monkeypatch):
    """A malformed `periodo_inicio` (e.g. a dict instead of a scalar) makes
    pandas.to_datetime(..., errors="coerce") raise inside build_context — this
    must be captured as a FAILED manifest entry, not an uncaught exception."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        batch_module.subprocess,
        "run",
        lambda command, **kwargs: _FakeCompletedProcess(stdout=json.dumps(_valid_response(), ensure_ascii=False)),
    )

    payload = _sample_payload("BADPERIOD")
    payload["periodo_inicio"] = {"a": 1}

    entry = batch_module.run_circuit(payload)

    assert entry["status"] == "FAILED"
    assert "error" in entry


def test_run_circuit_unexpected_error_logs_full_traceback_to_stderr(tmp_path, monkeypatch, capsys):
    """A genuine programming bug (e.g. a bare KeyError raised from inside
    build_context) must still land as a clean FAILED manifest entry — but,
    unlike a routine per-circuit failure, its full traceback must be logged
    to stderr as a diagnostic side-channel; the manifest entry itself is
    unaffected (still just `error`, no traceback in the manifest)."""
    monkeypatch.chdir(tmp_path)

    def raise_key_error(payload):
        raise KeyError("simulated programming bug")

    monkeypatch.setattr(batch_module, "build_context", raise_key_error)

    entry = batch_module.run_circuit(_sample_payload("BUGCKT"))

    assert entry["status"] == "FAILED"
    assert "error" in entry
    assert "Traceback" not in entry["error"], "the manifest entry must stay a clean, short error message"

    captured = capsys.readouterr()
    assert "Traceback" in captured.err
    assert "KeyError" in captured.err
    assert "simulated programming bug" in captured.err


def test_run_batch_continues_when_one_circuit_has_a_malformed_field(tmp_path, monkeypatch):
    """A batch with one bad circuit (malformed periodo_inicio) and one good
    circuit must still complete with both entries in the manifest."""
    monkeypatch.chdir(tmp_path)

    def fake_run(command, **kwargs):
        prompt = command[-1]
        if "OKCKT" in prompt:
            return _FakeCompletedProcess(stdout=json.dumps(_valid_response("OKCKT"), ensure_ascii=False))
        return _FakeCompletedProcess(stdout=json.dumps(_valid_response(), ensure_ascii=False))

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    bad_payload = _sample_payload("BADCKT")
    bad_payload["periodo_inicio"] = {"a": 1}

    manifest = batch_module.run_batch([bad_payload, _sample_payload("OKCKT")])

    statuses = {entry["circuito"]: entry["status"] for entry in manifest["circuits"]}
    assert statuses == {"BADCKT": "FAILED", "OKCKT": "ok"}
    assert len(manifest["circuits"]) == 2


def test_publish_report_is_atomic_and_never_leaves_a_partial_file(tmp_path, monkeypatch):
    """A crash mid-write must never leave a truncated/corrupt published
    report: the write goes to a temp file first, then os.replace() swaps it
    into place; if the replace itself fails, the pre-existing file (if any)
    must be untouched."""
    monkeypatch.chdir(tmp_path)
    published_dir = tmp_path / "reports" / "interpretability" / "published"
    published_dir.mkdir(parents=True)
    report_path = published_dir / "ATOMICCKT.json"
    report_path.write_text('{"existing": "valid"}')

    def failing_replace(*args, **kwargs):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(_atomic_io.os, "replace", failing_replace)

    with pytest.raises(OSError):
        batch_module._publish_report("ATOMICCKT", {"sintesis_final": "new content"})

    assert report_path.read_text() == '{"existing": "valid"}', (
        "the pre-existing published report must never be left partially overwritten"
    )


def test_load_circuit_payloads_concatenates_multiple_file_arguments(tmp_path):
    file_a = tmp_path / "a.json"
    file_b = tmp_path / "b.json"
    file_a.write_text(json.dumps(_sample_payload("CKTA"), ensure_ascii=False))
    file_b.write_text(json.dumps([_sample_payload("CKTB"), _sample_payload("CKTC")], ensure_ascii=False))

    payloads = batch_module._load_circuit_payloads([str(file_a), str(file_b)])

    assert [p["circuito"] for p in payloads] == ["CKTA", "CKTB", "CKTC"]
