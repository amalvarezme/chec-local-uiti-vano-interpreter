"""El boton de encuadre sale del panel y se pone encima del mapa, como en el 01.

El boton afecta SOLO al mapa, y vivia en la ultima fila del panel de control, a media
pantalla de lo que mueve. El tablero de clima ya resolvio esto: su boton va en una
`.barra-encuadre` justo encima de la figura, alineado con el borde donde el mapa empieza.

## La diferencia con el 01, que es la que obliga a medir

En el clima el mapa arranca en el margen IZQUIERDO de la figura, asi que a su barra le
basta `padding-left: {MARGEN_IZQ_FIGURA}px`.

Aqui no. El mapa del 03 es la casilla (1,9) de una rejilla de quince columnas: empieza
pasada la mitad del ancho. Su borde izquierdo en pixeles es

    margen_izquierdo + x0_del_dominio * (ancho - margen_izquierdo - margen_derecho)

y como la figura es responsiva -- sin `width`, con `default_width='100%'` -- eso no es un
numero de pixeles sino un `calc()`: los margenes van en pixeles y el dominio en fraccion.

## Por que el dominio se LEE de la figura y no se escribe a mano

`x0` sale del reparto de columnas y del `horizontal_spacing`. Escribirlo como literal lo
deja a merced de la siguiente vez que alguien toque la rejilla: el numero no fallaria, se
desalinearia en silencio. Se toma de `fig.layout.map.domain.x[0]`, que es la misma fuente
que lee el JS del tablero (`fl.map.domain`).
"""

from __future__ import annotations

import re

from ayudas_tableros import fuente_de_tablero

CUADERNO = "03_uiti_vano_trayectorias_circuitos"


def _fuente() -> str:
    return fuente_de_tablero(CUADERNO, solo_codigo=True)


def _sin_comentarios(fuente: str) -> str:
    return "\n".join(l for l in fuente.splitlines() if not l.lstrip().startswith("#"))


def test_el_boton_ya_no_vive_en_el_panel():
    """Su sitio es el mapa, que es lo unico que mueve."""
    fuente = _fuente()
    panel = re.search(r"PANEL_HTML = f'''(.*?)'''", fuente, re.S)
    assert panel, "no se pudo leer `PANEL_HTML`"
    assert "tr-centrar" not in panel.group(1), (
        "el boton de encuadre sigue dentro del panel de control")


def test_el_boton_va_en_su_barra_encima_de_la_figura():
    """Misma forma que el 01: una `.barra-encuadre` delante de la figura.

    El `id` no cambia -- es de donde cuelga su manejador en `PANEL_JS` --, asi que moverlo
    de sitio no puede romper el JS.
    """
    fuente = _sin_comentarios(_fuente())
    assert "BARRA_ENCUADRE" in fuente, "el 03 no declara su barra de encuadre"
    assert re.search(r'id="tr-centrar"', fuente), "el boton perdio su `id`"
    ensamblado = re.search(r"PANEL_COMPLETO = (.+)", fuente)
    assert ensamblado, "el 03 no ensambla `PANEL_COMPLETO`"
    assert ensamblado.group(1).strip() == (
        "PANEL_HTML + BARRA_ENCUADRE + FIGURA_HTML + PANEL_JS"), (
        f"la barra no va entre el panel y la figura: {ensamblado.group(1).strip()!r}")


def test_la_barra_se_alinea_con_el_MAPA_y_no_con_la_figura():
    """Un `calc()`, porque los margenes van en pixeles y el dominio en fraccion.

    Alinearla con el margen izquierdo de la figura -- que es lo que hace el 01 -- dejaria
    el boton bajo el panel de agrupamiento, que es el vecino de la izquierda.
    """
    fuente = _sin_comentarios(_fuente())
    assert re.search(r"\.barra-encuadre \{\{[^}]*calc\(", fuente), (
        "la barra no calcula su sangria; un padding fijo no sigue a una figura responsiva")
    assert "MAPA_IZQ" in fuente, (
        "la sangria no nombra el borde izquierdo del mapa")


def test_el_borde_del_mapa_se_lee_de_la_figura():
    """Nunca un literal: el dominio sale del reparto de columnas y del espaciado."""
    fuente = _sin_comentarios(_fuente())
    assert re.search(r"MAPA_IZQ\s*=\s*float\(fig\.layout\.map\.domain\.x\[0\]\)", fuente), (
        "`MAPA_IZQ` no se lee de `fig.layout.map.domain.x[0]`")


def test_el_panel_pierde_una_fila_y_aprieta_las_separaciones():
    """Menos alto, para que panel y figura quepan juntos en la pantalla.

    Tres cosas, y las tres se ven en la fuente:
      * el circuito y la ventana comparten fila, en vez de una cada uno;
      * el `gap` de FILA baja, que con cinco bloques apilados era lo que mas pesaba;
      * y la fila entera del boton se fue con el boton.
    """
    fuente = _fuente()
    panel = re.search(r"PANEL_HTML = f'''(.*?)'''", fuente, re.S).group(1)
    filas = len(re.findall(r"flex-basis:\s*100%", panel))
    assert filas <= 2, (
        f"el panel sigue apilando {filas} bloques a lo ancho; con el boton fuera y el "
        f"circuito junto a la ventana tienen que quedar dos")
    gap = re.search(r"\.panel-tray \{\{[^}]*?gap:\s*([^;]+);", panel, re.S)
    assert gap, "el panel no declara `gap`"
    assert gap.group(1).strip() != "18px", (
        "el `gap` sigue siendo el mismo en fila y en columna; el de fila era lo que mas "
        "alto sumaba")
