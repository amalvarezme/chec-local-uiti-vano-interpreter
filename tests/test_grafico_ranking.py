"""La barra de apertura del informe: el ranking de circuitos del cuaderno 02.

Sustituye a la nube de agrupamiento de circuitos. La nube situaba al circuito por tamano
-- eventos contra UITI acumulado --, y la pregunta con la que se abre un informe de
criticidad es en que puesto esta por VANOS CRITICOS y cuantos circuitos tiene por encima.
"""

from __future__ import annotations

import pandas as pd
import pytest

from chec_local_interpreter.plotting import plot_ranking_circuitos
from chec_local_interpreter.ranking_circuitos import COLORES_RANGO


def _base():
    piezas = []
    for circuito, vanos, n, uiti in [
        ("C_ALTO", 6, 30, 40000.0),
        ("C_MEDIO", 3, 11, 850.0),
        ("C_BAJO", 2, 2, 15.0),
        ("C_OTRO", 4, 12, 900.0),
    ]:
        for k in range(vanos):
            fechas = pd.date_range("2026-01-01", periods=n, freq="D").strftime("%Y-%m-%d")
            piezas.append(pd.DataFrame({
                "CIRCUITO": [circuito] * n,
                "FID_VANO": [f"{circuito}_{k}"] * n,
                "FECHA": fechas,
                "UITI_VANO": [uiti / n] * n,
            }))
    return pd.concat(piezas, ignore_index=True)


def test_the_chart_draws_one_bar_per_circuit_of_the_base():
    fig = plot_ranking_circuitos(_base(), "C_ALTO")

    barras = [t for t in fig.data if t.type == "bar"]
    assert len(barras) == 1, "una sola traza de barras, coloreada por banda"
    assert len(barras[0].y) == 4


def test_the_studied_circuit_bar_is_marked_without_stealing_its_band_colour():
    """El color de la barra ES su banda de riesgo, asi que resaltar el circuito
    recoloreandolo mentiria sobre su banda. Se marca con el borde y con una anotacion."""
    fig = plot_ranking_circuitos(_base(), "C_ALTO")

    barra = next(t for t in fig.data if t.type == "bar")
    anchos = list(barra.marker.line.width)
    posicion = list(barra.hovertext).index(
        next(h for h in barra.hovertext if "C_ALTO" in h))
    assert anchos[posicion] > max(
        w for i, w in enumerate(anchos) if i != posicion), "el borde distingue la barra"
    assert barra.marker.color[posicion] in COLORES_RANGO, "el color sigue siendo el de su banda"
    assert any("C_ALTO" in str(a.text) for a in fig.layout.annotations)


def test_the_quartile_cuts_are_drawn_between_bars_not_as_extra_categories():
    """Las divisiones caen en `k - 0.5`, entre la ultima barra de una banda y la primera
    de la siguiente. Sobre un eje de CATEGORIAS Plotly interpreta un x numerico como una
    categoria nueva y las tres lineas se dibujan pegadas al final del eje."""
    fig = plot_ranking_circuitos(_base(), "C_ALTO")

    assert fig.layout.xaxis.type == "linear"
    cortes = next((t for t in fig.data if t.type == "scatter"), None)
    assert cortes is not None
    xs = [x for x in cortes.x if x is not None]
    assert xs, "tiene que haber al menos una division"
    assert all(abs(x - round(x)) == pytest.approx(0.5) for x in xs)


def test_the_axis_is_labelled_with_circuit_names_even_though_it_is_numeric():
    fig = plot_ranking_circuitos(_base(), "C_ALTO")

    assert list(fig.layout.xaxis.ticktext), "los nombres van como ticks"
    assert len(fig.layout.xaxis.tickvals) == len(fig.layout.xaxis.ticktext)


