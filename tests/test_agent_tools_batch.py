"""Headless per-circuit batch runner (design's Failure handling section / WU4).

Every test stubs the subprocess boundary (`subprocess.run`) — no real
`claude` process is ever invoked. Each test also chdirs into `tmp_path` so
published reports and failure artifacts never touch the real repo.

`agent=` is a required keyword-only argument on `run_circuit`/`run_batch`
(an `AgentSpec`, generalized in the shared-infra hardening slice so the
runner is not hardcoded to a single agent role) — every call site below
passes `batch_module.EXPERT_ALIGNMENT_AGENT` explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from chec_local_interpreter.agent_tools import _atomic_io, batch as batch_module
from chec_local_interpreter.agent_tools import inference as inference_module
from chec_local_interpreter.agent_tools.expert_alignment import TOOL_VERSION
from chec_local_interpreter.expert_alignment import construir_contexto_expert_alignment

EXPERT_ALIGNMENT_AGENT = batch_module.EXPERT_ALIGNMENT_AGENT


def _sample_payload(circuito: str = "DON23L13") -> dict:
    """Build an already-built expert-alignment context — the real payload
    shape `EXPERT_ALIGNMENT_AGENT.build_context` (== `agent_tools.expert_alignment.build_context`)
    expects post-fix, matching what `report_pipeline.prepare_expert_alignment()`
    writes to `expert-alignment.bc.json`. `circuito` stays a top-level key
    (it already is, on the built context) since `run_circuit` keys its own
    manifest/dedupe/publish bookkeeping off it regardless of agent role."""
    context = construir_contexto_expert_alignment(
        circuito=circuito,
        periodo_inicio="2026-01-01",
        periodo_fin="2026-01-31",
        fechas_informe=[
            {
                "source": "critical_point",
                "fecha_inicio": "2026-01-10",
                "fecha_fin": "2026-01-10",
                "descripcion": "cp",
                "peso": 3.0,
            }
        ],
        validation_data={"period_synthesis": "UITI_VANO sube en el punto crítico."},
        inference_validation_data={"hallazgos": ["El modelo resalta CNT_TRF."]},
        pdf_expert_matches=[
            {
                "Circuito": circuito,
                "Fecha inicio": "2026-01-09",
                "Fecha fin": "2026-01-11",
                "Análisis": "UITI_VANO alto",
                "Evidencia": "Evidencia experta verificable",
                "pdf_row_index": 3,
            }
        ],
        variables_modelo_predictivo=["CNT_TRF"],
    )
    context["skill_bundle"] = "Skill bundle de prueba"
    return context


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

    entry = batch_module.run_circuit(_sample_payload(), agent=EXPERT_ALIGNMENT_AGENT)

    assert len(calls) == 1, "success on the first attempt must be exactly one isolated invocation"
    assert calls[0][:2] == list(batch_module.DEFAULT_AGENT_COMMAND)

    assert entry["circuito"] == "DON23L13"
    assert entry["status"] == "ok"
    assert entry["tool_version"] == TOOL_VERSION
    assert entry["retries"] == 0
    assert entry["artifact_paths"], "expected the published report path to be recorded"

    published_path = Path(entry["artifact_paths"][0])
    assert published_path.is_file()
    assert published_path.parent.name == "expert-alignment", (
        "the published report must be namespaced under the agent's role directory"
    )
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

    entry = batch_module.run_circuit(_sample_payload(), agent=EXPERT_ALIGNMENT_AGENT, max_retries=2)

    assert len(calls) == 3, "expected the first attempt plus 2 retries (MAX_VALIDATION_RETRIES default)"
    # The repair pattern must feed validator errors back — later prompts differ from the first.
    assert calls[1][-1] != calls[0][-1]
    assert "sintesis_final" in calls[1][-1] or "Errores de validaci" in calls[1][-1]

    assert entry["status"] == "FAILED"
    assert entry["retries"] == 2
    assert entry["artifact_paths"], "expected failure artifact paths to be recorded"
    for artifact_path in entry["artifact_paths"]:
        assert Path(artifact_path).is_file()

    published_dir = tmp_path / "reports" / "interpretability" / "published" / "expert-alignment"
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

    manifest = batch_module.run_batch(
        [_sample_payload("FAILCKT"), _sample_payload("OKCKT")],
        agent=EXPERT_ALIGNMENT_AGENT,
    )

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

    entry = batch_module.run_circuit(_sample_payload(), agent=EXPERT_ALIGNMENT_AGENT)

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

    manifest = batch_module.run_batch(
        [_sample_payload("DUPCKT"), _sample_payload("DUPCKT")],
        agent=EXPERT_ALIGNMENT_AGENT,
    )

    statuses = [entry["status"] for entry in manifest["circuits"]]
    assert statuses == ["ok", "SKIPPED_DUPLICATE"]
    assert len(calls) == 1, "the duplicate must never trigger a second agent invocation"

    published_path = tmp_path / "reports" / "interpretability" / "published" / "expert-alignment" / "DUPCKT.json"
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

    manifest = batch_module.run_batch(
        [_sample_payload("AAA/BBB"), _sample_payload("CCC/BBB")],
        agent=EXPERT_ALIGNMENT_AGENT,
    )

    statuses = [entry["status"] for entry in manifest["circuits"]]
    assert statuses == ["ok", "SKIPPED_DUPLICATE"]
    assert len(calls) == 1, "the sanitize-collision duplicate must never trigger a second agent invocation"

    published_dir = tmp_path / "reports" / "interpretability" / "published" / "expert-alignment"
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

    manifest = batch_module.run_batch(
        [_sample_payload("DON23L13"), _sample_payload("don23l13")],
        agent=EXPERT_ALIGNMENT_AGENT,
    )

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

    manifest = batch_module.run_batch(
        [_sample_payload("AAA/CCC"), _sample_payload("AAA/DDD")],
        agent=EXPERT_ALIGNMENT_AGENT,
    )

    statuses = [entry["status"] for entry in manifest["circuits"]]
    assert statuses == ["ok", "ok"], "genuinely distinct circuits must never be falsely deduped"
    assert len(calls) == 2


def test_run_batch_dedup_and_publish_share_the_same_canonical_filename_identity(tmp_path, monkeypatch):
    """`DON23L13` and `don23l13` are the same circuit for dedup purposes
    (`_dedupe_key` uses `canonical_circuit_identity`); `_publish_report` must
    derive the on-disk filename with the SAME identity function, so the
    manifest's SKIPPED_DUPLICATE claim ("to avoid overwriting the first
    run's published report") stays factually true — a case-only difference
    in the raw value must not silently produce two different-case filenames
    that would never actually collide on a case-sensitive filesystem."""
    monkeypatch.chdir(tmp_path)

    def fake_run(command, **kwargs):
        return _FakeCompletedProcess(stdout=json.dumps(_valid_response("don23l13"), ensure_ascii=False))

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    manifest = batch_module.run_batch(
        [_sample_payload("don23l13"), _sample_payload("DON23L13")],
        agent=EXPERT_ALIGNMENT_AGENT,
    )

    statuses = [entry["status"] for entry in manifest["circuits"]]
    assert statuses == ["ok", "SKIPPED_DUPLICATE"]

    published_dir = tmp_path / "reports" / "interpretability" / "published" / "expert-alignment"
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
    real_validate = EXPERT_ALIGNMENT_AGENT.validate

    def spy_validate(payload):
        captured_contexts.append(payload.get("context", {}).get("circuito"))
        return real_validate(payload)

    # `agent` is a frozen AgentSpec, so a "spy" is a fresh spec with only
    # `validate` swapped — not a monkeypatched module attribute.
    spied_agent = batch_module.AgentSpec(
        role=EXPERT_ALIGNMENT_AGENT.role,
        build_context=EXPERT_ALIGNMENT_AGENT.build_context,
        validate=spy_validate,
        tool_version=EXPERT_ALIGNMENT_AGENT.tool_version,
    )
    monkeypatch.setattr(
        batch_module.subprocess,
        "run",
        lambda command, **kwargs: _FakeCompletedProcess(stdout=json.dumps(_invalid_response(), ensure_ascii=False)),
    )

    payload = _sample_payload()
    payload["circuito"] = None

    entry = batch_module.run_circuit(payload, agent=spied_agent, max_retries=0)

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

    entry = batch_module.run_circuit(_sample_payload(), agent=EXPERT_ALIGNMENT_AGENT)

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

    batch_module.run_circuit(_sample_payload(), agent=EXPERT_ALIGNMENT_AGENT)

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

    batch_module.run_circuit(_sample_payload(), agent=EXPERT_ALIGNMENT_AGENT, timeout=7.5)

    assert captured_kwargs.get("timeout") == 7.5


def test_run_batch_passes_timeout_through_to_run_circuit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    response_text = json.dumps(_valid_response(), ensure_ascii=False)
    captured_kwargs: dict = {}

    def fake_run(command, **kwargs):
        captured_kwargs.update(kwargs)
        return _FakeCompletedProcess(stdout=response_text)

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    batch_module.run_batch([_sample_payload()], agent=EXPERT_ALIGNMENT_AGENT, timeout=3.0)

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

    entry = batch_module.run_circuit(_sample_payload(), agent=EXPERT_ALIGNMENT_AGENT)

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

    entry = batch_module.run_circuit(_sample_payload("BAD\x00CKT"), agent=EXPERT_ALIGNMENT_AGENT, max_retries=0)

    assert entry["status"] == "FAILED"
    assert "error" in entry


def test_run_circuit_malformed_context_missing_periodo_informe_does_not_crash_and_is_failed(tmp_path, monkeypatch):
    """`build_context` no longer parses a raw `periodo_inicio` (that
    assembly now lives entirely upstream, in
    `report_pipeline.prepare_expert_alignment()`) — the analogous new-contract
    failure mode is an already-built context missing a field `build_context`
    still reads directly (`context["periodo_informe"]`). This must still be
    captured as a FAILED manifest entry, not an uncaught exception."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        batch_module.subprocess,
        "run",
        lambda command, **kwargs: _FakeCompletedProcess(stdout=json.dumps(_valid_response(), ensure_ascii=False)),
    )

    payload = _sample_payload("BADPERIOD")
    del payload["periodo_informe"]

    entry = batch_module.run_circuit(payload, agent=EXPERT_ALIGNMENT_AGENT)

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

    fake_agent = batch_module.AgentSpec(
        role=EXPERT_ALIGNMENT_AGENT.role,
        build_context=raise_key_error,
        validate=EXPERT_ALIGNMENT_AGENT.validate,
        tool_version=EXPERT_ALIGNMENT_AGENT.tool_version,
    )

    entry = batch_module.run_circuit(_sample_payload("BUGCKT"), agent=fake_agent)

    assert entry["status"] == "FAILED"
    assert "error" in entry
    assert "Traceback" not in entry["error"], "the manifest entry must stay a clean, short error message"

    captured = capsys.readouterr()
    assert "Traceback" in captured.err
    assert "KeyError" in captured.err
    assert "simulated programming bug" in captured.err


