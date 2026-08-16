"""Congela la huella de los cinco tableros ANTES de migrarlos a `src/`.

## Por que una huella y no el artefacto

La rebanada S3 del plan pedia "congelar 4 HTML y el `paquete/` del simulador".
Medido: el tablero del clima solo pesa **27,8 MB**, los cuatro juntos rondan los
55 MB y el `paquete/` del simulador otros **95 MB**. Guardarlos en git son ~150 MB
de salida generada que S14 no podria devolver -- borrar un fichero no lo saca del
historial.

Y no hacen falta. Medido tambien: **la construccion es reproducible byte a byte**.
Dos corridas seguidas de cada tablero producen el mismo `datos.<sha>.json` y el
mismo `index.html`; las ocho piezas de carga del `paquete/` tambien. Lo unico que
cambia entre corridas es `manifiesto.json`, que lleva la marca de tiempo
`construido_en` -- por eso se excluye.

Con eso, `sha256` del artefacto es una huella EXACTA: no aproxima el golden, lo
sustituye sin perder poder de deteccion, y ocupa unos pocos KB.

## Por que ademas se desglosa el payload

Un `sha256` que no cuadra solo dice "algo de 24 MB cambio". El payload de cada
tablero es un diccionario de bloques con nombre (`geometrias`, `vanos`, `circuitos`,
...), asi que se guarda tambien la huella de cada bloque. Cuando la migracion a
`src/chec_tableros` mueva algo, la prueba nombra el bloque en vez de senalar el
fichero entero.

## Uso

    python scripts/capturar_goldenes.py

Reconstruye los cinco y reescribe `tests/golden/tableros_pre_migracion/huellas.json`.
Necesita `data/Indicadores_vano_v3.csv`, los tres shapefiles, el modelo entrenado y
`data/derived/bolsas_mil_full.joblib` (este ultimo solo para el simulador).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "tests" / "golden" / "tableros_pre_migracion" / "huellas.json"

# El manifiesto lleva `construido_en`, asi que difiere en cada corrida por diseno.
# Incluirlo convertiria un golden estable en uno que falla siempre.
EXCLUIDOS = {"manifiesto.json"}

TABLEROS = {
    "01_clima": "01_clima",
    "02_agrupamiento_vanos": "02_agrupamiento_vanos",
    "03_trayectorias_circuitos": "03_trayectorias_circuitos",
    "04_trayectorias_vanos": "04_trayectorias_vanos",
}


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _huella_json(texto: bytes) -> str:
    return hashlib.sha256(texto).hexdigest()


def huella_de_carpeta(carpeta: Path) -> dict:
    """`sha256` por fichero, ignorando los comprimidos y el manifiesto.

    Los `.gz` son derivados deterministas de su original: si el original cuadra,
    el comprimido tambien, y duplicarlos solo hace el golden mas ruidoso.
    """
    piezas = {}
    for ruta in sorted(carpeta.iterdir()):
        if not ruta.is_file() or ruta.suffix == ".gz" or ruta.name in EXCLUIDOS:
            continue
        # El nombre lleva el hash corto del contenido (`datos.<sha10>.json`), asi que
        # se normaliza para que la clave del golden no cambie cuando cambie el dato:
        # lo que compara la prueba es el valor, no el nombre.
        nombre = ruta.name
        if nombre.startswith("datos.") and nombre.endswith(".json"):
            nombre = "datos.json"
        elif nombre.startswith("plotly-"):
            nombre = "plotly.js"
        piezas[nombre] = {"bytes": ruta.stat().st_size, "sha256": sha256(ruta)}
    return piezas


def bloques_del_payload(carpeta: Path) -> dict:
    """Huella por bloque con nombre dentro de `datos.<sha>.json`.

    Es lo que traduce "24 MB cambiaron" en "cambio `geometrias`".
    """
    datos = next(
        (r for r in carpeta.iterdir()
         if r.name.startswith("datos.") and r.name.endswith(".json")),
        None,
    )
    if datos is None:
        return {}
    payload = json.loads(datos.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return {
        clave: _huella_json(
            json.dumps(valor, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        for clave, valor in sorted(payload.items())
    }


def construir(app: str) -> None:
    subprocess.run(
        [sys.executable, str(RAIZ / "aplicaciones" / app / "construir.py")],
        check=True,
        cwd=RAIZ,
        stdout=subprocess.DEVNULL,
    )


def construir_simulador() -> None:
    """En subproceso: la celda 1 del cuaderno 06 purga `sys.modules`.

    `preparar.construir_paquete()` ejecuta esa celda, que borra todo lo que
    empiece por `chec_impacto`, `chec_local_interpreter` o `scripts`. Aislarlo
    evita que este script deje el interprete en un estado del que no avisa nadie.
    """
    subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'aplicaciones/06_simulador');"
         " import preparar; preparar.construir_paquete()"],
        check=True,
        cwd=RAIZ,
        stdout=subprocess.DEVNULL,
    )


def main() -> int:
    huellas: dict = {}
    for nombre, app in TABLEROS.items():
        print(f"  construyendo {nombre} ...", flush=True)
        construir(app)
        panel = RAIZ / "aplicaciones" / app / "panel"
        huellas[nombre] = {
            "piezas": huella_de_carpeta(panel),
            "bloques_del_payload": bloques_del_payload(panel),
        }

    print("  construyendo 06_simulador ...", flush=True)
    construir_simulador()
    huellas["06_simulador"] = {
        "piezas": huella_de_carpeta(RAIZ / "aplicaciones" / "06_simulador" / "paquete"),
        "bloques_del_payload": {},
    }

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(
        json.dumps(huellas, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    total = sum(
        p["bytes"] for t in huellas.values() for p in t["piezas"].values()
    )
    print(f"\n  {DESTINO.relative_to(RAIZ)}")
    print(f"  {len(huellas)} tableros, {total / 1e6:.1f} MB de artefacto resumidos "
          f"en {DESTINO.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
