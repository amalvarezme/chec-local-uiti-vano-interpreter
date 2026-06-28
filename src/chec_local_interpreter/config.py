from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATA_PATH = "../data/Indicadores_vano_v3.csv"
DEFAULT_OUTPUT_DIR = "reports/interpretability/artifacts"

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
