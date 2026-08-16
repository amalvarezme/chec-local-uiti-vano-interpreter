"""Construye el tablero de 04_trayectorias_vanos: llama a su modulo y empaqueta su salida.

Se corre solo, o a traves de `iniciar`, que lo invoca cuando falta el tablero.

Aqui vivia la advertencia mas repetida del proyecto: la salida GUARDADA dentro del
`.ipynb` de este tablero era un insumo -- de ahi se extraia la geometria K-Means que
comparten el 05 y el simulador --, asi que nadie debia "limpiar" ese cuaderno. La regla
esta RETIRADA, con sus dos motivos: la geometria es hoy un artefacto versionado
(`data/geometria_kmeans_014_v1.json`, producido por `scripts/exportar_geometria.py`) y el
cuaderno ya no existe -- su codigo es `src/chec_tableros/trayectorias_vanos.py`.
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
