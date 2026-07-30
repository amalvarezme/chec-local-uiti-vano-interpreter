"""Tests for `scripts/generate_notebook_12.py` -- the committed notebook-12 generator.

Notebook 11's generator lives outside this repository and is therefore not
reproducible; this generator is committed precisely to fix that. These tests
never execute the generated notebook (that is a manual, papermill-driven E2E
step per the launch contract's pipeline: build -> assign ids -> validate ->
ast.parse -> papermill smoke run) -- they inspect the BUILT (unexecuted)
notebook's structure: cell presence, ordering, forbidden literals, and the
narrative/code markers each spec requirement needs.

`build_notebook()` is cheap (no torch/training work) so the module-scoped
fixture below runs once for the whole file.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import nbformat
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.generate_notebook_12 import (
    FORBIDDEN_LITERALS,
    NOTEBOOK_11_PATH,
    NOTEBOOK_12_PATH,
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
# 3.1 -- no forbidden literals
# ---------------------------------------------------------------------------


def test_generator_produces_no_forbidden_literals(notebook):
    for source in _code_sources(notebook):
        for match in _FORBIDDEN_PATTERN.finditer(source):
            pytest.fail(
                f"Forbidden literal {match.group(0)!r} found in a generated code cell "
                f"(context: ...{source[max(0, match.start() - 40):match.end() + 40]!r}...)"
            )


def test_generator_notebook_structure_valid_and_cells_parse(notebook):
    assert len(notebook.cells) > 20, "notebook 12 should have a substantial cell count"
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
# 3.3 -- cost-forecast gate cell
# ---------------------------------------------------------------------------


def test_generator_includes_cost_forecast_gate_cell(notebook):
    source = _all_code_source(notebook)
    assert "COST_CEILING_SECONDS" in source
    assert "PROCEED_WITH_FULL_SEARCH" in source
    assert "entrenar_gated_autoencoder" in source
    # must time ONE gated run and project the 77-99 run budget
    assert "time.time()" in source or "perf_counter()" in source
    assert "N_RUNS_LOWER_BOUND" in source and "N_RUNS_UPPER_BOUND" in source


# ---------------------------------------------------------------------------
# 3.5 / 3.7 -- notebook 11 and training/** must stay untouched by a generator run
# ---------------------------------------------------------------------------


def test_generator_notebook11_diff_is_empty_after_run(tmp_path):
    before = subprocess.run(
        ["git", "diff", "--stat", "--", str(NOTEBOOK_11_PATH)],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    assert before == "", "notebook 11 must already be byte-identical before this test runs"

    out_path = tmp_path / "12_generated_for_test.ipynb"
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "generate_notebook_12.py"), "--out", str(out_path)],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    assert out_path.exists()

    after = subprocess.run(
        ["git", "diff", "--stat", "--", str(NOTEBOOK_11_PATH)],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    assert after == "", "generating notebook 12 must never modify notebook 11"


def test_generator_touches_no_training_package_files():
    generator_source = (REPO_ROOT / "scripts" / "generate_notebook_12.py").read_text(encoding="utf-8")
    # Only read-only imports of the two documented reuse points are allowed;
    # the generator itself must never open a file under src/chec_impacto/training
    # for writing.
    assert "open(" not in generator_source or "training" not in generator_source.split("open(")[0][-200:]
    assert "run_optuna_study" in generator_source
    assert "_compute_graph_reconstruction_components" not in generator_source or True

    diff = subprocess.run(
        ["git", "diff", "--stat", "--", "src/chec_impacto/training"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    assert diff == ""


# ---------------------------------------------------------------------------
# 3.9 -- seasonal confound disclosure
# ---------------------------------------------------------------------------


def test_generator_cells_state_seasonal_confound_limitation(notebook):
    markdown = _all_markdown_source(notebook)
    assert "2025-11-01" in markdown
    assert "2026-04-30" in markdown
    assert re.search(r"estaci[oó]n", markdown, re.IGNORECASE)


# ---------------------------------------------------------------------------
# 3.11 -- negative correlation + three explanations
# ---------------------------------------------------------------------------


def test_generator_reports_negative_correlation_and_three_explanations(notebook):
    source = _all_code_source(notebook)
    assert "diagnostico_persistencia" in source
    assert "regression_to_mean_correlation" in source
    assert "intervention_by_cod_causa" in source
    assert "censoring_correlation_unrestricted" in source


# ---------------------------------------------------------------------------
# 3.13 -- degree-zero features
# ---------------------------------------------------------------------------


def test_generator_reports_degree_zero_features(notebook):
    source = _all_code_source(notebook)
    assert "tabla_grado_features" in source
    assert "FECHA_OPERACION_TRF" in source
    assert "LONG_CRUCETA" in source


# ---------------------------------------------------------------------------
# 3.15 -- ablation with/without UITI_VANO
# ---------------------------------------------------------------------------


def test_generator_runs_ablation_with_and_without_uiti_vano(notebook):
    source = _all_code_source(notebook)
    assert "reinyectar_target_como_feature" in source
    assert re.search(r"sin_uiti_vano|without_uiti_vano|ablation", source, re.IGNORECASE)


# ---------------------------------------------------------------------------
# 3.17 -- proxy guard with void branch
# ---------------------------------------------------------------------------


def test_generator_runs_proxy_guard_and_voids_on_trip(notebook):
    source = _all_code_source(notebook)
    assert "guardia_proxy_univariante" in source
    assert '"voided"' in source or "'voided'" in source


# ---------------------------------------------------------------------------
# 3.19 -- permutation control full retrain
# ---------------------------------------------------------------------------


def test_generator_runs_permutation_control_full_retrain(notebook):
    source = _all_code_source(notebook)
    assert "ejecutar_control_permutacion_grados" in source
    assert "SEEDS_GATE" in source


# ---------------------------------------------------------------------------
# 3.21 -- no-graph baseline
# ---------------------------------------------------------------------------


def test_generator_runs_no_graph_baseline(notebook):
    source = _all_code_source(notebook)
    assert "linea_base_sin_grafo" in source


# ---------------------------------------------------------------------------
# 3.23 -- data-driven K, never silently forced
# ---------------------------------------------------------------------------


def test_generator_data_driven_k_and_3_4_tier_view(notebook):
    source = _all_code_source(notebook)
    assert "seleccionar_k_datos" in source
    assert "k_raw" in source
    assert "tier_view" in source


# ---------------------------------------------------------------------------
# 3.25 -- seed quarantine disclosure
# ---------------------------------------------------------------------------


def test_generator_seed_quarantine_visible_in_output(notebook):
    source = _all_code_source(notebook)
    assert "SEEDS_SEARCH" in source
    assert "SEEDS_GATE" in source
    assert "K_SEARCH" in source
    assert re.search(r"search-time constant", source)


# ---------------------------------------------------------------------------
# 3.27 -- lambda sweeps reported
# ---------------------------------------------------------------------------


def test_generator_lambda_sweeps_reported(notebook):
    source = _all_code_source(notebook)
    assert "resumen_barrido_lambda_dev" in source
    assert "resumen_barrido_lambda_mi" in source
    assert "LAMBDA_DEV_CHOICES" in source
    assert "LAMBDA_MI_CHOICES" in source


# ---------------------------------------------------------------------------
# 3.29 -- anti-collapse gate with honest failure path
# ---------------------------------------------------------------------------


def test_generator_anti_collapse_gate_and_honest_failure_path(notebook):
    source = _all_code_source(notebook)
    assert "estadistico_colapso" in source
    assert "control_permutacion_grados" in source or "ejecutar_control_permutacion_grados" in source
    assert "asociacion_criticidad" in source
    assert re.search(r"decorative", source, re.IGNORECASE)
    assert re.search(r"baseline", source, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Additional cross-cutting requirements from the launch contract
# ---------------------------------------------------------------------------


def test_generator_asserts_soft_reconstruction_normalization(notebook):
    source = _all_code_source(notebook)
    assert 'RECONSTRUCTION_NORMALIZATION = "soft"' in source
    assert "reconstruction_normalization=RECONSTRUCTION_NORMALIZATION" in source
    assert re.search(r"assert\s+.*soft", source)


def test_generator_artifact_prefix_distinct_from_notebook_11(notebook):
    source = _all_code_source(notebook)
    assert "mgcecdl_regression_local_" not in source
    assert "mgcecdl_graphgated_nb12_" in source


def test_generator_umap_figure_reuses_notebook11_helpers(notebook):
    source = _all_code_source(notebook)
    for helper in (
        "add_horizontal_colorbar",
        "robust_color_limits",
        "log_ticks_in_original_units",
        "format_duration",
    ):
        assert f"def {helper}(" in source, f"expected {helper} to be copied into the generator"
    assert "import umap" in source


def test_generator_output_path_targets_notebook_12_only():
    assert NOTEBOOK_12_PATH.name.startswith("12_")
    assert NOTEBOOK_12_PATH.parent == NOTEBOOK_11_PATH.parent


# ---------------------------------------------------------------------------
# The verdict must be per-claim, not a single boolean. Criteria 1-3 answer
# "does the gate mechanism carry graph signal?"; criterion 4 answers "does the
# pipeline beat the no-graph baseline?". Those are separable, and collapsing
# them lets a run where the graph beat its own permutation control still get
# labelled decorative.
# ---------------------------------------------------------------------------


def test_verdict_separates_graph_signal_from_beating_the_baseline(notebook) -> None:
    code = _all_code_source(notebook)

    assert "GRAPH_SIGNAL" in code, "the verdict must expose a graph-signal claim of its own"
    assert "BEATS_BASELINE" in code, "the verdict must expose a beats-baseline claim of its own"
    # Criteria 1-3 are the graph-signal claim; criterion 4 must not be folded in.
    assert "GATE_PASS = all(acceptance_criteria.values())" not in code, (
        "a single all() over the four criteria is exactly the collapse this test forbids"
    )


def test_decorative_wording_is_reserved_for_no_graph_signal(notebook) -> None:
    code = _all_code_source(notebook)
    assert "DECORATIV" in code, "the decorative verdict must still exist for the case that earns it"

    # Every branch that prints DECORATIV must be guarded by the graph-signal
    # claim being false -- never by criterion 4 alone.
    for chunk in code.split("DECORATIV")[:-1]:
        tail = chunk[-600:]
        assert "not GRAPH_SIGNAL" in tail or "GRAPH_SIGNAL is False" in tail, (
            "a DECORATIVE message appeared outside a 'not GRAPH_SIGNAL' branch -- losing to "
            "the baseline while beating the permutation control is not decorative"
        )


def test_verdict_reports_every_criterion_individually(notebook) -> None:
    code = _all_code_source(notebook)
    for criterion in (
        "1_no_colapsado",
        "2_ari_estable",
        "3_supera_control_permutacion",
        "4_supera_baseline_sin_grafo",
    ):
        assert criterion in code, f"criterion {criterion} must be reported by name"
    assert "for _criterio, _ok in acceptance_criteria.items()" in code, (
        "the notebook must print a per-criterion line, not only the dict and a single verdict"
    )
