from __future__ import annotations

import json

import pytest

from chec_local_interpreter.agent_output import ReportPipelineError
from chec_local_interpreter.report_pipeline import record_stage_timing


def test_record_preserves_legacy_entries_and_replaces_one_stage(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "stage_timing.json").write_text(json.dumps({"historical": {"duration_seconds": 7.0}}))
    record_stage_timing(run, "inference", seconds=12.5)
    record_stage_timing(run, "historical", seconds=9.0)
    assert json.loads((run / "stage_timing.json").read_text()) == {
        "historical": {"duration_seconds": 9.0},
        "inference": {"duration_seconds": 12.5},
    }


def test_record_writes_atomically_via_tmp_and_replace(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    record_stage_timing(run, "historical", seconds=1.0)
    record_stage_timing(run, "inference", seconds=2.0)
    record_stage_timing(run, "historical", seconds=3.0)
    # No leftover temp file, and final content merges all recorded stages.
    assert not (run / ".stage_timing.json.tmp").exists()
    assert json.loads((run / "stage_timing.json").read_text()) == {
        "historical": {"duration_seconds": 3.0},
        "inference": {"duration_seconds": 2.0},
    }


def test_record_rejects_unknown_stage(tmp_path):
    with pytest.raises(ValueError):
        record_stage_timing(tmp_path, "not-a-real-stage", seconds=1.0)


@pytest.mark.parametrize("seconds", [-1, -0.001, "3.5", None, float("nan"), float("inf"), True])
def test_record_rejects_invalid_durations(tmp_path, seconds):
    with pytest.raises(ValueError):
        record_stage_timing(tmp_path, "historical", seconds=seconds)


def test_record_accepts_zero_duration(tmp_path):
    result = record_stage_timing(tmp_path, "historical", seconds=0.0)
    assert result == {"duration_seconds": 0.0}


def test_record_accepts_int_duration_and_stores_as_float(tmp_path):
    result = record_stage_timing(tmp_path, "historical", seconds=5)
    assert result == {"duration_seconds": 5.0}


def test_record_rejects_invalid_existing_sidecar_shape(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "stage_timing.json").write_text(json.dumps({"totally-unknown-stage": {"duration_seconds": 1.0}}))
    with pytest.raises(ReportPipelineError):
        record_stage_timing(run, "historical", seconds=1.0)


def test_record_rejects_malformed_existing_sidecar_json(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "stage_timing.json").write_text("{not valid json")
    with pytest.raises(ReportPipelineError):
        record_stage_timing(run, "historical", seconds=1.0)


def test_no_verify_duration_symbol_exists():
    import chec_local_interpreter.report_pipeline as report_pipeline

    assert not hasattr(report_pipeline, "verify_stage_timing")
    assert not hasattr(report_pipeline, "verify_stage_duration")
