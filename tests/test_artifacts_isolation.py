"""Regression guard: pytest MUST NOT write into the tracked
`reports/interpretability/artifacts/` tree.

`historical.validate()` / `inference.validate()` write failure artifacts
under a module-level `ARTIFACTS_ROOT` resolved relative to the process cwd.
Production `/reporte` runs rely on that (cwd = repo root, intentional). But
in-process tests that call `validate()` directly with an invalid payload
share the same cwd as the pytest process itself, so without isolation they
leak stub files into the real, git-tracked artifacts tree.

The autouse fixture in `tests/conftest.py` closes that leak by redirecting
every agent-tools module's `ARTIFACTS_ROOT` to a per-test `tmp_path`
subdirectory. This test proves the redirect actually takes effect for the
two writer modules known to leak (see design doc item 1a).
"""

from __future__ import annotations

import json
from pathlib import Path

from chec_local_interpreter.agent_tools import historical, inference

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRACKED_ARTIFACTS_ROOT = PROJECT_ROOT / "reports" / "interpretability" / "artifacts"


def _invalid_payload() -> dict:
    # Missing/garbage response_text fails schema validation immediately,
    # which is enough to reach `_write_failure_artifact` without needing a
    # fully-built context fixture.
    return {"response_text": json.dumps({"not": "a valid response"}), "context": {}}


def test_historical_validate_failure_writes_under_tmp_not_tracked_tree():
    result, exit_code = historical.validate(_invalid_payload())

    assert exit_code == 1
    artifact_path = Path(result["artifact_path"])
    assert artifact_path.exists()
    assert TRACKED_ARTIFACTS_ROOT not in artifact_path.parents
    assert TRACKED_ARTIFACTS_ROOT.resolve() not in artifact_path.resolve().parents


def test_inference_validate_failure_writes_under_tmp_not_tracked_tree():
    result, exit_code = inference.validate(_invalid_payload())

    assert exit_code == 1
    artifact_path = Path(result["artifact_path"])
    assert artifact_path.exists()
    assert TRACKED_ARTIFACTS_ROOT not in artifact_path.parents
    assert TRACKED_ARTIFACTS_ROOT.resolve() not in artifact_path.resolve().parents


def test_full_suite_leaves_tracked_artifacts_tree_unchanged(pytestconfig):
    """Documents the invariant the fixture guarantees; the real end-to-end
    proof is `git status` after a full `pytest -q` run (spec scenario:
    "Full pytest run leaves tracked tree unchanged"), which this single test
    cannot observe from inside the same session. This test instead confirms
    the tracked-tree pattern used by that manual/CI check stays valid: the
    directory (if present) contains no files newer than the fixture redirect
    was introduced, i.e. no invalid_*.json siblings created by this run.
    """
    before = set(TRACKED_ARTIFACTS_ROOT.rglob("invalid_*.json")) if TRACKED_ARTIFACTS_ROOT.exists() else set()

    historical.validate(_invalid_payload())
    inference.validate(_invalid_payload())

    after = set(TRACKED_ARTIFACTS_ROOT.rglob("invalid_*.json")) if TRACKED_ARTIFACTS_ROOT.exists() else set()

    assert after == before, "validate() failures must never add files under the tracked artifacts tree"