def test_run_batch_continues_when_one_circuit_has_a_malformed_field(tmp_path, monkeypatch):
    """A batch with one bad circuit (missing periodo_informe) and one good
    circuit must still complete with both entries in the manifest."""
    monkeypatch.chdir(tmp_path)

    def fake_run(command, **kwargs):
        prompt = command[-1]
        if "OKCKT" in prompt:
            return _FakeCompletedProcess(stdout=json.dumps(_valid_response("OKCKT"), ensure_ascii=False))
        return _FakeCompletedProcess(stdout=json.dumps(_valid_response(), ensure_ascii=False))

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    bad_payload = _sample_payload("BADCKT")
    del bad_payload["periodo_informe"]

    manifest = batch_module.run_batch(
        [bad_payload, _sample_payload("OKCKT")],
        agent=EXPERT_ALIGNMENT_AGENT,
    )

    statuses = {entry["circuito"]: entry["status"] for entry in manifest["circuits"]}
    assert statuses == {"BADCKT": "FAILED", "OKCKT": "ok"}
    assert len(manifest["circuits"]) == 2


def test_publish_report_is_atomic_and_never_leaves_a_partial_file(tmp_path, monkeypatch):
    """A crash mid-write must never leave a truncated/corrupt published
    report: the write goes to a temp file first, then os.replace() swaps it
    into place; if the replace itself fails, the pre-existing file (if any)
    must be untouched."""
    monkeypatch.chdir(tmp_path)
    published_dir = tmp_path / "reports" / "interpretability" / "published" / "expert-alignment"
    published_dir.mkdir(parents=True)
    report_path = published_dir / "ATOMICCKT.json"
    report_path.write_text('{"existing": "valid"}')

    def failing_replace(*args, **kwargs):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(_atomic_io.os, "replace", failing_replace)

    with pytest.raises(OSError):
        batch_module._publish_report("ATOMICCKT", {"sintesis_final": "new content"}, role="expert-alignment")

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


