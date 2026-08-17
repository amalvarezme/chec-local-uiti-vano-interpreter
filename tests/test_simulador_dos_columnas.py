"""El tablero 06 en dos columnas: los controles a la izquierda, las figuras a la derecha.

El panel de control iba ENCIMA de la figura, y las dos piezas ocupaban el ancho entero.
Medido en el navegador sobre la aplicacion servida, ventana de 1.512 px: 1.341 px de
panel mas 2.489 px de figura, o sea **3.912 px de pagina**. Elegir una variable y ver que
le hace al mapa son dos gestos en extremos opuestos del scroll.

En dos columnas -- 30% para los controles y 70% para las figuras -- la pagina baja a
**2.565 px**, un 34% menos, porque las dos piezas dejan de sumarse a lo alto.

## Lo que hubo que arreglar para que quepa

Las casillas del catalogo de actividades llevaban `width: 580px` FIJO. En una columna de
445 px eso no se sale por ningun lado -- comprobado: la pagina no scrollea a lo ancho y
nada se pinta fuera del panel --, pero le deja al recuadro una barra horizontal propia y
recorta el rotulo a 580 px de los 1.035 que mide su contenido. Una anchura que puede
ENCOGER (`flex: 0 1 <ancho>`) conserva la rejilla de siempre cuando hay sitio y se adapta
cuando no lo hay, que es la unica diferencia entre las dos disposiciones.

## Y el enganche con la aplicacion local

`aplicaciones/06_simulador/preparar.py` parchea el cuaderno por TEXTO LITERAL para meterle
el boton de cerrar. La linea del `APP` es una de sus anclas, asi que moverla rompe la
construccion de la aplicacion -- y lo hizo, en esta misma tarea. El guardian avisa bien,
pero avisa al construir; aqui se comprueba antes, que es donde cuesta un segundo.
"""

from __future__ import annotations

import re
from pathlib import Path

import ayudas_tableros
import pytest

RAIZ = Path(__file__).resolve().parents[1]
TABLERO = "06_uiti_vano_explicabilidad_simulador"


def _celda_del_tablero() -> str:
    """El codigo que arma `APP`, que es donde se decide la disposicion.

    Era la CELDA que armaba `APP`; ahora es el modulo entero. Lo que se busca abajo
    son definiciones de nivel de `construir()` -- `CUERPO = widgets.HBox(`,
    `COLUMNA_FIGURAS = widgets.VBox(` --, que aparecen una sola vez en todo el
    fichero, asi que la busqueda dice lo mismo sobre un texto mas grande.
    """
    return ayudas_tableros.fuente_de_tablero(TABLERO)


# ------------------------------------------------------------- las dos columnas


def test_el_cuerpo_del_tablero_es_una_fila_de_dos_columnas():
    """Un `HBox` y no un `VBox`: es lo que pone una pieza al lado de la otra."""
    celda = _celda_del_tablero()
    assert "CUERPO = widgets.HBox(" in celda, (
        "el tablero ya no se arma como una fila de dos columnas")
    fila = re.search(r"CUERPO = widgets\.HBox\(\s*\[([^\]]+)\]", celda)
    assert fila, "no se pudo leer que va dentro de la fila"
    hijos = [h.strip() for h in fila.group(1).split(",") if h.strip()]
    assert hijos == ["COLUMNA_CONTROLES", "COLUMNA_FIGURAS"], (
        f"la fila lleva {hijos}; los controles van a la IZQUIERDA, o sea primero")


@pytest.mark.parametrize("columna,ancho", [("COLUMNA_CONTROLES", "30%"),
                                           ("COLUMNA_FIGURAS", "70%")])
def test_cada_columna_declara_su_ancho(columna: str, ancho: str):
    """30% y 70%, escritos donde se leen. En porcentaje y no en pixeles: el tablero se
    sirve en pantallas de 1.280 a 1.900 px y un ancho fijo deja banda o corta."""
    celda = _celda_del_tablero()
    definicion = re.search(rf"{columna} = widgets\.VBox\((?:[^()]|\([^()]*\))*?\)", celda,
                           re.S)
    assert definicion, f"{columna} no se define en la celda del tablero"
    assert f"width='{ancho}'" in definicion.group(0), (
        f"{columna} no declara `width='{ancho}'`")


def test_la_figura_va_en_la_columna_derecha_con_sus_botones_de_encuadre():
    """Los dos botones de encuadre se posan cada uno sobre su mapa, asi que viajan con
    la figura y no con los controles: separados, apuntarian a otro sitio."""
    celda = _celda_del_tablero()
    derecha = re.search(r"COLUMNA_FIGURAS = widgets\.VBox\(\s*\[([^\]]+)\]", celda)
    assert derecha, "no se pudo leer la columna de figuras"
    hijos = [h.strip() for h in derecha.group(1).split(",") if h.strip()]
    assert hijos == ["ENCUADRES", "fig"], f"la columna de figuras lleva {hijos}"


# ------------------------------------------------- las casillas que tienen que encoger


