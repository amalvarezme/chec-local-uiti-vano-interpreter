"""Los dos informes comparten identidad visual, y la comparten de UNA fuente.

El informe por circuito y el gerencial son dos productos del mismo proyecto y llegan al
mismo lector. Tenian dos hojas de estilo escritas por separado: distinta tipografia,
distinto marco, y el escudo de CHEC y el pie de los agentes solo en uno de los dos.

Lo que se comparte vive en `informe_estilo` y se INYECTA en las dos plantillas. Copiarlo
en cada archivo es lo que produjo la divergencia, y la volveria a producir.

## La trampa de las llaves

Las dos plantillas son f-strings, asi que escriben sus propias reglas con llaves DOBLES
-- `body {{ ... }}` -- y la f-string las reduce a una al evaluar. Un valor inyectado NO
se vuelve a escanear: sus llaves viajan tal cual. Por eso la hoja compartida se escribe
con llaves SIMPLES.

Equivocarse aqui no da error: `.dn {{ }}` es CSS sintacticamente valido cuyo cuerpo es
la cadena `{ }`, o sea una regla vacia. Ya paso en este repositorio con el diagrama del
menu, que estuvo semanas sin flechas y con la fuente equivocada porque nadie vio la
hoja inerte. De ahi el guardian de abajo.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from chec_local_interpreter.plotting import render_llm_analysis


def _raw_df():
    return pd.DataFrame({
        "CIRCUITO": ["C1"] * 3,
        "FID_VANO": ["V1", "V2", "V3"],
        "FECHA": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
        "UITI_VANO": [1.0, 2.0, 3.0],
        "TOT_USUS": [10, 20, 30],
        "DURACION": [1.0, 2.0, 3.0],
    })


def _css_de(html: str) -> str:
    bloques = re.findall(r"<style[^>]*>(.*?)</style>", html, flags=re.S)
    return "\n".join(bloques)


# --- El guardian de las llaves -------------------------------------------------


@pytest.mark.parametrize("producto", ["circuito", "gerencial"])
def test_ninguna_hoja_de_estilos_sale_con_llaves_dobles(producto, tmp_path):
    """`.clase {{ ... }}` parsea sin error y deja la regla VACIA.

    No hay excepcion: en CSS emitido, una llave doble siempre es una f-string a la que
    se le escapo el escape.
    """
    if producto == "circuito":
        html = render_llm_analysis(
            validation_data={}, raw_df=_raw_df(), selected_circuitos=["C1"],
            inference_results=None, inference_analysis={}, output_dir=tmp_path,
        ).read_text(encoding="utf-8")
    else:
        from chec_local_interpreter.informe_gerencial_contract import _REPORT_CSS

        html = f"<style>{_REPORT_CSS}</style>"

    css = _css_de(html)
    assert css.strip(), "no se encontro ninguna hoja de estilos"
    assert "{{" not in css, "quedaron llaves dobles: esas reglas estan vacias"
    assert "}}" not in css


# --- Lo que las dos comparten --------------------------------------------------


def test_la_hoja_compartida_se_escribe_con_llaves_SIMPLES():
    """Se INYECTA como valor en dos f-strings, y un valor inyectado no se vuelve a
    escanear. Con llaves dobles llegaria doble al HTML."""
    from chec_local_interpreter.informe_estilo import CSS_IDENTIDAD

    assert "{{" not in CSS_IDENTIDAD
    assert CSS_IDENTIDAD.count("{") == CSS_IDENTIDAD.count("}")


@pytest.mark.parametrize("regla", [
    "font-family: 'Segoe UI'",
    ".container",
    ".escudo-chec",
    ".pie-agentes",
    ".logo-labia",
])
def test_las_reglas_de_identidad_estan_en_la_hoja_compartida(regla):
    """Tipografia, marco, escudo y pie: lo que hace que los dos se reconozcan como el
    mismo producto."""
    from chec_local_interpreter.informe_estilo import CSS_IDENTIDAD

    assert regla in CSS_IDENTIDAD


def test_el_informe_por_circuito_usa_la_hoja_compartida(tmp_path):
    from chec_local_interpreter.informe_estilo import CSS_IDENTIDAD

    html = render_llm_analysis(
        validation_data={}, raw_df=_raw_df(), selected_circuitos=["C1"],
        inference_results=None, inference_analysis={}, output_dir=tmp_path,
    ).read_text(encoding="utf-8")

    assert ".escudo-chec" in _css_de(html)
    assert CSS_IDENTIDAD.splitlines()[1].strip() in html or ".container" in _css_de(html)


def test_el_gerencial_usa_la_hoja_compartida():
    from chec_local_interpreter.informe_estilo import CSS_IDENTIDAD
    from chec_local_interpreter.informe_gerencial_contract import _REPORT_CSS

    assert CSS_IDENTIDAD in _REPORT_CSS


# --- El escudo y el pie, en los DOS --------------------------------------------


def test_el_escudo_y_el_pie_viajan_dentro_del_html():
    """Como `data:` URI. Los informes se abren desde cualquier carpeta y se mandan por
    correo: un `<img src="site/...">` da un icono roto en cuanto el archivo se mueve."""
    from chec_local_interpreter.informe_estilo import escudo_chec_html, pie_agentes_html

    escudo = escudo_chec_html()
    pie = pie_agentes_html()

    assert "class='escudo-chec'" in escudo
    assert "data:image/png;base64" in escudo
    assert "Reporte construido por agentes de IA" in pie
    assert "class='logo-labia'" in pie


def test_un_logo_que_falta_no_tumba_el_informe(monkeypatch):
    """Un informe no se pierde por un adorno."""
    from chec_local_interpreter import informe_estilo

    monkeypatch.setattr(informe_estilo, "DIR_LOGOS", Path("/no/existe"))

    assert informe_estilo.escudo_chec_html() == ""
    # El pie SIN logo sigue diciendo quien lo construyo: el texto no es el adorno.
    assert "agentes de IA" in informe_estilo.pie_agentes_html()


def test_el_gerencial_lleva_escudo_y_pie(monkeypatch, tmp_path):
    """Era lo que mas los separaba: el informe por circuito los tenia y el gerencial no,
    aunque los firma el mismo laboratorio y los recibe el mismo lector."""
    from chec_local_interpreter import informe_gerencial_contract as ig

    html = ig.render_managerial_report(
        group={"label": "Muy Alta", "slug": "muy-alta", "circuit_count": 2},
        synthesis={
            "resumen_ejecutivo": ["a"], "patrones_comunes": ["b"],
            "circuitos_atipicos": [], "riesgo_agregado": {"items": ["c"]},
            "acciones_recomendadas": ["d"], "anexo_por_circuito": [],
        },
        raw_df=_raw_df(),
        resolved_window={"fecha_inicio": "2026-01-01", "fecha_fin": "2026-01-03"},
        sampled=["C1"],
    )

    assert "escudo-chec" in html
    assert "Reporte construido por agentes de IA" in html
    assert 'class="container"' in html, "el gerencial sigue sin el marco del informe"
