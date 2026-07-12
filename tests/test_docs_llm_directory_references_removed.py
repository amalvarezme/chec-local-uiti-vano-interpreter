"""Guard test for `sdd/retire-llm-directory` Phase E (docs rewrite).

Pins that the two prose docs which used to cite the retired top-level `llm/`
tree — `docs/agents-guide.md`'s "three meanings of skills" table plus its
per-role "Related artifacts" path citations, and `AGENTS.md` — no longer
contain the literal `llm/` path prefix anywhere in their text.

Matches the precision style of `tests/test_dead_doc_removal.py`: a bare
literal-string scan for the exact `llm/` path prefix, not a broader "llm"
word-overlap check (bare mentions of "LLM" as the abstract term, e.g. "LLM
Safety And Quality" in `AGENTS.md`, are not path references and must NOT be
flagged).
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CHECKED_FILES = (
    "docs/agents-guide.md",
    "AGENTS.md",
)

# The literal old path prefix. Anything after it (`llm/skills*`, `llm/prompts/*`,
# `llm/evals/*`, `llm/README.md`, ...) was a reference into the now-deleted
# `llm/` tree.
STALE_PATH_PREFIX = "llm/"


def test_no_llm_path_references_in_docs():
    offenders: list[str] = []
    for rel_path in CHECKED_FILES:
        full_path = PROJECT_ROOT / rel_path
        assert full_path.is_file(), f"{rel_path} should exist"
        text = full_path.read_text(encoding="utf-8")
        if STALE_PATH_PREFIX in text:
            matching_lines = [
                f"  line {i}: {line.strip()}"
                for i, line in enumerate(text.splitlines(), start=1)
                if STALE_PATH_PREFIX in line
            ]
            offenders.append(f"{rel_path}:\n" + "\n".join(matching_lines))

    assert offenders == [], "Stale `llm/` path references remain:\n" + "\n".join(offenders)


def test_llm_the_abstract_term_is_not_flagged_as_a_path():
    # Sanity check on the test's own precision: "LLM" (the abstract term, no
    # trailing slash) legitimately appears throughout AGENTS.md and must not
    # trip the guard above. This documents why STALE_PATH_PREFIX requires the
    # trailing slash rather than matching the bare substring "llm".
    agents_md = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "LLM" in agents_md
    assert STALE_PATH_PREFIX not in agents_md