@pytest.mark.parametrize("atributo", ["_layout_casilla", "_layout_casilla_columna"])
def test_las_casillas_del_selector_pueden_encoger(atributo: str):
    """`width` MAS `max_width='100%'`: fluida sin cambiar donde hay sitio.

    La casilla mide `ancho_casilla`, salvo que su recuadro sea mas estrecho, y ahi se
    recorta a el. Sin el `max_width`, las 580 px del catalogo de actividades dentro de
    una columna de 445 dejaban al recuadro una barra horizontal propia.

    Y `width` sigue haciendo falta: quitarlo -- probado con `flex: 0 1 <ancho>` -- deja
    mandar al ancho por defecto de ipywidgets, y las casillas se quedaban en 300 px aun
    con 493 px de recuadro. En pantalla grande el rotulo perdia sitio en vez de ganarlo.
    """
    fuente = (RAIZ / "src" / "chec_local_interpreter" / "vano_widgets.py").read_text(
        encoding="utf-8")
    bloque = re.search(rf"self\.{atributo} = widgets\.Layout\([^)]*\)", fuente, re.S)
    assert bloque, f"el selector ya no arma `{atributo}`"
    assert "width=ancho_casilla" in bloque.group(0), (
        f"{atributo} dejo de fijar el ancho de la casilla; sin el manda el de ipywidgets")
    assert 'max_width="100%"' in bloque.group(0), (
        f"{atributo} no puede encoger: en una columna mas estrecha que la casilla, el "
        "recuadro se queda con una barra horizontal propia")


# --------------------------------------------- el enganche con la aplicacion local


def test_la_barra_de_cerrar_va_encima_de_las_dos_columnas():
    """La barra es del tablero ENTERO, no de una de sus columnas.

    Metida dentro de `COLUMNA_CONTROLES` se iria al 30% del ancho, que es la mitad de
    por que `encabezado` entra en el `VBox` exterior y no en el `HBox`.

    Aqui vivia una prueba de que los seis parches de texto de `preparar.py` seguian
    encontrando sus anclas en el cuaderno 06 -- entre ellas la linea del `APP`. Los
    parches ya no existen: el tablero recibe la barra como parametro, asi que lo que
    antes era un ancla de texto es hoy una firma de funcion, y lo que queda por fijar
    es DONDE la pone.
    """
    fuente = _celda_del_tablero()
    armado = re.search(r"APP = widgets\.VBox\(\s*\[([^\]]+)\]", fuente)
    assert armado, "el tablero ya no arma `APP` como un VBox"
    piezas = [p.strip() for p in armado.group(1).split(",") if p.strip()]
    assert piezas[0] == "ENCABEZADO", (
        f"`APP` lleva {piezas}; la fila del encabezado va PRIMERA y fuera del HBox, o la "
        "barra de cerrar acaba dentro de una columna del 30%")
    # Y dentro de esa fila, el `encabezado` que pasa la aplicacion se DESPLIEGA junto al
    # titulo. Antes iba suelto en el `VBox`; ahora comparte fila con "Simulador
    # Criticidad", que va a la izquierda mientras la barra queda a la derecha. Lo que la
    # prueba persigue no ha cambiado: que la barra sea del tablero entero y no de una
    # columna.
    fila = re.search(r"ENCABEZADO = widgets\.HBox\(\s*\[([^\]]+)\]", fuente)
    assert fila, "el tablero ya no arma la fila del encabezado"
    dentro = [p.strip() for p in fila.group(1).split(",") if p.strip()]
    assert "*encabezado" in dentro, (
        f"la fila del encabezado lleva {dentro}; sin `*encabezado` la barra de cerrar no "
        "llega a ninguna parte")


def test_la_rejilla_muestra_dos_vanos_por_fila():
    """Cuatro columnas de controles en un panel que ocupa el 30% del ancho no se leen.

    El panel de control es una COLUMNA -- no una barra a lo ancho --, asi que cada una de
    las cuatro se quedaba con una franja donde el nombre de la variable y su deslizador ya
    no caben en la misma linea. Con dos, cada vano tiene la mitad del panel.
    """
    from chec_local_interpreter.vano_widgets import VANOS_POR_PAGINA
    assert VANOS_POR_PAGINA == 2, (
        f"la rejilla muestra {VANOS_POR_PAGINA} vanos por pagina y no dos")


def test_las_dos_columnas_reparten_la_fila_a_medias():
    """`row wrap` con anchos automaticos no garantiza DOS por fila: con un nombre de
    variable largo la segunda columna se pasa del ancho y baja a la fila siguiente.

    `flex: 1 1 0%` reparte la fila entre las columnas que haya, y `min-width: 0` apaga el
    `min-width: auto` que trae todo hijo de flex -- sin el, el contenido mas ancho de la
    columna manda sobre el reparto y el wrap vuelve.
    """
    fuente = (RAIZ / "src" / "chec_tableros" / "simulador" / "tablero.py").read_text(
        encoding="utf-8")
    bloque = fuente[fuente.index("columnas.append((fid, widgets.VBox("):]
    bloque = bloque[:bloque.index("))")]
    assert "flex='1 1 0%'" in bloque, (
        f"las columnas de la rejilla no reparten la fila a medias: {bloque}")
    assert "min_width='0'" in bloque, (
        f"el contenido mas ancho puede seguir mandando sobre el reparto: {bloque}")
