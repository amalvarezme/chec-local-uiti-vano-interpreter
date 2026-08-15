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
la propiedad que lo garantiza y que se puede leer del cuaderno: **quien escribe en una
celda es el panel que vive en ella**.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CUADERNO = RAIZ / "notebooks" / "base_apps" / "06_uiti_vano_explicabilidad_simulador.ipynb"

# Donde vive cada panel en la rejilla de `make_subplots`, y como se le reconoce en el
# codigo. La fila del grafo y la del top son vecinas y las dos ocupan las columnas 3-4:
# es precisamente esa vecindad la que hace que un desfase de uno no se note al leerlo.
GRAFO = (3, 3)
TOP_POR_VANO = (4, 3)


def _celdas() -> list[str]:
    cuaderno = json.loads(CUADERNO.read_text(encoding="utf-8"))
    return ["".join(c["source"]) for c in cuaderno["cells"] if c["cell_type"] == "code"]


def _sin_comentarios(fuente: str) -> str:
    """El codigo, sin la prosa. Estas celdas explican por extenso en que fila esta cada
    panel, asi que buscar `row=3` sobre el texto crudo encuentra los comentarios."""
    return "\n".join(l for l in fuente.splitlines() if not l.lstrip().startswith("#"))


def _llamadas_a_ejes() -> list[tuple[int, str, int, int]]:
    """`(celda, llamada, fila, columna)` de cada `update_?axes` con destino explicito."""
    patron = re.compile(
        r"(update_[xy]axes)\((?:[^()]|\([^()]*\))*?row=(\d+),\s*col=(\d+)", re.S)
    encontradas = []
    for i, fuente in enumerate(_celdas()):
        for m in patron.finditer(_sin_comentarios(fuente)):
            encontradas.append((i, m.group(0), int(m.group(2)), int(m.group(3))))
    return encontradas


def _funcion(nombre: str) -> str:
    """El cuerpo de una funcion del cuaderno, hasta la siguiente definicion de nivel 0."""
    for fuente in _celdas():
        if f"def {nombre}(" not in fuente:
            continue
        resto = fuente.split(f"def {nombre}(", 1)[1]
        corte = re.search(r"\n(?=(?:def |@|[A-Za-z_]+\s*=))", resto)
        return _sin_comentarios(resto[:corte.start()] if corte else resto)
    raise AssertionError(f"no se encontro `def {nombre}` en el cuaderno")


# ------------------------------------------------------- el fallo, en su sitio exacto


def test_el_top_por_vano_le_escribe_a_su_propia_fila():
    """El rango del top va a la fila 4, que es donde esta el top.

    Iba a la 3 -- el grafo -- desde que el perfil del circuito entro como fila nueva y
    bajo al top una fila sin que esta llamada se enterara.
    """
    cuerpo = _funcion("_pintar_top_por_vano")
    destinos = re.findall(r"update_yaxes\([^)]*row=(\d+),\s*col=(\d+)", cuerpo)
    assert destinos, "_pintar_top_por_vano ya no fija el rango de su eje"
    for fila, columna in destinos:
        assert (int(fila), int(columna)) == TOP_POR_VANO, (
            f"_pintar_top_por_vano escribe en la fila {fila}, columna {columna}. "
            f"El top vive en {TOP_POR_VANO}; {GRAFO} es el grafo, y escribirle ahi le "
            "descentra el circulo y lo saca de su recuadro.")


def test_nadie_mas_que_la_figura_le_toca_el_rango_al_grafo():
    """El grafo recibe su rango UNA vez, al armar la figura, y nadie se lo reescribe.

    Su eje no mide nada: es una disposicion circular, y el rango es lo unico que reparte
    el panel entre el anillo y los nombres de sus nodos. Cualquier repintado que se lo
    cambie -- aunque sea a un rango razonable para otra cosa -- descentra el circulo,
    porque `scaleanchor` estira lo que reciba hasta cuadrar los pixeles y conserva el
    CENTRO de lo que le den.
    """
    celda_figura = next(i for i, f in enumerate(_celdas()) if "make_subplots(" in f)
    culpables = [(celda, llamada[:90]) for celda, llamada, fila, col in _llamadas_a_ejes()
                 if (fila, col) == GRAFO and celda != celda_figura]
    assert not culpables, (
        f"estas llamadas le reescriben los ejes al grafo fuera de la celda que arma la "
        f"figura: {culpables}")


def test_el_rango_del_grafo_es_simetrico():
    """Centrado en 0, que es donde esta el centro del circulo.

    Un rango asimetrico no se ve como un error: se ve como un grafo que se sale por un
    lado y deja una banda blanca por el otro.
    """
    celda = _sin_comentarios(next(f for f in _celdas() if "make_subplots(" in f))
    rangos = re.findall(
        r"update_([xy])axes\((?:[^()]|\([^()]*\))*?range=\[([^\]]+)\]"
        r"(?:[^()]|\([^()]*\))*?row=3,\s*col=3", celda, re.S)
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
    celda = _sin_comentarios(next(f for f in _celdas() if "make_subplots(" in f))
    for eje in ("x", "y"):
        llamada = re.search(
            rf"update_{eje}axes\((?:[^()]|\([^()]*\))*?row=3,\s*col=3", celda, re.S)
        assert llamada, f"el grafo no configura su eje {eje}"
        assert "constrain='domain'" in llamada.group(0), (
            f"el eje {eje} del grafo no lleva `constrain='domain'`: plotly le estirara "
            "el rango y el circulo se quedara pequenio dentro de su panel")


def test_cada_celda_de_la_rejilla_existe_en_las_especificaciones():
    """Ningun `row=`/`col=` apunta fuera de la rejilla declarada.

    Plotly no avisa: `update_yaxes(row=9, col=9)` no encuentra nada y no hace nada, y el
    panel se queda sin configurar sin que nadie lo diga.
    """
    celda = next(f for f in _celdas() if "make_subplots(" in f)
    filas = int(re.search(r"rows=(\d+)", celda).group(1))
    columnas = int(re.search(r"cols=(\d+)", celda).group(1))
    for numero, llamada, fila, col in _llamadas_a_ejes():
        assert 1 <= fila <= filas and 1 <= col <= columnas, (
            f"celda {numero}: `{llamada[:80]}` apunta fuera de la rejilla "
            f"{filas}x{columnas}")
