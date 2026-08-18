"""El grafo radial de conceptos del informe gerencial, dibujado con Plotly.

Se dibujaba con `vis-network` desde un CDN y viajaba al informe DENTRO de un iframe.
Eso costaba tres cosas concretas:

1. **Otra biblioteca.** El informe por circuito y el gerencial presentan anillos que se
   leen igual y se dibujaban con dos motores distintos; quien mira los dos tiene que
   reconciliar dos comportamientos de zoom, de hover y de arrastre.
2. **El iframe aisla.** Su contenido no hereda ni la hoja de estilos del informe ni su
   `plotly.js`, y no puede crecer con el ancho de la pagina.
3. **Una dependencia mas por CDN**, con su `integrity` fijado a una version.

El MODELO no cambia: `build_graph_elements` sigue siendo la misma funcion pura, con sus
tres anillos y sus posiciones fijas. Lo que cambia es quien lo pinta.
"""

from __future__ import annotations

import math

import pytest


def _nodos_y_aristas():
    """Dos circuitos, una causa compartida y una estrategia que sale de ella."""
    nodes = [
        {"id": "circuito::C1", "kind": "circuito", "label": "C1", "soporte": None,
         "detalle": [], "x": 500.0, "y": 0.0},
        {"id": "circuito::C2", "kind": "circuito", "label": "C2", "soporte": None,
         "detalle": [], "x": -500.0, "y": 0.0},
        {"id": "causa::Vegetación", "kind": "causa", "label": "Vegetación",
         "soporte": 2, "total_circuitos": 2, "circuitos": ["C1", "C2"],
         "detalle": ["C1: ramas sobre la red", "C2: corredor sin podar"],
         "x": 310.0, "y": 0.0},
        {"id": "estrategia::Poda · NR_T", "kind": "estrategia",
         "label": "Poda · NR_T", "soporte": 2, "total_circuitos": 2,
         "prioridad": "alta", "circuitos": ["C1", "C2"],
         "detalle": ["C1: programar poda"], "x": 130.0, "y": 0.0},
    ]
    edges = [
        {"source": "circuito::C1", "target": "causa::Vegetación",
         "kind": "circuito_causa", "weight": 1},
        {"source": "circuito::C2", "target": "causa::Vegetación",
         "kind": "circuito_causa", "weight": 1},
        {"source": "causa::Vegetación", "target": "estrategia::Poda · NR_T",
         "kind": "causa_estrategia", "weight": 2},
    ]
    return nodes, edges


def test_los_tres_anillos_salen_como_trazas_separadas():
    """Circuito, causa y estrategia son tres cosas distintas y la leyenda tiene que
    poder apagarlas por separado -- que es justo lo que un iframe de vis-network no
    dejaba hacer desde el informe."""
    from chec_local_interpreter.intervention_graph import figura_plotly

    fig = figura_plotly(*_nodos_y_aristas())

    nombres = {t.name for t in fig.data if t.mode and "markers" in (t.mode or "")}
    assert nombres == {"Circuitos", "Causas", "Estrategias"}


def test_cada_nodo_conserva_su_posicion_del_modelo():
    """El anillo es una funcion PURA (`build_graph_elements`) y esta figura solo lo
    pinta. Recalcular aqui las posiciones abriria la puerta a que el dibujo y el
    resumen JSON del mismo grafo se separen."""
    from chec_local_interpreter.intervention_graph import figura_plotly

    nodes, edges = _nodos_y_aristas()
    fig = figura_plotly(nodes, edges)

    causas = next(t for t in fig.data if t.name == "Causas")
    assert list(causas.x) == [310.0]
    assert list(causas.y) == [0.0]


def test_la_evidencia_verbatim_de_los_agentes_viaja_en_el_hover():
    """Es lo que el panel lateral del iframe mostraba al hacer clic. Sin iframe, el
    sitio natural es el hover: las frases de los agentes, sin parafrasear."""
    from chec_local_interpreter.intervention_graph import figura_plotly

    fig = figura_plotly(*_nodos_y_aristas())

    causas = next(t for t in fig.data if t.name == "Causas")
    texto = causas.hovertext[0]
    assert "ramas sobre la red" in texto
    assert "2" in texto, "no dice en cuantos circuitos aparece"


