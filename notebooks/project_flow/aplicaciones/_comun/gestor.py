"""Arranque comun de las tres aplicaciones. Solo biblioteca estandar.

Este archivo corre con el Python del SISTEMA, antes de que exista ningun entorno
virtual, asi que no puede importar nada que haya que instalar. Su unico trabajo es:
crear el entorno de la aplicacion, y despues volver a lanzar los scripts de la
aplicacion CON el interprete de ese entorno.

    python3 _comun/gestor.py <accion> [--app <carpeta>] [opciones de la accion]

Acciones:
    instalar    crea el entorno virtual de la aplicacion e instala sus dependencias
    construir   genera los artefactos que la aplicacion necesita para arrancar
    iniciar     construye si falta algo y levanta la aplicacion
    estado      dice que hay y que falta, sin cambiar nada
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import entorno  # noqa: E402  -- despues de arreglar sys.path, a proposito


def _app_por_defecto() -> Path:
    """La carpeta de la aplicacion es el cwd, que es donde la deja el lanzador."""
    return Path.cwd().resolve()


def _correr_en_entorno(app: Path, script: str, argumentos: list[str]) -> int:
    py = entorno.asegurar(app)
    ruta = app / script
    if not ruta.exists():
        raise SystemExit(f"La aplicacion {app.name} no tiene {script}.")
    return subprocess.run([str(py), str(ruta), *argumentos]).returncode


def _estado(app: Path) -> None:
    py = entorno.python_del_venv(app)
    print(f"aplicacion : {app}")
    print(f"entorno    : {'listo' if py.exists() else 'FALTA -- corre instalar'} ({py})")
    marca = app / "panel" / "index.html"
    paquete = app / "paquete" / "manifiesto.json"
    if marca.exists():
        print(f"tablero    : construido ({marca.stat().st_size / 1024:,.0f} KB de armazon)")
    elif paquete.exists():
        print(f"paquete    : construido ({paquete})")
    else:
        print("artefactos : FALTAN -- corre construir")


def main(argv: list[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(prog="gestor", description=__doc__)
    analizador.add_argument("accion", choices=["instalar", "construir", "iniciar", "estado"])
    analizador.add_argument("--app", type=Path, default=None,
                            help="carpeta de la aplicacion (por defecto, el directorio actual)")
    analizador.add_argument("--recrear", action="store_true",
                            help="borra y rehace el entorno virtual (solo con instalar)")
    argumentos, sobrantes = analizador.parse_known_args(argv)
    app = (argumentos.app or _app_por_defecto()).resolve()

    if not (app / "requirements.txt").exists():
        raise SystemExit(
            f"{app} no parece una aplicacion de esta carpeta (no tiene requirements.txt).\n"
            "Ejecuta el lanzador desde dentro de 01_clima, 02_agrupamiento_vanos o 06_simulador."
        )

    if argumentos.accion == "estado":
        _estado(app)
        return 0

    if argumentos.accion == "instalar":
        entorno.crear(app, recrear=argumentos.recrear)
        print(f"\n  Entorno de {app.name} listo.")
        print(f"  Siguiente paso: iniciar{'.bat' if entorno.ES_WINDOWS else '.command'}\n")
        return 0

    if argumentos.accion == "construir":
        return _correr_en_entorno(app, "construir.py", sobrantes)

    return _correr_en_entorno(app, "app.py", sobrantes)


if __name__ == "__main__":
    raise SystemExit(main())
