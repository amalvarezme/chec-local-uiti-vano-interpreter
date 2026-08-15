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

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CUADERNO = RAIZ / "notebooks" / "base_apps" / "06_uiti_vano_explicabilidad_simulador.ipynb"
PREPARAR = RAIZ / "aplicaciones" / "06_simulador" / "preparar.py"


def _celdas() -> list[str]:
    cuaderno = json.loads(CUADERNO.read_text(encoding="utf-8"))
    return ["".join(c["source"]) for c in cuaderno["cells"] if c["cell_type"] == "code"]


def _celda_del_tablero() -> str:
    """La celda que arma `APP`, que es donde se decide la disposicion."""
    return next(f for f in _celdas() if "APP = widgets.VBox(" in f)


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


def test_los_parches_de_la_aplicacion_local_encuentran_todas_sus_anclas(tmp_path,
                                                                       monkeypatch):
    """`preparar.py` parchea el cuaderno por texto literal, y una de sus anclas es la
    linea del `APP`.

    Esto no es una prueba de estilo: mover esa linea aborta la construccion de la
    aplicacion local con `SystemExit`, y el aviso llega al construir -- despues de
    preparar el paquete entero. Aqui llega en un segundo.
    """
    especificacion = importlib.util.spec_from_file_location("preparar_06", PREPARAR)
    preparar = importlib.util.module_from_spec(especificacion)
    sys.modules["preparar_06"] = especificacion.name and preparar
    especificacion.loader.exec_module(preparar)

    # La copia se escribe donde no moleste: lo que se prueba es que los parches
    # encuentren su sitio, no donde acaba el archivo.
    monkeypatch.setattr(preparar, "COPIA", tmp_path / "06_simulador.ipynb")
    (tmp_path / "06_simulador.ipynb").parent.mkdir(parents=True, exist_ok=True)

    try:
        copia = preparar.preparar_copia()
    except SystemExit as fallo:
        pytest.fail(f"preparar.py ya no encuentra una de sus anclas en el cuaderno:\n"
                    f"{fallo}")
    assert copia.exists()
    documento = json.loads(copia.read_text(encoding="utf-8"))
    fuentes = "".join("".join(c["source"]) for c in documento["cells"])
    assert "_BARRA_CERRAR" in fuentes, "la copia se quedo sin boton de cerrar"
    assert "_display_real(APP)" in fuentes, "la copia no muestra el tablero"
