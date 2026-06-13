from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd


def save_uiti_vano_plot(
    daily_df: pd.DataFrame,
    critical_points: list[dict[str, object]],
    *,
    selected_circuitos: list[str],
    start_date: str | None,
    end_date: str | None,
    output_path: str | Path,
) -> Path:
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "chec_local_matplotlib"))
    import matplotlib.pyplot as plt

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(12, 5))
    if not daily_df.empty:
        work = daily_df.copy()
        work["fecha_dia"] = pd.to_datetime(work["fecha_dia"], errors="coerce")
        ax.plot(work["fecha_dia"], work["UITI_VANO"], color="#19535F", linewidth=1.8, label="UITI_VANO diario")
        point_dates = [pd.to_datetime(point["fecha_dia"]) for point in critical_points]
        if point_dates:
            point_frame = work[work["fecha_dia"].isin(point_dates)]
            ax.scatter(
                point_frame["fecha_dia"],
                point_frame["UITI_VANO"],
                color="#D1495B",
                s=55,
                zorder=3,
                label="Puntos criticos",
            )
    circuit_text = ", ".join(selected_circuitos[:4]) if selected_circuitos else "todos los circuitos"
    if len(selected_circuitos) > 4:
        circuit_text += f" +{len(selected_circuitos) - 4}"
    ax.set_title(f"UITI_VANO - {circuit_text} - {start_date or 'inicio'} a {end_date or 'fin'}")
    ax.set_xlabel("Fecha")
    ax.set_ylabel("UITI_VANO")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(target, dpi=150)
    plt.close(fig)
    return target
