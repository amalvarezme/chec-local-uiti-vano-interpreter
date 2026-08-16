"""El tablero 03 vuelve a apilarse: panel arriba a lo ancho, figura debajo a lo ancho.

El reparto en dos columnas (controles al 30%, figuras al 70%) sigue siendo el bueno para
el 01 y el 04. Aqui no: el panel del 03 es una barra que ya nace preparada para el ancho
entero -- `.panel-tray` declara `width: 100%`, `display: flex` y `flex-wrap: wrap` en su
propio `<style>` --, y meterla en una columna estrecha obligaba a un bloque de CSS que
le daba la vuelta a todo eso: le cambiaba la direccion, le partia las filas y vencia con
`!important` los `min-width` que sus controles traen en linea.

Apilado, ese bloque entero sobra. El panel recupera su forma original y la figura gana
el ancho que la columna del 70% le recortaba.

## Lo que esta prueba vigila

Que no quede una copia MUERTA de `CSS_DOS_COLUMNAS` en el 03. La suite
`test_tableros_dos_columnas.py` exige que las copias de ese bloque sean identicas byte a
byte entre los cuadernos que SI lo usan; una copia olvidada aqui seguiria pasando esa
prueba -- se compara con las demas, no con quien la usa -- y quedaria como codigo que
alguien tiene que leer dos veces para descubrir que no hace nada.
"""

from __future__ import annotations

import re

from ayudas_tableros import fuente_de_tablero

CUADERNO = "03_uiti_vano_trayectorias_circuitos"


def _fuente() -> str:
    return fuente_de_tablero(CUADERNO, solo_codigo=True)


def test_el_03_no_va_en_dos_columnas():
    """Ni el envoltorio ni las clases de columna."""
    fuente = _fuente()
    assert "cuerpo-2col" not in fuente, (
        "el 03 sigue envuelto en la fila de dos columnas")
    assert "col-controles" not in fuente and "col-figuras" not in fuente, (
        "el 03 conserva las clases de las columnas")


def test_no_queda_una_copia_muerta_del_css_de_dos_columnas():
    """El bloque entero se va con la columna que lo necesitaba.

    Dejarlo definido y sin usar es lo que esta prueba existe para impedir: pasaria la
    comparacion byte a byte de la otra suite sin que nadie lo estuviera aplicando.
    """
    # Se mira la DECLARACION y no la palabra: el comentario que cuenta por que se fue
    # la nombra, y tiene que poder seguir nombrandola.
    fuente = "\n".join(l for l in _fuente().splitlines() if not l.lstrip().startswith("#"))
    assert not re.search(r"CSS_DOS_COLUMNAS\s*=", fuente), (
        "el 03 sigue declarando `CSS_DOS_COLUMNAS`, que ya no aplica a nada")
    assert "CSS_DOS_COLUMNAS +" not in fuente, (
        "el 03 sigue anteponiendo `CSS_DOS_COLUMNAS` a algo")


def test_el_panel_va_arriba_y_la_figura_debajo():
    """El orden del ensamblado ES el orden en la pagina: panel, figura, y el JS al final.

    El JS va ultimo y fuera de todo: no pinta nada, solo cuelga manejadores, y necesita
    que sus elementos ya existan en el documento cuando corre.
    """
    fuente = _fuente()
    ensamblado = re.search(r"PANEL_COMPLETO = (.+)", fuente)
    assert ensamblado, "el 03 no ensambla `PANEL_COMPLETO`"
    # La barra del boton de encuadre entra entre el panel y la figura: pertenece al mapa,
    # no al panel. El orden lo fija `test_trayectorias_circuitos_encuadre.py`; aqui lo que
    # importa es que el panel siga PRIMERO, la figura DESPUES y el JS al final.
    linea = ensamblado.group(1).strip()
    piezas = [p.strip() for p in linea.split("+")]
    assert piezas[0] == "PANEL_HTML", f"el panel ya no va primero: {linea!r}"
    assert piezas[-1] == "PANEL_JS", f"el JS ya no va al final: {linea!r}"
    assert piezas.index("FIGURA_HTML") > 0, f"la figura no va debajo del panel: {linea!r}"


def test_el_panel_conserva_su_barra_a_lo_ancho():
    """`.panel-tray` ya traia la forma correcta; lo que sobraba era lo que la tapaba."""
    fuente = _fuente()
    regla = re.search(r"\.panel-tray \{\{(.*?)\}\}", fuente, re.S)
    assert regla, "no se encontro la regla de `.panel-tray`"
    cuerpo = regla.group(1)
    assert "width: 100%" in cuerpo, "el panel del 03 ya no ocupa el ancho entero"
    assert "flex-wrap: wrap" in cuerpo, (
        "el panel del 03 ya no parte sus filas cuando no caben")
