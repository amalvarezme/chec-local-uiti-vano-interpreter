"""Tests for `scripts/generate_notebook_10.py` -- the committed notebook-10
generator (PR5 of `sdd/notebook-10-mil-vano-ventana`).

Follows the same convention recovered from commit `28e8dfe`
(`scripts/generate_notebook_12.py` + `tests/test_generate_notebook_12.py`,
both since deleted when notebooks 02.1/11/12 were removed): these tests
inspect the BUILT (unexecuted) notebook's structure -- cell presence,
ordering, forbidden literals, narrative/code markers -- and NEVER execute the
generated notebook. Executing it means training the MIL model on 288,632
instance rows, which is explicitly out of scope for this test suite and for
the apply run that wrote it; that is a manual, user-authorized step.
"""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
import sys
from pathlib import Path

import nbformat
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.generate_notebook_10 import (
    FORBIDDEN_LITERALS,
    NOTEBOOK_10_PATH,
    assign_deterministic_cell_ids,
    build_notebook,
)

_FORBIDDEN_PATTERN = re.compile(r"(?<![\w.])(" + "|".join(FORBIDDEN_LITERALS) + r")(?![\w])")


@pytest.fixture(scope="module")
def notebook():
    nb = build_notebook()
    assign_deterministic_cell_ids(nb)
    return nb


def _code_sources(nb) -> list[str]:
    return [cell.source for cell in nb.cells if cell.cell_type == "code"]


def _markdown_sources(nb) -> list[str]:
    return [cell.source for cell in nb.cells if cell.cell_type == "markdown"]


def _all_code_source(nb) -> str:
    return "\n".join(_code_sources(nb))


def _all_markdown_source(nb) -> str:
    return "\n".join(_markdown_sources(nb))


# ---------------------------------------------------------------------------
# Structure + forbidden literals (p must never be hardcoded; E == 64 IS an
# intentional, required, printed assertion per design's Assertion Placement
# table -- so 64 is NOT in FORBIDDEN_LITERALS)
# ---------------------------------------------------------------------------


def test_generator_produces_no_forbidden_literals(notebook):
    for source in _code_sources(notebook):
        for match in _FORBIDDEN_PATTERN.finditer(source):
            pytest.fail(
                f"Forbidden literal {match.group(0)!r} found in a generated code cell "
                f"(context: ...{source[max(0, match.start() - 40):match.end() + 40]!r}...)"
            )


def test_generator_notebook_structure_valid_and_cells_parse(notebook):
    assert len(notebook.cells) > 15, "notebook 10 should have a substantial cell count"
    nbformat.validate(notebook)
    for cell in notebook.cells:
        assert "id" in cell and cell["id"], "every cell must carry a deterministic id"
        if cell.cell_type == "code":
            ast.parse(cell.source)


def test_generator_mode_parameter_cell_is_papermill_tagged(notebook):
    parameter_cells = [
        cell
        for cell in notebook.cells
        if cell.cell_type == "code" and "parameters" in cell.get("metadata", {}).get("tags", [])
    ]
    assert parameter_cells, "exactly one papermill parameters cell must be tagged 'parameters'"
    assert any('mode = "smoke"' in cell.source for cell in parameter_cells)


# ---------------------------------------------------------------------------
# Mandatory self-timing forecast cell, BEFORE any full training run
# ---------------------------------------------------------------------------


def test_generator_includes_cost_forecast_gate_cell(notebook):
    source = _all_code_source(notebook)
    assert "COST_CEILING_SECONDS" in source
    assert "entrenar_mil" in source
    assert "time.time()" in source or "perf_counter()" in source
    assert re.search(r"PROCEDER_CON_ENTRENAMIENTO_COMPLETO", source)


