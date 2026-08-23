"""Static contract tests for the Databricks deployment command.

These pin the properties that were actually broken before, and that prose alone
will silently lose again on the next edit:

1. the command reads the shared contract and states the never-abort rule,
2. it does not tell the assistant to abort at the first privilege wall,
3. the shared contract still documents the restrictions met in the field,
4. each of the three stages checks Databricks BEFORE uploading anything,
5. the run log covers the three stages, one row each, whatever happened.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CMD_DIR = PROJECT_ROOT / ".claude" / "commands"
CONTRATO = CMD_DIR / "_contrato-despliegue-databricks.md"
BITACORA = PROJECT_ROOT / "scripts" / "bitacora_despliegue.py"

# La familia entera es UN comando desde 2026-08-17. Eran ocho a mediados de agosto y
# se fueron retirando por dos motivos distintos, que conviene no confundir:
#
#   * `/app-vano-clima`, `/app-agrupamiento-vanos-circuitos`,
#     `/app-trayectorias-circuitos` y `/app-trayectorias-vanos` publicaban un tablero
#     cada uno parcheando su `.ipynb` por contenido. Ese codigo se fue a
#     `src/chec_tableros/` y los cuadernos se borraron: los cuatro apuntaban a archivos
#     que ya no existen.
#   * `/subir-notebooks-databricks`, `/subir-datos-databricks`, `/app-criticidad-chec` y
#     `/app-simulador-vano` seguian siendo CORRECTOS. Se retiraron porque un despliegue
#     partido en cuatro invocaciones deja cuatro reportes parciales y obliga al usuario a
#     acordarse del orden. Su procedimiento no se perdio: vive en los pasos 3, 4 y 5 de
#     `/subir-a-databricks`, que es hoy el unico que habla con Databricks.
FAMILIA = ("subir-a-databricks.md",)

RETIRADOS = (
    "app-agrupamiento-vanos-circuitos.md",
    "app-criticidad-chec.md",
    "app-simulador-vano.md",
    "app-trayectorias-circuitos.md",
    "app-trayectorias-vanos.md",
    "app-vano-clima.md",
    "subir-datos-databricks.md",
    "subir-notebooks-databricks.md",
)


@pytest.mark.parametrize("nombre", RETIRADOS)
def test_los_comandos_retirados_no_volvieron(nombre: str):
    """Se borran en vez de dejarlos con un aviso, porque un aviso en la cabecera no
    impide que alguien invoque el comando."""
    assert not (CMD_DIR / nombre).exists()


def _leer(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_el_contrato_compartido_existe():
    assert CONTRATO.exists(), "el contrato compartido es la referencia del comando"


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
    """Decia "D1–D9" mucho despues de que el contrato llegara a D10.

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
    """Una corrida que abre dos apps no puede dejar tres reportes parciales."""
    texto = _leer(CONTRATO)
    assert "A1." in texto
    assert "Only the outermost command calls" in texto


# --------------------------------------------------------------------------
# El comando unico /subir-a-databricks
# --------------------------------------------------------------------------

ORQUESTADOR = CMD_DIR / "subir-a-databricks.md"

LAS_DOS_APPS = ("criticidad-chec", "simulador-vano")

# Los tres artefactos que suben, y nada mas. Es el contrato entero de este comando.
ARTEFACTOS = ("data/", "notebooks/05_mil_vano_ventana.ipynb", "dos aplicaciones")

# Las tres etapas, en el orden en que el comando las recorre, con el encabezado que
# cada una tiene que llevar. El encabezado NO es decoracion: enuncia la compuerta.
ETAPAS = (
    ("3", "Are the data in the Volume? Upload only if not"),
    ("4", "Are the apps deployed and serving? Deploy only if not"),
    ("5", "Is the notebook in the Workspace? Import only if not"),
)


@pytest.mark.parametrize("numero,titulo", ETAPAS, ids=[t[0] for t in ETAPAS])
def test_cada_etapa_verifica_databricks_antes_de_subir(numero: str, titulo: str):
    """La compuerta esta en el TITULO del paso y no enterrada en su prosa.

    Sin ella el comando vuelve a subir 566 MB para descubrir que ya estaban, y a
    redesplegar una app sana -- que en el simulador son diez minutos de `pip install
    torch` a cambio de nada.
    """
    texto = _leer(ORQUESTADOR)
    assert f"## {numero}. {titulo}" in texto, (
        f"el paso {numero} perdio su compuerta de verificacion en el titulo")


