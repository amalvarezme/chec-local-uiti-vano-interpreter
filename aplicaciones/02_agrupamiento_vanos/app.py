"""Levanta el tablero de 02_agrupamiento_vanos en el navegador, desde el servidor local.

Si el tablero todavia no esta construido, lo construye antes. Construir cuesta
minutos y se hace una vez; arrancar cuesta menos de un segundo porque no vuelve a
leer el CSV ni a ajustar nada -- el tablero ya es un documento estatico.
"""
import argparse
import runpy
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "_comun"))

import servidor  # noqa: E402

PANEL = AQUI / "panel"


# El puerto que le da `.claude/commands/_contrato-apps-locales.md`. Solo se usa
# cuando nadie pasa `--puerto`, o sea en el doble clic: los comandos y
# CriticidadCHEC lo pasan siempre. Que cada tablero pida EL SUYO es lo que evita
# que dos abiertos a la vez se peleen por un 8765 comun y el segundo acabe en un
# puerto al azar, donde el menu ya no lo reconoce.
PUERTO = 8802


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--no-abrir", action="store_true",
                            help="no abre el navegador; solo deja el servidor escuchando")
    analizador.add_argument("--puerto", type=int, default=None)
    analizador.add_argument("--reconstruir", action="store_true",
                            help="vuelve a ejecutar el cuaderno aunque el tablero ya exista")
    analizador.add_argument("--verboso", action="store_true", help="registra cada peticion")
    # La pasa CriticidadCHEC cuando es el quien lanza este tablero. Sin ella el
    # tablero se sirve igual, con su boton de cerrar suelto: la barra del menu solo
    # tiene sentido si hay un menu al que volver.
    analizador.add_argument("--menu", default=None,
                            help="URL de CriticidadCHEC, si fue el quien lanzo este tablero")
    args = analizador.parse_args()

    if args.reconstruir or not (PANEL / "index.html").exists():
        print("El tablero no esta construido todavia." if not args.reconstruir else
              "Reconstruyendo el tablero.")
        runpy.run_path(str(AQUI / "construir.py"), run_name="__main__")

    servidor.servir(PANEL, abrir=not args.no_abrir, puerto=args.puerto,
                    preferido=PUERTO,
                    verboso=args.verboso, menu=args.menu)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
