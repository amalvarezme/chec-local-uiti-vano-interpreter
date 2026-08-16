"""El arranque caro del simulador, fuera del cuaderno y sin cambiar un byte.

## Que se esta moviendo, y por que importa el "sin cambiar un byte"

Hasta ahora `aplicaciones/06_simulador/preparar.py` construia el paquete
**ejecutando las siete primeras celdas del cuaderno 06** con `exec()`. Ese diseno
tenia una virtud real -- no duplicaba la derivacion -- y un costo: el constructor
dependia de los INDICES de celda de un `.ipynb`, y nadie podia importar esa
derivacion desde ningun otro sitio ni probarla por separado.

`chec_tableros.simulador.derivacion` se la lleva a un modulo. La pregunta que
decide si el movimiento fue correcto no es si el paquete "se ve bien": es si sale
**identico byte a byte** al que producia el camino viejo. Cualquier diferencia --
un dtype, un orden de columnas, un redondeo de coordenada -- se propaga al
simulador sin dar ningun error.

Por eso estas pruebas comparan contra `tests/golden/tableros_pre_migracion/`,
congelado ANTES de que existiera este modulo.

## Por que se saltan sin datos

`derivar()` abre el CSV de 566 MB, tres shapefiles y el cache de bolsas de 199 MB.
Sin ellos se salta, que es informacion honesta; fingir que paso no lo es.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
GOLDEN = RAIZ / "tests" / "golden" / "tableros_pre_migracion" / "huellas.json"
CSV = RAIZ / "data" / "Indicadores_vano_v3.csv"
BOLSAS = RAIZ / "data" / "derived" / "bolsas_mil_full.joblib"
MODELO = RAIZ / "data" / "models" / "mil_vano_ventana_v1.pt"

requiere_datos = pytest.mark.skipif(
    not (CSV.exists() and BOLSAS.exists() and MODELO.exists()),
    reason="requiere el CSV, el cache de bolsas y el modelo entrenado",
)

# Los cuatro que `congelar` escribe. Los otros cuatro del paquete son copias
# literales de archivos de `data/`, asi que no dicen nada sobre la derivacion.
DERIVADOS = ("tabla.parquet", "X_inst.npy", "geo.json", "catalogo.joblib")


def _huellas_golden() -> dict:
    piezas = json.loads(GOLDEN.read_text(encoding="utf-8"))["06_simulador"]["piezas"]
    return {n: piezas[n]["sha256"] for n in DERIVADOS}


def test_el_modulo_expone_derivar_y_congelar():
    """Guarda barata: corre sin datos y falla con un mensaje claro si el modulo
    no existe todavia o si se le cambia la firma."""
    from chec_tableros.simulador import derivacion

    assert callable(derivacion.derivar)
    assert callable(derivacion.congelar)


@requiere_datos
def test_derivar_congela_los_mismos_bytes_que_el_camino_viejo(tmp_path):
    """El corazon de la rebanada: mismo paquete, sin ejecutar una sola celda.

    Se comparan solo los cuatro archivos que la derivacion PRODUCE. Los otros
    cuatro del paquete son `shutil.copy2` de archivos versionados: incluirlos
    inflaria la prueba sin anadir una sola garantia sobre este modulo.
    """
    from chec_tableros.simulador import derivacion

    derivacion.congelar(derivacion.derivar(), tmp_path)

    esperado = _huellas_golden()
    obtenido = {
        nombre: hashlib.sha256((tmp_path / nombre).read_bytes()).hexdigest()
        for nombre in DERIVADOS
    }
    distintos = [n for n in DERIVADOS if obtenido[n] != esperado[n]]
    assert not distintos, (
        f"{distintos} no reproducen el golden. El movimiento a src/ NO fue neutral: "
        "algo cambio de dtype, de orden o de redondeo."
    )


@requiere_datos
def test_derivado_trae_los_nombres_que_el_cuaderno_puentea_al_tablero(tmp_path):
    """Las celdas 8-16 del cuaderno leen 22 nombres de las celdas 3-7.

    De esos, los que produce el arranque CARO son estos. Si `Derivado` deja de
    traer uno, el cuaderno servido se queda sin el y el fallo aparece a mitad del
    tablero, lejos de aqui.
    """
    from chec_tableros.simulador import derivacion

    d = derivacion.derivar()
    for campo in ("tabla", "ventanas", "x_inst", "features_mil", "bag_index",
                  "geo_por_circuito", "trafos", "switches", "knobs",
                  "feature_names", "label_encoders", "max_values_imputed"):
        assert getattr(d, campo) is not None, campo

    assert len(d.tabla) > 100_000, f"la tabla trae {len(d.tabla)} celdas"
    assert d.x_inst.dtype.name == "float32", (
        "el artefacto guarda float64; convertirlo aqui es lo que baja X_inst.npy "
        "de 184,7 a 92,4 MB, y esta medido que no mueve ni un bit del resultado"
    )
    assert list(d.features_mil[:len(d.feature_names)]) == list(d.feature_names), (
        "las features del MIL ya no empiezan por las de MGCECDL: el catalogo de "
        "knobs apuntaria a columnas equivocadas"
    )


# Los 23 nombres que las celdas 8-16 leen del arranque, medidos con `ast` sobre el
# cuaderno. Si el arranque deja de definir uno, el fallo aparece a mitad del tablero,
# lejos de su causa; aqui aparece en el sitio.
PUENTE = (
    "COSTOS_ITEMS_PATH", "VARIABLES_SELECCION_PATH", "label_encoders",
    "max_values_imputed", "BAG_INDEX", "COLORES_MODALIDAD", "COLUMNAS_MODALIDAD",
    "FEATURES_MIL", "MIL", "MODALIDADES_MIL", "X_INST", "CIRCUITOS", "DATOS_VENTANA",
    "GEO_POR_CIRCUITO", "SWITCHES", "TABLA", "TRAFOS", "VANOS_POR_CIRCUITO",
    "VENTANAS", "VENTANAS_POR_CIRCUITO", "clases_para", "KNOBS", "feature_names",
)

_GUION_PUENTE = """
import json, sys
sys.path.insert(0, {comun!r})
import cuaderno
from pathlib import Path
espacio = cuaderno.ejecutar(Path({nb!r}), celdas=range(0, 8))
print("RESULTADO " + json.dumps({{
    "faltan": [n for n in {puente!r} if n not in espacio],
    "celdas": len(espacio["TABLA"]),
    "bolsas": len(espacio["BAG_INDEX"].keys),
    "knobs": len(espacio["KNOBS"]),
}}))
"""


def _puente_de(notebook: Path, entorno: dict | None = None) -> dict:
    """Ejecuta las celdas 0-7 de un cuaderno EN SUBPROCESO y reporta el puente.

    En subproceso porque la celda 1 purga de `sys.modules` todo `chec_impacto`,
    `chec_local_interpreter` y `chec_tableros`. Hacerlo en proceso deja a las
    pruebas siguientes con modulos reimportados a media suite.
    """
    import os
    import subprocess

    guion = _GUION_PUENTE.format(
        comun=str(RAIZ / "aplicaciones" / "_comun"), nb=str(notebook), puente=PUENTE)
    salida = subprocess.run(
        [sys.executable, "-c", guion], check=True, cwd=RAIZ, capture_output=True,
        text=True, env={**os.environ, **(entorno or {})},
    ).stdout
    linea = next(l for l in salida.splitlines() if l.startswith("RESULTADO "))
    return json.loads(linea[len("RESULTADO "):])


@requiere_datos
def test_el_cuaderno_sigue_entregando_al_tablero_los_23_nombres_del_puente():
    """El cuaderno ahora DISPARA la derivacion en vez de contenerla.

    Mover ese codigo a un modulo es neutral solo si las celdas 8-16 siguen
    encontrando lo mismo en su espacio de nombres. Ninguna prueba miraba eso, y es
    justo donde un movimiento asi se rompe en silencio.
    """
    r = _puente_de(RAIZ / "notebooks" / "base_apps"
                   / "06_uiti_vano_explicabilidad_simulador.ipynb")
    assert r["faltan"] == [], r["faltan"]
    assert r["celdas"] > 100_000 and r["bolsas"] > 100_000 and r["knobs"] > 0


@requiere_datos
def test_la_copia_servida_entrega_el_mismo_puente_leyendo_el_paquete():
    """El camino que NUNCA se habia comprobado de forma automatica.

    `preparar_copia()` parchea el cuaderno para que lea del paquete, y hasta ahora
    la unica forma de saber si el resultado arrancaba era abrir el simulador a
    mano. Aqui se ejecutan sus celdas de arranque de verdad: si el parche dejara
    un nombre sin definir, el tablero saldria a medias y nadie se enteraria hasta
    abrirlo.
    """
    sys.path.insert(0, str(RAIZ / "aplicaciones" / "06_simulador"))
    import preparar

    copia = preparar.preparar_copia()
    r = _puente_de(copia, {"PAQUETE_06": str(RAIZ / "aplicaciones" / "06_simulador" / "paquete")})
    assert r["faltan"] == [], r["faltan"]
    assert r["celdas"] > 100_000 and r["bolsas"] > 100_000 and r["knobs"] > 0


@requiere_datos
def test_derivar_no_ejecuta_ninguna_celda_del_cuaderno(monkeypatch):
    """Lo que esta rebanada existe para lograr, comprobado y no prometido.

    Se rompe `cuaderno.ejecutar` a proposito: si `derivar()` siguiera pasando por
    ahi, la prueba falla. Sin esto, el modulo podria envolver la ejecucion de
    celdas y las huellas cuadrarian igual.
    """
    sys.path.insert(0, str(RAIZ / "aplicaciones" / "_comun"))
    import cuaderno as _cuaderno

    def _prohibido(*_a, **_k):
        raise AssertionError("derivar() ejecuto celdas del cuaderno 06")

    monkeypatch.setattr(_cuaderno, "ejecutar", _prohibido)

    from chec_tableros.simulador import derivacion

    assert derivacion.derivar().tabla is not None