@pytest.mark.parametrize("numero,titulo", ETAPAS, ids=[t[0] for t in ETAPAS])
def test_cada_etapa_dice_que_hacer_en_los_dos_casos(numero: str, titulo: str):
    """Una compuerta que solo dice que hacer cuando falta algo se lee como una orden
    de subir siempre."""
    texto = _leer(ORQUESTADOR)
    inicio = texto.index(f"## {numero}. {titulo}")
    fin = texto.index("\n## ", inicio + 1)
    etapa = texto[inicio:fin]
    assert "**Read-only check first" in etapa, (
        f"el paso {numero} no empieza por la comprobacion de solo lectura")
    assert "**If everything is present**" in etapa, (
        f"el paso {numero} no dice que hacer cuando ya esta todo en Databricks")
    assert "**If anything is missing**" in etapa, (
        f"el paso {numero} no dice que hacer cuando falta algo")


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
    for saber in ("10 MB", "mkdirs", "COPY in the scratch directory"):
        assert saber in texto, f"el paso del cuaderno perdio lo que sabia sobre {saber!r}"


def test_el_orquestador_absorbio_la_subida_de_los_datos():
    """`/subir-datos-databricks` se retiro el 2026-08-17. Lo que sabia y que un
    `fs cp -r data` a secas pierde: que el CLI no tiene filtro de exclusion y arrastra
    `.DS_Store`, que `site/data/variables.json` es la unica excepcion fuera de `data/`,
    y que un CSV de 130 bytes es un puntero de Git LFS sin traer."""
    texto = _leer(ORQUESTADOR)
    for saber in (
        "databricks fs cp -r data",
        ".DS_Store",
        "site/data/variables.json",
        "git lfs pull",
    ):
        assert saber in texto, f"el paso de los datos perdio lo que sabia sobre {saber!r}"


def test_el_orquestador_absorbio_el_despliegue_de_las_dos_apps():
    """`/app-criticidad-chec` y `/app-simulador-vano` se retiraron el 2026-08-17.

    Lo que sabian y que no se puede re-derivar leyendo el codigo: que los paneles y el
    paquete se construyen AQUI con el mismo constructor que corre la aplicacion de
    escritorio -- nunca ejecutando celdas ni parcheando un cuaderno --, que el cuaderno
    servido va sin boton de cerrar, y que el permiso del Volume se declara como recurso
    de la app en vez de otorgarse a mano.
    """
    texto = _leer(ORQUESTADOR)
    for saber in (
        "scripts/empacar_app_databricks.py paneles",
        "scripts/empacar_app_databricks.py fuente",
        "aplicaciones/06_simulador/construir.py",
        "con_cierre=False",
        "uc_securable",
    ):
        assert saber in texto, f"el despliegue perdio lo que sabia sobre {saber!r}"


@pytest.mark.parametrize("defecto", LAS_DOS_APPS)
def test_cada_app_esta_en_la_tabla(defecto: str):
    texto = _leer(ORQUESTADOR)
    inicio = texto.index("| # | App |")
    tabla = texto[inicio : texto.index("\n\n", inicio)]
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


def test_el_relevo_de_las_apps_viejas_se_pregunta():
    """Publicar la nueva no autoriza borrar las que reemplaza. Son apps que alguien
    puede tener abiertas, y borrarlas es destructivo.

    Se llamaban "las cuatro apps viejas" hasta el 2026-08-19. Dejaron de ser cuatro
    cuando se descubrio que cada comando de la familia bautizaba su app a su manera:
    la lista lleva los dos juegos de nombres, con y sin el prefijo `app-`.
    """
    texto = _leer(ORQUESTADOR)
    assert "Las apps de la familia retirada" in texto
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


# --------------------------------------------------------------------------
# La bitacora: una fila por etapa, pasara lo que pasara
# --------------------------------------------------------------------------


def test_la_bitacora_es_lo_primero_que_se_abre():
    """Antes de la primera pregunta: una corrida que muere en el paso 0 tambien deja
    documento."""
    texto = _leer(ORQUESTADOR)
    assert "bitacora_despliegue.py init" in texto
    assert "$RUTA_BITACORA" in texto


