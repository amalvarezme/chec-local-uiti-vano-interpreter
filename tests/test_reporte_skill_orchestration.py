"""Structural guard: `.claude/skills/reporte/SKILL.md` must declare
`historical`, `inference`, and `auto-simulator` (steps 3/4/4b) as
independent, parallel-eligible calls, while still preserving the
`expert-alignment` (step 5/6) dependency on both `historical` and
`inference` completing first.

This is a documentation/runbook change (SDD `reporte-perf-optimization`
item 2, Report Orchestration Concurrency): the three calls write disjoint
files and share no mutable state, so a runtime that supports issuing
independent tool/Skill calls in one turn (e.g. Claude Code) MAY run them in
parallel, while a runtime with unconfirmed concurrency (e.g. OpenCode)
degrades safely to sequential-in-any-order. Nothing here asserts true
concurrency happened -- SKILL.md is a runbook read by an LLM orchestrator,
not executable code -- so this test only checks the declarative text is
present and internally consistent.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTE_SKILL_PATH = PROJECT_ROOT / ".claude" / "skills" / "reporte" / "SKILL.md"


def _run_sequence_text() -> str:
    text = REPORTE_SKILL_PATH.read_text(encoding="utf-8")
    match = re.search(r"^## Run sequence$(?P<body>.*?)^## ", text, re.MULTILINE | re.DOTALL)
    assert match is not None, "SKILL.md must have a '## Run sequence' section"
    return match.group("body")


def test_skill_declares_historical_inference_auto_simulator_independent():
    body = _run_sequence_text()

    independence_markers = ["independent", "parallel"]
    assert all(marker in body.lower() for marker in independence_markers), (
        "Run sequence must declare historical/inference/auto-simulator as independent "
        "and parallel-eligible where the runtime supports it"
    )

    assert "historical" in body and "inference" in body and "auto-simulator" in body


def test_skill_does_not_require_true_concurrency():
    body = _run_sequence_text()

    # Must degrade safely: sequential execution (in any order) must remain an
    # explicitly sanctioned outcome, not just an implicit fallback.
    assert re.search(r"sequential(ly)?", body, re.IGNORECASE), (
        "Run sequence must explicitly allow sequential execution as a safe degrade path"
    )


def test_skill_preserves_expert_alignment_dependency_on_both_stages():
    body = _run_sequence_text()

    # Step 5 (prepare_expert_alignment) / step 6 (expert-alignment) must still
    # require BOTH historical and inference to have completed first.
    step5_match = re.search(r"\*\*`prepare_expert_alignment`\*\*.*?(?=\n\d)", body, re.DOTALL)
    assert step5_match is not None, "Step 5 (prepare_expert_alignment) must still be documented"
    step5_text = step5_match.group(0)
    assert "historical" in step5_text and "inference" in step5_text
