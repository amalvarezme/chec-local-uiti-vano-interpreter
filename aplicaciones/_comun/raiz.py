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

# El paquete instalable del repositorio. Ninguna aplicacion lo tenia en su `sys.path`
# hasta que las notebooks 01-04 importaban cero modulos del proyecto -- `construccion.py`
# es quien lo agrega, una sola vez, para que cualquier codigo que las aplicaciones
# importen desde aqui en adelante (`chec_local_interpreter`, `chec_impacto`) resuelva.
RAIZ_SRC = RAIZ_REPO / "src"

# Aqui vivia `CUADERNOS_APPS = CUADERNOS / "base_apps"`, la carpeta de la que salian las
# cinco aplicaciones. Ya no existe: su codigo esta en `src/chec_tableros/` y las
# aplicaciones lo importan. Se retira la constante entera y no se deja apuntando a una
# carpeta vacia, porque una ruta que ya nadie resuelve es la que reaparece en el proximo
# `Path` sin que nadie compruebe que existe.
#
# La carpeta se llamo `old_version/` hasta el 2026-08-14, y ese nombre costo caro:
# invitaba a borrarla cuando lo que tenia dentro era justo lo que se construia. Se
# renombro a `base_apps/` para que dijera lo que era, y se vacio dos dias despues por el
# camino correcto -- migrando lo de dentro primero.


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
