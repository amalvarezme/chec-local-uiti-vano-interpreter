from __future__ import annotations

import base64

import pandas as pd

from chec_local_interpreter.plotting import render_expert_alignment_tab, render_llm_analysis

# Sentinel distinguishing "kwarg omitted entirely" from "kwarg passed as None"
# for the `stage_breakdown` byte-identical regression-lock tests below.
_UNSET = object()


# ---------------------------------------------------------------------------
# Task 3.5 -- `_figure_html` accepts a persisted PNG path (str/Path), not
# only an open matplotlib figure object, since `_run_inference_simulator`
# (task 3.2) now saves figures to disk and `render()` (task 3.4) only ever
# passes back paths, never live figure objects.
# ---------------------------------------------------------------------------


def _minimal_raw_df():
    raw_df = pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1"],
            "FECHA": ["2026-01-01", "2026-01-02"],
            "UITI_VANO": [10.0, 20.0],
            "FID_VANO": ["V1", "V2"],
        }
    )
    return raw_df


def test_figure_html_embeds_persisted_png_path_as_base64_img(tmp_path):
    png_path = tmp_path / "fig_barras.png"
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"not-a-real-png-but-bytes-are-enough"
    png_path.write_bytes(png_bytes)

    raw_df = _minimal_raw_df()
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
    raw_df = _minimal_raw_df()
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
        selected_circuitos=["TODOS"],
        inference_results=inference_results,
        inference_analysis={},
        output_dir=tmp_path / "html",
    )
    html = html_path.read_text(encoding="utf-8")

    assert "No se pudo renderizar" in html
    # `embedded-figure` y no `<img` a secas: el informe lleva ahora el escudo de CHEC
    # embebido en su cabecera, que es otra imagen y no tiene nada que ver con esta
    # figura. La afirmacion es que la FIGURA ausente no dibuja nada.
    assert "<img class='embedded-figure'" not in html


def _resultado_de_ventana(ventana, nombre, png=None):
    return {
        "fig_serie": png,
        "fig_barras": None,
        "fig_uiti": None,
        "fig_grafo": None,
        "grafo_motivo": "",
        "contexto": {
            "nombre": nombre,
            "ventana": ventana,
            "periodo": "2026-01-01 a 2026-01-31",
            "variables_por_grupo": {
                "Intervencion": [
                    {"knob_id": "ALTURA", "label": "Altura", "grupo": "Intervencion",
                     "n_vanos": 10, "n_vanos_alcanza": 3, "avance_mediano": 0.42,
                     "caida_mediana": 0.8, "valor_tipico": 18.0},
                ],
                "Escenario": [
                    {"knob_id": "clima:wind_spd", "label": "Viento", "grupo": "Escenario",
                     "n_vanos": 10, "n_vanos_alcanza": 7, "avance_mediano": 0.91,
                     "caida_mediana": 1.9, "valor_tipico": 0.0},
                ],
            },
            "simulacion": {
                "knobs_usados": ["ALTURA"],
                "vanos": [
                    {"fid": "V1", "u_base": 90.0, "u_simulado": 12.0,
                     "clase_base": 3, "clase_simulada": 1, "delta_grupo": -2,
                     "pasos": [{"knob_id": "ALTURA", "valor": 18.0}]},
                ],
            },
        },
    }


