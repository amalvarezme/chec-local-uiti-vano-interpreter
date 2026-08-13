"""Construye el tablero de 03_trayectorias_circuitos: ejecuta el cuaderno y empaqueta su salida.

Se corre solo, o a traves de `iniciar`, que lo invoca cuando falta el tablero.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_comun"))

from construccion import construir_tablero  # noqa: E402

CUADERNO = "03_uiti_vano_trayectorias_circuitos.ipynb"
TITULO = "Trayectoria y agrupamiento de circuitos -- CHEC"
DESTINO = Path(__file__).resolve().parent / "panel"

if __name__ == "__main__":
    construir_tablero(CUADERNO, DESTINO, titulo=TITULO)
