"""Interpretability exports, resueltas cuando se piden y no cuando se importa el paquete.

Mismo defecto que en `chec_impacto.models`, un paquete mas alla. `mgcecdl_graph` y
`circuit_analysis` arrastran torch, y traerlos aqui de entrada hacia que TOCAR
cualquier submodulo lo pagara. El caso que duele es `circuit_analysis`, del que el
CLI del rol `inference` solo saca `construir_prompt_inferencia` -- que ese mismo
archivo describe como "pure prompt-rendering only": renderizar un prompt y validar un
JSON no necesitan el modelo, y las dos llamadas del rol pagaban 1,47 s por el.

El aplazamiento NO cambia la API: `from chec_impacto.interpretability import
grafo_reconstruido_por_grupo` sigue funcionando y trae su submodulo en ese momento.
Un nombre que no existe sigue dando `AttributeError`.

Contrato fijado en `tests/test_costo_de_arranque.py`.
"""

from __future__ import annotations

from typing import Any

#: Nombre exportado -> submodulo del que sale. La MISMA informacion que tenian los
#: `from .x import (...)` de antes, en la forma que permite resolverla tarde.
_ORIGEN: dict[str, str] = {
    "build_classification_expected_class_outputs": "mgcecdl",
    "build_classification_modality_outputs_per_sample": "mgcecdl",
    "plot_classification_modality_expected_classes": "mgcecdl",
    "plot_classification_modality_radar": "mgcecdl",
    "summarize_classification_modality_support": "mgcecdl",
    "summarize_modality_reliability_by_class": "mgcecdl",
    "agregar_borda": "borda",
    "construir_modos_interpretabilidad": "circuit_analysis",
    "radar_atribucion_degradado": "circuit_analysis",
    "radar_atribucion_degradado_modelos": "circuit_analysis",
    "afinidad_entre_grafos": "mgcecdl_graph",
    "agrupar_gates_por_vano": "mgcecdl_graph",
    "anidamiento_entre_particiones": "mgcecdl_graph",
    "asignar_nombres_de_riesgo": "mgcecdl_graph",
    "asociacion_criticidad": "mgcecdl_graph",
    "corregir_benjamini_hochberg": "mgcecdl_graph",
    "assert_fecha_excluded_from_features": "mgcecdl_graph",
    "control_permutacion_grados": "mgcecdl_graph",
    "diagnostico_persistencia": "mgcecdl_graph",
    "ejecutar_control_permutacion_grados": "mgcecdl_graph",
    "estabilidad_por_submuestreo": "mgcecdl_graph",
    "estadistico_colapso": "mgcecdl_graph",
    "grafo_reconstruido_por_grupo": "mgcecdl_graph",
    "guardia_proxy_univariante": "mgcecdl_graph",
    "linea_base_sin_grafo": "mgcecdl_graph",
    "perfil_por_cluster": "mgcecdl_graph",
    "separabilidad_fuera_de_pliegue": "mgcecdl_graph",
    "seleccionar_k_datos": "mgcecdl_graph",
    "split_cronologico_p70": "mgcecdl_graph",
    "tabla_desviacion_aristas": "mgcecdl_graph",
    "tabla_grado_features": "mgcecdl_graph",
    "uiti_futuro_por_vano": "mgcecdl_graph",
    "verificar_orden_de_riesgo": "mgcecdl_graph",
}

__all__ = list(_ORIGEN)


def __getattr__(nombre: str) -> Any:
    """PEP 562: importa el submodulo la primera vez que se pide uno de sus nombres."""
    origen = _ORIGEN.get(nombre)
    if origen is None:
        raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")

    from importlib import import_module

    valor = getattr(import_module(f"{__name__}.{origen}"), nombre)
    globals()[nombre] = valor
    return valor


def __dir__() -> list[str]:
    return sorted({*globals(), *_ORIGEN})
