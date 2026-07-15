from __future__ import annotations

import base64

import pandas as pd

from chec_local_interpreter.plotting import render_expert_alignment_tab, render_llm_analysis


# ---------------------------------------------------------------------------
# Task 3.5 -- `_figure_html` accepts a persisted PNG path (str/Path), not
# only an open matplotlib figure object, since `_run_inference_simulator`
# (task 3.2) now saves figures to disk and `render()` (task 3.4) only ever
# passes back paths, never live figure objects.
# ---------------------------------------------------------------------------


def _minimal_raw_and_daily_df():
    raw_df = pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1"],
            "FECHA": ["2026-01-01", "2026-01-02"],
            "UITI_VANO": [10.0, 20.0],
            "FID_VANO": ["V1", "V2"],
        }
    )
    daily_df = pd.DataFrame(
        {
            "fecha_dia": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "UITI_VANO": [10.0, 20.0],
            "event_count": [1, 1],
        }
    )
    return raw_df, daily_df


def test_figure_html_embeds_persisted_png_path_as_base64_img(tmp_path):
    png_path = tmp_path / "fig_barras.png"
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"not-a-real-png-but-bytes-are-enough"
    png_path.write_bytes(png_bytes)

    raw_df, daily_df = _minimal_raw_and_daily_df()
    inference_results = {
        "top_uiti_periodo": {
            "fig_barras": str(png_path),
            "fig_radar": None,
            "grafo_interactivo": None,
            "contexto": {"nombre": "Top P97 por UITI_VANO — período completo"},
        },
    }

    html_path = render_llm_analysis(
        validation_data={},
        raw_df=raw_df,
        daily_df=daily_df,
        critical_points=[],
        selected_circuitos=["TODOS"],
        inference_results=inference_results,
        inference_analysis={},
        output_dir=tmp_path / "html",
    )
    html = html_path.read_text(encoding="utf-8")

    encoded = base64.b64encode(png_bytes).decode("ascii")
    assert encoded in html
    assert "<img" in html


def test_figure_html_nonexistent_png_path_falls_back_without_crash(tmp_path):
    raw_df, daily_df = _minimal_raw_and_daily_df()
    inference_results = {
        "top_uiti_periodo": {
            "fig_barras": str(tmp_path / "does-not-exist.png"),
            "fig_radar": None,
            "grafo_interactivo": None,
            "contexto": {"nombre": "Top P97 por UITI_VANO — período completo"},
        },
    }

    html_path = render_llm_analysis(
        validation_data={},
        raw_df=raw_df,
        daily_df=daily_df,
        critical_points=[],
        selected_circuitos=["TODOS"],
        inference_results=inference_results,
        inference_analysis={},
        output_dir=tmp_path / "html",
    )
    html = html_path.read_text(encoding="utf-8")

    assert "No se pudo renderizar" in html
    assert "<img" not in html


