"""Construye el tablero de 02_agrupamiento_vanos: ejecuta el cuaderno y empaqueta su salida.

Se corre solo, o a traves de `iniciar`, que lo invoca cuando falta el tablero.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_comun"))

from construccion import construir_tablero  # noqa: E402

CUADERNO = "02_uiti_vano_kmeans.ipynb"
TITULO = "Agrupamiento de vanos por UITI acumulado -- CHEC"
DESTINO = Path(__file__).resolve().parent / "panel"

if __name__ == "__main__":
    construir_tablero(CUADERNO, DESTINO, titulo=TITULO)
