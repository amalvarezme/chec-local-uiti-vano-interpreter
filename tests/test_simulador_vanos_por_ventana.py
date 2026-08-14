"""Contract tests: la lista de vanos del cuaderno 06 sigue a la VENTANA.

Antes el selector ofrecia todo vano que el mapa dibujara, tuviera o no celdas en
el modelo. Medido sobre 30 circuitos, solo el 21% de esas casillas tenia eventos
en una ventana dada: el usuario marcaba cinco vanos, pulsaba "Simular" y no
aparecia nada, y la unica pista era un renglon de aviso debajo de la lista.

Ahora la lista se recorta a los vanos con eventos en la ventana activa y se
repuebla en cada paso del deslizador. Eso mueve tres cosas que estos tests fijan
contra la fuente del cuaderno (sin ejecutarlo, para que siga siendo rapido),
porque las tres fallan en silencio:

  1. `_vanos_marcables` tiene que recibir la ventana. Sin ella la lista vuelve a
     ser la del circuito entero y el recorte no ocurre en ninguna parte.
  2. El deslizador tiene que REPOBLAR, no solo repintar el mapa. Un observer que
     solo redibuja deja la lista de la ventana anterior sobre el mapa nuevo.
  3. La lista vacia tiene que decir por que. Una caja vacia y muda se lee como
     que el tablero se rompio.

La mecanica del selector -- conservar la seleccion que sobrevive, emitir un solo
cambio de `value`, dibujar el mensaje -- se prueba de verdad, con widgets vivos,
en `tests/test_vano_widgets.py`. Aqui solo se comprueba que el cuaderno la usa.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
NOTEBOOK = (
    RAIZ / "notebooks" / "old_version"
    / "06_uiti_vano_explicabilidad_simulador.ipynb"
)


@pytest.fixture(scope="module")
def fuente() -> str:
    celdas = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    return "\n".join(
        "".join(celda["source"]) for celda in celdas if celda["cell_type"] == "code"
    )


def test_the_markable_vanos_depend_on_the_active_window(fuente):
    """Sin la ventana como argumento no hay recorte posible: la funcion no puede
    saber a que periodo se refiere la pregunta."""
    assert "def _vanos_marcables(circuito, ventana_i):" in fuente


def test_the_markable_vanos_come_from_that_window_cells(fuente):
    """`clases_para(circuito, ventana_i)` trae UNA entrada por vano con celda en
    esa ventana, y ya esta cacheada porque el repintado del mapa la pide igual.
    Derivar la lista de otra fuente -- la geometria, `VANOS_POR_CIRCUITO` -- es
    como se vuelve a ofrecer un vano sin eventos."""
    cuerpo = fuente[fuente.index("def _vanos_marcables(circuito, ventana_i):"):]
    cuerpo = cuerpo[: cuerpo.index("\nvano_widget = ")]
    assert "clases_para(circuito, ventana_i)" in cuerpo
    # La union con la geometria del mapa era justo lo contrario del recorte.
    assert "GEO_POR_CIRCUITO" not in cuerpo


def test_moving_the_window_repopulates_the_list(fuente):
    """El deslizador tiene que repoblar ANTES de repintar. Registrar solo el
    repintado deja la lista de la ventana anterior."""
    assert "def _on_ventana_change(" in fuente
    assert "ventana_widget.observe(_on_ventana_change, names='value')" in fuente
    # El registro suelto del repintado sobre la ventana se sustituyo por el de
    # arriba, que llama a los dos en orden.
    assert "ventana_widget.observe(_redibujar_mapa_historico, names='value')" not in fuente


def test_repopulating_by_window_keeps_what_survives(fuente):
    """Mover el deslizador un paso no puede desmarcar un vano que sigue teniendo
    eventos en la ventana nueva."""
    assert "conservar=True" in fuente


def test_changing_circuit_drops_the_selection_whole(fuente):
    """El universo de vanos es otro: conservar ahi dejaria marcados fids del
    circuito anterior."""
    cuerpo = fuente[fuente.index("def _on_circuito_change("):]
    cuerpo = cuerpo[: cuerpo.index("def _al_hacer_clic(")]
    assert "conservar=" not in cuerpo
    # La ventana se resuelve ANTES de repoblar: repoblar con la ventana del
    # circuito anterior ofreceria los vanos equivocados.
    assert cuerpo.index("ventana_widget.value =") < cuerpo.index("vano_widget.poblar(")


def test_an_empty_window_says_so_in_the_panel(fuente):
    """Es el texto que el usuario ve dentro de la caja de vanos cuando la ventana
    activa no tiene un solo evento en el circuito."""
    assert "mensaje_vacio=" in fuente
    assert "Ventana sin eventos" in fuente


# ------------------------------------------------ el encuadre sigue a la ventana


def test_moving_the_window_reframes_the_base_map(fuente):
    """Mover el deslizador tiene que MOVER el mapa, no solo repintarlo.

    Medido en el navegador antes de este cambio: pasar de V11 a V1 en AGU23L12
    redistribuia las capas de clase (`0,51,30,0,828` -> `42,213,0,0,654`) y
    cambiaba la leyenda, pero dejaba `center` y `zoom` identicos. Como el 86% del
    dibujo es la linea negra de "sin evento", lo unico que se movia era el color
    de unos pocos tramos cortos, y el tablero se leia como que no habia pasado
    nada.
    """
    assert "def _encuadrar_ventana(" in fuente
    cuerpo = fuente[fuente.index("def _on_ventana_change("):]
    cuerpo = cuerpo[: cuerpo.index("def _on_circuito_change(")]
    assert "_encuadrar_ventana(" in cuerpo, (
        "el deslizador repuebla y repinta pero no reencuadra")


def test_the_window_frame_covers_the_vanos_with_events(fuente):
    """El encuadre sale de los vanos CON eventos en esa ventana -- los mismos que
    la lista ofrece --, no de la geometria entera del circuito: encuadrar sobre
    todo el circuito es exactamente la vista que ya habia y que no se movia."""
    cuerpo = fuente[fuente.index("def _encuadrar_ventana("):]
    cuerpo = cuerpo[: cuerpo.index("def _al_hacer_clic(")]
    assert "clases_para(circuito, ventana_i)" in cuerpo
    assert "bounds_de_fids(" in cuerpo
    # Y una ventana sin un solo evento no puede dejar el mapa sobre un punto
    # inventado: se cae a la vista del circuito, que es la que ya existia.
    assert "_vista_del_circuito(circuito)" in cuerpo


def test_only_the_window_reframes_the_base_map(fuente):
    """Marcar un vano NO puede mover el mapa.

    `_redibujar_mapa_historico` corre en cada clic sobre el mapa y en cada
    casilla. Reencuadrar ahi movería el dibujo bajo la mano del usuario justo
    mientras esta marcando, que es peor que no moverse. El reencuadre pertenece
    al deslizador y a nadie mas; para lo demas esta el boton "Centrar mapa base".
    """
    cuerpo = fuente[fuente.index("def _redibujar_mapa_historico("):]
    cuerpo = cuerpo[: cuerpo.index("def _alto_del_mapa_px(")]
    assert "_encuadrar_ventana(" not in cuerpo
    assert "_aplicar_vista(" not in cuerpo
