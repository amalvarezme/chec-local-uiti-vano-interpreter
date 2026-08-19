"""Un clon de este repositorio en otra maquina tiene que poder correrlo todo.

Esto dejo de ser una hipotesis el 2026-08-19: la subida a Databricks **se hace clonando
este repositorio en otro PC** y corriendo `/subir-a-databricks` desde ahi. Lo que no
viaje en git, alli no existe -- y el modo en que eso falla es el peor posible, porque
`fs cp -r data` sube alegremente lo que encuentra y el hueco aparece mucho despues,
dentro de una app que no arranca.

Lo que se fija aqui es la lista de INSUMOS -- lo que se lee y nadie genera en esa
maquina --, no la de artefactos construidos. Los `panel/` de los tableros y el
`paquete/` del simulador se construyen en destino a proposito: son cientos de MB
reproducibles, y versionarlos seria pagar dos veces por lo mismo.

## Por que cada uno esta en la lista

  * los seis de `data/` que ya venian versionados: sin ellos no hay tablero que construir;
  * `data/derived/bolsas_mil_full.joblib`, que entro a LFS el 2026-08-19 por esta misma
    razon -- el simulador no se puede construir sin el, y en la otra maquina nadie va a
    correr el cuaderno 05 de 40 minutos para producirlo;
  * `site/data/variables.json`, que el cuaderno 05 lee para etiquetar sus tablas de
    features y cuya ausencia cuesta una columna, no una corrida: por eso nadie noto
    durante meses que tenia un consumidor.

## La trampa que este archivo NO puede atrapar

Que un archivo este rastreado no significa que un clon traiga sus bytes: los de LFS
llegan como punteros de ~134 bytes hasta que alguien corre `git lfs pull`. Eso se
comprueba por tamanio en el momento de usarlos -- lo hace la etapa 3 de
`/subir-a-databricks` y lo hacen las aplicaciones al construir --, no aqui.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]

# Los tres entregables que tienen que salir de un clon limpio, y lo que lee cada uno.
# La fuente no es una lista escrita a mano: son las guardas que ya existen en el
# codigo -- `aplicaciones/06_simulador/preparar.py`, los `construir.py` de los cuatro
# visores y el inventario `_INSUMOS` del generador del cuaderno 05.
INSUMOS = {
    "data/Indicadores_vano_v3.csv": "la base de eventos (LFS)",
    "data/Variables_seleccion.xlsx": "el diccionario de variables",
    "data/Variables_simular.xlsx": "el catalogo de variables a simular",
    "data/Actividades_mantenimiento_costos_2026.xlsx": "el catalogo de costos",
    "data/geometria_kmeans_014_v1.json": "la geometria KMeans congelada",
    "data/models/mil_vano_ventana_v1.pt": "el modelo MIL entrenado",
    "data/graphs/mgcecdl_feature_order.json": "el orden de features del grafo",
    "data/derived/bolsas_mil_full.joblib": "las bolsas vano x ventana (LFS)",
    "site/data/variables.json": "los modos tematicos A-F del cuaderno 05",
}

# Un shapefile sin sus sidecars abre como una capa VACIA, no como un error. Los tres
# que se leen, con el minimo que los hace utiles.
SHAPEFILES = ("MVLINSEC", "GDBCHEC_TRANSFOR", "SWITCHES")
SIDECARS = ("shp", "shx", "dbf", "prj")

# Derivados que NO viajan, y por que. Se fija la ausencia igual que la presencia: cada
# uno es regenerable en destino, y meterlos a LFS es cuota que se paga cada mes.
NO_VIAJAN = {
    "data/derived/catalogo_controles_mil.joblib": "cache; se rehace solo al pedirlo",
    "data/derived/oof_mil_full_film_clase1.0.npz": "opcional; el desglose va DENTRO del .pt",
    "data/derived/geometrias_014.json": "heredado del extractor retirado del cuaderno 04",
}


def _rastreado(ruta: str) -> bool:
    hecho = subprocess.run(["git", "ls-files", "--error-unmatch", ruta],
                           cwd=RAIZ, capture_output=True, text=True)
    return hecho.returncode == 0


@pytest.mark.parametrize("ruta", sorted(INSUMOS), ids=lambda r: r.split("/")[-1])
def test_cada_insumo_viaja_en_el_clon(ruta: str):
    assert _rastreado(ruta), (
        f"{ruta} ({INSUMOS[ruta]}) no esta rastreado por git: un clon en otra maquina "
        "no lo tendria, y el hueco no aparece hasta que algo falla mucho despues")


@pytest.mark.parametrize("nombre", SHAPEFILES)
def test_cada_shapefile_viaja_con_sus_sidecars(nombre: str):
    faltan = [e for e in SIDECARS if not _rastreado(f"data/GEO/{nombre}.{e}")]
    assert not faltan, (
        f"a {nombre} le faltan en git los sidecars {faltan}: un shapefile sin ellos abre "
        "como una capa vacia, que es un fallo mudo")


@pytest.mark.parametrize("ruta", sorted(NO_VIAJAN), ids=lambda r: r.split("/")[-1])
def test_los_derivados_regenerables_no_viajan(ruta: str):
    """Versionar un derivado regenerable es pagar cuota de LFS todos los meses por algo
    que la maquina de destino puede rehacer sola."""
    assert not _rastreado(ruta), (
        f"{ruta} entro a git y no deberia: {NO_VIAJAN[ruta]}")


def test_el_cache_de_bolsas_viaja_por_lfs_y_no_como_blob():
    """199 MB como blob normal inflarian el `.git` de todo el que clone, para siempre.

    Se comprueba el ATRIBUTO y no el contenido: el contenido de un archivo de LFS en el
    indice es su puntero, y eso ya lo dice el atributo sin leer nada.
    """
    hecho = subprocess.run(
        ["git", "check-attr", "filter", "--", "data/derived/bolsas_mil_full.joblib"],
        cwd=RAIZ, capture_output=True, text=True)
    assert "filter: lfs" in hecho.stdout, (
        f"el cache de bolsas no esta declarado para LFS: {hecho.stdout.strip()}")
