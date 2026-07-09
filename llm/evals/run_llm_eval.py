from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))

from chec_local_interpreter.expert_alignment import (
    validar_provenance_expert_alignment,
    validar_respuesta_expert_alignment,
)
from chec_local_interpreter.llm_contracts import PROMPT_VERSION, load_output_schema, render_prompt
from chec_local_interpreter.llm_validation import validate_llm_response


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _valid_output(context: dict) -> dict:
    point = context["critical_points"][0]
    return {
        "source": "llm",
        "prompt_version": PROMPT_VERSION,
        "headline": "Concentracion de UITI_VANO en el periodo analizado",
        "section_title": "Hallazgos del periodo",
        "executive_summary": [
            "La evidencia tabular muestra que el comportamiento del periodo se concentra en los puntos criticos entregados."
        ],
        "key_findings": [
            {
                "title": "Dia dominante del periodo",
                "text": "El punto critico entregado concentra el mayor aporte de UITI_VANO dentro de la ventana.",
                "evidence": [
                    {
                        "date": point["fecha_dia"],
                        "critical_point_id": point["critical_point_id"],
                        "variable": "UITI_VANO",
                        "summary": point["selection_reason"],
                    }
                ],
                "referenced_events": [
                    {
                        "date": point["fecha_dia"],
                        "critical_point_id": point["critical_point_id"],
                        "indicator_value": float(point["metrics"]["UITI_VANO"]),
                        "selection_reason": point["selection_reason"],
                    }
                ],
                "variable_groups_used": ["Evento/Impacto"],
                "confidence": "media",
            }
        ],
        "circuit_characterization": {
            "text": "Characterization text.",
            "p97_vanos_uiti_vano": ["V1"],
            "p97_vanos_eventos": ["V2"],
            "top_3_modes_related": ["Mode1"],
            "probable_justifications_rules": ["Rule1"]
        },
        "period_synthesis": "El periodo se explica principalmente por la concentracion de UITI_VANO en los puntos ya detectados por el codigo.",
        "data_gaps": ["No todas las variables opcionales estan disponibles en esta version local."]
        if context["metadata"].get("unavailable_optional_columns")
        else [],
        "limitations": ["El analisis usa solo datos estructurados disponibles en la ventana seleccionada."],
        "recommended_actions": ["Revisar las filas fuente asociadas a los puntos criticos detectados."],
    }


def _valid_expert_alignment_output(context: dict) -> dict:
    """Synthetic, offline expert-alignment pilot response: 7 required keys plus a
    `provenance` object on at least one item per array, giving the pilot an eval
    gate parallel to the base agent's `_valid_output` above — no API call, no
    real `claude` subprocess, everything is checked through the same code-level
    validators the L2 CLI's `validate` verb runs (WU1 schema + WU2 provenance)."""
    return {
        "contexto": {
            "circuito": context["circuito"],
            "periodo": context["periodo_informe"],
            "n_filas_expertas_comparadas": len(context.get("pdf_expert_matches", [])),
        },
        "coincidencias": [
            {
                "tema": "UITI_VANO alto",
                "fechas_relacionadas": ["2026-01-10"],
                "fuentes": ["Agente Descriptor", "Agente predictivo", "DON23L13.pdf"],
                "explicacion": "Coinciden temporalmente en el periodo evaluado.",
                "evidencia_pdf": "Evidencia experta verificable",
                "provenance": {
                    "data_ref": ["2026-01-10", "CNT_TRF", "pdf_row_index:3"],
                    "agent": "expert-alignment",
                    "rule": "02_predictive_variable_prioritization",
                },
            }
        ],
        "diferencias": [
            {
                "tema": "Énfasis distinto entre fuentes",
                "fuentes": ["Agente predictivo"],
                "explicacion": "El modelo predictivo resalta la variable con mayor peso que el análisis histórico.",
                "provenance": {
                    "data_ref": ["CNT_TRF"],
                    "agent": "expert-alignment",
                    "rule": "03_graph_context_for_alignment",
                },
            }
        ],
        "hallazgos_expertos_no_cubiertos": [],
        "hallazgos_modelo_no_respaldados_por_pdf": [],
        "variables_a_priorizar": [
            {
                "variable": "CNT_TRF",
                "prioridad": "alta",
                "fuentes_que_la_respaldan": ["Agente predictivo"],
                "justificacion": "Aparece en las señales del modelo predictivo y en la comparación.",
                "tipo_de_validacion_sugerida": "Revisar conexión en grafos y eventos fuente.",
                "provenance": {
                    "data_ref": ["CNT_TRF"],
                    "agent": "expert-alignment",
                    "rule": "02_predictive_variable_prioritization",
                },
            }
        ],
        "sintesis_final": "La comparación es consistente y requiere validación operacional adicional.",
    }


def _assert_prompt_contents(prompt: str, context: dict, schema: dict) -> list[str]:
    errors: list[str] = []
    required = [
        "UITI_VANO",
        "included_steps",
        "excluded_steps",
        "do_not_detect_new_points",
        "RAG",
        "bitacoras",
        "normativa",
        "modelo_predictivo",
        "mascaras_relevancia",
        "what_if",
        "reporte_final",
        "uiti-vano-explanation-v1",
        "critical_points",
    ]
    for item in required:
        if item not in prompt:
            errors.append(f"Prompt missing fragment: {item}")
    for circuit in context["selected_context"]["circuitos"]:
        if circuit not in prompt:
            errors.append(f"Prompt missing selected circuit: {circuit}")
    for date_key in ("start_date", "end_date"):
        if context["selected_context"][date_key] not in prompt:
            errors.append(f"Prompt missing {date_key}: {context['selected_context'][date_key]}")
    if schema.get("$id", "") not in prompt:
        errors.append("Prompt missing output schema id.")
    return errors


def main() -> int:
    schema = load_output_schema()
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    errors: list[str] = []
    for path in sorted(fixture_dir.glob("synthetic_context_*.json")):
        context = _load_json(path)
        prompt = render_prompt(
            context_json=json.dumps(context, ensure_ascii=False, indent=2),
            output_schema_json=json.dumps(schema, ensure_ascii=False, indent=2),
        )
        errors.extend(f"{path.name}: {error}" for error in _assert_prompt_contents(prompt, context, schema))
        valid = json.dumps(_valid_output(context), ensure_ascii=False)
        valid_result = validate_llm_response(valid, context, schema)
        if not valid_result.ok:
            errors.append(f"{path.name}: valid synthetic output failed: {valid_result.errors}")

    for path in sorted(fixture_dir.glob("synthetic_expert_alignment_context_*.json")):
        expert_context = _load_json(path)
        expert_response_text = json.dumps(_valid_expert_alignment_output(expert_context), ensure_ascii=False)
        schema_result = validar_respuesta_expert_alignment(expert_response_text, expert_context)
        if not schema_result["ok"]:
            errors.append(
                f"{path.name}: valid synthetic expert-alignment output failed schema validation: {schema_result['errors']}"
            )
            continue
        provenance_result = validar_provenance_expert_alignment(schema_result["data"], expert_context)
        if not provenance_result["ok"]:
            errors.append(
                f"{path.name}: valid synthetic expert-alignment output failed provenance validation: {provenance_result['errors']}"
            )

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("Offline LLM evals passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
