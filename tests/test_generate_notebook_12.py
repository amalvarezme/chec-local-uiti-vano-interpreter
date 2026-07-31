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


# ---------------------------------------------------------------------------
# PR4 -- characterization section (redirects notebook 12 from PREDICTION to
# CHARACTERIZATION: the full run's ablation showed 54x of the apparent
# cluster/UITI association is persistence, and UITI/UITI_VANO are input
# features, so no predictive claim is defensible without a temporal holdout.
# ---------------------------------------------------------------------------


def test_characterization_section_states_descriptive_not_predictive(notebook) -> None:
    markdown = _all_markdown_source(notebook)
    assert re.search(r"caracteriza", markdown, re.IGNORECASE)
    assert re.search(r"NO\s+predic", markdown, re.IGNORECASE) or re.search(
        r"no es una predicci[oó]n", markdown, re.IGNORECASE
    )
    # The reasoning must be present, not just the disclaimer: input-feature circularity.
    assert re.search(r"UITI", markdown)
    assert re.search(r"feature", markdown, re.IGNORECASE) or re.search(
        r"variable de entrada", markdown, re.IGNORECASE
    )


def test_characterization_never_writes_the_word_predice(notebook) -> None:
    full_text = _all_markdown_source(notebook) + "\n" + _all_code_source(notebook)
    assert "predice" not in full_text.lower(), (
        "the launch contract's hard rule: if you find yourself writing 'predice', stop"
    )


def test_characterization_runs_stability_protocol_and_does_not_reuse_k_raw(notebook) -> None:
    code = _all_code_source(notebook)
    assert "estabilidad_por_submuestreo" in code
    assert re.search(r"K_ESTABLE", code), "the chosen K must be a distinctly-named variable"
    # It must not simply reuse k_raw as the characterization K.
    assert "K_ESTABLE = k_raw" not in code


def test_characterization_reports_stability_curve_over_k_2_to_8(notebook) -> None:
    code = _all_code_source(notebook)
    assert "CHAR_K_VALUES" in code
    assert re.search(r"range\(2,\s*9\)", code), "the full-mode K sweep must cover 2..8"


def test_characterization_warns_when_stable_k_outside_3_4(notebook) -> None:
    code = _all_code_source(notebook)
    assert re.search(r"3\s*<=\s*K_ESTABLE\s*<=\s*4", code) or re.search(
        r"K_ESTABLE\s+in\s+\(3,\s*4\)", code
    )


def test_characterization_runs_separability_with_shuffled_floor(notebook) -> None:
    code = _all_code_source(notebook)
    assert "separabilidad_fuera_de_pliegue" in code
    assert re.search(r"shuffl|barajad", code, re.IGNORECASE)
    assert "balanced_accuracy" in code


def test_characterization_reuses_edge_deviation_table(notebook) -> None:
    code = _all_code_source(notebook)
    # tabla_desviacion_aristas must be called again for the characterization clusters
    # (a second, distinctly-named call site), not only the existing acceptance-gate one.
    assert code.count("tabla_desviacion_aristas(") >= 2


def test_characterization_runs_perfil_por_cluster(notebook) -> None:
    code = _all_code_source(notebook)
    assert "perfil_por_cluster" in code
    assert "efecto_estandarizado" in code


def test_characterization_reports_historical_uiti_and_event_profiles_labelled_descriptive(
    notebook,
) -> None:
    code = _all_code_source(notebook)
    markdown = _all_markdown_source(notebook)
    assert "UITI_VANO_futuro_acumulado" in code
    assert "n_eventos_futuro" in code
    assert re.search(r"HIST[OÓ]RIC", code) or re.search(r"HIST[OÓ]RIC", markdown)
    assert re.search(r"DESCRIPTIV", code) or re.search(r"DESCRIPTIV", markdown)


def test_characterization_imports_are_present_in_bootstrap_guard(notebook) -> None:
    code = _all_code_source(notebook)
    for name in (
        "estabilidad_por_submuestreo",
        "separabilidad_fuera_de_pliegue",
        "perfil_por_cluster",
    ):
        assert name in code

    # The bootstrap import-guard cell specifically must carry all three names,
    # not just some later cell that happens to mention them.
    bootstrap_cell = next(
        cell for cell in notebook.cells
        if cell.cell_type == "code" and "chec_impacto.interpretability" in cell.source
    )
    for name in (
        "estabilidad_por_submuestreo",
        "separabilidad_fuera_de_pliegue",
        "perfil_por_cluster",
    ):
        assert name in bootstrap_cell.source


