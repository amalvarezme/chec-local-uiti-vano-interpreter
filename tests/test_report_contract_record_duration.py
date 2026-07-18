from __future__ import annotations

import json

import pytest

from chec_local_interpreter.report_contract import main


def test_cli_record_duration_success(capsys, tmp_path):
    exit_code = main(
        ["record-duration", "--run-dir", str(tmp_path), "--stage", "historical", "--seconds", "1.5"]
    )
    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {"status": "success", "timing": {"duration_seconds": 1.5}}
    assert json.loads((tmp_path / "stage_timing.json").read_text()) == {
        "historical": {"duration_seconds": 1.5}
    }


def test_cli_record_duration_negative_seconds_exits_2(capsys, tmp_path):
    exit_code = main(
        ["record-duration", "--run-dir", str(tmp_path), "--stage", "historical", "--seconds", "-1"]
    )
    assert exit_code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "error"


def test_cli_record_duration_unknown_stage_exits_2(capsys, tmp_path):
    exit_code = main(
        ["record-duration", "--run-dir", str(tmp_path), "--stage", "not-a-stage", "--seconds", "1"]
    )
    assert exit_code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "error"


def test_cli_record_duration_non_numeric_seconds_raises_system_exit(tmp_path):
    with pytest.raises(SystemExit):
        main(["record-duration", "--run-dir", str(tmp_path), "--stage", "historical", "--seconds", "not-a-number"])


def test_cli_record_duration_missing_stage_raises_system_exit(tmp_path):
    with pytest.raises(SystemExit):
        main(["record-duration", "--run-dir", str(tmp_path), "--seconds", "1.5"])


def test_cli_record_duration_missing_seconds_raises_system_exit(tmp_path):
    with pytest.raises(SystemExit):
        main(["record-duration", "--run-dir", str(tmp_path), "--stage", "historical"])


def test_no_verify_duration_cli_verb():
    with pytest.raises(SystemExit):
        main(["verify-duration", "--run-dir", "/tmp"])


def test_cli_record_duration_merges_multiple_stages(capsys, tmp_path):
    assert main(["record-duration", "--run-dir", str(tmp_path), "--stage", "historical", "--seconds", "10"]) == 0
    capsys.readouterr()
    assert main(["record-duration", "--run-dir", str(tmp_path), "--stage", "inference", "--seconds", "20"]) == 0
    capsys.readouterr()
    assert json.loads((tmp_path / "stage_timing.json").read_text()) == {
        "historical": {"duration_seconds": 10.0},
        "inference": {"duration_seconds": 20.0},
    }
