"""La revision de "Ajuste Reporte criticidad circuito html", aplicada al informe.

Cada prueba de aqui fija UN comentario del revisor. Estan juntas a proposito: cuando
el informe se vuelva a tocar, lo que hay que no romper es la lista de comentarios
atendidos, no la forma concreta de la plantilla.
"""

from __future__ import annotations

import pandas as pd
import pytest

from chec_local_interpreter.plotting import render_llm_analysis


@pytest.fixture
def flota():
    """Tres circuitos con vanos suficientes para que el ranking agrupe y ordene."""
    filas = []
    for circuito, vanos, golpes in (("C1", 12, 5), ("C2", 6, 2), ("C3", 3, 1)):
        for v in range(vanos):
            for g in range(golpes):
                filas.append({
                    "CIRCUITO": circuito,
                    "FID_VANO": f"{circuito}-V{v}",
                    "UITI_VANO": 10.0 * (v + 1) + g,
                    "FECHA": f"2026-01-{(g % 28) + 1:02d}",
                })
    return pd.DataFrame(filas)


@pytest.fixture
def validacion():
    return {
        "executive_summary": [
            "C1 ocupa la posición 1 entre los 3 circuitos de la flota, "
            "con un UITI acumulado alto."
        ],
        "key_findings": [
            {"text": "El circuito muestra afectación sostenida en todo el período."}
        ],
        "cause_hypothesis_note": (
            "Las variables de vegetación concentran la explicación. "
            "El riesgo por vegetación domina. La topología aporta menos."
        ),
        "circuit_characterization": {
            "text": "C1 se caracteriza como circuito de Riesgo Alto dentro de su flota.",
            "ventanas_estudiadas": ["V1 fue la más activa."],
            "probable_justifications_rules": [
                {
                    "modo": "Vegetacion",
                    "variables_asociadas": ["NR_T"],
                    "justificacion_fisico_logica": "El arbolado roza el conductor.",
                    "analisis_causas": "Poda vencida en el tramo rural.",
                }
            ],
        },
        "period_synthesis": "El período cierra con actividad decreciente.",
    }


def _render(tmp_path, flota, validacion=None, **kwargs):
    ruta = render_llm_analysis(
        validation_data=validacion or {},
        raw_df=flota[flota["CIRCUITO"] == "C1"],
        selected_circuitos=["C1"],
        all_circuits_df=flota,
        start_date="2026-01-01",
        end_date="2026-01-31",
        output_dir=tmp_path / "html",
        **kwargs,
    )
    return ruta.read_text(encoding="utf-8")


# --------------------------------------------------------------- cabecera del informe


class TestValoresGeneralesEnLaCabecera:
    """Comentario 1: abrir con los valores generales del circuito."""

    def test_la_cabecera_trae_la_ficha_del_circuito(self, tmp_path, flota, validacion):
        html = _render(tmp_path, flota, validacion)
        assert "Vanos probables de causa de falla" in html
        assert "UITI acumulado del circuito" in html

    def test_la_ficha_va_antes_de_la_barra_del_ranking(self, tmp_path, flota, validacion):
        """La barra situa al circuito entre los demas.

        Esa pregunta solo tiene sentido cuando ya se sabe de que circuito se habla, y
        antes de la ficha el informe no lo decia en ninguna parte.
        """
        html = _render(tmp_path, flota, validacion)
        # `<div class="chart-container">` y no `chart-container` a secas: la clase
        # aparece antes en la hoja de estilos, que no es donde se dibuja nada.
        assert html.index("Vanos probables de causa de falla") < html.index(
            '<div class="chart-container">'
        )

    def test_la_ficha_distingue_vanos_de_registros(self, tmp_path, flota, validacion):
        """El revisor pidio renombrar "cantidad de eventos".

        No se renombra la prosa -- 235 interrupciones no son 235 vanos --, se surte el
        numero de vanos como dato propio y se define la diferencia junto a la tabla.
        """
        html = _render(tmp_path, flota, validacion)
        assert "Registros vano-evento" in html
        assert "registro vano-evento</b> es una fila" in html


class TestExplicacionDeVentanas:
    """Comentario 2: explicar al comienzo como se conforman las ventanas."""

    def test_el_informe_explica_como_se_arman_las_ventanas(self, tmp_path, flota, validacion):
        html = _render(tmp_path, flota, validacion)
        assert "Cómo se construyen las ventanas" in html

    def test_la_explicacion_advierte_del_traslape(self, tmp_path, flota, validacion):
        html = _render(tmp_path, flota, validacion)
        assert "no son aditivos" in html


