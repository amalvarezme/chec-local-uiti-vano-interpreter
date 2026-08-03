"""RED/GREEN tests for the geometry-VALUE pinning addition to PR5.

Closes a residual risk flagged by the orchestrator
(`sdd/notebook-10-mil-vano-ventana/estado-ramas`, obs #542): the
sha256-before/after check in `scripts/extract_geometrias_014.py` only proves
01.4 was not WRITTEN during extraction -- it says nothing about whether the
extracted `geometrias` block's VALUES (the KMeans offsets/scales/centroids)
match a previous extraction. If a future edit to 01.4 moved the centroids,
`extraer_geometrias_014` would silently write different constants and every
downstream criticality class would shift with no warning.

This adds:
  - `scripts.extract_geometrias_014._sha1_de_geometrias`: canonical sha1 over
    ONLY the `geometrias` block (sorted-key, no-whitespace JSON), stored as
    `payload["geometrias_sha1"]`.
  - `chec_impacto.models.criticality_assignment.verificar_sha1_geometrias`:
    reads that field back and compares it against a PINNED expected value
    (`GEOMETRIAS_SHA1_ESPERADO`), computed 2026-08-02 by running the real
    extraction script against the real, committed 01.4 notebook -- not
    fabricated (see this file's own `test_geometrias_sha1_esperado_matches_real_014`).

Uses the same committed fixture as `tests/test_criticality_assignment.py`
(`tests/fixtures/notebook_01_4_fixture.ipynb`), which embeds the REAL
`espacios`/`grupos`/`geometrias` JSON read from 01.4's committed cell-7
output -- so extracting from the fixture and from the real notebook must
produce the IDENTICAL `geometrias_sha1` (verified directly, not assumed).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chec_impacto.models.criticality_assignment import (
    GEOMETRIAS_SHA1_ESPERADO,
    verificar_sha1_geometrias,
)
from scripts.extract_geometrias_014 import (
    DEFAULT_NOTEBOOK_PATH,
    _sha1_de_geometrias,
    extraer_geometrias_014,
)

FIXTURE_NOTEBOOK = Path(__file__).parent / "fixtures" / "notebook_01_4_fixture.ipynb"


def test_extraction_payload_carries_geometrias_sha1(tmp_path):
    salida = tmp_path / "geometrias_014.json"
    extraer_geometrias_014(FIXTURE_NOTEBOOK, salida)

    payload = json.loads(salida.read_text(encoding="utf-8"))
    assert "geometrias_sha1" in payload
    sha1_value = payload["geometrias_sha1"]
    assert isinstance(sha1_value, str)
    assert len(sha1_value) == 40
    int(sha1_value, 16)  # must be valid hex, else raises ValueError


def test_geometrias_sha1_is_recomputable_and_deterministic(tmp_path):
    salida = tmp_path / "geometrias_014.json"
    extraer_geometrias_014(FIXTURE_NOTEBOOK, salida)
    payload = json.loads(salida.read_text(encoding="utf-8"))

    recomputed = _sha1_de_geometrias(payload["geometrias"])
    assert recomputed == payload["geometrias_sha1"]

    # Re-running extraction must reproduce the exact same digest (no
    # nondeterminism from dict ordering / float formatting).
    salida_2 = tmp_path / "geometrias_014_again.json"
    extraer_geometrias_014(FIXTURE_NOTEBOOK, salida_2)
    payload_2 = json.loads(salida_2.read_text(encoding="utf-8"))
    assert payload_2["geometrias_sha1"] == payload["geometrias_sha1"]


def test_verificar_sha1_geometrias_matches_pinned_constant_on_fixture(tmp_path):
    """The fixture embeds the REAL 01.4 geometrias block, so verifying it
    against the pinned expected constant must report a match."""
    salida = tmp_path / "geometrias_014.json"
    extraer_geometrias_014(FIXTURE_NOTEBOOK, salida)

    sha1_real, coincide = verificar_sha1_geometrias(salida)
    assert coincide is True
    assert sha1_real == GEOMETRIAS_SHA1_ESPERADO


def test_verificar_sha1_geometrias_reports_mismatch_against_wrong_expected(tmp_path):
    salida = tmp_path / "geometrias_014.json"
    extraer_geometrias_014(FIXTURE_NOTEBOOK, salida)

    sha1_real, coincide = verificar_sha1_geometrias(
        salida, esperado="0" * 40
    )
    assert coincide is False
    assert sha1_real == GEOMETRIAS_SHA1_ESPERADO


def test_verificar_sha1_geometrias_raises_on_legacy_payload_without_field(tmp_path):
    salida = tmp_path / "geometrias_014_legacy.json"
    salida.write_text(json.dumps({"grupos": [], "geometrias": {}}), encoding="utf-8")

    with pytest.raises(KeyError):
        verificar_sha1_geometrias(salida)


@pytest.mark.skipif(
    not DEFAULT_NOTEBOOK_PATH.exists(),
    reason="01.4's real committed notebook is not present in this checkout.",
)
def test_geometrias_sha1_esperado_matches_real_014(tmp_path):
    """Confirms the pinned constant was measured from the REAL notebook, not
    fabricated: extracting from the actual committed 01.4 must produce the
    SAME digest as the fixture-derived one used elsewhere in this file."""
    salida = tmp_path / "geometrias_014_real.json"
    extraer_geometrias_014(DEFAULT_NOTEBOOK_PATH, salida)
    sha1_real, coincide = verificar_sha1_geometrias(salida)
    assert coincide is True
    assert sha1_real == GEOMETRIAS_SHA1_ESPERADO
