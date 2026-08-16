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

# La familia entera. Eran ocho hasta agosto de 2026; cinco se retiraron a la vez
# (`sdd/retire-base-apps-notebooks`, fase 5) y no por limpieza:
#
#   * `/app-vano-clima`, `/app-agrupamiento-vanos-circuitos`,
#     `/app-trayectorias-circuitos` y `/app-trayectorias-vanos` publicaban un tablero
#     cada uno parcheando su `.ipynb` por contenido. Ese codigo se fue a
#     `src/chec_tableros/` y los cuadernos se borraron: los cuatro apuntaban a archivos
#     que ya no existen. `/app-criticidad-chec` los reemplaza con UNA app de cuatro
#     rutas, que ademas gasta un cupo en vez de cuatro contra un tope de tres.
#   * `/subir-notebooks-databricks` subia seis cuadernos y quedo uno. Su procedimiento
#     -- que sigue siendo correcto -- se absorbio en el paso 4 de `/subir-a-databricks`.
FAMILIA = (
    "app-criticidad-chec.md",
    "app-simulador-vano.md",
    "subir-a-databricks.md",
    "subir-datos-databricks.md",
)

RETIRADOS = (
    "app-agrupamiento-vanos-circuitos.md",
    "app-trayectorias-circuitos.md",
    "app-trayectorias-vanos.md",
    "app-vano-clima.md",
    "subir-notebooks-databricks.md",
)


@pytest.mark.parametrize("nombre", RETIRADOS)
def test_los_comandos_retirados_no_volvieron(nombre: str):
    """Un comando que publica parcheando un cuaderno inexistente no falla: publica un
    tablero vacio. Se borran en vez de dejarlos con un aviso, porque un aviso en la
    cabecera no impide que alguien invoque el comando."""
    assert not (CMD_DIR / nombre).exists()


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
def test_cada_comando_nombra_el_rango_completo_de_restricciones(nombre: str):
    """Los cuatro decian "D1–D9" mucho despues de que el contrato llegara a D10.

    No es cosmetico: la cabecera es lo unico que dice cuantas restricciones ya
    diagnosticadas hay, y un comando que anuncia nueve invita a re-diagnosticar la
    decima -- que es `git push` fallando por la API de locking de LFS, justo lo que
    el paso final de `/subir-a-databricks` hace.
    """
    texto = _leer(CMD_DIR / nombre)
    ultima = max(int(m) for m in re.findall(r"^### D(\d+) ", _leer(CONTRATO), re.M))
    assert f"D1–D{ultima}" in texto, (
        f"{nombre} anuncia un rango de restricciones que no llega a D{ultima}")


@pytest.mark.parametrize("nombre", FAMILIA)
def test_cada_comando_enuncia_las_cuatro_reglas(nombre: str):
    texto = _leer(CMD_DIR / nombre)
    for regla in ("A. Run log", "B. Never abort", "C. Destination", "D. Known restrictions"):
        assert regla in texto, f"{nombre} no enuncia la regla {regla!r}"


@pytest.mark.parametrize("nombre", FAMILIA)
def test_cada_comando_pregunta_el_workspace_en_cada_corrida(nombre: str):
    """El destino se PREGUNTA; el perfil se DERIVA de el.

    Equivocarse de workspace no se ve: el otro tambien autentica, tambien crea el
    Volume y tambien publica una app que contesta. El usuario se entera cuando alguien
    abre una URL que no tiene sus datos.

    Y la tentacion es concreta: en esta maquina hay cinco perfiles configurados, y
    `databricks auth profiles` dice cual se puede alcanzar -- no cual quiere el usuario.
    """
    texto = _leer(CMD_DIR / nombre)
    assert "workspace URL is asked on every run" in texto, (
        f"{nombre} no dice que el workspace se pregunta en cada corrida")
    assert "never inferred from a profile" in texto, (
        f"{nombre} no prohibe deducir el workspace de un perfil con sesion vigente")
    # Y no solo en la cabecera heredada: el paso que lo pregunta tiene que decirlo,
    # porque es el que alguien lee cuando esta ejecutando el comando.
    assert "Ask it **every run** (contract C0)" in texto, (
        f"{nombre} no lo repite donde de verdad se pregunta el workspace")


def test_el_contrato_explica_por_que_el_workspace_se_pregunta_y_el_perfil_no():
    """La regla sin su motivo es una regla que alguien optimiza el dia que estorba."""
    texto = _leer(CONTRATO)
    assert "### C0. The workspace URL is ASKED, every run" in texto
    assert "### C1. The Unity Catalog target is DISCOVERED" in texto
    # El motivo, que es lo que la hace defendible: la asimetria del error.
    assert "look identical from here" in texto
    # Y la otra mitad: el perfil se deriva, no se pregunta.
    assert "derived** from the URL and never asked" in texto


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

