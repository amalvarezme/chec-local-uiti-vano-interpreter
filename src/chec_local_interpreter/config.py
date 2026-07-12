from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_PATH = PROJECT_ROOT / "data" / "Indicadores_vano_v3.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports" / "interpretability" / "artifacts"

# MGCECDL/SHAP simulator artifacts (read-only: never trained/searched by this
# project's runtime code, only loaded from what already exists on disk).
DEFAULT_MODEL_DIR = PROJECT_ROOT / "data" / "models"
DEFAULT_MODEL_BASENAME = "mgcecdl_classifier_best.zip"
DEFAULT_OPTUNA_STUDY_PATH = (
    PROJECT_ROOT / "data" / "optuna" / "mgcecdl_classification_feature_attention_params.journal"
)
DEFAULT_VARIABLES_SELECCION_PATH = PROJECT_ROOT / "data" / "Variables_seleccion.xlsx"

# Mirrors the notebook's own `SHAP_RANDOM_STATE` (deprecated
# `notebooks/core/02_local_uiti_vano_interpretability_v3.ipynb`), threaded
# explicitly into every `KernelShapTopVarsExtractor(...)` call for
# reproducible SHAP background sampling and ranking.
SHAP_RANDOM_STATE = 42

PROMPT_VERSION = "uiti-vano-explanation-v1"
SCHEMA_VERSION = "uiti-vano-output-schema-v1"

HIGH_ROBUST_Z = 3.0
DELTA_ROBUST_Z = 3.0
HIGH_PERCENTILE = 0.97
TOP_CONTRIBUTOR_PCT = 0.10
SUSTAINED_PERCENTILE = 0.80
SUSTAINED_MIN_DAYS = 3
MAX_CRITICAL_POINTS = 5

REQUIRED_COLUMNS = ("CIRCUITO", "FECHA", "UITI_VANO")

ID_COLUMNS = {
    "CIRCUITO",
    "FID_SW",
    "COD_EQ_PROTEGE",
    "FID_VANO",
    "COD_CAUSA",
    "DESC_CAUSA",
    "COD_APOYO_FIN",
    "FID_APOYO_FIN",
    "FID_TRAFO",
    "CODIGO",
}


@dataclass(frozen=True)
class CriticalityThresholds:
    high_robust_z: float = HIGH_ROBUST_Z
    delta_robust_z: float = DELTA_ROBUST_Z
    high_percentile: float = HIGH_PERCENTILE
    top_contributor_pct: float = TOP_CONTRIBUTOR_PCT
    sustained_percentile: float = SUSTAINED_PERCENTILE
    sustained_min_days: int = SUSTAINED_MIN_DAYS
    max_points: int = MAX_CRITICAL_POINTS


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def prompt_assets_dir() -> Path:
    """Package-relative home for shared prompt templates/schemas.

    Survives install and does not depend on CWD/repo layout. Replaces the
    retired, repo-root-relative ``llm_root()`` resolver (removed in
    ``sdd/retire-llm-directory`` Slice E, once the residual ``llm/`` tree was
    deleted).
    """
    return Path(__file__).resolve().parent / "prompt_assets"


def agent_prompt_dir(agent_slug: str) -> Path:
    """Repo-root-relative home for a migrated agent's playbook prompts."""
    return project_root() / ".claude" / "skills" / agent_slug / "prompt"


def _modelo_mas_reciente(model_dir: str | Path, base_name: str) -> Path:
    """Return "the" model file among several dated candidates under `model_dir`.

    Ported from the notebook precedent (`notebooks/inference/04_mgcecdl_performance.ipynb`
    and `notebooks/core/02_local_uiti_vano_interpretability_v3.ipynb`, deprecated in
    place): glob `{stem}*{suffix}` from `base_name` and deterministically pick
    the lexicographically last candidate (`sorted(candidates)[-1]`).

    Raises `FileNotFoundError` if no candidate exists — callers that need a
    graceful "no model available" degrade path (R3 gap shape) catch this
    explicitly rather than this function silently returning `None`.
    """
    model_dir = Path(model_dir)
    stem = Path(base_name).stem
    suffix = Path(base_name).suffix
    candidates = sorted(model_dir.glob(f"{stem}*{suffix}"))
    if not candidates:
        raise FileNotFoundError(f"No se encontro {base_name} en {model_dir}.")
    return candidates[-1]