def test_inference_layout_consolidates_general_discussion(tmp_path):
    raw_df = pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1"],
            "FECHA": ["2026-01-01", "2026-01-02"],
            "UITI_VANO": [10.0, 20.0],
            "FID_VANO": ["V1", "V2"],
        }
    )
    daily_df = pd.DataFrame(
        {
            "fecha_dia": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "UITI_VANO": [10.0, 20.0],
            "event_count": [1, 1],
        }
    )
    inference_results = {
        "top_frecuencia_periodo": {"contexto": {"nombre": "Frecuencia periodo"}},
        "top_uiti_periodo": {"contexto": {"nombre": "Severidad periodo"}},
        "top_frecuencia_puntos_criticos": {"contexto": {"nombre": "Frecuencia puntos"}},
        "top_uiti_puntos_criticos": {"contexto": {"nombre": "Severidad puntos"}},
    }
    inference_analysis = {
        "hallazgos": ["Hallazgo general uno.", "Hallazgo general dos."],
        "escenarios": [
            {"nombre": "Frecuencia periodo", "interpretacion": "Frecuencia item uno. Frecuencia item dos."},
            {"nombre": "Severidad periodo", "interpretacion": "Severidad item uno. Severidad item dos."},
            {"nombre": "Frecuencia puntos", "interpretacion": "Frecuencia critica uno. Frecuencia critica dos."},
            {"nombre": "Severidad puntos", "interpretacion": "Severidad critica uno. Severidad critica dos."},
        ],
        "discusion_grafos": [
            {"seccion": "periodo_completo", "lectura": "Grafo periodo uno."},
            {"seccion": "puntos_criticos", "lectura": "Grafo critico uno."},
        ],
        "hipotesis_modelo_predictivo": {
            "periodo_completo": [
                "El modelo sugiere que la recurrencia y la severidad del periodo se explican por señales combinadas de infraestructura y grafos."
            ],
            "puntos_criticos": [
                "El modelo sugiere que los puntos críticos concentran señales consistentes entre variables priorizadas y grafos estimados."
            ],
        },
    }

    html_path = render_llm_analysis(
        validation_data={},
        raw_df=raw_df,
        daily_df=daily_df,
        critical_points=[],
        selected_circuitos=["TODOS"],
        inference_results=inference_results,
        inference_analysis=inference_analysis,
        output_dir=tmp_path,
    )
    html = html_path.read_text(encoding="utf-8")

    assert html.count("Discusión general de inferencias del modelo") == 1
    assert "Hallazgos generales del modelo de inferencia" not in html
    assert "Discusión general de inferencias del modelo &mdash; Número de Eventos" not in html
    assert "<h4>Número de Eventos</h4>" in html
    assert "<h4>UITI_VANO</h4>" in html
    assert "Hipótesis del modelo predictivo — período completo" in html
    assert html.index("Hipótesis del modelo predictivo — período completo") > html.index("Discusión general de inferencias del modelo")
    assert "Hipótesis del modelo predictivo — puntos críticos" in html
    assert html.index("Hipótesis del modelo predictivo — puntos críticos") > html.index("Discusión de inferencias en puntos críticos")
    assert html.count("Discusión de inferencias en puntos críticos") == 1