LAS_DOS_APPS = [
    ("/app-criticidad-chec", "criticidad-chec"),
    ("/app-simulador-vano", "simulador-vano"),
]

# Los tres artefactos que suben, y nada mas. Es el contrato entero de este comando
# desde agosto de 2026, y sustituye a "seis cuadernos y cinco apps".
ARTEFACTOS = ("data/", "notebooks/05_mil_vano_ventana.ipynb", "dos aplicaciones")


def test_el_orquestador_verifica_los_datos_antes_de_subirlos():
    texto = _leer(ORQUESTADOR)
    assert "Are the data in the Volume? Upload only if not" in texto
    assert "/subir-datos-databricks" in texto


def test_el_orquestador_sube_el_05_como_cuaderno_y_no_como_app():
    texto = _leer(ORQUESTADOR)
    assert "as a notebook, not an app" in texto
    assert "05_mil_vano_ventana" in texto


@pytest.mark.parametrize("artefacto", ARTEFACTOS)
def test_el_contrato_de_tres_artefactos_esta_enunciado(artefacto: str):
    """Lo que sube y lo que no es la primera pregunta de quien lee este comando."""
    texto = _leer(ORQUESTADOR)
    assert "Tres artefactos" in texto
    assert artefacto in texto


def test_el_orquestador_absorbio_la_subida_del_cuaderno():
    """`/subir-notebooks-databricks` se retiro, y su procedimiento no podia irse con el.

    Las tres cosas que aquel comando sabia y que un `workspace import` a secas pierde:
    el limite de 10 MB de `--format JUPYTER`, que los directorios padre no se crean
    solos, y que la copia que se sube es una COPIA.
    """
    texto = _leer(ORQUESTADOR)
    paso4 = texto.split("## 4.")[1].split("## 5.")[0]

    # Se busca la DELEGACION, no la mencion. El paso explica que antes delegaba y por
    # que dejo de hacerlo, y esa explicacion es justo lo que hay que conservar: prohibir
    # el nombre empujaria a borrarla. Es el mismo criterio que ya gobierna las pruebas
    # sobre el codigo migrado.
    assert "Delegate to `/subir-notebooks-databricks`" not in paso4, (
        "el paso 4 sigue delegando en un comando retirado")
    for saber in ("10 MB", "mkdirs", "COPY in the scratch directory"):
        assert saber in texto, f"el paso 4 perdio lo que sabia sobre {saber!r}"


@pytest.mark.parametrize("comando,defecto", LAS_DOS_APPS)
def test_cada_app_esta_en_la_tabla(comando: str, defecto: str):
    texto = _leer(ORQUESTADOR)
    inicio = texto.index("| # | Comando |")
    tabla = texto[inicio : texto.index("\n\n", inicio)]
    assert comando in tabla, f"falta {comando} en la tabla de apps"
    assert defecto in tabla, f"falta el nombre por defecto {defecto}"


def test_ya_no_hay_tabla_de_prioridad_porque_las_dos_caben():
    """Eran cinco apps contra un cupo de tres, y cual entraba era una decision que
    este comando tomaba en cada corrida. Con dos, el cupo deja de decidir nada.

    Se afirma la AUSENCIA porque una tabla de prioridad que sobrevive a su motivo es
    peor que inutil: hace pensar que hay una eleccion que hacer.
    """
    texto = _leer(ORQUESTADOR)
    assert "| Prioridad | Cuaderno |" not in texto
    assert "corte del cupo de 3" not in texto
    assert "no hace falta" in texto.lower()


def test_el_cupo_se_descubre_no_se_asume():
    """Sigue valiendo aunque hoy las dos quepan: el tope es del workspace, no nuestro,
    y otro workspace puede tener uno mas bajo o apps ajenas ocupandolo."""
    texto = _leer(ORQUESTADOR)
    assert "there is no quota API" in texto
    assert "has reached the maximum limit of N apps" in texto


def test_el_relevo_de_las_cuatro_apps_viejas_se_pregunta():
    """Publicar la nueva no autoriza borrar las que reemplaza. Son cuatro apps que
    alguien puede tener abiertas, y borrarlas es destructivo."""
    texto = _leer(ORQUESTADOR)
    assert "Las cuatro apps viejas" in texto
    assert "Preguntar antes de borrar cada una" in texto


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
