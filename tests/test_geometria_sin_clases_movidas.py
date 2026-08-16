"""Ninguna clase de criticidad se movio al promover la geometria KMeans.

## Por que existe, y por que sobre el dataset COMPLETO

Al sacar la geometria del HTML guardado del cuaderno 04 y congelarla como
artefacto versionado, la pregunta que decide si el cambio fue correcto no es si
los numeros se parecen: es si ALGUNA celda `(vano, ventana)` cambio de clase. Un
solo desplazamiento se propaga en silencio al simulador, a los informes y al
ranking de criticidad, y ninguna prueba de igualdad de campos lo delataria si la
frontera pasara justo entre dos centroides.

La especificacion pide literalmente "GIVEN the full `Indicadores_vano_v3.csv`
dataset". La verificacion de la fase 0 solo lo comprobo con seis puntos
sinteticos y lo reporto como no verificado --- correctamente. Esta prueba cierra
ese hueco de verdad.

## Por que es barata

`leer_eventos` trae solo las columnas base, asi que leer los ~159 k eventos y
agregar las ~111 k celdas cuesta decimas de segundo, no los cientos de MB que
costaria abrir el CSV entero. Medido: 0,4 s de punta a punta.

## El testigo independiente

Se compara el artefacto versionado contra la geometria embebida en
`data/models/mil_vano_ventana_v1.pt`. Ese `.pt` lo escribio el entrenamiento con
la geometria que el cuaderno 04 exporto en su dia, y no se ha vuelto a entrenar:
es un testigo que no pasa por el codigo que esta prueba verifica.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from chec_impacto.models.criticality_assignment import Geometria, asignar_clase
from chec_local_interpreter.ventanas_015 import (
    RUTA_GEOMETRIA,
    construir_tabla_vano_ventana,
    construir_ventanas,
)

RAIZ = Path(__file__).resolve().parents[1]
RUTA_CSV = RAIZ / "data" / "Indicadores_vano_v3.csv"
RUTA_MODELO = RAIZ / "data" / "models" / "mil_vano_ventana_v1.pt"
CLAVE_ESPACIO = "0"


def _geometria_de(bloque: dict) -> Geometria:
    return Geometria(
        logs=(bool(bloque["logs"][0]), bool(bloque["logs"][1])),
        offset=np.asarray(bloque["offset"], dtype=float),
        scale=np.asarray(bloque["scale"], dtype=float),
        centroides=np.asarray(bloque["centroides"], dtype=float),
    )


def _geometria_del_artefacto() -> Geometria:
    payload = json.loads(Path(RUTA_GEOMETRIA).read_text(encoding="utf-8"))
    return _geometria_de(payload["geometrias"][CLAVE_ESPACIO])


def _geometria_del_modelo_entrenado() -> Geometria:
    import torch

    payload = torch.load(RUTA_MODELO, map_location="cpu", weights_only=False)
    return _geometria_de(payload["geometria"])


requiere_datos = pytest.mark.skipif(
    not RUTA_CSV.exists() or not RUTA_MODELO.exists(),
    reason="requiere data/Indicadores_vano_v3.csv (git-lfs) y el modelo entrenado",
)


@requiere_datos
def test_los_cuatro_campos_de_la_geometria_son_identicos():
    artefacto = _geometria_del_artefacto()
    modelo = _geometria_del_modelo_entrenado()
    assert artefacto.logs == modelo.logs
    for campo in ("offset", "scale", "centroides"):
        np.testing.assert_array_equal(
            getattr(artefacto, campo), getattr(modelo, campo), err_msg=campo
        )


@requiere_datos
def test_ninguna_celda_vano_ventana_cambia_de_clase_sobre_el_dataset_completo():
    from scripts.exportar_geometria import leer_eventos

    eventos = leer_eventos()
    tabla = construir_tabla_vano_ventana(eventos, construir_ventanas(eventos["FECHA"]))
    n_obs = tabla["num_eventos"].to_numpy(dtype=float)
    u = tabla["uiti_acumulado"].to_numpy(dtype=float)

    # Guarda de la propia prueba: si la agregacion devolviera un punado de filas,
    # las comparaciones de abajo pasarian sin haber mirado nada.
    assert len(tabla) > 100_000, f"solo {len(tabla)} celdas; la agregacion cambio"

    clase_artefacto, _ = asignar_clase(n_obs, u, _geometria_del_artefacto())
    clase_modelo, _ = asignar_clase(n_obs, u, _geometria_del_modelo_entrenado())

    distintas = int((clase_artefacto != clase_modelo).sum())
    assert distintas == 0, (
        f"{distintas} de {len(clase_artefacto):,} celdas cambiaron de clase al "
        "promover la geometria. El cambio NO es neutral."
    )
