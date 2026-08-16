"""Cada panel del tablero 06 escribe en SU celda de la rejilla, y no en la del vecino.

El tablero es un `make_subplots` de 6x4, y todo el mundo se dirige a sus paneles por
`row=` / `col=`. Eso no lo comprueba nadie en tiempo de ejecucion: escribirle a la celda
equivocada no levanta ningun error, deja el panel propio sin configurar y le pisa la
configuracion al ajeno. Es exactamente lo que paso, y el sintoma no se parecio en nada a
la causa.

## El fallo que motiva este archivo

`_pintar_top_por_vano` fija el rango de su eje antes de escribir las barras -- lo necesita
para decidir que rotulo cabe en cada una -- con

    fig.update_yaxes(range=[0, _rango], row=3, col=3)

y el panel del top vive en la fila **4**. La fila 3, columna 3 es el **grafo**. Cuando el
perfil del circuito entro como fila nueva, el top bajo de la fila 3 a la 4 y esta llamada
se quedo donde estaba.

Consecuencias, las dos medidas en el navegador sobre la aplicacion servida:

  * **El grafo se sale de su recuadro.** Su eje Y queda en `[0, _rango]` en vez del
    `[-1.75, 1.75]` simetrico que le fija la figura. Con `scaleanchor` activo, plotly
    estira ese rango hasta cuadrar los pixeles por unidad y el resultado es
    `[-0.737, 1.737]`: centrado en 0,5 y no en 0. Los nodos viven sobre el circulo de
    radio 1, asi que todo lo que hay por debajo de `y = -0,737` -- el arco inferior y sus
    rotulos -- cae FUERA del panel. Y los rotulos son anotaciones, que plotly no recorta
    al subplot: se dibujan encima del panel de al lado.
  * **El top por vano se queda sin rango.** Nadie se lo fija ya, que es justo lo que su
    propio docstring dice que hay que evitar: con las trazas vacias el eje autoescala a
    `[-1, 4]` y saca marcas negativas para una caida que no puede serlo.

Por eso lo que se fija aqui no es "el grafo se ve bien" -- eso pide un navegador -- sino
la propiedad que lo garantiza y que se puede leer del codigo: **quien escribe en una
celda de la rejilla es el panel que vive en ella**.

## Que cambio al salir el tablero del cuaderno

Este fichero repartia las llamadas por CELDA del cuaderno, y de ahi sacaba la unica
distincion que necesita: la figura se arma una vez, y despues cada funcion la repinta.
Esa frontera era un accidente del formato -- nadie eligio que armar la figura fuera la
celda 11 -- y desaparecio al juntarlo todo en `construir()`.

La frontera que si existe, y que es la que se queria desde el principio, es de AMBITO:
armar la figura son sentencias del cuerpo de `construir()`, y repintar son llamadas
desde dentro de una funcion anidada. Se lee con `ast` en vez de con una expresion
regular, y de paso desaparecen las dos fragilidades que arrastraba: `_sin_comentarios`
por lineas -- que no distingue un `#` dentro de una cadena -- y `rows=(\\d+)` sobre el
texto entero, que en un modulo de 3.600 lineas casa con el `nrows=` de otra llamada.
"""

from __future__ import annotations

import ast
import functools
import re
from pathlib import Path

import ayudas_tableros

RAIZ = Path(__file__).resolve().parents[1]
TABLERO = "06_uiti_vano_explicabilidad_simulador"

# Donde vive cada panel en la rejilla de `make_subplots`.
#
# El GRAFO ya no esta en esta rejilla: se fue a su propia figura, debajo del panel de
# control, porque ese era su sitio pedido y un subplot no puede salirse de su figura. Sus
# ejes se configuran sobre `_fig_grafo` y sin `row`/`col`, asi que se le busca aparte --
# ver `_llamadas_a_los_ejes_del_grafo`.
#
# El TOP paso a la columna 1 y de ancho completo cuando la serie de UITI subio a la fila 3
# a compartir con el perfil. Antes el grafo y el top eran vecinos en las columnas 3-4, y
# era esa vecindad la que hacia que un desfase de uno no se notara al leerlo.
TOP_POR_VANO = (4, 1)

# El ambito en el que se ARMA la figura. Todo lo demas que le escriba a un eje es un
# repintado, y un repintado solo puede tocar su propio panel.
ARMADO = "construir"


