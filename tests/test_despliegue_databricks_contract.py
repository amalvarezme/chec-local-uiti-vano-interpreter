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


def test_la_etapa_3_avisa_de_que_derived_esta_en_gitignore():
    """La trampa que costo la corrida, escrita donde se cae en ella.

    No es un detalle de git: es que la pregunta "¿existe este archivo?" se contesta
    distinto segun con que herramienta se haga, y la que respeta el gitignore miente.
    """
    etapa = _etapa("3", "Are the data in the Volume? Upload only if not")
    assert ".gitignore" in etapa, (
        "la etapa 3 no avisa de que `data/derived/` esta en .gitignore, que es como "
        "un archivo de 199 MB que esta en el disco se reporta como inexistente")


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
