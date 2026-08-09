"""Criticality assignment from 01.4's own KMeans geometry (design D6).

The reported criticality class is NOT re-fit here: it is 01.4's own
nearest-centroid rule over `(n_obs, u)`, replayed from the geometry 01.4
already computed and committed. `n_obs` is always the OBSERVED bag
cardinality (`num_eventos`) -- never predicted, for the model or for any
baseline. `u` is `uiti_acumulado`, observed on ground truth and predicted
(`û`) for the model's own output.

Canonical space is HARDCODED as `(log_x=False, log_y=True, prep='minmax')`
-> `GEOMETRIAS["2"]`. 01.4's minified JS is never traced to "discover" the
default; the key is fixed by this module's own contract.

01.4 pre-sorts its 4 groups ascending by each raw group's median
`uiti_acumulado` before export (see `scripts/extract_geometrias_014.py`'s
docstring), so exported centroid index k IS the final class id: 0=Bajo,
1=Medio, 2=Medio-Alto, 3=Alto. No remapping happens here.

`EPS_UITI` clamps `log10(u)` against `u <= 0`. It is applied uniformly by
axis (only the axis flagged `logs=True` is ever clamped), which is why it
structurally only ever fires on the PREDICTED `û` path: `n_obs`'s axis is
never logged in the canonical space, and 0 of 111,233 measured OBSERVED
bags have `uiti_acumulado == 0` (obs #524) -- so the observed path never
reaches a value the clamp would change.

See:
  - spec: `sdd/notebook-10-mil-vano-ventana/spec` (domain
    `criticality-assignment-from-014`)
  - design: `sdd/notebook-10-mil-vano-ventana/design` (D6)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ESPACIO_CANONICO = (False, True, "minmax")  # -> GEOMETRIAS key "0"
# It was "2" while 01.4 enumerated eight spaces (log_x x log_y x {minmax, zscore}) and the
# panel let you pick one. That choice was removed on 2026-08-09: the space is now fixed to
# this exact triple, `ESPACIOS` holds a single entry, and the only key left is "0". The
# canonical geometry's VALUES are byte-identical across that change -- same fit, same seed,
# same space -- so no criticality class shifted; only the index it is filed under moved.
CLAVE_ESPACIO_CANONICO = "0"
EPS_UITI = 1e-6
GRUPOS = ("Bajo", "Medio", "Medio-Alto", "Alto")

# Pins the KMeans geometry VALUES 01.4 committed, not merely that the
# notebook stayed unwritten (`extract_geometrias_014.py`'s sha256 check
# already guarantees that, but not this). Measured 2026-08-02 by running the
# real `extraer_geometrias_014()` against 01.4's real, committed notebook and
# hashing the resulting `geometrias` block with `_sha1_de_geometrias`'s
# canonicalization (sorted keys, no whitespace) -- reproduced independently
# against `tests/fixtures/notebook_01_4_fixture.ipynb` (which embeds that
# same real payload) in `tests/test_geometrias_sha1.py`. If a future edit to
# 01.4 moves the KMeans centroids, this constant will no longer match and
# `verificar_sha1_geometrias` reports the mismatch instead of silently
# shifting every downstream criticality class. See the residual risk this
# closes: `sdd/notebook-10-mil-vano-ventana/estado-ramas`.
#
# Re-pinned 2026-08-09 (was dcc90cea2aa820018412e3dc37189d6b3e6ec49a). The digest covers
# the WHOLE `geometrias` block, and that block lost its seven non-canonical spaces when the
# axis-scale and preprocessing controls were removed from 01.4 -- so it moved even though
# the canonical geometry did not. That was verified before re-pinning, not assumed: the
# block under the old key "2" and the new key "0" compare equal field by field
# (logs/offset/scale/centroides), so this is a re-pin of the same centroids under a smaller
# block, NOT a geometry change. Anything that shifts the centroids themselves still trips
# the guard exactly as before.
GEOMETRIAS_SHA1_ESPERADO = "2e351bbdc7a391054440f8155235ec91b20f2b7b"


@dataclass(frozen=True)
class Geometria:
    """One KMeans space's fitted standardization + centroids, as exported by
    01.4. `logs` is `(log_x, log_y)`; axis 0 is `n_obs`, axis 1 is `u`."""

    logs: tuple[bool, bool]
    offset: np.ndarray  # (2,)
    scale: np.ndarray  # (2,)
    centroides: np.ndarray  # (4, 2), index k IS the final class id


def cargar_geometria_014(
    path: str | Path, clave: str = CLAVE_ESPACIO_CANONICO
) -> Geometria:
    """Load a `Geometria` from `scripts/extract_geometrias_014.py`'s output
    JSON. `clave` defaults to the hardcoded canonical space `"2"`."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No existe el cache de geometrías: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    geometrias = payload["geometrias"]
    if clave not in geometrias:
        raise KeyError(
            f"La clave de espacio '{clave}' no existe en {path} "
            f"(claves disponibles: {sorted(geometrias.keys())})."
        )

    bloque = geometrias[clave]
    return Geometria(
        logs=(bool(bloque["logs"][0]), bool(bloque["logs"][1])),
        offset=np.asarray(bloque["offset"], dtype=np.float64),
        scale=np.asarray(bloque["scale"], dtype=np.float64),
        centroides=np.asarray(bloque["centroides"], dtype=np.float64),
    )


