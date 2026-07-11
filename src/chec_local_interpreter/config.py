from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_PATH = PROJECT_ROOT / "data" / "Indicadores_vano_v3.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports" / "interpretability" / "artifacts"

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


def llm_root() -> Path:
    return project_root() / "llm"


def prompt_assets_dir() -> Path:
    """Package-relative home for shared prompt templates/schemas.

    Survives install and does not depend on CWD/repo layout, unlike
    ``llm_root()`` (repo-root-relative, retired incrementally per
    ``sdd/retire-llm-directory``).
    """
    return Path(__file__).resolve().parent / "prompt_assets"


def agent_prompt_dir(agent_slug: str) -> Path:
    """Repo-root-relative home for a migrated agent's playbook prompts."""
    return project_root() / ".claude" / "skills" / agent_slug / "prompt"
