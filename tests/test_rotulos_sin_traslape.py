"""Las decisiones que impiden que los textos de los tableros se pisen entre si.

Medido en Chrome sobre las cinco aplicaciones a 1.280, 1.512 y 1.900 px de ventana:
**69 traslapes de texto** en los cuatro tableros estaticos y **19 mas** en el simulador,
que con dato subian a **81**. Todos quedaron en cero.

Un traslape se mide comparando las cajas ORIENTADAS de cada `<text>` del SVG -- la caja
alineada a los ejes de una marca girada 30 grados se pisa con la de al lado aunque las
letras no se toquen, y contarla seria perseguir un fallo que nadie ve.

## Que se fija aqui y que no

Que dos textos no se toquen es una propiedad de PIXELES: pide un navegador, la figura
dibujada y un ancho de ventana concreto. Lo que se puede fijar en una prueba rapida es la
DECISION que lo garantiza, y es lo que hay abajo: el angulo de las marcas de fecha, el
tipo de los ejes que arrancan vacios, y que el rotulo dentro de una barra se decida
mirando los dos lados de la barra y no uno solo.

Cada una nacio de un traslape medido, y el numero medido esta en su docstring.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
BASE = RAIZ / "notebooks" / "base_apps"
VENTANA = ("03_uiti_vano_trayectorias_circuitos.ipynb",
           "04_uiti_vano_trayectorias_vano.ipynb")
SIMULADOR = "06_uiti_vano_explicabilidad_simulador.ipynb"


def _fuente(nombre: str) -> str:
    """La fuente del tablero, ya viva en el cuaderno o en `src/chec_tableros/`."""
    from ayudas_tableros import fuente_de_tablero

    return fuente_de_tablero(nombre, solo_codigo=True)


def _sin_comentarios(fuente: str) -> str:
    return "\n".join(l for l in fuente.splitlines()
                     if not l.lstrip().startswith(("#", "//")))


# ------------------------------------------------- las once fechas de la evolucion


# El cuaderno y la COLUMNA en la que vive su panel de evolucion. No es la misma en los
# dos: en el 04 el perfil del circuito entro a su izquierda y la corrio de la 1 a la 6.
# Se parametriza en vez de aceptar cualquier columna porque lo que se vigila es el angulo
# de ESE panel, y un patron laxo pasaria mirando el de al lado.
COLUMNA_EVOLUCION = {
    "03_uiti_vano_trayectorias_circuitos.ipynb": 1,
    "04_uiti_vano_trayectorias_vano.ipynb": 6,
}


@pytest.mark.parametrize("nombre", VENTANA)
def test_las_fechas_de_la_ventana_van_bastante_inclinadas(nombre: str):
    """A 55 grados como MINIMO, y hoy a 90.

    La cuenta original: el panel de la evolucion media 396 px a 1.280 px de ventana para
    las once ventanas del periodo, o sea 36 px por marca. Una etiqueta '11-01 a 11-30'
    mide 65 px; a 30 grados ocupa 56 px de ancho y las once se pisaban en cadena -- diez
    traslapes medidos --, y a 55 ocupa 37 y justo cabia.

    Ese "justo" se acabo cuando el perfil del circuito entro a su izquierda: la evolucion
    paso de 6 de 15 columnas (40%) a 5 de 20 (25%), un 37% menos de ancho, o sea unos 22
    px por marca. A 55 grados volverian a pisarse. A 90 lo que ocupa la etiqueta ya no es
    su ancho proyectado sino su ALTURA de linea -- unos 12 px --, que entra de sobra.

    Se fija el MINIMO y no el valor exacto, que es lo que deja que esto suba sin tocar la
    prueba. Lo que la prueba impide es que BAJE.
    """
    fuente = _sin_comentarios(_fuente(nombre))
    angulo = re.search(
        rf"update_xaxes\(tickangle=(-?\d+)(?:[^()]|\([^()]*\))*?"
        rf"row=2,\s*col={COLUMNA_EVOLUCION[nombre]}\b",
        fuente, re.S)
    assert angulo, f"{nombre} ya no fija el angulo de las marcas de la evolucion"
    assert int(angulo.group(1)) <= -50, (
        f"{nombre}: con tickangle={angulo.group(1)} las once fechas se pisan a 1.280 px")


# ------------------------------------------- los paneles que arrancan vacios


def test_los_paneles_por_vano_del_simulador_declaran_su_eje_categorico():
    """`type='category'` en los cinco ejes x que dibujan barras por vano.

    Los cinco arrancan VACIOS -- esperan a que se pulse Simular --, y un eje sin datos
    ni tipo declarado cae a lineal y se inventa marcas de -1 a 6. La marca '-1' del
    origen tocaba el '0' del eje y en la esquina: tres traslapes medidos, en los tres
    anchos. Un eje categorico vacio no dibuja ninguna marca, que es lo correcto -- no
    hay ningun vano que nombrar todavia.
    """
    fuente = _sin_comentarios(_fuente(SIMULADOR))
    celdas = [(4, 3), (5, 1), (5, 4), (6, 1), (6, 4)]
    for fila, columna in celdas:
        llamada = re.search(
            rf"update_xaxes\((?:[^()]|\([^()]*\))*?row={fila},\s*col={columna}\)",
            fuente, re.S)
        assert llamada, f"el simulador no configura el eje x de ({fila}, {columna})"
        assert "type='category'" in llamada.group(0), (
            f"el eje x de ({fila}, {columna}) no declara `type='category'`: vacio se "
            "inventa marcas de -1 a 6 y la del origen toca al eje y")


# --------------------------------------- el rotulo dentro de la barra, por sus dos lados


def test_el_top_por_vano_decide_su_rotulo_mirando_el_grosor_de_la_barra():
    """El rotulo va girado -90: la barra lo limita por sus DOS lados.

    `rotulo_en_barra` solo miraba el LARGO -- si el texto cabe escrito --. El GROSOR es
    lo que decide si cabe SIN montarse sobre la barra de al lado, y con ocho vanos por
    diez posiciones cada barra mide 3,6 px contra los 11 que mide el renglon del texto.
    Resultado medido: **81 traslapes**, ochenta rotulos verticales unos sobre otros.
    """
    fuente = _fuente(SIMULADOR)
    llamada = re.search(r"rotulo_en_barra\((?:[^()]|\([^()]*\))*?\)", fuente, re.S)
    assert llamada, "el simulador ya no llama a `rotulo_en_barra`"
    assert "grosor_px=" in llamada.group(0), (
        "el top por vano decide su rotulo sin mirar el grosor de la barra; con ocho "
        "vanos marcados eso escribe ochenta rotulos encimados")


def test_el_ancho_supuesto_del_panel_es_el_del_caso_mas_estrecho():
    """El ancho del panel NO se conoce en Python: la figura es responsive.

    Asi que se supone, y la suposicion tiene que ser la del caso mas ESTRECHO que el
    tablero soporta -- ventana de 1.280 px --, no la del comodo. Suponer de mas escribe
    rotulos que en una pantalla chica se montan, que es justo lo que esto evita.
    """
    fuente = _sin_comentarios(_fuente(SIMULADOR))
    valor = re.search(r"ANCHO_PANEL_TOP_PX_MINIMO\s*=\s*([\d.]+)", fuente)
    assert valor, "el simulador no declara el ancho supuesto del panel del top"
    # 848 px de figura a 1.280 de ventana, y este panel al 42,5% de ella.
    assert float(valor.group(1)) <= 380.0, (
        f"ANCHO_PANEL_TOP_PX_MINIMO = {valor.group(1)} supone una pantalla mas ancha "
        "que la mas estrecha que el tablero soporta")
