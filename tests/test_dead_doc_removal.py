"""Guard test for `sdd/retire-llm-directory` Phase B dead-doc removal.

`llm/prompts/ContextoProyectoSimuladorCHEC.md` and `llm/prompts/arquitecturayflujo.md`
were deleted outright (no code path ever loaded them — confirmed during
exploration). This test pins two things:

1. The files no longer exist at their old path.
2. No tracked, in-scope file in the repository references their old
   `llm/prompts/...` path.

Note: bare filename citations (e.g. "`ContextoProyectoSimuladorCHEC.md`" with
no `llm/prompts/` prefix) inside `.claude/skills/historical/prompt/*.md` and
`docs/*.md` are NOT stale — they refer to the still-existing
`docs/ContextoProyectoSimuladorCHEC.md` / `docs/arquitecturayflujo.md` copies
of the same-named document, not to the deleted `llm/prompts/` variant. Only
the literal old path is checked here.

`docs/project-workflow-analysis.md` is a pre-existing, tracked scratch
analysis document explicitly out of scope for this change (it predates and
is unrelated to `sdd/retire-llm-directory`); it still contains one literal
mention of the old `llm/prompts/arquitecturayflujo.md` path as a historical
note about doc triplication. It is intentionally excluded from this guard's
scan rather than edited.

`docs/project-workflow-diagram.svg` is the pre-rendered companion image to
the analysis doc above (same historical, out-of-scope commit); it contains
baked-in `llm/skills*` label text from its Mermaid source but does not
contain either of this guard's `OLD_PATHS` strings. It is excluded here
defensively, for the same reason as its companion `.md` file.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

OLD_PATHS = (
    "llm/prompts/ContextoProyectoSimuladorCHEC.md",
    "llm/prompts/arquitecturayflujo.md",
)

# Pre-existing, tracked, out-of-scope scratch doc and its pre-rendered
# companion SVG (see module docstring), plus this test file itself, which
# necessarily cites the old paths literally in OLD_PATHS/the docstring above
# and would otherwise flag itself as an offender.
EXCLUDED_FILES = {
    "docs/project-workflow-analysis.md",
    "docs/project-workflow-diagram.svg",
    "tests/test_dead_doc_removal.py",
}


def test_dead_docs_no_longer_exist():
    for old_path in OLD_PATHS:
        assert not (PROJECT_ROOT / old_path).exists(), f"{old_path} should have been deleted"


def test_no_tracked_reference_to_dead_doc_old_paths():
    tracked_files = subprocess.run(
        ["git", "ls-files"],
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
        for old_path in OLD_PATHS:
            if old_path in text:
                offenders.append(f"{rel_path} references {old_path}")

    assert offenders == [], "Stale references to deleted dead-doc paths:\n" + "\n".join(offenders)
