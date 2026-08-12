"""Ejecuta las celdas de un cuaderno y devuelve su espacio de nombres.

## Por que no `nbclient` ni `jupyter nbconvert --execute`

Porque no hace falta un kernel. Los cuadernos 01 y 02 no usan magias de IPython ni
`get_ipython()`: son Python corriente que termina construyendo una cadena con el
tablero. Ejecutarlos con `exec` evita meter `jupyter`, `nbclient`, `nbformat`,
`pyzmq`, `tornado` y `traitlets` en el entorno de una aplicacion que solo tiene que
construir un HTML y servirlo.

## Por que se ejecuta el cuaderno y no una copia del codigo

Porque una copia se desincroniza. Si el cuaderno cambia de paleta, de umbrales o de
agregacion, la aplicacion tiene que cambiar con el sin que nadie se acuerde de
copiarlo. El cuaderno es la fuente de verdad; esto solo lo corre.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import time
from pathlib import Path


def ejecutar(
    cuaderno: Path,
    *,
    sustituciones: dict[str, str] | None = None,
    celdas: range | None = None,
    silencioso: bool = True,
) -> dict:
    """Ejecuta las celdas de codigo de `cuaderno` y devuelve el espacio de nombres.

    `sustituciones` reemplaza texto en el codigo ANTES de ejecutarlo, y exige que
    cada patron aparezca exactamente una vez en todo el cuaderno. Es deliberado: una
    sustitucion que no encuentra su patron -- porque el cuaderno cambio -- tiene que
    fallar aqui y no producir en silencio un tablero que abre un navegador en un
    servidor sin pantalla.
    """
    cuaderno = Path(cuaderno)
    documento = json.loads(cuaderno.read_text("utf-8"))
    fuentes = [
        (i, "".join(c["source"]))
        for i, c in enumerate(documento["cells"])
        if c["cell_type"] == "code"
    ]
    if celdas is not None:
        fuentes = [(i, s) for i, s in fuentes if i in celdas]

    for viejo, nuevo in (sustituciones or {}).items():
        apariciones = sum(s.count(viejo) for _, s in fuentes)
        if apariciones != 1:
            raise SystemExit(
                f"La sustitucion {viejo!r} aparece {apariciones} veces en "
                f"{cuaderno.name}; se esperaba exactamente 1. El cuaderno cambio y "
                "esta aplicacion tiene que actualizarse antes de volver a construir."
            )
        fuentes = [(i, s.replace(viejo, nuevo, 1)) for i, s in fuentes]

    # El cuaderno resuelve la raiz del repositorio subiendo desde el directorio de
    # trabajo, asi que hay que pararse donde el vive.
    cwd_previo = Path.cwd()
    os.chdir(cuaderno.parent)
    espacio: dict = {"__name__": "__main__", "__file__": str(cuaderno)}
    try:
        for indice, fuente in fuentes:
            t0 = time.perf_counter()
            salida = io.StringIO()
            try:
                if silencioso:
                    with contextlib.redirect_stdout(salida):
                        exec(compile(fuente, f"{cuaderno.name}:celda{indice}", "exec"), espacio)
                else:
                    exec(compile(fuente, f"{cuaderno.name}:celda{indice}", "exec"), espacio)
            except Exception:
                # La salida de la celda que fallo es la unica pista util, y sin esto se
                # pierde entera dentro del redirect.
                texto = salida.getvalue().strip()
                if texto:
                    print(f"--- salida de la celda {indice} antes del fallo ---\n{texto}")
                raise
            print(f"  celda {indice:>2}  {time.perf_counter() - t0:>6.1f} s")
    finally:
        os.chdir(cwd_previo)
    return espacio