def test_inference_layout_renders_one_section_per_window(tmp_path):
    """La seccion de figuras del modelo se renderizaba VACIA en todos los informes.

    `_render_inference_layout` buscaba cuatro claves fijas del camino MGCECDL
    (`top_uiti_periodo` y companía), pero `prepare` escribe los escenarios por VENTANA
    desde el port al MIL. Ninguna coincidia, y el informe salia sin una sola figura del
    modelo sin un solo mensaje.
    """
    raw_df = _minimal_raw_df()
    inference_results = {
        "V11": _resultado_de_ventana("V11", "C1 -- ventana V11"),
        "V2": _resultado_de_ventana("V2", "C1 -- ventana V2"),
    }
    inference_analysis = {
        "hallazgos": ["El circuito concentra su criticidad en dos ventanas."],
        "escenarios": [
            {"nombre": "C1 -- ventana V2", "interpretacion": "Lectura de la ventana V2."},
            {"nombre": "C1 -- ventana V11", "interpretacion": "Lectura de la ventana V11."},
        ],
    }

    html = render_llm_analysis(
        validation_data={},
        raw_df=raw_df,
        selected_circuitos=["C1"],
        inference_results=inference_results,
        inference_analysis=inference_analysis,
        output_dir=tmp_path,
    ).read_text(encoding="utf-8")

    assert "Diagnóstico y simulación por ventana" in html
    assert "Ventana V2" in html and "Ventana V11" in html
    assert "Lectura de la ventana V2." in html
    # Orden cronologico: V2 antes que V11, no el alfabetico de las etiquetas.
    assert html.index("Ventana V2") < html.index("Ventana V11")


def test_the_two_variable_groups_render_as_separate_tables(tmp_path):
    """Una racha de viento junto a la poda en la misma tabla ordenada por caida de UITI
    se lee como igual de accionable. Van en dos bloques, cada uno rotulado."""
    html = render_llm_analysis(
        validation_data={},
        raw_df=_minimal_raw_df(),
        selected_circuitos=["C1"],
        inference_results={"V11": _resultado_de_ventana("V11", "C1 -- ventana V11")},
        inference_analysis={},
        output_dir=tmp_path,
    ).read_text(encoding="utf-8")

    assert "Variables de intervención" in html
    assert "Variables de escenario" in html
    assert html.index("Variables de intervención") < html.index("Variables de escenario")
    # El valor viaja con la variable: la fila se lee como una instruccion.
    assert "18" in html and "Altura" in html
    assert "3 / 10" in html, "cuantos vanos alcanzan Bajo con esa sola variable"


def test_the_reduction_scenario_shows_measured_against_simulated_with_its_group(tmp_path):
    """Sin la clase, una caida de UITI no dice si el vano cambio de grupo, que es la
    unidad en la que se decide."""
    html = render_llm_analysis(
        validation_data={},
        raw_df=_minimal_raw_df(),
        selected_circuitos=["C1"],
        inference_results={"V11": _resultado_de_ventana("V11", "C1 -- ventana V11")},
        inference_analysis={},
        output_dir=tmp_path,
    ).read_text(encoding="utf-8")

    assert "Escenario de disminución" in html
    assert "Alto" in html and "Medio" in html
    assert "Palancas movidas (solo intervención): ALTURA" in html


def test_an_empty_inference_results_leaves_the_section_out_without_crashing(tmp_path):
    html = render_llm_analysis(
        validation_data={},
        raw_df=_minimal_raw_df(),
        selected_circuitos=["C1"],
        inference_results=None,
        inference_analysis={},
        output_dir=tmp_path,
    ).read_text(encoding="utf-8")

    assert "Diagnostico y simulacion por ventana" not in html
    assert html.strip()


