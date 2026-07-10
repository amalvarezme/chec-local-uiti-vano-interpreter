"""Pin the shared L2 CLI stdin-hardening contract (exit codes 0/1/2/3).

Both `agent_tools/expert_alignment.py` and the future `agent_tools/historical.py`
delegate their `main()` to `cli_support.dispatch`, so this module's behavior
IS the shared contract every L2 CLI must honor: exactly one JSON document on
stdout for every path, and the same 0/1/2/3 exit-code meaning everywhere.
"""

from __future__ import annotations

import io
import json

import pytest

from chec_local_interpreter.agent_tools.cli_support import (
    MalformedRequestError,
    dispatch,
    load_stdin_object,
)


def _set_stdin(monkeypatch, text: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


class _UnreadableStdin:
    """Simulates a stdin read failure not anticipated by JSON parsing."""

    def read(self, *args, **kwargs):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")


def test_load_stdin_object_returns_parsed_dict_when_required_key_present(monkeypatch):
    _set_stdin(monkeypatch, json.dumps({"circuito": "DON23L13", "extra": 1}))
    payload = load_stdin_object("circuito")
    assert payload == {"circuito": "DON23L13", "extra": 1}


def test_load_stdin_object_raises_on_invalid_json(monkeypatch):
    _set_stdin(monkeypatch, "not json at all")
    with pytest.raises(MalformedRequestError):
        load_stdin_object("circuito")


def test_load_stdin_object_raises_on_empty_stdin(monkeypatch):
    _set_stdin(monkeypatch, "")
    with pytest.raises(MalformedRequestError):
        load_stdin_object("circuito")


def test_load_stdin_object_raises_on_non_dict_payload(monkeypatch):
    _set_stdin(monkeypatch, json.dumps([1, 2, 3]))
    with pytest.raises(MalformedRequestError):
        load_stdin_object("circuito")


def test_load_stdin_object_raises_on_missing_required_key(monkeypatch):
    _set_stdin(monkeypatch, json.dumps({"other": 1}))
    with pytest.raises(MalformedRequestError):
        load_stdin_object("circuito")


def _handlers_ok_zero(payload):
    return {"ok": True, "data": payload}, 0


def _handlers_validation_fail():
    def handler(payload):
        return {"ok": False, "errors": ["bad"]}, 1

    return handler


def _handlers_raises(payload):
    raise RuntimeError("boom")


def test_dispatch_success_path_writes_one_json_document_and_returns_handler_exit_code(monkeypatch, capsys):
    _set_stdin(monkeypatch, json.dumps({"circuito": "DON23L13"}))

    exit_code = dispatch(
        "build-context",
        {"build-context": ("circuito", _handlers_ok_zero)},
        module_name="test_module",
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert json.loads(out) == {"ok": True, "data": {"circuito": "DON23L13"}}


def test_dispatch_validation_failure_path_returns_handler_exit_code_one(monkeypatch, capsys):
    _set_stdin(monkeypatch, json.dumps({"response_text": "bad"}))

    exit_code = dispatch(
        "validate",
        {"validate": ("response_text", _handlers_validation_fail())},
        module_name="test_module",
    )

    assert exit_code == 1
    out = capsys.readouterr().out
    stdout_data = json.loads(out)
    assert stdout_data["ok"] is False


def test_dispatch_malformed_request_returns_exit_code_two_with_single_json_document(monkeypatch, capsys):
    _set_stdin(monkeypatch, "not json")

    exit_code = dispatch(
        "build-context",
        {"build-context": ("circuito", _handlers_ok_zero)},
        module_name="test_module",
    )

    assert exit_code == 2
    captured = capsys.readouterr()
    stdout_data = json.loads(captured.out)
    assert stdout_data["ok"] is False
    assert stdout_data["errors"]
    assert "Traceback" not in captured.err


def test_dispatch_missing_required_field_returns_exit_code_two(monkeypatch, capsys):
    _set_stdin(monkeypatch, json.dumps({"other": 1}))

    exit_code = dispatch(
        "build-context",
        {"build-context": ("circuito", _handlers_ok_zero)},
        module_name="test_module",
    )

    assert exit_code == 2
    stdout_data = json.loads(capsys.readouterr().out)
    assert stdout_data["ok"] is False


def test_dispatch_handler_exception_returns_exit_code_three_with_traceback_on_stderr_only(monkeypatch, capsys):
    _set_stdin(monkeypatch, json.dumps({"circuito": "DON23L13"}))

    exit_code = dispatch(
        "build-context",
        {"build-context": ("circuito", _handlers_raises)},
        module_name="test_module",
    )

    assert exit_code == 3
    captured = capsys.readouterr()
    stdout_data = json.loads(captured.out)
    assert stdout_data["ok"] is False
    assert "Traceback" not in captured.out
    assert "Traceback" in captured.err
    assert "RuntimeError" in captured.err


def test_dispatch_unexpected_payload_loading_error_still_yields_one_json_document(monkeypatch, capsys):
    """Spec: L2 CLI Payload-Loading Exception Coverage — an exception during
    stdin reading/parsing that is NOT anticipated by the malformed-request
    check (e.g. a `UnicodeDecodeError` from non-UTF-8 bytes) must still
    produce exactly one JSON document on stdout with `ok: false` and a
    non-zero exit code, never a bare traceback / no output at all."""
    monkeypatch.setattr("sys.stdin", _UnreadableStdin())

    exit_code = dispatch(
        "build-context",
        {"build-context": ("circuito", _handlers_ok_zero)},
        module_name="test_module",
    )

    assert exit_code == 3
    captured = capsys.readouterr()
    stdout_data = json.loads(captured.out)
    assert stdout_data["ok"] is False
    assert "Traceback" not in captured.out
    assert "Traceback" in captured.err
