"""RED/GREEN tests for `agentes_linea_tiempo`, the deterministic renderer that
turns a finished `/report` run directory into an illustrative picture of what
the agents did.

Why this module exists at all, and why it is not a live dashboard: everything
it needs is ALREADY on disk when a run finishes (`stage_timing.json`,
`token_usage.json`, `l1_state.json` and each stage's `.bc.json`/`.out.json`).
It therefore makes no LLM call, opens no socket, polls nothing and pulls no
dependency -- it reads files and emits one self-contained SVG string.

The load-bearing claim under test is the TIMELINE, and it is not cosmetic.
`historical` and `inference` are dispatched concurrently by design
(`.claude/skills/report/SKILL.md`), so the three stage durations do NOT
partition the run's wall clock: laid end to end they overrun the real span by
13-40%. Measured over the 15 archived runs, each of those two stages ends
within 5-26 s of `fin_preparacion + su propia duracion`, whereas a sequential
schedule would put `inference`'s end 216-448 s later. `construir_linea_tiempo`
must therefore place both at the same start offset; `test_las_dos_ramas_...`
is the regression guard that a future refactor cannot silently turn the
picture back into a lie.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from chec_local_interpreter.agentes_linea_tiempo import (
    construir_linea_tiempo,
    render_svg,
    render_pagina,
)


# --------------------------------------------------------------------------
# Fixture: a run directory shaped exactly like a real one, with the archived
# HER23L16 numbers so the assertions below are anchored to measured values.
# --------------------------------------------------------------------------

_DURACIONES = {
    "historical": 447.502,
    "inference": 536.193,
    "expert-alignment": 372.298,
}
_TOKENS = {
    "historical": 100714,
    "inference": 138831,
    "expert-alignment": 106848,
}


@pytest.fixture
def corrida(tmp_path: Path) -> Path:
    run = tmp_path / "HER23L16" / "20260826T151933937029"
    run.mkdir(parents=True)
    (run / "stage_timing.json").write_text(
        json.dumps({k: {"duration_seconds": v} for k, v in _DURACIONES.items()}),
        encoding="utf-8",
    )
    (run / "token_usage.json").write_text(
        json.dumps({k: {"total": v} for k, v in _TOKENS.items()}), encoding="utf-8"
    )
    (run / "l1_state.json").write_text(
        json.dumps(
            {
                "circuito": "HER23L16",
                "fecha_inicio": "2025-11-01",
                "fecha_fin": "2026-04-30",
                "ventanas_estudio": ["V8", "V9", "V11"],
            }
        ),
        encoding="utf-8",
    )
    for etapa in _DURACIONES:
        (run / f"{etapa}.bc.json").write_text('{"contexto": 1}', encoding="utf-8")
        (run / f"{etapa}.out.json").write_text(
            json.dumps({"ok": True, "data": {"x": 1}}), encoding="utf-8"
        )
    return run


# --------------------------------------------------------------------------
# construir_linea_tiempo -- the data model
# --------------------------------------------------------------------------


def test_devuelve_una_entrada_por_etapa_del_agente(corrida: Path) -> None:
    linea = construir_linea_tiempo(corrida)
    nombres = [e["etapa"] for e in linea["etapas"]]
    assert nombres == ["historical", "inference", "expert-alignment"]


def test_conserva_las_duraciones_y_los_tokens_medidos(corrida: Path) -> None:
    linea = construir_linea_tiempo(corrida)
    por_nombre = {e["etapa"]: e for e in linea["etapas"]}
    for etapa, segundos in _DURACIONES.items():
        assert por_nombre[etapa]["duracion_segundos"] == pytest.approx(segundos)
        assert por_nombre[etapa]["tokens"] == _TOKENS[etapa]


def test_las_dos_ramas_concurrentes_arrancan_en_el_mismo_instante(
    corrida: Path,
) -> None:
    """`historical` e `inference` se despachan concurrentemente por diseno.

    Si un refactor los pusiera en fila, `inference` arrancaria 447 s despues y
    la figura afirmaria algo que las 15 corridas archivadas desmienten.
    """
    por_nombre = {e["etapa"]: e for e in construir_linea_tiempo(corrida)["etapas"]}
    assert por_nombre["historical"]["inicio_segundos"] == pytest.approx(0.0)
    assert por_nombre["inference"]["inicio_segundos"] == pytest.approx(0.0)


def test_la_tercera_etapa_espera_a_que_terminen_las_dos(corrida: Path) -> None:
    por_nombre = {e["etapa"]: e for e in construir_linea_tiempo(corrida)["etapas"]}
    barrera = max(
        por_nombre["historical"]["duracion_segundos"],
        por_nombre["inference"]["duracion_segundos"],
    )
    assert por_nombre["expert-alignment"]["inicio_segundos"] == pytest.approx(barrera)


def test_el_reloj_de_pared_es_menor_que_la_suma_de_etapas(corrida: Path) -> None:
    """Es el hecho que la figura existe para contar: el paralelismo ahorra."""
    linea = construir_linea_tiempo(corrida)
    suma = sum(e["duracion_segundos"] for e in linea["etapas"])
    assert linea["reloj_de_pared_segundos"] < suma
    assert linea["reloj_de_pared_segundos"] == pytest.approx(536.193 + 372.298)
    assert linea["ahorro_segundos"] == pytest.approx(suma - (536.193 + 372.298))


def test_lee_la_identidad_del_circuito(corrida: Path) -> None:
    linea = construir_linea_tiempo(corrida)
    assert linea["circuito"] == "HER23L16"
    assert linea["ventanas"] == ["V8", "V9", "V11"]


def test_una_etapa_que_nunca_corrio_se_omite_sin_reventar(corrida: Path) -> None:
    (corrida / "expert-alignment.bc.json").unlink()
    (corrida / "expert-alignment.out.json").unlink()
    datos = json.loads((corrida / "stage_timing.json").read_text(encoding="utf-8"))
    del datos["expert-alignment"]
    (corrida / "stage_timing.json").write_text(json.dumps(datos), encoding="utf-8")

    linea = construir_linea_tiempo(corrida)
    assert [e["etapa"] for e in linea["etapas"]] == ["historical", "inference"]


def test_una_corrida_sin_medidas_no_revienta(tmp_path: Path) -> None:
    vacia = tmp_path / "VACIA" / "20260101T000000000000"
    vacia.mkdir(parents=True)
    linea = construir_linea_tiempo(vacia)
    assert linea["etapas"] == []
    assert linea["reloj_de_pared_segundos"] == 0.0


# --------------------------------------------------------------------------
# render_svg / render_pagina -- la figura
# --------------------------------------------------------------------------


def _sin_xmlns(marcado: str) -> str:
    """Quita las declaraciones `xmlns`, que son identificadores y no peticiones.

    `xmlns="http://www.w3.org/2000/svg"` es obligatorio en un SVG suelto y
    ningun agente de usuario lo resuelve por red. Buscar "http" a secas lo
    confunde con una descarga real, asi que se descarta antes de mirar.
    """
    return re.sub(r'xmlns(?::\w+)?="[^"]*"', "", marcado)


def test_el_svg_no_pide_nada_a_la_red(corrida: Path) -> None:
    """La figura tiene que verse desde `file://` y dentro de un PDF."""
    svg = render_svg(construir_linea_tiempo(corrida))
    assert "<svg" in svg
    limpio = _sin_xmlns(svg)
    for prohibido in ("http://", "https://", "<script", "<foreignObject", "url("):
        assert prohibido not in limpio


def test_el_svg_nombra_las_tres_etapas(corrida: Path) -> None:
    svg = render_svg(construir_linea_tiempo(corrida))
    for etapa in _DURACIONES:
        assert etapa in svg


def test_las_barras_concurrentes_comparten_la_coordenada_x(corrida: Path) -> None:
    """El paralelismo tiene que VERSE, no solo estar en los datos."""
    svg = render_svg(construir_linea_tiempo(corrida))
    barras = dict(
        re.findall(r'data-etapa="([^"]+)"[^>]*\bx="([0-9.]+)"', svg)
    )
    assert barras["historical"] == barras["inference"]
    assert float(barras["expert-alignment"]) > float(barras["historical"])


def test_la_pagina_es_autocontenida(corrida: Path) -> None:
    html = render_pagina(construir_linea_tiempo(corrida))
    assert html.lstrip().startswith("<!doctype html>")
    assert "<svg" in html
    limpio = _sin_xmlns(html)
    for prohibido in ("http://", "https://", "<script", "<link", "url("):
        assert prohibido not in limpio


def test_la_pagina_dice_el_ahorro_en_lenguaje_llano(corrida: Path) -> None:
    html = render_pagina(construir_linea_tiempo(corrida))
    assert "HER23L16" in html
    assert "en paralelo" in html


# --------------------------------------------------------------------------
# CLI -- `python -m chec_local_interpreter.agentes_linea_tiempo <run_dir>`
# --------------------------------------------------------------------------


def test_el_cli_escribe_la_pagina_junto_a_la_corrida(corrida: Path) -> None:
    from chec_local_interpreter.agentes_linea_tiempo import main

    assert main([str(corrida)]) == 0
    destino = corrida / "agentes.html"
    assert destino.exists()
    assert "HER23L16" in destino.read_text(encoding="utf-8")


def test_el_cli_acepta_un_destino_explicito(corrida: Path, tmp_path: Path) -> None:
    from chec_local_interpreter.agentes_linea_tiempo import main

    destino = tmp_path / "sub" / "figura.html"
    assert main([str(corrida), "-o", str(destino)]) == 0
    assert destino.exists()


def test_el_cli_avisa_si_la_carpeta_no_existe(tmp_path: Path) -> None:
    from chec_local_interpreter.agentes_linea_tiempo import main

    assert main([str(tmp_path / "no-existe")]) == 2
