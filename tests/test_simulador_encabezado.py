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


# ------------------------------------------------- el grafo, fuera de la figura grande


def test_el_grafo_tiene_su_propia_figura():
    """Su sitio pedido es DEBAJO del panel de control y con su ancho.

    El panel es la columna izquierda y la figura grande vive entera en la derecha: un
    subplot no puede salirse de su figura.
    """
    fuente = _sin_comentarios(_fuente())
    assert "_fig_grafo = go.Figure()" in fuente, "no existe la figura del grafo"
    assert "fig_grafo = go.FigureWidget(_fig_grafo)" in fuente, (
        "la figura del grafo no llega a ser un widget")
    assert "'Grafo - Relaciones relevantes" in fuente, (
        "la figura del grafo perdio su titulo")


def test_el_grafo_va_dentro_de_la_columna_de_controles():
    """Es de ahi de donde saca el mismo ancho que el panel."""
    fuente = _sin_comentarios(_fuente())
    assert re.search(r"COLUMNA_CONTROLES = widgets\.VBox\(\s*\[PANEL, fig_grafo\]", fuente), (
        "el grafo no va debajo del panel dentro de la columna de controles")


def test_las_anotaciones_del_grafo_se_fueron_con_el():
    """Sus rotulos se guardan POR POSICION, igual que los avisos de los otros paneles.

    Dejar una a medias en la figura grande correria los indices de las demas sin que nada
    falle: los avisos de los costos y del mapa simulado apuntarian a otra cosa.
    """
    fuente = _sin_comentarios(_fuente())
    assert "_fig_grafo.add_annotation(" in fuente, (
        "las anotaciones del grafo no se crean en su figura")
    assert "fig_grafo.layout.annotations[IDX_ANOTACION_GRAFO]" in fuente, (
        "el aviso del grafo sigue buscandose en la figura grande")
    assert "_anotacion = fig_grafo.layout.annotations[_i_anotacion]" in fuente, (
        "los rotulos de los nodos siguen escribiendose en la figura grande")


def test_la_fila_del_perfil_comparte_con_la_serie_y_va_a_la_mitad():
    """Perfil a la izquierda, UITI acumulado a su derecha, y la fila a mitad de alto.

    El alto de esa fila lo mandaba el diametro del grafo. Sin el, la mitad basta.

    Halvar una fila no es dividir su fraccion por dos: `row_heights` reparte lo que sobra
    DESPUES del espaciado, asi que las seis se recalculan a la vez desde los pixeles
    medidos -- 189,4 | 189,4 | 474,8 | 230 | 230 | 189,4 sobre 1.503 repartibles.
    """
    fuente = _sin_comentarios(_fuente())
    alturas = re.search(r"row_heights=\[([^\]]+)\]", fuente)
    assert alturas, "no se declaran `row_heights`"
    r = [float(x) for x in alturas.group(1).split(",")]
    assert len(r) == 6, f"la figura ya no tiene seis filas: {r}"
    # La fila 3 tiene que valer la mitad de lo que valia, en PIXELES.
    area = 2226 - 106 - 44
    hueco = 0.078 * area
    filas = area - 5 * hueco
    assert abs(r[2] * filas - 237.4) < 6, (
        f"la fila 3 mide {r[2] * filas:.0f} px y tiene que medir 237, la mitad de 475")
    assert abs(r[3] * filas - 230) < 6, (
        f"la fila 4 mide {r[3] * filas:.0f} px; tenia que quedarse en 230")


def test_el_top_de_variables_ocupa_las_cuatro_columnas():
    """Compartia fila con la serie; con la serie arriba se queda con el ancho entero."""
    fuente = _sin_comentarios(_fuente())
    assert re.search(r"\[\{'type': 'xy', 'colspan': 4\}, None, None, None\]", fuente), (
        "el top de variables no ocupa las cuatro columnas")
    assert re.search(r"\), 4, 1\) for _p in range\(TOP_VARIABLES_POR_VANO\)", fuente), (
        "las trazas del top no van a la columna 1")