def test_forecast_cell_precedes_the_full_cv_training_loop(notebook):
    code_cells = [cell.source for cell in notebook.cells if cell.cell_type == "code"]
    forecast_index = next(
        i for i, src in enumerate(code_cells) if "COST_CEILING_SECONDS" in src and "time.time()" in src
    )
    cv_loop_index = next(
        i for i, src in enumerate(code_cells) if "for fold_i, (train_idx, test_idx)" in src
    )
    assert forecast_index < cv_loop_index


# ---------------------------------------------------------------------------
# Population-level assertions belong to the notebook (design's Assertion
# Placement table), never to a unit test
# ---------------------------------------------------------------------------


def test_generator_asserts_population_level_measurements(notebook):
    source = _all_code_source(notebook)
    assert "111233" in source or "111_233" in source
    assert "288632" in source or "288_632" in source
    assert "0.527" in source or "52.7" in source
    assert re.search(r"uiti_acumulado", source, re.IGNORECASE) or "bag_index.y" in source


def test_generator_never_hardcodes_p_and_derives_it_at_runtime(notebook):
    source = _all_code_source(notebook)
    assert "len(features_inst)" in source or "X_inst_bolsas.shape[1]" in source
    assert "CodCausaEncoding" in source or "encoding.codigos_propios" in source


def test_generator_asserts_edge_count_and_cod_causa_sink(notebook):
    source = _all_code_source(notebook)
    assert "edge_index.n_edges" in source
    assert "== 64" in source
    assert "COD_CAUSA" in source


# ---------------------------------------------------------------------------
# Geometry-VALUE pinning addition (closes the residual risk in
# sdd/notebook-10-mil-vano-ventana/estado-ramas)
# ---------------------------------------------------------------------------


def test_generator_asserts_geometrias_sha1_pin(notebook):
    source = _all_code_source(notebook)
    assert "verificar_sha1_geometrias" in source
    assert "GEOMETRIAS_SHA1_ESPERADO" in source
    assert "sha1" in source.lower()


# ---------------------------------------------------------------------------
# Geometry re-sourcing (sdd/retire-base-apps-notebooks, D3b): the bootstrap
# cell must no longer depend on scripts/extract_geometrias_014.py, which is
# deleted. This must hold on a clean checkout with no data/derived/ present.
# ---------------------------------------------------------------------------


def test_generator_bootstrap_does_not_import_extract_geometrias_014(notebook):
    source = _all_code_source(notebook)
    assert "from scripts.extract_geometrias_014 import" not in source
    assert "extraer_geometrias_014" not in source