@pytest.mark.parametrize("numero,titulo", ETAPAS, ids=[t[0] for t in ETAPAS])
def test_cada_etapa_deja_su_paso_en_la_bitacora(numero: str, titulo: str):
    """El pedido entero de este comando es un reporte que diga, etapa por etapa, si
    pudo o que lo bloqueo. Una etapa que no escribe su paso desaparece del documento y
    se lee como si no hubiera hecho falta."""
    texto = _leer(ORQUESTADOR)
    inicio = texto.index(f"## {numero}. {titulo}")
    fin = texto.index("\n## ", inicio + 1)
    etapa = texto[inicio:fin]
    assert "bitacora_despliegue.py paso" in etapa, (
        f"el paso {numero} no registra su resultado en la bitacora")


def test_el_reporte_lleva_una_fila_por_etapa():
    texto = _leer(ORQUESTADOR)
    assert "one row per stage" in texto, (
        "el reporte final tiene que resumir las tres etapas, cada una con su estado")


def test_la_bitacora_registra_las_restricciones_con_quien_desbloquea():
    """Un muro de permisos anotado sin decir quien lo levanta obliga al usuario a
    volver a diagnosticarlo."""
    texto = _leer(ORQUESTADOR)
    assert "bitacora_despliegue.py restriccion" in texto
    assert "--quien-desbloquea" in texto


def test_una_etapa_bloqueada_no_detiene_las_otras():
    """Es la regla B aplicada a la forma concreta de este comando: el valor de la
    corrida esta en salir con la lista COMPLETA de muros, no con el primero."""
    texto = _leer(ORQUESTADOR)
    assert "The never-abort rule matters more here than anywhere else" in texto


RETIRADOS_STACK = [
    CMD_DIR / "deploy-databricks-dashboard.md",
    PROJECT_ROOT / "notebooks" / "databricks",
]


@pytest.mark.parametrize("ruta", RETIRADOS_STACK, ids=lambda r: r.name)
def test_el_stack_lakeview_quedo_borrado(ruta: Path):
    """El dashboard Lakeview y el job de tablas se retiraron por completo."""
    assert not ruta.exists(), f"{ruta} debio borrarse con el stack de Lakeview"


DELEGACIONES_MUERTAS = (
    "Delegate to `/subir-datos-databricks`",
    "Delegate to `/subir-notebooks-databricks`",
    "delegate to `/subir-datos-databricks`",
    "deploy-databricks-dashboard.md",
)


@pytest.mark.parametrize("delegacion", DELEGACIONES_MUERTAS)
def test_el_comando_no_delega_en_nada_que_ya_no_existe(delegacion: str):
    """Se busca la DELEGACION, no la mencion.

    La prosa explica que estos comandos existieron y por que se absorbieron, y esa
    explicacion es justo lo que hay que conservar: prohibir el nombre empujaria a
    borrarla. Es el mismo criterio que gobierna las pruebas sobre el codigo migrado.
    """
    assert delegacion not in _leer(ORQUESTADOR), (
        f"el comando sigue delegando en algo retirado: {delegacion!r}")


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


# --------------------------------------------------------------------------
# Lo que la corrida real del 2026-08-19 dejo al descubierto
# --------------------------------------------------------------------------
#
# Tres hallazgos, y ninguno era un fallo de Databricks:
#
#   1. La etapa 3 reporto `data/derived/bolsas_mil_full.joblib` como "no existe en
#      esta maquina". Existe: 198.945.074 bytes, del 2026-08-03. Lo que pasa es que
#      `data/derived/` esta en `.gitignore` -- la linea `data/*` sin un `!` que lo
#      rescate --, asi que `git ls-files` y cualquier herramienta que respete el
#      gitignore lo dan por ausente. El inventario de la etapa 3 no lo nombraba, asi
#      que nada contradijo esa lectura.
#   2. El relevo de apps viejas solo reconocia `vano-clima`, sin prefijo. El
#      workspace tenia `app-clima`, que es la misma app de la familia retirada, y al
#      no reconocerla la conto como ajena: cupo ocupado por algo nuestro.
#   3. Con un solo cupo libre para dos apps, el comando decia que "esa asimetria
#      decide cual" y no decia cual. Sin desempate escrito, la corrida no desplego
#      ninguna.

RUTA_BOLSAS = "data/derived/bolsas_mil_full.joblib"


def _etapa(numero: str, titulo: str) -> str:
    """El texto de una etapa, de su encabezado al de la siguiente."""
    texto = _leer(ORQUESTADOR)
    inicio = texto.index(f"## {numero}. {titulo}")
    return texto[inicio : texto.index("\n## ", inicio + 1)]


