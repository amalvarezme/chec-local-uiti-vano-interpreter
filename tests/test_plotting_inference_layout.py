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

    # El desglose por etapa ya no vive en el subtitulo como tabla gris: ahora
    # es la figura "Como se construyo este informe" al final del documento
    # (`agentes_linea_tiempo.seccion_agentes_html`), alimentada por ESTE mismo
    # `stage_breakdown`. Lo que se verifica sigue siendo lo mismo -- cada etapa
    # con su cifra y su tiempo -- en el sitio nuevo y con su formato.
    assert "Cómo se construyó este informe" in html

    # Una etapa por fila, con sus tokens en formato espanol. La procedencia se
    # marca fila a fila con `~` (la convencion que el informe ya usaba para
    # "esto es aproximado"): `historical` es measured y va limpia; las otras dos
    # no lo son y van marcadas.
    assert "historical" in html and ">1.000<" in html
    assert "inference" in html and ">~2.000<" in html
    assert "expert-alignment" in html and ">~500<" in html

    # Duraciones medidas, en el formato mm:ss de la figura.
    for esperado in ("1:17", "2:03", "1:05"):
        assert esperado in html

    # Y el hecho que la tabla vieja no podia contar: dos de esas etapas corren
    # a la vez, asi que el reloj de pared (2:03 + 1:05) es menor que la suma.
    assert "en paralelo" in html

    # La linea de totales de toda la corrida se conserva, no se reemplaza.
    assert "Tokens totales (todas las etapas, incl. sub-agentes/corridas en paralelo) medidos: 5,000" in html
    # El tiempo sale de las ETAPAS con su barrera -- max(77,4; 123,1) + 65,0 = 188,1 s --
    # y no de `elapsed_seconds=753`, que mide desde que nacio el `run_dir` hasta este
    # render y crece con cada repintado.
    assert "Tiempo total de ejecución: 3m 8s" in html
    assert "12m 33s" not in html


def test_como_se_construyo_vive_dentro_de_la_pestana_del_informe(tmp_path):
    """"Cómo se construyó este informe" pertenece al INFORME, no a la comparación.

    Estaba inyectada fuera del contenedor de pestañas, asi que se dibujaba una sola vez
    pero quedaba visible bajo LAS DOS: quien abria "Comparación con reportes expertos"
    veia debajo la linea de tiempo de los tres agentes, que no explica nada de esa
    pestaña -- la comparacion se lee contra los PDF de los expertos, no contra el reloj
    de la corrida. Es un fallo de pertenencia, no de duplicado: buscar la cadena en el
    HTML entero no lo habria visto nunca, por eso esta prueba mira POR PANEL.
    """
    import re

    html = _render_with_stage_breakdown(
        tmp_path,
        stage_breakdown=[{"stage": "historical", "tokens_total": 1000,
                          "token_source": "measured", "duration_seconds": 77.4,
                          "duration_source": "measured"}],
        token_source="measured",
    )

    def _panel(panel_id):
        inicio = html.index(f'id="{panel_id}"')
        fin = html.index("</section>", inicio)
        return html[inicio:fin]

    assert "Cómo se construyó este informe" in _panel("tab-informe")
    assert "Cómo se construyó este informe" not in _panel("tab-expertos")

    # Y una sola vez en todo el documento: moverla no puede dejar una copia atras.
    assert len(re.findall("Cómo se construyó este informe", html)) == 1


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

    # `inference` sigue mostrando sus tokens con normalidad...
    assert ">2.000<" in html
    # ...y `historical` conserva su duracion medida. Solo se degrada la barra
    # de `inference`, que sin duracion se dibuja en su ancho minimo en vez de
    # inventar uno.
    assert "1:17" in html
    assert "0:00" in html


def _seccion_construccion(html: str) -> str:
    """El bloque «¿Cómo se construyó este informe?», acotado a su propia caja."""
    marca = "¿Cómo se construyó este informe?"
    if marca not in html:
        return ""
    i = html.index(marca)
    # La caja abre justo antes del h2 y cierra en el </div> que la cierra a ella.
    return html[html.rindex("<div class=\"content-box\"", 0, i):html.index("</div>", html.index("</table>", i)) + 6] \
        if "</table>" in html[i:] else html[i:i + 4000]


