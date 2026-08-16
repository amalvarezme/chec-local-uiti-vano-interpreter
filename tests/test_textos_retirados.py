"""Textos que se retiran del menu y del simulador.

Cinco parrafos explicativos y una descripcion por tarjeta. Todos decian cosas ciertas; lo
que fallaba era el sitio. Se leen una vez, estorban siempre, y en un panel de control cada
linea de prosa empuja hacia abajo el control siguiente.

## Lo que NO se va del menu, y por que

La tarjeta de cada aplicacion tenia dos cosas bajo el nombre: la DESCRIPCION -- prosa fija,
la misma en cada apertura -- y el ESTADO, que es la unica ventana que el usuario tiene
sobre lo que pasa. `menu.py` lo dice en su encabezado: cuando algo falla, "el usuario no
esta mirando ninguna terminal: el menu es su unica ventana", y `_fallo()` escribe ahi la
ultima linea de pip o del constructor.

Asi que la descripcion se va entera, y la linea de estado se queda SOLO cuando dice algo
que el usuario no puede deducir mirando la tarjeta: un fallo, un avance, un puerto, o que
falta instalar. El "lista, abre en menos de un segundo" del caso normal desaparece, que es
justo el texto que sobraba.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
COMUN = RAIZ / "aplicaciones" / "_comun"
SIMULADOR = RAIZ / "src" / "chec_tableros" / "simulador" / "tablero.py"


def _comun(nombre: str):
    sys.path.insert(0, str(COMUN))
    try:
        return __import__(nombre)
    finally:
        sys.path.pop(0)


def _simulador() -> str:
    return SIMULADOR.read_text(encoding="utf-8")


def _solo_lo_que_ve_el_usuario(fuente: str) -> str:
    """La fuente sin comentarios NI docstrings.

    Los docstrings hay que quitarlos con `ast` y no a ojo: el de `_rehacer_rejilla`
    describe la rejilla con las mismas palabras que el texto que se retiro del panel
    ("con su costo unitario y cuantas veces se ejecutan"), y buscarlo sobre la fuente
    cruda daba un fallo por un texto que el usuario no ve. Documentar el codigo con las
    palabras del dominio es lo correcto; lo que se retira es lo que se PINTA.
    """
    import ast

    arbol = ast.parse(fuente)
    docs = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        cuerpo = getattr(nodo, "body", None)
        if cuerpo and isinstance(cuerpo[0], ast.Expr) \
                and isinstance(cuerpo[0].value, ast.Constant) \
                and isinstance(cuerpo[0].value.value, str):
            docs.update(range(cuerpo[0].lineno, (cuerpo[0].end_lineno or 0) + 1))
    return "\n".join(l for i, l in enumerate(fuente.splitlines(), start=1)
                      if i not in docs and not l.lstrip().startswith("#"))


# ------------------------------------------------------------------------- el menu


def test_la_tarjeta_no_escribe_la_descripcion_de_la_aplicacion():
    """Prosa fija bajo cada nombre, identica en cada apertura."""
    guion = _comun("menu_pagina")._GUION
    assert "app.descripcion" not in guion, (
        "la tarjeta sigue escribiendo la descripcion de la aplicacion")


def test_el_estado_solo_se_escribe_cuando_dice_algo():
    """El fallo, el avance, el puerto y el "hay que instalarla" siguen visibles.

    Es lo que impide que quitar prosa se lleve por delante la unica via por la que el
    usuario se entera de que una aplicacion no arranco.
    """
    guion = _comun("menu_pagina")._GUION
    assert "app.detalle" in guion, "el detalle del fallo ya no llega a la tarjeta"
    assert "hay que instalarla la primera vez" in guion, (
        "la tarjeta ya no avisa de que falta instalar")
    assert "lista, abre en menos de un segundo" not in guion, (
        "sigue el texto de relleno del caso normal")


def test_el_catalogo_conserva_las_descripciones():
    """No se borran de `tableros.py`: solo dejan de dibujarse.

    `/estado` las sigue mandando y otras herramientas las leen; lo que cambio es la
    tarjeta, no el catalogo.
    """
    tableros = (COMUN / "tableros.py").read_text(encoding="utf-8")
    assert "descripcion" in tableros, (
        "las descripciones desaparecieron del catalogo, no solo de la tarjeta")


# -------------------------------------------------------------------- el simulador


RETIRADOS = [
    ("la lista de vanos", "La lista trae los vanos con eventos del circuito"),
    ("la lista de vanos (cola)", "se dibujan hasta"),
    ("las no simulables", "la tabla de arriba dice por que"),
    ("las actividades", "El costo no alimenta al modelo"),
    ("las actividades (cola)", "cuantas veces se ejecuta"),
    ("la rejilla vacia", "recibe su propia columna"),
]


def test_los_parrafos_del_simulador_se_retiran():
    """Los cinco, uno por uno, para que el mensaje del fallo diga cual sigue."""
    fuente = _solo_lo_que_ve_el_usuario(_simulador())
    presentes = [nombre for nombre, aguja in RETIRADOS if aguja in fuente]
    assert not presentes, f"estos textos siguen en el panel del simulador: {presentes}"


def test_lo_que_queda_de_las_actividades_sigue_siendo_una_frase():
    """De la fila de actividades se quita la cola, no la explicacion entera.

    Lo que dice donde aparece lo que marcas -- una fila bajo cada vano, con su costo
    unitario -- es lo unico que no se descubre mirando el panel.
    """
    fuente = _simulador()
    assert "Lo que marques " in fuente, (
        "se fue tambien la frase que dice donde aparecen las actividades marcadas")
    assert "costo unitario" in fuente, (
        "la frase de las actividades ya no nombra el costo unitario")


# ------------------------------------------------ la leyenda de los mapas del simulador


def test_la_leyenda_de_los_mapas_va_encima_y_centrada():
    """Arriba y en el centro, entre los dos mapas. Estaba DEBAJO de ellos.

    Medido sobre la figura construida: los dos mapas ocupan `y = [0.766, 1.0]` en
    coordenadas de papel, y la leyenda estaba anclada por ARRIBA a `y = 0.762`, o sea
    justo por debajo de su borde inferior.

    Subirla no es cambiar el signo. En `y = 1.0` -- el borde de arriba de los mapas -- ya
    hay algo: los dos titulos de subplot ("Criticidad Original" y "Criticidad Simulada"),
    anclados por ABAJO a esa misma linea y con fuente 16. Anclar ahi la leyenda la pone
    encima de ellos. Por eso se despeja el alto de esa banda, y por eso ese despeje se
    calcula desde el alto de la figura en vez de escribirse como una fraccion a ojo: la
    banda es texto y mide lo mismo en pixeles pase lo que pase con la figura.

    `x = 0.5` no cambia y es literalmente "entre los mapas": el primero acaba en 0.4225 y
    el segundo empieza en 0.5175.
    """
    fuente = _solo_lo_que_ve_el_usuario(_simulador())
    legend = re.search(r"legend=dict\((.*?)\),\n", fuente, re.S)
    assert legend, "no se pudo leer la declaracion de la leyenda"
    cuerpo = legend.group(1)
    assert "yanchor='bottom'" in cuerpo, (
        f"la leyenda sigue anclada por arriba, o sea colgando hacia abajo: {cuerpo}")
    assert "domain.y[1]" in cuerpo, (
        f"la `y` no sale del borde SUPERIOR del dominio del mapa: {cuerpo}")
    assert "x=0.5" in cuerpo and "xanchor='center'" in cuerpo, (
        f"la leyenda dejo de estar centrada entre los mapas: {cuerpo}")
    assert "_BANDA_TITULO_MAPAS" in cuerpo, (
        "la leyenda no despeja la banda de los titulos de los mapas")
    assert re.search(r"_BANDA_TITULO_MAPAS\s*=\s*[\d.]+\s*/\s*_ALTO_FIGURA", fuente), (
        "el despeje no se calcula desde el alto de la figura; una fraccion a ojo deja de "
        "valer en cuanto la figura cambia de alto")
