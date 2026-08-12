"""Localiza la raiz del repositorio desde cualquier directorio de trabajo.

Las tres aplicaciones se lanzan con doble clic, y el directorio de trabajo con el
que arrancan depende del sistema: en macOS `Terminal.app` abre el `.command` en la
carpeta del usuario, no en la del archivo. Por eso ninguna ruta de este paquete se
resuelve contra `Path.cwd()`, sino contra la ubicacion de ESTE archivo.
"""
from __future__ import annotations

from pathlib import Path

# aplicaciones/_comun/raiz.py -> aplicaciones/_comun -> aplicaciones -> project_flow
# -> notebooks -> raiz del repositorio.
RAIZ_REPO = Path(__file__).resolve().parents[4]

# Carpeta que contiene las tres aplicaciones.
RAIZ_APPS = Path(__file__).resolve().parents[1]

# Carpeta de los cuadernos que alimentan las aplicaciones.
CUADERNOS = RAIZ_REPO / "notebooks" / "project_flow"


def verificar_repo() -> None:
    """Falla temprano si el arbol no es el que estas rutas suponen.

    Es barato y evita el modo de fallo mas confuso de estas aplicaciones: que un
    `parents[4]` mal contado deje `RAIZ_REPO` apuntando a la carpeta del usuario y
    que el error salga mucho despues, como un `data/` inexistente.
    """
    if not (RAIZ_REPO / "src" / "chec_local_interpreter").is_dir():
        raise SystemExit(
            f"No se encontro src/chec_local_interpreter bajo {RAIZ_REPO}. "
            "Esta carpeta de aplicaciones tiene que vivir dentro del repositorio, "
            "en notebooks/project_flow/aplicaciones/."
        )


def datos(*partes: str) -> Path:
    """Ruta dentro de `data/` del repositorio."""
    return RAIZ_REPO.joinpath("data", *partes)
