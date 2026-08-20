"""Un entorno pelado para un subproceso, sin dejarlo tan pelado que no arranque.

Dos ficheros de prueba lanzan un `python -c` con un `env=` escrito a mano en vez de
heredar el del proceso que corre las pruebas. La intencion es buena y hay que
conservarla: si un modulo necesitara una variable de entorno al importarse, un entorno
heredado se la daria sin que nadie se entere, y el dia que falte en la maquina de otro
el fallo aparece lejos de aqui.

Lo que los dos escribian era `{"PATH": "/usr/bin:/bin", "HOME": ...}`, y eso mezcla dos
cosas distintas: lo que el PROYECTO no debe necesitar, que es el punto de la prueba, y
lo que el SISTEMA necesita para que el interprete arranque siquiera, que no tiene nada
que ver con el proyecto.

En Windows esa segunda parte es `SystemRoot`. Sin ella, Winsock no consigue inicializar
su catalogo de proveedores, e `import asyncio` -- que por debajo hace `import
_overlapped` -- muere con `OSError: [WinError 10106]`. Ni una linea del proyecto llega a
ejecutarse, asi que la prueba no comprueba nada: solo informa de que Python no arranca.
Medido el 2026-08-20 sobre el mismo subproceso: sale 1 sin la variable y 0 con ella.

Y `/usr/bin:/bin` alli no nombra ningun directorio que exista, con lo que el `PATH`
tampoco decia lo que pretendia decir.
"""

from __future__ import annotations

import os
from pathlib import Path


def entorno_minimo(**extra: str) -> dict[str, str]:
    """El entorno mas pequenio en el que este Python arranca, mas lo que se le pase.

    `extra` es para lo que la prueba SI quiere dar -- un `PYTHONPATH`, por ejemplo. Todo
    lo demas del entorno de quien lanza las pruebas se queda fuera a proposito.
    """
    entorno = {"HOME": str(Path.home()), **extra}
    if os.name == "nt":
        # Las dos que pide el sistema, no el proyecto. `SystemRoot` la necesita Winsock;
        # `System32` en el PATH lo necesitan las DLL que el interprete carga al arrancar.
        entorno["SystemRoot"] = os.environ["SystemRoot"]
        entorno["PATH"] = os.path.join(os.environ["SystemRoot"], "System32")
    else:
        entorno["PATH"] = "/usr/bin:/bin"
    return entorno
