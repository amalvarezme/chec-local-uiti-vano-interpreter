"""El piso de Python que declara la guarda tiene que ser el que aguantan las ruedas.

`entorno.verificar_python_actual()` existe para que quien abra una aplicacion con un
Python demasiado viejo lea una frase que dice que instalar, en vez de una traza. Con el
piso mal puesto hace exactamente lo contrario: **deja pasar** y el fallo llega despues,
como un error del resolutor de pip en mitad de una instalacion.

Y ese era el estado. La guarda admitia 3.10 mientras `requirements.txt` de la raiz y
`docs/REQUISITOS-MINIMOS.md` ya decian 3.11, con el motivo escrito. Consultado a PyPI el
2026-08-19, la version mas VIEJA que satisface cada linea pinchada:

| linea                | version mas vieja que la cumple | `requires_python` |
|----------------------|--------------------------------|-------------------|
| `numpy>=2.4`         | 2.4.2                          | `>=3.11`          |
| `pandas>=3.0`        | 3.0.0                          | `>=3.11`          |
| `scikit-learn>=1.9`  | 1.9.0                          | `>=3.11`          |

No hay ninguna rueda de esas tres por debajo de 3.11, asi que en una maquina con 3.10
--- una Windows corporativa cualquiera --- la guarda decia que si y pip decia
`Could not find a version that satisfies the requirement numpy>=2.4`.

Esta prueba no consulta PyPI: pinchar la red en la suite la haria lenta y fragil. Fija
la tabla de arriba, que es la evidencia, y comprueba que la guarda no quede por debajo.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
COMUN = RAIZ / "aplicaciones" / "_comun"
if str(COMUN) not in sys.path:
    sys.path.insert(0, str(COMUN))

import entorno  # noqa: E402

# Medido contra PyPI el 2026-08-19. La clave es la LINEA del requirements, el valor es
# el piso que publica la version mas vieja que la satisface.
PISOS_MEDIDOS = {
    "numpy>=2.4": (3, 11),
    "pandas>=3.0": (3, 11),
    "scikit-learn>=1.9": (3, 11),
}

APPS = sorted(p for p in (RAIZ / "aplicaciones").glob("0*") if p.is_dir())


def test_la_guarda_no_admite_un_python_sin_ruedas():
    """El piso de la guarda, contra el mas alto de los medidos."""
    exigido = max(PISOS_MEDIDOS.values())
    assert entorno.PYTHON_MINIMO >= exigido, (
        f"la guarda admite {entorno.PYTHON_MINIMO} y las ruedas empiezan en {exigido}: "
        f"deja pasar una maquina donde pip va a fallar. Motivo: {PISOS_MEDIDOS}")


@pytest.mark.parametrize("app", APPS, ids=lambda p: p.name)
def test_ninguna_aplicacion_pide_una_linea_sin_piso_medido(app: Path):
    """Si alguien sube un pin por encima de lo medido, esta prueba lo dice.

    Cubre el otro sentido del mismo error: la tabla de arriba se queda vieja en cuanto
    `requirements.txt` sube un limite, y una tabla vieja vuelve a autorizar un Python
    que ya no sirve.
    """
    requisitos = (app / "requirements.txt").read_text(encoding="utf-8")
    lineas = {l.split("#")[0].strip() for l in requisitos.splitlines()}
    for linea in lineas:
        if not linea:
            continue
        paquete = re.split(r"[<>=]", linea)[0].strip()
        if paquete not in {p.split(">=")[0] for p in PISOS_MEDIDOS}:
            continue
        assert linea in PISOS_MEDIDOS, (
            f"{app.name} pide {linea!r} y el piso de esa linea no esta medido en "
            "PISOS_MEDIDOS; sin medirlo, la guarda de Python puede estar autorizando "
            "una maquina donde no hay ruedas")


def test_el_mensaje_de_la_guarda_dice_el_piso_de_verdad():
    """Quien lo lea tiene que salir sabiendo que instalar."""
    fuente = (COMUN / "entorno.py").read_text(encoding="utf-8")
    inicio = fuente.index("def verificar_python_actual")
    mensaje = fuente[inicio : inicio + 700]
    assert "PYTHON_MINIMO[0]" in mensaje and "PYTHON_MINIMO[1]" in mensaje, (
        "el mensaje escribe el numero a mano y puede desincronizarse de la guarda")


def test_la_documentacion_de_las_aplicaciones_dice_el_mismo_piso():
    """`aplicaciones/README.md` es lo que lee quien va a instalar. Decia 3.10."""
    texto = (RAIZ / "aplicaciones" / "README.md").read_text(encoding="utf-8")
    piso = f"Python {entorno.PYTHON_MINIMO[0]}.{entorno.PYTHON_MINIMO[1]} o superior"
    assert piso in texto, f"el README de aplicaciones no dice {piso!r}"
