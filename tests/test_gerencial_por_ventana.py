"""El estudio POR VENTANA del informe gerencial.

El informe agregaba por circuito y perdia la dimension en la que el modelo trabaja: la
unidad del MIL es la bolsa `(vano, ventana)`, y cada `/report` estudia TRES ventanas de
su circuito. Sumando los circuitos del grupo sin mirar la ventana, dos hallazgos que
ocurrieron en meses distintos se leen como el mismo problema.

La fuente es el SOBRE de inferencia (`inference.bc.json`) y no la salida del agente:
medido sobre las corridas en disco, los escenarios que el agente devuelve traen
`nombre`, `interpretacion` y `provenance` -- sin `ventana` ni `vanos_criticos`. Lo que
`prepare` dejo en el sobre si trae la ventana, cuantos vanos tiene, cuales son criticos
y cuales alcanzan el grupo Bajo.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _sobre(ventana: str, *, n_vanos: int, criticos: int, alcanzan: int) -> dict:
    return {
        "ventana": ventana,
        "n_vanos": n_vanos,
        "vanos_criticos": [
            {"fid": f"F{i}", "clase_base": 3, "clase_final": 0 if i < alcanzan else 3,
             "alcanza": i < alcanzan, "u_base": 9.0, "u_final": 1.0, "pasos": []}
            for i in range(criticos)
        ],
    }


def _escribir_corrida(runs_root: Path, circuito: str, escenarios: list[dict],
                      periodos: dict[str, str] | None = None) -> Path:
    """Una corrida COMPLETA, que es la unica que el informe gerencial mira.

    `find_latest_run` exige un `expert-alignment.out.json` validado -- una corrida a
    medias no es una corrida --, asi que el sobre de inferencia solo no basta. Es
    correcto que lo exija: media corrida en el agregado del grupo es un circuito que
    cuenta sus ventanas y no sus causas.
    """
    run = runs_root / circuito / "20260101T000000000000"
    run.mkdir(parents=True)
    (run / "inference.bc.json").write_text(json.dumps({
        "escenarios": escenarios,
        "ventanas_estudio": [e["ventana"] for e in escenarios],
        "periodos_ventana": periodos or {},
    }, ensure_ascii=False), encoding="utf-8")
    (run / "expert-alignment.out.json").write_text(json.dumps({
        "ok": True, "data": {"variables_a_priorizar": []},
    }, ensure_ascii=False), encoding="utf-8")
    (run / "historical.out.json").write_text(json.dumps({
        "ok": True, "data": {"cause_hypothesis_note": None, "key_findings": [],
                             "recommended_actions": []},
    }, ensure_ascii=False), encoding="utf-8")
    return run


def test_agrega_las_ventanas_de_todos_los_circuitos_muestreados(tmp_path):
    """La pregunta del grupo es en QUE ventanas se concentra su criticidad, y eso no se
    puede contestar circuito por circuito."""
    from chec_local_interpreter.informe_gerencial_contract import ventanas_del_grupo

    _escribir_corrida(tmp_path, "C1", [_sobre("V9", n_vanos=100, criticos=15, alcanzan=2),
                                       _sobre("V11", n_vanos=90, criticos=9, alcanzan=9)])
    _escribir_corrida(tmp_path, "C2", [_sobre("V9", n_vanos=80, criticos=10, alcanzan=0)])

    filas = ventanas_del_grupo(["C1", "C2"], runs_root=tmp_path)

    por_ventana = {f["ventana"]: f for f in filas}
    assert por_ventana["V9"]["circuitos"] == 2
    assert por_ventana["V9"]["vanos_criticos"] == 25
    assert por_ventana["V9"]["alcanzan_bajo"] == 2
    assert por_ventana["V11"]["circuitos"] == 1


def test_las_ventanas_salen_en_orden_CRONOLOGICO_y_no_alfabetico():
    """`V10` va despues de `V9`, no entre `V1` y `V2`. Es el mismo orden que el resto
    del proyecto usa, y con el alfabetico la lectura del grupo queda al reves."""
    from chec_local_interpreter.informe_gerencial_contract import _orden_ventana

    etiquetas = ["V11", "V2", "V10", "V9"]

    assert sorted(etiquetas, key=_orden_ventana) == ["V2", "V9", "V10", "V11"]


def test_el_periodo_de_cada_ventana_viaja_para_poder_nombrarla(tmp_path):
    """"V9" no le dice nada a quien lee un informe gerencial; "del 1 al 31 de marzo"
    si."""
    from chec_local_interpreter.informe_gerencial_contract import ventanas_del_grupo

    _escribir_corrida(tmp_path, "C1", [_sobre("V9", n_vanos=10, criticos=1, alcanzan=0)],
                      periodos={"V9": "2026-03-01 a 2026-03-31"})

    filas = ventanas_del_grupo(["C1"], runs_root=tmp_path)

    assert filas[0]["periodo"] == "2026-03-01 a 2026-03-31"


def test_un_circuito_sin_corrida_no_tumba_la_agregacion(tmp_path):
    """Un grupo puede tener circuitos sin corrida todavia; el informe ya lo declara en
    otra parte y aqui simplemente no aportan ventanas."""
    from chec_local_interpreter.informe_gerencial_contract import ventanas_del_grupo

    _escribir_corrida(tmp_path, "C1", [_sobre("V9", n_vanos=10, criticos=1, alcanzan=1)])

    filas = ventanas_del_grupo(["C1", "NO_EXISTE"], runs_root=tmp_path)

    assert [f["ventana"] for f in filas] == ["V9"]
    assert filas[0]["circuitos"] == 1


def test_sin_ninguna_corrida_no_hay_filas(tmp_path):
    from chec_local_interpreter.informe_gerencial_contract import ventanas_del_grupo

    assert ventanas_del_grupo(["C1"], runs_root=tmp_path) == []


# --- La figura -----------------------------------------------------------------


def test_la_figura_enfrenta_vanos_criticos_con_los_que_alcanzan_bajo():
    """Las dos cifras juntas son la lectura: cuantos vanos hay que atender en esa
    ventana, y en cuantos la intervencion basta para sacarlos del grupo critico."""
    from chec_local_interpreter.informe_gerencial_contract import figura_por_ventana

    fig = figura_por_ventana([
        {"ventana": "V9", "periodo": "marzo", "circuitos": 2,
         "vanos_criticos": 25, "alcanzan_bajo": 2},
        {"ventana": "V11", "periodo": "abril", "circuitos": 1,
         "vanos_criticos": 9, "alcanzan_bajo": 9},
    ])

    nombres = {t.name for t in fig.data}
    assert "Vanos críticos" in nombres
    assert "Alcanzan el grupo Bajo" in nombres
    criticos = next(t for t in fig.data if t.name == "Vanos críticos")
    assert list(criticos.x) == ["V9", "V11"]
    assert list(criticos.y) == [25, 9]


def test_sin_filas_no_hay_figura():
    from chec_local_interpreter.informe_gerencial_contract import figura_por_ventana

    assert figura_por_ventana([]) is None


def test_la_seccion_nombra_la_ventana_con_su_periodo():
    """Y declara que el calculo es determinista, como las otras secciones que no pasan
    por un agente."""
    from chec_local_interpreter.informe_gerencial_contract import _ventanas_html

    html = _ventanas_html([
        {"ventana": "V9", "periodo": "2026-03-01 a 2026-03-31", "circuitos": 2,
         "vanos_criticos": 25, "alcanzan_bajo": 2},
    ])

    assert "V9" in html
    assert "2026-03-01 a 2026-03-31" in html
    assert "determinista" in html.lower()
    assert "plotly" in html.lower() or "grafica" in html.lower()


def test_sin_ventanas_la_seccion_no_aparece():
    from chec_local_interpreter.informe_gerencial_contract import _ventanas_html

    assert _ventanas_html([]) == ""


def test_cuenta_tambien_los_que_BAJAN_DE_GRUPO_sin_llegar_a_bajo(tmp_path):
    """Solo contaba `alcanza`, o sea llegar al grupo Bajo.

    Medido sobre DON23L14 V11: de los 16 vanos que el plan mueve, 8 llegan a Bajo y
    otros 8 bajan un grupo sin llegar. Contando solo los primeros, la mitad del efecto
    de la obra desaparece del informe del grupo -- y una ventana donde nada llega a Bajo
    pero todo baja un escalon se lee como una ventana sin nada que hacer.
    """
    from chec_local_interpreter.informe_gerencial_contract import ventanas_del_grupo

    escenario = {
        "ventana": "V9", "n_vanos": 50,
        "vanos_criticos": [
            {"fid": "A", "alcanza": True, "baja_de_grupo": True},
            {"fid": "B", "alcanza": False, "baja_de_grupo": True},
            {"fid": "C", "alcanza": False, "baja_de_grupo": False},
        ],
    }
    _escribir_corrida(tmp_path, "C1", [escenario])

    fila = ventanas_del_grupo(["C1"], runs_root=tmp_path)[0]

    assert fila["alcanzan_bajo"] == 1
    assert fila["bajan_de_grupo"] == 2, "no cuenta los que bajan sin llegar a Bajo"


def test_una_corrida_vieja_sin_el_campo_no_inventa_bajadas(tmp_path):
    """Las corridas anteriores al cambio no traen `baja_de_grupo`. Se cae a lo que si
    se puede afirmar -- llegar a Bajo ES bajar de grupo -- y nada mas."""
    from chec_local_interpreter.informe_gerencial_contract import ventanas_del_grupo

    escenario = {
        "ventana": "V9", "n_vanos": 50,
        "vanos_criticos": [{"fid": "A", "alcanza": True}, {"fid": "B", "alcanza": False}],
    }
    _escribir_corrida(tmp_path, "C1", [escenario])

    fila = ventanas_del_grupo(["C1"], runs_root=tmp_path)[0]

    assert fila["alcanzan_bajo"] == 1
    assert fila["bajan_de_grupo"] == 1


def test_la_figura_muestra_las_tres_cifras():
    from chec_local_interpreter.informe_gerencial_contract import figura_por_ventana

    fig = figura_por_ventana([
        {"ventana": "V9", "periodo": "marzo", "circuitos": 2, "vanos_criticos": 25,
         "bajan_de_grupo": 10, "alcanzan_bajo": 2},
    ])

    nombres = {t.name for t in fig.data}
    assert "Bajan de grupo" in nombres