def test_generator_bootstrap_cell_runs_with_no_data_derived_dir(tmp_path, monkeypatch):
    """The unconditional bootstrap `try:` (design D3b) must not raise
    ImportError/SystemExit on a clean checkout with no `data/derived/` --
    that used to be exactly where `extract_geometrias_014.py` broke it."""
    bootstrap_source = next(
        cell.source for cell in notebook_para_bootstrap() if "Guarda OK" in cell.source
    )
    # The bootstrap cell resolves its own project root and imports real PR1-4
    # modules; running it for real (not just grepping for the import line)
    # proves the ImportError/SystemExit branch is never reached.
    resultado = subprocess.run(
        [sys.executable, "-c", bootstrap_source],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert resultado.returncode == 0, resultado.stderr
    assert "Guarda OK" in resultado.stdout


def notebook_para_bootstrap():
    nb = build_notebook()
    return [cell for cell in nb.cells if cell.cell_type == "code"]


# ---------------------------------------------------------------------------
# Three baselines + A1 bar + negative-result path + per-circuit breakdown
# ---------------------------------------------------------------------------


def test_generator_runs_three_baselines_and_a1_bar(notebook):
    source = _all_code_source(notebook)
    for symbol in (
        "baseline_mayoritaria",
        "baseline_estructural",
        "baseline_persistencia",
        "evaluar_arms",
        "BARRA_ACEPTACION_A1_PUNTOS",
        "subconjunto_variacion_intravano",
    ):
        assert symbol in source, f"expected {symbol!r} to be used by the generated notebook"


def test_generator_reports_desglose_por_circuito(notebook):
    source = _all_code_source(notebook)
    assert "desglose_por_circuito" in source


# ---------------------------------------------------------------------------
# Per-epoch / per-fold progress monitoring wiring
# ---------------------------------------------------------------------------


def _extract_balanced_calls(source: str, call_prefix: str) -> list[str]:
    """Extract each `call_prefix(...)` call's full source, matching parens to
    arbitrary nesting depth (a single-level regex undercounts calls whose
    arguments themselves contain nested calls)."""
    calls = []
    start = 0
    while True:
        idx = source.find(call_prefix, start)
        if idx == -1:
            break
        depth = 0
        i = idx + len(call_prefix) - 1  # position of the opening '('
        for i in range(i, len(source)):
            if source[i] == "(":
                depth += 1
            elif source[i] == ")":
                depth -= 1
                if depth == 0:
                    break
        calls.append(source[idx : i + 1])
        start = i + 1
    return calls


def test_generator_wires_verbose_into_every_entrenar_mil_call(notebook):
    source = _all_code_source(notebook)
    calls = _extract_balanced_calls(source, "entrenar_mil(")
    assert len(calls) >= 2, "expected entrenar_mil to be called at least twice (fold fit + full fit)"
    for call in calls:
        assert "verbose=True" in call, f"entrenar_mil call missing verbose=True: {call}"


def test_generator_cv_loop_prints_per_fold_progress_and_eta(notebook):
    code_cells = [cell.source for cell in notebook.cells if cell.cell_type == "code"]
    cv_loop_source = next(
        src for src in code_cells if "for fold_i, (train_idx, test_idx)" in src
    )
    assert "perf_counter()" in cv_loop_source or "time.time()" in cv_loop_source
    assert re.search(r"N_SPLITS", cv_loop_source)
    assert re.search(r"format_duration", cv_loop_source)
    # Fold-level ETA must be derived from the mean fold time observed so far.
    assert re.search(r"segundos_acumulados_pliegues\s*/\s*pliegues_completados", cv_loop_source)


def test_generator_states_negative_result_path_explicitly(notebook):
    source = _all_code_source(notebook)
    assert "veredicto" in source
    markdown = _all_markdown_source(notebook)
    assert re.search(r"resultado negativo|negative", markdown, re.IGNORECASE)


# ---------------------------------------------------------------------------
# A3 / A4 / A6 wiring
# ---------------------------------------------------------------------------


def test_generator_runs_proxy_guard_a3(notebook):
    source = _all_code_source(notebook)
    assert "guardia_proxy_univariante_mil" in source


def test_generator_runs_collapse_detection_a4(notebook):
    source = _all_code_source(notebook)
    assert "grafo_por_grupo_si_no_colapsado" in source


def test_generator_runs_temporal_block_diagnostic_a6_as_secondary(notebook):
    source = _all_code_source(notebook)
    assert "particion_bloque_temporal" in source
    assert "evaluar_diagnostico_temporal" in source
    markdown = _all_markdown_source(notebook)
    assert re.search(r"secundari|diagn[oó]stico", markdown, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Cross-cutting narrative requirements
# ---------------------------------------------------------------------------


def test_generator_no_emite_analisis_de_sensibilidad_en_el_cuaderno(notebook):
    """El cuaderno entrena y guarda; no explica el modelo.

    Aqui se afirmaba que el cuaderno delegara el pegamento SHAP -> Borda en
    `construir_ranking_borda`. Esa celda ya no existe: SHAP salio del proyecto y
    con el se fue el unico productor de relevancias que el cuaderno tenia.

    Lo que queda vigilado es la frontera, que es lo que de verdad se decidio: el
    analisis de sensibilidad NO vive en el cuaderno de entrenamiento sino en
    `mil_simulador_015` (`relevancia_hacia_uiti_minimo`, `plan_hacia_clase_minima`),
    donde lo consumen el simulador y `/report`. Sin esta prueba, la forma natural
    de "arreglar" un cuaderno que ya no explica nada seria volver a meterle un
    explicador dentro.

    Las afirmaciones de biblioteca que esta prueba tenia -- la composicion exacta
    de la familia exposicion/severidad -- se mudaron a
    tests/test_mil_ranking_borda.py, junto a las funciones que las sostienen.
    """
    source = _all_code_source(notebook)
    assert "import shap" not in source
    assert "KernelShapTopVarsExtractor" not in source
    assert "construir_ranking_borda" not in source, (
        "el cuaderno volvio a calcular un ranking de relevancias: el analisis de "
        "sensibilidad vive en mil_simulador_015, no aqui"
    )


def test_generator_states_observed_n_predicted_u_boundary(notebook):
    markdown = _all_markdown_source(notebook)
    assert re.search(r"observad", markdown, re.IGNORECASE)
    assert re.search(r"predich|predicci[oó]n", markdown, re.IGNORECASE)


def test_generator_notes_persistence_information_advantage(notebook):
    markdown = _all_markdown_source(notebook)
    assert re.search(r"informaci[oó]n.*(ventaj|adelant)|persistencia.*informaci[oó]n", markdown, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Untouched-notebooks / unchanged-selection guarantees
# ---------------------------------------------------------------------------


def test_generator_output_path_targets_notebook_10_only():
    assert NOTEBOOK_10_PATH.name.startswith("05_")
    assert NOTEBOOK_10_PATH.parent.name == "notebooks"


def test_generator_never_edits_upstream_notebooks_or_variable_selection(tmp_path):
    # Los cuadernos de tablero que se vigilaban aqui ya no existen
    # (`sdd/retire-base-apps-notebooks`, fases 3 y 4): su codigo vive en
    # `src/chec_tableros/`. Se vigilan los MODULOS en su lugar, que es lo que el
    # generador podria pisar ahora.
    #
    # El del simulador entra como sus DOS mitades. Es la que mas importa de la lista:
    # el generador escribe `notebooks/05_mil_vano_ventana.ipynb`, y el `05` produce el
    # modelo y el cache de bolsas que la derivacion del simulador consume. Un generador
    # que tocara ese lado escribiria sobre su propio consumidor.
    watched_paths = [
        "src/chec_tableros/agrupamiento.py",
        "src/chec_tableros/trayectorias_circuitos.py",
        "src/chec_tableros/trayectorias_vanos.py",
        "src/chec_tableros/simulador/derivacion.py",
        "src/chec_tableros/simulador/tablero.py",
        "data/Variables_seleccion.xlsx",
    ]
    # Every watched path must exist: a rename upstream has to fail this test loudly
    # rather than silently shrink the watch list and leave the file unguarded.
    missing = [p for p in watched_paths if not (REPO_ROOT / p).exists()]
    assert not missing, f"watched paths missing from this checkout: {missing}"
    existing = watched_paths

    # Compare the files' own bytes before and after, NOT `git diff` against HEAD.
    # The claim under test is "the generator does not modify these files", which is a
    # before/after delta. Asserting a clean working tree instead made this test fail
    # whenever someone had legitimate uncommitted edits to a watched file -- observed
    # once for real, when a concurrent session was editing one while the suite ran.
    def _digests() -> dict[str, str]:
        return {p: hashlib.sha256((REPO_ROOT / p).read_bytes()).hexdigest() for p in existing}

    before = _digests()

    out_path = tmp_path / "10_generated_for_test.ipynb"
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "generate_notebook_10.py"), "--out", str(out_path)],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    assert out_path.exists()

    after = _digests()
    changed = sorted(p for p in existing if before[p] != after[p])
    assert not changed, (
        "generar el cuaderno 05 nunca puede modificar los modulos de los tableros "
        f"ni la seleccion de variables, y estos cambiaron: {changed}"
    )


def test_generator_touches_no_training_package_files(tmp_path):
    """El generador LEE `chec_impacto.training`; no puede reescribirlo.

    Antes esto preguntaba `git diff --stat -- src/chec_impacto/training` y exigia la
    cadena vacia. Eso no mide al generador -- ni siquiera lo ejecuta --: mide si el arbol
    de trabajo tiene cambios sin confirmar en esa carpeta. Cualquier edicion legitima al
    paquete lo ponia rojo, y con el retiro de `MGCECDLClassifier` lo puso. Lo que el
    nombre promete es antes-y-despues alrededor de UNA corrida del generador, que es lo
    que se mide aqui.
    """
    paquete = REPO_ROOT / "src" / "chec_impacto" / "training"
    archivos = sorted(p for p in paquete.rglob("*.py"))
    assert archivos, "no se encontro el paquete de entrenamiento"

    def _huellas():
        return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in archivos}

    antes = _huellas()
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "generate_notebook_10.py"),
         "--out", str(tmp_path / "10_para_la_prueba.ipynb")],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )

    cambiados = sorted(p.name for p in archivos if antes[p] != _huellas()[p])
    assert not cambiados, f"el generador reescribio el paquete de entrenamiento: {cambiados}"


