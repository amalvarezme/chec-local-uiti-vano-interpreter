"""Structural guard: `.claude/skills/report/SKILL.md` must declare
`historical`, `inference`, and `auto-simulator` (steps 3/4/4b) as
independent, parallel-eligible calls, while still preserving the
`expert-alignment` (step 5/6) dependency on both `historical` and
`inference` completing first.

This is a documentation/runbook change (SDD `reporte-perf-optimization`
item 2, Report Orchestration Concurrency): the three calls write disjoint
files and share no mutable state, so a runtime that supports issuing
independent tool/Skill calls in one turn (e.g. Claude Code) MAY run them in
parallel, while a runtime with unconfirmed concurrency degrades safely to
sequential-in-any-order. Nothing here asserts true
concurrency happened -- SKILL.md is a runbook read by an LLM orchestrator,
not executable code -- so this test only checks the declarative text is
present and internally consistent.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTE_SKILL_PATH = PROJECT_ROOT / ".claude" / "skills" / "report" / "SKILL.md"


def _run_sequence_text() -> str:
    text = REPORTE_SKILL_PATH.read_text(encoding="utf-8")
    match = re.search(r"^## Run sequence$(?P<body>.*?)^## ", text, re.MULTILINE | re.DOTALL)
    assert match is not None, "SKILL.md must have a '## Run sequence' section"
    return match.group("body")


def test_skill_declares_historical_and_inference_independent():
    """El flujo pasa de cuatro agentes a tres: el `auto-simulator` se jubilo con
    MGCECDL, porque su barrido min-max es lo que la relevancia MIL sustituyo. Lo que
    esta prueba sigue fijando es que los dos que quedan antes de expert-alignment
    puedan correr en paralelo -- es de donde sale el tiempo de una corrida."""
    body = _run_sequence_text()

    independence_markers = ["independent", "parallel"]
    assert all(marker in body.lower() for marker in independence_markers), (
        "Run sequence must declare historical/inference as independent "
        "and parallel-eligible where the runtime supports it"
    )

    assert "historical" in body and "inference" in body
    assert "auto-simulator" not in body, "el agente jubilado no puede volver al flujo"


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


def test_skill_forbids_ambiguous_generic_worker_dispatch():
    body = _run_sequence_text()

    assert "Role-dispatch safety contract" in body
    assert "exactly one role" in body
    assert "never\nlaunch multiple identical generic workers" in body
    assert "If any worker asks which role it has" in body
    assert "verify that the selected agent can run" in body
    assert "A read-only/research-only worker cannot author a" in body
    assert "historical.out.json" in body and "inference.out.json" in body
    assert "report the stalled role" in body


def test_skill_requires_measured_subagent_totals_when_runtime_exposes_them():
    body = _run_sequence_text()

    assert "Pi's subagent runner" in body
    assert "This is mandatory whenever the runtime exposes that" in body
    assert "do not show a `chars // 4` artifact estimate" in body
