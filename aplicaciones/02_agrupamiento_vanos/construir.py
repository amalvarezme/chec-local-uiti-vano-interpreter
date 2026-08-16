"""Construye el tablero de 02_agrupamiento_vanos: ejecuta el cuaderno y empaqueta su salida.

Se corre solo, o a traves de `iniciar`, que lo invoca cuando falta el tablero.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_comun"))

from construccion import construir_tablero  # noqa: E402

# El tablero: su codigo vive en `src/chec_tableros/`, no en un cuaderno. Hasta el
# 2026-08-15 aqui iba el nombre de un `.ipynb` que `_comun/construccion.py` leia y
# ejecutaba con `exec()`.
TABLERO = "chec_tableros.agrupamiento"
TITULO = "Agrupamiento de vanos por UITI acumulado -- CHEC"
DESTINO = Path(__file__).resolve().parent / "panel"

if __name__ == "__main__":
    construir_tablero(TABLERO, DESTINO, titulo=TITULO)
