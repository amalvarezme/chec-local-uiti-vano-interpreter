"""Shared atomic-write helper (`agent_tools/_atomic_io.py`), hoisted out of
`batch.py` and `expert_alignment.py` (which previously duplicated it
verbatim) so the permissions fix only needs to happen in one place."""

from __future__ import annotations

import os
import stat

from chec_local_interpreter.agent_tools._atomic_io import atomic_write_text
from chec_local_interpreter.agent_tools import batch as batch_module
from chec_local_interpreter.agent_tools import expert_alignment as agent_tools_module


def test_atomic_write_text_does_not_force_owner_only_permissions(tmp_path):
    """`tempfile.mkstemp()` always creates the temp file at mode `0600`, and
    `os.replace()` preserves that mode — every published/failure artifact
    would otherwise be locked to owner-only access even when the process
    umask would normally allow group/other read. The helper must reset the
    resulting file's permissions to a sane default instead of silently
    inheriting mkstemp's restrictive mode."""
    target = tmp_path / "report.json"

    atomic_write_text(target, '{"ok": true}')

    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode != 0o600, "the atomic write must not leave the file locked to owner-only access"
    assert mode == 0o644


def test_atomic_write_text_respects_a_restrictive_process_umask(tmp_path):
    """A hardcoded `0o644` silently overrides a hardened host's umask policy
    (e.g. `umask 077` should produce `0o600`, not `0o644`). The helper must
    derive the mode from the current process umask, the same as a normal
    file-creation call would."""
    target = tmp_path / "restrictive.json"
    previous_umask = os.umask(0o077)
    try:
        atomic_write_text(target, '{"ok": true}')
    finally:
        os.umask(previous_umask)

    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == (0o666 & ~0o077)


def test_batch_module_reuses_the_shared_atomic_write_helper():
    assert batch_module._atomic_write_text is atomic_write_text


def test_expert_alignment_module_reuses_the_shared_atomic_write_helper():
    assert agent_tools_module._atomic_write_text is atomic_write_text