def _render_with_tokens(tmp_path, *, tokens_input, tokens_output, token_source=None):
    kwargs = dict(
        validation_data={"hallazgos": ["algo"]},
        raw_df=_minimal_raw_df(),
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
    raw_df = _minimal_raw_df()
    kwargs = dict(
        validation_data={"hallazgos": ["algo"]},
        raw_df=raw_df,
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


# ---------------------------------------------------------------------------
# `stage_breakdown` per-stage header rows (PR3 of the report-usage-accounting
# chain, design #327 ADR-2). Additive block placed AFTER the existing
# tokens_total/elapsed_seconds whole-run line, never replacing it. Shape per
# entry: {stage, tokens_total, token_source, duration_seconds, duration_source}
# per `report_pipeline._resolve_stage_breakdown`.
# ---------------------------------------------------------------------------


def _extract_header_h1(html: str) -> str:
    """Pull out the `<h1>...</h1>` header block (contains `title_html`/
    `subtitle_info`, plotting.py L2826) for regression-lock comparisons.

    The rest of the document embeds Plotly figures with randomly generated
    per-call `div` UUIDs, so a full-document byte comparison across two
    separate `render_llm_analysis` calls is never stable even with zero
    behavior change -- the header block itself has no such randomness and is
    the correct byte-identical anchor for the `stage_breakdown` regression
    lock.
    """
    import re as _re

    match = _re.search(r"<h1>.*?</h1>", html, _re.DOTALL)
    assert match, "expected an <h1> header block in the rendered HTML"
    return match.group(0)


def _render_with_stage_breakdown(
    tmp_path, *, stage_breakdown=_UNSET, output_filename="reporte.html", token_source=None
):
    raw_df = _minimal_raw_df()
    kwargs = dict(
        validation_data={"hallazgos": ["algo"]},
        raw_df=raw_df,
        selected_circuitos=["C1"],
        tokens_total=5000,
        elapsed_seconds=753,
        output_dir=tmp_path,
        output_filename=output_filename,
    )
    if stage_breakdown is not _UNSET:
        kwargs["stage_breakdown"] = stage_breakdown
    if token_source is not None:
        kwargs["token_source"] = token_source
    html_path = render_llm_analysis(**kwargs)
    return html_path.read_text(encoding="utf-8")


def test_header_shows_per_stage_rows_when_every_stage_is_measured(tmp_path):
    stage_breakdown = [
        {
            "stage": "historical",
            "tokens_total": 1000,
            "token_source": "measured",
            "duration_seconds": 77.4,
            "duration_source": "measured",
        },
        {
            "stage": "inference",
            "tokens_total": 2000,
            "token_source": "mixed",
            "duration_seconds": 123.1,
            "duration_source": "measured",
        },
        {
            "stage": "expert-alignment",
            "tokens_total": 500,
            "token_source": "estimated",
            "duration_seconds": 65.0,
            "duration_source": "measured",
        },
    ]
    html = _render_with_stage_breakdown(tmp_path, stage_breakdown=stage_breakdown, token_source="measured")

    # Every stage row is present with its token count and its token-source
    # label, plus its duration labeled "medidos" (never estimated).
    assert "historical" in html
    assert "1,000" in html and "medidos" in html
    assert "inference" in html
    assert "2,000" in html and "medidos/estimados" in html
    assert "expert-alignment" in html
    assert "500" in html and "aproximados" in html
    for expected_duration in ("1m 17s", "2m 3s", "1m 5s"):
        assert expected_duration in html
    # The pre-existing whole-run total line is preserved, not replaced.
    assert "Tokens totales (todas las etapas, incl. sub-agentes/corridas en paralelo) medidos: 5,000" in html
    assert "Tiempo total de ejecución: 12m 33s" in html


def test_header_stage_row_shows_na_time_when_duration_missing_for_one_stage(tmp_path):
    stage_breakdown = [
        {
            "stage": "historical",
            "tokens_total": 1000,
            "token_source": "measured",
            "duration_seconds": 77.4,
            "duration_source": "measured",
        },
        {
            "stage": "inference",
            "tokens_total": 2000,
            "token_source": "measured",
            "duration_seconds": None,
            "duration_source": None,
        },
    ]
    html = _render_with_stage_breakdown(tmp_path, stage_breakdown=stage_breakdown)

    assert "2,000" in html  # inference's tokens still shown normally
    assert "N/D" in html
    # historical's own row keeps its measured duration; only inference's
    # Tiempo cell degrades to N/D.
    assert "1m 17s" in html


def test_header_omits_stage_breakdown_block_when_stage_breakdown_is_none(tmp_path):
    baseline_html = _render_with_totals(tmp_path, tokens_total=5000, elapsed_seconds=753)
    html = _render_with_stage_breakdown(tmp_path, stage_breakdown=None)

    assert _extract_header_h1(html) == _extract_header_h1(baseline_html)
    assert "Desglose por etapa" not in html


def test_header_omits_stage_breakdown_block_when_stage_breakdown_is_empty_list(tmp_path):
    baseline_html = _render_with_totals(tmp_path, tokens_total=5000, elapsed_seconds=753)
    html = _render_with_stage_breakdown(tmp_path, stage_breakdown=[])

    assert _extract_header_h1(html) == _extract_header_h1(baseline_html)
    assert "Desglose por etapa" not in html


def test_header_default_stage_breakdown_matches_explicit_none_byte_identical(tmp_path):
    # No `stage_breakdown` kwarg passed at all (uses the PR2-added default of
    # `None`) -- byte-identical regression lock against the pre-PR3 render
    # path, proven by comparing against an explicit `stage_breakdown=None`
    # call rather than merely asserting "no crash".
    html_default = _render_with_stage_breakdown(tmp_path, stage_breakdown=_UNSET)
    html_explicit_none = _render_with_stage_breakdown(tmp_path, stage_breakdown=None)

    assert _extract_header_h1(html_default) == _extract_header_h1(html_explicit_none)


# ---------------------------------------------------------------------------
# Los mapas: el estado observado de las TRES ventanas, sin capa simulada.
# ---------------------------------------------------------------------------


class _MapaFalso:
    """Lo minimo que `_mapas_ventana_html` le pide a un mapa de folium."""

    def __init__(self, etiqueta):
        self.etiqueta = etiqueta

    def get_root(self):
        return self

    def render(self):
        return f"<div>MAPA {self.etiqueta}</div>"


def _mapas_de_tres_ventanas():
    return [
        {"ventana": "V9", "periodo": "2026-03-01 a 2026-03-31", "n_vanos": 103,
         "top_uiti": ["V1"],
         "base": {"valor": {"V1": 3, "V2": 1}, "clase": {"V1": "Alto", "V2": "Medio"}}},
        {"ventana": "V10", "periodo": "2026-04-01 a 2026-04-14", "n_vanos": 102,
         "top_uiti": ["V2"],
         "base": {"valor": {"V1": 2, "V2": 1}, "clase": {"V1": "Medio-Alto", "V2": "Medio"}}},
        {"ventana": "V11", "periodo": "2026-04-15 a 2026-04-30", "n_vanos": 116,
         "top_uiti": ["V1", "V2"],
         "base": {"valor": {"V1": 1, "V2": 0}, "clase": {"V1": "Medio", "V2": "Bajo"}}},
    ]


def _render_con_mapas(tmp_path, monkeypatch, mapas):
    llamadas = []

    def _falso(df, circuito, **kwargs):
        llamadas.append(kwargs)
        return _MapaFalso(len(llamadas))

    monkeypatch.setattr("chec_local_interpreter.plotting.plot_circuit_map_folium", _falso)
    html_path = render_llm_analysis(
        validation_data={},
        raw_df=_minimal_raw_df(),
        selected_circuitos=["C1"],
        inference_results=None,
        inference_analysis={},
        output_dir=tmp_path / "html",
        mapas_ventana=mapas,
    )
    return html_path.read_text(encoding="utf-8"), llamadas


def test_el_informe_dibuja_un_mapa_por_ventana_estudiada(tmp_path, monkeypatch):
    """Tres mapas del mismo circuito en tres momentos, no dos de una sola ventana.

    El par base/simulado respondia "que cambia si va la cuadrilla", que es lo que la
    tabla del plan ya da con numeros y con el delta de grupo por vano. Las tres
    ventanas dicen lo que ninguna tabla dice de un vistazo: DONDE esta el problema en
    el trazado y como se movio.
    """
    html, llamadas = _render_con_mapas(tmp_path, monkeypatch, _mapas_de_tres_ventanas())

    assert len(llamadas) == 3, f"se dibujaron {len(llamadas)} mapas, no tres"
    for ventana in ("V9", "V10", "V11"):
        assert ventana in html, f"falta el mapa de {ventana}"


def test_no_queda_ni_un_mapa_simulado(tmp_path, monkeypatch):
    """La capa simulada se retiro entera, no se dejo de dibujar."""
    html, llamadas = _render_con_mapas(tmp_path, monkeypatch, _mapas_de_tres_ventanas())

    assert "simulado" not in html.lower()
    assert "tras la intervencion" not in html.lower()
    for kwargs in llamadas:
        assert kwargs.get("metric_column") != "grupo_simulado"


def test_los_tres_mapas_pintan_la_clase_observada_de_su_propia_ventana(tmp_path, monkeypatch):
    """Un mapa que repitiera la misma capa tres veces se veria bien y no diria nada."""
    html, llamadas = _render_con_mapas(tmp_path, monkeypatch, _mapas_de_tres_ventanas())

    clases = [dict(k["metric_class_by_vano"]) for k in llamadas]
    assert clases[0]["V1"] == "Alto"
    assert clases[1]["V1"] == "Medio-Alto"
    assert clases[2]["V1"] == "Medio"
    assert len({tuple(sorted(c.items())) for c in clases}) == 3, (
        "los tres mapas llevan la misma capa")


def test_una_ventana_sin_mapa_no_borra_las_otras(tmp_path, monkeypatch):
    """Un circuito sin bolsas en una ventana es un dato, no un fallo del informe."""
    mapas = _mapas_de_tres_ventanas()
    mapas[1]["base"] = {"valor": {}, "clase": {}}

    html, llamadas = _render_con_mapas(tmp_path, monkeypatch, mapas)

    assert len(llamadas) == 2
    assert "V9" in html and "V11" in html


def test_sin_mapas_la_seccion_no_aparece(tmp_path, monkeypatch):
    html, llamadas = _render_con_mapas(tmp_path, monkeypatch, [])

    assert llamadas == []


# ---------------------------------------------------------------------------
# Las variables se nombran en castellano, con su codigo entre parentesis.
# ---------------------------------------------------------------------------


def _html_con_justificaciones(tmp_path, justificaciones):
    ruta = render_llm_analysis(
        validation_data={
            "circuit_characterization": {
                "text": "sintesis",
                "probable_justifications_rules": justificaciones,
            }
        },
        raw_df=_minimal_raw_df(),
        selected_circuitos=["TODOS"],
        inference_results=None,
        inference_analysis={},
        output_dir=tmp_path / "html",
    )
    return ruta.read_text(encoding="utf-8")


def test_las_variables_asociadas_se_escriben_en_castellano_con_su_codigo(tmp_path):
    """En el informe de DON23L14 se leia `Modo Entorno/Riesgo (NR_T, DDT):`.

    Quien lo lee sabe de redes de distribucion, no de nombres de columna de este CSV.
    El codigo se conserva entre parentesis porque es lo que hay que buscar en el
    dataset y en el tablero.
    """
    html = _html_con_justificaciones(tmp_path, [{
        "modo": "Entorno/Riesgo",
        "variables_asociadas": ["NR_T", "DDT"],
        "justificacion_fisico_logica": "j",
        "analisis_causas": "a",
    }])

    assert "Riesgo por vegetación cercana al vano (NR_T)" in html
    assert "Densidad de descargas a tierra (DDT)" in html


def test_una_variable_climatica_conserva_su_rezago_al_traducirse(tmp_path):
    """`temp_3` es la temperatura tres horas antes; perder el `_3` borra justo lo que
    distingue un rezago de otro."""
    html = _html_con_justificaciones(tmp_path, [{
        "modo": "Entorno/Riesgo",
        "variables_asociadas": ["temp_3"],
        "justificacion_fisico_logica": "j",
        "analisis_causas": "a",
    }])

    assert "Temperatura del aire (temp_3)" in html


def test_una_variable_fuera_del_glosario_se_muestra_tal_cual(tmp_path):
    """Sin repetirse: `X (X)` se lee como un fallo del informe."""
    html = _html_con_justificaciones(tmp_path, [{
        "modo": "Otro",
        "variables_asociadas": ["COLUMNA_RARA"],
        "justificacion_fisico_logica": "j",
        "analisis_causas": "a",
    }])

    assert "COLUMNA_RARA" in html
    assert "COLUMNA_RARA (COLUMNA_RARA)" not in html


# ---------------------------------------------------------------------------
# Estilo: las tablas de variables usan una clase que EXISTE.
# ---------------------------------------------------------------------------


def test_ninguna_tabla_usa_una_clase_sin_definir(tmp_path, monkeypatch):
    """Las tablas de intervención y de escenario salían sin divisiones de fila ni
    columna, y no por una decisión de estilo: llevaban `class='report-table'`, una
    clase que el informe NUNCA define. Cero reglas CSS.

    La comprobación es estructural y no una lista de nombres a mano: para cada clase
    que aparece en un `class='...'` de una tabla, la hoja tiene que declararla.
    """
    import re

    html = render_llm_analysis(
        validation_data={},
        raw_df=_minimal_raw_df(),
        selected_circuitos=["C1"],
        inference_results={"V11": _resultado_de_ventana("V11", "C1 -- ventana V11")},
        inference_analysis={},
        output_dir=tmp_path,
    ).read_text(encoding="utf-8")

    hoja = html[html.index("<style>"):html.index("</style>")]
    clases_de_tabla = set(re.findall(r"<table class='([\w-]+)'", html))
    assert clases_de_tabla, "el informe no dibujó ninguna tabla; la prueba no vale"
    for clase in clases_de_tabla:
        assert f".{clase}" in hoja, (
            f"la tabla usa `{clase}` y la hoja no la define: sale sin bordes")


def test_el_panel_del_grafo_ocupa_la_mitad(tmp_path):
    """El anillo es cuadrado y con `width: 100%` se comía una franja del informe tan
    alta como ancha. Se muestra a la mitad y centrado.

    Se reduce lo que se VE, no el PNG: encoger el lienzo dejaría los rótulos de las
    variables ilegibles, que es lo único que el anillo tiene que dejar leer.
    """
    html = render_llm_analysis(
        validation_data={},
        raw_df=_minimal_raw_df(),
        selected_circuitos=["C1"],
        inference_results={"V11": _resultado_de_ventana("V11", "C1 -- ventana V11")},
        inference_analysis={},
        output_dir=tmp_path,
    ).read_text(encoding="utf-8")

    hoja = html[html.index("<style>"):html.index("</style>")]
    assert ".figura-mitad" in hoja, "no existe la regla que reduce el grafo"
    assert "50%" in hoja[hoja.index(".figura-mitad"):hoja.index(".figura-mitad") + 200]


def test_el_escudo_de_chec_va_arriba_a_la_derecha(tmp_path):
    html = render_llm_analysis(
        validation_data={}, raw_df=_minimal_raw_df(), selected_circuitos=["C1"],
        inference_results=None, inference_analysis={}, output_dir=tmp_path,
    ).read_text(encoding="utf-8")

    assert "class='escudo-chec'" in html or 'class="escudo-chec"' in html
    assert "data:image/png;base64" in html, "el escudo tiene que viajar DENTRO del HTML"


def test_el_pie_declara_que_lo_construyeron_agentes(tmp_path):
    """Quien recibe el informe tiene que saber como se produjo, sin buscarlo."""
    html = render_llm_analysis(
        validation_data={}, raw_df=_minimal_raw_df(), selected_circuitos=["C1"],
        inference_results=None, inference_analysis={}, output_dir=tmp_path,
    ).read_text(encoding="utf-8")

    assert "Reporte construido por agentes de IA" in html


# ---------------------------------------------------------------------------
# UN mapa con deslizador, no tres apilados.
# ---------------------------------------------------------------------------


def test_los_mapas_van_en_un_solo_visor_con_deslizador(tmp_path, monkeypatch):
    """Tres mapas apilados obligan a bajar y subir para comparar, y a esa distancia
    la comparación se hace de memoria. En el mismo sitio, uno encima del otro, el
    cambio entre ventanas se ve como un movimiento."""
    html, llamadas = _render_con_mapas(tmp_path, monkeypatch, _mapas_de_tres_ventanas())

    assert len(llamadas) == 3, "se siguen dibujando los tres, uno por ventana"
    assert "type='range'" in html or 'type="range"' in html, "no hay deslizador"
    # prefijo, no cadena exacta: la primera capa lleva ademas ` activa`
    assert html.count("class='mapa-ventana") == 3
    # solo uno visible al abrir
    assert html.count("class='mapa-ventana activa'") == 1


def test_el_deslizador_recorre_las_ventanas_en_orden(tmp_path, monkeypatch):
    html, _ = _render_con_mapas(tmp_path, monkeypatch, _mapas_de_tres_ventanas())

    assert "min='0'" in html and "max='2'" in html
    # el rótulo de cada posición existe para que el deslizador no sea un número suelto
    for ventana in ("V9", "V10", "V11"):
        assert ventana in html


def test_el_mapa_destaca_el_top_15_por_uiti_acumulado(tmp_path, monkeypatch):
    """El color dice el grupo; el destacado dice dónde está el impacto."""
    html, llamadas = _render_con_mapas(tmp_path, monkeypatch, _mapas_de_tres_ventanas())

    destacados = [k.get("vanos_destacados") for k in llamadas]
    assert destacados[0] == {"V1"}
    assert destacados[1] == {"V2"}
    assert destacados[2] == {"V1", "V2"}


def test_un_solo_mapa_no_necesita_deslizador(tmp_path, monkeypatch):
    """Un deslizador de una sola posición es un control que no hace nada."""
    html, _ = _render_con_mapas(tmp_path, monkeypatch, _mapas_de_tres_ventanas()[:1])

    assert "type='range'" not in html
    assert html.count("class='mapa-ventana activa'") == 1


def test_ninguna_cadena_del_informe_se_imprime_sin_tilde(tmp_path, monkeypatch):
    """Guarda contra la reincidencia: el informe salió con 22 "vegetacion" y 23
    "proteccion" porque las cadenas del renderizador seguían la convención de escribir
    el CÓDIGO sin tildes. Estas se imprimen.

    Mira sólo el texto VISIBLE — fuera etiquetas, script, style y los `data:` URI — y
    exime a los códigos de columna, que no se acentúan nunca, y a los plurales que de
    verdad van sin tilde.
    """
    import re

    # CON escenarios: sin ellos no se rinde media pagina -- ni el encabezado
    # "Diagnostico y simulacion por ventana", que fue justo el ultimo que se escapo.
    llamadas = []
    monkeypatch.setattr("chec_local_interpreter.plotting.plot_circuit_map_folium",
                        lambda df, c, **k: (llamadas.append(k), _MapaFalso(1))[1])
    html = render_llm_analysis(
        validation_data={},
        raw_df=_minimal_raw_df(),
        selected_circuitos=["C1"],
        inference_results={"V11": _resultado_de_ventana("V11", "C1 -- ventana V11")},
        inference_analysis={},
        output_dir=tmp_path / "html",
        mapas_ventana=_mapas_de_tres_ventanas(),
    ).read_text(encoding="utf-8")
    cuerpo = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    cuerpo = re.sub(r"data:image/[^\"']+", " ", cuerpo)
    cuerpo = re.sub(r"<[^>]+>", " ", cuerpo)

    correctas = {"protecciones", "condiciones", "intervenciones", "ubicaciones",
                 "relaciones", "opciones", "secciones", "direcciones", "funciones"}
    sospechosas = []
    for palabra in re.findall(r"\b[a-záéíóúñA-ZÁÉÍÓÚÑ]{5,}\b", cuerpo):
        base = palabra.lower()
        if base in correctas or palabra.isupper():  # MAYUSCULAS = codigo de columna
            continue
        if base.endswith(("cion", "sion")) or base in {
                "periodo", "analisis", "critico", "criticos", "tecnico", "metrica",
                "minimo", "maximo", "numero", "electrica", "fisica", "climatica",
                "diagnostico", "hipotesis", "energia", "topologia"}:
            sospechosas.append(palabra)

    assert not sospechosas, f"el renderizador imprime sin tilde: {sorted(set(sospechosas))}"