def test_arm_selecting_parameters_are_papermill_overridable(notebook):
    """The arm knobs must live in the `parameters` cell, not in the config cell.

    Attribution needs one run per arm (fusion on/off x class term on/off).
    With FUSION and LAMBDA_CLASE buried in a plain code cell, papermill's
    `-p` cannot reach them and every arm would need its own generated
    notebook -- three artifacts that can silently drift apart.
    """
    parameter_cells = [
        cell.source
        for cell in notebook.cells
        if cell.cell_type == "code" and "parameters" in cell.get("metadata", {}).get("tags", [])
    ]
    assert len(parameter_cells) == 1, "exactly one papermill parameters cell is expected"
    fuente = parameter_cells[0]

    for nombre in ("mode", "FUSION", "LAMBDA_CLASE", "TEMPERATURA_CLASE"):
        assert re.search(rf"^{nombre}\s*=", fuente, re.MULTILINE), (
            f"{nombre} debe definirse en la celda `parameters` para ser sobrescribible con -p"
        )

    # ...y NO redefinirse despues, o el override de papermill quedaria pisado.
    otras = "\n".join(
        cell.source
        for cell in notebook.cells
        if cell.cell_type == "code"
        and "parameters" not in cell.get("metadata", {}).get("tags", [])
    )
    for nombre in ("FUSION", "LAMBDA_CLASE", "TEMPERATURA_CLASE"):
        assert not re.search(rf"^{nombre}\s*=", otras, re.MULTILINE), (
            f"{nombre} se redefine fuera de la celda `parameters`: pisaria el -p de papermill"
        )


