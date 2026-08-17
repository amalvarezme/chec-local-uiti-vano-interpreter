"""Local UITI_VANO interpretability toolkit."""

# Aqui se reexportaban ademas `HIGH_PERCENTILE`, `HIGH_ROBUST_Z` y
# `MAX_CRITICAL_POINTS`, de la deteccion de puntos criticos que el informe ya no hace.
# El bucle estaba cerrado: este reexport era su UNICO uso en todo el arbol, asi que un
# grep por sus nombres los encontraba y parecian vivos.
from chec_local_interpreter.config import DEFAULT_OUTPUT_DIR

__all__ = [
    "DEFAULT_OUTPUT_DIR",
]
