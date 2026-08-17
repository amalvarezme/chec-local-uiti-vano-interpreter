"""Los tableros se adaptan al ancho de la pantalla, y la barra del boton no los desborda.

## Lo medido, en Chrome sobre los cuatro paneles construidos

A 1.920, 1.440 y 1.280 px de ventana:

    tablero                      desborde horizontal
    01 clima                      96 px  en los tres anchos
    02 agrupamiento                0
    03 trayectorias circuitos      0
    04 trayectorias vanos        666 / 490 / 432 px

Un desborde horizontal es el sintoma numero uno de un diseno que no se adapta: aparece una
barra de scroll lateral y parte del tablero queda fuera de la pantalla.

## La causa, la misma en los dos

`.barra-encuadre` -- el div que coloca el boton de encuadre sobre el borde izquierdo del
mapa -- lleva un `padding-left` grande y calculado (514 px medidos en el 04 a 1.440), y
`box-sizing` en `content-box`, que es el valor por defecto. Con `content-box` el relleno se
SUMA al ancho en vez de caber dentro:

    ancho usado 960 px + padding-left 514 px = 1.475 px  en una ventana de 1.440

El 02 y el 03 no desbordan porque su barra no esta en el mismo contexto de caja, no porque
esten bien: la regla que los salva es accidental.

## Por que `border-box` y no quitar el relleno

El relleno ES la funcion de esa barra: alinea el boton con el borde izquierdo del mapa, que
no empieza en el margen de la figura. Con `border-box` el relleno sigue empujando el boton
exactamente igual y deja de sumar ancho.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CON_BARRA = ("clima.py", "trayectorias_circuitos.py", "trayectorias_vanos.py")


def _fuente(nombre: str) -> str:
    return (RAIZ / "src" / "chec_tableros" / nombre).read_text(encoding="utf-8")


def test_la_barra_del_boton_mete_su_relleno_dentro_de_la_caja():
    """Sin `border-box`, el `padding-left` se suma al ancho y saca el tablero de pantalla."""
    for nombre in CON_BARRA:
        fuente = _fuente(nombre)
        regla = re.search(r"\.barra-encuadre \{\{(.*?)\}\}", fuente, re.S)
        assert regla, f"{nombre}: no existe la regla `.barra-encuadre`"
        cuerpo = regla.group(1)
        assert "padding" in cuerpo, (
            f"{nombre}: la barra ya no coloca el boton con relleno; esta prueba sobra")
        assert "box-sizing: border-box" in cuerpo, (
            f"{nombre}: `.barra-encuadre` lleva relleno sin `border-box`, asi que lo suma "
            f"al ancho: {cuerpo.strip()}")


def test_la_barra_no_puede_crecer_mas_que_su_contenedor():
    """`border-box` solo obliga si hay un ancho al que aplicarlo.

    Con `width: auto` en un contenedor flexible, el ancho lo decide el contenido y el
    relleno vuelve a sumar. `width: 100%` lo ata al padre.
    """
    for nombre in CON_BARRA:
        regla = re.search(r"\.barra-encuadre \{\{(.*?)\}\}", _fuente(nombre), re.S)
        assert "width: 100%" in regla.group(1), (
            f"{nombre}: la barra no se ata al ancho de su contenedor: {regla.group(1).strip()}")


def test_las_figuras_siguen_siendo_responsive():
    """El ancho se adapta y el alto NO, y las dos mitades son deliberadas.

    `default_width='100%'` + `config.responsive` hacen que la figura ocupe el ancho
    disponible. El alto se queda en pixeles fijos porque lo que hay dentro de una fila es
    TEXTO -- rotulos, titulos de panel --, y el texto no encoge con la figura: un alto
    proporcional junta los rotulos en cuanto la pantalla es baja.
    """
    for nombre in ("clima.py", "agrupamiento.py", "trayectorias_circuitos.py",
                   "trayectorias_vanos.py"):
        fuente = _fuente(nombre)
        assert "'responsive': True" in fuente, (
            f"{nombre}: la figura no se redibuja al cambiar el tamanio de la ventana")
        assert "default_width='100%'" in fuente, (
            f"{nombre}: la figura no toma el ancho disponible")
        assert not re.search(r"fig\w*\.update_layout\([^)]*\bwidth=\d", fuente), (
            f"{nombre}: alguna figura fija su ancho en pixeles y anula el modo responsive")
