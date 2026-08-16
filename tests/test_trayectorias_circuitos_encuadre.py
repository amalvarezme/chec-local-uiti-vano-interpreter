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


def test_el_tablero_entero_cabe_en_una_pantalla_de_portatil():
    """Panel, barra y figura sin scroll en un viewport de 830 px.

    El panel a la mitad NO bastaba, y el numero lo dice: con el panel en 119 px el
    documento seguia en 1.147, de los cuales 960 eran la figura. Borrar el panel entero
    tampoco habria alcanzado.

    El presupuesto, con lo que hay MEDIDO alrededor de la figura:

        panel 119 + su margen 6 + barra del boton 32 + su margen 6
                  + relleno del body 24                      = 187 px fijos
        830 - 187 = 643

    Los dos margenes de 6 px no son un detalle: con 655 el documento MEDIDO daba 842
    contra los 830 de la pantalla, y esos 12 px de mas son exactamente ellos.

    Se fija el `height` porque es el unico numero que se puede elegir: los otros tres
    salen del contenido. Si alguien sube el panel otra vez, esta prueba no lo ve -- lo
    que vigila es que la figura no vuelva a los 960 sin que nadie lo haya decidido.
    """
    fuente = _sin_comentarios(_fuente())
    alto = re.search(r"height=(\d+), template='plotly_white'", fuente)
    assert alto, "la figura del 03 no declara `height`"
    assert int(alto.group(1)) == 643, (
        f"el alto de la figura es {alto.group(1)}; el presupuesto de una pantalla de "
        f"830 px deja 643")

    # El alto y la separacion entre filas NO se pueden elegir por separado.
    # `vertical_spacing` es una FRACCION del area de dibujo: al bajar la figura de 960 a
    # 643 el hueco entre filas se encogia de 97 px a 59, y lo que tiene que caber ahi --
    # el rotulo del eje x de la fila 1 y los titulos de los cuatro paneles de la fila 2 --
    # es TEXTO, que no encoge. Visto en captura: "Numero de eventos en la ventana" se
    # pisaba con "Evolucion (color = grupo)".
    sep = re.search(r"vertical_spacing=([\d.]+)", fuente)
    assert sep and float(sep.group(1)) == 0.19, (
        f"la separacion vertical es {sep.group(1) if sep else None}; con el area nueva "
        f"hace falta 0.19 para conservar los ~94 px que pide el texto")
    area = 643 - 89 - 60
    assert abs(0.19 * area - 94) < 5, (
        f"la separacion ya no da los ~94 px: {0.19 * area:.0f}")
