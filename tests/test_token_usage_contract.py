from __future__ import annotations

import json

import pytest

from chec_local_interpreter.report_pipeline import record_token_usage, verify_token_usage


def test_record_preserves_legacy_entries_and_replaces_one_stage(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "token_usage.json").write_text(json.dumps({"historical": {"total": 7}}))
    record_token_usage(run, "inference", input=1, output=2)
    record_token_usage(run, "historical", total=9)
    assert json.loads((run / "token_usage.json").read_text()) == {
        "historical": {"total": 9}, "inference": {"input": 1, "output": 2}
    }


@pytest.mark.parametrize("kwargs", [{"total": -1}, {"input": 1}, {"total": 1, "input": 2, "output": 3}])
def test_record_rejects_invalid_measurements(tmp_path, kwargs):
    with pytest.raises(ValueError):
        record_token_usage(tmp_path, "historical", **kwargs)


def test_verification_reports_missing_and_invalid_without_estimating(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "token_usage.json").write_text(json.dumps({"historical": {"total": "bad"}}))
    result = verify_token_usage(run, expected_roles=("historical", "inference"), executed_roles=("historical", "inference"))
    assert not result.ok
    assert result.missing_measurements == ("historical", "inference")
    assert result.invalid_roles == ("historical",)


def test_cli_record_and_verify(capsys, tmp_path):
    from chec_local_interpreter.report_contract import main

    assert main(["record-usage", "--run-dir", str(tmp_path), "--stage", "historical", "--total", "4"]) == 0
    assert main(["verify-usage", "--run-dir", str(tmp_path), "--executed-role", "historical"]) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["ok"] is True


def test_strict_render_requires_measured_executed_roles_before_render(capsys, tmp_path):
    from chec_local_interpreter.report_contract import main

    exit_code = main(
        [
            "render", "C1", "--run-dir", str(tmp_path), "--runtime", "pi",
            "--require-measured-usage", "--executed-role", "historical",
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert result["status"] == "execution_error"
    assert "token usage verification failed" in result["errors"]


def test_verification_rejects_executed_role_outside_expected_roles(tmp_path):
    record_token_usage(tmp_path, "historical", total=7)

    result = verify_token_usage(
        tmp_path,
        expected_roles=("inference",),
        executed_roles=("historical",),
    )

    assert not result.ok
    assert result.errors == ("executed role is not expected: historical",)