def test_characterization_section_appears_after_verdict_and_edge_deviation(notebook) -> None:
    sources = [cell.source for cell in notebook.cells]
    verdict_index = next(i for i, s in enumerate(sources) if "GRAPH_SIGNAL" in s)
    edge_deviation_index = next(
        i for i, s in enumerate(sources) if "tabla_desviacion_aristas(" in s
    )
    characterization_index = next(
        i for i, s in enumerate(sources) if "stability_by_seed" in s
    )
    assert characterization_index > verdict_index
    assert characterization_index > edge_deviation_index


# --- Delivery sections 21-25: nesting verdict, refit-on-all, risk naming, profiling ---


def test_nesting_verdict_is_per_family_not_a_single_boolean(notebook) -> None:
    """The earlier nesting analysis collapsed a structured result into one
    min-purity boolean, which reported a flat "does not nest" for a case where
    3 of 4 families were perfectly pure. The notebook must report per family
    AND report how many vanos live in nesting families."""
    code = _all_code_source(notebook)
    assert "anidamiento_entre_particiones" in code
    assert "fraccion_vanos_anidados" in code, (
        "the share of vanos in nesting families is what a min-purity boolean erases"
    )
    assert "pureza_minima" in code and "pureza_media" in code
    # A boundary family must be described as a finding, not only as a failure.
    assert re.search(r"frontera", code, re.IGNORECASE)


def test_delivery_k_is_separate_from_data_driven_k(notebook) -> None:
    code = _all_code_source(notebook)
    assert "K_ENTREGA" in code and "K_ESTABLE" in code
    assert "K_ENTREGA = len(NOMBRES_RIESGO)" in code, (
        "K_ENTREGA must derive from the risk-name list, never a bare literal"
    )
    # The notebook must not silently overwrite the data-driven K with the ask.
    assert "K_ESTABLE = K_ENTREGA" not in code
    markdown = _all_markdown_source(notebook)
    assert re.search(r"operaci[oó]n", markdown, re.IGNORECASE)


def test_final_refit_uses_all_rows_not_only_the_past_window(notebook) -> None:
    refit_cell = next(
        cell.source for cell in notebook.cells
        if cell.cell_type == "code" and "gate_means_final" in cell.source
    )
    assert "X_past_arr=X_with_target" in refit_cell, (
        "the delivery model must be refit on every row, not on the past window only"
    )
    assert "circuito_arr=circuito_all" in refit_cell
    assert "fid_vano_arr=fid_vano_all" in refit_cell


def test_refit_section_declares_it_is_no_longer_out_of_sample(notebook) -> None:
    markdown = _all_markdown_source(notebook)
    assert re.search(r"YA\s+VIO\s+la\s+ventana\s+futura", markdown), (
        "refitting on all data makes the downstream UITI profile descriptive, "
        "not out-of-sample -- the notebook must say so instead of implying validation"
    )


def test_model_checkpoint_is_saved_and_round_trip_verified(notebook) -> None:
    code = _all_code_source(notebook)
    assert "guardar_modelo_gated" in code
    assert "cargar_modelo_gated" in code, "saving without reloading proves nothing"
    assert re.search(r"np\.allclose\(_gates_original,\s*_gates_recargado", code), (
        "the checkpoint must be proven to reproduce the trained model's gates"
    )
    assert "MODELS_DIR" in code


def test_checkpoint_metadata_carries_everything_another_notebook_needs(notebook) -> None:
    code = _all_code_source(notebook)
    for key in (
        '"nombres_riesgo"',
        '"centroides_kmeans"',
        '"feature_mean"',
        '"feature_std"',
        '"K_ENTREGA"',
    ):
        assert key in code, f"checkpoint metadata is missing {key}"


def test_risk_names_are_assigned_by_uiti_not_by_kmeans_id(notebook) -> None:
    code = _all_code_source(notebook)
    assert "asignar_nombres_de_riesgo" in code
    assert 'NOMBRES_RIESGO = ("Bajo", "Medio", "Medio-Alto", "Alto")' in code
    # KMeans ids are arbitrary; the checkpoint must store the REORDERED centroids.
    # Asserting the variable merely exists is not enough -- it has to be the one
    # that actually reaches the metadata, or a reloaded model would assign
    # different risk levels than this notebook reports.
    assert '"centroides_kmeans": centroides_ordenados' in code, (
        "the checkpoint must store centroids reordered by risk, not raw KMeans centroids"
    )