def test_expert_alignment_tab_renders_auto_simulation_analysis():
    table = pd.DataFrame(
        [
            {
                "variable": "CNT_TRF",
                "valor_original_base": 1.0,
                "valor_minimo_usado": 0.0,
                "valor_maximo_usado": 3.0,
                "riesgo_base": 1.2,
                "riesgo_base_etiqueta": "Riesgo bajo",
                "riesgo_valor_minimo": 1.0,
                "riesgo_valor_minimo_etiqueta": "Riesgo bajo",
                "riesgo_valor_maximo": 1.5,
                "riesgo_valor_maximo_etiqueta": "Riesgo alto",
                "cambio_absoluto_minimo": -0.2,
                "cambio_absoluto_maximo": 0.3,
                "direccion_cambio_minimo": "disminuye riesgo",
                "direccion_cambio_maximo": "aumenta riesgo",
                "observacion": "CNT_TRF cambia el riesgo.",
            },
            {
                "variable": "LONGITUD",
                "valor_original_base": 10.0,
                "valor_minimo_usado": 5.0,
                "valor_maximo_usado": 20.0,
                "riesgo_base": 2.1,
                "riesgo_base_etiqueta": "Riesgo medio-alto (Q3)",
                "riesgo_valor_minimo": 2.0,
                "riesgo_valor_minimo_etiqueta": "Riesgo medio-alto (Q3)",
                "riesgo_valor_maximo": 2.2,
                "riesgo_valor_maximo_etiqueta": "Riesgo medio-alto (Q3)",
                "cambio_absoluto_minimo": -0.1,
                "cambio_absoluto_maximo": 0.1,
                "direccion_cambio_minimo": "sin cambio relevante",
                "direccion_cambio_maximo": "sin cambio relevante",
                "observacion": "LONGITUD mantiene la clase.",
            }
        ]
    )
    analysis = {
        "contexto": {"fuentes_usadas": ["Agente Descriptor", "Agente predictivo"]},
        "coincidencias": [],
        "diferencias": [],
        "variables_a_priorizar": [
            {
                "variable": "CNT_TRF",
                "prioridad": "Alta",
                "fuentes_que_la_respaldan": ["Agente predictivo"],
                "justificacion": "Variable sensible en simulación.",
                "tipo_de_validacion_sugerida": "Revisión operativa",
            }
        ],
        "sintesis_final": "Síntesis.",
    }
    auto_analysis = {
        "resumen": ["Resumen del simulador con &#x27;Riesgo bajo (Q1)&#x27; legible."],
        "variables_mas_sensibles": [
            {"variable": "CNT_TRF", "lectura": "Mayor sensibilidad.", "mayor_cambio_abs": 0.3}
        ],
        "patrones_minimo_maximo": ["El mínimo baja y el máximo sube."],
        "hallazgos_para_criticidad": ["Útil para revisar criticidad."],
        "limitaciones": ["Una variable a la vez."],
        "contexto_reutilizado": ["Variables priorizadas."],
    }
    cost_context = {
        "disponible": True,
        "metodo": "Coincidencia por tokens.",
        "advertencias": [],
        "coincidencias": [
            {
                "variable": "CNT_TRF",
                "riesgo_base_etiqueta": "Riesgo bajo",
                "riesgo_valor_minimo_etiqueta": "Riesgo bajo",
                "riesgo_valor_maximo_etiqueta": "Riesgo alto",
                "items_costo_cercanos": [
                    {
                        "item_costo": "SERVICIO DE INSTALACION DE TRANSFORMADOR TRIFASICO",
                        "costo_promedio": 696655.0,
                        "puntaje_cercania": 0.42,
                    }
                ],
            }
        ],
    }
    softmax_curves = {
        "variables": [
            {
                "variable": "CNT_TRF",
                "etiquetas_clase": [
                    "Riesgo bajo (Q1)",
                    "Riesgo medio-bajo (Q2)",
                    "Riesgo medio-alto (Q3)",
                    "Riesgo alto (Q4)",
                ],
                "filas": [
                    {
                        "valor_original": 0.0,
                        "riesgo_ordinal_estimado": 0.2,
                        "clase_estimacion": "Riesgo bajo (Q1)",
                        "probabilidades": {
                            "Riesgo bajo (Q1)": 0.9,
                            "Riesgo medio-bajo (Q2)": 0.1,
                            "Riesgo medio-alto (Q3)": 0.0,
                            "Riesgo alto (Q4)": 0.0,
                        },
                    },
                    {
                        "valor_original": 3.0,
                        "riesgo_ordinal_estimado": 2.6,
                        "clase_estimacion": "Riesgo alto (Q4)",
                        "probabilidades": {
                            "Riesgo bajo (Q1)": 0.05,
                            "Riesgo medio-bajo (Q2)": 0.05,
                            "Riesgo medio-alto (Q3)": 0.2,
                            "Riesgo alto (Q4)": 0.7,
                        },
                    },
                ],
                "mejor_escenario_menor_riesgo": {
                    "valor_original": 0.0,
                    "riesgo_ordinal_estimado": 0.2,
                    "clase_estimacion": "Riesgo bajo (Q1)",
                    "probabilidades": {
                        "Riesgo bajo (Q1)": 0.9,
                        "Riesgo medio-bajo (Q2)": 0.1,
                        "Riesgo medio-alto (Q3)": 0.0,
                        "Riesgo alto (Q4)": 0.0,
                    },
                },
            },
            {
                "variable": "LONGITUD",
                "etiquetas_clase": [
                    "Riesgo bajo (Q1)",
                    "Riesgo medio-bajo (Q2)",
                    "Riesgo medio-alto (Q3)",
                    "Riesgo alto (Q4)",
                ],
                "filas": [
                    {
                        "valor_original": 5.0,
                        "riesgo_ordinal_estimado": 2.0,
                        "clase_estimacion": "Riesgo medio-alto (Q3)",
                        "probabilidades": {
                            "Riesgo bajo (Q1)": 0.0,
                            "Riesgo medio-bajo (Q2)": 0.2,
                            "Riesgo medio-alto (Q3)": 0.7,
                            "Riesgo alto (Q4)": 0.1,
                        },
                    }
                ],
                "mejor_escenario_menor_riesgo": {
                    "valor_original": 5.0,
                    "riesgo_ordinal_estimado": 2.0,
                    "clase_estimacion": "Riesgo medio-alto (Q3)",
                    "probabilidades": {
                        "Riesgo bajo (Q1)": 0.0,
                        "Riesgo medio-bajo (Q2)": 0.2,
                        "Riesgo medio-alto (Q3)": 0.7,
                        "Riesgo alto (Q4)": 0.1,
                    },
                },
            },
        ],
        "metadata": {"variables_graficadas": ["CNT_TRF", "LONGITUD"], "warnings": []},
    }

    html = render_expert_alignment_tab(
        analysis,
        automatic_simulation_table=table,
        automatic_simulation_analysis=auto_analysis,
        automatic_simulation_cost_context=cost_context,
        automatic_simulation_softmax_curves=softmax_curves,
    )

    assert "Análisis automático de sensibilidad" in html
    assert "CNT_TRF" in html
    assert "LONGITUD" in html
    assert html.index("Variables a priorizar") < html.index("Gráficas del simulador automático")
    assert "Comparación breve del simulador" in html
    assert "Clase de riesgo por variable priorizada" not in html
    assert "Transiciones de categoría detectadas" not in html
    assert "Escala ordinal usada en la gráfica" not in html
    assert "Riesgo bajo -&gt; Riesgo alto" not in html
    assert "Costos aproximados por ítems de contrato" in html
    assert "referencias para discusión económica" in html
    assert "no presupuestos cerrados ni causalidad de intervención" in html
    assert "Contraste con variables priorizadas" in html
    assert "CNT_TRF también aparece en las coincidencias de costos" in html
    assert "Curvas softmax por clase" in html
    assert "Probabilidad softmax promedio" in html
    assert "Valores sugeridos por menor clase dominante" in html
    assert "Estimación económica orientativa para menor riesgo" in html
    assert "Estimación determinística de referencia" in html
    assert "SERVICIO DE INSTALACION DE TRANSFORMADOR TRIFASICO" in html
    assert "&#x27;" not in html
    assert "&amp;#x27;" not in html
    assert "Mayor sensibilidad" in html


