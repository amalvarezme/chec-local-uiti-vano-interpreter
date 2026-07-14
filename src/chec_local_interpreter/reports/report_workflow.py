"""Workflow helpers shared by report-generation notebooks."""

from __future__ import annotations

import json
from typing import Any, Callable

import pandas as pd

from chec_local_interpreter.llm.validation import parse_llm_json


def select_rows_by_percentile(tabla: pd.DataFrame, metric_col: str, percentile: float) -> tuple[pd.DataFrame, float]:
    """Select rows whose metric is greater than or equal to the configured percentile."""
    if tabla.empty:
        return tabla.copy(), float("nan")
    p = min(max(float(percentile), 0.0), 100.0)
    values = pd.to_numeric(tabla[metric_col], errors="coerce").fillna(0.0)
    threshold = float(values.quantile(p / 100.0))
    selected = tabla[values >= threshold].copy()
    sort_cols = [metric_col]
    ascending = [False]
    if "UITI_VANO_PROM" in selected.columns:
        sort_cols.append("UITI_VANO_PROM")
        ascending.append(False)
    selected = selected.sort_values(sort_cols, ascending=ascending, kind="stable")
    return selected.reset_index(drop=True), threshold


def top_percentile_label(percentile: float) -> str:
    """Return a compact percentile label such as P95."""
    p = int(percentile) if float(percentile).is_integer() else percentile
    return f"P{p}"


def run_inference_scenario(
    *,
    key: str,
    nombre: str,
    criterio: str,
    tabla_top: pd.DataFrame,
    eventos_escenario: pd.DataFrame,
    graph_output_name: str,
    results_store: dict[str, Any],
    plot_builder: Callable[..., dict[str, Any]],
    context_builder: Callable[..., dict[str, Any]],
    plot_kwargs: dict[str, Any],
    context_kwargs: dict[str, Any],
    fechas_interes=None,
) -> dict[str, Any]:
    """Run one inference scenario and store its plotting/context result."""
    result = plot_builder(eventos_escenario, nombre, graph_output_name=graph_output_name, **plot_kwargs)
    result["contexto"] = context_builder(
        nombre=nombre,
        criterio=criterio,
        resultado=result,
        tabla_top=tabla_top,
        fechas_interes=fechas_interes,
        **context_kwargs,
    )
    results_store[key] = result
    return result


def compact_inference_context(context_package: dict[str, Any]) -> dict[str, Any]:
    """Build a compact inference context for regeneration prompts."""
    scenarios = []
    for item in context_package.get("escenarios", []):
        if not isinstance(item, dict):
            continue
        scenarios.append(
            {
                "nombre": item.get("nombre"),
                "criterio": item.get("criterio"),
                "n_vanos_efectivo": item.get("n_vanos_efectivo"),
                "n_eventos": item.get("n_eventos"),
                "top_variables": item.get("top_variables", [])[:5],
                "modos": item.get("modos", [])[:4],
            }
        )
    graph_sections = []
    for graph in context_package.get("graph_html_paths", []):
        text = str(graph.get("escenario") or graph.get("nombre") or graph.get("path") or "").lower() if isinstance(graph, dict) else ""
        if any(token in text for token in ["critico", "crítico", "punto", "fecha"]):
            section = "puntos_criticos"
        elif any(token in text for token in ["periodo", "período", "completo", "general"]):
            section = "periodo_completo"
        else:
            section = ""
        if section and section not in graph_sections:
            graph_sections.append(section)
    return {
        "contexto": context_package.get("contexto", {}),
        "escenarios": scenarios,
        "graph_sections_requeridas": graph_sections,
        "nota_grafos": "No copies rutas largas en la salida; usa path vacío y discute secciones requeridas.",
    }


