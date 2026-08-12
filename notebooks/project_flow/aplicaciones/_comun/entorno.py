"""Entorno virtual propio de cada aplicacion, identico en macOS y en Windows.

Cada aplicacion instala SOLO sus dependencias en su propio `.venv`. No comparten
entorno con el repositorio ni entre ellas, y por una razon medible: el visor de
tableros (01 y 02) no necesita `torch` ni `geopandas` para SERVIR el tablero ya
construido, y el simulador (06) no necesita `scikit-learn` en tiempo de ejecucion.
Un entorno unico las obligaria a instalar la union de las tres.

Este modulo usa solo la biblioteca estandar: corre con el Python del sistema,
ANTES de que exista ningun entorno.
"""
from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

# `venv` reproduce el layout de la instalacion, y en Windows los ejecutables van a
# Scripts/ en vez de bin/. No hay forma portable de preguntarlo sin el interprete
# ya creado, asi que se decide por plataforma.
ES_WINDOWS = os.name == "nt"
SUBCARPETA_BIN = "Scripts" if ES_WINDOWS else "bin"
NOMBRE_PYTHON = "python.exe" if ES_WINDOWS else "python"

# El repositorio corre sobre 3.11. Se admite desde 3.10 porque nada de estas
# aplicaciones usa sintaxis mas nueva, y se rechaza 3.9 y anteriores explicitamente:
# `list[str]` en anotaciones evaluadas y `zoneinfo` fallan ahi de formas poco claras.
PYTHON_MINIMO = (3, 10)


def ruta_venv(app: Path) -> Path:
    return app / ".venv"


def python_del_venv(app: Path) -> Path:
    return ruta_venv(app) / SUBCARPETA_BIN / NOMBRE_PYTHON


def ejecutable_del_venv(app: Path, nombre: str) -> Path:
    """Ruta de un ejecutable instalado por pip dentro del entorno (p. ej. `voila`)."""
    sufijo = ".exe" if ES_WINDOWS else ""
    return ruta_venv(app) / SUBCARPETA_BIN / f"{nombre}{sufijo}"


def verificar_python_actual() -> None:
    if sys.version_info < PYTHON_MINIMO:
        raise SystemExit(
            f"Se necesita Python {PYTHON_MINIMO[0]}.{PYTHON_MINIMO[1]} o superior; "
            f"este es {sys.version.split()[0]} ({sys.executable}).\n"
            "En macOS: brew install python@3.11 -- en Windows: https://www.python.org/downloads/"
        )


def existe(app: Path) -> bool:
    return python_del_venv(app).exists()


def crear(app: Path, *, recrear: bool = False) -> Path:
    """Crea el entorno de la aplicacion e instala su `requirements.txt`.

    Devuelve la ruta del interprete del entorno. Es idempotente: volver a llamarla
    reinstala las dependencias sobre el entorno existente, que es lo que hace falta
    cuando `requirements.txt` cambia.
    """
    verificar_python_actual()
    destino = ruta_venv(app)

    if recrear and destino.exists():
        import shutil

        print(f"[entorno] borrando {destino}")
        shutil.rmtree(destino)

    if not python_del_venv(app).exists():
        print(f"[entorno] creando {destino} con {sys.executable}")
        # `with_pip=True` es el valor por defecto, pero se deja explicito: sin pip el
        # entorno queda inservible y el error aparece recien en el install de abajo.
        venv.EnvBuilder(with_pip=True, clear=False).create(destino)
    else:
        print(f"[entorno] reutilizando {destino}")

    py = python_del_venv(app)
    requisitos = app / "requirements.txt"
    if not requisitos.exists():
        raise SystemExit(f"Falta {requisitos}")

    # pip nuevo en el entorno antes de instalar: las ruedas de `pyarrow` y `torch`
    # dependen de etiquetas de plataforma que pip viejo no sabe leer, y el sintoma es
    # una compilacion desde fuente de veinte minutos en vez de un mensaje claro.
    _correr([str(py), "-m", "pip", "install", "--upgrade", "pip", "wheel"])
    _correr([str(py), "-m", "pip", "install", "-r", str(requisitos)])
    return py


def asegurar(app: Path) -> Path:
    """Devuelve el interprete del entorno, o explica como crearlo."""
    py = python_del_venv(app)
    if not py.exists():
        script = "instalar.bat" if ES_WINDOWS else "instalar.command"
        raise SystemExit(
            f"La aplicacion {app.name} todavia no tiene entorno.\n"
            f"Ejecuta primero {app / script} (doble clic)."
        )
    return py


def _correr(comando: list[str]) -> None:
    print("[entorno] $ " + " ".join(comando))
    resultado = subprocess.run(comando)
    if resultado.returncode != 0:
        raise SystemExit(
            f"Fallo la instalacion de dependencias (codigo {resultado.returncode}). "
            "El detalle esta en las lineas de pip de arriba."
        )
