"""Builder for the notebook-12-local variable-selection override.

Recovers `DURACION`, `TOT_USUS`, `UITI`, `COD_CAUSA` on top of the shared
`data/Variables_seleccion.xlsx` selection WITHOUT ever writing to that file.
The additional variables are read from a committed manifest
(`data/nb12_additional_variables.txt`), and the resulting derived selection
is written to a gitignored path under `data/derived/` (see `.gitignore`'s
`data/*` rule -- `data/derived/` has no explicit un-ignore, so it stays out
of version control) with a basename that is deliberately DISTINCT from the
shared file's.

That distinct-basename requirement guards a real silent-fallback hazard in
`procesar_dataset_completo` (`src/chec_impacto/data/preprocessing.py:64-68`):
when the given `path_variables_seleccion` does not exist, it silently
retries under `data/<basename>` instead of raising. A same-basename derived
file could therefore accidentally rebind onto the shared file with no error
at all. `assert_derived_selection_exists` guards the other half of that same
hazard: a caller that forgets to run this builder first must fail loudly
here, before `procesar_dataset_completo` ever gets a chance to silently
resolve to the wrong file.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_PATH = REPO_ROOT / "data" / "Variables_seleccion.xlsx"
DEFAULT_MANIFEST_PATH = REPO_ROOT / "data" / "nb12_additional_variables.txt"
DEFAULT_DERIVED_PATH = REPO_ROOT / "data" / "derived" / "nb12_variables_seleccion.xlsx"

_REQUIRED_SELECTION_COLUMNS = {"COLUMNA", "SELECCIÓN"}


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(manifest_path: Path) -> list[str]:
    lines = manifest_path.read_text(encoding="utf-8").splitlines()
    variables = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    if not variables:
        raise ValueError(f"Manifest {manifest_path} does not list any variables.")
    return variables


def build_nb12_variable_selection(
    source_path: Path = DEFAULT_SOURCE_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    derived_path: Path = DEFAULT_DERIVED_PATH,
) -> Path:
    """Build the notebook-12-local derived selection without ever touching `source_path`."""
    source_path = Path(source_path)
    manifest_path = Path(manifest_path)
    derived_path = Path(derived_path)

    if source_path.name == derived_path.name:
        raise ValueError(
            "derived_path must use a basename distinct from source_path's to avoid "
            "colliding with preprocessing.py's silent path-rebinding fallback "
            f"(source={source_path.name!r}, derived={derived_path.name!r})."
        )

    sha256_before = _sha256_of_file(source_path)

    selection = pd.read_excel(source_path)
    missing_columns = _REQUIRED_SELECTION_COLUMNS - set(selection.columns)
    if missing_columns:
        raise ValueError(f"{source_path} is missing required columns: {sorted(missing_columns)}")

    additional_variables = _read_manifest(manifest_path)
    known_columns = set(selection["COLUMNA"].astype(str).str.strip())
    unknown_variables = [v for v in additional_variables if v not in known_columns]
    if unknown_variables:
        raise ValueError(f"Manifest lists variables absent from {source_path}: {unknown_variables}")

    derived_selection = selection.copy()
    columna = derived_selection["COLUMNA"].astype(str).str.strip()
    derived_selection.loc[columna.isin(additional_variables), "SELECCIÓN"] = 1

    derived_path.parent.mkdir(parents=True, exist_ok=True)
    derived_selection.to_excel(derived_path, index=False)

    sha256_after = _sha256_of_file(source_path)
    if sha256_after != sha256_before:
        raise RuntimeError(
            f"{source_path} changed while building the derived selection "
            f"(sha256 before={sha256_before}, after={sha256_after}); this must never happen."
        )

    return derived_path


def assert_derived_selection_exists(derived_path: Path = DEFAULT_DERIVED_PATH) -> Path:
    """Raise loudly if the derived selection has not been built yet.

    Must run BEFORE any call to `procesar_dataset_completo` with
    `derived_path` -- see this module's docstring for the silent
    path-rebinding hazard this guards against.
    """
    derived_path = Path(derived_path)
    if not derived_path.exists():
        raise FileNotFoundError(
            f"Derived variable selection not found at {derived_path}. "
            "Run `python scripts/build_nb12_variable_selection.py` first."
        )
    return derived_path


def main() -> None:
    derived_path = build_nb12_variable_selection()
    print(f"Derived selection written to {derived_path}")


if __name__ == "__main__":
    main()
