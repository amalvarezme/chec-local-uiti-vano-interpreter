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


# --------------------------------------------------------------------------
# linea_desde_desglose -- el adaptador que usa el informe de circuito
#
# `plotting.render_llm_analysis` ya RECIBE `stage_breakdown` (la lista que
# arma `report_pipeline._resolve_stage_breakdown`), asi que la figura del
# informe no necesita la carpeta de la corrida ni un parametro nuevo: se
# construye desde esa misma lista. Lo unico que se pierde son los tamanos de
# entrada/salida, que solo existen mirando los archivos.
# --------------------------------------------------------------------------

_DESGLOSE = [
    {
        "stage": "historical",
        "tokens_total": 100714,
        "token_source": "measured",
        "duration_seconds": 447.502,
        "duration_source": "measured",
    },
    {
        "stage": "inference",
        "tokens_total": 138831,
        "token_source": "measured",
        "duration_seconds": 536.193,
        "duration_source": "measured",
    },
    {
        "stage": "expert-alignment",
        "tokens_total": 106848,
        "token_source": "estimated",
        "duration_seconds": 372.298,
        "duration_source": "measured",
    },
]


def test_el_adaptador_produce_el_mismo_horario_que_la_carpeta(corrida: Path) -> None:
    from chec_local_interpreter.agentes_linea_tiempo import linea_desde_desglose

    desde_disco = construir_linea_tiempo(corrida)
    desde_lista = linea_desde_desglose(_DESGLOSE, circuito="HER23L16")

    assert [e["etapa"] for e in desde_lista["etapas"]] == [
        e["etapa"] for e in desde_disco["etapas"]
    ]
    for a, b in zip(desde_lista["etapas"], desde_disco["etapas"]):
        assert a["inicio_segundos"] == pytest.approx(b["inicio_segundos"])
        assert a["duracion_segundos"] == pytest.approx(b["duracion_segundos"])
    assert desde_lista["reloj_de_pared_segundos"] == pytest.approx(
        desde_disco["reloj_de_pared_segundos"]
    )
    assert desde_lista["ahorro_segundos"] == pytest.approx(desde_disco["ahorro_segundos"])


def test_el_adaptador_conserva_si_los_tokens_son_medidos_o_estimados(corrida: Path) -> None:
    """El informe ya distingue medidos de estimados; la figura no puede perderlo."""
    from chec_local_interpreter.agentes_linea_tiempo import linea_desde_desglose

    por_nombre = {e["etapa"]: e for e in linea_desde_desglose(_DESGLOSE)["etapas"]}
    assert por_nombre["historical"]["token_source"] == "measured"
    assert por_nombre["expert-alignment"]["token_source"] == "estimated"


def test_el_adaptador_aguanta_una_etapa_sin_medidas() -> None:
    from chec_local_interpreter.agentes_linea_tiempo import linea_desde_desglose

    linea = linea_desde_desglose(
        [
            {"stage": "historical", "tokens_total": None, "duration_seconds": None},
            {"stage": "inference", "tokens_total": 10, "duration_seconds": 60.0},
        ]
    )
    por_nombre = {e["etapa"]: e for e in linea["etapas"]}
    assert por_nombre["historical"]["duracion_segundos"] == 0.0
    assert por_nombre["historical"]["tokens"] is None
    assert linea["reloj_de_pared_segundos"] == pytest.approx(60.0)


def test_el_adaptador_ignora_una_etapa_desconocida() -> None:
    """Una etapa fuera de las tres del contrato no puede colarse en el horario."""
    from chec_local_interpreter.agentes_linea_tiempo import linea_desde_desglose

    linea = linea_desde_desglose(
        [
            {"stage": "historical", "tokens_total": 1, "duration_seconds": 10.0},
            {"stage": "una-etapa-inventada", "tokens_total": 9, "duration_seconds": 999.0},
        ]
    )
    assert [e["etapa"] for e in linea["etapas"]] == ["historical"]


# --------------------------------------------------------------------------
# seccion_agentes_html -- el bloque que se inserta en el informe de circuito
# --------------------------------------------------------------------------


def test_la_seccion_del_informe_trae_la_figura_y_la_explicacion() -> None:
    from chec_local_interpreter.agentes_linea_tiempo import (
        linea_desde_desglose,
        seccion_agentes_html,
    )

    bloque = seccion_agentes_html(linea_desde_desglose(_DESGLOSE))
    assert "<svg" in bloque
    assert "en paralelo" in bloque
    for etapa in ("historical", "inference", "expert-alignment"):
        assert etapa in bloque


def test_la_seccion_del_informe_no_trae_red_ni_guion() -> None:
    from chec_local_interpreter.agentes_linea_tiempo import (
        linea_desde_desglose,
        seccion_agentes_html,
    )

    limpio = _sin_xmlns(seccion_agentes_html(linea_desde_desglose(_DESGLOSE)))
    for prohibido in ("http://", "https://", "<script", "<link"):
        assert prohibido not in limpio


def test_sin_desglose_la_seccion_es_vacia() -> None:
    """Una corrida sin analisis LLM no debe dejar un recuadro vacio en el informe."""
    from chec_local_interpreter.agentes_linea_tiempo import (
        linea_desde_desglose,
        seccion_agentes_html,
    )

    assert seccion_agentes_html(linea_desde_desglose([])) == ""
    assert seccion_agentes_html(None) == ""


def test_la_seccion_marca_con_tilde_los_tokens_que_no_son_medidos() -> None:
    """La tabla vieja etiquetaba la procedencia FILA A FILA; no se puede perder.

    El informe ya usa `~` para "esto es una aproximacion" (ver
    `plotting._token_source_label`), asi que la figura reusa esa convencion en
    vez de inventar otra.
    """
    from chec_local_interpreter.agentes_linea_tiempo import (
        linea_desde_desglose,
        seccion_agentes_html,
    )

    bloque = seccion_agentes_html(linea_desde_desglose(_DESGLOSE))
    # `historical` es measured: su cifra va limpia.
    assert ">100.714<" in bloque
    # `expert-alignment` es estimated: su cifra va marcada.
    assert ">~106.848<" in bloque


def test_no_afirma_un_ahorro_cuando_no_lo_hubo() -> None:
    """Con una sola etapa medida el reloj IGUALA la suma; decir "es menor" mentiria."""
    from chec_local_interpreter.agentes_linea_tiempo import (
        linea_desde_desglose,
        seccion_agentes_html,
    )

    degradado = linea_desde_desglose(
        [
            {"stage": "historical", "tokens_total": 1000, "duration_seconds": 77.4},
            {"stage": "inference", "tokens_total": 2000, "duration_seconds": None},
        ]
    )
    assert degradado["ahorro_segundos"] == pytest.approx(0.0)
    bloque = seccion_agentes_html(degradado)
    assert "en paralelo" in bloque          # el hecho estructural sigue siendo cierto
    assert "menor que la suma" not in bloque  # la consecuencia, no

    con_ahorro = seccion_agentes_html(linea_desde_desglose(_DESGLOSE))
    assert "menor que la suma" in con_ahorro
