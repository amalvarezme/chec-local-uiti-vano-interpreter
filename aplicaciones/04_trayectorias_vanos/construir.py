"""Construye el tablero de 04_trayectorias_vanos: ejecuta el cuaderno y empaqueta su salida.

Se corre solo, o a traves de `iniciar`, que lo invoca cuando falta el tablero.

Este cuaderno tiene una particularidad que conviene no descubrir por las malas: su
salida GUARDADA en el .ipynb es un insumo de `scripts/extract_geometrias_014.py`, que
lee de ahi la geometria K-Means que comparten los cuadernos 05 y 06. Construir no la
toca -- `cuaderno.ejecutar` lee el documento y ejecuta las fuentes con `exec`, sin
escribir nunca de vuelta --, pero por eso mismo nadie debe "limpiar" ese cuaderno.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_comun"))

from construccion import construir_tablero  # noqa: E402

# El tablero: su codigo vive en `src/chec_tableros/`, no en un cuaderno. Hasta el
# 2026-08-15 aqui iba el nombre de un `.ipynb` que `_comun/construccion.py` leia y
# ejecutaba con `exec()`.
TABLERO = "chec_tableros.trayectorias_vanos"
TITULO = "Agrupamiento y evolucion por vano -- CHEC"
DESTINO = Path(__file__).resolve().parent / "panel"

if __name__ == "__main__":
    construir_tablero(TABLERO, DESTINO, titulo=TITULO)
