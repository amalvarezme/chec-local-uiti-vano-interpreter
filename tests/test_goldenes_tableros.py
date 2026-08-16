"""El golden congelado ANTES de mover los tableros a `src/chec_tableros`.

## Que contrato fija

Los cinco tableros se construyen hoy ejecutando las celdas de un `.ipynb` con
`exec()`. La migracion planificada los convierte en modulos importables. Este
fichero es la referencia contra la que se comprueba que esa migracion **no
cambio lo que el tablero produce** -- que es lo unico que el usuario ve.

## Por que el golden son huellas y no los artefactos

Los cinco artefactos suman **158 MB**. El golden ocupa **10,5 KB** y detecta
exactamente lo mismo, porque la construccion es reproducible byte a byte: dos
corridas seguidas dan el mismo `datos.<sha>.json`, el mismo `index.html` y las
mismas ocho piezas del `paquete/`. La justificacion completa esta en
`scripts/capturar_goldenes.py`.

## Por que estas pruebas se saltan sin datos

Reconstruir exige el CSV de 566 MB, tres shapefiles y (para el simulador) el
cache de bolsas de 199 MB. En un checkout sin ellos se saltan en vez de fallar:
un `skip` honesto es informacion, un `xfail` disfrazado no.

La comprobacion estructural del propio golden -- la primera -- si corre siempre,
porque un golden vacio o truncado pasaria las demas sin mirar nada.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
GOLDEN = RAIZ / "tests" / "golden" / "tableros_pre_migracion" / "huellas.json"
CSV = RAIZ / "data" / "Indicadores_vano_v3.csv"
BOLSAS = RAIZ / "data" / "derived" / "bolsas_mil_full.joblib"

TABLEROS = (
    "01_clima",
    "02_agrupamiento_vanos",
    "03_trayectorias_circuitos",
    "04_trayectorias_vanos",
)

sys.path.insert(0, str(RAIZ / "scripts"))
from capturar_goldenes import bloques_del_payload, huella_de_carpeta  # noqa: E402


def _golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_el_golden_cubre_los_cinco_tableros_y_no_esta_vacio():
    """Guarda de las demas pruebas: un golden truncado las dejaria pasar en vano."""
    golden = _golden()
    assert set(golden) == set(TABLEROS) | {"06_simulador"}
    for nombre, tablero in golden.items():
        assert tablero["piezas"], f"{nombre} no tiene ninguna pieza congelada"
        for pieza, huella in tablero["piezas"].items():
            assert len(huella["sha256"]) == 64, f"{nombre}/{pieza}"
            assert huella["bytes"] > 0, f"{nombre}/{pieza}"


def test_el_golden_no_congela_el_manifiesto_que_lleva_marca_de_tiempo():
    """`manifiesto.json` guarda `construido_en`, asi que difiere en cada corrida.

    Congelarlo convertiria el golden en una prueba que falla siempre, y la
    reaccion natural a eso es borrarla, no arreglarla.
    """
    for nombre, tablero in _golden().items():
        assert "manifiesto.json" not in tablero["piezas"], nombre


@pytest.mark.skipif(not CSV.exists(), reason="requiere data/Indicadores_vano_v3.csv")
@pytest.mark.parametrize("tablero", TABLEROS)
def test_reconstruir_el_tablero_reproduce_su_huella(tablero):
    """Reconstruye y compara pieza a pieza, y bloque a bloque dentro del payload.

    El desglose por bloque es lo que hace util el fallo: sin el, un `sha256`
    distinto solo dice que algo de 24 MB cambio.
    """
    subprocess.run(
        [sys.executable, str(RAIZ / "aplicaciones" / tablero / "construir.py")],
        check=True,
        cwd=RAIZ,
        stdout=subprocess.DEVNULL,
    )
    panel = RAIZ / "aplicaciones" / tablero / "panel"
    esperado = _golden()[tablero]

    bloques = bloques_del_payload(panel)
    distintos = [
        clave for clave, h in esperado["bloques_del_payload"].items()
        if bloques.get(clave) != h
    ]
    assert not distintos, f"{tablero}: cambiaron los bloques {distintos}"
    assert set(bloques) == set(esperado["bloques_del_payload"]), (
        f"{tablero}: el payload gano o perdio bloques"
    )

    piezas = huella_de_carpeta(panel)
    for nombre, huella in esperado["piezas"].items():
        assert piezas.get(nombre) == huella, f"{tablero}/{nombre} no reproduce"


@pytest.mark.skipif(
    not CSV.exists() or not BOLSAS.exists(),
    reason="requiere el CSV y data/derived/bolsas_mil_full.joblib (lo produce el cuaderno 05)",
)
def test_reconstruir_el_paquete_del_simulador_reproduce_su_huella():
    """El `paquete/` no tiene payload con bloques: son ocho ficheros de carga.

    Esta es ademas la unica prueba automatica que ejercita `construir_paquete()`
    de punta a punta. Hasta ahora nada lo hacia, y por eso un import roto en la
    celda 1 del cuaderno 06 convivio con 2.310 pruebas en verde.

    Corre en SUBPROCESO por una razon medida, no por gusto: la celda 1 del
    cuaderno 06 purga de `sys.modules` todo lo que empiece por `chec_impacto`,
    `chec_local_interpreter` o `scripts`. Ejecutarla en proceso deja a las pruebas
    que vengan despues con modulos reimportados a media suite -- reproducido:
    tumbaba `test_mgcecdl_graph_interpretability` y `test_report_pipeline`, dos
    ficheros que no tienen nada que ver con el simulador y que pasan solos.
    """
    subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'aplicaciones/06_simulador');"
         " import preparar; preparar.construir_paquete()"],
        check=True,
        cwd=RAIZ,
        stdout=subprocess.DEVNULL,
    )
    piezas = huella_de_carpeta(RAIZ / "aplicaciones" / "06_simulador" / "paquete")
    for nombre, huella in _golden()["06_simulador"]["piezas"].items():
        assert piezas.get(nombre) == huella, f"paquete/{nombre} no reproduce"


def test_la_huella_de_un_bloque_es_estable_frente_al_orden_de_las_claves():
    """El desglose serializa con `sort_keys`, no con el orden de insercion.

    Sin eso, un `dict` reconstruido en otro orden daria un falso positivo y la
    migracion parecerian romper algo que no rompio.
    """
    a = json.dumps({"x": 1, "y": 2}, sort_keys=True, separators=(",", ":"))
    b = json.dumps({"y": 2, "x": 1}, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(a.encode()).digest() == hashlib.sha256(b.encode()).digest()
