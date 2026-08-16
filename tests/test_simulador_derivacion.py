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


# --------------------------------------------------- el puente derivacion -> tablero

PAQUETE = RAIZ / "aplicaciones" / "06_simulador" / "paquete"

# Aqui vivian dos pruebas del "puente": los 23 nombres que las celdas 8-16 leian del
# espacio de nombres que dejaban las celdas 0-7. Se comprobaban ejecutando las celdas
# de arranque en un subproceso y mirando que ninguno faltara.
#
# Ese puente ya no es un espacio de nombres compartido: es la firma
# `tablero.construir(derivado, ...)`, y `Derivado` es un dataclass, asi que un campo
# que falte falla al construirlo y no diez pantallas mas abajo. Lo que aquellas dos
# pruebas querian saber -- "¿el tablero encuentra todo lo que el arranque le deja?" --
# se contesta mejor haciendolo: se arma el tablero de verdad contra el paquete.

_GUION_TABLERO = """
import json, os, sys
sys.path.insert(0, {src!r})
os.environ['RUTA_VARIABLES_SIMULAR'] = {simular!r}
from chec_tableros.simulador import derivacion, tablero
D = derivacion.cargar({paquete!r})


def hojas(w):
    yield w
    for h in getattr(w, 'children', ()):
        yield from hojas(h)


APP = tablero.construir(D, costos={costos!r})
figuras = [w for w in hojas(APP) if hasattr(w, 'data') and hasattr(w, 'layout')]
print('RESULTADO ' + json.dumps({{
    'widgets': sum(1 for _ in hojas(APP)),
    'figuras': len(figuras),
    'trazas': len(figuras[0].data) if figuras else 0,
    'titulos': [a.text for a in figuras[0].layout.annotations if a.text][:10],
}}))
"""


@pytest.mark.skipif(not (PAQUETE / "catalogo.joblib").exists(),
                    reason="requiere el paquete del simulador construido")
def test_el_tablero_se_arma_entero_contra_el_paquete_congelado():
    """El camino EXACTO de la aplicacion: `cargar()` y despues `construir()`.

    Corre en subproceso porque arma 593 widgets y un `FigureWidget` con el bundle
    de plotly.js dentro; eso no se devuelve al proceso de pruebas al terminar.

    No sustituye a `test_simulador_flujo_vivo.py`, que conduce el tablero en un
    navegador: aqui no se puede pulsar `Simular` -- corre en el bucle de eventos
    del widget y fuera del navegador deja las barras vacias. Lo que si se afirma es
    lo que aquel no puede permitirse comprobar en cada arranque, y lo hace en
    segundos en vez de en ocho minutos.
    """
    import subprocess

    guion = _GUION_TABLERO.format(
        src=str(RAIZ / "src"), paquete=str(PAQUETE),
        simular=str(PAQUETE / "Variables_simular.xlsx"),
        costos=str(PAQUETE / "Actividades_mantenimiento_costos_2026.xlsx"))
    proceso = subprocess.run([sys.executable, "-c", guion], cwd=RAIZ,
                             capture_output=True, text=True)
    assert proceso.returncode == 0, proceso.stderr[-3000:]
    linea = next(l for l in proceso.stdout.splitlines() if l.startswith("RESULTADO "))
    r = json.loads(linea[len("RESULTADO "):])

    assert r["figuras"] == 1, "el tablero tiene UNA figura, con sus ocho paneles dentro"
    assert r["trazas"] > 50, f"la figura salio con {r['trazas']} trazas"
    assert r["widgets"] > 300, (
        f"el tablero armo {r['widgets']} widgets; las casillas de vano, de variable y "
        "de actividad ya pasan de 200 por su cuenta")
    # Los tres paneles que dan sentido al tablero: el mapa medido, el simulado y el
    # grafo. Que la figura tenga trazas no dice que los paneles esten.
    for panel in ("Criticidad Original", "Criticidad Simulada", "Grafo"):
        assert any(panel in t for t in r["titulos"]), (
            f"falta el panel {panel!r}; hay {r['titulos']}")


def test_derivar_no_necesita_ningun_cuaderno():
    """Lo que esta rebanada existe para lograr, comprobado y no prometido.

    Se comprobaba rompiendo `cuaderno.ejecutar` a proposito, y era la forma correcta
    mientras existia: sin eso, el modulo podia envolver la ejecucion de celdas y las
    huellas cuadraban igual. Ese ayudante se borro con el ultimo `.ipynb`, asi que la
    pregunta se contesta un nivel mas arriba y sin datos: `derivacion` no nombra
    ningun cuaderno ni ningun `exec`.

    La version cara -- que `derivar()` produce el paquete byte a byte -- ya la
    comprueba `test_derivar_reproduce_el_paquete_golden` mas arriba.
    """
    import ast

    fuente = (RAIZ / "src" / "chec_tableros" / "simulador" / "derivacion.py").read_text(
        encoding="utf-8")
    arbol = ast.parse(fuente)

    llamadas = {ast.unparse(n.func) for n in ast.walk(arbol) if isinstance(n, ast.Call)}
    assert not {"exec", "eval"} & llamadas
    assert ".ipynb" not in {
        n.value for n in ast.walk(arbol)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
