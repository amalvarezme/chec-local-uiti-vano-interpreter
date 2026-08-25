"""Behaviour tests for `scripts/bitacora_despliegue.py`.

The bitacora is the deployment log the `/app-*` and `/subir-*-databricks`
commands write while they run. Its contract is unusual and worth pinning:

- it must be readable **mid-run**, because the whole point is to survive a
  command that dies halfway, so every subcommand re-renders a complete
  document rather than appending fragments;
- a restriction must never look like a success, and a run that hit one must
  never close as `COMPLETO`;
- credentials that show up in captured CLI output must not reach the file.

Style follows `tests/test_experimento_kaggle_contract.py`: real subprocess
calls against the CLI, since prose alone cannot prove the renderer works.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI = PROJECT_ROOT / "scripts" / "bitacora_despliegue.py"


def _run(*args: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert proc.returncode == 0, f"fallo {args!r}:\n{proc.stdout}\n{proc.stderr}"
    return proc.stdout.strip()


@pytest.fixture()
def bitacora(tmp_path: Path) -> Path:
    destino = tmp_path / "bitacora.md"
    _run(
        "init",
        "--archivo", str(destino),
        "--comando", "/app-vano-clima",
        "--cuaderno", "notebooks/base_apps/01_uiti_vano_clima.ipynb",
        "--workspace", "https://adb-418048194347500.0.azuredatabricks.net",
        "--app", "vano-clima",
        "--perfil", "azure-chec",
    )
    return destino


def test_init_crea_el_documento_con_su_encabezado(bitacora: Path):
    texto = bitacora.read_text(encoding="utf-8")
    assert texto.startswith("# Bitacora de despliegue")
    for esperado in (
        "/app-vano-clima",
        "01_uiti_vano_clima.ipynb",
        "adb-418048194347500",
        "vano-clima",
        "azure-chec",
    ):
        assert esperado in texto, f"falta {esperado!r} en el encabezado"


def test_init_devuelve_la_ruta_para_encadenar(tmp_path: Path):
    destino = tmp_path / "otra.md"
    salida = _run("init", "--archivo", str(destino), "--comando", "/x")
    assert salida == str(destino)


def test_init_sin_archivo_deriva_una_ruta_fechada(tmp_path: Path, monkeypatch):
    salida = _run("init", "--comando", "/app-vano-clima", "--raiz", str(tmp_path))
    ruta = Path(salida)
    assert ruta.exists()
    assert ruta.parent == tmp_path
    assert ruta.name.startswith("app-vano-clima_")
    assert ruta.suffix == ".md"


def test_paso_ok_queda_en_la_tabla_y_en_el_detalle(bitacora: Path):
    _run(
        "paso", "--archivo", str(bitacora),
        "--id", "2",
        "--titulo", "Preflight del Volume",
        "--estado", "ok",
        "--detalle", "El Volume ya existia",
        "--comando", "databricks fs ls dbfs:/Volumes/...",
        "--salida", "data/  dashboards/",
    )
    texto = bitacora.read_text(encoding="utf-8")
    assert "| 2 | Preflight del Volume |" in texto
    assert "El Volume ya existia" in texto
    assert "databricks fs ls dbfs:/Volumes/..." in texto
    assert "data/  dashboards/" in texto


def test_el_mismo_paso_se_actualiza_no_se_duplica(bitacora: Path):
    for estado in ("ok", "degradado"):
        _run(
            "paso", "--archivo", str(bitacora),
            "--id", "3", "--titulo", "Subida", "--estado", estado,
            "--detalle", f"intento {estado}",
        )
    texto = bitacora.read_text(encoding="utf-8")
    assert texto.count("| 3 | Subida |") == 1
    assert "degradado" in texto
    assert "intento ok" not in texto


def test_los_pasos_conservan_el_orden_de_registro(bitacora: Path):
    for ident in ("2", "2a", "10", "3"):
        _run("paso", "--archivo", str(bitacora), "--id", ident,
             "--titulo", f"paso {ident}", "--estado", "ok")
    texto = bitacora.read_text(encoding="utf-8")
    posiciones = [texto.index(f"| {i} | paso {i} |") for i in ("2", "2a", "10", "3")]
    assert posiciones == sorted(posiciones), "la tabla debe seguir el orden de registro"


def test_restriccion_registra_todos_sus_campos(bitacora: Path):
    _run(
        "restriccion", "--archivo", str(bitacora),
        "--id", "R1",
        "--titulo", "Falta USE CATALOG para el service principal",
        "--paso", "6",
        "--evidencia", "all account users lack USE CATALOG permission",
        "--impacto", "La app responde 500 al leer el Volume",
        "--rodeo", "Se otorgo READ_VOLUME; la app queda desplegada",
        "--quien-desbloquea", "leidy.arias@epm.com.co, dueno del catalogo",
        "--severidad", "bloqueante",
    )
    texto = bitacora.read_text(encoding="utf-8")
    assert "### R1" in texto
    for esperado in (
        "Falta USE CATALOG",
        "all account users lack USE CATALOG permission",
        "La app responde 500",
        "Se otorgo READ_VOLUME",
        "leidy.arias@epm.com.co",
        "bloqueante",
    ):
        assert esperado in texto, f"falta {esperado!r} en la restriccion"


def test_sin_restricciones_la_seccion_lo_dice_explicitamente(bitacora: Path):
    assert "Sin restricciones" in bitacora.read_text(encoding="utf-8")


def test_cerrar_limpio_da_completo(bitacora: Path):
    _run("paso", "--archivo", str(bitacora), "--id", "1", "--titulo", "a", "--estado", "ok")
    _run("cerrar", "--archivo", str(bitacora), "--url", "https://app.example")
    texto = bitacora.read_text(encoding="utf-8")
    assert "COMPLETO" in texto
    assert "CON RESTRICCIONES" not in texto
    assert "https://app.example" in texto


def test_cerrar_con_restriccion_no_puede_decir_completo_a_secas(bitacora: Path):
    _run("restriccion", "--archivo", str(bitacora), "--id", "R1",
         "--titulo", "t", "--impacto", "i", "--severidad", "bloqueante")
    _run("cerrar", "--archivo", str(bitacora))
    assert "COMPLETO CON RESTRICCIONES" in bitacora.read_text(encoding="utf-8")


def test_cerrar_con_paso_fallido_da_incompleto(bitacora: Path):
    _run("paso", "--archivo", str(bitacora), "--id", "4", "--titulo", "t", "--estado", "fallo")
    _run("cerrar", "--archivo", str(bitacora))
    assert "INCOMPLETO" in bitacora.read_text(encoding="utf-8")


def test_cerrar_con_paso_omitido_da_incompleto(bitacora: Path):
    """Un paso `omitido` dice que el objetivo del comando no se cumplio, y para
    eso existe INCOMPLETO. El titular es lo que se lee: una corrida que se quedo
    a medias no puede encabezarse COMPLETO por el hecho de no haber tropezado
    con ningun permiso -- no tropezo porque no llego a intentarlo."""
    _run("paso", "--archivo", str(bitacora), "--id", "1", "--titulo", "a", "--estado", "ok")
    _run("paso", "--archivo", str(bitacora), "--id", "2", "--titulo", "t", "--estado", "omitido")
    _run("cerrar", "--archivo", str(bitacora))
    assert "| Estado final | **INCOMPLETO** |" in bitacora.read_text(encoding="utf-8")


def test_lo_omitido_pesa_mas_que_una_restriccion(bitacora: Path):
    """Los tres estados finales estan ordenados, no son etiquetas sueltas.
    COMPLETO CON RESTRICCIONES significa "se cumplio el objetivo, con rodeos";
    si ademas quedaron pasos sin correr, no se cumplio, y gana INCOMPLETO."""
    _run("restriccion", "--archivo", str(bitacora), "--id", "R1",
         "--titulo", "t", "--impacto", "i", "--severidad", "limitante")
    _run("paso", "--archivo", str(bitacora), "--id", "1", "--titulo", "t", "--estado", "omitido")
    _run("cerrar", "--archivo", str(bitacora))
    assert "| Estado final | **INCOMPLETO** |" in bitacora.read_text(encoding="utf-8")


def test_el_resumen_cuenta_cada_estado(bitacora: Path):
    _run("paso", "--archivo", str(bitacora), "--id", "1", "--titulo", "a", "--estado", "ok")
    _run("paso", "--archivo", str(bitacora), "--id", "2", "--titulo", "b", "--estado", "ok")
    _run("paso", "--archivo", str(bitacora), "--id", "3", "--titulo", "c", "--estado", "degradado")
    _run("paso", "--archivo", str(bitacora), "--id", "4", "--titulo", "d", "--estado", "omitido")
    texto = bitacora.read_text(encoding="utf-8")
    assert "2 ok" in texto
    assert "1 degradado" in texto
    assert "1 omitido" in texto


def test_estado_invalido_es_rechazado(bitacora: Path):
    proc = subprocess.run(
        [sys.executable, str(CLI), "paso", "--archivo", str(bitacora),
         "--id", "1", "--titulo", "t", "--estado", "casi"],
        capture_output=True, text=True,
    )
    assert proc.returncode != 0


def test_el_documento_es_legible_a_medio_camino(bitacora: Path):
    """Nunca se cierra: el archivo debe estar completo despues de cada paso."""
    _run("paso", "--archivo", str(bitacora), "--id", "1", "--titulo", "a", "--estado", "ok")
    texto = bitacora.read_text(encoding="utf-8")
    assert "## Pasos" in texto
    assert "## Restricciones y errores" in texto
    assert "EN CURSO" in texto


def test_las_credenciales_no_llegan_al_archivo(bitacora: Path):
    # Las credenciales falsas se ARMAN aqui en vez de escribirse literales: el
    # escaneo de secretos de GitHub rechaza el push si ve la forma `dapi…`
    # completa en el fuente, aunque sea inventada. La forma que llega al CLI es
    # identica, que es lo unico que le importa a la prueba.
    falso_dapi = "dapi" + "1234567890abcdef" * 2
    falso_jwt = "eyJhbGciOiJIUzI1NiJ9" + ".abc.def"
    falso_valor = "s3cr3t" + "-value-largo"

    _run(
        "paso", "--archivo", str(bitacora), "--id", "1", "--titulo", "auth", "--estado", "ok",
        "--salida",
        f"Bearer {falso_jwt}\n"
        f"token {falso_dapi}\n"
        f'{{"access_token": "{falso_valor}"}}',
    )
    texto = bitacora.read_text(encoding="utf-8")
    assert falso_dapi not in texto
    assert falso_jwt not in texto
    assert falso_valor not in texto
    assert texto.count("[REDACTADO]") >= 3


def test_la_salida_larga_se_recorta_pero_lo_avisa(bitacora: Path):
    _run("paso", "--archivo", str(bitacora), "--id", "1", "--titulo", "t", "--estado", "ok",
         "--salida", "x" * 20000)
    texto = bitacora.read_text(encoding="utf-8")
    assert len(texto) < 20000
    assert "recortada" in texto


def test_el_estado_paralelo_json_permite_reanudar(bitacora: Path):
    _run("paso", "--archivo", str(bitacora), "--id", "1", "--titulo", "t", "--estado", "ok")
    estado = bitacora.with_suffix(".json")
    assert estado.exists()
    datos = json.loads(estado.read_text(encoding="utf-8"))
    assert datos["comando"] == "/app-vano-clima"
    assert datos["pasos"][0]["id"] == "1"


def test_resumen_imprime_las_restricciones_para_el_reporte_final(bitacora: Path):
    _run("restriccion", "--archivo", str(bitacora), "--id", "R1",
         "--titulo", "FUSE 403", "--impacto", "el cuaderno no lee el Volume",
         "--severidad", "bloqueante")
    salida = _run("resumen", "--archivo", str(bitacora))
    assert "R1" in salida
    assert "FUSE 403" in salida


# ------------------------------- la causa, al lado del paso que la sufrio


def test_un_paso_fallido_publica_su_causa_en_la_misma_fila(bitacora: Path):
    """La tabla de pasos decia QUE fallo y la causa vivia en otra seccion, a varias
    pantallas de distancia. Quien lee un despliegue quiere las dos cosas en el mismo
    renglon: sin eso hay que cruzar dos tablas a mano para saber por que no esta lo
    que no esta."""
    _run("paso", "--archivo", str(bitacora), "--id", "4", "--titulo", "Aplicaciones",
         "--estado", "fallo", "--detalle", "simulador-vano no arranco",
         "--causa", "cupo de apps lleno: 3 de 3 en uso")
    texto = bitacora.read_text(encoding="utf-8")
    fila = next(l for l in texto.splitlines() if l.startswith("| 4 |"))
    assert "simulador-vano no arranco" in fila
    assert "cupo de apps lleno" in fila


def test_un_paso_ok_no_arrastra_una_columna_de_causa_llena(bitacora: Path):
    _run("paso", "--archivo", str(bitacora), "--id", "3", "--titulo", "Datos",
         "--estado", "ok", "--detalle", "ya estaban")
    fila = next(l for l in bitacora.read_text(encoding="utf-8").splitlines()
                if l.startswith("| 3 |"))
    assert fila.rstrip().endswith("|  |")


def test_un_paso_que_no_salio_bien_y_no_declaro_causa_lo_dice(bitacora: Path):
    """Una celda vacia al lado de un `fallo` se lee como que fallo sin motivo. Decir
    que la causa no se registro es informacion: significa que el comando la dejo
    fuera, y eso hay que poder verlo."""
    _run("paso", "--archivo", str(bitacora), "--id", "5", "--titulo", "Cuaderno",
         "--estado", "fallo", "--detalle", "no se importo")
    fila = next(l for l in bitacora.read_text(encoding="utf-8").splitlines()
                if l.startswith("| 5 |"))
    assert "sin causa registrada" in fila


def test_la_causa_puede_venir_de_la_restriccion_ligada_al_paso(bitacora: Path):
    """Sin repetirla a mano. La restriccion ya guarda su impacto y a que paso
    pertenece; obligar a escribirla dos veces es garantizar que un dia digan cosas
    distintas."""
    _run("paso", "--archivo", str(bitacora), "--id", "4", "--titulo", "Aplicaciones",
         "--estado", "restriccion", "--detalle", "una de dos")
    _run("restriccion", "--archivo", str(bitacora), "--id", "R1",
         "--titulo", "Falta USE CATALOG", "--severidad", "bloqueante",
         "--paso", "4", "--impacto", "la app no puede leer el Volume")
    fila = next(l for l in bitacora.read_text(encoding="utf-8").splitlines()
                if l.startswith("| 4 |"))
    assert "R1" in fila
    assert "Falta USE CATALOG" in fila


# ---------------------------------------- donde quedo cada cosa en Databricks


def test_sin_ubicaciones_la_seccion_no_aparece(bitacora: Path):
    """Un comando que no registro ninguna no publica una tabla vacia."""
    assert "Donde quedo cada cosa" not in bitacora.read_text(encoding="utf-8")


def test_una_ubicacion_queda_con_su_ruta_y_como_se_llega(bitacora: Path):
    """La pregunta que ninguna otra seccion contesta: acabo el despliegue, y ahora
    donde esta lo que subi. Buscarlo obliga a leer los comandos del detalle por paso
    y reconstruir las rutas a mano."""
    _run("ubicacion", "--archivo", str(bitacora), "--clave", "datos",
         "--titulo", "Datos del proyecto",
         "--ruta", "/Volumes/gold/chec/chec-simulador/data",
         "--como", "Catalog > Volumes > chec-simulador > data",
         "--estado", "ok", "--detalle", "566 MB, 3 shapefiles con sus sidecars")
    texto = bitacora.read_text(encoding="utf-8")
    assert "Donde quedo cada cosa" in texto
    fila = next(l for l in texto.splitlines() if "Datos del proyecto" in l)
    assert "/Volumes/gold/chec/chec-simulador/data" in fila
    assert "Catalog > Volumes" in fila
    assert "566 MB" in fila


def test_una_app_publica_su_url_ademas_de_su_ruta(bitacora: Path):
    """Una app tiene DOS direcciones y no son intercambiables: la URL por la que
    entra quien la usa, y la carpeta del Workspace desde la que se desplego, que es
    donde se mira cuando no arranca."""
    _run("ubicacion", "--archivo", str(bitacora), "--clave", "app-simulador",
         "--titulo", "Simulador", "--ruta", "/Workspace/Users/x@y.com/chec/simulador",
         "--url", "https://simulador-vano-123.azuredatabricks.net",
         "--como", "Compute > Apps > simulador-vano", "--estado", "ok")
    fila = next(l for l in bitacora.read_text(encoding="utf-8").splitlines()
                if "Simulador" in l and l.startswith("|"))
    assert "https://simulador-vano-123.azuredatabricks.net" in fila
    assert "/Workspace/Users/x@y.com/chec/simulador" in fila


def test_la_misma_ubicacion_se_actualiza_no_se_duplica(bitacora: Path):
    for ruta in ("/Volumes/a/b/c", "/Volumes/d/e/f"):
        _run("ubicacion", "--archivo", str(bitacora), "--clave", "datos",
             "--titulo", "Datos", "--ruta", ruta, "--estado", "ok")
    texto = bitacora.read_text(encoding="utf-8")
    assert texto.count("/Volumes/d/e/f") == 1
    assert "/Volumes/a/b/c" not in texto


def test_una_ubicacion_que_no_se_logro_sigue_en_la_tabla(bitacora: Path):
    """Y es la fila mas util de todas. Borrarla del inventario deja al lector
    creyendo que eso no formaba parte del despliegue, en vez de que falto."""
    _run("ubicacion", "--archivo", str(bitacora), "--clave", "simulaciones",
         "--titulo", "Carpeta de simulaciones guardadas",
         "--ruta", "/Volumes/gold/chec/chec-simulador/simulaciones",
         "--estado", "fallo", "--detalle", "sin WRITE VOLUME")
    fila = next(l for l in bitacora.read_text(encoding="utf-8").splitlines()
                if "simulaciones guardadas" in l)
    assert "fallo" in fila
    assert "sin WRITE VOLUME" in fila


def test_las_ubicaciones_conservan_el_orden_de_registro(bitacora: Path):
    """El comando las registra en el orden del despliegue -- datos, apps, cuaderno --
    y ese orden es el que hace legible la tabla."""
    for clave, titulo in (("volumen", "Volume"), ("datos", "Datos"),
                          ("app-tableros", "Tableros"), ("cuaderno", "Cuaderno 05")):
        _run("ubicacion", "--archivo", str(bitacora), "--clave", clave,
             "--titulo", titulo, "--ruta", f"/x/{clave}", "--estado", "ok")
    texto = bitacora.read_text(encoding="utf-8")
    posiciones = [texto.index(f"/x/{c}")
                  for c in ("volumen", "datos", "app-tableros", "cuaderno")]
    assert posiciones == sorted(posiciones)


def test_las_credenciales_tampoco_llegan_a_una_ubicacion(bitacora: Path):
    # Armado en tiempo de ejecucion y no escrito literal, por lo mismo que en
    # `test_las_credenciales_no_llegan_al_archivo`: el escaneo de secretos de GitHub
    # rechaza el push si ve la forma `dapi…` completa en el fuente, aunque sea
    # inventada. Escrito literal, esta prueba paso en local y bloqueo el push.
    falso_dapi = "dapi" + "0123456789abcdef" * 2
    _run("ubicacion", "--archivo", str(bitacora), "--clave", "datos", "--titulo", "D",
         "--ruta", "/Volumes/x", "--detalle", f"token {falso_dapi}", "--estado", "ok")
    assert falso_dapi not in bitacora.read_text(encoding="utf-8")
    assert "[REDACTADO]" in bitacora.read_text(encoding="utf-8")


def test_el_resumen_final_nombra_las_ubicaciones_registradas(bitacora: Path):
    """`resumen` es lo que el comando lee para reportarle al usuario. Si el inventario
    solo vive en el Markdown, el reporte en pantalla no lo menciona."""
    _run("ubicacion", "--archivo", str(bitacora), "--clave", "cuaderno",
         "--titulo", "Cuaderno 05", "--ruta", "/Workspace/x/05.ipynb", "--estado", "ok")
    salida = _run("resumen", "--archivo", str(bitacora))
    assert "/Workspace/x/05.ipynb" in salida
