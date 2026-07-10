"""Pin the behavior of the shared, agent-agnostic circuit-identity helpers.

These functions used to be duplicated/diverged across `expert_alignment.py`
(`normalizar_circuito`), `agent_tools/expert_alignment.py`
(`_sanitize_circuito_dirname`), and `agent_tools/batch.py`
(`_canonical_circuit_identity`). This module is now their single home.
"""

from __future__ import annotations

from chec_local_interpreter.circuit_identity import (
    canonical_circuit_identity,
    normalizar_circuito,
    sanitize_circuito_dirname,
)


def test_normalizar_circuito_strips_non_alnum_and_uppercases():
    assert normalizar_circuito("don23l13") == "DON23L13"
    assert normalizar_circuito("DON-23-L13") == "DON23L13"
    assert normalizar_circuito("don 23 l13") == "DON23L13"


def test_normalizar_circuito_handles_none_and_empty():
    assert normalizar_circuito(None) == ""
    assert normalizar_circuito("") == ""
    assert normalizar_circuito("   ") == ""


def test_sanitize_circuito_dirname_strips_control_chars():
    assert sanitize_circuito_dirname("DON\x01\x1f23L13") == "DON23L13"


def test_sanitize_circuito_dirname_strips_embedded_null_byte():
    # An embedded NUL byte would otherwise crash Path.resolve()/mkdir()/
    # write_text() with `ValueError: embedded null byte` further downstream.
    assert sanitize_circuito_dirname("BAD\x00CKT") == "BADCKT"


def test_sanitize_circuito_dirname_collapses_path_traversal():
    assert sanitize_circuito_dirname("../../../../etc/evil") == "evil"


def test_sanitize_circuito_dirname_collapses_absolute_path():
    assert sanitize_circuito_dirname("/etc/evil-circuit") == "evil-circuit"


def test_sanitize_circuito_dirname_falls_back_to_unknown_for_dot_only_input():
    assert sanitize_circuito_dirname(".") == "unknown"
    assert sanitize_circuito_dirname("..") == "unknown"


def test_sanitize_circuito_dirname_falls_back_to_unknown_for_control_only_input():
    assert sanitize_circuito_dirname("\x00\x01\x02") == "unknown"
    assert sanitize_circuito_dirname("") == "unknown"
    assert sanitize_circuito_dirname(None) == "unknown"


def test_sanitize_circuito_dirname_caps_length_at_128_chars():
    oversized = "A" * 300
    result = sanitize_circuito_dirname(oversized)
    assert len(result) == 128
    assert result == "A" * 128


def test_canonical_circuit_identity_composes_sanitize_then_normalize():
    # Sanitize first (path-safe), then normalize (case/punctuation-insensitive).
    assert canonical_circuit_identity("don23l13") == "DON23L13"
    assert canonical_circuit_identity("DON-23-L13") == "DON23L13"
    assert canonical_circuit_identity("../../../../DON23L13") == "DON23L13"


def test_canonical_circuit_identity_matches_manual_composition():
    for raw in ("don23l13", "DON-23-L13", "../../evil/BBB", "/etc/evil-circuit", None, ""):
        assert canonical_circuit_identity(raw) == normalizar_circuito(sanitize_circuito_dirname(raw))
