"""Las cuatro rutas que publica la app consolidada.

Es una VISTA de `aplicaciones/_comun/tableros.py`, no una segunda lista: de alli salen
la clave, el titulo y la descripcion, y aqui se les agrega lo unico que este consumidor
necesita y los demas no -- la ruta publica.

## Por que se copia el modulo y no se importa

Esta carpeta se sube entera al Workspace de Databricks y corre ahi, donde
`aplicaciones/_comun/` no existe. `/app-criticidad-chec` copia `tableros.py` al lado de
estos archivos antes de subirlos, asi que el import de abajo resuelve en los dos sitios:
en el repositorio, porque el comando deja la copia; y en la app, porque viajo con ella.

La alternativa era escribir los cuatro titulos aqui otra vez. Ya se probo con el menu
local, y el resultado fue que el mismo tablero tenia dos nombres segun por donde
entrara el usuario.
"""
from __future__ import annotations

from dataclasses import dataclass

import tableros as _tableros


@dataclass(frozen=True)
class Ruta:
    clave: str
    ruta: str
    titulo: str
    descripcion: str


# La clave usa `_` porque nombra carpetas y variables; la ruta usa `-` porque es lo que
# se escribe en una barra de direcciones. Traducir en un solo sitio es mas barato que
# renombrar las carpetas del repositorio para que coincidan con una URL.
def _ruta_de(clave: str) -> str:
    return "/" + clave.replace("_", "-")


RUTAS: tuple[Ruta, ...] = tuple(
    Ruta(t.clave, _ruta_de(t.clave), t.titulo, t.descripcion)
    for t in _tableros.ESTATICOS
)
