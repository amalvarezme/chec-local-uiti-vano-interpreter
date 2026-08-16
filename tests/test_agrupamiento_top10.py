"""El top 10 y el ranking de circuitos tienen que ordenar por lo MISMO.

Los dos paneles de la derecha del tablero 02 responden a la misma pregunta -- que
circuitos concentran los vanos criticos -- y hasta este cambio la respondian con
criterios distintos:

    top 10                 ordenaba por vanos en clase Alto, a secas
    Grupos Circuitos       ordena por Medio-Alto + Alto

Medido sobre la ventana completa, de los diez circuitos del top solo DOS estaban
entre los diez ultimos del ranking. Ocho no. Puestos uno al lado del otro en la
misma figura, eso se lee como un error de datos, no como dos preguntas distintas.

Ahora los dos usan `critDe()`, la suma de las dos clases criticas. Un circuito con
muchos vanos a un paso de la clase peor es tan accionable como uno que ya los tiene
ahi, y esa era ya la razon declarada del panel de abajo.

Las pruebas son sobre la FUENTE del JS y no sobre el navegador: el panel es
JavaScript generado dentro de un HTML, y este repo fija ese contrato leyendo el
codigo, como en `test_agrupamiento_disposicion.py`.
"""

from __future__ import annotations

import re

from ayudas_tableros import fuente_de_tablero


def _panel_js() -> str:
    """El bloque de JavaScript del panel de vanos, que es el que ordena."""
    fuente = fuente_de_tablero("02_uiti_vano_kmeans", solo_codigo=True)
    i = fuente.index("PANEL_VANO_JS = ")
    return fuente[i:]


def _sin_comentarios(js: str) -> str:
    """Fuera los comentarios de linea, para no acertar por lo que dice un `//`."""
    return "\n".join(l for l in js.splitlines() if not l.lstrip().startswith("//"))


def test_las_dos_clases_criticas_se_suman_en_un_solo_sitio():
    """`critDe` es la definicion unica de "vano critico" del tablero.

    Que exista una sola vez es lo que impide que los dos paneles vuelvan a
    separarse: cambiar el criterio en uno y olvidar el otro deja de ser posible.
    """
    js = _sin_comentarios(_panel_js())
    definiciones = re.findall(r"function critDe\s*\(", js)
    assert len(definiciones) == 1, (
        f"`critDe` esta definida {len(definiciones)} veces; tiene que ser una sola")
    assert re.search(
        r"function critDe\s*\(c\)\s*\{\s*return porCirc\[c\]\[ALTO - 1\] \+ porCirc\[c\]\[ALTO\];",
        js), "`critDe` ya no suma Medio-Alto (ALTO - 1) con Alto"


def test_el_top_10_ordena_por_la_suma_y_no_por_alto_a_secas():
    """El orden del top sale de `critDe`, igual que el del panel de abajo."""
    js = _sin_comentarios(_panel_js())
    # El cuerpo del `sort` lleva su propio `;` dentro del `return`, asi que no se
    # puede acotar con [^;]: se corta hasta el `.slice(0, 10)`, que es su final.
    orden = re.search(r"var ranking = Object\.keys\(porCirc\)\.sort\((.+?)\)\.slice\(0, 10\)",
                      js, re.S)
    assert orden, "no se pudo leer el orden del top 10"
    cuerpo = orden.group(1)
    assert "critDe(b) - critDe(a)" in cuerpo, (
        f"el top 10 no ordena por `critDe`: {cuerpo.strip()}")
    assert "porCirc[b][ALTO] - porCirc[a][ALTO]" not in cuerpo, (
        "el top 10 sigue ordenando por la clase Alto a secas")


def test_critDe_esta_declarada_antes_de_que_el_top_la_use():
    """Las declaraciones de funcion se izan, asi que esto NO es un error de runtime.

    Es justamente por eso que se fija: si `critDe` se quedara despues del top, el
    codigo funcionaria igual y el lector tendria que confiar en el izado para
    entender por que. Se lee de arriba abajo o no se lee.
    """
    js = _sin_comentarios(_panel_js())
    assert js.index("function critDe") < js.index("var ranking = Object.keys(porCirc)"), (
        "`critDe` se declara despues del top 10 que la usa")


def test_el_titulo_del_top_nombra_las_dos_clases():
    """Si el panel cuenta dos clases, su titulo no puede nombrar una.

    El texto es ademas la LLAVE con la que el JS encuentra la anotacion para
    reescribirla con el numero de circuitos (`TITULOS_N_VANO`), asi que cambiarlo
    en un solo sitio revienta al generar en vez de rotular mal en silencio.
    """
    fuente = fuente_de_tablero("02_uiti_vano_kmeans", solo_codigo=True)
    assert "'Top 10 clase Alto'" not in fuente, (
        "el titulo sigue nombrando solo la clase Alto")
    assert fuente.count("'Top 10 Medio-Alto + Alto'") == 2, (
        "el titulo nuevo tiene que estar en `subplot_titles` y en `TITULOS_N_VANO`")


def test_el_hover_del_top_muestra_la_suma_que_lo_ordena():
    """El numero por el que un circuito esta en la lista tiene que poder leerse.

    Sin el, el top muestra porcentajes de cuatro clases y el motivo del puesto
    -- la suma de las dos criticas -- se queda fuera de la figura.
    """
    js = _sin_comentarios(_panel_js())
    assert "critDe(ranking[i])" in js, (
        "el hover del top 10 no muestra la suma Medio-Alto + Alto")
