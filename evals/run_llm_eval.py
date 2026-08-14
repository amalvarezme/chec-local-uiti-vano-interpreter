from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from chec_local_interpreter.expert_alignment import (
    validar_provenance_expert_alignment,
    validar_respuesta_expert_alignment,
)
from chec_local_interpreter.inference_validation import (
    validar_provenance_inferencia,
    validar_respuesta_inferencia_strict,
)
from chec_local_interpreter.llm_contracts import PROMPT_VERSION, load_output_schema, render_prompt
from chec_local_interpreter.llm_validation import validar_provenance_base, validate_llm_response


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _valid_output(context: dict) -> dict:
    ventana = context["ventanas"][0]
    return {
        "source": "llm",
        "prompt_version": PROMPT_VERSION,
        "headline": "Concentracion de UITI_VANO en el periodo analizado",
        "section_title": "Hallazgos del periodo",
        "executive_summary": [
            "La evidencia tabular muestra que el comportamiento del periodo se concentra en las ventanas estudiadas."
        ],
        "key_findings": [
            {
                "title": "Ventana dominante del periodo",
                "text": "La ventana estudiada concentra el mayor aporte de UITI_VANO del periodo.",
                "evidence": [
                    {
                        "date": ventana["desde"],
                        "ventana": ventana["w"],
                        "variable": "UITI_VANO",
                        "summary": "La ventana concentra el aporte de UITI_VANO del periodo.",
                    }
                ],
                "referenced_events": [
                    {
                        "date": ventana["desde"],
                        "ventana": ventana["w"],
                        "indicator_value": float(ventana["uv"]),
                        "selection_reason": "Ventana estudiada por el informe.",
                    }
                ],
                "variable_groups_used": ["Evento/Impacto"],
                "confidence": "media",
            }
        ],
        "circuit_characterization": {
            "text": "Characterization text.",
            "ventanas_estudiadas": ["V1"],
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


def _valid_historical_output(context: dict) -> dict:
    """Synthetic, offline historical/base agent response: the 10 required base
    keys plus a resolving `provenance` object on its one `key_finding`, giving
    the historical agent an eval gate parallel to the base `_valid_output` and
    the expert-alignment `_valid_expert_alignment_output` above — no API
    call, no real `claude` subprocess, everything checked through the same
    code-level validators the L2 CLI's `validate` verb runs (two-stage:
    schema/guardrails then provenance)."""
    ventana = context["ventanas"][0]
    return {
        "source": "llm",
        "prompt_version": PROMPT_VERSION,
        "headline": "Concentracion de UITI_VANO en el periodo analizado",
        "section_title": "Hallazgos del periodo",
        "executive_summary": [
            "La evidencia tabular muestra que el comportamiento del periodo se concentra en la ventana estudiada."
        ],
        "key_findings": [
            {
                "title": "Ventana dominante del periodo",
                "text": "La ventana estudiada concentra el mayor aporte de UITI_VANO del periodo.",
                "evidence": [
                    {
                        "date": ventana["desde"],
                        "ventana": ventana["w"],
                        "variable": "UITI_VANO",
                        "summary": "La ventana concentra el aporte de UITI_VANO del periodo.",
                    }
                ],
                "referenced_events": [],
                "variable_groups_used": ["Evento/Impacto"],
                "confidence": "media",
                "provenance": {
                    "data_ref": [ventana["desde"], ventana["w"], "UITI_VANO"],
                    "agent": "historical",
                    "rule": "03_uiti_vano_behavior_explainer",
                },
            }
        ],
        "circuit_characterization": {
            "text": "Characterization text.",
            "ventanas_estudiadas": ["V1"],
            "top_3_modes_related": ["Mode1"],
            "probable_justifications_rules": ["Rule1"],
        },
        "period_synthesis": "El periodo se explica principalmente por la concentracion de UITI_VANO en la ventana estudiada.",
        "data_gaps": [],
        "limitations": ["El analisis usa solo datos estructurados disponibles en la ventana seleccionada."],
        "recommended_actions": ["Revisar las filas fuente asociadas a la ventana estudiada."],
    }


def _valid_inference_output(context: dict) -> dict:
    """Synthetic, offline inference response: the 9 required keys of
    `inference.output_schema.json` plus a resolving `provenance` on both sections
    the validator inspects (`escenarios` and `discusion_grafos`), giving the MIL
    interpretation role the same eval gate the other two already had — no API
    call, everything checked through the two code-level validators the L2 CLI's
    `validate` verb runs (strict schema+guardrails, then provenance).

    Every citable token is READ from the context instead of hard-coded: the
    scenario name, the window and the variable. A literal here would keep passing
    after `construir_contexto_inferencia_mil` renames any of the three, which is
    exactly the drift this eval exists to catch.

    The wording avoids attributing the EVENT COUNT to the model on purpose. The
    MIL predicts `uiti_acumulado`; the count is an axis of the KMeans space that
    fixes the class, and `errores_de_metrica` rejects any sentence that hangs one
    on the other — a plausible sentence no reader could tell apart from a correct
    one.
    """
    escenario = context["escenarios"][0]
    nombre = escenario["nombre"]
    ventana = escenario["ventana"]
    variable = context["features"][0]
    return {
        "contexto": {
            "circuito": context["circuito_interes"],
            "periodo": {"inicio": context["fecha_inicio"], "fin": context["fecha_fin"]},
            "modelo": context["modelo"],
        },
        "entregables": {"grafos_html": []},
        "escenarios": [
            {
                "nombre": nombre,
                "interpretacion": (
                    f"En la ventana {ventana}, {variable} es la palanca que mas baja el "
                    f"{context['metrica']} estimado de las bolsas del circuito."
                ),
                "provenance": {
                    "data_ref": [variable, ventana, nombre],
                    "agent": "inference",
                    "rule": "02_window_scenario_interpreter",
                },
            }
        ],
        "discusion_grafos": [
            {
                "seccion": ventana,
                "lectura": (
                    f"El grafo diferencia de la ventana {ventana} mueve las aristas que "
                    f"salen de {variable} al simular la intervencion."
                ),
                "provenance": {
                    "data_ref": [ventana],
                    "agent": "inference",
                    "rule": "04_graph_connectivity_guardrails",
                },
            }
        ],
        "coherencia_grafo_modelo": [
            f"La relevancia de {variable} es coherente con las relaciones que el grafo "
            f"del propio modelo conserva para esa variable."
        ],
        "hallazgos": [
            f"{variable} concentra la mayor caida del {context['metrica']} estimado en "
            f"los vanos criticos de la ventana {ventana}."
        ],
        "limitaciones": [
            "La relevancia explica el comportamiento del modelo sobre la bolsa "
            "(vano, ventana), no una relacion causal.",
        ],
        "inferencias_predictivas": [
            {
                "horizonte": "periodo analizado",
                "riesgo": "moderado",
                "justificacion_modelo": (
                    f"El modelo asocia el {context['metrica']} de las bolsas criticas "
                    f"con el nivel de {variable}."
                ),
            }
        ],
        "hipotesis_modelo_predictivo": {
            "ventanas_estudiadas": [
                f"La ventana {ventana} sostiene la lectura del periodo."
            ],
            "plan_de_intervencion": [
                f"Verificar {variable} en los vanos que el diagnostico senala."
            ],
        },
    }


def _assert_prompt_contents(prompt: str, context: dict, schema: dict) -> list[str]:
    errors: list[str] = []
    required = [
        "UITI_VANO",
        "included_steps",
        "excluded_steps",
        "RAG",
        "bitacoras",
        "normativa",
        "modelo_predictivo",
        "mascaras_relevancia",
        "what_if",
        "reporte_final",
        "uiti-vano-explanation-v1",
        "ventanas",
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

    for path in sorted(fixture_dir.glob("synthetic_historical_context_*.json")):
        historical_context = _load_json(path)
        historical_response = json.dumps(_valid_historical_output(historical_context), ensure_ascii=False)
        schema_result = validate_llm_response(historical_response, historical_context, schema)
        if not schema_result.ok:
            errors.append(
                f"{path.name}: valid synthetic historical output failed schema/guardrail validation: {schema_result.errors}"
            )
            continue
        provenance_result = validar_provenance_base(schema_result.data, historical_context)
        if not provenance_result["ok"]:
            errors.append(
                f"{path.name}: valid synthetic historical output failed provenance validation: {provenance_result['errors']}"
            )

    for path in sorted(fixture_dir.glob("synthetic_inference_context_*.json")):
        inference_context = _load_json(path)
        inference_response = json.dumps(_valid_inference_output(inference_context), ensure_ascii=False)
        schema_result = validar_respuesta_inferencia_strict(inference_response, inference_context)
        if not schema_result["ok"]:
            errors.append(
                f"{path.name}: valid synthetic inference output failed schema/guardrail validation: {schema_result['errors']}"
            )
            continue
        provenance_result = validar_provenance_inferencia(schema_result["data"], inference_context)
        if not provenance_result["ok"]:
            errors.append(
                f"{path.name}: valid synthetic inference output failed provenance validation: {provenance_result['errors']}"
            )

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("Offline LLM evals passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
