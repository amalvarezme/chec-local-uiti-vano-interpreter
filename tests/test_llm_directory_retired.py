"""Guard test for `sdd/retire-llm-directory` Phase E (final `llm/` retirement).

Pins two things once Slice E lands:

1. The top-level `llm/` directory (the residual `llm/README.md` plus the
   emptied `llm/skills_auto_simulator/` dir left over from Phase D's
   `git mv`) no longer exists at all.
2. No tracked file under `src/` calls or imports `config.llm_root` /
   `chec_local_interpreter.config.llm_root` — the resolver itself was removed
   in this slice (`agent_prompt_dir()` and `prompt_assets_dir()`, its
   permanent replacements, are NOT touched and are exempt from this scan).

This file itself necessarily names ``config.llm_root`` in its own source
(the attribute/docstrings below), so it excludes itself from the source scan,
matching the precedent set by `tests/test_dead_doc_removal.py`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# This test file necessarily names the retired symbol in its own source
# (module docstring, constant below) and would otherwise flag itself.
EXCLUDED_FILES = {"tests/test_llm_directory_retired.py"}

# The literal call-site/import shapes we look for. A bare comment mentioning
# "llm_root" in prose (e.g. explaining historical resolver behavior) is not
# flagged — only an actual attribute access or import is a live call site.
LLM_ROOT_CALL_PATTERNS = (
    "config.llm_root(",
    "from chec_local_interpreter.config import llm_root",
    "import llm_root",
)


def test_llm_directory_no_longer_exists():
    assert not (PROJECT_ROOT / "llm").exists(), "llm/ should have been deleted in Slice E"


def test_no_src_file_calls_config_llm_root():
    tracked_files = subprocess.run(
        ["git", "ls-files", "src"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    offenders: list[str] = []
    for rel_path in tracked_files:
        if rel_path in EXCLUDED_FILES:
            continue
        full_path = PROJECT_ROOT / rel_path
        if not full_path.is_file():
            continue
        try:
            text = full_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in LLM_ROOT_CALL_PATTERNS:
            if pattern in text:
                offenders.append(f"{rel_path} references {pattern!r}")

    assert offenders == [], "Stale config.llm_root call sites under src/:\n" + "\n".join(offenders)