def test_the_title_says_where_the_studied_circuit_stands():
    """Un ranking de 208 barras no se cuenta a ojo: el puesto y el total van escritos."""
    fig = plot_ranking_circuitos(_base(), "C_ALTO")

    titulo = str(fig.layout.title.text)
    assert "C_ALTO" in titulo
    assert "1" in titulo and "4" in titulo, "puesto sobre total"


def test_an_empty_base_returns_an_empty_figure_not_a_crash():
    vacio = pd.DataFrame(columns=["CIRCUITO", "FID_VANO", "FECHA", "UITI_VANO"])

    fig = plot_ranking_circuitos(vacio, "C1")

    assert fig.data == ()


def test_a_circuit_absent_from_the_base_still_renders_the_ranking():
    """Un circuito que no esta en la base no puede dejar al informe sin su grafico de
    apertura: se dibuja el ranking completo, sin barra resaltada."""
    fig = plot_ranking_circuitos(_base(), "NO_EXISTE")

    assert next(t for t in fig.data if t.type == "bar").y is not None
    assert not any("NO_EXISTE" in str(a.text) for a in fig.layout.annotations)


def test_cada_barra_lleva_su_numero_de_ubicacion():
    """La revision pidio el numero de ubicacion en la grafica Y en la tabla.

    Sin el, la barra y la tabla de clasificacion son dos listas de 208 nombres y no hay
    forma de saltar de una a la otra: el rotulo de la barra son 8 px girados noventa
    grados, y el orden de dibujo (de menos a mas critico) es el INVERSO del puesto.
    """
    fig = plot_ranking_circuitos(_base(), "C_ALTO")

    rotulos = list(fig.layout.xaxis.ticktext)
    # El circuito mas critico es el puesto 1 y se dibuja el ULTIMO.
    assert rotulos[-1] == "1. C_ALTO", rotulos[-1]

    puestos = [int(r.split(".", 1)[0]) for r in rotulos]
    # De izquierda a derecha el puesto MEJORA (numero mas bajo). No se exige que sea
    # estrictamente decreciente: `rank(method="min")` reparte el mismo puesto entre
    # circuitos empatados, y dos circuitos con cero vanos criticos estan empatados de
    # verdad -- inventarles un desempate seria afirmar un orden que no existe.
    assert puestos == sorted(puestos, reverse=True), puestos
    assert min(puestos) == 1


def test_el_hover_nombra_los_vanos_probables_de_causa_de_falla():
    """"De N vanos con eventos" era el mismo dato con otro nombre.

    La revision unifico el vocabulario: un vano que aparece en registros de
    interrupcion es un vano probable de causa de falla, y asi se llama en la ficha, en
    la tabla de clasificacion y aqui.
    """
    fig = plot_ranking_circuitos(_base(), "C_ALTO")

    hover = " ".join(list(fig.data[0].hovertext))
    assert "Vanos probables de causa de falla" in hover
    assert "vanos con eventos" not in hover


def test_el_hover_no_llama_eventos_a_los_registros_por_vano():
    """`eventos_total` suma los registros de cada vano, no las interrupciones.

    La misma interrupcion golpea varios vanos, asi que este numero es siempre mayor
    que el de interrupciones y llamarlo "eventos" es lo que hacia que un circuito con
    6.455 interrupciones se leyera como si tuviera 159.470.
    """
    fig = plot_ranking_circuitos(_base(), "C_ALTO")

    hover = " ".join(list(fig.data[0].hovertext))
    assert "Registros vano-evento" in hover


def test_el_titulo_no_deja_entidades_html_sin_decodificar():
    """Plotly no decodifica `&mdash;` en el titulo: lo dibuja tal cual.

    Se veia literalmente "vanos criticos &mdash; DON23L13" en la portada de todos los
    informes. La raya va como caracter, no como entidad.
    """
    fig = plot_ranking_circuitos(_base(), "C_ALTO")

    titulo = fig.layout.title.text
    assert "&mdash;" not in titulo, titulo
    assert "&" not in titulo or "&#" not in titulo
