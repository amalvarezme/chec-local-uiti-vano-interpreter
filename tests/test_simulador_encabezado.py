"""El encabezado del simulador: titulo a la izquierda y boton de cerrar a la derecha.

Tres cosas, y las tres son de la CABECERA, no de la figura:

1. "Simulador Criticidad" deja de ser el titulo de la figura y pasa a ser un rotulo en
   negrita encima del panel de control, arriba a la izquierda.
2. El boton de cerrar va arriba a la DERECHA, en esa misma fila.
3. El panel pierde los rotulos "Circuito" y "Ventana". Los controles se quedan: un
   desplegable de circuitos y un deslizador de ventanas no necesitan que se los nombre
   -- el desplegable muestra el circuito y el deslizador su rango al lado.

## Por que el titulo sale de la figura

Estaba como `title` del `FigureWidget`, o sea dentro del area de dibujo y centrado sobre
ella: a la derecha del panel de control y no encima. Anclarlo ahi ademas competia por el
margen superior con la leyenda de los mapas, que subio antes a ese mismo hueco.

Fuera de la figura es un `widgets.HTML`, que es lo que permite ponerlo a la izquierda del
todo y en la misma fila que el boton.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
TABLERO = RAIZ / "src" / "chec_tableros" / "simulador" / "tablero.py"


def _fuente() -> str:
    return TABLERO.read_text(encoding="utf-8")


def _sin_comentarios(fuente: str) -> str:
    return "\n".join(l for l in fuente.splitlines() if not l.lstrip().startswith("#"))


def test_el_titulo_ya_no_es_el_de_la_figura():
    """Dentro de la figura quedaba centrado sobre el area de dibujo, no sobre el panel."""
    fuente = _sin_comentarios(_fuente())
    assert not re.search(r"title=dict\(text='Simulador Criticidad'", fuente), (
        "'Simulador Criticidad' sigue siendo el titulo de la figura")


def test_el_titulo_va_en_negrita_encima_del_panel():
    """Un `widgets.HTML` en negrita, alineado a la izquierda."""
    fuente = _fuente()
    assert re.search(r"<b>Simulador Criticidad</b>", fuente), (
        "el titulo no va en negrita como rotulo del encabezado")
    assert "ENCABEZADO_TITULO" in fuente, (
        "el rotulo no se declara en un solo sitio")


def test_el_encabezado_pone_el_titulo_a_la_izquierda_y_el_cierre_a_la_derecha():
    """Una fila, con el espacio repartido entre los dos extremos.

    `justify_content='space-between'` y no dos cajas al 50%: el titulo mide lo que mide y
    el boton tambien, y repartir a medias deja a uno de los dos flotando en su mitad.
    """
    fuente = _sin_comentarios(_fuente())
    fila = re.search(r"ENCABEZADO = widgets\.HBox\((.*?)\)\n", fuente, re.S)
    assert fila, "no existe la fila del encabezado"
    assert "space-between" in fila.group(1), (
        f"el encabezado no reparte a los extremos: {fila.group(1)}")
    assert "ENCABEZADO_TITULO" in fila.group(1), (
        "el titulo no esta en la fila del encabezado")


def test_el_panel_pierde_los_rotulos_de_circuito_y_ventana():
    """Sin los rotulos, pero CON sus controles.

    Es la unica parte que se puede leer mal: quitar el rotulo no es quitar el control.
    """
    fuente = _sin_comentarios(_fuente())
    assert "_titulo('Circuito')" not in fuente, "sigue el rotulo 'Circuito'"
    assert "_titulo('Ventana')" not in fuente, "sigue el rotulo 'Ventana'"
    assert "circuito_widget" in fuente, "se fue tambien el desplegable de circuitos"
    assert "ventana_widget" in fuente, "se fue tambien el deslizador de ventanas"
    assert re.search(r"_grupo\(circuito_widget\)", fuente), (
        "el desplegable de circuitos ya no esta en el panel")
    assert re.search(r"_grupo\(ventana_widget\)", fuente), (
        "el deslizador de ventanas ya no esta en el panel")


def test_el_titulo_no_se_parte_en_dos_renglones():
    """En la fila del encabezado comparte ancho con la barra de cerrar.

    Sin `nowrap` se parte en cuanto la ventana se estrecha, que es justo cuando la fila
    empieza a apretar.
    """
    fuente = _fuente()
    assert "white-space:nowrap" in fuente, (
        "el titulo del encabezado puede partirse en dos renglones")


# ----------------------------------------------- el grafo, de vuelta en la figura
#
# Aqui vivian cuatro pruebas que fijaban lo contrario: que el grafo tuviera figura propia,
# que fuera dentro de la columna de controles y que se llevara sus anotaciones. El grafo
# volvio a la figura grande, a una septima fila bajo el costo, y su contrato entero -- fila,
# columnas, titulo y anotaciones -- vive ahora en `test_simulador_grafo_abajo.py`.
#
# No se borran en silencio: se dice donde fueron, que es lo que le falta a un guardian que
# simplemente desaparece.
