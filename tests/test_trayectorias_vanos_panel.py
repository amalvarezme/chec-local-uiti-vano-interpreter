"""El panel del 04 se aligera y el perfil del circuito baja debajo de el.

Cuatro cambios, y los cuatro se leen en la fuente:

1. El parrafo largo que explicaba la mecanica de la lista se queda en una linea que dice
   lo unico que el usuario necesita para leerla: que la lista es del PERIODO, y cual es
   ese periodo.
2. El aviso de abajo pierde el " -- su evolucion abajo dice en que ventanas si": el panel
   de evolucion ya no esta debajo de esa frase.
3. El perfil del circuito sale de la figura grande y pasa a su PROPIA figura, en la
   columna de la izquierda y debajo del panel, con el mismo ancho que el.
4. El boton de encuadre sube encima del mapa, como en el 01 y en el 03.

## Por que el perfil se saca de la figura y no se mueve dentro de ella

Porque "debajo del panel de control" y "del ancho del panel" es la columna izquierda, y
la figura grande vive entera en la derecha. Un subplot no puede salirse de su figura.

Eso arrastra tres cosas que este archivo vigila, porque las tres pueden romperse en
silencio:

  * el indice de la traza. En la figura grande `IDX` es aritmetica sobre el numero de
    cupos y el perfil iba EL ULTIMO; en su figura propia es la traza 0 y nada mas.
  * el titulo. Dentro de la figura era una ANOTACION de subplot que el JS mutaba por
    posicion (`CTX.titulos.perfil[0]`); ahora es el titulo de su figura, que se cambia
    con un relayout sobre su propio div.
  * el alto de la figura grande. `row_heights` es una fraccion de lo que sobra tras el
    espaciado, asi que quitar una fila sin recalcular el alto y las fracciones a la vez
    NO devuelve a las dos de arriba el tamano que tenian: las estira.
"""

from __future__ import annotations

import re

from ayudas_tableros import fuente_de_tablero

CUADERNO = "04_uiti_vano_trayectorias_vano"


def _fuente() -> str:
    return fuente_de_tablero(CUADERNO, solo_codigo=True)


def _sin_comentarios(fuente: str) -> str:
    return "\n".join(l for l in fuente.splitlines() if not l.lstrip().startswith("#"))


def _panel() -> str:
    m = re.search(r"PANEL_HTML = f'''(.*?)'''", _fuente(), re.S)
    assert m, "no se pudo leer `PANEL_HTML`"
    return m.group(1)


# ------------------------------------------------------------------- los dos textos


def test_el_parrafo_largo_de_la_lista_se_queda_en_una_linea():
    """De ocho lineas de mecanica a una que dice el periodo.

    Lo que explicaba -- que la lista no cambia con el deslizador, a quien se marca al
    entrar, que se puede agregar y quitar, y que significa el recuadro -- se descubre
    usando el tablero. Lo que NO se descubre es de que periodo es la lista, y eso es lo
    que se queda.
    """
    panel = _panel()
    assert "La lista trae los vanos con eventos del circuito" not in panel, (
        "el parrafo largo sigue en el panel")
    assert "se encierra en un recuadro del color de su grupo" not in panel, (
        "queda parte del parrafo largo en el panel")
    assert "Lista de vanos con eventos del circuito en el periodo:" in panel, (
        "no esta la linea que sustituye al parrafo")
    assert "{PERIODO_ANALISIS}" in panel, (
        "la linea no trae el periodo; escrito a mano dejaria de ser cierto al cambiar los "
        "datos")


def test_el_periodo_sale_de_las_ventanas_y_no_de_una_constante():
    """Primera ventana y ultima, que es lo que el tablero cubre de verdad."""
    fuente = _sin_comentarios(_fuente())
    assert re.search(r"PERIODO_ANALISIS\s*=", fuente), "no se declara `PERIODO_ANALISIS`"
    # La declaracion ocupa dos lineas: se lee hasta el `PERIODOS =` que la sigue, no
    # con un `.*` que se corta en el primer salto y perderia el `VENTANAS[-1]`.
    decl = re.search(r"PERIODO_ANALISIS\s*=(.*?)\n\n", fuente, re.S).group(1)
    assert "VENTANAS[0]" in decl and "VENTANAS[-1]" in decl, (
        f"el periodo no se deriva de las ventanas: {decl}")


def test_el_aviso_ya_no_manda_al_usuario_a_la_evolucion():
    """Esa frase apuntaba a un panel que ya no esta debajo de ella."""
    fuente = _fuente()
    assert "su evolucion abajo dice en que ventanas si" not in fuente, (
        "el aviso sigue mandando a la evolucion de abajo")


# ------------------------------------------------- el perfil, de vuelta en la figura


