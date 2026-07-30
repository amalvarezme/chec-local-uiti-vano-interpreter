"""Tests for the notebook-12-local variable-selection override builder.

`scripts/build_nb12_variable_selection.py` derives an ADDITIONAL selection
(`DURACION`, `TOT_USUS`, `UITI`, `COD_CAUSA` on top of the shared file's
existing selection, per `data/nb12_additional_variables.txt`) without ever
writing to the shared, tracked `data/Variables_seleccion.xlsx`. Most tests
build synthetic tiny selection/manifest files under `tmp_path` so they never
touch the real dataset; one test additionally runs against the REAL shared
file (still strictly read-only) to prove the sha256-unchanged guarantee on
the actual tracked asset, per the launch contract's constraint: "Never
modify `data/Variables_seleccion.xlsx`."
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from scripts.build_nb12_variable_selection import (
    DEFAULT_SOURCE_PATH,
    assert_derived_selection_exists,
    build_nb12_variable_selection,
)

_ADDITIONAL_VARIABLES = ("DURACION", "TOT_USUS", "UITI", "COD_CAUSA")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_synthetic_source(path: Path) -> None:
    df = pd.DataFrame(
        {
            "COLUMNA": [*_ADDITIONAL_VARIABLES, "UITI_VANO", "OTHER"],
            "DESCRIPCIÓN_COLUMNA": ["d", "t", "u", "c", "target", "o"],
            "SELECCIÓN": [0, 0, 0, 0, 1, 1],
        }
    )
    df.to_excel(path, index=False)


def _write_manifest(path: Path) -> None:
    path.write_text("\n".join(_ADDITIONAL_VARIABLES) + "\n", encoding="utf-8")


def test_selection_recovers_p74_and_shared_file_untouched(tmp_path: Path) -> None:
    source_path = tmp_path / "Variables_seleccion.xlsx"
    manifest_path = tmp_path / "nb12_additional_variables.txt"
    derived_path = tmp_path / "derived" / "nb12_variables_seleccion.xlsx"
    _write_synthetic_source(source_path)
    _write_manifest(manifest_path)

    sha_before = _sha256(source_path)

    build_nb12_variable_selection(
        source_path=source_path, manifest_path=manifest_path, derived_path=derived_path
    )

    sha_after = _sha256(source_path)
    assert sha_after == sha_before, "the shared selection file must never be modified"

    derived = pd.read_excel(derived_path)
    recovered = derived.loc[derived["COLUMNA"].isin(_ADDITIONAL_VARIABLES), "SELECCIÓN"]
    assert len(recovered) == len(_ADDITIONAL_VARIABLES)
    assert (recovered == 1).all(), "every additional variable must be selected in the derived file"

    # Pre-existing selections (e.g. the target) must be preserved, not clobbered.
    target_row = derived.loc[derived["COLUMNA"] == "UITI_VANO", "SELECCIÓN"]
    assert (target_row == 1).all()


def test_real_shared_selection_file_untouched_by_builder(tmp_path: Path) -> None:
    """End-to-end guard against the actual tracked asset (strictly read-only)."""
    if not DEFAULT_SOURCE_PATH.exists():
        pytest.skip("data/Variables_seleccion.xlsx not present in this checkout.")

    sha_before = _sha256(DEFAULT_SOURCE_PATH)
    derived_path = tmp_path / "nb12_variables_seleccion.xlsx"
    manifest_path = tmp_path / "nb12_additional_variables.txt"
    _write_manifest(manifest_path)

    build_nb12_variable_selection(
        source_path=DEFAULT_SOURCE_PATH, manifest_path=manifest_path, derived_path=derived_path
    )

    sha_after = _sha256(DEFAULT_SOURCE_PATH)
    assert sha_after == sha_before


def test_derived_selection_distinct_basename_and_existence_guard(tmp_path: Path) -> None:
    source_path = tmp_path / "Variables_seleccion.xlsx"
    manifest_path = tmp_path / "nb12_additional_variables.txt"
    _write_synthetic_source(source_path)
    _write_manifest(manifest_path)

    # Same basename as the shared file must be rejected -- it would collide with
    # preprocessing.py's silent path-rebinding fallback (:64-68).
    same_basename_path = tmp_path / "derived" / "Variables_seleccion.xlsx"
    with pytest.raises(ValueError):
        build_nb12_variable_selection(
            source_path=source_path, manifest_path=manifest_path, derived_path=same_basename_path
        )

    missing_path = tmp_path / "derived" / "nb12_variables_seleccion.xlsx"
    with pytest.raises(FileNotFoundError):
        assert_derived_selection_exists(missing_path)

    build_nb12_variable_selection(
        source_path=source_path, manifest_path=manifest_path, derived_path=missing_path
    )
    assert assert_derived_selection_exists(missing_path) == missing_path


def test_builder_rejects_manifest_variable_absent_from_source(tmp_path: Path) -> None:
    source_path = tmp_path / "Variables_seleccion.xlsx"
    manifest_path = tmp_path / "nb12_additional_variables.txt"
    _write_synthetic_source(source_path)
    manifest_path.write_text("NOT_A_REAL_COLUMN\n", encoding="utf-8")

    with pytest.raises(ValueError):
        build_nb12_variable_selection(
            source_path=source_path,
            manifest_path=manifest_path,
            derived_path=tmp_path / "derived" / "nb12_variables_seleccion.xlsx",
        )
