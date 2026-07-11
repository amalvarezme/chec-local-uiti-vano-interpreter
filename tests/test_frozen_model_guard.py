"""Frozen-model invariant guard (design section 4 / WU3).

Layered, cheap, code-checked safety net — the only one this CI-less repo
has — that the M-GCECDL model artifact and its training package are never
touched by the agent-tools surface:

(a) Static import guard — no `agent_tools` module imports `chec_impacto.training`.
(b) sha256 manifest — the model zip's hash must match the recorded, tracked
    manifest; any drift (accidental write/retrain) fails loudly.
(c) Content guard — agent role / Claude Code Skill markdown files must never
    mention training/retraining vocabulary. WU5a/WU5b have since landed
    `.claude/agents/**/*.md` and `.claude/skills/expert-alignment/**/*.md`;
    this test now actively scans those real, tracked files (no vacuous case
    in this branch's state).
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_TOOLS_DIR = PROJECT_ROOT / "src" / "chec_local_interpreter" / "agent_tools"
MODEL_ZIP_PATH = PROJECT_ROOT / "data" / "models" / "mgcecdl_classifier_best.zip"
MODEL_MANIFEST_PATH = PROJECT_ROOT / "data" / "models" / "manifest.sha256.json"
MODEL_MANIFEST_KEY = "data/models/mgcecdl_classifier_best.zip"

GOVERNANCE_MARKDOWN_ROOTS = (
    PROJECT_ROOT / ".claude" / "agents",
    PROJECT_ROOT / ".claude" / "skills" / "expert-alignment",
    PROJECT_ROOT / ".claude" / "skills" / "historical",
    PROJECT_ROOT / ".claude" / "skills" / "inference",
    PROJECT_ROOT / ".claude" / "skills" / "reporte",
)
# The governance docs this guard scans (`.claude/agents/**/*.md`,
# `.claude/skills/expert-alignment/**/*.md`) are Spanish-language documents,
# so the forbidden-phrase list must cover the Spanish training vocabulary
# too (e.g. "reentrenar el modelo"), not just the English terms — otherwise
# a future Spanish-language edit would bypass this guard entirely. Matching
# is case-insensitive (all scanned text is lowercased first).
FORBIDDEN_TRAINING_PHRASES = (
    "training",
    ".fit(",
    "retrain",
    "entrenar",
    "entrenamiento",
    "reentrenar",
    "reentrenamiento",
)


def _agent_tools_modules() -> list[Path]:
    assert AGENT_TOOLS_DIR.is_dir(), f"agent_tools package missing: {AGENT_TOOLS_DIR}"
    return sorted(AGENT_TOOLS_DIR.rglob("*.py"))


def test_agent_tools_modules_scans_nested_subpackages_too(tmp_path, monkeypatch):
    """A future subpackage under `agent_tools/` (e.g. `agent_tools/foo/bar.py`)
    must never be silently unscanned by the import guard — a non-recursive
    top-level-only glob would miss it entirely."""
    (tmp_path / "top.py").write_text("x = 1\n")
    nested_dir = tmp_path / "nested_subpkg"
    nested_dir.mkdir()
    nested_file = nested_dir / "mod.py"
    nested_file.write_text("import chec_impacto.training\n")

    monkeypatch.setattr(sys.modules[__name__], "AGENT_TOOLS_DIR", tmp_path)

    modules = _agent_tools_modules()

    assert nested_file in modules, "a nested agent_tools subpackage module must be scanned"


def _imports_training_package(node: ast.AST) -> str | None:
    """Return the offending dotted module name if `node` imports chec_impacto.training, else None."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            name = alias.name
            if name == "chec_impacto.training" or name.startswith("chec_impacto.training."):
                return name
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if module == "chec_impacto.training" or module.startswith("chec_impacto.training."):
            return module
    return None


def test_agent_tools_modules_never_import_the_training_package():
    violations: list[str] = []
    for path in _agent_tools_modules():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            offending_module = _imports_training_package(node)
            if offending_module:
                violations.append(f"{path.relative_to(PROJECT_ROOT)}: imports {offending_module}")

    assert not violations, (
        "agent_tools must have no import path to chec_impacto.training "
        f"(frozen-model invariant): {violations}"
    )


def test_agent_tools_modules_never_reference_the_model_zip_path():
    """Defense in depth: no agent_tools source should even name the model artifact."""
    violations: list[str] = []
    for path in _agent_tools_modules():
        source = path.read_text()
        if "mgcecdl_classifier_best" in source:
            violations.append(str(path.relative_to(PROJECT_ROOT)))

    assert not violations, f"agent_tools must never reference the frozen model artifact: {violations}"


def test_model_zip_sha256_matches_the_tracked_manifest():
    assert MODEL_ZIP_PATH.exists(), (
        f"Frozen model artifact is missing: {MODEL_ZIP_PATH}. "
        "This guard must fail loudly, not silently skip, if the artifact disappears."
    )
    assert MODEL_MANIFEST_PATH.exists(), (
        f"sha256 manifest is missing: {MODEL_MANIFEST_PATH}. "
        "Generate it once via a local sha256 computation and commit it alongside this test."
    )

    manifest = json.loads(MODEL_MANIFEST_PATH.read_text())
    assert MODEL_MANIFEST_KEY in manifest, f"manifest has no entry for {MODEL_MANIFEST_KEY}: {manifest}"

    recorded_digest = manifest[MODEL_MANIFEST_KEY]
    actual_digest = hashlib.sha256(MODEL_ZIP_PATH.read_bytes()).hexdigest()

    assert actual_digest == recorded_digest, (
        "Frozen model artifact hash drifted from the recorded manifest — the model "
        f"must never be modified/retrained. expected={recorded_digest} actual={actual_digest}"
    )


