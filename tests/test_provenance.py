from __future__ import annotations

import copy

from chec_local_interpreter.expert_alignment import (
    EXPERT_ALIGNMENT_AGENT_ID,
    EXPERT_ALIGNMENT_PROVENANCE_RULES,
    EXPERT_ALIGNMENT_REQUIRED_KEYS,
    PRIOR_REPORT_PDF_ROW_INDEX_OFFSET,
    validar_provenance_expert_alignment,
    validar_respuesta_expert_alignment,
)


def _context() -> dict:
    return {
        "periodo_informe": {"inicio": "2026-01-01", "fin": "2026-01-31"},
        "fechas_informe": [
            {"source": "critical_point", "fecha_inicio": "2026-01-10", "fecha_fin": "2026-01-10"}
        ],
        "llm1_analysis": {},
        "llm2_inference_analysis": {},
        "variables_modelo_predictivo": ["CNT_TRF"],
        "pdf_expert_matches": [
            {
                "Circuito": "DON23L13",
                "Fecha inicio": "2026-01-09",
                "Fecha fin": "2026-01-11",
                "Análisis": "UITI_VANO alto",
                "Evidencia": "Evidencia experta verificable",
                "pdf_row_index": 3,
            }
        ],
    }


def _data_with_provenance() -> dict:
    return {
        "contexto": {"circuito": "DON23L13", "periodo": {"inicio": "2026-01-01", "fin": "2026-01-31"}},
        "coincidencias": [
            {
                "tema": "UITI_VANO alto",
                "fuentes": ["Agente predictivo"],
                "explicacion": "Coinciden temporalmente.",
                "provenance": {
                    "data_ref": ["2026-01-10", "CNT_TRF", "pdf_row_index:3"],
                    "agent": "expert-alignment",
                    "rule": "02_predictive_variable_prioritization",
                },
            }
        ],
        "diferencias": [],
        "hallazgos_expertos_no_cubiertos": [],
        "hallazgos_modelo_no_respaldados_por_pdf": [],
        "variables_a_priorizar": [
            {
                "variable": "CNT_TRF",
                "prioridad": "alta",
                "fuentes_que_la_respaldan": ["Agente predictivo"],
                "justificacion": "Aparece en las fuentes comparadas.",
                "tipo_de_validacion_sugerida": "Revisar eventos fuente.",
                "provenance": {
                    "data_ref": ["CNT_TRF"],
                    "agent": "expert-alignment",
                    "rule": "02_predictive_variable_prioritization",
                },
            }
        ],
        "sintesis_final": "La comparación es consistente y requiere validación operacional.",
    }


def test_provenance_rule_allow_list_is_hermetic_and_matches_known_playbooks():
    # Hermetic: asserted against a small in-module constant, not a file read.
    assert EXPERT_ALIGNMENT_PROVENANCE_RULES == {
        "01_pdf_report_comparison",
        "02_predictive_variable_prioritization",
        "03_graph_context_for_alignment",
        "04_prior_report_continuity",
    }
    assert EXPERT_ALIGNMENT_AGENT_ID == "expert-alignment"


def test_validar_provenance_passes_when_every_data_ref_resolves():
    context = _context()
    data = _data_with_provenance()
    result = validar_provenance_expert_alignment(data, context)
    assert result["ok"], result["errors"]
    assert result["errors"] == []


def test_validar_provenance_fails_on_unknown_date():
    context = _context()
    data = _data_with_provenance()
    data["coincidencias"][0]["provenance"]["data_ref"] = ["2099-12-31"]

    result = validar_provenance_expert_alignment(data, context)

    assert not result["ok"]
    assert any("2099-12-31" in error for error in result["errors"])


def test_validar_provenance_fails_on_unknown_variable():
    context = _context()
    data = _data_with_provenance()
    data["variables_a_priorizar"][0]["provenance"]["data_ref"] = ["VARIABLE_INEXISTENTE"]

    result = validar_provenance_expert_alignment(data, context)

    assert not result["ok"]
    assert any("VARIABLE_INEXISTENTE" in error for error in result["errors"])


def test_validar_provenance_fails_on_unknown_pdf_row_index():
    context = _context()
    data = _data_with_provenance()
    data["coincidencias"][0]["provenance"]["data_ref"] = ["pdf_row_index:99"]

    result = validar_provenance_expert_alignment(data, context)

    assert not result["ok"]
    assert any("pdf_row_index:99" in error for error in result["errors"])


def test_validar_provenance_fails_when_agent_does_not_match_producing_role():
    context = _context()
    data = _data_with_provenance()
    data["coincidencias"][0]["provenance"]["agent"] = "some-other-agent"

    result = validar_provenance_expert_alignment(data, context)

    assert not result["ok"]
    assert any("agent" in error.lower() for error in result["errors"])


