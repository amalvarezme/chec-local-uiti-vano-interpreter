"""RED/GREEN test for design D2's gap: the local apps never put `src/` on
`sys.path`.

Notebooks 01-04 imported zero project modules, so nothing exercised the gap
before. Once dashboard construction moves into `src/chec_tableros/` (later
slices), every app process needs `chec_local_interpreter`/`chec_impacto`
importable -- and today it is not: `01_clima/app.py:13-14` inserts only
`_comun` and its own directory.

The fix (design D2) is a SINGLE shared insertion point in
`aplicaciones/_comun/construccion.py`, not a per-app `app.py` edit: every app
already imports `construccion` right after inserting `_comun` onto
`sys.path`, so putting the `src/` insertion there covers all apps at once.

This test spawns a real subprocess from each app's own directory, seeding
`sys.path` with EXACTLY what `app.py` seeds it with today (`_comun` + the
app's own directory) and nothing else, then imports `construccion` and
checks that `chec_local_interpreter`/`chec_impacto` become importable as a
side effect -- proving the insertion happens where every app already passes
through, not that the test cheats by adding `src/` itself.

See:
  - spec: `sdd/retire-base-apps-notebooks/spec` (domain criticidad-geometria
    is unaffected; this covers design D2, folded into domain
    tableros-modulos's dual-consumer prerequisite)
  - design: `sdd/retire-base-apps-notebooks/design` (D2)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
APPS = RAIZ / "aplicaciones"

# The four dashboard apps + the simulator: every app whose `app.py` inserts
# `_comun` and its own directory onto `sys.path` before importing
# `construccion`. `00_criticidad_chec` (the menu) does not import
# `construccion` and is excluded on purpose.
NOMBRES_APPS = (
    "01_clima",
    "02_agrupamiento_vanos",
    "03_trayectorias_circuitos",
    "04_trayectorias_vanos",
)


def _importa_src_via_construccion(carpeta: Path) -> subprocess.CompletedProcess:
    """Runs a subprocess from `carpeta` seeded with exactly the sys.path
    entries `app.py` seeds today (`_comun` + `carpeta`), then imports
    `construccion` and tries to import `chec_local_interpreter`/
    `chec_impacto` afterwards -- proving the insertion is a side effect of
    importing `construccion`, not of anything this test adds itself."""
    codigo = (
        "import sys\n"
        f"sys.path.insert(0, {str(carpeta.parent / '_comun')!r})\n"
        f"sys.path.insert(0, {str(carpeta)!r})\n"
        "import construccion\n"
        "import chec_local_interpreter\n"
        "import chec_impacto\n"
        "print('IMPORTS_OK')\n"
    )
    return subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=carpeta,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("nombre_app", NOMBRES_APPS)
def test_construccion_pone_src_en_sys_path_para_cada_app(nombre_app):
    carpeta = APPS / nombre_app
    resultado = _importa_src_via_construccion(carpeta)

    assert resultado.returncode == 0, (
        f"import de chec_local_interpreter/chec_impacto fallo desde {carpeta} "
        f"con solo _comun y la carpeta de la app en sys.path (como hace app.py "
        f"hoy):\n{resultado.stderr}"
    )
    assert "IMPORTS_OK" in resultado.stdout


def test_construccion_no_agrega_src_dos_veces():
    """Importar `construccion` dos veces (como pasaria si dos modulos lo
    importan) no debe duplicar la entrada de `src/` en `sys.path` -- una
    insercion repetida no rompe nada hoy, pero infla `sys.path` sin razon."""
    carpeta = APPS / "01_clima"
    codigo = (
        "import sys\n"
        f"sys.path.insert(0, {str(carpeta.parent / '_comun')!r})\n"
        f"sys.path.insert(0, {str(carpeta)!r})\n"
        "import construccion\n"
        "import importlib\n"
        "importlib.reload(construccion)\n"
        f"ruta_src = {str(RAIZ / 'src')!r}\n"
        "apariciones = sys.path.count(ruta_src)\n"
        "print('APARICIONES', apariciones)\n"
        "assert apariciones == 1, f'src/ aparece {apariciones} veces en sys.path'\n"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=carpeta,
        capture_output=True,
        text=True,
    )
    assert resultado.returncode == 0, resultado.stderr
