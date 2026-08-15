"""La figura del clima: el mapa en una fila junto a la serie, y los violines de a dos.

El tablero 01 tenia el mapa ocupando DOS filas y las seis variables repartidas en otras
dos, una por panel. Eso dejaba el mapa mas alto que la serie que tiene al lado -- las dos
piezas de la fila de arriba no empezaban ni acababan a la misma altura -- y estiraba la
figura a 2.100 px para dibujar seis violines de un solo dato cada uno.

Ahora son DOS filas: arriba el mapa (columnas 1-2) y la serie (columna 3), a la misma
altura; abajo tres paneles con DOS violines cada uno.

## Por que el segundo violin va en un eje propio

Las seis variables no comparten unidad: milimetros, grados, km/h, un indice y
descargas/km2/anio. Dos violines de unidades distintas en un solo eje se leen como si uno
fuera mas grande que el otro cuando lo unico que pasa es que se miden en otra cosa.

Con UNA excepcion, que es la que fija este archivo: **la rafaga y la velocidad del viento
estan las dos en km/h**. Ahi un eje secundario seria lo contrario de una ayuda -- dos
escalas distintas para la misma unidad invitan a comparar alturas que no son comparables
--, asi que ese par comparte el eje y se leen una contra la otra, que es justo lo que uno
quiere de esas dos.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CUADERNO = RAIZ / "notebooks" / "base_apps" / "01_uiti_vano_clima.ipynb"

# El orden en que se dibujan, que es el de `VARS_VIOLIN`, y su unidad.
VIOLINES = [("prep", "mm"), ("temp", "°C"),
            ("wind_gust_spd", "km/h"), ("wind_spd", "km/h"),
            ("NR_T", "indice"), ("DDT", "descargas/km²/año")]


def _celdas() -> list[str]:
    documento = json.loads(CUADERNO.read_text(encoding="utf-8"))
    return ["".join(c["source"]) for c in documento["cells"]
            if c["cell_type"] == "code"]


def _celda_de_la_figura() -> str:
    return next(f for f in _celdas() if "make_subplots(" in f)


def _sin_comentarios(fuente: str) -> str:
    return "\n".join(l for l in fuente.splitlines() if not l.lstrip().startswith("#"))


def _rejilla() -> tuple[int, int]:
    celda = _sin_comentarios(_celda_de_la_figura())
    filas = int(re.search(r"rows=(\d+)", celda).group(1))
    columnas = int(re.search(r"cols=(\w+)", celda).group(1).replace("VIOL_COLS", "3"))
    return filas, columnas


# ------------------------------------------------- el mapa, a la altura de la serie


def test_la_figura_tiene_dos_filas():
    """Una para el mapa y la serie, otra para los tres paneles de violines."""
    filas, _ = _rejilla()
    assert filas == 2, f"la figura declara {filas} filas; el mapa ya no ocupa dos"


def test_el_mapa_ocupa_una_sola_fila_y_dos_columnas():
    """`colspan=2` sin `rowspan`.

    Con `rowspan=2` el mapa bajaba hasta la mitad de la figura y la serie se quedaba
    arriba: las dos piezas de la misma fila no compartian ni el borde de abajo.
    """
    celda = _sin_comentarios(_celda_de_la_figura())
    mapa = re.search(r"\{'type': 'map'[^}]*\}", celda)
    assert mapa, "la figura ya no declara un panel de mapa"
    assert "'rowspan'" not in mapa.group(0), (
        f"el mapa sigue ocupando mas de una fila: {mapa.group(0)}")
    assert "'colspan': 2" in mapa.group(0), (
        f"el mapa no ocupa dos columnas: {mapa.group(0)}")


def test_el_alto_de_la_figura_se_elige_contra_el_del_panel_de_control():
    """Las dos columnas del tablero tienen que acabar mas o menos a la misma altura.

    El panel de control mide 1.248 px a 1.280 de ventana, 1.034 a 1.512 y 915 a 1.900 --
    medido en el navegador; cambia de alto porque su texto se reparte en mas o menos
    renglones. No existe un numero que iguale a los tres, asi que se elige el que deja la
    diferencia mas chica donde mas se usa: con 1.050 son 16 px a 1.512 y menos de 200 en
    el peor caso. Con los 2.100 de antes le sobraban 660 px de banda muerta.
    """
    fuente = _sin_comentarios("\n".join(_celdas()))
    alto = re.search(r"ALTO_FIGURA\s*=\s*(\d+)", fuente)
    assert alto, "el cuaderno ya no declara `ALTO_FIGURA`"
    assert 900 <= int(alto.group(1)) <= 1200, (
        f"ALTO_FIGURA = {alto.group(1)}: la figura deja de estar a la altura del panel "
        "de control, que mide entre 915 y 1.248 px segun el ancho de la ventana")


def test_la_fila_del_mapa_no_se_come_la_figura():
    """El reparto entre las dos filas sale de la FORMA del mapa.

    Con dos tercios el recuadro del mapa quedaba alto y angosto y empujaba la fila de
    violines hacia abajo. Con 0,63 queda casi cuadrado -- medido: 459 x 455 px a 1.512 --
    y lo que deja de gastar lo gana la fila de abajo.
    """
    celda = _sin_comentarios(_celda_de_la_figura())
    alturas = re.search(r"row_heights=\[([^\]]+)\]", celda)
    assert alturas, "la figura no declara `row_heights`"
    valores = [eval(v.strip()) for v in alturas.group(1).split(",")]  # noqa: S307
    assert len(valores) == 2, f"se esperaban dos filas, hay {len(valores)}"
    assert abs(sum(valores) - 1.0) < 1e-9, f"las dos filas no suman 1: {valores}"
    assert 0.55 <= valores[0] <= 0.70, (
        f"la fila del mapa se lleva {valores[0]:.0%} de la figura; fuera de esa banda o "
        "el mapa queda como una tira o los violines se quedan sin alto")


# ------------------------------------------- los violines, de a dos por panel


def test_los_violines_van_de_a_dos_en_una_sola_fila():
    """Seis violines en tres paneles, y los tres paneles en la fila 2.

    El indice manda: el violin `i` cae en la columna `i // 2 + 1`, asi que las parejas
    salen del orden de `VARS_VIOLIN` y no de una lista aparte que haya que mantener
    sincronizada con el.
    """
    celda = _sin_comentarios(_celda_de_la_figura())
    fila = re.search(r"_fila\s*=\s*FILA_VIOLINES", celda)
    assert fila, "los violines ya no declaran su fila con `FILA_VIOLINES`"
    columna = re.search(r"_col\s*=\s*_idx\s*//\s*2\s*\+\s*1", celda)
    assert columna, "los violines no se reparten de a dos por columna"
    assert re.search(r"FILA_VIOLINES\s*=\s*2", celda), (
        "los violines no estan en la fila 2")


def test_los_tres_paneles_de_violines_admiten_un_eje_secundario():
    """La rejilla tiene que declararlo: un `secondary_y` no se puede agregar despues."""
    celda = _sin_comentarios(_celda_de_la_figura())
    specs = re.search(r"specs=\[(.*?)\]\],", celda, re.S)
    assert specs, "no se pudo leer `specs`"
    # La ultima fila declarada, que es la de los violines.
    segunda = specs.group(1).rsplit("[", 1)[-1]
    assert segunda.count("'secondary_y': True") == 3, (
        "los tres paneles de violines tienen que declarar `secondary_y`")


def test_el_par_que_comparte_unidad_comparte_eje():
    """Rafaga y velocidad estan las dos en km/h.

    Dos escalas distintas para la misma unidad invitan a comparar alturas que no son
    comparables; una sola las hace comparables, que es lo que uno quiere de ese par.
    Los otros dos pares -- mm contra grados, indice contra descargas -- si necesitan
    ejes propios.
    """
    celda = _sin_comentarios(_celda_de_la_figura())
    regla = re.search(r"_secundario\s*=\s*\(?([^\n]+)", celda)
    assert regla, "la figura no decide en codigo que violin va al eje secundario"
    assert "UNIDADES" in regla.group(1), (
        f"la decision no mira la unidad de las dos variables: {regla.group(1)!r}")


def test_cada_violin_se_reconoce_por_su_propia_marca_en_el_eje_x():
    """Con dos violines en un panel, el nombre de cada uno es lo que los distingue.

    Cuando habia uno por panel el titulo bastaba y la marca del eje x lo repetia, asi
    que se apagaba. Ahora hacen falta las dos cosas.
    """
    celda = _sin_comentarios(_celda_de_la_figura())
    assert "NOMBRES_CORTOS_VIOLIN" in celda, (
        "los violines no traen un nombre corto para su marca del eje x")
    apagado = re.search(
        r"update_xaxes\(showticklabels=False,\s*row=_fila", celda)
    assert not apagado, (
        "el eje x de los violines sigue apagado: con dos por panel, esa marca es lo "
        "unico que dice cual es cual")