def build_inference_regeneration_prompt(context_package: dict[str, Any], errors=None) -> str:
    """Build a compact regeneration prompt for the MGCECDL inference agent."""
    compact_context = compact_inference_context(context_package)
    errors_text = "" if not errors else "\nErrores previos que debes corregir:\n" + json.dumps(errors, ensure_ascii=False, indent=2)
    return f"""
Eres el agente de inferencia MGCECDL para CHEC. Debes generar una respuesta nueva, completa y válida.

REGLAS CRÍTICAS:
- Devuelve SOLO JSON válido; sin markdown, sin ```json, sin <think>, sin texto adicional.
- No cortes la respuesta: cierra todos los arreglos y el objeto raíz.
- No copies rutas largas; en `entregables.grafos_html` usa `path`: "".
- Incluye exactamente todos los escenarios listados, con el mismo `nombre`.
- `discusion_grafos` debe incluir una entrada por cada sección requerida.
- Máximo 5 ítems por lista. Cada texto debe ser breve pero conservar la interpretación.
- Usa solo el contexto compacto; no inventes variables, escenarios ni causalidad.
{errors_text}

Contexto compacto:
{json.dumps(compact_context, ensure_ascii=False, indent=2, default=str)}

Forma exacta requerida:
{{
  "contexto": {{"circuito": "...", "periodo": {{"inicio": "...", "fin": "..."}}, "modelo": "..."}},
  "entregables": {{"grafos_html": [{{"escenario": "...", "path": ""}}]}},
  "escenarios": [{{"nombre": "...", "interpretacion": "..."}}],
  "discusion_grafos": [{{"seccion": "periodo_completo", "lectura": "..."}}, {{"seccion": "puntos_criticos", "lectura": "..."}}],
  "coherencia_grafo_modelo": ["..."],
  "hallazgos": ["..."],
  "limitaciones": ["..."],
  "inferencias_predictivas": [{{"horizonte": "periodo analizado", "riesgo": "...", "justificacion_modelo": "..."}}],
  "hipotesis_modelo_predictivo": {{"periodo_completo": ["..."], "puntos_criticos": ["..."]}}
}}
"""


def build_base_repair_attempt_prompt(
    errors,
    *,
    repair_prompt_builder: Callable[..., str],
    context_package: dict[str, Any],
    prompt_version: str,
    top_vanos_percentile: float,
    max_critical_points: int,
) -> str:
    """Build a repair prompt for the base report-generation agent."""
    return repair_prompt_builder(
        context_package,
        prompt_version=prompt_version,
        top_vanos_percentile=top_vanos_percentile,
        max_critical_points=max_critical_points,
    ) + """

Errores detectados en el intento anterior:
{errors}

Reglas críticas de reparación:
- Devuelve SOLO JSON válido y completo.
- No uses markdown ni <think>.
- Cierra todos los arreglos y el objeto raíz.
- Máximo 5 ítems por lista.
- Si el error fue de sintaxis JSON, regenera desde cero; no continúes el texto anterior.
""".format(errors=json.dumps(errors, ensure_ascii=False, indent=2))


def compact_expert_alignment_context(context: dict[str, Any]) -> dict[str, Any]:
    """Build a compact context for expert-alignment regeneration prompts."""
    return {
        "circuito": context.get("circuito"),
        "periodo": context.get("periodo"),
        "fuentes_usadas": context.get("fuentes_usadas"),
        "modelo_experto_disponible": context.get("modelo_experto_disponible"),
        "modelo_experto_razon": context.get("modelo_experto_razon"),
        "pdf_expert_matches": context.get("pdf_expert_matches", [])[:6],
        "variables_modelo_predictivo": context.get("variables_modelo_predictivo", [])[:80],
        "llm1_analysis": context.get("llm1_analysis", {}),
        "llm2_inference_analysis": context.get("llm2_inference_analysis", {}),
        "top_variables_modelo": context.get("top_variables_modelo", [])[:20],
        "modos_modelo": context.get("modos_modelo", [])[:20],
    }


def build_expert_alignment_regeneration_prompt(context: dict[str, Any], errors=None) -> str:
    """Build a compact regeneration prompt for expert alignment."""
    errors_text = "" if not errors else "\nErrores previos que debes corregir:\n" + json.dumps(errors, ensure_ascii=False, indent=2)
    compact_context = compact_expert_alignment_context(context)
    return f"""
Eres el agente de comparación experta CHEC. Genera una respuesta nueva y válida.

REGLAS CRÍTICAS:
- Devuelve SOLO JSON válido; sin markdown, sin ```json, sin <think>, sin texto adicional.
- No cortes la respuesta: cierra todos los arreglos y el objeto raíz.
- No inventes fechas, variables, evidencia PDF ni fuentes.
- Usa solo variables presentes en `variables_modelo_predictivo` para `variables_a_priorizar`.
- Si `pdf_expert_matches` está vacío, `hallazgos_expertos_no_cubiertos` debe ser [].
- Máximo 5 ítems por lista.
{errors_text}

Contexto compacto:
{json.dumps(compact_context, ensure_ascii=False, indent=2, default=str)}

Forma exacta requerida:
{{
  "contexto": {{"fuentes_usadas": ["Agente Descriptor", "Agente predictivo"], "modelo_experto_disponible": false, "modelo_experto_razon": "..."}},
  "coincidencias": [{{"tema": "...", "fuentes": ["Agente Descriptor", "Agente predictivo"], "explicacion": "..."}}],
  "diferencias": [{{"tema": "...", "fuentes": ["Agente Descriptor", "Agente predictivo"], "explicacion": "..."}}],
  "hallazgos_expertos_no_cubiertos": [],
  "hallazgos_modelo_no_respaldados_por_pdf": [],
  "variables_a_priorizar": [{{"variable": "...", "prioridad": "media", "fuentes_que_la_respaldan": ["Agente predictivo"], "justificacion": "...", "tipo_de_validacion_sugerida": "..."}}],
  "sintesis_final": "..."
}}
"""