def test_el_perfil_es_un_subplot_de_la_figura_grande():
    """Vuelve a la figura, en la ULTIMA fila y a la izquierda de la evolucion.

    Estuvo un tiempo en su propia figura, debajo del panel. Alli tenia el ancho del panel
    -- una columna del 30% -- y su titulo se salia por los dos lados; aqui comparte fila
    con la evolucion y hereda su alto, que es lo que se pidio.

    Volver NO es deshacer: la fila de abajo pasa de cuatro paneles a CINCO, y en quince
    columnas no caben. Ver `test_la_rejilla_crece_a_veinte_columnas`.
    """
    fuente = _sin_comentarios(_fuente())
    assert "fig_perfil" not in fuente, "sigue existiendo la figura aparte del perfil"
    assert "DIV_PERFIL" not in fuente, "sigue existiendo el div aparte del perfil"
    assert "caja-perfil" not in fuente, "sigue el envoltorio que lo bajaba 50 px"
    assert re.findall(r"\), row=2, col=1\)", fuente), (
        "ninguna traza va a (2,1), que es donde va el perfil")


def test_la_rejilla_crece_a_veinte_columnas():
    """Cinco paneles y sus cuatro canales no caben en quince.

    Las columnas EN BLANCO entre panel y panel no son decoracion: son los canales donde
    cada eje y dibuja sus marcas, y donde el eje DERECHO de la evolucion pone las suyas.
    Sin ellos las etiquetas de un panel se superponen con el vecino.

    La cuenta con quince, dandole dos columnas a cada panel pequenio:

        perfil 3 + canal 1 + evolucion 3 + canal 1 + 3 x (2 + 1) = 17 > 15

    Con veinte cierra sin apretar a nadie: 4 + 1 + 5 + 1 + 2 + 1 + 2 + 1 + 2 + 1.
    """
    fuente = _sin_comentarios(_fuente())
    cols = re.search(r"rows=2, cols=(\d+)", fuente)
    assert cols and cols.group(1) == "20", (
        f"la rejilla declara {cols.group(1) if cols else '?'} columnas")
    anchos = re.search(r"column_widths=\[1 / (\d+)\] \* (\d+)", fuente)
    assert anchos and anchos.group(1) == anchos.group(2) == "20", (
        "los anchos de columna no siguen a `cols`; escritos aparte se separan")


def test_los_titulos_siguen_el_orden_de_lectura():
    """Plotly los reparte por filas sobre las casillas CON spec, no por nombre.

    El perfil entra ANTES que la evolucion porque va a su izquierda. Meterlo al final
    -- que es donde estaba cuando era la fila 3 -- le pone a cada panel el titulo del
    vecino, y no da ningun error.
    """
    fuente = _sin_comentarios(_fuente())
    titulos = re.search(r"subplot_titles=\((.*?)\),\n", fuente, re.S)
    assert titulos, "no se pudo leer `subplot_titles`"
    textos = re.findall(r"'([^']*)'", titulos.group(1))
    assert len(textos) == 7, f"son 7 casillas con spec, hay {len(textos)} titulos: {textos}"
    assert textos[2] == "Perfil del circuito", (
        f"el tercer titulo es el de (2,1), el perfil: {textos}")
    assert textos[3].startswith("Evolucion"), (
        f"el cuarto es el de la evolucion, a su derecha: {textos}")


def test_el_titulo_del_perfil_vuelve_a_ser_una_anotacion():
    """Dentro de la figura el titulo de un subplot ES una anotacion.

    Cuando el perfil vivia aparte era el titulo de SU figura y se cambiaba con un
    relayout sobre su div. De vuelta aqui ese div no existe.
    """
    fuente = _sin_comentarios(_fuente())
    assert "gdPerfil" not in fuente, (
        "el JS sigue buscando el div de la figura aparte, que ya no existe")
    assert "('perfil', 'Perfil del circuito')" in fuente, (
        "`TITULOS_N` no vuelve a declarar el perfil")
    assert "CTX.titulos.perfil" in fuente, (
        "el JS no reescribe el titulo del perfil por su anotacion")


def test_la_columna_de_controles_vuelve_a_llevar_solo_el_panel():
    """Sin el perfil debajo, no queda nada mas que poner ahi."""
    fuente = _sin_comentarios(_fuente())
    assert re.search(r'col-controles">\{PANEL_HTML\}</div>', fuente), (
        "la columna de controles no lleva solo el panel")


# --------------------------------------------------------------- el boton de encuadre


def test_el_boton_de_encuadre_sube_encima_del_mapa():
    """Como en el 01 y en el 03: una `.barra-encuadre` delante de la figura."""
    panel = _panel()
    assert "v4-centrar" not in panel, (
        "el boton de encuadre sigue dentro del panel de control")
    fuente = _sin_comentarios(_fuente())
    assert "BARRA_ENCUADRE" in fuente, "el 04 no declara su barra de encuadre"
    col = re.search(r"col-figuras\">\{(\w+)\}\{(\w+)\}</div>", fuente)
    assert col and col.group(1) == "BARRA_ENCUADRE" and col.group(2) == "FIGURA_HTML", (
        f"la barra no va encima de la figura: {col.groups() if col else None}")


def test_la_barra_del_04_se_alinea_con_su_mapa():
    """Mismo `calc()` que el 03: el mapa no empieza en el margen de la figura."""
    fuente = _sin_comentarios(_fuente())
    assert re.search(r"\.barra-encuadre \{\{[^}]*calc\(", fuente), (
        "la barra no calcula su sangria")
    assert re.search(r"MAPA_IZQ\s*=\s*float\(fig\.layout\.map\.domain\.x\[0\]\)", fuente), (
        "`MAPA_IZQ` no se lee de la figura")