# --- AgentSpec generalization (Phase 4) ---------------------------------


def test_agent_is_a_required_keyword_only_argument_on_run_circuit():
    with pytest.raises(TypeError):
        batch_module.run_circuit(_sample_payload())  # missing required `agent` kwarg

    with pytest.raises(TypeError):
        batch_module.run_circuit(_sample_payload(), EXPERT_ALIGNMENT_AGENT)  # positional not allowed


def test_agent_is_a_required_keyword_only_argument_on_run_batch():
    with pytest.raises(TypeError):
        batch_module.run_batch([_sample_payload()])  # missing required `agent` kwarg

    with pytest.raises(TypeError):
        batch_module.run_batch([_sample_payload()], EXPERT_ALIGNMENT_AGENT)  # positional not allowed


def test_two_agent_specs_publish_the_same_circuito_without_colliding(tmp_path, monkeypatch):
    """The whole point of role-namespacing (spec: agent-namespaced-reports):
    two different agents publishing a report for the SAME circuito must
    never overwrite each other."""
    monkeypatch.chdir(tmp_path)

    def fake_run(command, **kwargs):
        return _FakeCompletedProcess(stdout=json.dumps(_valid_response("SHARED01"), ensure_ascii=False))

    monkeypatch.setattr(batch_module.subprocess, "run", fake_run)

    historical_agent = batch_module.AgentSpec(
        role="historical",
        build_context=EXPERT_ALIGNMENT_AGENT.build_context,
        validate=EXPERT_ALIGNMENT_AGENT.validate,
        tool_version="historical-agent-tools/0.1.0",
    )

    expert_entry = batch_module.run_circuit(_sample_payload("SHARED01"), agent=EXPERT_ALIGNMENT_AGENT)
    historical_entry = batch_module.run_circuit(_sample_payload("SHARED01"), agent=historical_agent)

    assert expert_entry["status"] == "ok"
    assert historical_entry["status"] == "ok"

    expert_path = Path(expert_entry["artifact_paths"][0])
    historical_path = Path(historical_entry["artifact_paths"][0])
    assert expert_path != historical_path
    assert expert_path.parent.name == "expert-alignment"
    assert historical_path.parent.name == "historical"
    assert expert_path.is_file()
    assert historical_path.is_file()


