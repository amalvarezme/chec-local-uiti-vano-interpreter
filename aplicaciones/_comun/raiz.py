"""Localiza la raiz del repositorio desde cualquier directorio de trabajo.

Las tres aplicaciones se lanzan con doble clic, y el directorio de trabajo con el
que arrancan depende del sistema: en macOS `Terminal.app` abre el `.command` en la
carpeta del usuario, no en la del archivo. Por eso ninguna ruta de este paquete se
resuelve contra `Path.cwd()`, sino contra la ubicacion de ESTE archivo.
"""
from __future__ import annotations

from pathlib import Path

# aplicaciones/_comun/raiz.py -> aplicaciones/_comun -> aplicaciones -> raiz del
# repositorio. `verificar_repo` comprueba la cuenta, que es lo que convierte un
# `parents[N]` mal contado en un error inmediato y no en un `data/` inexistente
# quinientas lineas mas abajo.
RAIZ_REPO = Path(__file__).resolve().parents[2]

# Carpeta que contiene las aplicaciones: los cinco visores mas el menu CriticidadCHEC.
RAIZ_APPS = Path(__file__).resolve().parents[1]

# Carpeta de los cuadernos del repositorio.
CUADERNOS = RAIZ_REPO / "notebooks"

# De donde salen las cinco aplicaciones: los cuadernos 01, 02, 03, 04 y 06 son su UNICA
# fuente. La carpeta se llamaba `old_version/` hasta el 2026-08-14, y ese nombre costo
# caro -- invitaba a borrarla, cuando lo que hay dentro es justo lo que se construye. Se
# renombro a `base_apps/` para que diga lo que es. Va aparte de `CUADERNOS` para que
# mover la carpeta se arregle SOLO aqui.
CUADERNOS_APPS = CUADERNOS / "base_apps"


def verificar_repo() -> None:
    """Falla temprano si el arbol no es el que estas rutas suponen.

    Es barato y evita el modo de fallo mas confuso de estas aplicaciones: que un
    `parents[2]` mal contado deje `RAIZ_REPO` apuntando a la carpeta del usuario y
    que el error salga mucho despues, como un `data/` inexistente.
    """
    if not (RAIZ_REPO / "src" / "chec_local_interpreter").is_dir():
        raise SystemExit(
            f"No se encontro src/chec_local_interpreter bajo {RAIZ_REPO}. "
            "Esta carpeta de aplicaciones tiene que vivir dentro del repositorio, "
            "en aplicaciones/."
        )


def datos(*partes: str) -> Path:
    """Ruta dentro de `data/` del repositorio."""
    return RAIZ_REPO.joinpath("data", *partes)