def verificar_sha1_geometrias(
    path: str | Path, *, esperado: str = GEOMETRIAS_SHA1_ESPERADO
) -> tuple[str, bool]:
    """Read the `geometrias_sha1` field `scripts/extract_geometrias_014.py`
    wrote into `path` and compare it against `esperado` (defaults to the
    pinned `GEOMETRIAS_SHA1_ESPERADO`). Returns `(sha1_real, coincide)` --
    never raises on a MISMATCH by itself, so the caller (typically the
    notebook) decides how loudly to report it; only raises `KeyError` when
    `path` predates this field (a legacy extraction that must be re-run).
    """
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "geometrias_sha1" not in payload:
        raise KeyError(
            f"{path} no tiene el campo 'geometrias_sha1' -- fue escrito por una version "
            "anterior de extract_geometrias_014.py. Vuelve a correr la extraccion."
        )
    sha1_real = str(payload["geometrias_sha1"])
    return sha1_real, sha1_real == esperado


def _estandarizar(
    n_obs: np.ndarray, u: np.ndarray, geometria: Geometria, eps: float
) -> tuple[np.ndarray, int]:
    """Return the standardized `(n, 2)` matrix `Z` and the count of values
    clamped by `eps` (only ever non-zero on the logged `u` axis when a
    predicted `û` is <= 0 -- see module docstring)."""
    if n_obs.shape != u.shape:
        raise ValueError("n_obs y u deben tener la misma forma.")

    log_x, log_y = geometria.logs

    n_clamped = 0
    if log_x:
        clamped_n = np.maximum(n_obs, eps)
        n_clamped += int(np.sum(n_obs < eps))
        x0 = np.log10(clamped_n)
    else:
        x0 = n_obs

    if log_y:
        clamped_u = np.maximum(u, eps)
        n_clamped += int(np.sum(u < eps))
        x1 = np.log10(clamped_u)
    else:
        x1 = u

    z0 = (x0 - geometria.offset[0]) / geometria.scale[0]
    z1 = (x1 - geometria.offset[1]) / geometria.scale[1]
    return np.stack([z0, z1], axis=-1), n_clamped


def _distancias_cuadradas(
    n_obs: np.ndarray, u: np.ndarray, geometria: Geometria, eps: float
) -> tuple[np.ndarray, int]:
    Z, n_clamped = _estandarizar(n_obs, u, geometria, eps)
    diffs = Z[:, None, :] - geometria.centroides[None, :, :]
    return np.sum(diffs**2, axis=-1), n_clamped


