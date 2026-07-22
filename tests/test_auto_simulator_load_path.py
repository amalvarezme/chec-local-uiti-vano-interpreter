"""Load-path / fail-loudly guard for `sdd/retire-llm-directory` Phase D
(auto-simulator, light contract per design D4).

Unlike `pdf-discussion-extraction` (Phase C), the auto-simulator profile flows
through the shared `llm_skills` resolver (`skills_dir()` / `verify_required_skills()`
/ `assemble_skill_bundle()`), not a raw `Path.read_text()` call. This test pins
the behavior spec/design require:

1. (RED before D.2/D.3) `skills_dir(profile="auto_simulator")` resolves to the
   code-owned `.claude/skills/auto-simulator/prompt/` home, per D3's per-profile
   incremental repoint. Before the relocation (D.2 `git mv`) and the resolver
   repoint (D.3), this assertion fails because the profile still resolves to
   `llm_root()/skills_auto_simulator`.
2. A missing/incomplete playbook directory makes `assemble_skill_bundle()` raise
   `FileNotFoundError` immediately, before any LLM call could happen — mirrored
   here via an empty `base_dir` override.

The notebook-content characterization tests this file previously carried
(`test_notebook_guards_missing_skills_before_llm_call`,
`test_notebook_has_no_hardcoded_old_auto_simulator_path`) asserted against
`the retired interactive notebook`'s raw text.
That notebook was deleted by `agent-native-pipeline-and-site-split` PR A1
once `/reporte` was proven to cover everything it did (the automatic
min/max simulator is now wired into `report_pipeline.py` -- see
`test_report_pipeline.py`'s `_run_automatic_simulator`/`prepare()` tests) --
those two tests are removed here rather than left asserting against a file
that no longer exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chec_local_interpreter.llm_skills import assemble_skill_bundle, skills_dir

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELOCATED_AUTO_SIMULATOR_DIR = (
    PROJECT_ROOT / ".claude" / "skills" / "auto-simulator" / "prompt"
)


def test_auto_simulator_skills_dir_resolves_to_relocated_path():
    resolved = skills_dir(profile="auto_simulator")
    assert resolved == RELOCATED_AUTO_SIMULATOR_DIR


def test_missing_auto_simulator_playbook_raises_loudly(tmp_path):
    # An empty base_dir simulates a missing/incomplete relocation: no LLM call
    # is reachable because assemble_skill_bundle raises before returning any
    # prompt text for call_llm to consume.
    with pytest.raises(FileNotFoundError):
        assemble_skill_bundle(base_dir=tmp_path, profile="auto_simulator")
