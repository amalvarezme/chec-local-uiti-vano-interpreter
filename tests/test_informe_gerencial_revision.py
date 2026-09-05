"""Lo que la revision del informe de circuito le toca tambien al gerencial.

El documento del revisor va sobre el informe por circuito, pero tres de sus
comentarios son sobre VOCABULARIO y valen igual aqui: los dos informes se leen
seguidos, y que uno diga "flota" y el otro "circuitos totales" para lo mismo es
exactamente el problema que el comentario venia a resolver.

Lo que NO se traslada esta anotado en la tabla de aplicacion: la ficha de cabecera y la
tabla de clasificacion no tienen sentido en un informe cuyo sujeto es un GRUPO de
circuitos y no uno solo.
"""

from __future__ import annotations

import pandas as pd
import pytest

from chec_local_interpreter.informe_gerencial_contract import (
    _preambulo_flota_html,
    _preambulo_html,
    _ventanas_html,
    figura_por_ventana,
    figura_preambulo,
)


@pytest.fixture
def base():
    """Tres circuitos con vanos suficientes para que el ranking del panorama agrupe."""
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
def perfil():
    return {
        "circuitos_flota": 208,
        "circuitos": ["C1", "C2"],
        "vanos_banda": 900,
        "vanos_flota": 5000,
        "vanos_criticos_banda": 300,
        "vanos_criticos_flota": 1200,
        "uiti_banda": 12345.6,
        "uiti_flota": 98765.4,
        "pct_criticos_de_la_flota": 25.0,
        "pct_vanos_de_la_flota": 18.0,
        "grupos": [
            {"grupo": "Bajo", "vanos": 100, "pct_banda": 11.1, "vanos_flota": 2000},
            {"grupo": "Medio", "vanos": 500, "pct_banda": 55.6, "vanos_flota": 1800},
            {"grupo": "Medio-Alto", "vanos": 200, "pct_banda": 22.2, "vanos_flota": 900},
            {"grupo": "Alto", "vanos": 100, "pct_banda": 11.1, "vanos_flota": 300},
        ],
    }


@pytest.fixture
def filas_ventana():
    return [
        {"ventana": "V1", "periodo": "2026-01-01 a 2026-01-31", "circuitos": 3,
         "vanos_criticos": 40, "bajan_de_grupo": 12, "alcanzan_bajo": 4},
        {"ventana": "V2", "periodo": "", "circuitos": 2,
         "vanos_criticos": 25, "bajan_de_grupo": 8, "alcanzan_bajo": 2},
    ]


class TestVocabularioCompartido:
    """"Flota" es jerga interna: quien recibe el informe tiene circuitos."""

    def test_el_preambulo_de_toda_la_red_no_dice_flota(self, perfil):
        html = _preambulo_flota_html(perfil, "", {"Riesgo Alto": 7}, ["C1"])
        assert "flota" not in html.lower()
        assert "todos los circuitos" in html.lower() or "circuitos totales" in html.lower()

    def test_el_preambulo_de_una_banda_no_dice_flota(self, perfil):
        html = _preambulo_html(perfil, "", "Riesgo Alto", 2)
        assert "flota" not in html.lower()

    def test_los_vanos_con_eventos_se_llaman_por_su_nombre(self, perfil):
        """Mismo termino que la ficha del informe de circuito y que el hover del ranking."""
        html = _preambulo_flota_html(perfil, "", {"Riesgo Alto": 7}, ["C1"])
        assert "vanos probables de causa de falla" in html.lower()

    def test_el_eje_del_panorama_no_dice_flota(self, perfil, base):
        fig = figura_preambulo(base, ["C1"], perfil, "2026-01-01", "2026-01-31")
        titulos = " ".join(str(eje.title.text or "") for eje in fig.select_xaxes())
        assert "flota" not in titulos.lower()


class TestEntidadesSinDecodificar:
    """Plotly no decodifica entidades, y `_escape` las vuelve a escapar.

    Los dos casos se dibujaban literalmente: "Panorama del grupo &mdash; ..." en el
    titulo de la figura, y una raya `&mdash;` en la columna Período de la tabla de
    ventanas cuando el período venía vacío.
    """

    def test_el_titulo_del_panorama_no_lleva_entidades(self, perfil, base):
        fig = figura_preambulo(base, ["C1"], perfil, "2026-01-01", "2026-01-31")
        assert "&mdash;" not in str(fig.layout.title.text)

    def test_la_tabla_de_ventanas_no_escapa_su_raya(self, filas_ventana):
        html = _ventanas_html(filas_ventana)
        assert "&amp;mdash;" not in html


class TestNoAditividadDeVentanas:
    """La misma advertencia que lleva el informe de circuito.

    Aqui la tabla suma las ventanas de VARIOS circuitos, asi que la tentacion de leer
    una fila total al pie es todavia mayor. Es el error que ya cambio el top 15 de 74
    circuitos una vez.
    """

    def test_la_seccion_por_ventana_advierte_del_traslape(self, filas_ventana):
        html = _ventanas_html(filas_ventana)
        assert "traslapan" in html or "no son aditivos" in html


class TestDegradacion:
    def test_sin_ventanas_no_se_dibuja_la_seccion(self):
        assert _ventanas_html([]) == ""

    def test_la_figura_por_ventana_sigue_saliendo(self, filas_ventana):
        assert figura_por_ventana(filas_ventana) is not None


