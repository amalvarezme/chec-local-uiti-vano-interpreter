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


def test_generator_labels_exposure_severity_columns_adjacent_to_value(notebook):
    source = _all_code_source(notebook)
    assert "CAPACIDAD_NOMINAL" in source
    assert "PROMEDIO_KWH_TRF" in source
    assert re.search(r"exposici[oó]n.*severidad|severidad.*exposici[oó]n", source, re.IGNORECASE)
    # CNT_VN is exempt from the exposure/severity family: the tuple of columns that
    # DOES carry the label must not include it.
    tuple_match = re.search(r"COLUMNAS_EXPOSICION_SEVERIDAD\s*=\s*\(([^)]*)\)", source)
    assert tuple_match, "expected a COLUMNAS_EXPOSICION_SEVERIDAD tuple defining the family"
    assert "CNT_VN" not in tuple_match.group(1)


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
    assert NOTEBOOK_10_PATH.name.startswith("10_")
    assert NOTEBOOK_10_PATH.parent.name == "project_flow"


def test_generator_never_edits_upstream_notebooks_or_variable_selection(tmp_path):
    watched_paths = [
        "notebooks/project_flow/01.2_uiti_vano_kmeans.ipynb",
        "notebooks/project_flow/01.3_uiti_vano_trayectorias_circuitos.ipynb",
        "notebooks/project_flow/01.4_uiti_vano_trayectorias_vano.ipynb",
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
    # whenever someone had legitimate uncommitted edits to 01.3/01.4 -- observed once
    # for real, when a concurrent session was editing 01.4 while the suite ran.
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
        "generating notebook 10 must never modify 01.2/01.3/01.4 or the variable "
        f"selection, but these changed: {changed}"
    )


def test_generator_touches_no_training_package_files():
    diff = subprocess.run(
        ["git", "diff", "--stat", "--", "src/chec_impacto/training"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    assert diff == ""