def test_el_encabezado_ya_no_lleva_tokens_ni_modelo_ni_tiempos(tmp_path):
    """Esa informacion es sobre la CORRIDA, no sobre el circuito.

    Estaba en el subtitulo, encima del nombre del circuito, donde lo primero que leia
    quien abre el informe eran cifras de consumo de un modelo de lenguaje. El informe
    trata de un circuito electrico; el costo de producirlo es una nota al pie, y ese pie
    ya existe -- la seccion del final de la primera pestaña.
    """
    html = _render_with_stage_breakdown(
        tmp_path,
        stage_breakdown=[{"stage": "historical", "tokens_total": 1000,
                          "token_source": "measured", "duration_seconds": 77.4,
                          "duration_source": "measured"}],
        token_source="measured",
    )
    encabezado = _extract_header_h1(html)

    assert "Período de análisis" in encabezado, "el periodo SI pertenece al encabezado"
    for fuera in ("Modelo LLM", "Tokens totales", "Tiempo total de ejecución",
                  "Tokens de entrada/salida"):
        assert fuera not in encabezado, f"«{fuera}» sigue en el encabezado"


def test_la_seccion_de_construccion_recoge_modelo_tokens_y_tiempo(tmp_path):
    """Lo que sale del encabezado tiene que APARECER abajo, no desaparecer."""
    html = _render_with_stage_breakdown(
        tmp_path,
        stage_breakdown=[{"stage": "historical", "tokens_total": 1000,
                          "token_source": "measured", "duration_seconds": 77.4,
                          "duration_source": "measured"}],
        token_source="measured",
    )
    seccion = _seccion_construccion(html)

    assert seccion, "no se encontro la seccion de construccion"
    assert "Modelo" in seccion
    assert "Tokens totales" in seccion
    assert "Tiempo total de ejecución" in seccion


def test_el_tiempo_total_sale_de_las_etapas_y_no_del_reloj_del_run_dir(tmp_path):
    """El reloj del `run_dir` mide desde que se creo la carpeta hasta que se renderiza.

    Eso incluye todo lo que paso en medio -- y, sobre todo, CADA re-render: una corrida
    de doce minutos leia "4h 45m" despues de repintarla cuatro veces en el dia. El numero
    se infla sin que cambie nada de la corrida, que es la definicion de una medida que no
    se puede usar.

    Las duraciones por etapa si son estables, y su composicion con la barrera de
    paralelismo -- max(historical, inference) + expert-alignment -- es el reloj de pared
    de los agentes. Aqui: max(100, 200) + 50 = 250 s.
    """
    html = _render_with_stage_breakdown(
        tmp_path,
        stage_breakdown=[
            {"stage": "historical", "tokens_total": 1, "token_source": "measured",
             "duration_seconds": 100.0, "duration_source": "measured"},
            {"stage": "inference", "tokens_total": 1, "token_source": "measured",
             "duration_seconds": 200.0, "duration_source": "measured"},
            {"stage": "expert-alignment", "tokens_total": 1, "token_source": "measured",
             "duration_seconds": 50.0, "duration_source": "measured"},
        ],
        token_source="measured",
    )

    assert "Tiempo total de ejecución: 4m 10s" in html
    # El del run_dir es OTRO numero y no puede colarse.
    assert "4h 45m" not in html


def test_no_es_la_suma_de_las_tres_etapas(tmp_path):
    """Sumarlas daria 350 s y afirmaria que las tres corrieron una detras de otra. Dos
    van a la vez, y ese es justamente el hecho que la figura existe para contar."""
    html = _render_with_stage_breakdown(
        tmp_path,
        stage_breakdown=[
            {"stage": "historical", "tokens_total": 1, "token_source": "measured",
             "duration_seconds": 100.0, "duration_source": "measured"},
            {"stage": "inference", "tokens_total": 1, "token_source": "measured",
             "duration_seconds": 200.0, "duration_source": "measured"},
            {"stage": "expert-alignment", "tokens_total": 1, "token_source": "measured",
             "duration_seconds": 50.0, "duration_source": "measured"},
        ],
        token_source="measured",
    )

    assert "Tiempo total de ejecución: 5m 50s" not in html


