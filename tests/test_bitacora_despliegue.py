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
        "--cuaderno", "notebooks/old_version/01_uiti_vano_clima.ipynb",
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
