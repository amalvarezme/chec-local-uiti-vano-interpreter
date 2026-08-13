"""CriticidadCHEC: el menu desde el que se abren y se cierran las otras cinco.

No dibuja ningun tablero. Levanta un servidor de control en el puerto 8800 y desde ahi
lanza cada aplicacion como proceso hijo, en su propio puerto y con su propio entorno.
Toda la maquinaria vive en `_comun/menu.py`; esto solo son los argumentos.
"""
import argparse
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "_comun"))

import menu  # noqa: E402


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--no-abrir", action="store_true",
                            help="no abre el navegador; solo deja el menu escuchando")
    analizador.add_argument("--puerto", type=int, default=None)
    analizador.add_argument("--verboso", action="store_true", help="registra cada peticion")
    args = analizador.parse_args()

    return menu.servir_menu(abrir=not args.no_abrir, puerto=args.puerto,
                            verboso=args.verboso)


if __name__ == "__main__":
    raise SystemExit(main())