def test_manifest_tool_version_comes_from_the_agent_spec_not_a_hardcoded_constant(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        batch_module.subprocess,
        "run",
        lambda command, **kwargs: _FakeCompletedProcess(stdout=json.dumps(_valid_response("OKCKT"), ensure_ascii=False)),
    )

    custom_agent = batch_module.AgentSpec(
        role="historical",
        build_context=EXPERT_ALIGNMENT_AGENT.build_context,
        validate=EXPERT_ALIGNMENT_AGENT.validate,
        tool_version="historical-agent-tools/9.9.9",
    )

    entry = batch_module.run_circuit(_sample_payload("OKCKT"), agent=custom_agent)
    assert entry["tool_version"] == "historical-agent-tools/9.9.9"

    manifest = batch_module.run_batch([_sample_payload("OKCKT")], agent=custom_agent)
    assert manifest["tool_version"] == "historical-agent-tools/9.9.9"
    assert manifest["circuits"][0]["tool_version"] == "historical-agent-tools/9.9.9"


def test_cli_agent_flag_selects_the_registered_agent_spec(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    circuits_file = tmp_path / "circuits.json"
    circuits_file.write_text(json.dumps([_sample_payload("OKCKT")], ensure_ascii=False))

    monkeypatch.setattr(
        batch_module.subprocess,
        "run",
        lambda command, **kwargs: _FakeCompletedProcess(stdout=json.dumps(_valid_response("OKCKT"), ensure_ascii=False)),
    )

    exit_code = batch_module.main(["--circuits", str(circuits_file), "--agent", "expert-alignment"])

    assert exit_code == 0
    published_path = tmp_path / "reports" / "interpretability" / "published" / "expert-alignment" / "OKCKT.json"
    assert published_path.is_file()


# --- Historical AgentSpec registration (Phase 9) ------------------------


def _sample_historical_context(circuito: str = "DON23L13") -> dict:
    return {
        # `run_circuit` keys its own manifest/dedupe/publish bookkeeping off a
        # top-level "circuito" field for every agent, regardless of how that
        # agent's own `build_context` derives its identity internally (the
        # historical agent derives its own from `metadata.circuitos`) — a
        # real caller assembling this payload for the batch runner must
        # supply both.
        "circuito": circuito,
        "analysis_name": "local_uiti_vano_interpretability",
        "metadata": {
            "v": "test",
            "schema": "test",
            "ts": "2026-01-01T00:00",
            "circuitos": [circuito],
            "start": "2026-01-01",
            "end": "2026-01-03",
            "unavailable_cols": [],
        },
        "selected_context": {"circuitos": [circuito], "indicator": "UITI_VANO"},
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


def _valid_historical_response(circuito: str = "DON23L13") -> dict:
    from chec_local_interpreter.llm_contracts import PROMPT_VERSION

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
                        "date": "2026-01-02",
                        "critical_point_id": "cp-2026-01-02",
                        "variable": "UITI_VANO",
                        "summary": "El dia aporta una fraccion alta del UITI_VANO total.",
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


def test_historical_agent_is_registered_in_agent_specs():
    assert "historical" in batch_module.AGENT_SPECS
    assert batch_module.AGENT_SPECS["historical"] is batch_module.HISTORICAL_AGENT
    assert batch_module.HISTORICAL_AGENT.role == "historical"


def test_historical_agent_end_to_end_build_context_validate_publish(tmp_path, monkeypatch):
    """End-to-end using the REAL `HISTORICAL_AGENT` spec (not a synthetic
    stand-in): build-context -> invoke -> validate -> publish
    `published/historical/{circuito}.json`."""
    monkeypatch.chdir(tmp_path)
    response_text = json.dumps(_valid_historical_response(), ensure_ascii=False)

    monkeypatch.setattr(
        batch_module.subprocess,
        "run",
        lambda command, **kwargs: _FakeCompletedProcess(stdout=response_text),
    )

    payload = _sample_historical_context("DON23L13")
    entry = batch_module.run_circuit(payload, agent=batch_module.HISTORICAL_AGENT)

    assert entry["status"] == "ok", entry
    assert entry["tool_version"] == batch_module.HISTORICAL_AGENT.tool_version

    published_path = Path(entry["artifact_paths"][0])
    assert published_path.is_file()
    assert published_path.parent.name == "historical"
    published_data = json.loads(published_path.read_text())
    assert published_data["headline"]


def test_inference_agent_is_registered_in_agent_specs():
    """Phase 4 (Slice A, PR3): the inference agent's `AgentSpec` must be
    registered in `AGENT_SPECS`, wired to the real
    `agent_tools.inference` module's `build_context`/`validate`/
    `TOOL_VERSION` — same registration shape as `HISTORICAL_AGENT`."""
    assert "inference" in batch_module.AGENT_SPECS
    assert batch_module.AGENT_SPECS["inference"] is batch_module.INFERENCE_AGENT
    assert batch_module.INFERENCE_AGENT.role == "inference"
    assert batch_module.INFERENCE_AGENT.build_context is inference_module.build_context
    assert batch_module.INFERENCE_AGENT.validate is inference_module.validate
    assert batch_module.INFERENCE_AGENT.tool_version == inference_module.TOOL_VERSION


def test_no_other_source_module_hardcodes_the_flat_published_path():
    """Only agent_tools/batch.py may reference the published-reports root for
    publishing purposes — every publish must go through the role-namespaced
    `PUBLISHED_REPORTS_ROOT / agent.role` composition, never the flat
    (pre-namespacing) path string, so a future agent's L2 CLI can never
    reintroduce a cross-agent publish collision by bypassing the runner.

    `cleanup_runs.py` is also allowlisted: it references the same flat root
    purely as a deletion target (one of the 9 known report-run artifact
    category roots enumerated in its `CATEGORIES` constant), never to
    construct a publish path, so it cannot reintroduce the bypass this guard
    defends against."""
    src_root = Path(__file__).resolve().parents[1] / "src" / "chec_local_interpreter"
    allowed_names = {"batch.py", "cleanup_runs.py"}
    offenders = [
        str(path)
        for path in src_root.rglob("*.py")
        if path.name not in allowed_names and "reports/interpretability/published" in path.read_text()
    ]
    assert offenders == []