@functools.cache
def _arbol() -> ast.Module:
    """UN solo arbol para todo el fichero.

    `functools.cache` no es una optimizacion: `_ambito_por_nodo` indexa por `id()`
    del nodo, asi que dos llamadas a `ast.parse` producirian dos arboles cuyos ids
    no se cruzan nunca y el ambito saldria `<modulo>` para todo.
    """
    return ast.parse(ayudas_tableros.fuente_de_tablero(TABLERO))


@functools.cache
def _ambito_por_nodo() -> dict[int, str]:
    """`id(nodo) -> nombre de la funcion mas interna que lo contiene`.

    `ast` no lleva punteros al padre, asi que se recorre de fuera hacia dentro
    arrastrando el nombre. Es lo que sustituye al indice de celda.
    """
    ambitos: dict[int, str] = {}

    def bajar(nodo, ambito: str) -> None:
        for hijo in ast.iter_child_nodes(nodo):
            propio = hijo.name if isinstance(
                hijo, (ast.FunctionDef, ast.AsyncFunctionDef)) else ambito
            ambitos[id(hijo)] = propio
            bajar(hijo, propio)

    bajar(_arbol(), "<modulo>")
    return ambitos


def _llamadas_a_ejes() -> list[tuple[str, str, int, int]]:
    """`(ambito, llamada, fila, columna)` de cada `update_?axes` con destino explicito."""
    ambitos = _ambito_por_nodo()
    encontradas = []
    for nodo in ast.walk(_arbol()):
        if not (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)):
            continue
        if nodo.func.attr not in ("update_xaxes", "update_yaxes"):
            continue
        destino = {k.arg: k.value for k in nodo.keywords if k.arg in ("row", "col")}
        if not (isinstance(destino.get("row"), ast.Constant)
                and isinstance(destino.get("col"), ast.Constant)):
            continue
        encontradas.append((ambitos.get(id(nodo), "<modulo>"), ast.unparse(nodo),
                            destino["row"].value, destino["col"].value))
    return encontradas


def _make_subplots() -> ast.Call:
    for nodo in ast.walk(_arbol()):
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                and nodo.func.id == "make_subplots"):
            return nodo
    raise AssertionError("el tablero ya no arma su figura con `make_subplots`")


def _llamadas_al_panel(fila: int, columna: int) -> list[str]:
    return [llamada for _amb, llamada, f, c in _llamadas_a_ejes()
            if (f, c) == (fila, columna)]


def _llamadas_a_los_ejes_del_grafo() -> list[str]:
    """Las llamadas que configuran los ejes de la figura PROPIA del grafo.

    No llevan `row`/`col` -- no hay rejilla que indexar --, asi que se reconocen por el
    nombre de la figura. Es lo que sustituye a buscarlas por su casilla.
    """
    fuente = ayudas_tableros.fuente_de_tablero(TABLERO)
    # Con los espacios COLAPSADOS: las llamadas ocupan varias lineas, y quien las lee
    # busca con `.*?`, que no cruza saltos de linea.
    return [" ".join(l.split()) for l in re.findall(
        r"_fig_grafo\.update_[xy]axes\((?:[^()]|\([^()]*\))*\)", fuente)]


def _funcion(nombre: str) -> str:
    return ayudas_tableros.cuerpo_de_funcion(
        ayudas_tableros.fuente_de_tablero(TABLERO), nombre)


# ------------------------------------------------------- el fallo, en su sitio exacto


def test_el_top_por_vano_le_escribe_a_su_propia_fila():
    """El rango del top va a (4,1), que es donde esta el top.

    Iba a (4,3) hasta que la serie de UITI subio a la fila 3 y el top se quedo con el
    ancho entero. Antes de eso iba a la 3 -- el grafo -- porque el perfil entro como fila
    nueva y bajo al top una fila sin que esta llamada se enterara. Dos veces el mismo
    fallo: por eso esta prueba.
    """
    cuerpo = _funcion("_pintar_top_por_vano")
    destinos = re.findall(r"update_yaxes\([^)]*row=(\d+),\s*col=(\d+)", cuerpo)
    assert destinos, "_pintar_top_por_vano ya no fija el rango de su eje"
    for fila, columna in destinos:
        assert (int(fila), int(columna)) == TOP_POR_VANO, (
            f"_pintar_top_por_vano escribe en la fila {fila}, columna {columna}. "
            f"El top vive en {TOP_POR_VANO}; escribirle a otra casilla le cambia el "
            "descentra el circulo y lo saca de su recuadro.")


