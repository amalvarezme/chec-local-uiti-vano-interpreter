"""Que hay que rehacer cuando se mueve un archivo base, y en que orden.

El proyecto ya tiene escrito -- en `aplicaciones/DATOS-Y-ACTUALIZACIONES.md` -- que
pasa cuando llega un CSV nuevo. Lo que no tenia es quien lo COMPRUEBE: la huella de
cada aplicacion contesta "cambio algun insumo?" y se reconstruye sola, pero nadie
contesta "los artefactos derivados salieron de ESTAS fuentes?".

Los tres desajustes que esa pregunta atrapa, y que ninguna huella ve:

1. **`src/chec_impacto/data/graph.py` editado.** La adyacencia del grafo experto se
   guarda DENTRO del `.pt` (`mil_persistencia.guardar_modelo_mil` la escribe,
   `cargar_modelo_mil` la lee de ahi y no la reconstruye del codigo). Editar el grafo
   no cambia nada hasta que se reentrena, y mientras tanto las cinco aplicaciones se
   reconstruyen -- vigilan `src/` entero -- sirviendo un modelo del grafo anterior.
2. **`Variables_seleccion.xlsx` editado.** Decide que columnas entran a
   `procesar_dataset_completo`, o sea la forma de la matriz que el modelo aprendio.
3. **Un reentrenamiento sin sellar.** El `.pt` nuevo y `manifest.sha256.json` viejo
   dejan la guarda del modelo congelado en rojo sin decir por que.

Y una fuente que NO reentrena: `Variables_simular.xlsx` solo decide que ofrece el
panel -- rango, tipo y si el control es deslizador o selector --, no como se entreno.
Confundirla con las otras tres costaria 8 a 14 minutos de CPU por editar una celda.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))
import estado_actualizacion as est  # noqa: E402


# ------------------------------------------------------------------ un arbol de mentira

def _arbol(tmp_path: Path) -> Path:
    """Un repositorio minimo: las cuatro fuentes y los tres derivados, con contenido."""
    for fuente in est.FUENTES:
        destino = tmp_path / fuente.ruta
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(f"contenido inicial de {fuente.ruta}", encoding="utf-8")
    for derivado in est.DERIVADOS:
        destino = tmp_path / derivado.ruta
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(f"contenido inicial de {derivado.ruta}", encoding="utf-8")
    modelo = tmp_path / est.CLAVE_MODELO
    modelo.parent.mkdir(parents=True, exist_ok=True)
    modelo.write_text("un modelo", encoding="utf-8")
    est.sellar(tmp_path)
    return tmp_path


def _mover(raiz: Path, ruta: str) -> None:
    destino = raiz / ruta
    destino.write_text(destino.read_text(encoding="utf-8") + " -- movido", encoding="utf-8")


def _claves(estado) -> list[str]:
    return [paso.clave for paso in estado.plan]


# ------------------------------------------------------------------ las cuatro fuentes

def test_las_cuatro_fuentes_existen_en_el_repositorio():
    faltan = [f.ruta for f in est.FUENTES if not (RAIZ / f.ruta).exists()]
    assert not faltan, f"la tabla nombra fuentes que no existen: {faltan}"


def test_las_tres_fuentes_del_modelo_reentrenan_y_la_del_panel_no():
    reentrenan = {f.ruta for f in est.FUENTES if f.reentrena}
    assert reentrenan == {
        "data/Indicadores_vano_v3.csv",
        "data/Variables_seleccion.xlsx",
        "src/chec_impacto/data/graph.py",
    }
    no_reentrenan = {f.ruta for f in est.FUENTES if not f.reentrena}
    assert no_reentrenan == {"data/Variables_simular.xlsx"}


def test_cada_fuente_dice_por_que_reentrena_o_por_que_no():
    sin_motivo = [f.ruta for f in est.FUENTES if len(f.porque.split()) < 5]
    assert not sin_motivo, (
        "una tabla que dice 'reentrena: si' sin decir por que se copia mal en la "
        f"proxima edicion: {sin_motivo}")


def test_todo_derivado_nombra_quien_lo_produce():
    huerfanos = [d.ruta for d in est.DERIVADOS if not d.produce.strip()]
    assert not huerfanos, f"un derivado sin productor no se puede regenerar: {huerfanos}"


# ------------------------------------------------------------------ el veredicto

def test_recien_sellado_esta_al_dia(tmp_path):
    raiz = _arbol(tmp_path)
    estado = est.estado(raiz)
    assert estado.veredicto == est.AL_DIA
    assert estado.plan == []


def test_sin_manifiesto_pide_sellar(tmp_path):
    raiz = _arbol(tmp_path)
    (raiz / est.RUTA_MANIFIESTO).unlink()
    estado = est.estado(raiz)
    assert estado.veredicto == est.SIN_SELLAR
    assert _claves(estado) == ["sellar"]


def test_el_csv_pide_reentrenar_y_rehacer_la_geometria(tmp_path):
    raiz = _arbol(tmp_path)
    _mover(raiz, "data/Indicadores_vano_v3.csv")
    estado = est.estado(raiz)
    assert estado.veredicto == est.REENTRENAR
    assert estado.fuentes_movidas == ["data/Indicadores_vano_v3.csv"]
    assert _claves(estado) == ["reentrenar", "geometria", "catalogo", "sellar",
                               "aplicaciones", "databricks"]


def test_el_grafo_base_pide_reentrenar(tmp_path):
    raiz = _arbol(tmp_path)
    _mover(raiz, "src/chec_impacto/data/graph.py")
    estado = est.estado(raiz)
    assert estado.veredicto == est.REENTRENAR
    assert "reentrenar" in _claves(estado)


def test_variables_seleccion_pide_reentrenar(tmp_path):
    raiz = _arbol(tmp_path)
    _mover(raiz, "data/Variables_seleccion.xlsx")
    estado = est.estado(raiz)
    assert estado.veredicto == est.REENTRENAR


def test_el_grafo_no_pide_rehacer_la_geometria(tmp_path):
    """La geometria KMeans sale del CSV y de nada mas: `exportar_geometria.py` no abre
    ni el grafo ni los dos catalogos."""
    raiz = _arbol(tmp_path)
    _mover(raiz, "src/chec_impacto/data/graph.py")
    assert "geometria" not in _claves(est.estado(raiz))


def test_variables_simular_no_reentrena_nada(tmp_path):
    raiz = _arbol(tmp_path)
    _mover(raiz, "data/Variables_simular.xlsx")
    estado = est.estado(raiz)
    assert estado.veredicto == est.SOLO_PANEL
    assert _claves(estado) == ["catalogo", "sellar", "aplicaciones", "databricks"]
    assert "reentrenar" not in _claves(estado)


def test_un_derivado_movido_a_solas_pide_sellar_no_reentrenar(tmp_path):
    """Alguien ya corrio el cuaderno: lo que falta es dejarlo escrito, no repetirlo."""
    raiz = _arbol(tmp_path)
    _mover(raiz, "data/models/mil_vano_ventana_v1.pt")
    estado = est.estado(raiz)
    assert estado.veredicto == est.SIN_SELLAR
    assert "reentrenar" not in _claves(estado)
    assert _claves(estado) == ["catalogo", "sellar", "aplicaciones", "databricks"]


def test_un_derivado_que_falta_se_nombra_y_se_pide_rehacer(tmp_path):
    raiz = _arbol(tmp_path)
    (raiz / "data/derived/bolsas_mil_full.joblib").unlink()
    estado = est.estado(raiz)
    assert estado.faltantes == ["data/derived/bolsas_mil_full.joblib"]
    assert "reentrenar" in _claves(estado)


def test_el_plan_termina_siempre_en_databricks(tmp_path):
    raiz = _arbol(tmp_path)
    for ruta in [f.ruta for f in est.FUENTES]:
        _mover(raiz, ruta)
        estado = est.estado(raiz)
        assert estado.plan[-1].clave == "databricks", (
            f"mover {ruta} dejo un plan que no termina subiendo: {_claves(estado)}")


def test_cada_paso_del_plan_trae_su_orden_y_su_porque(tmp_path):
    raiz = _arbol(tmp_path)
    _mover(raiz, "data/Indicadores_vano_v3.csv")
    for paso in est.estado(raiz).plan:
        assert paso.orden.strip(), f"el paso {paso.clave} no dice que ejecutar"
        assert len(paso.porque.split()) >= 5, f"el paso {paso.clave} no dice por que"


# ------------------------------------------------------------------ el sello

def test_sellar_graba_las_cuatro_fuentes_y_los_derivados(tmp_path):
    raiz = _arbol(tmp_path)
    manifiesto = json.loads((raiz / est.RUTA_MANIFIESTO).read_text(encoding="utf-8"))
    assert set(manifiesto["fuentes"]) == {f.ruta for f in est.FUENTES}
    assert set(manifiesto["derivados"]) == {d.ruta for d in est.DERIVADOS}


def test_la_huella_del_modelo_tiene_una_sola_casa(tmp_path):
    """`manifest.sha256.json` ya la guarda, y una guarda del repositorio la compara.
    Una segunda copia en `procedencia.json` seria una segunda verdad."""
    raiz = _arbol(tmp_path)
    manifiesto = json.loads((raiz / est.RUTA_MANIFIESTO).read_text(encoding="utf-8"))
    assert est.CLAVE_MODELO not in manifiesto["derivados"]
    assert est.CLAVE_MODELO not in manifiesto["fuentes"]


def test_sellar_actualiza_el_manifiesto_del_modelo_congelado(tmp_path):
    """Reentrenar deja en rojo `tests/test_frozen_model_guard.py` hasta que el sha
    del artefacto se vuelve a escribir. Es parte de sellar, no un paso aparte que se
    olvida."""
    raiz = _arbol(tmp_path)
    (raiz / est.CLAVE_MODELO).write_text("un modelo reentrenado", encoding="utf-8")
    est.sellar(raiz)
    grabado = json.loads((raiz / est.RUTA_MANIFIESTO_MODELO).read_text(encoding="utf-8"))
    assert grabado[est.CLAVE_MODELO] == est.huella(raiz / est.CLAVE_MODELO)


def test_sellar_deja_el_arbol_al_dia(tmp_path):
    raiz = _arbol(tmp_path)
    _mover(raiz, "data/Indicadores_vano_v3.csv")
    _mover(raiz, "data/models/mil_vano_ventana_v1.pt")
    est.sellar(raiz)
    assert est.estado(raiz).veredicto == est.AL_DIA


# ------------------------------------------------------------------ la linea de ordenes

def test_al_dia_sale_cero_y_pendiente_sale_uno(tmp_path, capsys):
    raiz = _arbol(tmp_path)
    assert est.main(["--raiz", str(raiz), "--json"]) == 0
    _mover(raiz, "data/Variables_simular.xlsx")
    assert est.main(["--raiz", str(raiz), "--json"]) == 1


def test_el_json_trae_veredicto_plan_y_fuentes(tmp_path, capsys):
    raiz = _arbol(tmp_path)
    _mover(raiz, "data/Indicadores_vano_v3.csv")
    est.main(["--raiz", str(raiz), "--json"])
    salida = json.loads(capsys.readouterr().out)
    assert salida["veredicto"] == est.REENTRENAR
    assert salida["fuentes_movidas"] == ["data/Indicadores_vano_v3.csv"]
    assert [p["clave"] for p in salida["plan"]][0] == "reentrenar"
    assert salida["plan"][0]["orden"]


def test_el_informe_legible_nombra_el_archivo_que_se_movio(tmp_path, capsys):
    raiz = _arbol(tmp_path)
    _mover(raiz, "src/chec_impacto/data/graph.py")
    est.main(["--raiz", str(raiz)])
    salida = capsys.readouterr().out
    assert "graph.py" in salida
    assert "reentrenar" in salida.lower()


def test_sellar_desde_la_linea_de_ordenes(tmp_path):
    raiz = _arbol(tmp_path)
    _mover(raiz, "data/Variables_simular.xlsx")
    assert est.main(["--raiz", str(raiz), "--sellar"]) == 0
    assert est.estado(raiz).veredicto == est.AL_DIA


# ------------------------------------------------------------------ el propio repositorio

def test_el_repositorio_trae_su_manifiesto_sellado():
    """Un clon nuevo tiene que poder contestar la pregunta sin correr nada primero."""
    assert (RAIZ / est.RUTA_MANIFIESTO).exists(), (
        f"falta {est.RUTA_MANIFIESTO}: sin el, `/actualizar` da todo por movido en un "
        "clon limpio y manda reentrenar sin motivo")