def test_generator_reports_the_per_class_breakdown_and_persists_oof(notebook):
    """A 40-minute run must leave more than a scalar and printed text.

    The out-of-fold predictions lived only in memory, so re-reading a
    finished run with any other metric -- a confusion matrix, per-class F1,
    a different threshold -- cost a full retrain. They are now written to
    `DERIVED_DIR`, keyed by arm so two configurations cannot overwrite each
    other's evidence.
    """
    source = _all_code_source(notebook)
    assert "desglose_por_clase" in source
    assert "formatear_desglose_por_clase" in source
    assert "np.savez_compressed" in source
    assert "oof_clase_modelo=oof_clase_modelo" in source
    # el nombre del artefacto debe distinguir el brazo
    assert re.search(r"oof_mil_\{mode\}_\{FUSION\}_clase\{LAMBDA_CLASE\}", source)


def test_per_class_breakdown_runs_after_the_a1_verdict(notebook):
    """It is a diagnostic OF the verdict, so it must not precede it."""
    code = [c.source for c in notebook.cells if c.cell_type == "code"]
    i_a1 = next(i for i, s in enumerate(code) if 'tabla_arms.attrs["veredicto"]' in s)
    i_clase = next(i for i, s in enumerate(code) if "desglose_por_clase(" in s)
    assert i_a1 < i_clase


