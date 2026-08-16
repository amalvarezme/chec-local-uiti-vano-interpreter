"""Que carpetas de `aplicaciones/` son aplicaciones LOCALES de escritorio.

Cuatro ficheros de prueba enumeraban ese directorio por su cuenta, con el mismo
criterio escrito cuatro veces: "todo lo que no empiece por `.` o `_`". Decia lo
correcto mientras alli dentro solo hubiera aplicaciones locales.

Dejo de ser cierto el 2026-08-16, cuando entro `aplicaciones/databricks/`: una
aplicacion que **no corre en esta maquina** -- no tiene entorno, ni lanzadores, ni
puerto, porque sus dependencias las instala Databricks y su proceso vive en el
contenedor de una app. Los cuatro ficheros la reclamaron como propia a la vez y le
exigieron un `Iniciar.app` que nunca va a tener.

El criterio bueno ya existia y estaba sin escribir: **una aplicacion local empieza por
un numero**. No es decoracion. `_contrato-apps-locales.md` reparte un puerto fijo por
numero y `menu.py` las gobierna en ese orden.

Vive aqui, una sola vez, por lo mismo que `ayudas_tableros.py`: cuatro copias de un
criterio son cuatro sitios donde actualizarlo, y el que se olvida es el que se entera
tarde.
"""
from __future__ import annotations

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
APLICACIONES = RAIZ / "aplicaciones"

# El menu. Es de otra especie -- no dibuja ningun tablero, gobierna a las demas --, y
# separarlo es lo que permite que las pruebas de los visores sigan siendo exigentes en
# vez de aflojarse hasta que el menu tambien pase.
MENU = "00_criticidad_chec"


def locales() -> list[Path]:
    """Las aplicaciones de escritorio, en orden. Incluye el menu."""
    return sorted(d for d in APLICACIONES.iterdir()
                  if d.is_dir() and d.name[:1].isdigit())


def visores() -> list[Path]:
    """Las que abren un tablero: todas menos el menu."""
    return [a for a in locales() if a.name != MENU]
