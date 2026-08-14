from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Force a non-interactive backend before any test imports matplotlib.pyplot.
# `graficar_barras_y_radar` (chec_impacto.interpretability.circuit_analysis)
# calls `plt.show()`, which blocks on an interactive backend (e.g. macOS's
# default) with no display attached -- headless test runs must never hang on
# a GUI window that will never be shown.
import matplotlib

matplotlib.use("Agg")


@pytest.fixture(autouse=True)
def _isolate_agent_tools_artifacts_root(tmp_path, monkeypatch):
    """Redirect every agent-tools module's `ARTIFACTS_ROOT` to a per-test
    `tmp_path` subdirectory for the duration of each test.

    `historical.py`/`inference.py`/`expert_alignment.py`/
    `pdf_discussion.py` each resolve a module-level `ARTIFACTS_ROOT` relative
    to the process cwd -- a deliberate feature for real `/reporte` runs (the
    invoking agent's cwd is the repo root). In-process tests that call
    `validate()`/writer functions directly share pytest's own cwd, so
    without this redirect a failing/invalid payload leaks stub files into
    the tracked `reports/reportescircuitos/artifacts/` tree.

    Subprocess-based tests (`_run_cli(..., cwd=tmp_path)`) spawn a separate
    Python process this fixture cannot reach; they already isolate via the
    explicit `cwd=tmp_path` argument, so together in-process (this fixture)
    + subprocess (explicit cwd) cover every writer.
    """
    from chec_local_interpreter.agent_tools import (
        expert_alignment,
        historical,
        inference,
        pdf_discussion,
    )

    artifacts_root = tmp_path / "reports" / "reportescircuitos" / "artifacts"
    monkeypatch.setattr(historical, "ARTIFACTS_ROOT", artifacts_root / "historical")
    monkeypatch.setattr(inference, "ARTIFACTS_ROOT", artifacts_root / "inference")
    monkeypatch.setattr(expert_alignment, "ARTIFACTS_ROOT", artifacts_root)
    monkeypatch.setattr(pdf_discussion, "ARTIFACTS_ROOT", artifacts_root / "pdf-discussion-extraction")


def pytest_configure(config):
    """Marcadores propios del proyecto.

    `sin_limpiar` exime a una prueba del reinicio automatico del simulador. Se
    registra aqui y no en el modulo que lo usa porque pytest solo lee este gancho
    de `conftest.py` y de los plugins: puesto en el modulo, el marcador funciona
    igual pero cada prueba avisa de "marcador desconocido".
    """
    config.addinivalue_line(
        "markers", "sin_limpiar: no reiniciar el tablero del simulador antes")
