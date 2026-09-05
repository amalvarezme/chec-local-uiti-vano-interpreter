"""Los titulos que son PREGUNTAS se escriben como preguntas, y la simulacion dice cuanto.

Dos cosas distintas que el revisor pidio sobre el mismo informe:

1. Tres encabezados del informe de circuito plantean una pregunta y estaban escritos como
   enunciado: "Cómo leer el mapa", "Cómo se construyen las ventanas", "Cómo se construyó
   este informe". En castellano una pregunta lleva sus dos signos, y el de apertura no es
   opcional -- es lo que avisa al lector, antes de empezar la frase, de que lo que sigue
   es una pregunta.

2. La tabla del escenario de disminucion traia el UITI base y el simulado, y dejaba al
   lector restar y dividir 15 veces para saber cuanto baja cada vano. El porcentaje es la
   cifra con la que se compara un vano contra otro, y es la unica que no depende de la
   escala del vano.
"""

from __future__ import annotations

import re

import pytest


def _fuente(modulo: str) -> str:
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[1]
    return (raiz / "src" / "chec_local_interpreter" / modulo).read_text(encoding="utf-8")


@pytest.mark.parametrize("modulo, pregunta", [
    ("plotting.py", "¿Cómo leer el mapa?"),
    ("plotting.py", "¿Cómo se construyen las ventanas"),
    ("agentes_linea_tiempo.py", "¿Cómo se construyó este informe?"),
])
def test_los_encabezados_que_preguntan_llevan_sus_dos_signos(modulo, pregunta):
    fuente = _fuente(modulo)
    assert pregunta in fuente, f"{modulo} no escribe «{pregunta}»"


@pytest.mark.parametrize("modulo, enunciado", [
    ("plotting.py", ">Cómo leer el mapa<"),
    ("agentes_linea_tiempo.py", ">🤖 Cómo se construyó este informe<"),
])
def test_no_queda_la_forma_enunciativa(modulo, enunciado):
    """Si sobrevive la version sin signos, el informe muestra las dos."""
    assert enunciado not in _fuente(modulo)


# ------------------------------------------------- el porcentaje del escenario


def test_el_escenario_declara_la_columna_de_porcentaje():
    fuente = _fuente("plotting.py")
    assert "Cambio de UITI" in fuente, (
        "la tabla del escenario no declara la columna del cambio porcentual")


def test_el_porcentaje_se_calcula_contra_la_base_de_cada_vano():
    """Contra SU base, no contra el total de la ventana.

    La pregunta que responde es "cuanto baja este vano", y un vano de UITI 900 y otro de
    9 pueden bajar el mismo porcentaje con magnitudes que no se parecen en nada. Dividir
    por el total de la ventana contestaria otra cosa -- cuanto pesa el vano -- que la
    columna de UITI base ya da.
    """
    fuente = _fuente("plotting.py")
    assert re.search(r"\(s\s*-\s*b\)\s*/\s*b\s*\*\s*100", fuente), (
        "no se ve el cambio relativo a la base del propio vano")
    assert "_cambio_pct_uiti(base, simulado)" in fuente, (
        "la fila no llama al helper con la base y el simulado de ESE vano")


def test_una_base_en_cero_no_divide_por_cero():
    """Un vano con base 0 es posible cuando el modelo no lo puntua. Sin guarda la celda
    sale `inf` o `nan` y la tabla entera se lee como rota."""
    from chec_local_interpreter.plotting import _cambio_pct_uiti

    assert _cambio_pct_uiti(0.0, 5.0) is None
    assert _cambio_pct_uiti(None, 5.0) is None


def test_el_signo_distingue_bajar_de_subir():
    """La simulacion no siempre baja: hay que poder leer un aumento como aumento."""
    from chec_local_interpreter.plotting import _cambio_pct_uiti

    assert _cambio_pct_uiti(100.0, 75.0) == pytest.approx(-25.0)
    assert _cambio_pct_uiti(100.0, 130.0) == pytest.approx(30.0)
    assert _cambio_pct_uiti(100.0, 100.0) == pytest.approx(0.0)