def test_expert_alignment_tab_cost_context_degrades_when_no_matches():
    analysis = {
        "contexto": {"fuentes_usadas": ["Agente Descriptor", "Agente predictivo"]},
        "coincidencias": [],
        "diferencias": [],
        "variables_a_priorizar": [],
        "sintesis_final": "Síntesis.",
    }
    table = pd.DataFrame([{"variable": "SIN_MATCH", "magnitud_max_cambio_abs": 0.1}])
    cost_context = {
        "disponible": False,
        "advertencias": ["No se encontraron ítems de costo cercanos para las variables simuladas."],
        "coincidencias": [],
    }

    html = render_expert_alignment_tab(
        analysis,
        automatic_simulation_table=table,
        automatic_simulation_cost_context=cost_context,
    )

    assert "Costos aproximados por ítems de contrato" in html
    assert "No se encontraron ítems de costo cercanos" in html
    assert "No hay coincidencias de costos disponibles para mostrar" in html


# ---------------------------------------------------------------------------
# Real token usage instrumentation (SDD `reporte-perf-optimization`, item 4):
# the report header must label the resolved token source
# (measured/mixed/estimated) passed in via `token_source`, defaulting to
# "estimated" for backward compatibility with callers that never pass it.
# ---------------------------------------------------------------------------


def _render_with_tokens(tmp_path, *, tokens_input, tokens_output, token_source=None):
    raw_df, daily_df = _minimal_raw_and_daily_df()
    kwargs = dict(
        validation_data={"hallazgos": ["algo"]},
        raw_df=raw_df,
        daily_df=daily_df,
        critical_points=[],
        selected_circuitos=["C1"],
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        output_dir=tmp_path,
    )
    if token_source is not None:
        kwargs["token_source"] = token_source
    html_path = render_llm_analysis(**kwargs)
    return html_path.read_text(encoding="utf-8")


def test_header_labels_measured_token_source_without_tilde(tmp_path):
    html = _render_with_tokens(tmp_path, tokens_input=1234, tokens_output=567, token_source="measured")

    assert "Tokens de entrada/salida medidos (medidos)" in html
    assert "entrada 1,234" in html
    assert "salida 567" in html
    assert "~1,234" not in html


def test_header_labels_mixed_token_source(tmp_path):
    html = _render_with_tokens(tmp_path, tokens_input=1234, tokens_output=567, token_source="mixed")

    assert "Tokens parciales disponibles (medidos/estimados; no representan el consumo global)" in html
    assert "~1,234" in html


