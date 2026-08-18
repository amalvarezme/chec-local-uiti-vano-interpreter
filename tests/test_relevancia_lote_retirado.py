"""Guarda de retiro de `chec_local_interpreter.relevancia_lote`.

El modulo barria las 111.233 bolsas del dataset entero y entregaba una fila por
(vano, ventana) con su grupo y sus diez variables mas relevantes. Su unico
consumidor era el cuaderno `07_relevancia_lote_por_vano`, **borrado el
2026-08-14** junto con los ocho del pipeline MGCECDL original. Desde ese dia lo
unico que lo importaba era su propia prueba: 363 lineas en verde sosteniendo 408
que no llamaba nadie.

Se borro el 2026-08-18, cuatro dias despues, sin que nadie lo reclamara.

**Que se pierde y donde estaba el valor.** Lo que el modulo sabia sigue escrito
en su docstring y en el historial de git: que barrer todas las bolsas cuesta las
MISMAS 197 pasadas que barrer cinco -- un minuto para el dataset entero contra
dias de un bucle por seleccion --, y que la pregunta se INVIERTE en el grupo mas
bajo, donde el ranking util no es que bajaria la bolsa sino de que depende que se
quede. Si el barrido por lote vuelve, eso es lo que hay que recuperar; el codigo
se saca de git.

**Por que la aguja es la ruta y no la palabra.** `07_relevancia_lote_por_vano`
-- el cuaderno -- se nombra a proposito en `README.md` y en
`docs/flujo-detallado.md` como historia de una generacion anterior, y contiene la
cadena `relevancia_lote`. Vigilar la palabra pelada marcaria esas dos menciones
legitimas. La aguja es el modulo importable, no el nombre del cuaderno que lo
usaba.

Mismo estilo que `tests/test_graph_view_builder_retirado.py`, y por el mismo
motivo: una mencion en prosa basta para que el proximo barrido de codigo muerto
de por vivo un modulo que no llama nadie.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MODULO_RETIRADO = "src/chec_local_interpreter/relevancia_lote.py"
PRUEBA_RETIRADA = "tests/test_relevancia_lote.py"

#: Las dos formas de volver a atarse a el: el import y la ruta del archivo.
#: NUNCA la palabra pelada -- ver el docstring de arriba.
AGUJAS = (
    "chec_local_interpreter.relevancia_lote",
    "relevancia_lote.py",
    "from .relevancia_lote",
)

RAICES_VIGILADAS = ("src", "tests", ".claude", "scripts", "aplicaciones", "notebooks")

ARCHIVOS_VIGILADOS = ("README.md", "AGENTS.md")

#: Este mismo archivo nombra el modulo en cada aguja; excluirlo no debilita nada.
EXCEPCIONES = {Path(__file__).relative_to(PROJECT_ROOT).as_posix()}

SUFIJOS = {".py", ".md", ".json", ".yaml", ".yml", ".ipynb"}


def _archivos_a_revisar() -> list[Path]:
    encontrados: list[Path] = []
    for raiz in RAICES_VIGILADAS:
        base = PROJECT_ROOT / raiz
        if not base.is_dir():
            continue
        for ruta in base.rglob("*"):
            if not ruta.is_file() or ruta.suffix not in SUFIJOS:
                continue
            if "__pycache__" in ruta.parts:
                continue
            encontrados.append(ruta)
    for nombre in ARCHIVOS_VIGILADOS:
        ruta = PROJECT_ROOT / nombre
        if ruta.is_file():
            encontrados.append(ruta)
    return encontrados


def test_el_modulo_y_su_prueba_no_vuelven():
    for rel in (MODULO_RETIRADO, PRUEBA_RETIRADA):
        assert not (PROJECT_ROOT / rel).exists(), (
            f"{rel} volvio al arbol. Su unico consumidor era el cuaderno "
            "`07_relevancia_lote_por_vano`, borrado el 2026-08-14. Si el barrido por "
            "lote vuelve a hacer falta, el codigo se saca de git con su consumidor, "
            "no se deja en pie esperandolo."
        )


def test_nadie_lo_importa_ni_lo_cita_por_ruta():
    culpables: list[str] = []
    for ruta in _archivos_a_revisar():
        rel = ruta.relative_to(PROJECT_ROOT).as_posix()
        if rel in EXCEPCIONES:
            continue
        texto = ruta.read_text(encoding="utf-8", errors="ignore")
        lineas = [
            f"  linea {i}: {linea.strip()}"
            for i, linea in enumerate(texto.splitlines(), start=1)
            if any(aguja in linea for aguja in AGUJAS)
        ]
        if lineas:
            culpables.append(f"{rel}:\n" + "\n".join(lineas))

    assert not culpables, (
        "`relevancia_lote` volvio a estar atado a algo:\n"
        + "\n".join(culpables)
        + "\n\nNombrar el CUADERNO `07_relevancia_lote_por_vano` como historia es "
        "legitimo y esta prueba no lo marca; importar el modulo o citar su ruta, no."
    )