def test_sin_desglose_el_tiempo_cae_al_reloj_del_run_dir(tmp_path):
    """Sin etapas no hay nada que componer, y el reloj del `run_dir` es lo unico que
    queda. Es peor medida, pero es una medida; callarla seria perder el dato."""
    html = _render_with_totals(tmp_path, tokens_total=5000, elapsed_seconds=753)

    assert "Tiempo total de ejecución: 12m 33s" in html


def test_sin_desglose_por_etapa_el_resumen_sigue_apareciendo(tmp_path):
    """Una corrida sin `stage_breakdown` tiene igualmente modelo, tokens y reloj.

    Antes la seccion entera se omitia, y con ella se iba la unica copia de esos datos.
    Ahora la caja se dibuja con el resumen y SIN la tabla por etapa, que es lo que de
    verdad falta.
    """
    html = _render_with_stage_breakdown(tmp_path, stage_breakdown=None)

    assert "¿Cómo se construyó este informe?" in html
    assert "Tiempo total de ejecución" in html
    # La tabla por etapa no se inventa: sin desglose no hay etapas que listar.
    assert "<th>Agente</th>" not in html


def test_una_corrida_solo_de_visualizacion_no_dibuja_la_seccion(tmp_path):
    """Sin analisis de modelo no hay nada que contar sobre como se construyo."""
    raw_df = _minimal_raw_df()
    ruta = render_llm_analysis(
        validation_data=None, raw_df=raw_df, selected_circuitos=["C1"],
        output_dir=tmp_path, output_filename="solo_viz.html",
    )
    html = ruta.read_text(encoding="utf-8")

    assert "¿Cómo se construyó este informe?" not in html


def test_header_omits_stage_breakdown_block_when_stage_breakdown_is_none(tmp_path):
    baseline_html = _render_with_totals(tmp_path, tokens_total=5000, elapsed_seconds=753)
    html = _render_with_stage_breakdown(tmp_path, stage_breakdown=None)

    assert _extract_header_h1(html) == _extract_header_h1(baseline_html)
    # La caja sigue, con el resumen; lo que no se dibuja es la tabla por etapa.
    assert "<th>Agente</th>" not in html


def test_header_omits_stage_breakdown_block_when_stage_breakdown_is_empty_list(tmp_path):
    baseline_html = _render_with_totals(tmp_path, tokens_total=5000, elapsed_seconds=753)
    html = _render_with_stage_breakdown(tmp_path, stage_breakdown=[])

    assert _extract_header_h1(html) == _extract_header_h1(baseline_html)
    # La caja sigue, con el resumen; lo que no se dibuja es la tabla por etapa.
    assert "<th>Agente</th>" not in html


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


def test_el_pie_lleva_el_logo_del_laboratorio(tmp_path):
    """El texto dice QUE lo construyeron agentes; el logo dice QUIEN los opera.

    Va junto al texto y no arriba con el escudo de CHEC: el escudo identifica a quien
    OPERA la red -- el destinatario del informe -- y el laboratorio a quien lo produjo.
    Ponerlos juntos arriba los leeria como dos marcas del mismo emisor.
    """
    html = render_llm_analysis(
        validation_data={}, raw_df=_minimal_raw_df(), selected_circuitos=["C1"],
        inference_results=None, inference_analysis={}, output_dir=tmp_path,
    ).read_text(encoding="utf-8")

    assert "class='logo-labia'" in html or 'class="logo-labia"' in html
    pie = html[html.index("pie-agentes"):]
    assert "logo-labia" in pie[:900], "el logo va DENTRO del pie, no suelto en la página"
    assert html.count("data:image/png;base64") >= 2, (
        "el logo tiene que viajar DENTRO del HTML, como el escudo"
    )


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


