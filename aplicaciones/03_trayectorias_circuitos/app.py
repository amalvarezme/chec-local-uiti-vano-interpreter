"""Levanta el tablero de 03_trayectorias_circuitos en el navegador, desde el servidor local.

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
sys.path.insert(0, str(AQUI))

import construccion  # noqa: E402
# `construir` ya no se importa. Estuvo aqui por su `TABLERO`, que hacia falta para
# preguntar si el tablero seguia al dia; desde que los cuatro visores comparten la
# misma lista de insumos -- todo `src/` como un arbol --, esa pregunta no depende de
# cual sea. Se construye con `runpy`, mas abajo y solo cuando hace falta.
import servidor  # noqa: E402

PANEL = AQUI / "panel"


# El puerto que le da `.claude/commands/app-local-criticidadCHEC.md`. Solo se usa
# cuando nadie pasa `--puerto`, o sea en el doble clic: los comandos y
# CriticidadCHEC lo pasan siempre. Que cada tablero pida EL SUYO es lo que evita
# que dos abiertos a la vez se peleen por un 8765 comun y el segundo acabe en un
# puerto al azar, donde el menu ya no lo reconoce.
PUERTO = 8803


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

    # Se pregunta por los INSUMOS, no solo por si existe el archivo. Un tablero
    # construido con datos que ya cambiaron se ve perfectamente bien y dibuja cifras que
    # ya no corresponden; que la aplicacion lo note sola es la unica defensa, porque
    # nada mas en el sistema va a avisar. Cuesta unos milisegundos.
    motivo = None if args.reconstruir else construccion.motivo_de_reconstruccion(PANEL)
    if args.reconstruir or motivo:
        print(f"Reconstruyendo el tablero: {motivo}." if motivo
              else "Reconstruyendo el tablero.")
        runpy.run_path(str(AQUI / "construir.py"), run_name="__main__")

    # `app=AQUI` es lo que deja que el servidor reconozca una segunda apertura como
    # PROPIA: deja su pid en esta carpeta y, si el puerto ya lo tiene esta misma
    # aplicacion, abre la que esta corriendo en vez de servir otra copia en un puerto al
    # azar -- que es donde iba a parar el segundo doble clic, invisible para el menu.
    return servidor.servir(PANEL, app=AQUI, abrir=not args.no_abrir, puerto=args.puerto,
                           preferido=PUERTO,
                           verboso=args.verboso, menu=args.menu)


if __name__ == "__main__":
    raise SystemExit(main())
