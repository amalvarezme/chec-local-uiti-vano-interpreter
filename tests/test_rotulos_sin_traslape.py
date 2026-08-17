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
    # (4,1) y ya no (4,3): el top de variables paso a ocupar las cuatro columnas cuando la
    # serie de UITI subio a la fila 3 a compartir con el perfil.
    celdas = [(4, 1), (5, 1), (5, 4), (6, 1), (6, 4)]
    for fila, columna in celdas:
        llamada = re.search(
            rf"update_xaxes\((?:[^()]|\([^()]*\))*?row={fila},\s*col={columna}\)",
            fuente, re.S)
        assert llamada, f"el simulador no configura el eje x de ({fila}, {columna})"
        assert "type='category'" in llamada.group(0), (
            f"el eje x de ({fila}, {columna}) no declara `type='category'`: vacio se "
            "inventa marcas de -1 a 6 y la del origen toca al eje y")


# --------------------------------------- el rotulo dentro de la barra, por sus dos lados


def test_el_top_por_vano_avisa_cuando_sus_codigos_se_encimaran():
    """El grosor de la barra dejo de VETAR el rotulo, y pasa a DECLARARSE.

    ## De donde viene este guardian

    El rotulo va girado -90, asi que la barra lo limita por sus DOS lados: el largo dice
    si el texto cabe escrito, el GROSOR dice si cabe sin montarse sobre la barra vecina.
    La cascada solo miraba el largo, y con ocho vanos por diez posiciones cada barra
    media 3,6 px contra los 11 del renglon: **81 traslapes medidos**, ochenta rotulos
    verticales unos sobre otros. De ahi salio la compuerta de grosor.

    ## Por que ya no veta

    Decision del usuario, tomada a sabiendas: las CINCO primeras posiciones llevan el
    codigo de su columna SIEMPRE, dentro de la barra o encima. Una barra sin codigo no se
    puede cruzar con la tabla de vanos, y ese cruce es para lo que existe el panel; el
    nombre en palabras del hover no lo resuelve, porque el hover se consulta de a uno.

    ## Lo que se fija en su lugar

    El numero no desaparece por dejar de vetar. Se sigue calculando y el panel lo declara
    en la etiqueta del mouse, para que los rotulos encimados no se lean como un fallo del
    tablero. Medido de nuevo sobre el panel mas estrecho que se soporta -- 719 px -- y a
    fuente 9, con renglon de 12,38 px: con cuatro vanos marcados la barra mide 12,81 px y
    los codigos no se tocan; con cinco mide 10,25 px y si.
    """
    fuente = _fuente(SIMULADOR)
    llamada = re.search(r"rotulo_de_codigo\((?:[^()]|\([^()]*\))*?\)", fuente, re.S)
    assert llamada, "el top por vano ya no escribe el codigo de columna de sus barras"
    assert "hueco_px=" in llamada.group(0), (
        "no se le pasa el hueco hasta el techo del eje, asi que el codigo que no cabe "
        "dentro no puede irse encima de la barra")
    assert "tam_fuente=" in llamada.group(0), (
        "decide con los anchos medidos a 8 px mientras el panel escribe a otro tamanio")
    assert "alto_renglon_px(" in fuente, (
        "el grosor de la barra dejo de calcularse: sin el, el panel no puede avisar de "
        "que sus codigos se enciman y el traslape se lee como un fallo")


def test_el_rotulo_del_top_usa_la_misma_fuente_que_las_marcas_de_su_eje():
    """El codigo escrito en la barra y el vano escrito debajo son dos etiquetas del mismo
    dibujo. A tamanios distintos, una se lee como subordinada de la otra."""
    fuente = _fuente(SIMULADOR)

    tam_barra = re.search(r"TAM_FUENTE_BARRA\s*=\s*(\d+)", fuente)
    eje = re.search(r"update_xaxes\([^)]*tickfont=dict\(size=(\d+)\)[^)]*row=4", fuente, re.S)

    assert tam_barra and eje, "no se encuentran los dos tamanios del panel del top"
    assert tam_barra.group(1) == eje.group(1), (
        f"el rotulo va a {tam_barra.group(1)} px y las marcas del eje a {eje.group(1)}")


def test_el_ancho_supuesto_del_panel_es_el_medido_en_la_pantalla_mas_estrecha():
    """El ancho del panel NO se conoce en Python: la figura es responsive.

    Asi que se supone, y la suposicion tiene que ser la del caso mas ESTRECHO que el
    tablero soporta -- ventana de 1.280 px --, no la del comodo. Suponer de mas escribe
    rotulos que en una pantalla chica se montan.

    ## Pero suponer de MENOS tampoco es gratis, y es lo que pasaba

    El valor era 380, de cuando el top ocupaba una fraccion del ancho de la figura. Al
    mover el grafico a las CUATRO columnas, el panel paso a ocuparla casi entera y la
    suposicion se quedo a menos de la mitad. Con ella, la compuerta de grosor calla desde
    tres vanos, y el diagnostico completa a ocho: el panel llevaba semanas sin escribir un
    solo rotulo -- medido, 80 barras y 80 textos vacios --, que es el fallo contrario al
    que la constante existe para evitar y se ve igual de poco.

    Medido de nuevo en el navegador a 1.280 px de ventana: figura de 875, **panel del top
    de 719**. Se toma ese, no el de una pantalla ancha.
    """
    fuente = _sin_comentarios(_fuente(SIMULADOR))
    valor = re.search(r"ANCHO_PANEL_TOP_PX_MINIMO\s*=\s*([\d.]+)", fuente)
    assert valor, "el simulador no declara el ancho supuesto del panel del top"
    ancho = float(valor.group(1))
    assert ancho <= 719.0, (
        f"ANCHO_PANEL_TOP_PX_MINIMO = {ancho} supone una pantalla mas ancha que la mas "
        "estrecha que el tablero soporta (719 px medidos a 1.280 de ventana)")
    assert ancho >= 640.0, (
        f"ANCHO_PANEL_TOP_PX_MINIMO = {ancho} se queda MUY corto de los 719 px medidos, y "
        "una suposicion baja apaga los rotulos que si caben")


def test_el_aviso_de_aplicar_no_explica_lo_que_el_boton_ya_dice():
    """"Presiona Simular", y nada mas.

    El aviso ya trae tres cifras -- vanos marcados, controles abiertos, que mitades van a
    entrar --; el "para ver el efecto" era la cuarta linea de un mensaje que se lee de
    pasada, y decia lo que el propio boton "Simular" ya dice.
    """
    fuente = _fuente(SIMULADOR)

    assert "para ver el efecto" not in fuente
    assert "Presiona <b>Simular</b>." in fuente
