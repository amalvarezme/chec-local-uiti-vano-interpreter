"""El tablero 02 vuelve a apilarse, y su figura se reordena en dos filas.

Los otros tres visores ganaron con el reparto 30/70 -- sus paneles de control son largos y
la figura les queda al lado --, pero el del 02 son DOS fechas y un boton: 212 px medidos
contra 1.700 de figura. Ese 30% dejaba ~1.500 px muertos en la columna izquierda.

Aqui el panel vuelve ARRIBA, a lo ancho, y la figura ocupa el ancho entero debajo.

## La rejilla

    fila 1:  barras "Vanos por grupo"  |  dispersion vano x ventana  |  "Top 10 clase Alto"
    fila 2:  violines "UITI acumulado" |  ranking de circuitos, sobre esas dos columnas

La fila de arriba es la lectura por VANO -- cuantos hay en cada grupo, donde caen en el
plano eventos x UITI, y que circuitos concentran los peores --, y la de abajo la lectura
por DISTRIBUCION y por CIRCUITO. El ranking sigue debajo de la dispersion y sobre sus
mismas dos columnas, que es lo que deja leer las dos como una sola cosa.

Y se fueron las dos densidades marginales con sus ocho trazas: repetian en forma lo que
la dispersion ya dice con sus puntos, y cada una se llevaba una fila o una columna
enteras del tablero.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from ayudas_tableros import fuente_de_tablero

RAIZ = Path(__file__).resolve().parents[1]

# Donde tiene que quedar cada panel. Arriba, las tres lecturas por vano; abajo, los
# violines y el ranking de circuitos.
DESTINOS = {
    "barras": (1, 1),
    "dispersion": (1, 2),
    "top10": (1, 3),
    "violines": (2, 1),
    "ranking": (2, 2),
}


def _celdas() -> list[str]:
    """La fuente del tablero, ya venga del cuaderno o de `src/chec_tableros/`."""
    return [fuente_de_tablero("02_uiti_vano_kmeans", solo_codigo=True)]


def _celda_de_la_figura() -> str:
    """El bloque que arma la figura de VANOS, que es la que se exporta.

    El 02 arma DOS figuras y solo exporta la de vanos, asi que el bloque hay que
    acotarlo: en el cuaderno lo acotaba la frontera de celda, y en el modulo no hay
    ninguna. Se corta desde `fig_vano = make_subplots(` porque a partir de ahi todo
    lo que sigue es de esa figura.
    """
    fuente = _celdas()[0]
    i = fuente.index("fig_vano = make_subplots(")
    return fuente[i:]


def _sin_comentarios(fuente: str) -> str:
    return "\n".join(l for l in fuente.splitlines() if not l.lstrip().startswith("#"))


def _rejilla(celda: str) -> tuple[int, int]:
    filas = int(re.search(r"rows=(\d+)", celda).group(1))
    columnas = int(re.search(r"cols=(\d+)", celda).group(1))
    return filas, columnas


# --------------------------------------------------------- el panel, arriba y a lo ancho


def test_el_tablero_de_vanos_no_va_en_dos_columnas():
    """El panel del 02 son dos fechas y un boton: 212 px contra 1.700 de figura.

    Reservarle el 30% del ancho dejaba ~1.500 px muertos debajo. Apilado, ese espacio se
    lo queda la figura, que es la que tiene algo que dibujar.
    """
    fuente = "\n".join(_celdas())
    assert "cuerpo-2col" not in fuente, (
        "el 02 sigue partido en dos columnas; su panel no da para una columna propia")
    assert "PANEL_VANOS_SOLO = PANEL_CSS + PANEL_VANO_HTML" in fuente, (
        "el tablero exportado ya no apila panel y figura")


# ------------------------------------------------------------------- la rejilla nueva


def test_la_rejilla_es_de_dos_por_tres():
    """Dos filas y tres columnas: cinco paneles y ni una casilla de relleno.

    La fila que se fue era la del top 10, que ahora comparte la de arriba con las otras
    dos lecturas por vano.
    """
    celda = _sin_comentarios(_celda_de_la_figura())
    filas, columnas = _rejilla(celda)
    assert (filas, columnas) == (2, 3), f"la figura declara {filas}x{columnas}"


def test_las_densidades_marginales_ya_no_se_dibujan():
    """Ocho trazas menos, y con ellas la fila de arriba y la columna de la derecha.

    Repetian en forma lo que la dispersion ya dice con sus puntos. Sus indices viajaban
    al JS, asi que quitarlas obliga a correr todo lo que venia detras: por eso hay una
    prueba y no solo un borrado.
    """
    fuente = _sin_comentarios("\n".join(_celdas()))
    assert "'kdeX'" not in fuente and "'kdeY'" not in fuente, (
        "los indices de las densidades siguen declarados")
    assert "kdeXeje" not in fuente and "kdeYeje" not in fuente, (
        "sus ejes siguen viajando al JS")
    assert "assert len(fig_vano.data) == 17" in fuente, (
        "el numero de trazas de la figura de vanos ya no es 17")


def test_cada_panel_esta_en_su_casilla():
    """El mapa completo, para que reordenar no dependa de leer nueve `add_trace`."""
    celda = _sin_comentarios(_celda_de_la_figura())
    # (traza que lo identifica, destino). El orden de las trazas NO cambia -- los indices
    # de `IDX_VANO` cuelgan de el --, solo cambia la casilla de cada una.
    esperado = {
        "go.Contour(": DESTINOS["dispersion"],
        "go.Scattergl(": DESTINOS["dispersion"],
    }
    for aguja, destino in esperado.items():
        i = celda.index(aguja)
        cierre = re.search(r"\),\s*row=(\d+),\s*col=(\d+)\)", celda[i:])
        assert cierre, f"no se pudo leer la casilla de {aguja}"
        assert (int(cierre.group(1)), int(cierre.group(2))) == destino, (
            f"{aguja} no esta en {destino}")


def test_la_dispersion_ya_no_se_lleva_dos_filas():
    """Ocupaba dos filas y dos columnas; ahora es una casilla como las demas.

    Es lo que libera la columna 3 de la fila 1 para el top 10 y deja la fila 2 entera
    para los violines y el ranking.
    """
    celda = _sin_comentarios(_celda_de_la_figura())
    assert "'rowspan'" not in celda, (
        "algun panel sigue ocupando dos filas")


def test_el_ranking_va_justo_debajo_del_scatter_y_sobre_sus_mismas_columnas():
    """Las dos de la derecha, ni una mas.

    184 barras con sus nombres rotados necesitan ancho, pero alinearlas con la dispersion
    y el top 10 es lo que deja leer las tres como una sola lectura: los circuitos de la
    derecha del ranking son los que pueblan la esquina superior de la nube.
    """
    celda = _sin_comentarios(_celda_de_la_figura())
    assert re.search(r"\[\{\}, \{'colspan': 2\}, None\],", celda), (
        "la ultima fila no pone el ranking sobre las dos columnas de la derecha")
    assert re.findall(r"\), row=2, col=2\)", celda), (
        "ninguna traza va a (2,2), que es la del ranking")


def test_las_dos_lecturas_por_grupo_comparten_la_columna_izquierda():
    """Barras arriba y violines abajo, las dos en la columna 1.

    Es lo que las pone debajo del panel de control, que es donde se pidieron, y lo que
    deja las dos columnas de la derecha para la dispersion, el top 10 y el ranking.
    """
    celda = _sin_comentarios(_celda_de_la_figura())
    assert re.search(r"row=1, col=1\)", celda), (
        "la fila 1 no coloca las barras en la columna izquierda")
    assert re.search(r"row=2, col=1\)", celda) or re.search(r"row=fila, col=1\)", celda), (
        "la fila 2 no coloca los violines en la columna izquierda")


def test_el_top_10_se_muda_a_la_esquina_superior_derecha():
    """Sus barras horizontales son la tercera casilla de la fila de arriba."""
    celda = _sin_comentarios(_celda_de_la_figura())
    assert re.findall(r"\), row=1, col=3\)", celda), (
        "ninguna traza va a (1,3), que es la del top 10")


def test_los_titulos_siguen_el_orden_de_lectura_de_la_rejilla():
    """Plotly los reparte por filas sobre las casillas CON subplot, no por nombre.

    Reordenar la rejilla sin reordenar esta tupla le pone a cada panel el titulo del
    vecino, y no da ningun error.
    """
    celda = _sin_comentarios(_celda_de_la_figura())
    titulos = re.search(r"subplot_titles=(\([^)]*\))", celda, re.S)
    assert titulos, "la figura no declara `subplot_titles`"
    # Se lee como tupla y no partiendo por comas: 'Top 10 circuitos, clase Alto' lleva una
    # coma dentro y partirla ahi inventa un titulo que no existe.
    textos = list(ast.literal_eval(titulos.group(1)))
    assert len(textos) == 5, f"son 5 casillas con subplot, hay {len(textos)} titulos"
    assert textos[0] == "Vanos por grupo", (
        f"el primer titulo es el de la casilla (1,1), que son las barras: {textos}")
    assert textos[1] == "", (
        f"el segundo es el de (1,2), la dispersion, que no lleva titulo: {textos}")
    assert textos[2].startswith("Top 10"), (
        f"el tercero es el de (1,3), el top 10: {textos}")
    assert textos[3] == "UITI acumulado", (
        f"el cuarto es el de (2,1), los violines: {textos}")
    assert textos[4].startswith("Grupos Circuitos"), (
        f"el quinto titulo es el del ranking, en (2,2): {textos}")
