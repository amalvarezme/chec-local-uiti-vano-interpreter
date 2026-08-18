"""Model exports, resueltas cuando se piden y no cuando se importa el paquete.

Los tres submodulos que exportan estos nombres -- `mgcecdl`, `mgcecdl_graph` y
`mgcecdl_graph_search` -- arrastran torch. Importarlos aqui de entrada hacia que
TOCAR cualquier submodulo del paquete pagara ese arranque, aunque no necesitara nada
de eso. El caso que duele es `criticality_assignment`, cuyo propio docstring dice por
que importa torch perezosamente: "this module is imported by notebook and reporting
code paths that have no reason to pay for torch". Esa intencion la anulaba este
archivo, un nivel mas arriba, en silencio.

Medido en esta maquina:

    import chec_impacto.models.criticality_assignment    1,49 s    2.585 modulos
    lo mismo, sin el arrastre de este `__init__`         0,03 s      199 modulos

Lo paga cada una de las ~diez llamadas al CLI de una corrida de `/report` -- seis de
ellas solo escriben un JSON de pocos bytes --, y ademas cada arranque de un tablero y
de un cuaderno que solo quiere asignar clases de criticidad.

El aplazamiento NO cambia la API: `from chec_impacto.models import MGCECDLRegressor`
sigue funcionando, y el submodulo se importa en ese momento. Un nombre que no existe
sigue dando `AttributeError` -- un `__getattr__` que devuelve algo para cualquier
nombre convierte un error de tecleo en un fallo mucho mas adentro.

Contrato fijado en `tests/test_costo_de_arranque.py`.
"""

from __future__ import annotations

from typing import Any

#: Nombre exportado -> submodulo del que sale. Es la MISMA informacion que tenian los
#: `from .x import (...)` de antes, en la forma que permite resolverla tarde.
_ORIGEN: dict[str, str] = {
    "KernelDensityWeightedMSELoss": "mgcecdl",
    "MGCECDLRegressionLoss": "mgcecdl",
    "MGCECDLRegressor": "mgcecdl",
    "GatedSelfSupervisedLoss": "mgcecdl_graph",
    "GraphEdgeIndex": "mgcecdl_graph",
    "GraphGatedMGCECDLRegressor": "mgcecdl_graph",
    "PerSampleEdgeGateDecoder": "mgcecdl_graph",
    "cargar_modelo_gated": "mgcecdl_graph",
    "construir_edge_index": "mgcecdl_graph",
    "entrenar_gated_autoencoder": "mgcecdl_graph",
    "guardar_modelo_gated": "mgcecdl_graph",
    "reinyectar_target_como_feature": "mgcecdl_graph",
    "LAMBDA_DEV_CHOICES": "mgcecdl_graph_search",
    "LAMBDA_MI_CHOICES": "mgcecdl_graph_search",
    "OPTIMIZER_CHOICES": "mgcecdl_graph_search",
    "construir_objetivo_gated": "mgcecdl_graph_search",
    "mean_pairwise_ari": "mgcecdl_graph_search",
    "resumen_barrido_lambda_dev": "mgcecdl_graph_search",
    "resumen_barrido_lambda_mi": "mgcecdl_graph_search",
}

__all__ = list(_ORIGEN)


def __getattr__(nombre: str) -> Any:
    """PEP 562: importa el submodulo la primera vez que se pide uno de sus nombres."""
    origen = _ORIGEN.get(nombre)
    if origen is None:
        raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")

    from importlib import import_module

    valor = getattr(import_module(f"{__name__}.{origen}"), nombre)
    # Se cachea en el modulo: la segunda vez ni siquiera pasa por aqui.
    globals()[nombre] = valor
    return valor


def __dir__() -> list[str]:
    """`dir()` y el autocompletado siguen viendo lo mismo que antes."""
    return sorted({*globals(), *_ORIGEN})
