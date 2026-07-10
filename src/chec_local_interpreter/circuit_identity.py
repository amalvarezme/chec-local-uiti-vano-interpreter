"""Single, agent-agnostic home for circuit-identity canonicalization.

Every code path that builds a circuit-derived filesystem path (published
report, failure artifact, or any future path) MUST derive its identity from
`canonical_circuit_identity` in this module — not a per-agent copy. Prior to
this module, `normalizar_circuito` lived in `expert_alignment.py`,
`sanitize_circuito_dirname` lived in `agent_tools/expert_alignment.py`, and
`agent_tools/batch.py` composed its own `_canonical_circuit_identity` from
both. `agent_tools/expert_alignment.py::_write_failure_artifact` used only
the sanitize step, diverging from the batch runner's publish path for the
same circuit (closed here).

This module is intentionally stdlib-only (no pandas): it is used by L1
domain code (`expert_alignment.py`), L2 CLIs (`agent_tools/*.py`), and the L4
batch runner alike, so it must not pull in any single agent's dependencies or
sit under a single-agent-named package.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_MAX_CIRCUITO_DIRNAME_LENGTH = 128


def normalizar_circuito(value: Any) -> str:
    """Normalize circuit ids for strict, case-insensitive equality checks."""
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def sanitize_circuito_dirname(circuito: Any) -> str:
    """Reduce an untrusted `circuito` value to a single, safe directory name.

    Strips ASCII control characters first (including an embedded NUL byte,
    which would otherwise crash `Path.resolve()`/`mkdir()`/`write_text()`
    with `ValueError: embedded null byte`). Then `Path(...).name` strips any
    directory separators and `..`/absolute-path components, so a value like
    "../../../../etc/evil" collapses to "evil" and can never be used to
    escape a target artifacts root. Falls back to "unknown" for any input
    that collapses to nothing usable, and caps the result length so an
    oversized `circuito` can never trip a filesystem name-length limit.
    """
    cleaned = _CONTROL_CHARS_RE.sub("", str(circuito or "")).strip()
    name = Path(cleaned).name
    if not name or name in {".", ".."}:
        return "unknown"
    return name[:_MAX_CIRCUITO_DIRNAME_LENGTH]


def canonical_circuit_identity(circuito: Any) -> str:
    """Compute the single canonical on-disk identity for a `circuito` value.

    Sanitizing first (`sanitize_circuito_dirname`) matches filesystem-safe
    naming — so two raw values that would land on the same filename (e.g. a
    path-separator-suffix collision like "AAA/BBB" vs "CCC/BBB", both
    becoming "BBB"; or two distinct whitespace/control-char-only strings
    both falling back to "unknown") are always recognized as the same
    on-disk target. Normalizing on top (`normalizar_circuito`, the
    codebase's own case/punctuation-insensitive circuit-identity check)
    additionally catches values that are the same circuit but differ only
    in case or punctuation (e.g. "DON23L13" vs "don23l13"), which would
    otherwise run twice and could further collide on a case-insensitive
    filesystem with no signal in the manifest.

    This MUST be the single identity function used by every consumer that
    needs to decide "is this the same circuit" or derive the actual on-disk
    filename for it (publish path, dedup key, failure-artifact directory) —
    using independently-derived functions for those questions would let them
    disagree, either silently dropping a legitimate distinct run or writing
    two different failure-artifact directories for what publishes to the
    same report file.
    """
    return normalizar_circuito(sanitize_circuito_dirname(circuito))
