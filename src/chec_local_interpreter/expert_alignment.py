from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

REQUIRED_PDF_DISCUSSION_COLUMNS = (
    "Circuito",
    "Fecha inicio",
    "Fecha fin",
    "Análisis",
    "Evidencia",
)

EXPERT_ALIGNMENT_REQUIRED_KEYS = (
    "contexto",
    "coincidencias",
    "diferencias",
    "hallazgos_expertos_no_cubiertos",
    "hallazgos_modelo_no_respaldados_por_pdf",
    "variables_a_priorizar",
    "sintesis_final",
)

TARGET_VARIABLES = {"UITI_VANO"}


def _date_text(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _date_value(value: Any):
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def cargar_discussiones_pdf_excel(path: str | Path) -> tuple[pd.DataFrame, list[str]]:
    """Load the already-extracted expert PDF discussion Excel table.

    The function never reads PDFs. It only normalizes the Excel created by the
    dedicated PDF discussion notebook.
    """
    warnings: list[str] = []
    source = Path(path)
    if not source.exists():
        return pd.DataFrame(columns=REQUIRED_PDF_DISCUSSION_COLUMNS), [f"No existe el Excel de discusiones PDF: {source}"]

    try:
        df = pd.read_excel(source)
    except Exception as exc:  # pragma: no cover - depends on local Excel engine/files
        return pd.DataFrame(columns=REQUIRED_PDF_DISCUSSION_COLUMNS), [f"No se pudo leer el Excel de discusiones PDF: {exc}"]

    missing = [col for col in REQUIRED_PDF_DISCUSSION_COLUMNS if col not in df.columns]
    if missing:
        return pd.DataFrame(columns=REQUIRED_PDF_DISCUSSION_COLUMNS), [f"El Excel de discusiones PDF no tiene columnas requeridas: {missing}"]

    normalized = df.loc[:, REQUIRED_PDF_DISCUSSION_COLUMNS].copy()
    normalized["Circuito"] = normalized["Circuito"].fillna("").astype(str).str.strip()
    normalized["Análisis"] = normalized["Análisis"].fillna("").astype(str).str.strip()
    normalized["Evidencia"] = normalized["Evidencia"].fillna("").astype(str).str.strip()
    normalized["Fecha inicio"] = pd.to_datetime(normalized["Fecha inicio"], errors="coerce").dt.date
    normalized["Fecha fin"] = pd.to_datetime(normalized["Fecha fin"], errors="coerce").dt.date
    normalized = normalized.dropna(subset=["Fecha inicio", "Fecha fin"])
    normalized = normalized[(normalized["Análisis"] != "") | (normalized["Evidencia"] != "")]
    normalized = normalized.reset_index(drop=True)

    if normalized.empty:
        warnings.append(f"El Excel de discusiones PDF está vacío o no tiene filas comparables: {source}")
    return normalized, warnings


def _extract_date_records_from_value(value: Any, *, source: str, peso: float, path: str = "") -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if isinstance(value, dict):
        lower_keys = {str(k).lower().replace("_", " ").strip(): k for k in value}
        start_key = next((lower_keys[k] for k in ("fecha inicio", "start date", "inicio", "start") if k in lower_keys), None)
        end_key = next((lower_keys[k] for k in ("fecha fin", "end date", "fin", "end") if k in lower_keys), None)
        single_key = next((lower_keys[k] for k in ("fecha", "date", "fecha dia", "d", "max date") if k in lower_keys), None)

        start = _date_text(value.get(start_key)) if start_key else None
        end = _date_text(value.get(end_key)) if end_key else None
        single = _date_text(value.get(single_key)) if single_key else None
        if start or end:
            records.append({
                "source": source,
                "fecha_inicio": start or end,
                "fecha_fin": end or start,
                "descripcion": path or source,
                "peso": peso,
            })
        elif single:
            records.append({
                "source": source,
                "fecha_inicio": single,
                "fecha_fin": single,
                "descripcion": path or source,
                "peso": peso,
            })

        for key, item in value.items():
            records.extend(_extract_date_records_from_value(item, source=source, peso=peso, path=f"{path}.{key}" if path else str(key)))
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            records.extend(_extract_date_records_from_value(item, source=source, peso=peso, path=f"{path}[{idx}]"))
    return records


def extraer_fechas_informe(
    *,
    validation_data: dict[str, Any] | None = None,
    inference_validation_data: dict[str, Any] | None = None,
    context_package: dict[str, Any] | None = None,
    inference_context_package: dict[str, Any] | None = None,
    critical_points: list[dict[str, Any]] | None = None,
    fecha_inicio: Any = None,
    fecha_fin: Any = None,
    fechas_interes: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Collect date points and intervals from the base, inference and context objects."""
    records: list[dict[str, Any]] = []
    records.extend(_extract_date_records_from_value(validation_data or {}, source="LLM1", peso=2.0))
    records.extend(_extract_date_records_from_value(inference_validation_data or {}, source="LLM2", peso=2.0))
    records.extend(_extract_date_records_from_value(context_package or {}, source="context", peso=0.75))
    records.extend(_extract_date_records_from_value(inference_context_package or {}, source="context", peso=0.75))
    records.extend(_extract_date_records_from_value(critical_points or [], source="critical_point", peso=3.0))

    for value in fechas_interes or []:
        date = _date_text(value)
        if date:
            records.append({
                "source": "critical_point",
                "fecha_inicio": date,
                "fecha_fin": date,
                "descripcion": "FECHAS_INTERES",
                "peso": 3.0,
            })

    start = _date_text(fecha_inicio)
    end = _date_text(fecha_fin)
    if start or end:
        records.append({
            "source": "context",
            "fecha_inicio": start or end,
            "fecha_fin": end or start,
            "descripcion": "periodo_global_informe",
            "peso": 0.5,
        })

    seen: set[tuple[str, str, str, str]] = set()
    normalized: list[dict[str, Any]] = []
    for record in records:
        start = _date_text(record.get("fecha_inicio"))
        end = _date_text(record.get("fecha_fin"))
        if not start and not end:
            continue
        start = start or end
        end = end or start
        if start > end:
            start, end = end, start
        out = {
            "source": str(record.get("source") or "context"),
            "fecha_inicio": start,
            "fecha_fin": end,
            "descripcion": str(record.get("descripcion") or ""),
            "peso": float(record.get("peso") or 1.0),
        }
        key = (out["source"], out["fecha_inicio"], out["fecha_fin"], out["descripcion"])
        if key not in seen:
            seen.add(key)
            normalized.append(out)
    return normalized


def _interval_overlap_and_distance(a_start, a_end, b_start, b_end) -> tuple[int, int]:
    overlap_start = max(a_start, b_start)
    overlap_end = min(a_end, b_end)
    overlap_days = max(0, (overlap_end - overlap_start).days + 1)
    if overlap_days > 0:
        return overlap_days, 0
    if a_end < b_start:
        return 0, (b_start - a_end).days
    return 0, (a_start - b_end).days


def seleccionar_top_coincidencias_temporales(
    *,
    fechas_informe: list[dict[str, Any]],
    pdf_df: pd.DataFrame,
    circuito_interes: str | None,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    if pdf_df.empty or not fechas_informe or top_k <= 0:
        return []

    candidates: list[dict[str, Any]] = []
    circuito_norm = str(circuito_interes or "").strip().upper()
    for idx, row in pdf_df.iterrows():
        pdf_start = _date_value(row.get("Fecha inicio"))
        pdf_end = _date_value(row.get("Fecha fin"))
        if not pdf_start or not pdf_end:
            continue
        if pdf_start > pdf_end:
            pdf_start, pdf_end = pdf_end, pdf_start

        best: dict[str, Any] | None = None
        for fecha in fechas_informe:
            report_start = _date_value(fecha.get("fecha_inicio"))
            report_end = _date_value(fecha.get("fecha_fin"))
            if not report_start or not report_end:
                continue
            if report_start > report_end:
                report_start, report_end = report_end, report_start
            overlap_days, distance_days = _interval_overlap_and_distance(report_start, report_end, pdf_start, pdf_end)
            union_days = max(1, (max(report_end, pdf_end) - min(report_start, pdf_start)).days + 1)
            overlap_ratio = overlap_days / union_days
            if overlap_days > 0:
                temporal_score = 1.0 + overlap_ratio
            else:
                temporal_score = 1.0 / (1.0 + distance_days)
            temporal_score *= float(fecha.get("peso") or 1.0)
            if circuito_norm and str(row.get("Circuito") or "").strip().upper() == circuito_norm:
                temporal_score += 0.5
            if str(row.get("Evidencia") or "").strip():
                temporal_score += 0.1

            match = {
                "Circuito": str(row.get("Circuito") or "").strip(),
                "Fecha inicio": _date_text(pdf_start),
                "Fecha fin": _date_text(pdf_end),
                "Análisis": str(row.get("Análisis") or "").strip(),
                "Evidencia": str(row.get("Evidencia") or "").strip(),
                "matched_source": str(fecha.get("source") or ""),
                "matched_fecha_inicio": _date_text(report_start),
                "matched_fecha_fin": _date_text(report_end),
                "matched_descripcion": str(fecha.get("descripcion") or ""),
                "temporal_score": round(float(temporal_score), 6),
                "overlap_days": int(overlap_days),
                "distance_days": int(distance_days),
                "pdf_row_index": int(idx),
            }
            if best is None or match["temporal_score"] > best["temporal_score"]:
                best = match
        if best is not None:
            candidates.append(best)

    return sorted(candidates, key=lambda item: item["temporal_score"], reverse=True)[:top_k]


def _truncate_text(value: Any, limit: int = 700) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _compact_strings(items: Any, *, limit: int = 5, text_limit: int = 400) -> list[str]:
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items[:limit]:
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            text = (
                item.get("text")
                or item.get("interpretacion")
                or item.get("lectura")
                or item.get("comentario")
                or item.get("title")
                or json.dumps(item, ensure_ascii=False)
            )
        else:
            text = str(item)
        text = _truncate_text(text, text_limit)
        if text:
            out.append(text)
    return out


def _compact_llm1_analysis(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    char = data.get("circuit_characterization", {})
    if not isinstance(char, dict):
        char = {}
    return {
        "executive_summary": _compact_strings(data.get("executive_summary", []), limit=4, text_limit=350),
        "key_findings": [
            {
                "title": _truncate_text(item.get("title"), 120),
                "text": _truncate_text(item.get("text"), 350),
                "evidence": item.get("evidence", [])[:2],
                "referenced_events": item.get("referenced_events", [])[:2],
                "variable_groups_used": item.get("variable_groups_used", []),
            }
            for item in (data.get("key_findings", []) if isinstance(data.get("key_findings"), list) else [])[:4]
            if isinstance(item, dict)
        ],
        "circuit_characterization": {
            "text": _truncate_text(char.get("text"), 450),
            "top_vanos_percentile": char.get("top_vanos_percentile"),
            "p97_vanos_uiti_vano": char.get("p97_vanos_uiti_vano", [])[:8],
            "p97_vanos_eventos": char.get("p97_vanos_eventos", [])[:8],
            "top_3_modes_related": char.get("top_3_modes_related", [])[:5],
        },
        "period_synthesis": _truncate_text(data.get("period_synthesis"), 500),
        "data_gaps": _compact_strings(data.get("data_gaps", []), limit=5, text_limit=200),
        "limitations": _compact_strings(data.get("limitations", []), limit=5, text_limit=200),
    }


def _compact_llm2_analysis(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    escenarios = []
    for item in data.get("escenarios", []) if isinstance(data.get("escenarios"), list) else []:
        if not isinstance(item, dict):
            continue
        escenarios.append({
            "nombre": _truncate_text(item.get("nombre"), 140),
            "interpretacion": _truncate_text(item.get("interpretacion"), 450),
        })
    return {
        "contexto": data.get("contexto", {}),
        "escenarios": escenarios[:6],
        "discusion_grafos": [
            {
                "seccion": item.get("seccion") or item.get("section"),
                "lectura": _truncate_text(item.get("lectura") or item.get("interpretacion") or item.get("texto"), 450),
            }
            for item in (data.get("discusion_grafos", []) if isinstance(data.get("discusion_grafos"), list) else [])[:4]
            if isinstance(item, dict)
        ],
        "hallazgos": _compact_strings(data.get("hallazgos", []), limit=5, text_limit=300),
        "limitaciones": _compact_strings(data.get("limitaciones", []), limit=5, text_limit=250),
    }


def _predictive_model_variables(inference_context_package: dict[str, Any] | None) -> list[str]:
    if not isinstance(inference_context_package, dict):
        return []
    variables = inference_context_package.get("features")
    if not isinstance(variables, list):
        variables = inference_context_package.get("graph_feature_order")
    if not isinstance(variables, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for variable in variables:
        text = str(variable).strip()
        if text and text.upper() not in TARGET_VARIABLES and text.upper() not in seen:
            seen.add(text.upper())
            out.append(text)
    return out


def _extract_variable_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("variable", "feature", "nombre", "name", "columna"):
            if value.get(key):
                return str(value.get(key)).strip()
        if len(value) == 1:
            only_key = next(iter(value))
            return str(only_key).strip()
    return None


def _predictive_model_signals(inference_context_package: dict[str, Any] | None, *, limit: int = 40) -> list[dict[str, Any]]:
    if not isinstance(inference_context_package, dict):
        return []
    signals: list[dict[str, Any]] = []
    for scenario in inference_context_package.get("escenarios", []) if isinstance(inference_context_package.get("escenarios"), list) else []:
        if not isinstance(scenario, dict):
            continue
        scenario_name = str(scenario.get("nombre") or scenario.get("criterio") or "").strip()
        for rank, item in enumerate(scenario.get("top_variables", []) if isinstance(scenario.get("top_variables"), list) else [], start=1):
            variable = _extract_variable_name(item)
            if variable:
                signals.append({
                    "variable": variable,
                    "escenario": scenario_name,
                    "rank": rank,
                    "tipo_senal": "top_variable",
                    "detalle": item if isinstance(item, dict) else str(item),
                })
        for mode in scenario.get("modos", []) if isinstance(scenario.get("modos"), list) else []:
            if not isinstance(mode, dict):
                continue
            mode_name = str(mode.get("modo") or mode.get("nombre") or mode.get("grupo") or "").strip()
            mode_variables = mode.get("variables") or mode.get("variables_asociadas") or mode.get("features") or []
            if isinstance(mode_variables, list):
                for variable in mode_variables[:10]:
                    variable_name = _extract_variable_name(variable)
                    if variable_name:
                        signals.append({
                            "variable": variable_name,
                            "escenario": scenario_name,
                            "modo": mode_name,
                            "tipo_senal": "modo_grafo",
                        })
    graph_discussions = inference_context_package.get("graph_discussions") or inference_context_package.get("discusion_grafos")
    if isinstance(graph_discussions, list):
        for item in graph_discussions[:6]:
            signals.append({
                "tipo_senal": "lectura_grafo",
                "detalle": _truncate_text(item, 300),
            })
    return signals[:limit]


def _normalize_variable_list(variables: Any) -> list[str]:
    if not isinstance(variables, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for variable in variables:
        text = str(variable).strip()
        if text and text.upper() not in TARGET_VARIABLES and text.upper() not in seen:
            seen.add(text.upper())
            out.append(text)
    return out


def _variable_aliases() -> dict[str, list[str]]:
    return {
        "CNT_TRF": ["cantidad de transformadores", "cantidad_transformadores", "transformadores", "cnt_trf"],
        "CNT_VN": ["cantidad de vanos", "cantidad_vanos", "vanos", "cnt_vn"],
        "TIPO": ["tipo de equipo", "tipo_equipo", "infraestructura de protección", "proteccion y maniobra", "protección y maniobra"],
        "NR_T": ["vegetación", "vegetacion", "nr_t"],
        "DDT": ["descargas a tierra", "descargas_atmosfericas", "rayos", "ddt"],
    }


def _resolve_predictive_variable_name(variable: Any, context: dict[str, Any]) -> str:
    text = str(variable or "").strip()
    if not text:
        return ""
    predictive_variables = _normalize_variable_list(context.get("variables_modelo_predictivo", []))
    predictive_by_upper = {item.upper(): item for item in predictive_variables}
    if text.upper() in predictive_by_upper:
        return predictive_by_upper[text.upper()]

    normalized_text = re.sub(r"[_\W]+", " ", text.lower()).strip()
    for canonical_upper, aliases in _variable_aliases().items():
        if canonical_upper not in predictive_by_upper:
            continue
        normalized_aliases = {re.sub(r"[_\W]+", " ", alias.lower()).strip() for alias in aliases}
        if normalized_text in normalized_aliases:
            return predictive_by_upper[canonical_upper]
    return text


def _compact_pdf_matches(matches: list[dict[str, Any]], *, limit: int = 10) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in matches[:limit]:
        if not isinstance(item, dict):
            continue
        circuito = str(item.get("Circuito") or "").strip()
        archivo_pdf = f"{circuito}.pdf" if circuito else None
        compact.append({
            "pdf_row_index": item.get("pdf_row_index"),
            "Circuito": item.get("Circuito"),
            "archivo_pdf": archivo_pdf,
            "Fecha inicio": item.get("Fecha inicio"),
            "Fecha fin": item.get("Fecha fin"),
            "Análisis": _truncate_text(item.get("Análisis"), 550),
            "Evidencia": _truncate_text(item.get("Evidencia"), 550),
            "matched_source": item.get("matched_source"),
            "matched_fecha_inicio": item.get("matched_fecha_inicio"),
            "matched_fecha_fin": item.get("matched_fecha_fin"),
            "temporal_score": item.get("temporal_score"),
            "overlap_days": item.get("overlap_days"),
            "distance_days": item.get("distance_days"),
        })
    return compact


def compactar_contexto_expert_alignment_para_prompt(context: dict[str, Any]) -> dict[str, Any]:
    """Reduce prompt size without changing the deterministic context artifact."""
    if not isinstance(context, dict):
        return {}
    return {
        "circuito": context.get("circuito"),
        "periodo_informe": context.get("periodo_informe"),
        "fechas_informe": [
            item for item in context.get("fechas_informe", [])
            if isinstance(item, dict) and item.get("source") != "context"
        ][:20],
        "llm1_analysis": _compact_llm1_analysis(context.get("llm1_analysis", {})),
        "llm2_inference_analysis": _compact_llm2_analysis(context.get("llm2_inference_analysis", {})),
        "variables_modelo_predictivo": context.get("variables_modelo_predictivo", []),
        "senales_modelo_predictivo": context.get("senales_modelo_predictivo", []),
        "pdf_expert_matches": _compact_pdf_matches(context.get("pdf_expert_matches", []), limit=10),
    }


def construir_prompt_expert_alignment(context: dict[str, Any], skill_bundle: str) -> str:
    compact = compactar_contexto_expert_alignment_para_prompt(context)
    return (
        "Eres un agente de comparación técnica entre tres fuentes: "
        "agente de análisis histórico, agente del modelo predictivo y reportes expertos extraídos previamente a Excel. "
        "Devuelve únicamente JSON válido, "
        "sin markdown, sin etiquetas <think> y sin texto adicional.\n\n"
        "## Skill expert_alignment\n"
        f"{skill_bundle}\n\n"
        "## Contexto estructurado\n"
        f"{json.dumps(compact, ensure_ascii=False, indent=2)}\n\n"
        "## Formato exacto de salida\n"
        "{\n"
        '  "contexto": {"circuito": "...", "periodo": {"inicio": "YYYY-MM-DD", "fin": "YYYY-MM-DD"}, "n_filas_expertas_comparadas": 0},\n'
        '  "coincidencias": [{"tema": "hallazgo", "fuentes": ["Agente base", "Agente predictivo", "DON23L13.pdf"], "explicacion": "..."}],\n'
        '  "diferencias": [{"tema": "hallazgo", "fuentes": ["Agente base", "Agente predictivo", "DON23L13.pdf"], "explicacion": "..."}],\n'
        '  "hallazgos_expertos_no_cubiertos": [],\n'
        '  "hallazgos_modelo_no_respaldados_por_pdf": [],\n'
        '  "variables_a_priorizar": [{"variable": "...", "prioridad": "alta", "fuentes_que_la_respaldan": ["Agente base", "Agente predictivo", "DON23L13.pdf"], "justificacion": "...", "tipo_de_validacion_sugerida": "..."}],\n'
        '  "sintesis_final": "..."\n'
        "}\n\n"
        "Aplica estrictamente las skills cargadas para decidir contenido, nombres de fuentes, "
        "variables priorizables, uso de grafos y lenguaje técnico. "
        "Devuelve solo el objeto JSON con las claves indicadas."
    )


def construir_contexto_expert_alignment(
    *,
    circuito: str,
    periodo_inicio: Any,
    periodo_fin: Any,
    fechas_informe: list[dict[str, Any]],
    validation_data: dict[str, Any],
    inference_validation_data: dict[str, Any],
    pdf_expert_matches: list[dict[str, Any]],
    inference_context_package: dict[str, Any] | None = None,
    variables_modelo_predictivo: list[Any] | None = None,
) -> dict[str, Any]:
    predictive_variables = _normalize_variable_list(variables_modelo_predictivo)
    if not predictive_variables:
        predictive_variables = _predictive_model_variables(inference_context_package)
    return {
        "circuito": str(circuito),
        "periodo_informe": {
            "inicio": _date_text(periodo_inicio),
            "fin": _date_text(periodo_fin),
        },
        "fechas_informe": fechas_informe,
        "llm1_analysis": validation_data,
        "llm2_inference_analysis": inference_validation_data,
        "variables_modelo_predictivo": predictive_variables,
        "senales_modelo_predictivo": _predictive_model_signals(inference_context_package),
        "pdf_expert_matches": pdf_expert_matches,
    }


def guardar_tabla_coincidencias_pdf(matches: list[dict[str, Any]], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(matches).to_excel(target, index=False)
    return target


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(_flatten_strings(item))
        return strings
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(_flatten_strings(item))
        return strings
    return []


def _parse_strict_json(response_text: str) -> dict[str, Any]:
    text = str(response_text).strip()
    if not text.startswith("{") or not text.endswith("}"):
        raise json.JSONDecodeError("La respuesta debe contener solo un objeto JSON.", text, 0)
    return json.loads(text)


def _allowed_dates(context: dict[str, Any]) -> set[str]:
    dates: set[str] = set()
    for record in context.get("fechas_informe", []):
        if isinstance(record, dict):
            dates.update(filter(None, [_date_text(record.get("fecha_inicio")), _date_text(record.get("fecha_fin"))]))
    period = context.get("periodo_informe", {})
    if isinstance(period, dict):
        dates.update(filter(None, [_date_text(period.get("inicio")), _date_text(period.get("fin"))]))
    for row in context.get("pdf_expert_matches", []):
        if isinstance(row, dict):
            dates.update(filter(None, [_date_text(row.get("Fecha inicio")), _date_text(row.get("Fecha fin"))]))
            dates.update(filter(None, [_date_text(row.get("matched_fecha_inicio")), _date_text(row.get("matched_fecha_fin"))]))
            for field in ("Análisis", "Evidencia"):
                dates.update(re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", str(row.get(field) or "")))
    return dates


def _allowed_evidences(context: dict[str, Any]) -> list[str]:
    evidences: list[str] = []
    for row in context.get("pdf_expert_matches", []):
        if not isinstance(row, dict):
            continue
        for field in ("Análisis", "Evidencia"):
            value = str(row.get(field) or "").strip()
            if value:
                evidences.append(value)
    return evidences


def _allowed_pdf_row_indexes(context: dict[str, Any]) -> set[str]:
    indexes: set[str] = set()
    for row in context.get("pdf_expert_matches", []):
        if isinstance(row, dict) and row.get("pdf_row_index") is not None:
            indexes.add(str(row.get("pdf_row_index")))
    return indexes


def _allowed_variables(context: dict[str, Any]) -> set[str]:
    predictive_variables = _normalize_variable_list(context.get("variables_modelo_predictivo", []))
    if predictive_variables:
        return {str(variable).strip().upper() for variable in predictive_variables if str(variable).strip()}
    text = json.dumps({
        "llm1": context.get("llm1_analysis", {}),
        "llm2": context.get("llm2_inference_analysis", {}),
        "fechas": context.get("fechas_informe", []),
        "pdf": context.get("pdf_expert_matches", []),
    }, ensure_ascii=False)
    variables = set(re.findall(r"\b[A-ZÁÉÍÓÚÑ][A-Z0-9ÁÉÍÓÚÑ_]{2,}\b", text.upper()))
    variables.update({"UITI_VANO", "SHAP", "MGCECDL"})
    return variables


def _evidence_is_supported(evidence: str, allowed_evidences: list[str], allowed_indexes: set[str] | None = None) -> bool:
    if not evidence:
        return True
    allowed_indexes = allowed_indexes or set()
    referenced_indexes = set(re.findall(r"(?:pdf_row_index|fila|row)\s*#?\s*(\d+)", evidence, flags=re.IGNORECASE))
    if referenced_indexes and referenced_indexes.issubset(allowed_indexes):
        return True
    if any(evidence in source or source in evidence for source in allowed_evidences):
        return True
    evidence_parts = [part.strip() for part in re.split(r";|\.\s+", evidence) if len(part.strip()) >= 30]
    if not evidence_parts:
        evidence_parts = [evidence]
    for part in evidence_parts:
        part_words = set(re.findall(r"\w{5,}", part.lower()))
        if not part_words:
            continue
        best_overlap = 0.0
        for source in allowed_evidences:
            source_words = set(re.findall(r"\w{5,}", source.lower()))
            if source_words:
                best_overlap = max(best_overlap, len(part_words & source_words) / max(1, len(part_words)))
        if best_overlap < 0.45:
            return False
    return True


def _infer_priority_variables(data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    predictive_variables = _normalize_variable_list(context.get("variables_modelo_predictivo", []))
    if not predictive_variables:
        return []

    predictive_by_upper = {variable.upper(): variable for variable in predictive_variables}
    text_blob = json.dumps(
        {
            "coincidencias": data.get("coincidencias", []),
            "diferencias": data.get("diferencias", []),
            "sintesis_final": data.get("sintesis_final", ""),
            "senales_modelo_predictivo": context.get("senales_modelo_predictivo", []),
        },
        ensure_ascii=False,
    ).lower()
    aliases = _variable_aliases()

    selected: list[str] = []
    for variable in predictive_variables:
        upper = variable.upper()
        candidates = [variable.lower(), upper.lower(), *aliases.get(upper, [])]
        if any(candidate and candidate in text_blob for candidate in candidates):
            selected.append(variable)

    if not selected:
        signal_counts: dict[str, int] = {}
        for signal in context.get("senales_modelo_predictivo", []) if isinstance(context.get("senales_modelo_predictivo"), list) else []:
            if not isinstance(signal, dict):
                continue
            variable = str(signal.get("variable") or "").strip()
            if variable.upper() in predictive_by_upper:
                signal_counts[variable.upper()] = signal_counts.get(variable.upper(), 0) + 1
        selected = [
            predictive_by_upper[upper]
            for upper, _ in sorted(signal_counts.items(), key=lambda item: item[1], reverse=True)
        ]

    # Prefer variables explicitly discussed by the model/expert comparison.
    selected = selected[:5]
    out = []
    for variable in selected:
        upper = variable.upper()
        if upper == "CNT_TRF":
            justification = "Aparece en la comparación como señal del modelo predictivo asociada a cantidad de transformadores."
        elif upper == "CNT_VN":
            justification = "Aparece en la comparación como señal del modelo predictivo asociada a cantidad de vanos."
        elif upper == "TIPO":
            justification = "Aparece en la comparación como señal del modelo predictivo asociada al tipo de equipo o protección."
        elif upper == "NR_T":
            justification = "Aparece en la comparación por su relación con vegetación y entorno."
        elif upper == "DDT":
            justification = "Aparece en la comparación por su relación con descargas atmosféricas."
        elif upper == "UITI_VANO":
            justification = "Aparece como indicador central comparado entre el análisis histórico, el modelo y reportes expertos."
        else:
            justification = "Aparece en los hallazgos de coincidencias o diferencias y pertenece a las variables del modelo predictivo."
        out.append({
            "variable": predictive_by_upper.get(upper, variable),
            "prioridad": "media",
            "fuentes_que_la_respaldan": ["Agente predictivo"],
            "justificacion": justification,
            "tipo_de_validacion_sugerida": "Validar su conexión en los grafos del modelo y contrastarla con eventos históricos del circuito.",
        })
    return out


def _pdf_source_names(context: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in context.get("pdf_expert_matches", []) or []:
        if not isinstance(item, dict):
            continue
        circuito = str(item.get("Circuito") or "").strip()
        if circuito:
            name = f"{circuito}.pdf"
            if name not in names:
                names.append(name)
    return names


def _normalize_visible_sources(value: Any, context: dict[str, Any]) -> list[str]:
    pdf_names = _pdf_source_names(context)
    fallback_pdf = pdf_names or ["reportes expertos"]
    if value in (None, "", []):
        return []
    raw_items = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    source_map = {
        "llm1": ["Agente base"],
        "llm 1": ["Agente base"],
        "agente base": ["Agente base"],
        "agente de análisis histórico": ["Agente base"],
        "agente de analisis historico": ["Agente base"],
        "llm de datos históricos": ["Agente base"],
        "llm de datos historicos": ["Agente base"],
        "llm2": ["Agente predictivo"],
        "llm 2": ["Agente predictivo"],
        "agente predictivo": ["Agente predictivo"],
        "agente del modelo predictivo": ["Agente predictivo"],
        "llm del modelo predictivo": ["Agente predictivo"],
        "pdf_experto": fallback_pdf,
        "reportes expertos": fallback_pdf,
        "reporte experto": fallback_pdf,
    }
    for item in raw_items:
        text = str(item or "").strip()
        if not text:
            continue
        mapped = source_map.get(text.lower(), [text])
        for source in mapped:
            source_text = str(source).strip()
            if source_text and source_text not in normalized:
                normalized.append(source_text)
    return normalized


def _normalize_comparison_sources(data: dict[str, Any], context: dict[str, Any]) -> None:
    for section_name in ("coincidencias", "diferencias"):
        section = data.get(section_name, [])
        if not isinstance(section, list):
            continue
        for item in section:
            if not isinstance(item, dict):
                continue
            sources = _normalize_visible_sources(item.get("fuentes"), context)
            if sources:
                item["fuentes"] = sources
    variables = data.get("variables_a_priorizar", [])
    if isinstance(variables, list):
        for item in variables:
            if not isinstance(item, dict):
                continue
            sources = _normalize_visible_sources(item.get("fuentes_que_la_respaldan"), context)
            if sources:
                item["fuentes_que_la_respaldan"] = sources


def validar_respuesta_expert_alignment(response_text: str, context: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    try:
        data = _parse_strict_json(response_text)
    except json.JSONDecodeError as exc:
        return {"ok": False, "data": None, "errors": [f"JSON invalido o texto adicional: {exc}"]}

    if not isinstance(data, dict):
        return {"ok": False, "data": None, "errors": ["La respuesta debe ser un objeto JSON."]}

    _normalize_comparison_sources(data, context)

    for key in EXPERT_ALIGNMENT_REQUIRED_KEYS:
        if key not in data:
            errors.append(f"Falta la clave requerida: {key}")

    allowed_dates = _allowed_dates(context)
    text_blob = json.dumps(data, ensure_ascii=False)
    for date in re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", text_blob):
        if date not in allowed_dates:
            errors.append(f"Fecha fuera del contexto o Excel comparado: {date}")

    evidences = _allowed_evidences(context)
    allowed_indexes = _allowed_pdf_row_indexes(context)
    evidence_sections: list[Any] = []
    for section_name in ("coincidencias", "diferencias", "hallazgos_expertos_no_cubiertos"):
        section = data.get(section_name, [])
        if isinstance(section, list):
            evidence_sections.extend(section)
        else:
            errors.append(f"{section_name} debe ser una lista.")
        if section_name in {"coincidencias", "diferencias"} and isinstance(section, list):
            for item in section:
                if isinstance(item, dict) and not item.get("fuentes"):
                    errors.append(f"{section_name} debe incluir fuentes visibles en cada item.")
    for item in evidence_sections:
        if not isinstance(item, dict):
            continue
        evidence = str(item.get("evidencia_pdf") or "").strip()
        if evidence and not _evidence_is_supported(evidence, evidences, allowed_indexes):
            errors.append(f"Evidencia PDF no proviene de filas comparadas: {evidence[:120]}")

    allowed_variables = _allowed_variables(context)
    variables_section = data.get("variables_a_priorizar", [])
    if isinstance(variables_section, list) and not variables_section and (data.get("coincidencias") or data.get("diferencias")):
        inferred_variables = _infer_priority_variables(data, context)
        if inferred_variables:
            data["variables_a_priorizar"] = inferred_variables
            variables_section = inferred_variables
    if not isinstance(variables_section, list):
        variables_section = []
        errors.append("variables_a_priorizar debe ser una lista.")
    normalized_variables_section: list[dict[str, Any]] = []
    dropped_invalid_variables: list[str] = []
    for item in variables_section:
        if not isinstance(item, dict):
            errors.append("Cada variable priorizada debe ser un objeto.")
            continue
        variable = _resolve_predictive_variable_name(item.get("variable"), context)
        if variable:
            item["variable"] = variable
        variable_tokens = set(re.findall(r"\b[A-ZÁÉÍÓÚÑ][A-Z0-9ÁÉÍÓÚÑ_]{2,}\b", variable.upper()))
        if not variable:
            errors.append("Hay una variable a priorizar sin nombre.")
        elif variable.upper() not in allowed_variables and not variable_tokens.intersection(allowed_variables):
            if not context.get("variables_modelo_predictivo"):
                errors.append(f"Variable no encontrada en fuentes entregadas: {variable}")
            else:
                dropped_invalid_variables.append(variable)
            continue
        normalized_variables_section.append(item)
    if isinstance(data.get("variables_a_priorizar"), list):
        if normalized_variables_section:
            data["variables_a_priorizar"] = normalized_variables_section
        elif dropped_invalid_variables:
            errors.append(
                "Variable no encontrada en fuentes entregadas: "
                + ", ".join(dropped_invalid_variables[:5])
            )

    has_relevant_comparison = bool(data.get("coincidencias") or data.get("diferencias"))
    if has_relevant_comparison and not data.get("variables_a_priorizar"):
        if context.get("variables_modelo_predictivo"):
            errors.append("variables_a_priorizar no debe estar vacío si hay coincidencias o diferencias relevantes.")

    forbidden = ["causó", "causo", "demuestra causalidad", "prueba causal"]
    lower_blob = text_blob.lower()
    for phrase in forbidden:
        if phrase in lower_blob:
            errors.append(f"Lenguaje causal no permitido: {phrase}")

    return {"ok": not errors, "data": data, "errors": errors}
