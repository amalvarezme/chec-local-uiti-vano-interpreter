from __future__ import annotations

import pytest

from chec_local_interpreter.config import (
    DEFAULT_MODEL_BASENAME,
    DEFAULT_MODEL_DIR,
    DEFAULT_OPTUNA_STUDY_PATH,
    DEFAULT_VARIABLES_SELECCION_PATH,
    PROJECT_ROOT,
    SHAP_RANDOM_STATE,
    _modelo_mas_reciente,
)


# ---------------------------------------------------------------------------
# Task 1.1 -- new paths/consts resolve under PROJECT_ROOT.
# ---------------------------------------------------------------------------


def test_default_model_dir_resolves_under_project_root():
    assert DEFAULT_MODEL_DIR == PROJECT_ROOT / "data" / "models"
    assert DEFAULT_MODEL_DIR.is_absolute()


def test_default_model_basename_is_the_known_artifact_name():
    assert DEFAULT_MODEL_BASENAME == "mgcecdl_classifier_best.zip"


def test_default_optuna_study_path_resolves_under_project_root():
    assert DEFAULT_OPTUNA_STUDY_PATH == (
        PROJECT_ROOT / "data" / "optuna" / "mgcecdl_classification_feature_attention_params.journal"
    )
    assert DEFAULT_OPTUNA_STUDY_PATH.is_absolute()


def test_default_variables_seleccion_path_resolves_under_project_root():
    assert DEFAULT_VARIABLES_SELECCION_PATH == PROJECT_ROOT / "data" / "Variables_seleccion.xlsx"
    assert DEFAULT_VARIABLES_SELECCION_PATH.is_absolute()


def test_shap_random_state_is_42():
    assert SHAP_RANDOM_STATE == 42


# ---------------------------------------------------------------------------
# Task 1.2 -- `_modelo_mas_reciente` picks the latest of several candidates.
# ---------------------------------------------------------------------------


def test_modelo_mas_reciente_picks_latest_of_three_fixture_filenames(tmp_path):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    for name in ("mgcecdl_classifier_best.zip", "mgcecdl_classifier_best_2025-01-01.zip", "mgcecdl_classifier_best_2026-06-01.zip"):
        (model_dir / name).write_bytes(b"stub")

    selected = _modelo_mas_reciente(model_dir, "mgcecdl_classifier_best.zip")

    assert selected == model_dir / "mgcecdl_classifier_best_2026-06-01.zip"


def test_modelo_mas_reciente_raises_when_no_candidate_exists(tmp_path):
    model_dir = tmp_path / "models"
    model_dir.mkdir()

    with pytest.raises(FileNotFoundError):
        _modelo_mas_reciente(model_dir, "mgcecdl_classifier_best.zip")