def test_la_etapa_3_nombra_el_cache_de_bolsas_en_su_inventario():
    """El inventario decia "el CSV, los sidecars, graphs/, models/ y los dos .xlsx" y
    se saltaba `derived/`. `fs cp -r data` SI lo lleva, pero quien lee el inventario
    para saber que sube concluye lo contrario -- y eso fue exactamente lo que paso.
    """
    etapa = _etapa("3", "Are the data in the Volume? Upload only if not")
    assert RUTA_BOLSAS in etapa, (
        "la etapa 3 no nombra el cache de bolsas; su inventario dice que sube y ese "
        "archivo no aparece, aunque `fs cp -r data` lo lleve")


def test_la_etapa_3_verifica_el_cache_de_bolsas_por_tamanio():
    """Con el mismo criterio que el CSV: un joblib truncado no falla al subir, falla
    dentro del simulador con un error que no apunta aqui."""
    etapa = _etapa("3", "Are the data in the Volume? Upload only if not")
    assert "data/derived" in etapa
    assert "199 MB" in etapa or "198.945.074" in etapa, (
        "la etapa 3 no dice cuanto debe pesar el cache de bolsas, asi que no puede "
        "distinguir uno completo de uno truncado")


def test_la_etapa_3_avisa_del_puntero_lfs_del_cache_de_bolsas():
    """El cache de bolsas se versiono el 2026-08-19 -- la subida se hace clonando este
    repo en otra maquina --, y al entrar a LFS hereda exactamente la trampa del CSV:
    un clon sin `git lfs pull` deja 134 bytes que parecen el archivo.

    La trampa anterior era la contraria y ya no aplica: estaba en `.gitignore`, asi que
    git lo daba por inexistente aunque estuviera en el disco. Se conserva contada en la
    misma nota, porque explica por que la etapa lo verifica.
    """
    etapa = _etapa("3", "Are the data in the Volume? Upload only if not")
    assert "git lfs pull" in etapa, (
        "la etapa 3 no dice como recuperar el cache de bolsas cuando el clon solo trajo "
        "su puntero de LFS")
    assert "134 bytes" in etapa, (
        "la etapa 3 no dice cuanto mide el puntero, que es como se distingue de un "
        "archivo truncado")


def test_la_etapa_5_no_le_exige_al_cuaderno_las_bolsas():
    """El cuaderno 05 no nombra `bolsas_mil_full` ni una vez: las produce al entrenar y
    las consumen el simulador y el agente `inference`, no el.

    Se fija porque esa confusion ya costo un `degradado` con un motivo falso.
    """
    etapa = _etapa("5", "Is the notebook in the Workspace? Import only if not")
    assert "No necesita `data/derived/bolsas_mil_full.joblib`" in etapa, (
        "la etapa 5 no desmiente que el cuaderno necesite las bolsas")


def test_las_dos_apps_se_despliegan_siempre():
    """No hay corrida en la que desplegar las apps sea opcional.

    En la corrida del 2026-08-19 la etapa 4 salio `omitido` con las dos apps sin
    desplegar. Lo que decide que se despliega es el cupo y el estado de cada app, no
    una eleccion por corrida.
    """
    etapa = _etapa("4", "Are the apps deployed and serving? Deploy only if not")
    assert "Las dos se despliegan siempre, por defecto" in etapa, (
        "la etapa 4 no enuncia que las dos apps se despliegan por defecto")
    assert "opcional" in etapa, (
        "la etapa 4 no dice que publicarlas NO es opcional ni una pregunta al usuario")


@pytest.mark.parametrize("nombre", ["app-clima", "app-vano-clima", "app-simulador-vano"])
def test_el_relevo_reconoce_los_nombres_con_prefijo(nombre: str):
    """La familia retirada dejo apps con y sin el prefijo `app-`, segun el comando que
    las creo. Reconocer solo una forma cuenta a la otra como ajena y le regala cupo.
    """
    etapa = _etapa("4", "Are the apps deployed and serving? Deploy only if not")
    assert nombre in etapa, (
        f"la etapa 4 no reconoce `{nombre}` como app de la familia retirada, asi que "
        "la contaria como ajena y no ofreceria retirarla")


