"""La guarda que decide si `/graphify --update` puede correr sin podar el grafo.

## El defecto, medido

El paso 9 de `/report` encadenaba `/graphify` sobre `reports/vault`. El manifiesto de
`graphify-out/` describe el PROYECTO ENTERO -- 426 claves, todas relativas a la raiz:
`astro.config.mjs`, `data/models/...`, `src/...` -- y CERO de ellas cuelgan de
`reports/vault`. Al reanclar esas 426 claves contra la raiz mas estrecha, todas
resuelven a rutas que nunca existieron, y la deteccion incremental las reporta como
BORRADAS. Continuar habria podado 426 archivos de un grafo de 6.479 nodos.

    detect_incremental('reports/vault')  ->  1 nuevo,  426 borrados,   0 existen
    detect_incremental('.')              -> 152 nuevos,  16 borrados,   0 existen

## Por que la guarda anterior no servia

Decia: "si algun borrado reportado no existe en disco, aborta". Un borrado GENUINO
tampoco existe en disco -- esa es la definicion de borrado. Con esa regla, los 16
borrados reales de la raiz (pruebas y comandos retirados de verdad) tambien abortaban,
y el grafo no podia enterarse nunca de que algo se habia ido.

Lo que de verdad distingue un fantasma de un borrado real no es si el archivo existe,
sino si el manifiesto esta ANCLADO en la misma raiz que se esta escaneando.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chec_local_interpreter.graphify_guarda import (
    ANCLAJE_MINIMO,
    Veredicto,
    revisar_anclaje,
)


def _manifiesto(tmp_path: Path, claves: list[str]) -> Path:
    salida = tmp_path / "graphify-out"
    salida.mkdir(exist_ok=True)
    destino = salida / "manifest.json"
    destino.write_text(json.dumps({k: {"hash": "x"} for k in claves}, ensure_ascii=False),
                       encoding="utf-8")
    return destino


def test_un_manifiesto_de_la_raiz_escaneado_desde_la_raiz_deja_seguir(tmp_path):
    """El caso sano: las claves resuelven donde el manifiesto dice."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "b.md").write_text("y", encoding="utf-8")
    _manifiesto(tmp_path, ["src/a.py", "b.md"])

    veredicto = revisar_anclaje(raiz_escaneo=tmp_path, raiz_manifiesto=tmp_path)

    assert veredicto.seguir is True
    assert veredicto.resuelven == 2 and veredicto.total == 2


def test_el_manifiesto_del_proyecto_escaneado_desde_una_subcarpeta_ABORTA(tmp_path):
    """El defecto real: 426 claves de la raiz contra `reports/vault`, que no contiene
    ninguna. Todas se leen como borradas."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    sub = tmp_path / "reports" / "vault"
    sub.mkdir(parents=True)
    (sub / "C1.md").write_text("z", encoding="utf-8")
    _manifiesto(tmp_path, ["src/a.py", "astro.config.mjs", "data/models/m.json"])

    veredicto = revisar_anclaje(raiz_escaneo=sub, raiz_manifiesto=tmp_path)

    assert veredicto.seguir is False
    assert veredicto.resuelven == 0
    assert "anclado" in veredicto.motivo.lower()


def test_los_borrados_GENUINOS_no_abortan(tmp_path):
    """La guarda anterior abortaba con estos, y son justo los que el grafo TIENE que
    conocer: archivos que de verdad se retiraron.

    Un borrado genuino no existe en disco -- esa es su definicion --, asi que la regla
    "si no existe, aborta" no podia distinguirlo de un fantasma.

    Lo que se mide aqui es UBICACION y no existencia: `b.md` sigue PERTENECIENDO a esta
    raiz aunque ya no este, asi que cuenta como resuelta y el anclaje sale sano. Es
    justo lo que permite que el grafo se entere de que se fue.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    # `b.md` esta en el manifiesto y ya no en disco: borrado de verdad.
    _manifiesto(tmp_path, ["src/a.py", "b.md"])

    veredicto = revisar_anclaje(raiz_escaneo=tmp_path, raiz_manifiesto=tmp_path)

    assert veredicto.seguir is True, veredicto.motivo
    assert veredicto.resuelven == 2 and veredicto.total == 2