class TestTablaDeClasificacion:
    """Comentario 3: la clasificacion en tabla, con el numero de ubicacion."""

    def test_la_clasificacion_tambien_va_en_tabla(self, tmp_path, flota, validacion):
        html = _render(tmp_path, flota, validacion)
        assert "Ubicación" in html
        assert "Clasificación de riesgo" in html

    def test_la_tabla_marca_el_circuito_del_informe(self, tmp_path, flota, validacion):
        html = _render(tmp_path, flota, validacion)
        assert "fila-destacada" in html


# ------------------------------------------------------------------- resumen ejecutivo


class TestResumenEjecutivo:
    """Comentario 4: cuatro bloques, y "flota" pasa a "circuitos totales"."""

    def test_el_resumen_lista_las_ventanas_y_los_vanos_de_mayor_impacto(
        self, tmp_path, flota, validacion
    ):
        html = _render(tmp_path, flota, validacion)
        assert "Ventanas de mayor aporte UITI" in html
        assert "Vanos de mayor impacto" in html

    def test_la_palabra_flota_no_sobrevive_en_la_prosa(self, tmp_path, flota, validacion):
        """Se normaliza al pintar, asi que las corridas ya archivadas tambien cambian."""
        html = _render(tmp_path, flota, validacion)
        assert "circuitos de la flota" not in html
        assert "circuitos totales" in html

    def test_los_vanos_de_mayor_impacto_separan_los_dos_criterios(
        self, tmp_path, flota, validacion
    ):
        html = _render(tmp_path, flota, validacion)
        assert "Por UITI acumulado" in html
        assert "Por número de apariciones" in html
        assert "En las dos listas" in html


# ----------------------------------------------------------------- hallazgos y ventanas


class TestHallazgos:
    """Comentarios 5 y 6: notas de lectura, y la caracterizacion se disuelve aqui."""

    def test_la_seccion_de_caracterizacion_desaparece(self, tmp_path, flota, validacion):
        html = _render(tmp_path, flota, validacion)
        assert "Caracterización del Circuito" not in html

    def test_las_justificaciones_sobreviven_dentro_de_hallazgos(
        self, tmp_path, flota, validacion
    ):
        """La seccion se elimina; su contenido util se muda, no se pierde."""
        html = _render(tmp_path, flota, validacion)
        assert "Justificaciones Físico-Lógicas" in html
        assert html.index("Hallazgos del análisis descriptivo") < html.index(
            "Justificaciones Físico-Lógicas"
        )

    def test_las_notas_advierten_que_la_lectura_es_descriptiva(
        self, tmp_path, flota, validacion
    ):
        html = _render(tmp_path, flota, validacion)
        assert "no anticipa el comportamiento futuro" in html

    def test_las_ventanas_estudiadas_van_en_tabla_con_sus_columnas(
        self, tmp_path, flota, validacion
    ):
        html = _render(tmp_path, flota, validacion)
        assert "Registros vano-evento</th>" in html
        assert "<th>Desde</th>" in html


class TestSintesisDelModelo:
    """Comentario 9: la sintesis cierra el numeral 2, no flota suelta."""

    def test_la_sintesis_va_antes_de_la_hipotesis_de_causa(
        self, tmp_path, flota, validacion
    ):
        html = _render(tmp_path, flota, validacion)
        assert html.index("Hallazgos del análisis descriptivo") < html.index(
            "Posible Causa Raíz"
        )


class TestHipotesisDeCausa:
    """Comentario 7: la primera frase es contexto, no una vineta mas."""

    def test_la_primera_frase_no_es_una_vineta(self, tmp_path, flota, validacion):
        html = _render(tmp_path, flota, validacion)
        inicio = html.index("Posible Causa Raíz")
        bloque = html[inicio:inicio + 900]
        assert "hipotesis-contexto" in bloque
        assert bloque.index("hipotesis-contexto") < bloque.index("<ul")


# ------------------------------------------------------------------------------ mapa


