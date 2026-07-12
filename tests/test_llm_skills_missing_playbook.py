"""Missing-playbook fail-loudly guard for `sdd/retire-llm-directory` Slice A/B
profiles (`base`, `inferencia`, `expert_alignment`).

Verification of `sdd/retire-llm-directory` (WARNING #1) found that only the
`auto_simulator` (`test_auto_simulator_load_path.py`) and
`pdf_discussion_extraction` (`test_pdf_discussion_extraction_load_path.py`)
profiles had a dedicated test proving a missing/incomplete playbook directory
raises `FileNotFoundError` loudly, before any LLM call could be attempted.

The underlying resolver (`verify_required_skills` / `assemble_skill_bundle` in
`llm_skills.py`) is shared, profile-agnostic code, but the spec names this as
an explicit per-profile scenario ("Missing playbook after relocation"). This
file closes the coverage gap for the three remaining profiles that route
through `.claude/skills/<agent>/prompt/`, mirroring
`test_auto_simulator_load_path.py::test_missing_auto_simulator_playbook_raises_loudly`'s
exact pattern: an empty `base_dir` override simulates a missing/incomplete
relocation, so `assemble_skill_bundle` must raise before any prompt text could
reach a `call_llm(...)` call site.
"""

from __future__ import annotations

import pytest

from chec_local_interpreter.llm_skills import assemble_skill_bundle


def test_missing_base_playbook_raises_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        assemble_skill_bundle(base_dir=tmp_path, profile="base")


def test_missing_inferencia_playbook_raises_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        assemble_skill_bundle(base_dir=tmp_path, profile="inferencia")


def test_missing_expert_alignment_playbook_raises_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        assemble_skill_bundle(base_dir=tmp_path, profile="expert_alignment")