class TestFichaDelGrupo:
    """Comentario 1, sobre otro sujeto: cuantos son, cuanto pesan, cuanto miden.

    El gerencial abria con el ranking, igual que el informe de circuito: una figura que
    situa al grupo entre los demas antes de decir de que grupo se habla.
    """

    def test_la_ficha_trae_los_valores_generales_del_grupo(self, perfil):
        from chec_local_interpreter.informe_gerencial_contract import ficha_grupo_html

        html = ficha_grupo_html(perfil, ["C1", "C2"], label="Riesgo Alto")
        assert "Vanos probables de causa de falla" in html
        assert "UITI acumulado" in html
        assert "Circuitos del grupo" in html

    def test_sin_perfil_no_dibuja_nada(self):
        from chec_local_interpreter.informe_gerencial_contract import ficha_grupo_html

        assert ficha_grupo_html({}, [], label="x") == ""


class TestExplicacionDeVentanasEnElGerencial:
    """Comentario 2: la seccion por ventana se lee sobre la misma rejilla."""

    def test_la_seccion_explica_como_se_arman_las_ventanas(self, filas_ventana):
        html = _ventanas_html(filas_ventana)
        assert "treinta días" in html
        assert "quince en quince" in html

    def test_la_seccion_advierte_que_describe_lo_observado(self, filas_ventana):
        html = _ventanas_html(filas_ventana)
        assert "no anticipa" in html


class TestCostoDeLasCorridas:
    """El gerencial NO ejecuta agentes: es Python puro, cero tokens.

    Su costo son las corridas de `/report` que sintetiza, y esas ya dejaron
    `stage_timing.json` y `token_usage.json` en disco. Agregar esos archivos no gasta
    nada y contesta la pregunta que el pie del informe abre.
    """

    def _corrida(self, raiz, circuito, marca, *, hist, inf, exp, tokens):
        import json

        d = raiz / circuito / marca
        d.mkdir(parents=True)
        (d / "stage_timing.json").write_text(json.dumps({
            "historical": {"duration_seconds": hist},
            "inference": {"duration_seconds": inf},
            "expert-alignment": {"duration_seconds": exp},
        }), encoding="utf-8")
        (d / "token_usage.json").write_text(json.dumps({
            k: {"total": v} for k, v in tokens.items()}), encoding="utf-8")
        return d

    def test_agrega_tokens_y_reloj_de_las_corridas_sintetizadas(self, tmp_path):
        from chec_local_interpreter.informe_gerencial_contract import costo_de_las_corridas

        raiz = tmp_path / "runs"
        self._corrida(raiz, "C1", "20260101T000000", hist=100.0, inf=200.0, exp=50.0,
                      tokens={"historical": 1000, "inference": 2000, "expert-alignment": 500})
        self._corrida(raiz, "C2", "20260101T000000", hist=300.0, inf=100.0, exp=60.0,
                      tokens={"historical": 3000, "inference": 1000, "expert-alignment": 600})

        costo = costo_de_las_corridas(["C1", "C2"], runs_root=raiz)

        assert costo["corridas"] == 2
        assert costo["tokens_totales"] == 8100

    def test_la_barrera_se_aplica_por_corrida_y_no_a_la_suma(self, tmp_path):
        """`historical` e `inference` van a la vez DENTRO de cada corrida.

        Sumar las duraciones de las dos corridas y aplicar la barrera al total
        afirmaria un paralelismo ENTRE corridas que no existe: se lanzan una tras otra.
        C1 = max(100,200)+50 = 250. C2 = max(300,100)+60 = 360. Total 610.
        """
        from chec_local_interpreter.informe_gerencial_contract import costo_de_las_corridas

        raiz = tmp_path / "runs"
        self._corrida(raiz, "C1", "20260101T000000", hist=100.0, inf=200.0, exp=50.0,
                      tokens={"historical": 1000, "inference": 2000, "expert-alignment": 500})
        self._corrida(raiz, "C2", "20260101T000000", hist=300.0, inf=100.0, exp=60.0,
                      tokens={"historical": 3000, "inference": 1000, "expert-alignment": 600})

        costo = costo_de_las_corridas(["C1", "C2"], runs_root=raiz)

        assert costo["reloj_segundos"] == 610.0
        assert costo["suma_etapas_segundos"] == 810.0
        assert costo["ahorro_segundos"] == 200.0

    def test_sin_corridas_en_disco_devuelve_vacio(self, tmp_path):
        from chec_local_interpreter.informe_gerencial_contract import costo_de_las_corridas

        assert costo_de_las_corridas(["C1"], runs_root=tmp_path / "no-existe") == {}

    def test_el_html_dice_que_el_gerencial_no_gasta_tokens_propios(self, tmp_path):
        from chec_local_interpreter.informe_gerencial_contract import (
            costo_de_las_corridas, costo_corridas_html,
        )

        raiz = tmp_path / "runs"
        self._corrida(raiz, "C1", "20260101T000000", hist=100.0, inf=200.0, exp=50.0,
                      tokens={"historical": 1000, "inference": 2000, "expert-alignment": 500})
        html = costo_corridas_html(costo_de_las_corridas(["C1"], runs_root=raiz))

        assert "no ejecuta agentes" in html
        assert "en paralelo" in html

    def test_sin_costo_no_dibuja_seccion(self):
        from chec_local_interpreter.informe_gerencial_contract import costo_corridas_html

        assert costo_corridas_html({}) == ""


class TestElPerfilTraeElUiti:
    """La ficha del grupo no puede pedir una clave que el perfil no escribe.

    Sin esta prueba, el fixture de arriba seria ficcion: pasaria porque yo se la puse,
    y en produccion la fila de UITI no saldria nunca.
    """

    def test_perfil_de_banda_calcula_el_uiti_del_grupo_y_de_la_red(self, base):
        from chec_local_interpreter.informe_gerencial_contract import perfil_de_banda

        perfil = perfil_de_banda(base, ["C1"], "2026-01-01", "2026-01-31")

        assert perfil["uiti_banda"] > 0
        assert perfil["uiti_flota"] >= perfil["uiti_banda"]
