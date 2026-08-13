"""Construccion compartida de los dos visores de tablero (01 y 02).

Los dos cuadernos terminan igual: escriben un documento HTML autocontenido en
`reports/paneles/` y devuelven su ruta en `RUTA_PANEL`. Lo unico que cambia entre
ellos es el archivo y el titulo, asi que el procedimiento vive aqui una sola vez.

El cuaderno se ejecuta con una unica sustitucion, `ABRIR_EN_NAVEGADOR = False`: sin
ella la construccion abriria el navegador con el documento de 27,8 MB antes de
empaquetarlo, que es justo lo que estas aplicaciones existen para no hacer.
"""
from __future__ import annotations

import time
from pathlib import Path

import cuaderno as _cuaderno
import empaquetar as _empaquetar
import raiz as _raiz


def construir_tablero(nombre_cuaderno: str, destino: Path, *, titulo: str) -> None:
    _raiz.verificar_repo()
    ruta_cuaderno = _raiz.CUADERNOS_APPS / nombre_cuaderno
    if not ruta_cuaderno.exists():
        raise SystemExit(f"No existe {ruta_cuaderno}")

    csv = _raiz.datos("Indicadores_vano_v3.csv")
    if not csv.exists():
        raise SystemExit(f"Falta {csv}. Es el insumo del cuaderno; sin el no hay tablero.")
    if csv.stat().st_size < 1024 * 1024:
        raise SystemExit(
            f"{csv} pesa {csv.stat().st_size} bytes: es un puntero de Git LFS sin "
            "descargar, no los datos. Corre `git lfs pull` en la raiz del repositorio."
        )

    print(f"[1/2] ejecutando {nombre_cuaderno}")
    t0 = time.perf_counter()
    espacio = _cuaderno.ejecutar(
        ruta_cuaderno,
        sustituciones={"ABRIR_EN_NAVEGADOR = True": "ABRIR_EN_NAVEGADOR = False"},
    )
    print(f"      cuaderno completo en {time.perf_counter() - t0:.1f} s")

    fuente = Path(espacio["RUTA_PANEL"])
    if not fuente.exists():
        raise SystemExit(f"El cuaderno no dejo su tablero en {fuente}.")

    print(f"[2/2] empaquetando {fuente.name} ({fuente.stat().st_size / 1024**2:,.1f} MB)")
    paquete = _empaquetar.empaquetar(fuente.read_text("utf-8"), destino, titulo=titulo)
    print()
    print(paquete.resumen())
    print()
    print(f"  Tablero listo en {destino}")
    ahorro = 1 - paquete.total_gzip / fuente.stat().st_size
    print(f"  Primera apertura: {paquete.total_gzip / 1024**2:,.1f} MB transferidos "
          f"({ahorro:.0%} menos que el documento original).")
    inmutable = sum(p.bytes_gzip for p in paquete.piezas if p.nombre != "index.html")
    print(f"  Aperturas siguientes: {(paquete.total_gzip - inmutable) / 1024:,.0f} KB "
          "(el resto queda en el cache del navegador).")
