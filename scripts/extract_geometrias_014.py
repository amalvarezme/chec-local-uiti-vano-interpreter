"""One-shot, read-only extraction of 01.4's KMeans geometry payload.

01.4's cell 7 (`notebooks/project_flow/04_uiti_vano_trayectorias_vano.ipynb`)
carries a large committed `display_data` output (`text/html`) whose embedded
JS payload holds `espacios` (the 8 `(log_x, log_y, prep)` KMeans spaces),
`grupos` (`["Bajo", "Medio", "Medio-Alto", "Alto"]`, pre-sorted ascending by
each raw group's median `uiti_acumulado` -- so centroid index k IS the final
class id) and `geometrias` (per-space `{logs, offset, scale, centroides}`).

This script parses that payload with a marker + brace-matching scan (the
payload is embedded inside a larger, non-JSON JS assignment, so it cannot be
`json.load`-ed wholesale) and writes a compact `{"grupos": ..., "geometrias":
...}` cache to `data/derived/geometrias_014.json` (gitignored, `.gitignore:8`
`data/*`). It NEVER writes to the source notebook -- a sha256 check before
and after the read enforces that.

See:
  - spec: `sdd/notebook-10-mil-vano-ventana/spec` (domain
    `criticality-assignment-from-014`)
  - design: `sdd/notebook-10-mil-vano-ventana/design` (D6, Data Flow)

The canonical space used downstream by
`chec_impacto.models.criticality_assignment` is hardcoded key `"2"`
(`log_x=False, log_y=True, prep='minmax'`) -- this script extracts all 8
spaces without picking one; the loader is what hardcodes the key.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NOTEBOOK_PATH = (
    REPO_ROOT / "notebooks" / "project_flow" / "04_uiti_vano_trayectorias_vano.ipynb"
)
DEFAULT_OUTPUT_PATH = REPO_ROOT / "data" / "derived" / "geometrias_014.json"
CELDA_GEOMETRIA = 7


def _sha256_de_archivo(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extraer_bloque_json(html: str, clave: str) -> str:
    """Return the raw JSON substring for `"clave":<obj|array>` inside `html`,
    found via brace/bracket matching (the payload lives inside a larger JS
    assignment, not a standalone JSON document)."""
    marcador = f'"{clave}":'
    idx = html.find(marcador)
    if idx == -1:
        raise ValueError(f"No se encontró la clave '{clave}' en el HTML de la celda.")
    inicio = idx + len(marcador)
    apertura = html[inicio]
    if apertura not in "{[":
        raise ValueError(f"La clave '{clave}' no abre un objeto ni un arreglo JSON.")
    cierre = "}" if apertura == "{" else "]"
    profundidad = 0
    for i in range(inicio, len(html)):
        if html[i] == apertura:
            profundidad += 1
        elif html[i] == cierre:
            profundidad -= 1
            if profundidad == 0:
                return html[inicio : i + 1]
    raise ValueError(f"No se encontró el cierre del bloque JSON para '{clave}'.")


def _sha1_de_geometrias(geometrias: Mapping[str, object]) -> str:
    """Canonical sha1 over ONLY the `geometrias` block (sorted keys, no
    whitespace) -- pins the KMeans geometry VALUES themselves, not just that
    the source notebook stayed unwritten (the sha256-before/after check
    above already guarantees that, but says nothing about whether a
    DIFFERENT edit to 01.4 moved the centroids between two extractions).
    See `chec_impacto.models.criticality_assignment.verificar_sha1_geometrias`,
    which reads this back and compares it against a pinned expected value.
    """
    canonical = json.dumps(geometrias, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def extraer_geometrias_014(
    notebook_path: str | Path = DEFAULT_NOTEBOOK_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    *,
    celda: int = CELDA_GEOMETRIA,
) -> Path:
    """Read-only extraction: parse `notebook_path`'s stored `display_data`
    output at cell `celda` and write the compact `grupos`/`geometrias`
    payload to `output_path`. Never writes to `notebook_path`.
    """
    notebook_path = Path(notebook_path)
    output_path = Path(output_path)

    sha256_antes = _sha256_de_archivo(notebook_path)

    with open(notebook_path, "r", encoding="utf-8") as handle:
        notebook = json.load(handle)

    cells = notebook["cells"]
    if celda >= len(cells):
        raise ValueError(f"El notebook tiene {len(cells)} celdas, no existe la celda {celda}.")
    cell = cells[celda]
    outputs = cell.get("outputs", [])
    salidas_html = [
        output
        for output in outputs
        if output.get("output_type") == "display_data" and "text/html" in output.get("data", {})
    ]
    if not salidas_html:
        raise ValueError(f"La celda {celda} no tiene un output display_data con text/html.")
    html = "".join(salidas_html[0]["data"]["text/html"])

    geometrias = json.loads(_extraer_bloque_json(html, "geometrias"))
    grupos = json.loads(_extraer_bloque_json(html, "grupos"))

    payload = {
        "grupos": grupos,
        "geometrias": geometrias,
        "geometrias_sha1": _sha1_de_geometrias(geometrias),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload), encoding="utf-8")

    sha256_despues = _sha256_de_archivo(notebook_path)
    if sha256_despues != sha256_antes:
        raise RuntimeError(
            f"{notebook_path} cambió durante la extracción (sha256 antes={sha256_antes}, "
            f"después={sha256_despues}); esto nunca debe pasar -- la extracción es de solo "
            "lectura sobre el notebook fuente."
        )

    return output_path


def main() -> None:
    output_path = extraer_geometrias_014()
    print(f"Geometrías de 01.4 extraídas en {output_path}")


if __name__ == "__main__":
    main()