def _mapas_de_todas_las_ventanas():
    """Once ventanas, de las que solo tres tienen escenario detrás."""
    mapas = []
    for i in range(1, 12):
        mapas.append({
            "ventana": f"V{i}",
            "periodo": f"2025-{i:02d}",
            "n_vanos": 100 + i,
            "top_uiti": ["V1"],
            "estudiada": i in (9, 10, 11),
            "base": {"valor": {"V1": 3, "V2": 1},
                     "clase": {"V1": "Alto", "V2": "Medio"}},
        })
    return mapas


def test_el_deslizador_recorre_las_once_ventanas(tmp_path, monkeypatch):
    """El informe ESTUDIA tres ventanas; el mapa las recorre todas.

    Estudiar tres recorta la parte cara -- relevancia, diagnóstico y simulación por
    ventana --, y el mapa no es esa parte. Con solo tres posiciones, ocho saltos del
    circuito quedaban sin dibujar y el lector tenía que reconstruir de memoria cómo se
    movió el problema por el trazado.
    """
    html, llamadas = _render_con_mapas(tmp_path, monkeypatch,
                                       _mapas_de_todas_las_ventanas())

    assert len(llamadas) == 11
    assert html.count("class='mapa-ventana") == 11
    assert "max='10'" in html
    assert html.count("class='mapa-ventana activa'") == 1


def test_las_ventanas_estudiadas_se_distinguen_en_el_deslizador(tmp_path, monkeypatch):
    """Solo tres de las once tienen diagnóstico y plan detrás.

    Sin marca, las once posiciones se leen como equivalentes, y quien busque en el
    informe el escenario de la ventana que está viendo no lo va a encontrar en ocho de
    los once casos.
    """
    html, _ = _render_con_mapas(tmp_path, monkeypatch, _mapas_de_todas_las_ventanas())

    assert html.count("class='marca-estudiada'") == 3
    # y la capa lo dice con palabras, no solo con un estilo
    assert html.count("con diagnóstico y plan en este informe") == 3


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


# ---------------------------------------------------------------------------
# Los tres paneles del tablero, INTERACTIVOS dentro del informe
# ---------------------------------------------------------------------------


def test_una_figura_guardada_como_json_se_embebe_interactiva_y_no_como_imagen(tmp_path):
    """El informe dibujaba estos tres paneles en matplotlib y los pegaba como PNG.

    Son los MISMOS que el simulador presenta vivos, y en imagen se pierde el hover, que
    es donde vive el nombre completo de cada variable y el desglose de cada barra.
    """
    import plotly.graph_objects as go

    from chec_local_interpreter.mil_figuras_interactivas import figura_top_variables

    figura = figura_top_variables({
        "vanos": {"V1": {"variables": [
            {"knob_id": "NR_T", "label": "Riesgo por vegetación", "caida": 1.2,
             "valor_optimo": 0.0, "alcanza": True}]}}})
    ruta = tmp_path / "V9_top.json"
    ruta.write_text(figura.to_json(), encoding="utf-8")

    html = render_llm_analysis(
        validation_data={}, raw_df=_minimal_raw_df(), selected_circuitos=["C1"],
        inference_results={"V9": {"fig_barras": str(ruta), "contexto": {}}},
        inference_analysis={}, output_dir=tmp_path / "html",
    ).read_text(encoding="utf-8")

    assert "plotly" in html.lower(), "no se embebio ninguna figura de Plotly"
    assert "NR_T" in html
    assert isinstance(figura, go.Figure)


def test_el_informe_carga_plotly_aunque_no_haya_figura_de_ranking(tmp_path):
    """`plotly.js` viajaba DENTRO de la figura del ranking, y las demas se embeben con
    `include_plotlyjs=False`.

    Un informe sin ranking dejaba mudas a todas las otras: los paneles se montaban en un
    `<div>` sin biblioteca que los dibujara, y eso no da error -- da un hueco en blanco.
    """
    html = render_llm_analysis(
        validation_data={}, raw_df=_minimal_raw_df(), selected_circuitos=["C1"],
        inference_results=None, inference_analysis={}, output_dir=tmp_path,
    ).read_text(encoding="utf-8")

    assert "cdn.plot.ly" in html, "el informe no carga plotly.js por su cuenta"