def test_validar_provenance_fails_when_rule_is_not_in_the_allow_list():
    context = _context()
    data = _data_with_provenance()
    data["coincidencias"][0]["provenance"]["rule"] = "not-a-real-rule"

    result = validar_provenance_expert_alignment(data, context)

    assert not result["ok"]
    assert any("rule" in error.lower() for error in result["errors"])


def test_provenance_keys_are_additive_and_optional():
    """An existing fixture without provenance keys must still validate exactly as before."""
    context = {
        "periodo_informe": {"inicio": "2026-01-01", "fin": "2026-01-31"},
        "fechas_informe": [{"source": "critical_point", "fecha_inicio": "2026-01-10", "fecha_fin": "2026-01-10"}],
        "llm1_analysis": {"period_synthesis": "UITI_VANO y NR_T aparecen en el periodo."},
        "llm2_inference_analysis": {"escenarios": [{"top_variables": ["UITI_VANO"]}]},
        "variables_modelo_predictivo": ["NR_T"],
        "pdf_expert_matches": [
            {
                "Circuito": "DON23L13",
                "Fecha inicio": "2026-01-09",
                "Fecha fin": "2026-01-11",
                "Análisis": "UITI_VANO alto",
                "Evidencia": "Evidencia experta verificable",
            }
        ],
    }
    output = {
        "contexto": {"circuito": "DON23L13", "periodo": {"inicio": "2026-01-01", "fin": "2026-01-31"}, "n_filas_expertas_comparadas": 1},
        "coincidencias": [
            {
                "tema": "UITI_VANO alto",
                "fechas_relacionadas": ["2026-01-10"],
                "fuentes": ["LLM1", "PDF_EXPERTO"],
                "explicacion": "Coinciden temporalmente.",
                "evidencia_pdf": "Evidencia experta verificable",
            }
        ],
        "diferencias": [],
        "hallazgos_expertos_no_cubiertos": [],
        "hallazgos_modelo_no_respaldados_por_pdf": [],
        "variables_a_priorizar": [
            {
                "variable": "NR_T",
                "prioridad": "alta",
                "fuentes_que_la_respaldan": ["LLM1", "PDF_EXPERTO"],
                "justificacion": "Aparece en las fuentes comparadas.",
                "tipo_de_validacion_sugerida": "Revisar eventos fuente.",
            }
        ],
        "sintesis_final": "La comparación es consistente y requiere validación operacional.",
    }
    import json

    result = validar_respuesta_expert_alignment(json.dumps(output, ensure_ascii=False), context)
    assert result["ok"], result["errors"]
    assert all(key in result["data"] for key in EXPERT_ALIGNMENT_REQUIRED_KEYS)

    # No item in the whole response carries a provenance key: the additive
    # validator must find nothing to complain about.
    provenance_result = validar_provenance_expert_alignment(result["data"], context)
    assert provenance_result["ok"], provenance_result["errors"]
    assert provenance_result["errors"] == []


def test_validar_provenance_ignores_items_without_provenance_key():
    context = _context()
    data = _data_with_provenance()
    # Drop provenance from one of the two provenance-bearing items; the item
    # without it must not be flagged (additive/optional per item).
    del data["variables_a_priorizar"][0]["provenance"]

    result = validar_provenance_expert_alignment(data, context)

    assert result["ok"], result["errors"]


def test_validar_provenance_rejects_fabricated_variable_when_no_predictive_variables_declared():
    """Fail-closed: when `variables_modelo_predictivo` is empty, the loose
    free-text scraper used elsewhere (prompt-shaping, `_allowed_variables`)
    must NOT be used to accept a variable-shaped `data_ref` — otherwise any
    incidental uppercase-looking word already present in unrelated context
    prose (e.g. "VERIFICABLE", scraped straight out of the fixture's own
    `Evidencia` text) would defeat the traceability guarantee. Verified
    reproduction: `_allowed_variables(context)` with an empty
    `variables_modelo_predictivo` includes "VERIFICABLE" today."""
    context = _context()
    context["variables_modelo_predictivo"] = []
    data = _data_with_provenance()
    data["variables_a_priorizar"][0]["provenance"]["data_ref"] = ["VERIFICABLE"]

    result = validar_provenance_expert_alignment(data, context)

    assert not result["ok"]
    assert any("VERIFICABLE" in error for error in result["errors"])


def test_validar_provenance_parity_preserved_when_no_predictive_variables_and_no_variable_refs():
    """Empty `variables_modelo_predictivo` with zero variable-shaped data_refs
    (only dates/pdf_row_index refs) must still pass — parity with prior
    behavior when there is nothing variable-shaped to reject."""
    context = _context()
    context["variables_modelo_predictivo"] = []
    data = _data_with_provenance()
    data["coincidencias"][0]["provenance"]["data_ref"] = ["2026-01-10", "pdf_row_index:3"]
    del data["variables_a_priorizar"][0]["provenance"]

    result = validar_provenance_expert_alignment(data, context)

    assert result["ok"], result["errors"]


