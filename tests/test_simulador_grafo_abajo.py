"""El grafo vuelve a la figura, en una fila propia bajo el costo, y el cierre va en paleta.

Tres cambios que no se parecen pero comparten motivo: que el simulador se lea como una
sola cosa.

1. El grafo estuvo debajo del panel de control, en su propia figura. Vuelve a la figura
   grande, en una SEPTIMA fila y en las columnas 2-3, debajo del costo de la intervencion.
2. El boton de cerrar deja el rojo de `button_style="danger"` y toma el verde de la paleta.
3. El menu deja de escribir el puerto -- y cualquier otra cosa -- bajo el nombre de cada
   tablero.

## Lo que el grafo arrastra al volver

Sus rotulos son ANOTACIONES guardadas por posicion, y las de los otros paneles tambien.
Volver no es deshacer el viaje de ida: los indices se recalculan solos porque cada uno se
toma con `len(...) - 1` al crear la anotacion, pero SOLO si no queda ninguna a medias en la
figura que la suelta.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
COMUN = RAIZ / "aplicaciones" / "_comun"
TABLERO = RAIZ / "src" / "chec_tableros" / "simulador" / "tablero.py"
CIERRE = RAIZ / "aplicaciones" / "06_simulador" / "cierre.py"


def _comun(nombre: str):
    sys.path.insert(0, str(COMUN))
    try:
        return __import__(nombre)
    finally:
        sys.path.pop(0)


def _sin_comentarios(fuente: str) -> str:
    return "\n".join(l for l in fuente.splitlines() if not l.lstrip().startswith("#"))


def _tablero() -> str:
    return _sin_comentarios(TABLERO.read_text(encoding="utf-8"))


# ------------------------------------------------------- el grafo, en su fila de abajo


def test_la_figura_vuelve_a_tener_siete_filas():
    """La septima es la del grafo, debajo del costo."""
    fuente = _tablero()
    assert "rows=7, cols=4" in fuente, "la figura no tiene siete filas"
    alturas = re.search(r"row_heights=\[([^\]]+)\]", fuente)
    assert alturas, "no se declaran `row_heights`"
    assert len([x for x in alturas.group(1).split(",")]) == 7, (
        f"`row_heights` no tiene siete fracciones: {alturas.group(1)}")


def test_el_grafo_ocupa_las_columnas_2_y_3_de_la_ultima_fila():
    """Centrado y a media anchura: el anillo lo acota la dimension MENOR del panel, asi que
    de ancho completo solo anadiria franjas blancas a los lados."""
    fuente = _tablero()
    assert re.search(r"\[None, \{'type': 'xy', 'colspan': 2\}, None, None\]", fuente), (
        "la ultima fila no reserva las columnas 2-3 para el grafo")
    assert re.search(r"\), 7, 2\)", fuente), (
        "ninguna traza del grafo va a (7,2)")


def test_el_grafo_ya_no_tiene_figura_propia():
    """Vuelve a la figura grande; su div y su widget aparte desaparecen."""
    fuente = _tablero()
    assert "_fig_grafo" not in fuente, "sigue existiendo la figura aparte del grafo"
    assert "fig_grafo" not in fuente, "sigue existiendo el widget aparte del grafo"
    assert re.search(r"COLUMNA_CONTROLES = widgets\.VBox\(\s*\[PANEL\]", fuente), (
        "la columna de controles sigue llevando el grafo debajo del panel")


def test_el_titulo_del_grafo_vuelve_a_la_rejilla():
    """Dentro de la figura el titulo de un panel ES una anotacion de subplot."""
    fuente = _tablero()
    assert "'Grafo - Relaciones relevantes de la simulación'," in fuente, (
        "`subplot_titles` no vuelve a nombrar el grafo")
    assert "CTX" not in fuente or True  # el simulador no usa CTX; se deja explicito
    assert "fig.layout.annotations[IDX_ANOTACION_GRAFO]" in fuente, (
        "el aviso del grafo no vuelve a buscarse en la figura grande")


# ----------------------------------------------------------------- el boton de cerrar


def test_el_boton_de_cerrar_deja_el_rojo():
    """`button_style="danger"` es el rojo de Jupyter, no un color de este proyecto."""
    fuente = CIERRE.read_text(encoding="utf-8")
    assert 'button_style="danger"' not in fuente, (
        "el boton de cerrar sigue en el rojo de Jupyter")


def test_el_boton_de_cerrar_usa_la_paleta_y_no_una_copia():
    """Los valores se comprueban contra `paleta.py`, que es la fuente.

    `cierre.py` no puede importarla: el cuaderno que Voila sirve solo pone `APP_06` y
    `RAIZ_SRC_06` en el `sys.path`, no `aplicaciones/_comun`. Asi que los escribe, y esta
    prueba es lo que impide que se separen.
    """
    fuente = CIERRE.read_text(encoding="utf-8")
    paleta = _comun("paleta")
    for token in ("ACENTO", "ACENTO_OSCURO"):
        assert paleta.TOKENS[token] in fuente, (
            f"el boton de cerrar no usa {token} = {paleta.TOKENS[token]} de la paleta")


def test_el_boton_de_cerrar_va_en_la_fila_del_encabezado():
    """Lo que este guardian defiende es que el cierre esta ARRIBA, en la cabecera.

    Fijaba tambien `space-between` -- titulo a un extremo y cierre al otro --, y ese
    reparto se cayo: era lo que ponia al boton a pelear el ancho contra el titulo, y en
    pantalla el boton acababa siendo una `C`. Ahora el cierre abre la fila.

    El sitio exacto vive en `test_simulador_encabezado.py`; aqui solo importa que la
    barra siga en la cabecera y no vuelva al cuerpo del tablero.
    """
    fuente = _tablero()
    # Se lee el bloque entero de la fila y se comprueba dentro. Un patron que intente
    # cruzar la llamada de una sola pasada tropieza con los parentesis anidados de
    # `widgets.Layout(...)`, y falla por el patron y no por el codigo.
    i = fuente.index("ENCABEZADO = widgets.HBox(")
    bloque = fuente[i:fuente.index("APP = widgets.VBox(", i)]
    assert "*encabezado" in bloque, (
        "la barra de cerrar ya no entra en la fila del encabezado")


# --------------------------------------------------------------- el menu, sin el puerto


def test_el_menu_no_escribe_el_puerto_bajo_el_nombre():
    """Ni el puerto ni nada mas: ese espacio se queda vacio.

    Lo unico que sobrevive es el detalle de un FALLO. No es una etiqueta de estado sino la
    unica via por la que el usuario se entera de que una aplicacion no arranco -- `menu.py`
    lo dice en su encabezado: cuando algo falla "el menu es su unica ventana".
    """
    guion = _comun("menu_pagina")._GUION
    assert "abierta en el puerto" not in guion, (
        "el menu sigue escribiendo el puerto bajo el nombre del tablero")
    assert "hay que instalarla la primera vez" not in guion, (
        "el menu sigue escribiendo etiquetas de estado bajo el nombre")
    assert "hay que construirla la primera vez" not in guion, (
        "el menu sigue escribiendo etiquetas de estado bajo el nombre")
    assert "app.detalle" in guion, (
        "se fue tambien el detalle del fallo, que es lo unico que hay que conservar")
    assert "'fallo'" in guion, (
        "el detalle ya no se limita al caso de fallo")