def test_el_umbral_es_una_FRACCION_y_no_un_conteo(tmp_path):
    """Un proyecto grande retira decenas de archivos sin que eso sea un desanclaje.

    Aqui NINGUNA de las cien claves esta fuera de la raiz -- diez ya no existen, pero
    siguen perteneciendo a ella --, asi que la fraccion es 1 y se sigue. La fraccion baja
    solo cuando las claves apuntan a OTRO sitio, que es el desanclaje de verdad.
    """
    (tmp_path / "src").mkdir()
    for i in range(90):
        (tmp_path / "src" / f"a{i}.py").write_text("x", encoding="utf-8")
    claves = [f"src/a{i}.py" for i in range(90)] + [f"ido{i}.md" for i in range(10)]
    _manifiesto(tmp_path, claves)

    veredicto = revisar_anclaje(raiz_escaneo=tmp_path, raiz_manifiesto=tmp_path)

    assert veredicto.fraccion == pytest.approx(1.0)
    assert veredicto.seguir is True
    assert ANCLAJE_MINIMO < 1.0


def test_sin_manifiesto_se_puede_seguir(tmp_path):
    """La primera corrida no tiene manifiesto que desanclar: no hay nada que podar."""
    veredicto = revisar_anclaje(raiz_escaneo=tmp_path, raiz_manifiesto=tmp_path)

    assert veredicto.seguir is True
    assert veredicto.total == 0


def test_un_manifiesto_ilegible_ABORTA(tmp_path):
    """Sin poder leerlo no se puede afirmar que el anclaje sea correcto, y la
    consecuencia de equivocarse es podar el grafo."""
    salida = tmp_path / "graphify-out"
    salida.mkdir()
    (salida / "manifest.json").write_text("{esto no es json", encoding="utf-8")

    veredicto = revisar_anclaje(raiz_escaneo=tmp_path, raiz_manifiesto=tmp_path)

    assert veredicto.seguir is False
    assert "no se pudo leer" in veredicto.motivo.lower()


def test_el_veredicto_se_puede_imprimir_para_el_runbook(tmp_path):
    """El paso 9 de `/report` lo lee en consola: tiene que decir el numero y la
    decision, no solo un codigo de salida."""
    _manifiesto(tmp_path, ["a.md"])
    (tmp_path / "a.md").write_text("x", encoding="utf-8")

    veredicto = revisar_anclaje(raiz_escaneo=tmp_path, raiz_manifiesto=tmp_path)

    texto = veredicto.linea()
    assert "1/1" in texto or "100" in texto
    assert "SEGUIR" in texto


def test_el_proyecto_REAL_esta_anclado_en_su_raiz_y_no_en_la_boveda():
    """Contra el manifiesto de verdad, que es el que aborto todas las corridas.

    Medido cuando se escribio: 426 claves, 0 bajo `reports/vault`. Escanear la boveda con
    ese manifiesto reporta 426 borrados fantasma; escanear la raiz reporta 16, y esos 16
    son reales.

    La cuenta exacta NO es el contrato. Tras la primera corrida sana el manifiesto tiene
    448 claves y UNA de ellas -- `reports/vault/DON23L14.md` -- si cuelga de la boveda,
    porque el grafo por fin la conoce. Un `== 0` aqui convertiria esa buena noticia en un
    fallo. Lo que se afirma es la FRACCION contra el umbral: 1 de 448 sigue siendo "casi
    ninguna", que es justo lo que la guarda mide.
    """
    raiz = Path(__file__).resolve().parents[1]
    if not (raiz / "graphify-out" / "manifest.json").is_file():
        pytest.skip("no hay manifiesto de graphify en esta copia")

    desde_raiz = revisar_anclaje(raiz_escaneo=raiz, raiz_manifiesto=raiz)
    desde_vault = revisar_anclaje(raiz_escaneo=raiz / "reports" / "vault",
                                  raiz_manifiesto=raiz)

    assert desde_raiz.seguir is True, desde_raiz.motivo
    assert desde_vault.seguir is False
    assert desde_vault.fraccion < ANCLAJE_MINIMO, (
        f"{desde_vault.resuelven}/{desde_vault.total} claves cuelgan de la boveda: el "
        "manifiesto dejo de estar anclado en la raiz")


def test_el_veredicto_es_un_dato_y_no_una_excepcion(tmp_path):
    """El runbook decide con el; lanzar tumbaria un informe que ya esta completo."""
    veredicto = revisar_anclaje(raiz_escaneo=tmp_path / "no" / "existe",
                                raiz_manifiesto=tmp_path)

    assert isinstance(veredicto, Veredicto)
