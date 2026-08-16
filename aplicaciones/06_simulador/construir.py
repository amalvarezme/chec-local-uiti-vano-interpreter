"""Construye el simulador: congela su arranque y escribe el cuaderno que lo sirve.

Se corre una vez, o cuando cambien los datos o los artefactos del cuaderno 05.
`iniciar` lo invoca por su cuenta si detecta que falta el paquete o que alguno de sus
insumos se movio desde la ultima construccion.
"""
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

from preparar import construir_paquete, escribir_cuaderno  # noqa: E402

if __name__ == "__main__":
    manifiesto = construir_paquete()
    print("[3/3] escribiendo el cuaderno que lee el paquete")
    copia = escribir_cuaderno()
    print(f"      {copia.relative_to(AQUI.parents[1])}")
    print()
    print(f"  Simulador listo. {manifiesto['n_bolsas']:,} bolsas | "
          f"{manifiesto['n_instancias']:,} instancias x {manifiesto['n_features']} features.")
    print("  Arrancalo con Iniciar.app (macOS) o iniciar.bat (Windows).")
