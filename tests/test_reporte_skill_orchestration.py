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

    # Antes se afirmaba aqui el nombre de un runtime concreto. El contrato es que el
    # total MEDIDO se use cuando el runtime lo expone, sea cual sea el runtime.
    assert "an equivalent runtime" in body or "Claude Code's `Agent` tool" in body
    assert "This is mandatory whenever the runtime exposes that" in body
    assert "do not show a `chars // 4` artifact estimate" in body


# --- Techo de concurrencia: un circuito a la vez -----------------------------
#
# El paralelismo declarado arriba es INTRA-circuito (steps 3/4). Nada de eso
# autoriza tener dos circuitos en vuelo. Se midio el costo de lo contrario el
# 2026-08-26: un fan-out de `/informe-gerencial todos` perdio 15 de 18 agentes
# vivos contra un solo tope de sesion, y el tiempo por informe dependia de
# cuantos vecinos compartian la maquina. Estas guardas fijan la regla en los
# tres runbooks para que no vuelva a diluirse en prosa.

LOTE_SKILL_PATH = PROJECT_ROOT / ".claude" / "skills" / "reporte-lote" / "SKILL.md"
GERENCIAL_SKILL_PATH = PROJECT_ROOT / ".claude" / "skills" / "informe-gerencial" / "SKILL.md"


def test_report_skill_declara_el_techo_de_un_circuito():
    """`report/SKILL.md` debe acotar el paralelismo a UN circuito, en la misma
    seccion donde lo autoriza -- si no, la regla de paralelizar se lee como
    permiso para abanicar circuitos."""
    body = _run_sequence_text()

    assert "Concurrency ceiling: one circuit at a time" in body, (
        "Run sequence must cap the parallel-dispatch rule at one circuit in flight"
    )
    assert re.search(r"never a licence to\s+have two circuits in flight", body), (
        "The ceiling must say explicitly that parallel dispatch is not a licence "
        "for two circuits at once"
    )


def test_report_skill_ya_no_normaliza_el_fan_out_entre_circuitos():
    """La prosa vieja hablaba de `multi-circuit parallel fan-out` como modo
    esperado. Mientras esa frase siga ahi, el orquestador tiene de donde
    agarrarse para abanicar."""
    text = REPORTE_SKILL_PATH.read_text(encoding="utf-8")

    for frase in ("multi-circuit parallel fan-out", "multi-circuit parallel\ndispatch"):
        assert frase not in text, (
            f"`report/SKILL.md` still normalizes cross-circuit concurrency: {frase!r}"
        )


def test_los_dos_comandos_de_lote_fijan_un_circuito_a_la_vez():
    """`/reporte-lote` e `/informe-gerencial` son los dos unicos que iteran
    circuitos. Los dos deben llevar la regla dura, no solo uno."""
    for path in (LOTE_SKILL_PATH, GERENCIAL_SKILL_PATH):
        text = path.read_text(encoding="utf-8")

        assert "One circuit at a time (hard rule, not negotiable)" in text, (
            f"{path.name} must carry the hard one-circuit-at-a-time rule"
        )
        assert re.search(r"Never start ANY work for circuit N\+1", text), (
            f"{path.name} must forbid starting circuit N+1 before N resolves"
        )
        assert "dispatching several circuits together" in text, (
            f"{path.name} must forbid dispatching several circuits together"
        )