def test_nadie_mas_que_la_figura_le_toca_el_rango_al_grafo():
    """El grafo recibe su rango UNA vez, al armar la figura, y nadie se lo reescribe.

    Su eje no mide nada: es una disposicion circular, y el rango es lo unico que reparte
    el panel entre el anillo y los nombres de sus nodos. Cualquier repintado que se lo
    cambie -- aunque sea a un rango razonable para otra cosa -- descentra el circulo,
    porque `scaleanchor` estira lo que reciba hasta cuadrar los pixeles y conserva el
    CENTRO de lo que le den.
    """
    # El grafo ya no vive en una casilla de la rejilla, asi que la regla cambia de forma
    # sin cambiar de fondo: a sus ejes solo se les escribe al ARMAR su figura. Un repintado
    # que le tocara el rango le descentraria el circulo igual que antes.
    culpables = [(ambito, llamada[:90])
                 for ambito, llamada, fila, col in _llamadas_a_ejes()
                 if "_fig_grafo" in llamada and ambito != ARMADO]
    assert not culpables, (
        f"estas llamadas le reescriben los ejes al grafo desde fuera del armado de la "
        f"figura: {culpables}")


def test_el_rango_del_grafo_es_simetrico():
    """Centrado en 0, que es donde esta el centro del circulo.

    Un rango asimetrico no se ve como un error: se ve como un grafo que se sale por un
    lado y deja una banda blanca por el otro.
    """
    rangos = [m for llamada in _llamadas_a_los_ejes_del_grafo()
              for m in re.findall(r"update_([xy])axes\(.*?range=\[([^\]]+)\]", llamada)]
    assert len(rangos) == 2, f"el grafo deberia fijar sus dos ejes; se hallaron {rangos}"
    limites = []
    for eje, valores in rangos:
        bajo, alto = (v.strip() for v in valores.split(","))
        assert bajo == f"-{alto}", (
            f"el eje {eje} del grafo va de {bajo} a {alto}: el circulo queda descentrado")
        limites.append(alto)
    # Y el MISMO en los dos. Dos rangos distintos con `scaleanchor` estan
    # sobredeterminados: plotly reconcilia en el navegador estirando uno, y el que se
    # estira es el que tenia calculado el sitio de los rotulos.
    assert limites[0] == limites[1], (
        f"los dos ejes del grafo llevan rangos distintos ({limites}); con `scaleanchor` "
        "eso lo decide plotly en el navegador y el circulo deja de llenar su panel")


def test_el_grafo_encoge_su_recuadro_y_no_su_rango():
    """`constrain='domain'` en los dos ejes del grafo.

    Con el 'range' por defecto, plotly cuadra los pixeles por unidad ESTIRANDO el rango
    del eje al que le sobra sitio. Pero aqui el rango no es una escala: es lo que reparte
    el panel entre el anillo y los nombres de sus nodos, y estirarlo encoge el circulo
    dentro de un panel que no cambia -- medido: 162 px de radio a 1.280, 1.512 y 1.900 px
    de ventana, con el panel creciendo hasta 789. Con 'domain' plotly respeta el rango y
    encoge el RECUADRO: el panel se vuelve cuadrado dentro de su celda y el circulo lo
    llena. Lo que sobra se queda dentro de la celda en vez de salirse a la de al lado.
    """
    for eje in ("x", "y"):
        llamada = next((l for l in _llamadas_a_los_ejes_del_grafo()
                        if f"update_{eje}axes(" in l), None)
        assert llamada, f"el grafo no configura su eje {eje}"
        assert "constrain='domain'" in llamada, (
            f"el eje {eje} del grafo no lleva `constrain='domain'`: plotly le estirara "
            "el rango y el circulo se quedara pequenio dentro de su panel")


def test_cada_celda_de_la_rejilla_existe_en_las_especificaciones():
    """Ningun `row=`/`col=` apunta fuera de la rejilla declarada.

    Plotly no avisa: `update_yaxes(row=9, col=9)` no encuentra nada y no hace nada, y el
    panel se queda sin configurar sin que nadie lo diga.
    """
    # De los argumentos de `make_subplots`, no de una busqueda por texto: en un modulo
    # de 3.600 lineas, `rows=(\d+)` casa tambien con el `nrows=` de cualquier otra
    # llamada, y una rejilla inventada deja pasar todo lo demas.
    rejilla = {k.arg: k.value.value for k in _make_subplots().keywords
               if k.arg in ("rows", "cols") and isinstance(k.value, ast.Constant)}
    filas, columnas = rejilla["rows"], rejilla["cols"]
    for ambito, llamada, fila, col in _llamadas_a_ejes():
        assert 1 <= fila <= filas and 1 <= col <= columnas, (
            f"{ambito}: `{llamada[:80]}` apunta fuera de la rejilla "
            f"{filas}x{columnas}")