def test_un_json_ilegible_no_se_lleva_el_informe(tmp_path):
    """Un panel se pierde; la corrida no."""
    roto = tmp_path / "V9_top.json"
    roto.write_text("{esto no es json", encoding="utf-8")

    html = render_llm_analysis(
        validation_data={}, raw_df=_minimal_raw_df(), selected_circuitos=["C1"],
        inference_results={"V9": {"fig_barras": str(roto), "contexto": {}}},
        inference_analysis={}, output_dir=tmp_path / "html",
    ).read_text(encoding="utf-8")

    assert "No se pudo renderizar la figura" in html


# ---------------------------------------------------------------------------
# La tabla del escenario: lo MEDIDO es lo medido
# ---------------------------------------------------------------------------


def _simulacion_con_observado():
    return {
        "knobs_usados": ["NR_T"],
        "vanos": [
            {"fid": "V1", "u_base": 9.0, "u_simulado": 2.0, "u_observado": 7.5,
             "clase_base": 3, "clase_simulada": 1, "delta_grupo": -2,
             "pasos": [{"knob_id": "NR_T", "valor": 0.0}]},
        ],
    }


def test_la_columna_UITI_medido_muestra_el_medido_y_no_la_base_del_modelo(tmp_path):
    """La cabecera decia "UITI medido" y la celda traia `u_base`, que es la base del
    MODELO.

    No es un detalle de nombre: las dos cantidades son de naturaleza distinta y el
    modelo corre +34% sobre el observado, medido sobre 599 bolsas. Presentar su
    prediccion bajo el rotulo "medido" convierte el sesgo del modelo en un dato de la
    base, y la diferencia con la simulada se lee como ahorro.
    """
    html = render_llm_analysis(
        validation_data={}, raw_df=_minimal_raw_df(), selected_circuitos=["C1"],
        inference_results={"V9": {"contexto": {"simulacion": _simulacion_con_observado()}}},
        inference_analysis={}, output_dir=tmp_path,
    ).read_text(encoding="utf-8")

    fila = html[html.index("<td style='text-align:left;'>V1</td>"):][:400]
    assert "7,5" in fila or "7.5" in fila, "la columna medida sigue trayendo la base del modelo"


def test_sin_uiti_observado_la_columna_se_llama_por_lo_que_es(tmp_path):
    """Un artefacto sin `u_observado` deja al informe sin la mitad medida. Se cae a la
    base del modelo y se DICE en la cabecera, en vez de seguir llamandola medida."""
    simulacion = _simulacion_con_observado()
    simulacion["vanos"][0].pop("u_observado")

    html = render_llm_analysis(
        validation_data={}, raw_df=_minimal_raw_df(), selected_circuitos=["C1"],
        inference_results={"V9": {"contexto": {"simulacion": simulacion}}},
        inference_analysis={}, output_dir=tmp_path,
    ).read_text(encoding="utf-8")

    assert "UITI base del modelo" in html
    assert ">UITI medido<" not in html


def test_la_tabla_dice_si_el_vano_BAJA_DE_GRUPO_y_no_solo_si_llega_a_bajo(tmp_path):
    """Bajar de Alto a Medio-Alto es una mejora real.

    Medido sobre DON23L14: en V9, 91 de 93 vanos en Alto reciben un plan que baja el
    UITI y NO cambia el grupo. Sin decirlo, esos 91 y los 2 que si bajan se leen igual.
    """
    html = render_llm_analysis(
        validation_data={}, raw_df=_minimal_raw_df(), selected_circuitos=["C1"],
        inference_results={"V9": {"contexto": {"simulacion": _simulacion_con_observado()}}},
        inference_analysis={}, output_dir=tmp_path,
    ).read_text(encoding="utf-8")

    assert "Baja de grupo" in html
