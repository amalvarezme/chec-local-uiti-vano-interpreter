"""El boton de encuadre pasa al borde DERECHO del mapa, y el mapa del 03 se ensancha.

Dos cambios que se piden juntos y comparten aritmetica: los dos se apoyan en el dominio
del mapa, que es lo unico que dice donde empieza y donde acaba ese panel dentro de la
figura.

## Por que el boton no se puede alinear "a la derecha" a secas

El mapa no llega al borde de la figura: entre los dos hay el margen derecho del `layout`,
en PIXELES, y ademas el mapa acaba donde acabe su dominio, que es una fraccion del area de
dibujo. Un `text-align: right` alinearia el boton con la ventana, no con el mapa, y el
desfase crece con el ancho de la pantalla -- que es justo el caso en el que se nota.

La cuenta es la simetrica de la que ya alineaba a la izquierda:

    padding-right = MARGEN_DER + (ancho util) * (1 - dominio derecho del mapa)

## El ancho del mapa en el 03

La fila de abajo lleva tres paneles -- evolucion, barras y dos violines -- y los tres de la
derecha ocupan de la columna 8 a la 15. El mapa iba de la 9 a la 15, o sea una columna mas
corto, y el borde derecho del mapa no coincidia con el de ningun panel de abajo. Se le da
`colspan: 8` desde la columna 8 para que las dos filas compartan la misma linea vertical.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CON_MAPA = ("trayectorias_circuitos.py", "trayectorias_vanos.py")


def _fuente(nombre: str) -> str:
    return (RAIZ / "src" / "chec_tableros" / nombre).read_text(encoding="utf-8")


def _regla_barra(fuente: str) -> str:
    regla = re.search(r"\.barra-encuadre \{\{(.*?)\}\}", fuente, re.S)
    assert regla, "no existe la regla `.barra-encuadre`"
    return regla.group(1)


def test_el_boton_se_alinea_con_el_borde_derecho_del_mapa():
    """Contra el dominio del mapa, no contra la ventana."""
    for nombre in CON_MAPA:
        fuente = _fuente(nombre)
        assert "MAPA_DER" in fuente, (
            f"{nombre}: no lee el borde DERECHO del dominio del mapa")
        assert re.search(r"MAPA_DER\s*=\s*float\(fig\.layout\.map\.domain\.x\[1\]\)", fuente), (
            f"{nombre}: `MAPA_DER` no sale del dominio del mapa de la propia figura")
        cuerpo = _regla_barra(fuente)
        assert "padding: 0 calc(" in cuerpo or "padding-right" in cuerpo, (
            f"{nombre}: la barra sigue empujando el boton desde la IZQUIERDA: {cuerpo}")
        assert "flex-end" in cuerpo, (
            f"{nombre}: la barra no manda su boton al extremo derecho: {cuerpo}")


def test_la_barra_sigue_sin_desbordar():
    """El `calc` de la derecha suma igual que el de la izquierda si la caja es
    `content-box`. Es el mismo fallo que dejo el tablero 04 saliendose 666 px."""
    for nombre in CON_MAPA:
        cuerpo = _regla_barra(_fuente(nombre))
        assert "box-sizing: border-box" in cuerpo and "width: 100%" in cuerpo, (
            f"{nombre}: la barra puede volver a desbordar la pantalla: {cuerpo}")


def test_el_mapa_del_03_llega_hasta_donde_llegan_los_paneles_de_abajo():
    """De la columna 8 a la 15, igual que barras y violines juntos.

    Iba de la 9 a la 15: una columna mas corto, asi que su borde derecho no coincidia con
    el de ningun panel de la fila de abajo y las dos filas no compartian ninguna linea.
    """
    fuente = _fuente("trayectorias_circuitos.py")
    fila1 = re.search(r"specs=\[\[(.*?)\],\s*\n\s*\[", fuente, re.S)
    assert fila1, "no se lee la primera fila de `specs`"
    mapa = re.search(r"\{'type': 'map', 'colspan': (\d+)\}", fila1.group(1))
    assert mapa, "la primera fila ya no lleva un mapa"
    assert int(mapa.group(1)) == 8, (
        f"el mapa ocupa {mapa.group(1)} columnas y los tres paneles de abajo ocupan 8")
    # Y arranca en la 8: con `colspan: 8` desde la 9 se saldria de la rejilla.
    antes = fila1.group(1)[:fila1.group(1).index("{'type': 'map'")]
    assert antes.count("None") == 6, (
        f"el mapa no empieza en la columna 8; lleva {antes.count('None')} celdas vacias "
        "delante en vez de 6")


def test_el_04_no_lista_los_vanos_marcados_en_la_leyenda():
    """La leyenda de arriba se queda con los GRUPOS y suelta los vanos.

    Un vano marcado entraba en la leyenda con su nombre y su circuito. Con quince
    marcados eso son quince entradas que empujan la leyenda a tres renglones, y la figura
    tiene que reajustar su margen superior en el navegador para no pisarse el titulo --
    `ajustarMargenSuperior` existe por eso.

    Lo que la leyenda explica de verdad es el COLOR, y el color lo fija el grupo de
    criticidad, no el vano. Cual vano es cual se lee en el mapa, donde esta rotulado, y en
    la etiqueta del mouse.
    """
    fuente = _fuente("trayectorias_vanos.py")
    linea = re.search(r"enLeyenda\.push\(([^)]*)\)", fuente)
    assert linea, "el panel ya no decide que vanos entran en la leyenda"
    assert linea.group(1).strip() == "false", (
        f"los vanos marcados siguen entrando en la leyenda: {linea.group(0)}")