def test_con_un_solo_cupo_hay_un_desempate_escrito():
    """Decir "esa asimetria decide cual" sin decir cual no es un desempate.

    Con un solo cupo libre la corrida no desplego NINGUNA de las dos, que es el peor
    de los tres resultados posibles.
    """
    etapa = _etapa("4", "Are the apps deployed and serving? Deploy only if not")
    inicio = etapa.lower().index("un solo cupo") if "un solo cupo" in etapa.lower() else -1
    assert inicio >= 0, "la etapa 4 no contempla el caso de un solo cupo libre"
    ventana = etapa[inicio : inicio + 600]
    assert "criticidad-chec" in ventana, (
        "el desempate no nombra cual de las dos apps entra primero")


def test_la_etapa_5_sincroniza_el_paquete_junto_al_cuaderno():
    """El cuaderno importa `chec_impacto` y en el Workspace no hay `src/` a menos que
    alguien lo ponga. Estaba solo en el paso 4c, a la carpeta de la app del simulador:
    otra ruta, y ninguna si el cupo dejaba al simulador fuera.

    Va en la etapa 5 y no en la 4 porque es una dependencia del CUADERNO.
    """
    etapa = _etapa("5", "Is the notebook in the Workspace? Import only if not")
    assert "databricks sync src/chec_impacto" in etapa, (
        "la etapa 5 no sincroniza el paquete junto al cuaderno")
    assert "project_flow/src/chec_impacto" in etapa, (
        "el paquete no se sincroniza en la MISMA carpeta que el cuaderno")


def test_la_etapa_5_apunta_los_datos_al_volume():
    """Codigo y datos no son el mismo sitio en el Workspace, asi que la ruta de los
    datos hay que decirla. Sin eso el cuaderno busca `<raiz>/data`, que alli no existe.
    """
    etapa = _etapa("5", "Is the notebook in the Workspace? Import only if not")
    assert "CHEC_DATA_DIR" in etapa, (
        "la etapa 5 no dice como apuntar los datos al Volume")
    assert "D2" in etapa, (
        "la etapa 5 no contempla el 403 del montaje FUSE, que es cuando esa misma "
        "variable tiene que apuntar a un directorio local")


# ---------------------------------------------------------------------------
# Lo que el comando manda subir tiene que EXISTIR
# ---------------------------------------------------------------------------
#
# La etapa 4c mandaba subir `arranque.py`, `app.yaml` y `requirements.txt` del
# simulador con `--file <scratch>/...`. Los tres vivian dentro de
# `/app-simulador-vano.md` como bloques de codigo; al fundir los cuatro comandos en
# uno (commit `1c0aa56`) se fueron con el `.md` y las lineas que los suben se
# quedaron. Desde entonces esa etapa no se podia ejecutar, y nada lo decia: un `.md`
# no tiene quien le pregunte si el archivo que nombra existe.


def _archivos_que_el_comando_sube() -> set[str]:
    """Los nombres CONCRETOS que aparecen tras `--file <scratch>/`, sin ruta.

    Se dejan fuera dos formas que no son un archivo: `$f`, la variable del bucle de la
    etapa 4b -- sus valores se enumeran en la misma linea y los cubre
    `tests/test_app_criticidad_chec.py` --, y cualquier marcador de prosa como `X`.
    Un nombre de archivo aqui es algo con extension y sin metacaracteres de shell.
    """
    texto = (CMD_DIR / "subir-a-databricks.md").read_text(encoding="utf-8")
    crudos = re.findall(r"--file\s+<scratch>/(\S+)", texto)
    return {Path(c).name for c in crudos
            if re.fullmatch(r"[A-Za-z0-9._/-]+\.[A-Za-z0-9]+", c)}


