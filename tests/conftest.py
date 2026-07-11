from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Force a non-interactive backend before any test imports matplotlib.pyplot.
# `graficar_barras_y_radar` (chec_impacto.interpretability.circuit_analysis)
# calls `plt.show()`, which blocks on an interactive backend (e.g. macOS's
# default) with no display attached -- headless test runs must never hang on
# a GUI window that will never be shown.
import matplotlib

matplotlib.use("Agg")
