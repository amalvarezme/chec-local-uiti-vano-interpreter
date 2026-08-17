"""El conteo Borda, en un modulo que no depende de nada mas que pandas.

Vivia dentro de `circuit_analysis`, y esa vecindad le costaba caro al proyecto
entero. `mil_vano_ventana` -- el predictor MIL que carga el informe -- importaba
`agregar_borda` desde alli, y `circuit_analysis` abria su cabecera con
`import shap` para una maquinaria de atribucion que ya nadie invocaba. Resultado:
toda corrida de `/report` cargaba SHAP entero, 1,87 s de arranque, por veinte
lineas de pandas que no lo tocan.

Separarlo no es cosmetica. Mientras la funcion siguiera en aquel modulo, el
invariante "el informe no carga SHAP" dependeria de que nadie volviera a poner un
import pesado en la cabecera de un archivo de 1.300 lineas que ya mezcla
matplotlib, torch y prompts. Aqui esa recaida es imposible por construccion.

Que es Borda: cada fila trae un diccionario ordenado de variables (la mas
relevante primero). A la que va en la posicion `pos` se le dan `top_k + 1 - pos`
puntos, se suman los puntos por grupo y se ordena. Es un consenso por PUESTOS y
no por magnitudes, que es justo lo que se quiere cuando las filas que se agregan
no comparten escala.
"""

from __future__ import annotations

import pandas as pd


def agregar_borda(df, group_cols, top_col="_TOP_VARS", top_k=20):
    """Suma de puntos Borda por variable dentro de cada grupo."""
    records = []
    row_id = 0
    for _, row in df.iterrows():
        d = row[top_col]
        if not isinstance(d, dict):
            row_id += 1
            continue
        g = {c: row[c] for c in group_cols}
        for pos, var in enumerate(list(d.keys())[:top_k], start=1):
            records.append({**g, "_var": var, "_borda": float(top_k + 1 - pos), "_row": row_id})
        row_id += 1

    if not records:
        return pd.DataFrame(columns=group_cols + ["RELEVANCIA_VARS"])

    exp = pd.DataFrame(records)
    borda = (
        exp.groupby(group_cols + ["_var"], dropna=False, sort=False)["_borda"]
        .sum()
        .reset_index()
    )
    borda = borda.sort_values(
        group_cols + ["_borda"],
        ascending=[True] * len(group_cols) + [False],
        kind="stable",
    )
    borda["_rank"] = borda.groupby(group_cols, sort=False).cumcount()
    borda = borda[borda["_rank"] < top_k].copy()
    borda["_item"] = list(zip(borda["_var"], borda["_borda"]))

    return (
        borda.groupby(group_cols, dropna=False, sort=False)["_item"]
        .agg(lambda items: {v: float(s) for v, s in items})
        .rename("RELEVANCIA_VARS")
        .reset_index()
    )