def test_la_arista_mas_compartida_se_dibuja_mas_gruesa():
    """El peso es en cuantos circuitos coinciden causa y estrategia. Dibujarlas todas
    igual borra la unica jerarquia que el grafo tiene."""
    from chec_local_interpreter.intervention_graph import figura_plotly

    nodes, edges = _nodos_y_aristas()
    fig = figura_plotly(nodes, edges)

    lineas = [t for t in fig.data if t.mode == "lines"]
    anchos = [t.line.width for t in lineas]
    assert max(anchos) > min(anchos), "todas las aristas salieron del mismo grosor"


def test_los_rotulos_no_se_leen_al_reves():
    """La misma `rotacion_radial` del tablero y del informe: en la mitad izquierda el
    rotulo se gira media vuelta para seguir leyendose de izquierda a derecha."""
    from chec_local_interpreter.intervention_graph import figura_plotly

    fig = figura_plotly(*_nodos_y_aristas())

    angulos = [a.textangle for a in fig.layout.annotations]
    assert angulos
    assert all(-90.0 <= a <= 90.0 for a in angulos), angulos


def test_el_anillo_es_un_circulo_y_no_una_elipse():
    """Sin anclar los ejes, el ancho del contenedor decide la forma y los tres anillos
    dejan de leerse como anillos."""
    from chec_local_interpreter.intervention_graph import figura_plotly

    fig = figura_plotly(*_nodos_y_aristas())

    assert fig.layout.yaxis.scaleanchor == "x"
    assert fig.layout.yaxis.scaleratio == 1


def test_un_grafo_sin_nodos_no_produce_figura():
    """El informe ya sabe callar la seccion; una figura vacia se lee como que no hubo
    ningun concepto compartido, que es otra cosa."""
    from chec_local_interpreter.intervention_graph import figura_plotly

    assert figura_plotly([], []) is None


def test_el_constructor_puede_emitir_plotly_en_vez_de_vis_network(tmp_path):
    """El HTML que se escribe a disco pasa a ser el de Plotly, y sin `vis-network`.

    Se comprueba por lo que NO trae: mientras quede el `<script>` de vis-network, el
    informe sigue cargando dos motores de grafo.
    """
    from chec_local_interpreter.intervention_graph import (
        build_graph_elements,
        render_html_plotly,
    )

    nodes, edges = _nodos_y_aristas()
    html = render_html_plotly(nodes, edges, output_name="grupo.html")

    assert "vis-network" not in html
    assert "plotly" in html.lower()
    assert "Vegetaci" in html
    assert build_graph_elements  # el modelo sigue siendo el mismo, no se toco


# --- Como llega al informe gerencial -------------------------------------------


def test_el_grafo_va_INLINE_y_no_dentro_de_un_iframe(tmp_path):
    """Un iframe aisla: su contenido no hereda la hoja de estilos del informe ni su
    `plotly.js`, y no crece con el ancho de la pagina.

    Con el grafo en Plotly ya no hace falta el aislamiento -- vis-network necesitaba su
    propio documento porque traia su panel lateral y su buscador --, asi que va inline y
    comparte el motor que la pagina ya carga para el dispersograma.
    """
    from chec_local_interpreter.informe_gerencial_contract import _intervention_graph_html

    html = _intervention_graph_html(
        "<div class='plotly-graph-div' id='grafo-conceptos'></div>",
        {"causas": [{"concepto": "Vegetación", "soporte": 2}], "estrategias": []},
        n_sampled=3,
    )

    assert "grafo-conceptos" in html
    assert "<iframe" not in html, "el grafo sigue encerrado en un iframe"


def test_sin_grafo_la_seccion_no_aparece():
    from chec_local_interpreter.informe_gerencial_contract import _intervention_graph_html

    assert _intervention_graph_html(None, None, n_sampled=3) == ""
    assert _intervention_graph_html("<div></div>", None, n_sampled=1) == ""