def variables_from_inference(context_package: dict[str, Any]) -> list[str]:
    """Extract unique top-variable names from an inference context package."""
    variables = []
    scenarios = context_package.get("escenarios", []) if isinstance(context_package, dict) else []
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            continue
        for item in scenario.get("top_variables", []):
            variable = item.get("variable") if isinstance(item, dict) else item
            text = str(variable or "").strip()
            if text and text not in variables:
                variables.append(text)
    return variables


def validate_auto_simulator_response(response_text: str) -> dict[str, Any]:
    """Validate the auto-simulator LLM JSON response shape."""
    required_keys = {
        "titulo",
        "resumen",
        "variables_mas_sensibles",
        "patrones_minimo_maximo",
        "hallazgos_para_criticidad",
        "limitaciones",
        "contexto_reutilizado",
    }
    try:
        data = parse_llm_json(response_text or "")
    except Exception as exc:
        return {"ok": False, "data": None, "errors": [f"JSON inválido: {exc}"]}
    if not isinstance(data, dict):
        return {"ok": False, "data": None, "errors": ["La respuesta debe ser un objeto JSON."]}
    missing_keys = sorted(required_keys - set(data))
    errors = [f"Faltan claves requeridas: {missing_keys}"] if missing_keys else []
    for key in [
        "resumen",
        "variables_mas_sensibles",
        "patrones_minimo_maximo",
        "hallazgos_para_criticidad",
        "limitaciones",
        "contexto_reutilizado",
    ]:
        if key in data and not isinstance(data[key], list):
            errors.append(f"{key} debe ser una lista.")
    return {"ok": not errors, "data": data, "errors": errors}


def compact_auto_simulation_context(
    *,
    automatic_simulation_results_df: pd.DataFrame,
    automatic_simulation_metadata: dict[str, Any],
    automatic_simulation_cost_context: dict[str, Any],
    automatic_simulation_softmax_curves: dict[str, Any],
    variables_priorizadas: list[str],
    variables_bajo_analisis: list[str],
    inference_context_package: dict[str, Any],
    circuito: str,
    fecha_inicio: Any,
    fecha_fin: Any,
    model_name: str,
) -> dict[str, Any]:
    """Build a compact context for the automatic min/max simulator agent."""
    table_records = automatic_simulation_results_df.head(20).to_dict(orient="records")
    return {
        "contexto": {
            "circuito": circuito,
            "periodo": {"inicio": str(fecha_inicio), "fin": str(fecha_fin)},
            "modelo": model_name,
        },
        "metadata": automatic_simulation_metadata,
        "variables_priorizadas": variables_priorizadas[:20],
        "variables_bajo_analisis": variables_bajo_analisis[:30],
        "tabla_simulador_automatico": table_records,
        "costos_items_contratos": automatic_simulation_cost_context,
        "curvas_softmax_top_variables": automatic_simulation_softmax_curves,
        "contexto_inferencia_resumen": {
            "escenarios": [
                {
                    "nombre": item.get("nombre"),
                    "top_variables": item.get("top_variables", [])[:4],
                    "modos": item.get("modos", [])[:3],
                }
                for item in inference_context_package.get("escenarios", [])[:4]
                if isinstance(item, dict)
            ],
        },
    }


def build_auto_simulator_prompt(skill_bundle: str, simulation_context: dict[str, Any], errors=None) -> str:
    """Build the automatic simulator LLM prompt."""
    errors_text = "" if not errors else "\nErrores previos que debes corregir:\n" + json.dumps(errors, ensure_ascii=False, indent=2)
    return f"""
{skill_bundle}

REGLAS CRÍTICAS ADICIONALES:
- Devuelve SOLO JSON válido; sin markdown, sin ```json, sin <think>, sin texto adicional.
- Cierra todos los arreglos y el objeto raíz.
- Máximo 5 ítems por lista.
- Usa solo la tabla y metadata entregadas. Si la tabla está vacía, responde con limitaciones basadas en esa ausencia, no inventes resultados.
{errors_text}

Contexto compacto del simulador automático:
{json.dumps(simulation_context, ensure_ascii=False, indent=2, default=str)}
"""