def _context_with_prior_report_index() -> dict:
    context = _context()
    context["pdf_expert_matches"].append(
        {
            "Circuito": "DON23L13",
            "Fecha inicio": "2026-01-01",
            "Fecha fin": "2026-01-10",
            "Análisis": "Síntesis previa",
            "Evidencia": "Evidencia previa",
            "pdf_row_index": PRIOR_REPORT_PDF_ROW_INDEX_OFFSET,
            "source_kind": "prior_report",
            "confidence": "baja",
        }
    )
    return context


def test_validar_provenance_rejects_offset_pdf_row_index_under_real_pdf_rule():
    """Judgment Day Round 1 WARNING(real) fix: an offset-range pdf_row_index
    (prior-report continuity row) must never be citable under a real-PDF
    rule id -- only under `04_prior_report_continuity`."""
    context = _context_with_prior_report_index()
    data = _data_with_provenance()
    data["coincidencias"][0]["provenance"]["rule"] = "01_pdf_report_comparison"
    data["coincidencias"][0]["provenance"]["data_ref"] = [
        f"pdf_row_index:{PRIOR_REPORT_PDF_ROW_INDEX_OFFSET}"
    ]

    result = validar_provenance_expert_alignment(data, context)

    assert not result["ok"]
    assert any("04_prior_report_continuity" in error for error in result["errors"])


def test_validar_provenance_rejects_real_pdf_row_index_under_prior_report_rule():
    """Judgment Day Round 1 WARNING(real) fix: a real-PDF-range pdf_row_index
    must never be citable under rule `04_prior_report_continuity`."""
    context = _context()
    data = _data_with_provenance()
    data["coincidencias"][0]["provenance"]["rule"] = "04_prior_report_continuity"
    data["coincidencias"][0]["provenance"]["data_ref"] = ["pdf_row_index:3"]

    result = validar_provenance_expert_alignment(data, context)

    assert not result["ok"]
    assert any("04_prior_report_continuity" in error for error in result["errors"])


def test_validar_provenance_accepts_correct_offset_index_and_rule_04_pairing():
    context = _context_with_prior_report_index()
    data = _data_with_provenance()
    data["coincidencias"][0]["provenance"]["rule"] = "04_prior_report_continuity"
    data["coincidencias"][0]["provenance"]["data_ref"] = [
        f"pdf_row_index:{PRIOR_REPORT_PDF_ROW_INDEX_OFFSET}"
    ]

    result = validar_provenance_expert_alignment(data, context)

    assert result["ok"], result["errors"]


def test_validar_provenance_accepts_correct_real_index_and_real_pdf_rule_pairing():
    context = _context()
    data = _data_with_provenance()
    data["coincidencias"][0]["provenance"]["rule"] = "01_pdf_report_comparison"
    data["coincidencias"][0]["provenance"]["data_ref"] = ["pdf_row_index:3"]

    result = validar_provenance_expert_alignment(data, context)

    assert result["ok"], result["errors"]


def test_validar_provenance_accepts_combined_real_and_offset_citation_as_reinforcement():
    """Judgment Day Round 2 CRITICAL fix: the feature's own documented design
    (`.claude/skills/expert-alignment/prompt/04_prior_report_continuity.md`)
    explicitly invites a SINGLE claim to cite BOTH a real-PDF row (Modelo
    Experto backing) AND a prior-report offset row (reinforcement) together
    in one `data_ref` list. Since the claim has other (real-PDF) backing, it
    is fundamentally a real-PDF-rule claim reinforced by prior-report
    evidence, so `01_pdf_report_comparison` is the reasonable rule choice --
    this combined citation must NOT be rejected."""
    context = _context_with_prior_report_index()
    data = _data_with_provenance()
    data["coincidencias"][0]["provenance"]["rule"] = "01_pdf_report_comparison"
    data["coincidencias"][0]["provenance"]["data_ref"] = [
        "pdf_row_index:3",
        f"pdf_row_index:{PRIOR_REPORT_PDF_ROW_INDEX_OFFSET}",
    ]

    result = validar_provenance_expert_alignment(data, context)

    assert result["ok"], result["errors"]


def test_validar_provenance_deepcopy_is_side_effect_free():
    """Guard against accidental mutation of the input data during validation."""
    context = _context()
    data = _data_with_provenance()
    snapshot = copy.deepcopy(data)

    validar_provenance_expert_alignment(data, context)

    assert data == snapshot
