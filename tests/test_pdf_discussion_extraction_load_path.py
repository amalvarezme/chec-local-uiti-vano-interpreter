"""Load-path guard for `sdd/retire-llm-directory` Phase C (pdf-discussion-extraction,
light contract per design D4).

`notebooks/core/01_pdf_discussion_table_from_pdfs.ipynb`'s `PDFDiscussionExtractionSkill`
wrapper loads its playbook via a raw `Path(...).read_text()` call — there is no
`agent_tools` L2 CLI and no dedicated Python loader function for this agent (the
light contract intentionally adds no new machinery). This test pins the two
behaviors spec/design require without introducing a new loader:

1. (RED equivalent) A missing playbook path raises `FileNotFoundError` loudly via
   the exact `Path.read_text()` call shape the notebook cell uses — a missing
   file at the new location fails the same way it would have at the old `llm/`
   location, never silently continuing with an empty/degraded prompt.
2. (GREEN / load-path smoke, covering the accepted "no full notebook execution
   in pytest" gap) The relocated playbook exists at
   `.claude/skills/pdf-discussion-extraction/prompt/01_pdf_discussion_extractor.md`,
   is readable, and still contains the `{fragmento}` template placeholder the
   notebook's `.replace()`-based prompt builder depends on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK_PATH = (
    PROJECT_ROOT
    / ".claude"
    / "skills"
    / "pdf-discussion-extraction"
    / "prompt"
    / "01_pdf_discussion_extractor.md"
)


def test_missing_playbook_path_raises_loudly(tmp_path):
    missing_path = tmp_path / "does_not_exist" / "01_pdf_discussion_extractor.md"
    with pytest.raises(FileNotFoundError):
        missing_path.read_text(encoding="utf-8")


def test_relocated_playbook_exists_and_is_readable():
    assert PLAYBOOK_PATH.exists(), f"Relocated playbook not found: {PLAYBOOK_PATH}"
    content = PLAYBOOK_PATH.read_text(encoding="utf-8")
    assert content.strip(), "Relocated playbook is empty"


def test_relocated_playbook_contains_fragmento_placeholder():
    content = PLAYBOOK_PATH.read_text(encoding="utf-8")
    assert "{fragmento}" in content


def test_notebook_skill_path_points_to_new_location():
    notebook_path = (
        PROJECT_ROOT / "notebooks" / "core" / "01_pdf_discussion_table_from_pdfs.ipynb"
    )
    text = notebook_path.read_text(encoding="utf-8")
    assert (
        r"SKILL_PATH = project_root / \".claude\" / \"skills\" / \"pdf-discussion-extraction\""
        r" / \"prompt\" / \"01_pdf_discussion_extractor.md\""
    ) in text
    assert "llm\\\" / \\\"skills_pdf_discussion_extraction" not in text
