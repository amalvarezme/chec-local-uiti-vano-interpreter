"""Contrato de las aplicaciones locales de `aplicaciones/`.

Las cinco aplicaciones no comparten codigo por herencia sino por convencion: el
gestor descubre la carpeta desde el directorio de trabajo, busca `requirements.txt`
para reconocerla, y vuelve a lanzar `construir.py` o `app.py` con el interprete del
entorno de esa carpeta. Nada de eso esta declarado en ningun sitio, asi que una
aplicacion nueva a la que le falte una pieza no falla al importarse: falla en la
maquina de quien le da doble clic, con el error del lanzador, que es el peor sitio
posible para enterarse.

Estas pruebas fijan esa convencion sobre las carpetas REALES. No construyen ningun
tablero -- eso cuesta minutos y lee 540 MB --; comprueban que las piezas estan y que
apuntan a donde dicen.

El boton de cerrar tiene su propia prueba porque son DOS extremos que tienen que
coincidir y viven en archivos distintos: la ruta que el boton llama (`empaquetar`) y
la ruta que el servidor atiende (`servidor`). Si se separan, el boton deja de apagar
nada y el sintoma es un tablero que parece cerrarse y deja el proceso vivo.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
APPS = RAIZ / "aplicaciones"
CUADERNOS = RAIZ / "notebooks" / "old_version"

# Las piezas sin las cuales el lanzador no llega a ninguna parte. `preparar.py` no
# esta: solo lo tiene el simulador, que congela un paquete en vez de un HTML.
PIEZAS = (
    "app.py",
    "construir.py",
    "requirements.txt",
    "README.md",
    "iniciar.command",
    "iniciar.bat",
    "instalar.command",
    "instalar.bat",
)


def _aplicaciones() -> list[Path]:
    return sorted(
        d for d in APPS.iterdir()
        if d.is_dir() and not d.name.startswith((".", "_"))
    )


def _ids(rutas: list[Path]) -> list[str]:
    return [r.name for r in rutas]


TODAS = _aplicaciones()


def test_estan_las_cinco_aplicaciones():
    """Fija la lista. Sin esto, las pruebas parametrizadas de abajo pasarian
    triunfalmente sobre una carpeta vacia si alguien renombrara `aplicaciones/`."""
    assert _ids(TODAS) == [
        "01_clima",
        "02_agrupamiento_vanos",
        "03_trayectorias_circuitos",
        "04_trayectorias_vanos",
        "06_simulador",
    ]


@pytest.mark.parametrize("app", TODAS, ids=_ids(TODAS))
@pytest.mark.parametrize("pieza", PIEZAS)
def test_cada_aplicacion_trae_todas_sus_piezas(app: Path, pieza: str):
    assert (app / pieza).is_file(), f"{app.name} no tiene {pieza}"


@pytest.mark.parametrize("app", TODAS, ids=_ids(TODAS))
def test_los_lanzadores_llaman_al_gestor_de_la_carpeta_de_al_lado(app: Path):
    """Los cuatro lanzadores se pisan en el directorio de trabajo primero (`cd` a la
    carpeta del script) y despues llaman al gestor por ruta relativa. Ese `cd` es lo
    que hace que `gestor` encuentre la aplicacion: la deduce del cwd. En macOS
    `Terminal.app` abre un `.command` en la carpeta del usuario, no en la del
    archivo, asi que sin el `cd` el gestor buscaria la aplicacion en `~`."""
    for nombre, orden in (("iniciar", "iniciar"), ("instalar", "instalar")):
        sh = (app / f"{nombre}.command").read_text(encoding="utf-8")
        bat = (app / f"{nombre}.bat").read_text(encoding="utf-8")
        assert 'cd "$(dirname "$0")"' in sh, f"{app.name}/{nombre}.command no se situa"
        assert 'cd /d "%~dp0"' in bat, f"{app.name}/{nombre}.bat no se situa"
        assert f"_comun/gestor.py {orden}" in sh, f"{app.name}/{nombre}.command"
        assert f"_comun\\gestor.py {orden}" in bat, f"{app.name}/{nombre}.bat"


@pytest.mark.parametrize("app", TODAS, ids=_ids(TODAS))
def test_cada_aplicacion_nombra_un_cuaderno_que_existe(app: Path):
    """El nombre del cuaderno se resuelve contra `CUADERNOS_APPS` en tiempo de
    ejecucion, asi que uno renombrado o archivado no rompe nada hasta que alguien
    intenta construir -- y para entonces ya creo el entorno virtual y espero. Aqui
    cuesta un `is_file()`.

    Se busca en TODOS los `.py` de la carpeta y no solo en `construir.py`: los
    cuatro visores estaticos lo declaran ahi, pero el simulador lo declara en
    `preparar.py`, que es quien congela su paquete. Fijar el archivo concreto
    convertiria esa diferencia legitima en un fallo."""
    nombres = {
        m.group(1)
        for py in sorted(app.glob("*.py"))
        for m in re.finditer(r"['\"]([\w.]+\.ipynb)['\"]",
                             py.read_text(encoding="utf-8"))
    }
    assert nombres, f"{app.name} no nombra ningun cuaderno en sus .py"
    # Se cuentan los que RESUELVEN, no los que se nombran. El simulador nombra dos --
    # el cuaderno fuente y la copia parcheada que el mismo escribe -- y esa segunda no
    # vive en `notebooks/` ni tiene por que. Lo que se fija es que haya exactamente
    # una fuente: cero significa que el cuaderno se renombro o se archivo a otro sitio.
    fuentes = {n for n in nombres if (CUADERNOS / n).is_file()}
    assert len(fuentes) == 1, (
        f"{app.name} nombra {sorted(nombres)} y de esos resuelven en {CUADERNOS}: "
        f"{sorted(fuentes) or 'ninguno'}. Una aplicacion sirve exactamente un cuaderno.")


@pytest.mark.parametrize("app", TODAS, ids=_ids(TODAS))
def test_cada_aplicacion_declara_sus_dependencias_con_comentarios(app: Path):
    """`requirements.txt` de estas aplicaciones no es una lista de paquetes sino la
    justificacion de por que cada entorno pesa lo que pesa. Un archivo sin una sola
    linea de comentario es la senal de que alguien lo copio de otra aplicacion sin
    revisar si esas dependencias son las suyas."""
    lineas = (app / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert any(l.lstrip().startswith("#") for l in lineas), f"{app.name}/requirements.txt"
    assert any(l.strip() and not l.lstrip().startswith("#") for l in lineas), (
        f"{app.name}/requirements.txt no declara ningun paquete")


def test_plotly_va_clavado_en_los_tableros_que_comparten_su_bundle():
    """Los cuatro visores estaticos empaquetan el plotly.js que trae plotly.py, con
    el hash de su contenido en el nombre. Comparten esa descarga en el cache del
    navegador SOLO si producen bytes identicos, y eso exige la misma version exacta.
    Con `>=`, instalarlos en semanas distintas da cuatro copias de ~4,7 MB."""
    versiones = {}
    for app in TODAS:
        if app.name == "06_simulador":
            continue      # no empaqueta plotly.js: sirve el cuaderno con un kernel vivo
        texto = (app / "requirements.txt").read_text(encoding="utf-8")
        clavada = re.search(r"^plotly==([\d.]+)$", texto, re.M)
        assert clavada, f"{app.name} no clava la version de plotly"
        versiones[app.name] = clavada.group(1)
    assert len(set(versiones.values())) == 1, f"versiones de plotly distintas: {versiones}"


def test_el_boton_de_cerrar_llama_a_la_ruta_que_el_servidor_atiende():
    """Los dos extremos viven en archivos distintos y solo coinciden porque
    `empaquetar` importa la constante de `servidor`. La prueba fija esa importacion:
    si alguien escribe la ruta a mano en el HTML, el boton pasa a llamar a una ruta
    que devuelve 404 y el tablero se queda servido con el proceso vivo."""
    sys.path.insert(0, str(APPS / "_comun"))
    try:
        import empaquetar
        import servidor
    finally:
        sys.path.pop(0)

    html = empaquetar._inyectar_boton_cerrar("<html><body>x</body></html>")
    assert f"fetch('{servidor.RUTA_APAGADO}'" in html
    assert "method: 'POST'" in html, (
        "tiene que ser POST: un GET que apaga el servidor lo dispara el prefetch del "
        "propio navegador y el tablero se cerraria solo")
    assert 'id="cerrar-tablero"' in html
    assert "window.close()" in html


def test_inyectar_el_boton_falla_si_no_encuentra_donde_ponerlo():
    """El fallo tiene que ser ruidoso. Un documento sin `</body>` que se empaquetara
    igual daria un tablero sin boton de cerrar, y eso solo se nota cuando alguien lo
    busca para cerrarlo."""
    sys.path.insert(0, str(APPS / "_comun"))
    try:
        import empaquetar
    finally:
        sys.path.pop(0)
    with pytest.raises(ValueError, match="boton de cerrar"):
        empaquetar._inyectar_boton_cerrar("<html>sin cierre")
