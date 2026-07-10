"""Shared L2 CLI stdin/stdout dispatch contract, agent-agnostic.

Every L2 tool-adapter CLI (`agent_tools/expert_alignment.py`, the future
`agent_tools/historical.py`) reads exactly one JSON document from stdin and
writes exactly one JSON document to stdout, using the same exit-code
contract:

    0   ok — the verb's handler succeeded.
    1   validation failure — the handler ran but rejected its input
        (schema/provenance/guardrail errors). Not a crash.
    2   malformed request — stdin was not valid JSON, was not a JSON object,
        or was missing the verb's required field.
    3   unexpected error — anything else, including an error raised while
        reading/parsing stdin that a malformed-request check did not
        anticipate (e.g. non-UTF-8 bytes). The traceback goes to stderr
        only; stdout still gets exactly one JSON document.

Hoisting this here (instead of duplicating it per agent, as the
expert-alignment pilot originally did) is what lets a new agent's CLI
inherit the same hardening from day one instead of re-introducing the
pilot's Known Limitation #2 (payload-loading errors bypassing the catch-all
and crashing with a bare traceback).
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable, Mapping

Handler = Callable[[dict[str, Any]], tuple[dict[str, Any], int]]


class MalformedRequestError(Exception):
    """Raised when the stdin payload is not valid JSON or misses a required field."""


def load_stdin_object(required_key: str) -> dict[str, Any]:
    """Parse stdin as a JSON object and check for `required_key`.

    Raises `MalformedRequestError` for empty/invalid JSON, a non-object
    payload, or a missing required field. Any OTHER exception raised while
    reading/parsing stdin (e.g. a `UnicodeDecodeError` from non-UTF-8 bytes)
    is intentionally left to propagate — `dispatch`'s outer catch-all turns
    it into exit code 3 instead of a malformed-request (2), since it is a
    genuinely unanticipated failure, not a well-formed-but-invalid request.
    """
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise MalformedRequestError(f"stdin is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise MalformedRequestError("stdin JSON payload must be an object.")

    if required_key not in payload:
        raise MalformedRequestError(f"Missing required field: {required_key}")

    return payload


def dispatch(
    verb: str,
    handlers: Mapping[str, tuple[str, Handler]],
    *,
    module_name: str,
) -> int:
    """Load stdin for `verb`, run its handler, and enforce the 0/1/2/3 contract.

    `handlers` maps each verb name to `(required_stdin_key, handler)`, where
    `handler(payload) -> (result_dict, exit_code)`. `dispatch` guarantees
    exactly one JSON document is written to `sys.stdout` on every path:
    the handler's own result on success or validation failure, a
    `{"ok": False, "errors": [...]}` document on a malformed request (exit 2),
    or the same shape on any other unexpected error (exit 3) — with the full
    traceback logged to stderr only, never mixed into stdout.
    """
    required_key, handler = handlers[verb]
    try:
        try:
            payload = load_stdin_object(required_key)
        except MalformedRequestError as exc:
            json.dump({"ok": False, "errors": [f"Malformed request: {exc}"]}, sys.stdout, ensure_ascii=False)
            return 2

        result, exit_code = handler(payload)
        json.dump(result, sys.stdout, ensure_ascii=False)
        return exit_code
    except Exception as exc:  # noqa: BLE001 - every path must still yield one JSON document
        print(f"[{module_name}] unexpected error:\n{traceback.format_exc()}", file=sys.stderr)
        json.dump({"ok": False, "errors": [f"Unexpected error: {exc}"]}, sys.stdout, ensure_ascii=False)
        return 3
