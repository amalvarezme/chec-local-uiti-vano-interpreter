"""Static contract tests for the Databricks deployment command family.

These pin the three properties that were actually broken before, and that
prose alone will silently lose again on the next edit:

1. every command reads the shared contract and states the never-abort rule,
2. no command still tells the assistant to abort at the first privilege wall,
3. the shared contract still documents the restrictions met in the field.

Style follows `tests/test_experimento_kaggle_contract.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CMD_DIR = PROJECT_ROOT / ".claude" / "commands"
CONTRATO = CMD_DIR / "_contrato-despliegue-databricks.md"
BITACORA = PROJECT_ROOT / "scripts" / "bitacora_despliegue.py"

FAMILIA = (
    "app-agrupamiento-vanos-circuitos.md",
    "app-simulador-vano.md",
    "app-trayectorias-circuitos.md",
    "app-trayectorias-vanos.md",
    "app-vano-clima.md",
    "subir-a-databricks.md",
    "subir-datos-databricks.md",
    "subir-notebooks-databricks.md",
)


def _leer(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_el_contrato_compartido_existe():
    assert CONTRATO.exists(), "el contrato compartido es la referencia de toda la familia"


def test_la_herramienta_de_bitacora_existe():
    assert BITACORA.exists()


@pytest.mark.parametrize("nombre", FAMILIA)
def test_cada_comando_existe(nombre: str):
    assert (CMD_DIR / nombre).exists()


@pytest.mark.parametrize("nombre", FAMILIA)
def test_cada_comando_apunta_al_contrato(nombre: str):
    texto = _leer(CMD_DIR / nombre)
    assert "_contrato-despliegue-databricks.md" in texto, (
        f"{nombre} debe leer el contrato compartido antes que nada"
    )


@pytest.mark.parametrize("nombre", FAMILIA)
def test_cada_comando_enuncia_las_cuatro_reglas(nombre: str):
    texto = _leer(CMD_DIR / nombre)
    for regla in ("A. Run log", "B. Never abort", "C. Unity Catalog target", "D. Known restrictions"):
        assert regla in texto, f"{nombre} no enuncia la regla {regla!r}"


@pytest.mark.parametrize("nombre", FAMILIA)
def test_ningun_comando_manda_abortar_ante_un_privilegio(nombre: str):
    """La regla B existe justamente para que el reporte no se corte en el primer muro."""
    texto = _leer(CMD_DIR / nombre)
    assert "stop and report exactly that" not in texto, (
        f"{nombre} conserva la orden de abortar que la regla B reemplaza"
    )


@pytest.mark.parametrize("nombre", FAMILIA)
def test_cada_comando_reporta_la_bitacora_al_usuario(nombre: str):
    texto = _leer(CMD_DIR / nombre)
    assert "The bitacora**: its path under" in texto, (
        f"{nombre} debe entregar la ruta y el estado final de la bitacora"
    )


@pytest.mark.parametrize("nombre", FAMILIA)
def test_el_catalogo_hardcodeado_quedo_marcado_como_valor_por_defecto(nombre: str):
    """`workspace.default` sigue apareciendo en las rutas de ejemplo, pero el
    comando tiene que decir que se resuelve en tiempo de ejecucion."""
    texto = _leer(CMD_DIR / nombre)
    if "workspace/default/chec-simulador" not in texto and "workspace.default" not in texto:
        pytest.skip("este comando no menciona el destino UC")
    assert "is a default, not a requirement" in texto, (
        f"{nombre} usa el catalogo literal sin marcarlo como valor por defecto"
    )


def test_el_contrato_cubre_las_restricciones_ya_vividas():
    texto = _leer(CONTRATO)
    for ident in [f"### D{i} " for i in range(1, 10)]:
        assert ident in texto, f"falta la restriccion {ident.strip()} en el contrato"


def test_el_contrato_nombra_los_tres_estados_finales():
    texto = _leer(CONTRATO)
    for estado in ("COMPLETO", "COMPLETO CON RESTRICCIONES", "INCOMPLETO"):
        assert estado in texto


def test_el_contrato_documenta_los_estados_de_paso_que_acepta_el_script():
    """El contrato y el CLI no pueden divergir en el vocabulario de estados."""
    contrato = _leer(CONTRATO)
    script = _leer(BITACORA)
    declarados = re.search(r'ESTADOS_PASO = \(([^)]+)\)', script).group(1)
    estados = re.findall(r'"([a-z]+)"', declarados)
    assert estados, "no se pudieron leer los estados del script"
    for estado in estados:
        assert f"`{estado}`" in contrato, f"el contrato no documenta el estado {estado!r}"


def test_el_contrato_exige_abrir_la_bitacora_antes_de_preguntar():
    texto = _leer(CONTRATO)
    assert "before asking the user anything" in texto


def test_el_contrato_conserva_las_tres_unicas_causas_de_parada():
    texto = _leer(CONTRATO)
    assert "expired OAuth token" in texto
    assert "explicit instruction from the user to stop" in texto
    assert "destructive action" in texto


def test_el_contrato_exige_una_sola_bitacora_al_delegar():
    """Una corrida que abre cinco apps no puede dejar seis reportes parciales."""
    texto = _leer(CONTRATO)
    assert "A1." in texto
    assert "Only the outermost command calls" in texto


# --------------------------------------------------------------------------
# El orquestador /subir-a-databricks
# --------------------------------------------------------------------------

ORQUESTADOR = CMD_DIR / "subir-a-databricks.md"

APPS_POR_PRIORIDAD = [
    ("01", "/app-vano-clima", "vano-clima"),
    ("02", "/app-agrupamiento-vanos-circuitos", "agrupamiento-circuitos"),
    ("06", "/app-simulador-vano", "simulador-vano"),
    ("03", "/app-trayectorias-circuitos", "trayectorias-circuitos"),
    ("04", "/app-trayectorias-vanos", "trayectorias-vanos"),
]


def test_el_orquestador_verifica_los_datos_antes_de_subirlos():
    texto = _leer(ORQUESTADOR)
    assert "Are the data in the Volume? Upload only if not" in texto
    assert "/subir-datos-databricks" in texto


def test_el_orquestador_sube_el_05_como_cuaderno_y_no_como_app():
    texto = _leer(ORQUESTADOR)
    assert "as a notebook, not an app" in texto
    assert "05_mil_vano_ventana" in texto


def test_el_05_no_aparece_en_la_tabla_de_apps():
    """El 05 es la unica excepcion deliberada: no se publica como app."""
    texto = _leer(ORQUESTADOR)
    inicio = texto.index("| Prioridad | Cuaderno |")
    tabla = texto[inicio : texto.index("\n\n", inicio)]
    assert "05" not in tabla, "el 05 no debe estar entre las apps"


@pytest.mark.parametrize("cuaderno,comando,defecto", APPS_POR_PRIORIDAD)
def test_cada_app_esta_en_la_tabla_de_prioridad(cuaderno, comando, defecto):
    texto = _leer(ORQUESTADOR)
    inicio = texto.index("| Prioridad | Cuaderno |")
    tabla = texto[inicio : texto.index("\n\n", inicio)]
    assert comando in tabla, f"falta {comando} en la tabla de prioridad"
    assert defecto in tabla, f"falta el nombre por defecto {defecto}"


def test_las_tres_primeras_apps_son_01_02_y_06():
    """La regla del usuario: con cupo de solo 3, van 01, 02 y 06."""
    texto = _leer(ORQUESTADOR)
    inicio = texto.index("| Prioridad | Cuaderno |")
    tabla = texto[inicio : texto.index("\n\n", inicio)]
    orden = [c for c, _, _ in APPS_POR_PRIORIDAD]
    posiciones = [tabla.index(f"| {i} |") for i in range(1, 6)]
    assert posiciones == sorted(posiciones), "la tabla debe ir en orden de prioridad"
    corte = tabla.index("corte del cupo de 3")
    for cuaderno in ("vano-clima", "agrupamiento-circuitos", "simulador-vano"):
        assert tabla.index(cuaderno) < corte, f"{cuaderno} debe ir antes del corte de 3"
    for cuaderno in ("trayectorias-circuitos", "trayectorias-vanos"):
        assert tabla.index(cuaderno) > corte, f"{cuaderno} debe ir despues del corte de 3"
    assert orden[:3] == ["01", "02", "06"]


def test_el_cupo_se_descubre_no_se_asume():
    texto = _leer(ORQUESTADOR)
    assert "Do not look for a quota API" in texto
    assert "has reached the maximum limit of N apps" in texto


def test_el_cupo_agotado_no_detiene_el_comando():
    texto = _leer(ORQUESTADOR)
    assert "Stop creating new apps, but do not stop the command" in texto


def test_borrar_una_app_para_hacer_cupo_se_pregunta():
    texto = _leer(ORQUESTADOR)
    assert "destructive" in texto and "ask the user first" in texto


def test_el_orquestador_cierra_con_commit_y_push():
    texto = _leer(ORQUESTADOR)
    assert "## 6. Commit and push" in texto
    assert "git push" in texto


def test_el_commit_no_toca_main_ni_lleva_atribucion():
    """Dos reglas permanentes del usuario, faciles de perder en una reescritura."""
    texto = _leer(ORQUESTADOR)
    assert "Never commit to `main` directly" in texto
    assert "git checkout -b" in texto
    assert "no AI attribution" in texto
    assert "Co-Authored-By" in texto


def test_el_push_intenta_primero_el_plano_y_conoce_el_bloqueo_de_lfs():
    assert "D10" in _leer(ORQUESTADOR)
    contrato = _leer(CONTRATO)
    assert "Always try the plain `git push` first" in contrato
    assert "locksverify" in contrato


def test_el_orquestador_no_reabre_la_bitacora_de_los_delegados():
    texto = _leer(ORQUESTADOR)
    assert "A1" in texto
    assert "$RUTA_BITACORA" in texto


RETIRADOS = [
    CMD_DIR / "deploy-databricks-dashboard.md",
    PROJECT_ROOT / "notebooks" / "databricks",
]


@pytest.mark.parametrize("ruta", RETIRADOS, ids=lambda r: r.name)
def test_el_stack_lakeview_quedo_borrado(ruta: Path):
    """El dashboard Lakeview y el job de tablas se retiraron por completo."""
    assert not ruta.exists(), f"{ruta} debio borrarse con el stack de Lakeview"


@pytest.mark.parametrize("nombre", FAMILIA)
def test_ningun_comando_referencia_el_comando_borrado(nombre: str):
    """Media familia delegaba en sus secciones 1 y 2; ahora viven en el contrato."""
    texto = _leer(CMD_DIR / nombre)
    assert "deploy-databricks-dashboard.md" not in texto, (
        f"{nombre} apunta a un comando que ya no existe"
    )


def test_el_perfil_y_el_warehouse_sobrevivieron_en_el_contrato():
    """Lo unico del comando borrado que la familia todavia necesitaba."""
    texto = _leer(CONTRATO)
    assert "### E1. CLI profile" in texto
    assert "databricks auth profiles" in texto
    assert "### E2. SQL warehouse" in texto
    assert "databricks warehouses list" in texto


def test_el_orquestador_dice_que_el_stack_se_retiro():
    texto = _leer(ORQUESTADOR)
    assert "Retired, not deferred" in texto
    assert "Appendix (optional)" not in texto