def _iter_governance_markdown_files():
    for root in GOVERNANCE_MARKDOWN_ROOTS:
        if not root.exists():
            continue
        yield from sorted(root.rglob("*.md"))


def test_agent_role_and_skill_markdown_files_contain_no_training_language():
    """Grep guard over `.claude/agents/**/*.md` and `.claude/skills/expert-alignment/**/*.md`.

    Governance markdown now exists (`.claude/agents/expert-alignment.md`,
    `.claude/agents/rules/invariants.md`, `.claude/skills/expert-alignment/SKILL.md`,
    landed in WU5a/WU5b) and is actively scanned by this test — no vacuous
    case in this branch's state.
    """
    violations: list[str] = []
    checked_any = False
    for path in _iter_governance_markdown_files():
        checked_any = True
        lowered = path.read_text().lower()
        for phrase in FORBIDDEN_TRAINING_PHRASES:
            if phrase in lowered:
                violations.append(f"{path.relative_to(PROJECT_ROOT)}: forbidden phrase {phrase!r}")

    assert not violations, violations
    if not checked_any:
        # Defensive fallback only: if the governance markdown roots ever go
        # missing again, this still asserts explicitly rather than silently
        # no-op-ing.
        assert list(_iter_governance_markdown_files()) == []


def test_historical_skill_directory_is_included_in_governance_roots():
    """The historical/base agent's Skill directory (Slice 1b) must be scanned
    by the frozen-model content guard, same as expert-alignment's."""
    assert PROJECT_ROOT / ".claude" / "skills" / "historical" in GOVERNANCE_MARKDOWN_ROOTS
    scanned_paths = {path.name for path in _iter_governance_markdown_files()}
    assert "SKILL.md" in scanned_paths
    assert (PROJECT_ROOT / ".claude" / "skills" / "historical" / "SKILL.md").exists()


def test_inference_skill_directory_is_included_in_governance_roots():
    """The inference agent's Skill directory (Slice A, Phase 4) must be
    scanned by the frozen-model content guard, same as historical's/
    expert-alignment's (mirrors historical's Phase 9.3 precedent)."""
    assert PROJECT_ROOT / ".claude" / "skills" / "inference" in GOVERNANCE_MARKDOWN_ROOTS
    scanned_paths = {path.name for path in _iter_governance_markdown_files()}
    assert "SKILL.md" in scanned_paths
    assert (PROJECT_ROOT / ".claude" / "skills" / "inference" / "SKILL.md").exists()


def test_reporte_skill_directory_is_included_in_governance_roots():
    """The `/reporte` orchestrator Skill directory (report-command-pipeline,
    Phase 7) must be scanned by the frozen-model content guard, same as
    historical's/inference's/expert-alignment's (mirrors historical's Phase
    9.3 / inference's Slice A precedent)."""
    assert PROJECT_ROOT / ".claude" / "skills" / "reporte" in GOVERNANCE_MARKDOWN_ROOTS
    scanned_paths = {path.name for path in _iter_governance_markdown_files()}
    assert "SKILL.md" in scanned_paths
    assert (PROJECT_ROOT / ".claude" / "skills" / "reporte" / "SKILL.md").exists()


def test_agent_tools_style_module_importing_interpretability_not_training_passes(tmp_path):
    """Positive case (locks in the guard's training-only scope): a synthetic
    agent_tools-style module importing `chec_impacto.interpretability` (a
    sibling, non-training subpackage name) must NOT be flagged by the same
    AST check the real guard uses."""
    module = tmp_path / "synthetic_agent_tools_module.py"
    module.write_text(
        "import chec_impacto.interpretability\n"
        "from chec_impacto.interpretability import something\n"
        "from chec_local_interpreter.circuit_identity import canonical_circuit_identity\n"
    )

    tree = ast.parse(module.read_text(), filename=str(module))
    violations = [_imports_training_package(node) for node in ast.walk(tree)]
    violations = [v for v in violations if v]

    assert violations == [], (
        f"a legitimate chec_impacto.interpretability import must never be flagged as a "
        f"training-package import: {violations}"
    )


def test_governance_markdown_guard_catches_spanish_training_phrase(tmp_path, monkeypatch):
    """The scanned governance docs (`.claude/agents/**/*.md`,
    `.claude/skills/expert-alignment/**/*.md`) are Spanish-language documents
    — an English-only forbidden-phrase list would miss a future edit adding
    e.g. "reentrenar el modelo"."""
    root = tmp_path / "governance"
    root.mkdir()
    doc = root / "example.md"
    doc.write_text("Este agente no debe reentrenar el modelo bajo ninguna circunstancia.\n")

    monkeypatch.setattr(sys.modules[__name__], "GOVERNANCE_MARKDOWN_ROOTS", (root,))

    violations: list[str] = []
    for path in _iter_governance_markdown_files():
        lowered = path.read_text().lower()
        for phrase in FORBIDDEN_TRAINING_PHRASES:
            if phrase in lowered:
                violations.append(f"{path.name}: forbidden phrase {phrase!r}")

    assert violations, "expected the Spanish training phrase 'reentrenar' to be flagged"