class TestVisorDeMapas:
    """Comentario 8: mapa mas bajo, con pantalla completa y flechas."""

    def _con_mapa(self, tmp_path, flota, validacion):
        mapas = [
            {"ventana": f"V{i}", "periodo": "2026-01-01 a 2026-01-31",
             "estudiada": i == 1,
             "base": {"valor": {"C1-V0": 10.0}, "clase": {"C1-V0": "Alto"}},
             "top_uiti": ["C1-V0"]}
            for i in (1, 2)
        ]
        return _render(tmp_path, flota, validacion, mapas_ventana=mapas)

    def test_el_visor_ofrece_pantalla_completa(self, tmp_path, flota, validacion):
        html = self._con_mapa(tmp_path, flota, validacion)
        assert "mapa-pantalla-completa" in html

    def test_el_deslizador_tiene_flechas_a_lado_y_lado(self, tmp_path, flota, validacion):
        html = self._con_mapa(tmp_path, flota, validacion)
        assert "mapa-anterior" in html
        assert "mapa-siguiente" in html


# ------------------------------------------------------------------------ degradacion


class TestDegradacion:
    """Nada de lo anterior puede tumbar un informe sin datos comparativos."""

    def test_sin_flota_el_informe_se_sigue_generando(self, tmp_path, flota):
        html = _render(tmp_path, flota, {})
        assert "<html" in html

    def test_sin_analisis_llm_no_aparecen_secciones_vacias(self, tmp_path, flota):
        html = _render(tmp_path, flota, {})
        assert "Posible Causa Raíz" not in html


class TestComparacionDeVentanas:
    """Comentario 6, segunda mitad: tabla Y resumen comparativo, no una en vez de otra.

    La tabla dice cuanto pesa cada ventana; la comparacion dice cual pesa mas que cual
    y por que, que es lo unico que una tabla de siete columnas no puede dar. Quedarse
    solo con la tabla habria descartado prosa que el agente ya produce y que el
    esquema del historiador sigue exigiendo (`ventanas_estudiadas`).
    """

    def test_la_lectura_comparativa_sobrevive_bajo_la_tabla(
        self, tmp_path, flota, validacion
    ):
        html = _render(tmp_path, flota, validacion)
        assert "Lectura comparativa entre ventanas" in html
        assert "V1 fue la más activa." in html
        assert html.index("<th>Desde</th>") < html.index(
            "Lectura comparativa entre ventanas"
        )


class TestUbicacionDeLasInferencias:
    """Comentario 6b: las inferencias van dentro del analisis por ventana.

    Sueltas al final del informe abrian un bloque nuevo entre lo observado y lo
    proyectado sin decir cual era cual. El revisor las situo en el punto 2.3, que es
    donde estan las ventanas.
    """

    def test_las_inferencias_van_dentro_de_los_hallazgos(self, tmp_path, flota, validacion):
        html = _render(
            tmp_path, flota, validacion,
            inference_analysis={
                "inferencias_predictivas": [
                    {"riesgo": "aumento de UITI", "horizonte": "V7",
                     "justificacion_modelo": "la vegetación domina la relevancia"}
                ]
            },
        )
        assert html.index("2. Hallazgos del análisis descriptivo") < html.index(
            "Inferencias complementarias del modelo"
        )
        assert html.index("Inferencias complementarias del modelo") < html.index(
            "Posible Causa Raíz"
        )

    def test_las_inferencias_se_marcan_como_proyeccion_y_no_como_observacion(
        self, tmp_path, flota, validacion
    ):
        html = _render(
            tmp_path, flota, validacion,
            inference_analysis={
                "inferencias_predictivas": [
                    {"riesgo": "aumento de UITI", "horizonte": "V7",
                     "justificacion_modelo": "la vegetación domina la relevancia"}
                ]
            },
        )
        assert "esto no describe lo observado" in html


class TestSubsecionesNumeradas:
    """El revisor razona en numerales (2.3, 2.7): el informe los lleva."""

    def test_los_hallazgos_llevan_sus_subsecciones_numeradas(
        self, tmp_path, flota, validacion
    ):
        html = _render(tmp_path, flota, validacion)
        for titulo in ("2.1 Comportamiento del circuito",
                       "2.2 Ventanas estudiadas",
                       "2.3 Análisis de vanos",
                       "2.5 Conclusión general del período"):
            assert titulo in html, titulo

    def test_ningun_titulo_repite_al_de_su_seccion(self, tmp_path, flota, validacion):
        """El bloque de hallazgos se titulaba igual que la seccion que lo contiene."""
        html = _render(tmp_path, flota, validacion)
        assert html.count("Hallazgos del análisis descriptivo") == 1


