from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_PATH = PROJECT_ROOT / "data" / "Indicadores_vano_v3.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports" / "reportescircuitos" / "artifacts"

# El artefacto que el simulador y el informe cargan es `mil_vano_ventana_v1.pt`,
# bajo este directorio. Solo se LEE: este proyecto no entrena en tiempo de
# ejecucion.
DEFAULT_MODEL_DIR = PROJECT_ROOT / "data" / "models"
DEFAULT_VARIABLES_SELECCION_PATH = PROJECT_ROOT / "data" / "Variables_seleccion.xlsx"

PROMPT_VERSION = "uiti-vano-explanation-v1"
SCHEMA_VERSION = "uiti-vano-output-schema-v1"

# Aqui vivian los ocho umbrales de la deteccion de PUNTOS CRITICOS -- `HIGH_ROBUST_Z`,
# `DELTA_ROBUST_Z`, `HIGH_PERCENTILE`, `TOP_CONTRIBUTOR_PCT`, `SUSTAINED_PERCENTILE`,
# `SUSTAINED_MIN_DAYS`, `MAX_CRITICAL_POINTS`, `MAX_CRITICAL_POINTS_CEILING` -- y la
# clase `CriticalityThresholds` que los agrupaba.
#
# Esa deteccion se retiro con el camino MGCECDL: el informe se apoya en el ranking del
# cuaderno 02 y en el diagnostico del 06, y la unidad de los dos es la VENTANA. Los
# umbrales quedaron sin un solo lector. El bucle estaba cerrado sobre si mismo: el unico
# uso de tres de ellos era el reexport de `__init__.py`, que nadie importaba, y el de los
# otros cinco era la dataclass, que tampoco usaba nadie. Un `MAX_CRITICAL_POINTS_CEILING`
# no tenia ni eso.

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


