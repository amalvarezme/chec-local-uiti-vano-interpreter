"""El cuaderno que sirve la aplicacion del simulador, y lo que NO puede tocar.

## De donde viene este fichero

Sustituye a `test_simulador_parches_vigentes.py`, que comprobaba que las seis marcas
de texto que `preparar.py` buscaba dentro del cuaderno 06 siguieran apareciendo
exactamente una vez. Ese fichero existia por una razon buena --- el parcheo solo se
verificaba al construir, y construir exige el CSV de 566 MB, asi que ninguna prueba lo
ejercitaba: medido, el cuaderno 06 quedo importando un modulo borrado y `pytest -q`
siguio en verde con 2.310 pruebas.

Ya no hay marcas ni parches. El cuaderno servido se genera entero desde `preparar.py`
y el tablero vive en `src/chec_tableros/simulador/tablero.py`. Lo que se hereda de
aquel fichero no es su tecnica sino sus dos preguntas, que siguen siendo las mismas:

1. **Lo que la aplicacion sirve, ¿arranca?** Antes se preguntaba ejecutando la celda 1
   del cuaderno. Ahora se pregunta compilando la celda generada y resolviendo sus
   imports de verdad.
2. **¿Se le escapa el camino caro?** Antes lo contestaba `_verificar_copia`, buscando
   `context_df`, `Xdf`, `procesar_dataset_completo` y `gpd` en la copia parcheada. La
   pregunta no cambio: el tablero NO puede abrir el CSV ni los shapefiles, porque eso
   son 909 MB y 7 s en cada apertura, que es exactamente lo que el paquete existe para
   evitar. Solo cambio donde se mira.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import ayudas_subproceso
import pytest

RAIZ = Path(__file__).resolve().parents[1]
APP = RAIZ / "aplicaciones" / "06_simulador"
TABLERO = RAIZ / "src" / "chec_tableros" / "simulador" / "tablero.py"


def _preparar():
    """`preparar.py` importado como modulo, con sus vecinos de `_comun` a la vista."""
    for ruta in (APP, APP.parent / "_comun"):
        if str(ruta) not in sys.path:
            sys.path.insert(0, str(ruta))
    import preparar  # noqa: PLC0415 -- el sys.path se arma justo arriba

    return preparar


# --------------------------------------------------------- el cuaderno generado


def test_el_cuaderno_generado_tiene_una_sola_celda_de_codigo(tmp_path, monkeypatch):
    """Un cuaderno de una celda es la mitad del punto de esta migracion.

    El anterior tenia veinte, y seis de ellas se reescribian por texto antes de
    servirse. Si esto vuelve a crecer, alguien esta metiendo logica en el
    generador en vez de en el modulo del tablero.
    """
    preparar = _preparar()
    monkeypatch.setattr(preparar, "COPIA", tmp_path / "06_simulador.ipynb")
    documento = json.loads(preparar.escribir_cuaderno().read_text("utf-8"))

    assert [c["cell_type"] for c in documento["cells"]] == ["code"]
    assert documento["cells"][0]["outputs"] == []
    assert documento["cells"][0]["execution_count"] is None


def test_el_cuaderno_generado_declara_el_kernel_de_la_aplicacion(tmp_path, monkeypatch):
    """`python3` es el nombre que usa todo el mundo, y Voila lo resuelve contra los
    kernels de LA MAQUINA: se le vio arrancando el interprete de otro proyecto, ya
    borrado, y contestando 500 con un FileNotFoundError sin relacion aparente."""
    preparar = _preparar()
    monkeypatch.setattr(preparar, "COPIA", tmp_path / "06_simulador.ipynb")
    documento = json.loads(preparar.escribir_cuaderno().read_text("utf-8"))

    assert documento["metadata"]["kernelspec"]["name"] == preparar.NOMBRE_KERNEL
    assert preparar.NOMBRE_KERNEL != "python3"


def test_la_celda_generada_compila_y_nombra_lo_que_app_py_le_pasa():
    """Las tres variables de entorno son el unico contrato entre `app.py` y la celda.

    La celda no tiene `__file__` ni sabe cual es el directorio de trabajo --- lo elige
    Voila ---, asi que si un nombre deja de coincidir, la aplicacion muere dentro del
    kernel con un `KeyError` que no menciona a `app.py`.
    """
    preparar = _preparar()
    compile(preparar.celda(), "<celda generada>", "exec")

    fuente_app = (APP / "app.py").read_text("utf-8")
    for variable in ("PAQUETE_06", "RAIZ_SRC_06", "APP_06"):
        assert variable in preparar.celda(), f"la celda no lee {variable}"
        assert f"{variable}=" in fuente_app, f"app.py no pone {variable} en el entorno"


def test_la_celda_generada_llama_al_camino_barato_y_no_al_caro():
    """`derivar()` abre 909 MB; `cargar()` lee 94,5 MB congelados. La aplicacion es
    lo unico que NUNCA puede llamar al primero: son 7,1 s contra 0,3 s en cada
    apertura, que es la razon entera de que el paquete exista."""
    llamadas = {
        f"{ast.unparse(n.func)}"
        for n in ast.walk(ast.parse(_preparar().celda())) if isinstance(n, ast.Call)
    }
    assert "derivacion.cargar" in llamadas
    assert "derivacion.derivar" not in llamadas


@pytest.mark.parametrize("con_cierre", [True, False])
def test_el_boton_de_cerrar_solo_va_donde_hay_algo_que_cerrar(con_cierre: bool):
    """En local cierra el Voila que arranco `app.py`; en Databricks no hay tal proceso.

    Ese boton manda `SIGTERM` al pid que `app.py` deja escrito. En el contenedor de
    una Databricks App no hay ni ese `app.py` ni ese pid, y el ciclo de vida lo
    gobierna la plataforma: un boton "Cerrar" que no cierra nada -- o que senala a un
    pid ajeno del contenedor -- no es un detalle cosmetico.
    """
    codigo = _preparar().celda(con_cierre=con_cierre)
    compile(codigo, "<celda generada>", "exec")
    assert ("import cierre" in codigo) is con_cierre
    assert ("cierre.barra()" in codigo) is con_cierre


# ------------------------------------------------ el tablero no toca el camino caro


# Los cuatro nombres que `_verificar_copia` prohibia en la copia parcheada, trasladados
# al modulo. `context_df` y `Xdf` eran los 1.919 MB del pipeline del CSV; `gpd`, los
# 326 MB de los tres shapefiles.
PROHIBIDOS_EN_EL_TABLERO = (
    "procesar_dataset_completo",
    "geopandas",
    "cargar_bolsas",
    "Indicadores_vano_v3.csv",
)


@pytest.mark.parametrize("prohibido", PROHIBIDOS_EN_EL_TABLERO)
def test_el_tablero_no_menciona_el_camino_caro(prohibido):
    """Se mira el codigo EFECTIVO, sin comentarios ni cadenas.

    Un comentario que explica por que el tablero ya no abre el CSV es justo lo que
    hay que conservar, y una prueba que lo prohibiera empujaria a borrar la
    explicacion en vez del acoplamiento. Es el mismo criterio -- y el mismo motivo --
    que `_sin_comentarios` aplicaba en `preparar.py` antes de esta migracion.
    """
    arbol = ast.parse(TABLERO.read_text("utf-8"))
    nombres = {n.id for n in ast.walk(arbol) if isinstance(n, ast.Name)}
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Attribute):
            nombres.add(nodo.attr)
        elif isinstance(nodo, ast.ImportFrom):
            nombres.update(a.name for a in nodo.names)
            nombres.update((nodo.module or "").split("."))
        elif isinstance(nodo, ast.Import):
            nombres.update(a.name.split(".")[0] for a in nodo.names)
    assert prohibido not in nombres


def test_el_tablero_se_importa_sin_tocar_ningun_dato():
    """Importar el modulo no puede costar un disco.

    Era un riesgo real y no teorico: la celda 1 del cuaderno apuntaba
    `RUTA_VARIABLES_SIMULAR` ANTES de importar `simulador_variables` porque uno de
    sus nombres se resolvia leyendo el .xlsx en el momento del import. Con el tablero
    en un modulo, ese orden ya no lo controla nadie, asi que la lectura tiene que
    haberse movido dentro de `construir()` --- y esta prueba es lo que lo fija.
    """
    import subprocess

    resultado = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'src');"
         " from chec_tableros.simulador import tablero;"
         " print(tablero.construir.__name__)"],
        cwd=RAIZ, capture_output=True, text=True,
        # Sin la variable de entorno: si algo la necesitara al importar, aqui falla.
        # Lo que el SISTEMA pide para arrancar es otra cosa, y va aparte: ver
        # `ayudas_subproceso`.
        env=ayudas_subproceso.entorno_minimo(),
    )
    assert resultado.returncode == 0, resultado.stderr[-2000:]
    assert resultado.stdout.strip() == "construir"