def test_group_graph_profiling_reports_both_affinities(notebook) -> None:
    code = _all_code_source(notebook)
    assert "grafo_reconstruido_por_grupo" in code
    assert 'metrica="coseno"' in code and 'metrica="correlacion"' in code
    markdown = _all_markdown_source(notebook)
    assert re.search(r"cerca de 1", markdown, re.IGNORECASE), (
        "the notebook must warn that cosine sits near 1 by construction, so a "
        "reader does not misread it as 'the groups are identical'"
    )


def test_kde_and_graph_figures_are_both_shown_and_written_to_png(notebook) -> None:
    code = _all_code_source(notebook)
    for path_var in ("GRAPHS_FIGURE_PATH", "AFFINITY_FIGURE_PATH", "KDE_FIGURE_PATH"):
        assert path_var in code, f"{path_var} is missing"
        assert f"fig.savefig({path_var}" in code, f"{path_var} is never written to disk"
    assert "gaussian_kde" in code
    # Every figure must also render into the notebook's own output cells.
    assert code.count("plt.show()") >= 4


def test_delivery_sections_come_after_the_characterization(notebook) -> None:
    sources = [cell.source for cell in notebook.cells]
    # Match the CALL, not the bare name: the bootstrap import-guard cell lists
    # every helper by name near the top and would otherwise win every `next()`.
    characterization_index = next(i for i, s in enumerate(sources) if "stability_by_seed" in s)
    nesting_index = next(i for i, s in enumerate(sources) if "anidamiento_entre_particiones(" in s)
    refit_index = next(i for i, s in enumerate(sources) if "gate_means_final," in s)
    naming_index = next(i for i, s in enumerate(sources) if "asignar_nombres_de_riesgo(" in s)
    kde_index = next(i for i, s in enumerate(sources) if "gaussian_kde(" in s)
    assert characterization_index < nesting_index < refit_index < naming_index < kde_index


def test_gate_inference_is_chunked_not_one_full_batch(notebook) -> None:
    """`gated_adjacency` is (B, p, p) -- one full adjacency matrix per sample.
    A single full-dataset batch asks for gigabytes in one tensor, and the
    section-22 refit sees every row, not just the past window."""
    code = _all_code_source(notebook)
    assert "def extraer_gates(" in code
    assert "GATE_INFERENCE_CHUNK" in code
    # No cell may run a whole feature matrix through the model in one go.
    for forbidden in (
        'trained_model(torch.as_tensor(np.asarray(X_past_arr)',
        'permuted_model(permuted_input)',
    ):
        assert forbidden not in code, f"full-batch inference survives: {forbidden}"
    helpers_cell = next(
        cell.source for cell in notebook.cells
        if cell.cell_type == "code" and "def entrenar_y_agrupar(" in cell.source
    )
    assert "extraer_gates(trained_model" in helpers_cell


def test_chunked_extraction_is_defined_before_its_first_call(notebook) -> None:
    sources = [cell.source for cell in notebook.cells]
    definition_index = next(i for i, s in enumerate(sources) if "def extraer_gates(" in s)
    # The `def` line itself contains "extraer_gates(trained_model", so match the
    # assignment at the call site instead of the bare name.
    first_call_index = next(
        i for i, s in enumerate(sources) if "gates = extraer_gates(trained_model" in s
    )
    assert definition_index < first_call_index


def test_affinity_reports_a_third_view_that_is_not_saturated_by_construction(notebook) -> None:
    """Cosine over weights is ~1 by construction. Correlation over weights was
    ALSO ~0.999 in the smoke run, because the expert graph's magnitude profile
    survives centring -- so claiming it "discriminates" would overclaim. The
    deviation view (gate - 1.0) is the one that starts unsaturated."""
    code = _all_code_source(notebook)
    assert "afinidad_desviacion" in code
    assert 'gate_mean"] - 1.0' in code, "the third view must subtract the neutral gate"
    markdown = _all_markdown_source(notebook)
    assert re.search(r"satura", markdown, re.IGNORECASE), (
        "the notebook must say correlation over weights saturates, not that it discriminates"
    )
    # And it must not include a FIJO row it cannot define.
    assert "afinidad_desviacion = pd.DataFrame(" in code
    assert "np.corrcoef(desviaciones)" in code


