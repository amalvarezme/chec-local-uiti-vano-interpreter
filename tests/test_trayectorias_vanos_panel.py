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


# --------------------------------------------------------- el perfil, en su propia figura


def test_el_perfil_sale_de_la_figura_grande():
    """Ni traza, ni fila, ni titulo de subplot dentro de `fig`."""
    fuente = _sin_comentarios(_fuente())
    assert "'Perfil del circuito')," not in fuente, (
        "`subplot_titles` sigue nombrando el perfil")
    assert not re.search(r"row=3, col=1\)", fuente), (
        "queda algo en la fila 3 de la figura grande")
    idx = re.search(r"IDX = \{(.*?)\n    \}", fuente, re.S)
    assert idx, "no se pudo leer `IDX`"
    assert "'perfil'" not in idx.group(1), (
        "`IDX` de la figura grande sigue declarando el perfil")


def test_la_figura_grande_vuelve_a_dos_filas_con_su_alto_recalculado():
    """Quitar una fila sin tocar el alto estira las dos que quedan.

    `row_heights` es una fraccion de lo que sobra DESPUES del espaciado, asi que el alto
    total, las fracciones y el espaciado se recalculan a la vez para que las filas 1 y 2
    conserven los pixeles que median.
    """
    fuente = _sin_comentarios(_fuente())
    filas = re.search(r"rows=(\d+), cols=15", fuente)
    assert filas and filas.group(1) == "2", (
        f"la figura grande declara {filas.group(1) if filas else '?'} filas")
    alturas = re.search(r"row_heights=\[([^\]]+)\]", fuente)
    assert alturas, "no se declaran `row_heights`"
    assert len([x for x in alturas.group(1).split(",")]) == 2, (
        f"`row_heights` sigue teniendo tres fracciones: {alturas.group(1)}")


def test_el_perfil_tiene_su_figura_y_su_div():
    """Traza 0 de una figura propia, con su propio div y su propio titulo."""
    fuente = _sin_comentarios(_fuente())
    assert "fig_perfil" in fuente, "no existe la figura del perfil"
    assert re.search(r"DIV_PERFIL\s*=", fuente), "el perfil no tiene div propio"
    assert re.search(r"pio\.to_html\(fig_perfil", fuente), (
        "la figura del perfil no se serializa")


def test_el_perfil_va_en_la_columna_izquierda_debajo_del_panel():
    """Mismo ancho que el panel, que es lo que da la columna de controles."""
    fuente = _sin_comentarios(_fuente())
    col = re.search(r"col-controles\">\{(\w+)\}\{(\w+)\}</div>", fuente)
    assert col, (
        "la columna de controles no lleva dos piezas; el perfil tiene que ir debajo "
        "del panel")
    assert col.group(1) == "PANEL_HTML" and col.group(2) == "PERFIL_HTML", (
        f"el orden de la columna izquierda no es panel y luego perfil: {col.groups()}")


def test_el_titulo_del_perfil_deja_de_ser_una_anotacion_de_subplot():
    """Ahora es el titulo de SU figura, y se cambia con un relayout sobre su div.

    Mutar `fig_anotaciones[CTX.titulos.perfil[0]]` era correcto mientras el perfil fuera
    un subplot de la figura grande. Fuera de ella ese indice apunta a otra cosa, y mutarlo
    reescribiria el titulo de un panel vecino sin fallar.
    """
    fuente = _sin_comentarios(_fuente())
    assert "CTX.titulos.perfil" not in fuente, (
        "el JS sigue tratando el titulo del perfil como una anotacion de la figura grande")
    assert "('perfil', 'Perfil del circuito')" not in fuente, (
        "`TITULOS_N` sigue declarando el perfil")
    assert re.search(r"Plotly\.relayout\(\s*gdPerfil", fuente), (
        "el titulo del perfil no se cambia con un relayout sobre su propio div")


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


def test_el_perfil_baja_50px_respecto_del_panel():
    """Cincuenta pixeles de aire entre el panel y el perfil.

    Medido antes: el hueco eran 6 px -- el `margin-bottom` del propio panel --, asi que el
    perfil arrancaba pegado al borde de la caja de controles y los dos se leian como una
    sola pieza.

    El desplazamiento va en un envoltorio y NO en el `margin.t` de la figura. Subir el
    margen de la figura mueve el area de dibujo DENTRO de un div que sigue donde estaba:
    baja las barras y deja el titulo flotando, en vez de bajar el panel entero. El
    envoltorio mueve las dos cosas juntas y no toca la figura.

    Y es `padding-top`, no `margin-top`. Los margenes verticales de hermanos adyacentes
    COLAPSAN al mayor: contra el `margin-bottom: 6px` del panel, un `margin-top: 50px`
    deja el hueco en 50 -- medido -- y el perfil baja 44, no 50. El relleno no colapsa.

    Tampoco va en `CSS_DOS_COLUMNAS`: ese bloque viaja COPIADO en el 01 y en el 04 y una
    prueba exige que las copias sean identicas byte a byte, asi que una regla que solo
    necesita este tablero lo separaria de su gemelo.
    """
    fuente = _sin_comentarios(_fuente())
    assert re.search(r"\.caja-perfil \{\{[^}]*padding-top:\s*50px", fuente), (
        "el perfil no baja 50 px respecto del panel")
    assert not re.search(r"\.caja-perfil \{\{[^}]*margin-top", fuente), (
        "usa `margin-top`, que colapsa contra el margen del panel y baja menos de 50 px")
    assert re.search(r'<div class="caja-perfil">', fuente), (
        "el perfil no va dentro de su envoltorio")
    css_compartido = re.search(r"CSS_DOS_COLUMNAS = '''(.*?)'''", _fuente(), re.S)
    assert css_compartido and "caja-perfil" not in css_compartido.group(1), (
        "la regla se colo en el CSS que este tablero comparte byte a byte con el 01")
