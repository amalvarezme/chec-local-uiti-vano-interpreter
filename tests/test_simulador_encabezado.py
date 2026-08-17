"""El encabezado del simulador: el boton de cerrar abre la fila y el titulo va detras.

Tres cosas, y las tres son de la CABECERA, no de la figura:

1. "Simulador Criticidad" deja de ser el titulo de la figura y pasa a ser un rotulo en
   negrita en la cabecera.
2. El boton de cerrar va arriba a la IZQUIERDA, abriendo esa misma fila. Estuvo a la
   derecha, repartido con `space-between`, y ese reparto es lo que lo dejaba en pantalla
   como una sola letra: `flex-shrink` vale 1 por defecto y el boton cedia su ancho.
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


def test_el_encabezado_lleva_el_titulo_y_el_cierre_en_una_sola_fila():
    """Lo que se conserva de este guardian es que los DOS viven en la misma fila.

    Fijaba ademas `space-between`, o sea el titulo a la izquierda y el cierre al otro
    extremo. Ese reparto se cayo: era justo lo que ponia al boton a pelear el ancho con
    el titulo, y quien cedia era el boton -- en pantalla salia como una `C`.

    El orden y la alineacion de ahora se comprueban en
    `test_el_encabezado_pone_el_cierre_a_la_IZQUIERDA_del_titulo`.
    """
    fuente = _sin_comentarios(_fuente())
    fila = re.search(r"ENCABEZADO = widgets\.HBox\((.*?)\)\n", fuente, re.S)
    assert fila, "no existe la fila del encabezado"
    assert "ENCABEZADO_TITULO" in fila.group(1), (
        "el titulo no esta en la fila del encabezado")
    assert "*encabezado" in fila.group(1), (
        "la barra de cerrar no esta en la fila del encabezado")


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


# ------------------------------------------- el boton de cerrar, entero y a la izquierda


def test_el_boton_de_cerrar_no_se_puede_encoger():
    """En la pantalla salia como una `C`: una sola letra.

    `flex-shrink` vale 1 por defecto, asi que un hijo de una caja flexible cede ancho
    aunque lo tenga declarado. El boton pedia 130 px y el navegador se los quitaba hasta
    dejar la inicial -- y un boton que dice `C` no dice que hace.

    `flex: 0 0 auto` es lo que lo saca de ese reparto. El ancho declarado no basta.
    """
    fuente = (RAIZ / "aplicaciones" / "06_simulador" / "cierre.py").read_text(
        encoding="utf-8")
    bloque = fuente[fuente.index('description="Cerrar"'):]
    bloque = bloque[:bloque.index(")\n\n")]
    assert "flex=" in bloque and "0 0 auto" in bloque, (
        f"el boton de cerrar sigue pudiendo encogerse: {bloque[-200:]}")


def test_la_barra_de_cerrar_no_reclama_todo_el_ancho():
    """Con `width: 100%` dentro de la fila del encabezado, la barra empujaba al titulo y
    el reparto acababa comiendose el boton. Mide lo que mide."""
    fuente = (RAIZ / "aplicaciones" / "06_simulador" / "cierre.py").read_text(
        encoding="utf-8")
    cola = fuente[fuente.rindex("return widgets.HBox("):]
    assert 'width="100%"' not in cola, (
        f"la barra de cerrar sigue reclamando el ancho entero: {cola}")


def test_el_encabezado_pone_el_cierre_a_la_IZQUIERDA_del_titulo():
    """Cambio de sitio: estaba a la derecha del todo y pasa a abrir la fila.

    `flex-start` y no `space-between`: repartir a los extremos es lo que dejaba al boton
    peleando por el ancho contra el titulo.
    """
    fuente = _sin_comentarios(_fuente())
    i = fuente.index("ENCABEZADO = widgets.HBox(")
    bloque = fuente[i:fuente.index("APP = widgets.VBox(", i)]
    assert bloque.index("*encabezado") < bloque.index("ENCABEZADO_TITULO"), (
        "el boton de cerrar no va antes que el titulo")
    assert "justify_content='flex-start'" in bloque, (
        f"el encabezado sigue repartiendo a los extremos: {bloque}")


def test_la_barra_de_cerrar_no_empuja_al_titulo():
    """`width: auto` no basta: la clase `.widget-hbox` de ipywidgets la estira igual.

    Medido a 1.280 px de ventana, con la barra suelta el titulo acababa en x=1066 -- o
    sea pegado al borde derecho -- mientras el boton se quedaba en x=45. `flex: 0 0 auto`
    es lo que la deja midiendo lo que mide.
    """
    fuente = (RAIZ / "aplicaciones" / "06_simulador" / "cierre.py").read_text(
        encoding="utf-8")
    cola = fuente[fuente.rindex("return widgets.HBox("):]
    assert 'flex="0 0 auto"' in cola, (
        f"la barra de cerrar sigue estirandose y empuja al titulo: {cola}")


def test_el_output_del_guion_no_ocupa_un_millon_de_pixeles():
    """La causa RAIZ del boton aplastado, y no se ve en el codigo.

    Un `widgets.Output` de ipywidgets nace con `width: 1e+06px` -- medido en el navegador
    sobre la aplicacion servida --. El de la barra de cierre solo lleva
    `display(Javascript(...))`, que no dibuja nada, pero su millon de pixeles competia en
    la fila y el reparto de flexbox se lo quitaba al unico hijo que podia ceder: el boton,
    que acababa mostrando una sola letra.

    El JavaScript sigue ejecutandose: depende de estar en el DOM, no de medir algo.
    """
    fuente = (RAIZ / "aplicaciones" / "06_simulador" / "cierre.py").read_text(
        encoding="utf-8")
    linea = re.search(r"salida = widgets\.Output\(([^)]*)\)", fuente)
    assert linea, "la barra ya no tiene un `Output` para el guion"
    assert 'width="0"' in linea.group(1), (
        f"el `Output` del guion sigue midiendo un millon de pixeles: {linea.group(0)}")