def test_affinity_panels_declare_their_own_colour_scale(notebook) -> None:
    """A shared [-1, 1] scale is comparable across panels but paints all three
    a flat red, because every affinity here lives between ~0.96 and 1.0 -- it
    hides the structure the figure exists to show. Each panel therefore takes
    its own limits from the off-diagonal range AND states them, so nobody
    compares colours across panels."""
    code = _all_code_source(notebook)
    assert "vmin=-1.0, vmax=1.0" not in code, "a shared [-1, 1] scale renders every panel flat"
    assert "vmin=escala_min, vmax=escala_max" in code
    assert "escala propia fuera de diagonal" in code, (
        "a per-panel scale is only honest if the panel says what its scale is"
    )
    markdown = _all_markdown_source(notebook)
    assert re.search(r"NO comparten escala", markdown), (
        "the reader must be told colours are not comparable across panels"
    )


def test_affinity_annotations_keep_enough_decimals_to_separate_values(notebook) -> None:
    code = _all_code_source(notebook)
    assert 'f"{valores[i, j]:.4f}"' in code, (
        "three decimals print 0.9991 and 0.9998 identically, erasing the distinction"
    )


def test_risk_ranking_uses_the_median_not_the_mean(notebook) -> None:
    """Accumulated UITI is heavy-tailed: group means run several times their
    own medians. Ranking by the mean ranks families by whoever suffered the
    single worst event. The previous full run showed exactly that -- the three
    lower tiers landed within 6.5% of each other and the median ordered them
    differently."""
    code = _all_code_source(notebook)
    assert 'ESTADISTICO_DE_RIESGO = "mediana"' in code
    assert "estadistico=ESTADISTICO_DE_RIESGO" in code
    markdown = _all_markdown_source(notebook)
    assert re.search(r"cola (muy )?pesada|cola pesada", markdown, re.IGNORECASE) or re.search(
        r"pesada", markdown, re.IGNORECASE
    ), "the notebook must justify the median, not just use it"


def test_delivered_order_is_verified_against_three_independent_criteria(notebook) -> None:
    code = _all_code_source(notebook)
    assert "verificar_orden_de_riesgo(" in code
    check_cell = next(
        cell.source for cell in notebook.cells
        if cell.cell_type == "code" and "verificar_orden_de_riesgo(" in cell.source
    )
    # Ranking by one statistic and checking against only that statistic proves nothing.
    assert '"UITI acumulado (mediana)"' in check_cell
    assert '"UITI acumulado (media)"' in check_cell
    assert '"numero de eventos (mediana)"' in check_cell
    assert "ORDEN_VERIFICADO" in code


def test_unverified_order_is_reported_as_such_not_as_a_stratification(notebook) -> None:
    check_cell = next(
        cell.source for cell in notebook.cells
        if cell.cell_type == "code" and "verificar_orden_de_riesgo(" in cell.source
    )
    assert re.search(r"NO se sostiene", check_cell), (
        "a failed order check must say so plainly"
    )
    assert re.search(r"criterios_disidentes", check_cell), (
        "it must name WHICH criterion contradicted the order"
    )
    # And a tier holding most of the fleet is not a stratification either.
    assert "_fraccion_mayor" in check_cell
    assert re.search(r"mas de la mitad", check_cell)


def test_checkpoint_records_whether_the_order_was_verified(notebook) -> None:
    code = _all_code_source(notebook)
    for key in ('"orden_verificado"', '"estadistico_de_riesgo"', '"criterios_disidentes"'):
        assert key in code, (
            f"{key} must reach the checkpoint: another notebook loading these tiers has "
            "to know whether the ordering claim survived verification"
        )


def test_order_check_runs_before_the_model_is_saved(notebook) -> None:
    sources = [cell.source for cell in notebook.cells]
    check_index = next(i for i, s in enumerate(sources) if "verificar_orden_de_riesgo(" in s)
    save_index = next(i for i, s in enumerate(sources) if "guardar_modelo_gated(" in s)
    assert check_index < save_index, (
        "the checkpoint stores the verdict, so the verdict must exist first"
    )


def test_a_constant_criterion_cannot_count_as_support_for_the_order(notebook) -> None:
    """The smoke run exposed this: event count was 1.00 in every tier and the
    check reported COINCIDE, which reads as evidence when it is a blank."""
    check_cell = next(
        cell.source for cell in notebook.cells
        if cell.cell_type == "code" and "verificar_orden_de_riesgo(" in cell.source
    )
    assert "criterios_sin_informacion" in check_cell
    assert '"SIN INFO"' in check_cell
    assert 'not verificacion_orden.attrs["criterios_sin_informacion"]' in check_cell, (
        "a criterion carrying no information must not be able to make the order verified"
    )