def test_generator_contrasts_the_model_against_the_forest_in_u_space(notebook):
    """Class metrics alone cannot say WHERE the gap lives.

    Both arms regress the same `u` and both pass through the same frozen
    nearest-centroid rule, so a macro-F1 gap sits either in the regression
    or in the mapping. The notebook must report the u-space comparison and
    persist the forest's own `û`, or answering that costs a retrain.
    """
    source = _all_code_source(notebook)
    assert "contraste_u(" in source
    assert "predecir_u_estructural(" in source
    assert "oof_u_estructural=oof_u_estructural" in source


def test_generator_fits_the_forest_once_per_fold(notebook):
    """Capturing û must not double the baseline's cost.

    `baseline_estructural` fits its own RandomForest, so calling it AND
    `predecir_u_estructural` in the same fold would fit 200 trees twice per
    fold for one extra array.
    """
    source = _all_code_source(notebook)
    assert "baseline_estructural(" not in source, (
        "el bucle debe derivar la clase de predecir_u_estructural, no reajustar el bosque"
    )
    assert source.count("predecir_u_estructural(") == 1


# ---------------------------------------------------------------------------
# El dispositivo de entrenamiento
# ---------------------------------------------------------------------------


def _celda_del_dispositivo(nb) -> str:
    """La celda de importaciones, que es donde se resuelve `DEVICE`."""
    return next(s for s in _code_sources(nb) if "RANDOM_STATE = 42" in s)


def test_el_cuaderno_nunca_entrena_en_mps(notebook):
    """MPS es el peor camino para ESTE modelo, y esta medido: 19,63 s por epoca y
    pliegue contra 3,28 en CPU (49,1 min contra 8,2 en la validacion completa) y
    11.234 MB de pico contra 3.293. Con 150.926 parametros y lotes de 256 bolsas
    no hay con que amortizar el viaje de cada lote a la GPU.

    La prueba EJECUTA la celda con un `resolve_training_device` que devuelve
    `mps`, en vez de buscar el texto del guardia. Buscar el texto ata la prueba a
    la forma en que hoy esta escrito; ejecutarlo ata la prueba a lo unico que
    importa, que es con que dispositivo se acaba entrenando. Sin el guardia esta
    misma celda deja `DEVICE` en `mps` -- comprobado.
    """
    import torch

    espacio = {"resolve_training_device": lambda _pedido: torch.device("mps")}
    exec(_celda_del_dispositivo(notebook), espacio)  # noqa: S102
    assert espacio["DEVICE"].type == "cpu", (
        f"el cuaderno entrenaria en {espacio['DEVICE']}, que esta medido 6x mas lento"
    )


def test_cuda_se_respeta_si_la_hay(notebook):
    """El guardia descarta MPS, no toda GPU. CUDA no se midio aqui -- una NVIDIA
    de escritorio podria ganarle a la CPU --, asi que forzar CPU sobre ella seria
    inventar un resultado que nadie tomo."""
    import torch

    espacio = {"resolve_training_device": lambda _pedido: torch.device("cuda")}
    exec(_celda_del_dispositivo(notebook), espacio)  # noqa: S102
    assert espacio["DEVICE"].type == "cuda"


def test_no_afirma_que_la_cpu_tarda_horas(notebook):
    """El aviso viejo decia que con `mode='full'` la CPU podia tardar horas. Solo
    salia cuando NO habia GPU -- o sea, en Windows -- y describia el camino MAS
    RAPIDO de los tres medidos."""
    todo = _all_code_source(notebook) + _all_markdown_source(notebook)
    assert "puede tardar horas" not in todo
