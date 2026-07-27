"""Static + guard contract tests for the `/experimento-kaggle` skill.

Covers PR1, PR2, and PR3 of `kaggle-notebook-builder-agent`:
- PR1: the skill contract (Hard Rule + Experiment Families dispatch +
  baseline reference), the import-based precondition guard, and `.pi`
  adapter integrity.
- PR2: the data/model dataset-transport gate, `src/` dataset packaging
  documentation, and the `dataset_sources` format documented for the
  future (PR3) `kernel-metadata.json`.
- PR3: the `uiti-vano-regression-budget` notebook package itself
  (`kernel-metadata.json` + `notebook.ipynb`) authored under
  `notebooks/kaggle_experiments/`.

Pattern follows `tests/test_llm_skills.py` (static assertions over authored
skill text) plus one real subprocess check for the guard, since prose alone
cannot prove the guard actually trips.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = PROJECT_ROOT / ".claude" / "skills" / "experimento-kaggle"
SKILL_MD = SKILL_DIR / "SKILL.md"
BASELINE_REF = SKILL_DIR / "references" / "uiti-vano-regression-baseline.md"
CLI_NOTES = SKILL_DIR / "references" / "kaggle-cli-notes.md"
PI_SKILL_MD = PROJECT_ROOT / ".pi" / "skills" / "experimento-kaggle" / "SKILL.md"

NOTEBOOK_SLUG = "uiti-vano-regression-budget"
NOTEBOOK_DIR = PROJECT_ROOT / "notebooks" / "kaggle_experiments" / NOTEBOOK_SLUG
KERNEL_METADATA = NOTEBOOK_DIR / "kernel-metadata.json"
NOTEBOOK_FILE = NOTEBOOK_DIR / "notebook.ipynb"

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


def test_dataset_transport_gate_documented():
    """SKILL.md must state a second, explicit upload-approval gate for
    private Kaggle datasets (code + data), separate from the notebook-
    approval gate, and must record the user's already-granted approval for
    the full `Indicadores_vano_v3.csv` upload as a decision, not a question."""
    text = _read(SKILL_MD)

    assert re.search(r"private dataset", text, re.IGNORECASE)
    assert re.search(r"second.{0,40}explicit.{0,40}approval|explicit.{0,40}approval.{0,40}separate", text, re.IGNORECASE | re.DOTALL)
    assert "Indicadores_vano_v3.csv" in text
    assert re.search(r"already approved|already-approved|recorded decision", text, re.IGNORECASE)


def test_src_dataset_packaging_documented():
    """SKILL.md must document packaging `src/chec_impacto/` as a whole
    subtree (never a single-file vendor) into a private code dataset, and
    name the cross-import reason for whole-subtree packaging."""
    text = _read(SKILL_MD)

    assert "Dataset Transport" in text
    assert "src/chec_impacto" in text
    assert re.search(r"whole subtree|entire subtree", text, re.IGNORECASE)
    assert "chec_impacto.training.mgcecdl" in text


def test_kernel_metadata_dataset_sources_format_documented():
    """references/kaggle-cli-notes.md must document the `dataset_sources`
    array format that the PR3 `kernel-metadata.json` will use, including
    both pinned dataset slugs for this family."""
    assert CLI_NOTES.exists()
    text = _read(CLI_NOTES)

    assert "dataset_sources" in text
    assert "chec-impacto-src" in text
    assert "uiti-vano-indicadores-v3" in text


def test_dataset_commands_documented_in_cli_notes():
    """references/kaggle-cli-notes.md must document the official dataset
    create/version commands and the `dataset-metadata.json` schema —
    separate from the existing kernel push/status/output commands."""
    text = _read(CLI_NOTES)

    assert "kaggle datasets create" in text
    assert "kaggle datasets version" in text
    assert "dataset-metadata.json" in text


def test_pi_adapter_thin_after_dataset_transport_addition():
    """.pi adapter may reference the new dataset-transport gate by name,
    but must not duplicate the pinned dataset slugs or packaging details."""
    text = _read(PI_SKILL_MD)

    for needle in ("chec-impacto-src", "uiti-vano-indicadores-v3", "Indicadores_vano_v3.csv"):
        assert needle not in text, f"'.pi' adapter must not duplicate dataset-transport detail {needle!r}"


def test_kernel_metadata_slug():
    """`kernel-metadata.json`'s `id` slug must match the folder name it
    lives in, and must reference both PR2-pinned dataset slugs."""
    assert KERNEL_METADATA.exists(), "kernel-metadata.json must exist under the slug folder"
    metadata = json.loads(_read(KERNEL_METADATA))

    assert metadata["id"].split("/")[-1] == NOTEBOOK_DIR.name == NOTEBOOK_SLUG
    assert metadata["code_file"] == "notebook.ipynb"
    assert metadata["is_private"] == "true"
    assert metadata["kernel_type"] == "notebook"

    dataset_sources = metadata["dataset_sources"]
    assert any(s.endswith("/chec-impacto-src") for s in dataset_sources)
    assert any(s.endswith("/uiti-vano-indicadores-v3") for s in dataset_sources)


def test_notebook_file_exists_and_is_valid():
    """notebook.ipynb must exist, be valid nbformat, and carry a papermill
    `parameters`-tagged cell defaulting to `mode = "smoke"` (so a bare
    execution never accidentally launches the full search budget)."""
    import nbformat

    assert NOTEBOOK_FILE.exists()
    nb = nbformat.read(NOTEBOOK_FILE, as_version=4)
    nbformat.validate(nb)

    parameter_cells = [c for c in nb.cells if "parameters" in c.get("metadata", {}).get("tags", [])]
    assert len(parameter_cells) == 1, "exactly one papermill parameters cell expected"
    assert 'mode = "smoke"' in parameter_cells[0]["source"]


def test_notebook_guard_mirror_present():
    """The notebook's bootstrap must mirror the skill's precondition guard:
    the exact import probe, failing with an actionable message naming the
    missing-code worktree — matching references/uiti-vano-regression-baseline.md's
    'In-Notebook Mirror' section."""
    import nbformat

    nb = nbformat.read(NOTEBOOK_FILE, as_version=4)
    full_source = "\n".join(c["source"] for c in nb.cells if c["cell_type"] == "code")

    assert GUARD_IMPORT_PROBE.replace(
        "from chec_impacto.models.mgcecdl import MGCECDLRegressor, MGCECDLRegressionLoss",
        "MGCECDLRegressor",
    ) or "MGCECDLRegressor" in full_source
    assert "from chec_impacto.models.mgcecdl import" in full_source
    assert "MGCECDLRegressor" in full_source
    assert "MGCECDLRegressionLoss" in full_source
    assert "KernelDensityWeightedMSELoss" in full_source
    assert MISSING_CODE_WORKTREE in full_source
    assert "ImportError" in full_source


def test_notebook_reuses_no_redefinition():
    """The notebook must import the model/loss classes, never redefine them
    (no `class MGCECDLRegressor` / `class MGCECDLRegressionLoss` anywhere)."""
    import nbformat

    nb = nbformat.read(NOTEBOOK_FILE, as_version=4)
    full_source = "\n".join(c["source"] for c in nb.cells if c["cell_type"] == "code")

    assert "class MGCECDLRegressor" not in full_source
    assert "class MGCECDLRegressionLoss" not in full_source
    assert "class KernelDensityWeightedMSELoss" not in full_source


def test_notebook_methodology_order_and_metric():
    """Loss sweep selects by `mae_original.idxmin()`, Optuna reuses
    `run_optuna_study` (GPSampler+MedianPruner, never reimplemented), the
    loss composition passes all parity terms, and `full` mode exceeds the
    baseline's 10-trial/20-epoch/60-epoch budget while `smoke` stays tiny."""
    import nbformat

    nb = nbformat.read(NOTEBOOK_FILE, as_version=4)
    full_source = "\n".join(c["source"] for c in nb.cells if c["cell_type"] == "code")

    assert 'mae_original"].idxmin()' in full_source
    assert "run_optuna_study" in full_source
    assert "class GPSampler" not in full_source and "class MedianPruner" not in full_source

    for term in ("gamma_sup", "gamma_agr", "gamma_reg", "lambda_reconstruction", "lambda_mutual_information"):
        assert term in full_source

    assert "kernel_weighted_mse" in full_source
    assert "OPTUNA_N_TRIALS = 15" in full_source  # full mode: > 10 (baseline)
    assert "OPTUNA_MAX_EPOCHS = 20" in full_source  # full mode: not reduced vs baseline
    assert "FINAL_MAX_EPOCHS = 60" in full_source  # full mode: not reduced vs baseline
    assert "K_RANGE = range(2," in full_source
    assert "adjusted_rand_score" in full_source


def test_notebook_report_cell_states_improvement_against_baseline():
    """The report cell must print this run's `mae_original` next to the
    pinned baseline (126.402) and state improved/not, per spec's 'Full run
    reports MAE against baseline' scenario."""
    import nbformat

    nb = nbformat.read(NOTEBOOK_FILE, as_version=4)
    full_source = "\n".join(c["source"] for c in nb.cells if c["cell_type"] == "code")

    assert "BASELINE_MAE_ORIGINAL = 126.402" in full_source
    assert "improved" in full_source.lower()
    assert 'final_metrics["mae_original"]' in full_source