class TestVentanasEstudiadasMarcadas:
    """Solo tres de las once ventanas tienen escenario, diagnostico y plan detras.

    Sin la marca, las once filas de la tabla se leen como equivalentes y quien busque
    en el informe el analisis de la ventana que esta mirando no lo encuentra en ocho
    de los once casos. Es la misma marca que ya lleva el deslizador del mapa.
    """

    def test_la_tabla_marca_las_ventanas_con_diagnostico_detras(
        self, tmp_path, flota, validacion
    ):
        html = _render(
            tmp_path, flota, validacion,
            inference_results={
                "V1": {"contexto": {"nombre": "Ventana V1", "ventana": "V1",
                                    "periodo": "2026-01-01 a 2026-01-31"}}
            },
        )
        assert "estudiada a fondo" in html

    def test_sin_escenarios_ninguna_ventana_se_marca(self, tmp_path, flota, validacion):
        html = _render(tmp_path, flota, validacion)
        assert "estudiada a fondo" not in html


class TestEntidadesHtml:
    """Ninguna entidad HTML puede llegar escapada a la pantalla.

    Se encontro verificando el informe renderizado: el titulo de la figura del ranking
    decia literalmente "vanos criticos &mdash; DON23L13", y el panel del grafo, "se
    mueven juntas &mdash; Ventana V6". Plotly no decodifica entidades en el titulo, y
    `_chart_panel` escapa el suyo, asi que en los dos casos la entidad se dibujaba tal
    cual. No es un comentario del revisor; es un defecto que estaba en todos los
    informes ya emitidos.
    """

    def test_ninguna_entidad_llega_escapada_a_la_pantalla(self, tmp_path, flota, validacion):
        html = _render(tmp_path, flota, validacion)
        assert "&amp;mdash;" not in html
        assert "&amp;middot;" not in html

    def test_el_marcado_de_los_bloques_calculados_no_llega_escapado(
        self, tmp_path, flota, validacion
    ):
        """`_envolver_items` escapa cada item, que es lo correcto para prosa de agente.

        Los bloques calculados por el informe SI traen marcado propio, y pasarlos por
        ahi dibujaba `&lt;b&gt;V2&lt;/b&gt;` en el resumen ejecutivo.
        """
        html = _render(tmp_path, flota, validacion)
        assert "&lt;b&gt;" not in html


class TestLecturaComparativaVacia:
    """`ventanas_estudiadas` no siempre trae prosa.

    En corridas reales el agente entrega a veces solo las etiquetas -- `["V6", "V7",
    "V11"]` --, y eso pintaba un titulo "Lectura comparativa entre ventanas" con tres
    vinetas que decian `V6`, `V7` y `V11`: cero informacion, y encima al lado de una
    tabla que ya trae las once ventanas con sus cifras.
    """

    def test_una_lista_de_solo_etiquetas_no_dibuja_la_seccion(self, tmp_path, flota, validacion):
        validacion["circuit_characterization"]["ventanas_estudiadas"] = ["V6", "V7", "V11"]
        html = _render(tmp_path, flota, validacion)
        assert "Lectura comparativa entre ventanas" not in html

    def test_la_prosa_de_verdad_si_se_dibuja(self, tmp_path, flota, validacion):
        validacion["circuit_characterization"]["ventanas_estudiadas"] = [
            "V6 concentra la mayor densidad de registros del período."
        ]
        html = _render(tmp_path, flota, validacion)
        assert "Lectura comparativa entre ventanas" in html


class TestOrigenDeLasVentanasEstudiadas:
    """La marca tiene que salir con cualquiera de las dos fuentes.

    `inference_results` trae las figuras y `inference_analysis` la interpretacion. Un
    informe rearmado desde el `.out.json` archivado tiene la segunda y no la primera, y
    con una sola fuente perdia la marca sin decir nada.
    """

    def test_los_escenarios_del_analisis_tambien_marcan(self, tmp_path, flota, validacion):
        html = _render(
            tmp_path, flota, validacion,
            inference_analysis={"escenarios": [{"nombre": "Ventana V1", "ventana": "V1"}]},
        )
        assert "estudiada a fondo" in html

    def test_la_ventana_se_lee_del_nombre_del_escenario(self, tmp_path, flota, validacion):
        """Los escenarios archivados no traen clave `ventana`.

        Medido sobre una corrida real: `escenarios[i]` solo tiene
        `nombre: "DON23L13 -- ventana V6"`. Exigir una clave que el artefacto no
        escribe dejaba la marca apagada en todos los informes rearmados.
        """
        html = _render(
            tmp_path, flota, validacion,
            inference_analysis={"escenarios": [{"nombre": "C1 -- ventana V1"}]},
        )
        assert "estudiada a fondo" in html