def test_todo_lo_que_la_etapa_4_sube_lo_escribe_algo_del_repositorio():
    """Cada `--file <scratch>/X` tiene que tener un productor con nombre.

    Los productores son dos y estan escritos, no adivinados: los subcomandos de
    `scripts/empacar_app_databricks.py` para la fuente de las dos apps, y
    `preparar.escribir_cuaderno(con_cierre=False)` para el cuaderno del simulador.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "empacar_para_contrato", PROJECT_ROOT / "scripts" / "empacar_app_databricks.py")
    empacador = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(empacador)

    producidos = set(empacador.ARCHIVOS_PROPIOS) | set(empacador.ARCHIVOS_COMPARTIDOS) \
        | set(empacador.ARCHIVOS_SIMULADOR) | {"06_simulador.ipynb"}
    huerfanos = sorted(_archivos_que_el_comando_sube() - producidos)
    assert not huerfanos, (
        f"el comando manda subir {huerfanos} y nada del repositorio los escribe")


@pytest.mark.parametrize("nombre", ["arranque.py", "app.yaml", "requirements.txt"])
def test_la_fuente_del_simulador_existe_como_archivo(nombre: str):
    """Y en una carpeta, no dentro de un Markdown: es la unica forma de que las
    pruebas la vean."""
    assert (PROJECT_ROOT / "aplicaciones" / "databricks" / "simulador" / nombre).is_file()


def test_la_etapa_4c_prepara_su_fuente_con_el_empacador():
    """Y no copiando bloques de codigo desde este mismo archivo, que es como se
    perdieron."""
    texto = (CMD_DIR / "subir-a-databricks.md").read_text(encoding="utf-8")
    etapa = texto[texto.index("### 4c."):texto.index("### 4d.")]
    assert "empacar_app_databricks.py fuente-simulador" in etapa, (
        "la etapa 4c no dice de donde sale la fuente de la app del simulador")
    assert "--volumen-paquete" in etapa, (
        "la etapa 4c no resuelve la ruta del Volume del paquete; sin eso la app "
        "arranca buscandolo en `workspace.default`, que en CHEC no existe (D1)")


# ---------------------------------------------------------------------------
# El inventario de la etapa 3 no puede nombrar lo que no existe
# ---------------------------------------------------------------------------


def test_el_inventario_de_la_etapa_3_no_nombra_archivos_inexistentes():
    """La fila `graphs/*.npy` describia "el grafo de restriccion fisica" y no hay ni un
    `.npy` en todo `data/`: el grafo experto se CONSTRUYE en codigo
    (`construir_matriz_adyacencia_mgcecdl`) y viaja dentro del `.pt`.

    Es el error simetrico del que costo la corrida del 2026-08-19. Alli el inventario se
    saltaba `derived/` y quien lo leyo concluyo que no subia; aqui nombra algo que no
    esta, y quien lo comprueba reporta un hueco que no existe. Un inventario miente en
    los dos sentidos.
    """
    etapa = _etapa("3", "Are the data in the Volume? Upload only if not")
    # Solo las FILAS de la tabla de inventario, no la prosa: explicar por que `*.npy` no
    # esta exige nombrarlo, y prohibir la palabra prohibe tambien explicarla. Una fila
    # es `| \`ruta\` | que es | peso |`.
    filas = re.findall(r"^\|\s*`([^`]+)`\s*\|", etapa, re.M)
    for ruta in filas:
        if not ruta.startswith(("graphs/", "models/", "derived/", "GEO/")):
            continue
        # `GEO/*.{shp,shx,dbf,prj}` es notacion legitima y `glob` no la entiende: se
        # expanden las llaves a un patron por extension y basta con que UNA acierte.
        llaves = re.search(r"\{([^}]+)\}", ruta)
        patrones = ([ruta.replace(llaves.group(0), alternativa)
                     for alternativa in llaves.group(1).split(",")]
                    if llaves else [ruta])
        encontrados = [f for patron in patrones
                       for f in (PROJECT_ROOT / "data").glob(patron)]
        assert encontrados, (
            f"el inventario de la etapa 3 nombra `{ruta}` y no existe ningun archivo "
            "asi bajo data/")


# ---------------------------------------------------------------------------
# El cuaderno necesita un computo que traiga torch
# ---------------------------------------------------------------------------


def test_la_etapa_5_dice_sobre_que_computo_corre_el_cuaderno():
    """Aterrizar no es correr, y el comando ya lo dice para el permiso del Volume. Le
    faltaba la otra mitad: `05` importa `torch`, `scikit-learn`, `plotly`, `networkx` y
    `pyarrow`, asi que en Serverless o en un DBR estandar muere en su cuarta celda con
    `ModuleNotFoundError: torch` -- con el cuaderno perfectamente importado.

    D8 cubre el caso vecino (ipywidgets no corre en Serverless) y por eso este se leia
    como cubierto. No es el mismo: alli el problema es el widget, aqui la imagen.
    """
    etapa = _etapa("5", "Is the notebook in the Workspace? Import only if not")
    assert "torch" in etapa, (
        "la etapa 5 no dice que el cuaderno necesita torch, que es lo que decide el "
        "runtime al que hay que adjuntarlo")
    assert re.search(r"\bML\b", etapa), (
        "la etapa 5 no nombra el runtime de Databricks que trae torch instalado")


def test_la_etapa_5_no_decide_la_frescura_por_fechas_de_archivos_versionados():
    """En un clon nuevo --- que es el escenario declarado de este comando --- todos los
    archivos versionados llevan la fecha del clon, con milisegundos de diferencia entre
    ellos. Comparar la fecha del `.ipynb` con la de su generador ahi es echar una
    moneda: medido en este checkout, 0,4 ms de diferencia.
    """
    etapa = _etapa("5", "Is the notebook in the Workspace? Import only if not")
    assert "clon" in etapa.lower(), (
        "la etapa 5 no advierte que las fechas de dos archivos versionados no se pueden "
        "comparar en un clon recien hecho")


# ---------------------------------------------------------------- presente != vigente

def _etapa_de_datos() -> str:
    texto = _leer(ORQUESTADOR)
    inicio = texto.index("## 3. Are the data in the Volume?")
    return texto[inicio:texto.index("\n## ", inicio + 1)]


def test_la_etapa_de_datos_distingue_estar_de_estar_vigente():
    """La compuerta miraba nombre y tamano, y nada mas.

    Un `.pt` reentrenado se llama igual y pesa casi lo mismo que el anterior, asi que
    "esta presente" daba `ok` y la etapa se saltaba la subida: Databricks se quedaba
    con el modelo viejo mientras el local ya era otro, y las apps de la etapa 4 --
    que si se reconstruyen en cada corrida -- servian un panel nuevo sobre artefactos
    de antes. Es el mismo desajuste que `/actualizar` cierra en local.
    """
    etapa = _etapa_de_datos()
    assert "procedencia.json" in etapa, (
        "la etapa 3 no compara el sello: sin el, un artefacto reentrenado no se sube "
        "porque el anterior ya ocupaba su nombre")
    assert re.search(r"presence|presente|nombre y (el )?tama|size alone", etapa,
                     re.IGNORECASE), (
        "la etapa no dice que estar presente no es estar vigente, que es justo lo que "
        "la hacia saltarse la subida")


def test_el_sello_esta_en_el_inventario_de_lo_que_sube():
    """Un inventario que no nombra algo se lee como que ese algo no sube -- ya paso con
    `derived/`, que `fs cp -r data` siempre llevo y el inventario no nombraba."""
    assert "models/procedencia.json" in _etapa_de_datos()


def test_la_etapa_de_datos_manda_a_actualizar_cuando_el_sello_local_no_cuadra():
    """Subir un artefacto que el sello local ya da por viejo es propagar el desajuste."""
    etapa = _etapa_de_datos()
    assert "/actualizar" in etapa, (
        "sin nombrar `/actualizar`, la etapa 3 no tiene a quien mandar el caso en que "
        "lo local tampoco esta al dia consigo mismo")


# ------------------------------------------------- reentrenar SOBRE Databricks

def _etapa_de_apps() -> str:
    texto = _leer(ORQUESTADOR)
    inicio = texto.index("## 4. Are the apps deployed and serving?")
    return texto[inicio:texto.index("\n## ", inicio + 1)]


def test_el_comando_contempla_que_el_reentrenamiento_ocurra_en_databricks():
    """Las dos compuertas de vigencia miraban SOLO archivos locales.

    El cuaderno 05 con `ENTRENAR = True` corre en Databricks y escribe el `.pt` en
    `CHEC_DATA_DIR`, o sea dentro del Volume. Nada local cambia. La etapa 3 compara
    sellos -- y `procedencia.json` guarda las huellas de las ENTRADAS del modelo, no
    del modelo, asi que reentrenar sobre los mismos insumos lo deja identico -- y la
    etapa 4 compara contra la fecha del `.pt` LOCAL, que tampoco se movio. Las dos
    dicen `ok` y el simulador desplegado sigue sirviendo el modelo anterior.
    """
    texto = _leer(ORQUESTADOR)
    assert re.search(r"reentren\w+ (en|sobre) Databricks", texto, re.IGNORECASE), (
        "el comando no nombra el caso de reentrenar SOBRE Databricks; sin nombrarlo, "
        "las dos compuertas de vigencia solo miran la maquina que despliega")


def test_la_etapa_de_apps_compara_el_modelo_del_volume_contra_el_del_paquete():
    """La comparacion exacta ya es posible y es barata.

    `manifiesto.json` del paquete guarda, bajo `insumos`, el `sha1` del
    `mil_vano_ventana_v1.pt` con el que se construyo. Contrastarlo contra el `.pt`
    que vive en `data/models` del Volume responde justo la pregunta que ninguna
    compuerta hacia: el paquete desplegado, se armo con ESTE modelo?
    """
    etapa = _etapa_de_apps()
    assert "insumos" in etapa and "sha1" in etapa, (
        "la etapa 4 no compara la huella del modelo: el manifiesto del paquete ya "
        "trae `insumos[mil_vano_ventana_v1.pt][sha1]` y nadie lo mira")
    assert "data/models/mil_vano_ventana_v1.pt" in etapa, (
        "la etapa 4 no nombra el `.pt` del Volume, que es el lado que cambia cuando "
        "el reentrenamiento ocurre en Databricks")


def test_la_etapa_de_apps_dice_como_reparar_un_paquete_armado_con_otro_modelo():
    """Detectar sin decir que hacer deja al operador con un rojo y sin salida.

    El paquete se construye en la maquina que despliega (`06_simulador/construir.py`),
    asi que la reparacion tiene UN orden: bajar el `.pt` reentrenado del Volume,
    reconstruir con el, y volver a subir el paquete.
    """
    etapa = _etapa_de_apps()
    # La direccion importa: `fs cp` aparece ya varias veces en la etapa, siempre
    # SUBIENDO. Lo que falta es la bajada, y por eso se exige el origen `dbfs:` con
    # el `.pt` en el mismo comando.
    assert re.search(r"(files download|fs cp)\s+dbfs:[^\n]*mil_vano_ventana_v1\.pt",
                     etapa), (
        "la etapa 4 no dice como traer el `.pt` reentrenado del Volume a local; los "
        "`fs cp` que ya tiene van todos en la direccion contraria")
    assert "06_simulador/construir.py" in etapa, (
        "la etapa 4 no manda reconstruir el paquete con el modelo reentrenado")


def test_la_subida_de_datos_no_pisa_un_modelo_reentrenado_en_databricks():
    """`fs cp -r data --overwrite` va en la direccion contraria y no pregunta.

    Si alguien reentreno en Databricks y ademas movio un insumo local, el sello
    difiere, la etapa 3 sube `data/` entera y el `.pt` local -- mas viejo -- pisa al
    reentrenado. Se pierde el entrenamiento, y ninguna compuerta lo nota.
    """
    etapa = _etapa_de_datos()
    assert re.search(r"pisa|sobrescrib|clobber|piso", etapa, re.IGNORECASE), (
        "la etapa 3 no advierte que su `fs cp -r data --overwrite` puede pisar un "
        "modelo reentrenado en Databricks")


def test_el_chequeo_del_sello_compara_tambien_la_huella_del_modelo():
    """El sello son DOS archivos y la etapa 3 solo comparaba uno.

    `procedencia.json` guarda el sha256 de las FUENTES y los derivados;
    `manifest.sha256.json` guarda el del `.pt` mismo -- `estado_actualizacion.py` los
    lee por separado, `huella_registrada_del_modelo()` contra `CLAVE_MODELO`. El
    chequeo 6 decia "dos archivos de 400 bytes" y hacia `diff` de uno solo, asi que la
    unica huella que habria delatado un reentrenamiento hecho SOBRE Databricks era
    justo la que no se miraba.
    """
    etapa = _etapa_de_datos()
    assert "manifest.sha256.json" in etapa, (
        "el chequeo del sello ignora `manifest.sha256.json`, que es el unico de los "
        "dos que guarda la huella del modelo")


def test_la_etapa_de_apps_avisa_que_los_dos_sellos_usan_algoritmos_distintos():
    """El mismo `.pt` tiene dos huellas legitimas y distintas, y cruzarlas no cuadra nunca.

    `estado_actualizacion.huella()` es **sha256** y sella `manifest.sha256.json`;
    `huellas.py` del paquete es **sha1** y llena `insumos` del `manifiesto.json`.
    Comparar uno contra otro da "difieren" siempre, para cualquier modelo, y ese falso
    rojo manda a reconstruir un paquete que estaba bien.
    """
    etapa = _etapa_de_apps()
    assert re.search(r"sha1.*sha256|sha256.*sha1", etapa, re.DOTALL), (
        "la etapa 4 no avisa que el sello es sha256 y el manifiesto del paquete sha1; "
        "cruzarlos produce un falso 'difieren' para cualquier modelo")
