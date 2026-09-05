"""El reparto de UITI por circuito: la tercera fila del tablero 02.

Debajo de "Grupos Circuitos" -- que ordena los 208 circuitos por VANOS en clase
Medio-Alto y Alto -- va una segunda hilera con los mismos circuitos ordenados por el
PORCENTAJE del UITI acumulado que se lleva cada uno en la ventana elegida.

Son dos preguntas que se parecen y no son la misma. Un circuito puede tener muchos vanos
criticos y poco UITI (el daño repartido y leve) u ocho vanos y una quinta parte del UITI
de la ventana (el daño concentrado). El tablero ya tenia la primera lectura; la segunda es
la que dice DONDE esta el impacto, que es lo que decide a donde va la cuadrilla.

Las pruebas son sobre la FUENTE del JS y no sobre el navegador, como en
`test_agrupamiento_top10.py` y `test_agrupamiento_disposicion.py`: el panel es JavaScript
generado dentro de un HTML, y este repo fija ese contrato leyendo el codigo.
"""

from __future__ import annotations

import re

from ayudas_tableros import fuente_de_tablero


def _panel_js() -> str:
    fuente = fuente_de_tablero("02_uiti_vano_kmeans", solo_codigo=True)
    i = fuente.index("PANEL_VANO_JS = ")
    return fuente[i:]


def _sin_comentarios(js: str) -> str:
    """Fuera los comentarios de linea, para no acertar por lo que dice un `//`."""
    return "\n".join(l for l in js.splitlines() if not l.lstrip().startswith("//"))


def _bloque_uiti(js: str) -> str:
    """El bloque que arma la hilera de UITI, acotado por su propio marcador."""
    i = js.index("--- Fila 3: reparto del UITI acumulado por circuito")
    return js[i:]


def test_las_barras_van_de_menor_a_mayor_porcentaje():
    """El usuario lee de izquierda a derecha y la pregunta termina a la derecha.

    Ordenar de mayor a menor pone los circuitos que importan pegados al eje y deja la
    cola larga ocupando el ancho: con 208 barras eso es casi toda la figura diciendo
    nada. Ascendente, los que concentran el UITI quedan al final, que es donde la vista
    se detiene, y ademas queda alineado con la hilera de arriba, que tambien sube.
    """
    bloque = _sin_comentarios(_bloque_uiti(_panel_js()))
    orden = re.search(r"ordenUiti\.sort\(function \(a, b\) \{\s*return ([^;]+);", bloque)
    assert orden, "no se encontro el comparador que ordena la hilera de UITI"
    cuerpo = orden.group(1)
    assert "pctUiti[a] - pctUiti[b]" in cuerpo, (
        f"el comparador no ordena ASCENDENTE por porcentaje: {cuerpo!r}")
    assert "pctUiti[b] - pctUiti[a]" not in cuerpo, (
        "el comparador ordena descendente; la hilera quedaria al reves que la de arriba")


def test_el_porcentaje_se_calcula_sobre_el_uiti_de_la_ventana():
    """El denominador es el UITI de la VENTANA, no un total fijo del periodo entero.

    Con un total fijo los porcentajes de una ventana corta no suman 100 y dejan de ser un
    reparto: se vuelven una fraccion de otra cosa, sin decir de que. `uitiCirc` ya lo
    calcula circuito a circuito con el rango elegido, asi que el total es su suma.
    """
    bloque = _sin_comentarios(_bloque_uiti(_panel_js()))
    assert re.search(r"totalUiti\s*\+=\s*uitiCirc\[", bloque), (
        "el total no se acumula desde `uitiCirc`, que es lo que respeta la ventana")
    assert re.search(r"100\s*\*\s*uitiCirc\[[^\]]+\]\s*/\s*totalUiti", bloque), (
        "el porcentaje no se calcula como uitiCirc / totalUiti")


def test_una_ventana_sin_uiti_no_divide_por_cero():
    """Un rango sin un solo evento es un resultado real, no un fallo.

    Sin la guarda cada barra sale NaN y Plotly dibuja el panel vacio sin un mensaje: se
    lee como un tablero roto en vez de como una ventana tranquila.
    """
    bloque = _sin_comentarios(_bloque_uiti(_panel_js()))
    assert "totalUiti > 0" in bloque or "totalUiti ?" in bloque, (
        "no hay guarda contra un UITI total en cero")


def test_el_hover_nombra_el_uiti_absoluto_y_no_solo_el_porcentaje():
    """Un porcentaje sin su magnitud no se puede accionar.

    El 12% de una ventana tranquila y el 12% de una ventana mala no son el mismo trabajo,
    y con 208 barras no hay donde escribir el numero encima: va al hover.
    """
    bloque = _bloque_uiti(_panel_js())
    assert "uitiCirc[" in bloque and "hovUiti" in bloque, (
        "el hover de la hilera de UITI no lleva el acumulado absoluto")


def test_la_hilera_de_uiti_reusa_el_adelgazador_de_rotulos():
    """208 nombres rotados no caben, y el problema ya estaba resuelto una vez.

    `rotularFila5` calcula el paso con el ancho REAL del subplot. Duplicarlo con un paso
    fijo devolveria el pisado de rotulos que esa funcion existe para evitar, y solo en
    una de las dos hileras.
    """
    js = _sin_comentarios(_panel_js())
    assert "rotularHilera" in js, (
        "no hay un adelgazador compartido entre las dos hileras de circuitos")
    assert js.count("PX_POR_ETIQUETA") >= 1, "el paso volvio a ser un numero fijo"
