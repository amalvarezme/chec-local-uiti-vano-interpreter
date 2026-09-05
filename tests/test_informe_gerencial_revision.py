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