def asignar_clase(
    n_obs: np.ndarray, u: np.ndarray, geometria: Geometria, *, eps: float = EPS_UITI
) -> tuple[np.ndarray, int]:
    """Nearest-centroid class assignment (hard argmin). Returns
    `(clase, n_clamped)`; `clase[i]` is directly the final class id
    (0=Bajo..3=Alto), no remapping."""
    n_obs = np.atleast_1d(np.asarray(n_obs, dtype=np.float64))
    u = np.atleast_1d(np.asarray(u, dtype=np.float64))
    d2, n_clamped = _distancias_cuadradas(n_obs, u, geometria, eps)
    return np.argmin(d2, axis=-1), n_clamped


def distribucion_suave(
    n_obs: np.ndarray,
    u: np.ndarray,
    geometria: Geometria,
    *,
    temperatura: float = 1.0,
    eps: float = EPS_UITI,
) -> np.ndarray:
    """Soft class distribution `softmax(-d^2 / temperatura)`, for SHAP /
    simulator compatibility only -- the REPORTED class always stays the hard
    `asignar_clase` argmin. `argmax(distribucion_suave(...)) ==
    asignar_clase(...)` for every `temperatura > 0` because softmax is
    strictly monotone in `-d^2` -- see D6."""
    if temperatura <= 0.0:
        raise ValueError("temperatura debe ser > 0.")
    n_obs = np.atleast_1d(np.asarray(n_obs, dtype=np.float64))
    u = np.atleast_1d(np.asarray(u, dtype=np.float64))
    d2, _ = _distancias_cuadradas(n_obs, u, geometria, eps)
    logits = -d2 / temperatura
    logits = logits - logits.max(axis=-1, keepdims=True)
    exp = np.exp(logits)
    return exp / exp.sum(axis=-1, keepdims=True)


def distancias_cuadradas_torch(
    n_obs: "torch.Tensor",
    u: "torch.Tensor",
    geometria: Geometria,
    *,
    eps: float = EPS_UITI,
) -> "torch.Tensor":
    """Differentiable mirror of `_distancias_cuadradas`, returning `(n, K)`.

    Exists so a loss can reach the criticality classes THROUGH `u` -- the
    numpy path above is the reporting path and stays authoritative. The two
    are pinned to agree numerically in
    `tests/test_mil_perdida_clase.py::test_torch_distances_match_the_numpy_implementation`;
    any future change to the standardization must move both.

    `torch` is imported lazily: this module is imported by notebook and
    reporting code paths that have no reason to pay for torch.
    """
    import torch

    n_obs = torch.as_tensor(n_obs)
    u = torch.as_tensor(u, dtype=n_obs.dtype if u is None else None)
    if n_obs.shape != u.shape:
        raise ValueError("n_obs y u deben tener la misma forma.")

    log_x, log_y = geometria.logs
    # `clamp` keeps the gradient finite at u <= 0 (it is zero there, which is
    # the right answer: below the clamp the standardized coordinate is
    # constant, so it genuinely does not respond to u).
    x0 = torch.log10(n_obs.clamp(min=eps)) if log_x else n_obs
    x1 = torch.log10(u.clamp(min=eps)) if log_y else u

    offset = torch.as_tensor(geometria.offset, dtype=x0.dtype, device=x0.device)
    scale = torch.as_tensor(geometria.scale, dtype=x0.dtype, device=x0.device)
    centroides = torch.as_tensor(
        geometria.centroides, dtype=x0.dtype, device=x0.device
    )

    z = torch.stack([(x0 - offset[0]) / scale[0], (x1 - offset[1]) / scale[1]], dim=-1)
    diffs = z.unsqueeze(-2) - centroides.unsqueeze(0)
    return torch.sum(diffs**2, dim=-1)
