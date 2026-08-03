"""MIL bag construction over 01.4's vano x window cells.

Bags are `(CIRCUITO, FID_VANO, window)` cells; instances are event rows. A
single event row legitimately falls in more than one bag when 01.4's windows
overlap (the crossed 15-to-15 window vs. the calendar-aligned window) --
this module duplicates such rows into separate instances rather than
filtering them out. See:
  - spec: `sdd/notebook-10-mil-vano-ventana/spec` (domains
    `mil-bag-construction`, `mil-bag-model`)
  - design: `sdd/notebook-10-mil-vano-ventana/design` (D1, D4)

`COD_CAUSA` handling (`codificar_cod_causa`, `construir_matriz_instancias`)
is D4: the raw integer code column is replaced, in place under the SAME
name, by its own relative frequency -- this is what keeps `COD_CAUSA` a live
node in the expert graph built by `chec_impacto.data.graph`, which matches
nodes by exact string name. A parallel block of `COD_CAUSA_<code>` / `_OTRAS`
one-hot indicators carries cause identity. Renaming the frequency column
(e.g. to `COD_CAUSA_28`) silently deletes the node and its 8 preserved
edges -- pinned by a dedicated negative test in `tests/test_mil_bags.py`.

`src/chec_impacto/training/**` is Edit-denied; this module only imports
`es_variable_exogena_mgcecdl` from it (read-only) for documentation/tests,
never edits it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import numpy as np
import pandas as pd

_COLUMNAS_FUGA_ALGEBRAICA = ("DURACION", "TOT_USUS", "UITI", "PORC_APORTE_VANO", "UITI_VANO")
_COLUMNAS_CARDINALIDAD = ("num_eventos", "counts")


@dataclass(frozen=True)
class BagIndex:
    """CSR-style flat instance layout: `(n_inst, p)` features + a segment
    index into `n_bags` bags. Chosen over padded `(n_bags, max, p)` tensors
    because 52.7% of bags are singletons and the max is 46 -- padding would
    waste >40x compute/memory on more than half the data (design D1).
    """

    keys: pd.DataFrame  # (n_bags, 3): CIRCUITO, FID_VANO, VENTANA
    instance_bag: np.ndarray  # (n_inst,) int64, bag id of each instance row
    offsets: np.ndarray  # (n_bags + 1,) int64, CSR-style
    counts: np.ndarray  # (n_bags,) int64 == num_eventos; NEVER a feature or target
    y: np.ndarray  # (n_bags,) float64, uiti_acumulado
    group: np.ndarray  # (n_bags,) object, f"{CIRCUITO}|{FID_VANO}" -- the CV group key
    instance_rows: np.ndarray  # (n_inst,) int64, position of each instance in its source df

    def __post_init__(self) -> None:
        n_bags = len(self.offsets) - 1
        if n_bags < 0:
            raise ValueError("offsets debe tener al menos un elemento.")
        for name, array in (
            ("keys", self.keys),
            ("counts", self.counts),
            ("y", self.y),
            ("group", self.group),
        ):
            if len(array) != n_bags:
                raise ValueError(
                    f"'{name}' tiene {len(array)} filas, pero offsets implica {n_bags} bolsas."
                )
        if len(self.instance_rows) != len(self.instance_bag):
            raise ValueError("instance_rows e instance_bag deben tener la misma longitud.")

        n_inst = len(self.instance_bag)
        if int(self.offsets[-1]) != n_inst:
            raise ValueError(
                f"offsets[-1] ({int(self.offsets[-1])}) debe ser igual a n_inst ({n_inst})."
            )
        if n_inst > 1 and np.any(np.diff(self.instance_bag) < 0):
            raise ValueError("instance_bag debe ser no-decreciente (layout CSR).")
        if int(self.counts.sum()) != n_inst:
            raise ValueError(
                f"counts.sum() ({int(self.counts.sum())}) debe ser igual a n_inst ({n_inst})."
            )
        if not np.array_equal(np.diff(self.offsets), self.counts):
            raise ValueError("offsets debe ser la suma acumulada exacta de counts.")


def construir_indice_bolsas(
    df: pd.DataFrame,
    ventanas: Sequence[tuple[str, np.ndarray]],
    *,
    circuito_col: str = "CIRCUITO",
    vano_col: str = "FID_VANO",
    target_col: str = "UITI_VANO",
) -> BagIndex:
    """Build one bag per `(circuito, vano, ventana)` cell with events.

    `ventanas` is a sequence of `(nombre_ventana, mascara)` pairs, where
    `mascara` is a boolean array aligned POSITIONALLY to `df` (i.e. against
    `df.reset_index(drop=True)`). Overlapping windows are expected: an event
    row selected by two masks becomes two separate instances, one per bag --
    this is the design's documented ~1.81x overlap, not a bug to filter out.
    Bags with no events are never created (bag count == populated cells).
    """
    df = df.reset_index(drop=True)
    n_rows = len(df)

    grupos: dict[tuple[str, str, str], list[int]] = {}
    orden_grupos: list[tuple[str, str, str]] = []
    for nombre_ventana, mascara in ventanas:
        mascara_array = np.asarray(mascara, dtype=bool)
        if mascara_array.shape[0] != n_rows:
            raise ValueError(
                f"La máscara de la ventana '{nombre_ventana}' tiene "
                f"{mascara_array.shape[0]} filas, pero df tiene {n_rows}."
            )
        posiciones = np.flatnonzero(mascara_array)
        if posiciones.size == 0:
            continue

        subset = df.iloc[posiciones]
        for (circuito, vano), grupo in subset.groupby([circuito_col, vano_col], sort=True):
            clave = (str(circuito), str(vano), str(nombre_ventana))
            if clave not in grupos:
                grupos[clave] = []
                orden_grupos.append(clave)
            grupos[clave].extend(int(pos) for pos in grupo.index.to_numpy())

    orden_grupos.sort()

    n_bags = len(orden_grupos)
    counts = np.array([len(grupos[clave]) for clave in orden_grupos], dtype=np.int64)
    offsets = np.zeros(n_bags + 1, dtype=np.int64)
    offsets[1:] = np.cumsum(counts)
    instance_bag = np.repeat(np.arange(n_bags, dtype=np.int64), counts)
    instance_rows = (
        np.concatenate([np.asarray(grupos[clave], dtype=np.int64) for clave in orden_grupos])
        if orden_grupos
        else np.array([], dtype=np.int64)
    )

    keys = pd.DataFrame(orden_grupos, columns=[circuito_col, vano_col, "VENTANA"])
    group = np.array([f"{circuito}|{vano}" for circuito, vano, _ in orden_grupos], dtype=object)
    valores_objetivo = df[target_col].to_numpy(dtype=np.float64)
    y = np.array(
        [valores_objetivo[grupos[clave]].sum() for clave in orden_grupos],
        dtype=np.float64,
    )

    return BagIndex(
        keys=keys,
        instance_bag=instance_bag,
        offsets=offsets,
        counts=counts,
        y=y,
        group=group,
        instance_rows=instance_rows,
    )


@dataclass(frozen=True)
class CodCausaEncoding:
    """D4. `nombre_frecuencia` is the graph-carrying column and MUST stay
    exactly 'COD_CAUSA' -- renaming it deletes 8 expert edges
    (`data/graph.py:32,36,37,41,42`)."""

    frecuencias: dict[int, float]  # code -> relative frequency, FULL dataset, target-free
    codigos_propios: tuple[int, ...]  # freq >= min_frecuencia_relativa
    nombre_frecuencia: str = "COD_CAUSA"
    nombres_indicadores: tuple[str, ...] = field(default_factory=tuple)


def codificar_cod_causa(
    df: pd.DataFrame,
    *,
    min_frecuencia_relativa: float = 0.01,
    columna: str = "COD_CAUSA",
) -> tuple[pd.DataFrame, CodCausaEncoding]:
    """Replace the raw `columna` code with its relative frequency (kept
    under the same name, the graph node) and append a rare-collapse
    indicator block: one `columna_<code>` per code at or above
    `min_frecuencia_relativa`, plus `columna_OTRAS` for the rest.

    Frequencies are computed on the FULL, unsplit `df` and depend only on
    `columna` -- never on any target column (target-free, D4).
    """
    if columna not in df.columns:
        raise ValueError(f"La columna '{columna}' no existe en el dataframe.")
    if not 0.0 < min_frecuencia_relativa <= 1.0:
        raise ValueError("min_frecuencia_relativa debe estar en el rango (0, 1].")

    codigos_originales = df[columna]
    frecuencias_series = codigos_originales.value_counts(normalize=True)
    frecuencias = {int(codigo): float(freq) for codigo, freq in frecuencias_series.items()}

    codigos_propios = tuple(
        sorted(codigo for codigo, freq in frecuencias.items() if freq >= min_frecuencia_relativa)
    )
    nombre_otras = f"{columna}_OTRAS"
    nombres_indicadores = tuple(f"{columna}_{codigo}" for codigo in codigos_propios) + (
        nombre_otras,
    )

    resultado = df.copy()
    resultado[columna] = codigos_originales.map(frecuencias).astype(float)
    for codigo in codigos_propios:
        resultado[f"{columna}_{codigo}"] = (codigos_originales == codigo).astype(float)
    resultado[nombre_otras] = (~codigos_originales.isin(codigos_propios)).astype(float)

    encoding = CodCausaEncoding(
        frecuencias=frecuencias,
        codigos_propios=codigos_propios,
        nombre_frecuencia=columna,
        nombres_indicadores=nombres_indicadores,
    )
    return resultado, encoding


def construir_matriz_instancias(
    resultado: Mapping[str, Any],
    df_causa: pd.DataFrame,
    encoding: CodCausaEncoding,
    features: Sequence[str],
) -> tuple[np.ndarray, list[str]]:
    """Append `encoding`'s COD_CAUSA frequency + indicator columns to
    `resultado["X"]` (the output of `procesar_dataset_completo`, row-aligned
    with `df_causa`), enforcing A5 (algebraic-leakage exclusion) and B2
    (no cardinality signal, no degenerate zero-variance column).
    """
    features_base = list(features)

    for columna in _COLUMNAS_FUGA_ALGEBRAICA:
        if columna in features_base:
            raise ValueError(
                f"Fuga algebraica (A5): '{columna}' no puede ser una feature de instancia."
            )
    for columna in _COLUMNAS_CARDINALIDAD:
        if columna in features_base:
            raise ValueError(
                f"Señal de cardinalidad (B2): '{columna}' no puede ser una feature de instancia."
            )

    X_base = np.asarray(resultado["X"], dtype=np.float64)
    if X_base.shape[1] != len(features_base):
        raise ValueError("resultado['X'] no coincide en ancho con 'features'.")
    if len(df_causa) != X_base.shape[0]:
        raise ValueError("df_causa no está alineado en filas con resultado['X'].")

    columnas_extra = [encoding.nombre_frecuencia, *encoding.nombres_indicadores]
    X_extra = df_causa[columnas_extra].to_numpy(dtype=np.float64)

    X_inst = np.hstack([X_base, X_extra])
    features_out = [*features_base, *columnas_extra]

    if features_out.count(encoding.nombre_frecuencia) != 1:
        raise ValueError(
            f"'{encoding.nombre_frecuencia}' debe aparecer exactamente una vez en las "
            "features de instancia -- cualquier otro nombre borra el nodo del grafo experto."
        )

    columnas_con_std_cero = [
        features_out[i] for i in range(X_inst.shape[1]) if np.std(X_inst[:, i]) <= 0.0
    ]
    if columnas_con_std_cero:
        raise ValueError(
            "Columnas con std <= 0 (perfil degenerado, sin varianza): "
            f"{columnas_con_std_cero}"
        )

    return X_inst, features_out


def cachear_bolsas(
    path: str | Path,
    X: np.ndarray,
    bag_index: BagIndex,
    features: Sequence[str],
    encoding: CodCausaEncoding,
) -> Path:
    """Persist a bag build under gitignored `data/derived/` (`.gitignore:8`
    `data/*`). Round-trips exactly with `cargar_bolsas`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "X": np.asarray(X),
        "features": list(features),
        "bag_index": bag_index,
        "encoding": encoding,
    }
    joblib.dump(payload, path)
    return path


def cargar_bolsas(path: str | Path) -> dict:
    """Load a bag build written by `cachear_bolsas`."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No existe el cache de bolsas: {path}")
    return joblib.load(path)
