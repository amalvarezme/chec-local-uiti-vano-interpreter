"""Shared atomic-write helper for `agent_tools` (hoisted out of `batch.py` and
`expert_alignment.py`, which previously duplicated this function verbatim).

Both the batch runner's published-report writes and the CLI's failure-artifact
writes go through this single implementation, so a fix here (e.g. the file
permissions behavior) only needs to happen once.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, content: str) -> None:
    """Write `content` to `path` atomically.

    Writes to a temp file in the same directory first, then `os.replace()`s
    it into place. `os.replace()` is atomic on the same filesystem, so a
    crash/exception mid-write can never leave `path` truncated or corrupt —
    either the previous content (if any) survives untouched, or the new
    content lands whole. The temp file is cleaned up if anything raises
    before the replace completes.

    `tempfile.mkstemp()` always creates its file at mode `0600`, and
    `os.replace()` preserves that mode — without an explicit `chmod`, every
    file written this way would be locked to owner-only access regardless of
    the process umask. Reset the mode to a sane default (`0o644`, the same
    default a normal `Path.write_text()` call would typically produce)
    before it lands at `path`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        # mkstemp() always creates the temp file at 0600; os.replace() would
        # otherwise carry that restrictive mode straight through to `path`.
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
