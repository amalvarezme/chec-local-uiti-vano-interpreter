"""Golden-snapshot characterization test pinning the `expert_alignment` skill
bundle (`sdd/retire-llm-directory`, Phase B).

Mirrors `tests/test_llm_skills_characterization.py`'s convention: pin the
FULL bundle text (never a substring/`in` check) via a committed golden file
under `tests/golden/retire_llm_directory/`, generated from the pre-move
`llm/skills_expert_alignment/` tree. This test is the safety net for B.3's
relocation to `.claude/skills/expert-alignment/prompt/` and B.4's resolver
repoint — it must pass unchanged, byte-identical, both before and after the
move.
"""

from __future__ import annotations

from pathlib import Path

from chec_local_interpreter.llm_skills import assemble_skill_bundle

GOLDEN_DIR = Path(__file__).parent / "golden" / "retire_llm_directory"


def _read_golden(name: str) -> str:
    path = GOLDEN_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"Golden fixture not found: {path}. Run the golden-generation step "
            "against the CURRENT unmoved llm/skills_expert_alignment/ tree "
            "before relocating anything."
        )
    return path.read_text(encoding="utf-8")


def test_char_expert_alignment_bundle_matches_golden():
    bundle = assemble_skill_bundle(profile="expert_alignment")
    assert bundle == _read_golden("expert_alignment_bundle.md")
