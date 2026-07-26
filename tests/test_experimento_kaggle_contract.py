"""Static + guard contract tests for the `/experimento-kaggle` skill.

Covers PR1 of `kaggle-notebook-builder-agent`: the skill contract (Hard Rule
+ Experiment Families dispatch + baseline reference), the import-based
precondition guard, and `.pi` adapter integrity. Pattern follows
`tests/test_llm_skills.py` (static assertions over authored skill text) plus
one real subprocess check for the guard, since prose alone cannot prove the
guard actually trips.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = PROJECT_ROOT / ".claude" / "skills" / "experimento-kaggle"
SKILL_MD = SKILL_DIR / "SKILL.md"
BASELINE_REF = SKILL_DIR / "references" / "uiti-vano-regression-baseline.md"
PI_SKILL_MD = PROJECT_ROOT / ".pi" / "skills" / "experimento-kaggle" / "SKILL.md"

GUARD_IMPORT_PROBE = "from chec_impacto.models.mgcecdl import MGCECDLRegressor, MGCECDLRegressionLoss"
MISSING_CODE_WORKTREE = "worktree-agent-a4051edb7e841e0f9"

# Digits that must never leak into SKILL.md (the contract file) — they live
# only in the baseline reference file.
_BASELINE_DIGIT_NEEDLES = ("126.4", "-0.027", "0.284", "0.1115")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_no_reimplementation_hard_rule():
    """SKILL.md must state the general no-reimplementation Hard Rule and
    carry zero inline baseline metric digits (those live in references/)."""
    assert SKILL_MD.exists(), "SKILL.md must exist before its contract can be tested"
    text = _read(SKILL_MD)

    assert re.search(r"never reimplement a model", text, re.IGNORECASE), (
        "SKILL.md must state the general no-reimplementation Hard Rule"
    )
    assert "src/" in text
    assert re.search(r"stop", text, re.IGNORECASE)

    for needle in _BASELINE_DIGIT_NEEDLES:
        assert needle not in text, (
            f"SKILL.md must not inline baseline metric digits ({needle!r} found); "
            "they belong in references/uiti-vano-regression-baseline.md"
        )


def test_experiment_families_table_present():
    """Step 2 must dispatch into an Experiment Families table naming the
    uiti-vano-regression family, its reuse module, baseline ref, and metric."""
    text = _read(SKILL_MD)
    assert "Experiment Families" in text
    assert "uiti-vano-regression" in text
    assert "chec_impacto.models.mgcecdl" in text
    assert "references/uiti-vano-regression-baseline.md" in text
    assert "mae_original" in text


def test_guard_documented_in_skill():
    """The exact import-probe command and the missing-code worktree name
    must both be documented in SKILL.md so the guard is actionable."""
    text = _read(SKILL_MD)
    assert GUARD_IMPORT_PROBE in text
    assert MISSING_CODE_WORKTREE in text


def test_guard_import_probe_trips_from_main_checkout():
    """The documented import probe, run with only this checkout's `src` on
    the path (no worktree src), must fail — proving the guard is a real,
    exercisable check and not just prose. `MGCECDLRegressor` is only
    present in the untracked worktree carrying this change's dependency."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    result = subprocess.run(
        [sys.executable, "-c", GUARD_IMPORT_PROBE],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode != 0, (
        "Guard probe unexpectedly succeeded from the main checkout — "
        "MGCECDLRegressor should not be importable here yet"
    )
    assert "ImportError" in result.stderr or "ModuleNotFoundError" in result.stderr


def test_baseline_reference_file_has_pinned_metrics():
    """references/uiti-vano-regression-baseline.md must exist and pin the
    primary metric (mae_original) plus the secondary diagnostics."""
    assert BASELINE_REF.exists()
    text = _read(BASELINE_REF)
    assert "mae_original" in text
    assert "126.4" in text
    assert "-0.027" in text
    assert "0.284" in text
    assert "mps" in text.lower(), "baseline hardware must be documented as MPS, not CPU"


def test_pi_adapter_is_thin_pointer():
    """.pi adapter must stay a thin `canonical_skill:` pointer: it may name
    the no-reimplementation rule and Experiment Families dispatch by
    reference, but must not duplicate rule text or baseline digits."""
    assert PI_SKILL_MD.exists()
    text = _read(PI_SKILL_MD)

    assert "canonical_skill: ../../../.claude/skills/experimento-kaggle/SKILL.md" in text

    for needle in _BASELINE_DIGIT_NEEDLES:
        assert needle not in text, f"'.pi' adapter must not duplicate baseline digit {needle!r}"

    # References the rule by name, does not restate its full text.
    assert re.search(r"reimplement", text, re.IGNORECASE)
    # Never re-embeds the Experiment Families table rows.
    assert "chec_impacto.models.mgcecdl" not in text
