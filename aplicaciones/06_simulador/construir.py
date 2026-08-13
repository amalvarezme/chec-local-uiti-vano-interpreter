"""Construye el simulador: congela el arranque del cuaderno 06 y prepara su copia.

Se corre una vez, o cuando cambie el cuaderno 06 o los artefactos del cuaderno 05.
`iniciar` lo invoca por su cuenta si detecta que falta el paquete o que el cuaderno
cambio desde la ultima construccion.
"""
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

from preparar import construir_paquete, preparar_copia  # noqa: E402

if __name__ == "__main__":
    manifiesto = construir_paquete()
    print("[3/3] preparando la copia del cuaderno que lee el paquete")
    copia = preparar_copia()
    print(f"      {copia.relative_to(AQUI.parents[1])}")
    print()
    print(f"  Simulador listo. {manifiesto['n_bolsas']:,} bolsas | "
          f"{manifiesto['n_instancias']:,} instancias x {manifiesto['n_features']} features.")
    print("  Arrancalo con iniciar.command (macOS) o iniciar.bat (Windows).")
