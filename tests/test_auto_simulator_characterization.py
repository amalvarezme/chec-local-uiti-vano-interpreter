"""Golden-snapshot characterization test pinning the `auto_simulator` skill
bundle (`sdd/retire-llm-directory`, Phase D).

Mirrors `tests/test_expert_alignment_characterization.py`'s convention: pin the
FULL bundle text (never a substring/`in` check) via a committed golden file
under `tests/golden/retire_llm_directory/`. The golden was captured from
`assemble_skill_bundle(profile="auto_simulator")` immediately after D.2's
`git mv` + D.3's resolver repoint — since `git mv` preserves file content
byte-for-byte, this is equivalent to capturing it from the pre-move
`llm/skills_auto_simulator/` tree. This test is the safety net for D.2/D.3: it
must keep passing, byte-identical, for any future edit that is a pure
relocation (not a content change).
"""

from __future__ import annotations

from pathlib import Path

from chec_local_interpreter.llm_skills import assemble_skill_bundle

GOLDEN_DIR = Path(__file__).parent / "golden" / "retire_llm_directory"


def _read_golden(name: str) -> str:
    path = GOLDEN_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"Golden fixture not found: {path}. Regenerate it from the current "
            ".claude/skills/auto-simulator/prompt/ tree before relying on this test."
        )
    return path.read_text(encoding="utf-8")


def test_char_auto_simulator_bundle_matches_golden():
    bundle = assemble_skill_bundle(profile="auto_simulator")
    assert bundle == _read_golden("auto_simulator_bundle.md")