def test_header_defaults_to_estimated_token_source_label(tmp_path):
    # No `token_source` passed at all -- keep the default source semantics,
    # but label the input/output scope explicitly.
    html = _render_with_tokens(tmp_path, tokens_input=1234, tokens_output=567)

    assert "Tokens parciales disponibles (aproximados; no representan el consumo global)" in html
    assert "~1,234" in html


# ---------------------------------------------------------------------------
# `tokens_total`/`elapsed_seconds` header line -- total tokens across every
# agent stage that ran (including sub-agents dispatched in parallel), plus
# the run's total wall-clock execution time. Independent of the existing
# entrada/salida `tokens_input`/`tokens_output` line above.
# ---------------------------------------------------------------------------


def _render_with_totals(
    tmp_path,
    *,
    tokens_input=None,
    tokens_output=None,
    tokens_total=None,
    elapsed_seconds=None,
    token_source=None,
    token_total_source=None,
):
    raw_df, daily_df = _minimal_raw_and_daily_df()
    kwargs = dict(
        validation_data={"hallazgos": ["algo"]},
        raw_df=raw_df,
        daily_df=daily_df,
        critical_points=[],
        selected_circuitos=["C1"],
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        tokens_total=tokens_total,
        elapsed_seconds=elapsed_seconds,
        output_dir=tmp_path,
    )
    if token_source is not None:
        kwargs["token_source"] = token_source
    if token_total_source is not None:
        kwargs["token_total_source"] = token_total_source
    html_path = render_llm_analysis(**kwargs)
    return html_path.read_text(encoding="utf-8")


def test_header_shows_total_tokens_and_elapsed_time_line(tmp_path):
    html = _render_with_totals(
        tmp_path,
        tokens_input=1234,
        tokens_output=567,
        tokens_total=5000,
        elapsed_seconds=753,
        token_source="measured",
    )

    assert (
        "Tokens totales (todas las etapas, incl. sub-agentes/corridas en paralelo) medidos: 5,000" in html
    )
    assert "Tiempo total de ejecución: 12m 33s" in html


def test_header_can_show_estimated_split_and_measured_total_independently(tmp_path):
    html = _render_with_totals(
        tmp_path,
        tokens_input=1234,
        tokens_output=567,
        tokens_total=5000,
        elapsed_seconds=753,
        token_source="estimated",
        token_total_source="measured",
    )

    assert "Tokens parciales disponibles (aproximados; no representan el consumo global): entrada ~1,234 | salida ~567" in html
    assert (
        "Tokens totales (todas las etapas, incl. sub-agentes/corridas en paralelo) medidos: 5,000" in html
    )


def test_header_formats_elapsed_seconds_over_an_hour_as_hours_minutes(tmp_path):
    html = _render_with_totals(tmp_path, tokens_total=100, elapsed_seconds=3661)

    assert "Tiempo total de ejecución: 1h 1m" in html


def test_header_omits_total_line_when_both_total_and_elapsed_are_none(tmp_path):
    html = _render_with_totals(tmp_path, tokens_input=1234, tokens_output=567)

    assert "Tokens totales" not in html
    assert "Tiempo total de ejecución" not in html


def test_header_total_line_renders_independently_of_entrada_salida_block(tmp_path):
    # tokens_input/tokens_output both None -- the entrada/salida block above
    # is skipped -- but the tokens_total/elapsed_seconds line must still
    # render, since the two blocks are independent.
    html = _render_with_totals(tmp_path, tokens_total=999, elapsed_seconds=65)

    assert "Tokens totales" in html
    assert "Tiempo total de ejecución: 1m 5s" in html
    assert "Tokens de entrada/salida" not in html


def test_header_total_line_shows_na_when_tokens_total_is_none(tmp_path):
    html = _render_with_totals(tmp_path, elapsed_seconds=10)

    assert "Uso total de tokens: no disponible" in html
    assert "Tiempo total de ejecución: 0m 10s" in html


def test_header_total_line_shows_na_when_elapsed_seconds_is_none(tmp_path):
    html = _render_with_totals(tmp_path, tokens_total=42)

    assert "Tiempo total de ejecución: N/D" in html
