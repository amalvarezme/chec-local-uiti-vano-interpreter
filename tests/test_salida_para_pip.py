"""La primera apertura en una maquina corporativa se cuelga instalando, y no dice nada.

Es la otra mitad del "se queda cargando" de Windows, y no tiene nada que ver con los
puertos. En una maquina recien clonada ninguna aplicacion tiene entorno, asi que lo
primero que hace `_preparar` es esto:

    hecho = subprocess.run([sys.executable, GESTOR, "instalar", ...],
                           capture_output=True, text=True)

**Sin `timeout` y con la salida capturada.** Si pip no tiene salida a la red -- lo
normal detras de un proxy corporativo que nadie configuro --, ahi se queda: la tarjeta
dice "creando el entorno (varios minutos, solo la primera vez)" y no cambia nunca. El
usuario no ve ni una linea de pip, porque el menu es su unica ventana.

## Por que el proxy del sistema no basta

En Windows el proxy de la empresa suele estar puesto en Opciones de Internet, o sea en
WinINET. **pip no lee WinINET**: va por `requests`/`urllib3`, que leen las variables de
entorno `HTTPS_PROXY` y `HTTP_PROXY` y nada mas. De ahi el caso que se ve una y otra
vez: el navegador entra a internet sin problema -- y por eso el menu se abre y se ve
bien -- y pip no.

Eso descarta ademas la otra sospecha, la de que el proxy este estorbando al NAVEGADOR:
la pagina del menu se sirve por 127.0.0.1 y carga, asi que ese camino esta despejado.

## Lo que se fija aqui

Preguntar ANTES de lanzar pip, y decir por que cuando no hay salida -- nombrando la
variable de entorno, que es lo unico que arregla el caso.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
COMUN = RAIZ / "aplicaciones" / "_comun"


def _modulo(nombre: str):
    if str(COMUN) not in sys.path:
        sys.path.insert(0, str(COMUN))
    especificacion = importlib.util.spec_from_file_location(
        nombre, COMUN / f"{nombre}.py")
    modulo = importlib.util.module_from_spec(especificacion)
    sys.modules[nombre] = modulo
    especificacion.loader.exec_module(modulo)
    return modulo


entorno = _modulo("entorno")


@pytest.fixture(autouse=True)
def sin_proxy_heredado(monkeypatch):
    """El entorno de quien corre las pruebas no puede decidir el resultado."""
    for nombre in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(nombre, raising=False)


# --------------------------------------------------- a quien se le pregunta


def test_sin_proxy_se_pregunta_por_el_indice(monkeypatch):
    """Sin proxy declarado, pip va directo a PyPI: es a PyPI a quien hay que sondear."""
    preguntados = []
    monkeypatch.setattr(entorno, "_alcanzable",
                        lambda host, puerto, espera=0: preguntados.append(host) or True)
    assert entorno.hay_salida_para_pip() is True
    assert preguntados and preguntados[0] in entorno.HOSTS_DE_PYPI


def test_con_proxy_declarado_se_pregunta_por_el_proxy(monkeypatch):
    """Con `HTTPS_PROXY` puesto, pip habla con el proxy y con nadie mas.

    Sondear PyPI en ese caso seria dar por rota una maquina que funciona: detras de un
    proxy la salida DIRECTA esta cortada a proposito, y ese es el caso normal, no el
    fallo.
    """
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.empresa.local:8080")
    preguntados = []
    monkeypatch.setattr(entorno, "_alcanzable",
                        lambda host, puerto, espera=0:
                        preguntados.append((host, puerto)) or True)
    assert entorno.hay_salida_para_pip() is True
    assert preguntados == [("proxy.empresa.local", 8080)]


def test_un_proxy_sin_puerto_se_sondea_en_el_suyo_por_defecto(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.empresa.local")
    preguntados = []
    monkeypatch.setattr(entorno, "_alcanzable",
                        lambda host, puerto, espera=0:
                        preguntados.append((host, puerto)) or True)
    entorno.hay_salida_para_pip()
    assert preguntados == [("proxy.empresa.local", 80)]


def test_un_proxy_escrito_sin_esquema_sigue_siendo_un_proxy(monkeypatch):
    """`proxy.empresa.local:8080` a secas es un valor legitimo y pip lo lee como host.

    Esta prueba nacio afirmando lo contrario -- que un valor asi era ilegible y habia
    que dejarlo pasar --, y estaba equivocada: `urlparse` con `//` delante lo lee bien,
    igual que lo lee `urllib3`. Darlo por ilegible seria sondear PyPI en una maquina
    que sale por proxy, o sea dar por rota una que funciona.
    """
    monkeypatch.setenv("HTTPS_PROXY", "proxy.empresa.local:3128")
    preguntados = []
    monkeypatch.setattr(entorno, "_alcanzable",
                        lambda host, puerto, espera=0:
                        preguntados.append((host, puerto)) or True)
    assert entorno.hay_salida_para_pip() is True
    assert preguntados == [("proxy.empresa.local", 3128)]


def test_un_proxy_sin_host_no_da_por_rota_la_maquina(monkeypatch):
    """Ante una variable de la que no sale ningun host se deja pasar a pip.

    Bloquear la instalacion por no entender un valor seria cambiar un fallo que se
    diagnostica por uno que no: si el valor esta mal, el mensaje que hay que ver es el
    de pip, que sabe decir que le pasa a SU configuracion.
    """
    monkeypatch.setenv("HTTPS_PROXY", "http://")
    monkeypatch.setattr(entorno, "_alcanzable",
                        lambda *_a, **_k: pytest.fail("no habia a quien sondear"))
    assert entorno.hay_salida_para_pip() is True


def test_sin_salida_se_dice_que_no(monkeypatch):
    monkeypatch.setattr(entorno, "_alcanzable", lambda *_a, **_k: False)
    assert entorno.hay_salida_para_pip() is False


# ------------------------------------------------------------------ el aviso


def test_el_aviso_nombra_la_variable_que_lo_arregla():
    """`HTTPS_PROXY` es lo unico que arregla el caso, y no es evidente: la maquina tiene
    internet -- el navegador entra --, asi que el usuario no busca ahi."""
    aviso = entorno.aviso_sin_salida()
    assert "HTTPS_PROXY" in aviso
    assert "pip" in aviso
    assert "pypi.org" in aviso


def test_el_aviso_explica_por_que_el_proxy_del_sistema_no_sirve():
    """Sin esta frase el aviso manda a mirar Opciones de Internet, que es donde el
    proxy YA esta puesto y donde no hay nada que corregir."""
    aviso = entorno.aviso_sin_salida().lower()
    assert "opciones de internet" in aviso or "wininet" in aviso


# ------------------------------------------- y no se lanza pip si no hay salida


def test_crear_no_lanza_pip_sin_salida(monkeypatch, tmp_path: Path):
    """El sondeo tiene que ir ANTES del `pip install`, o no ahorra el cuelgue.

    Vale unos segundos como mucho; el cuelgue que evita no tiene final.
    """
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    monkeypatch.setattr(entorno, "hay_salida_para_pip", lambda: False)
    monkeypatch.setattr(entorno, "_correr",
                        lambda _c: pytest.fail("se lanzo pip sin salida a la red"))
    with pytest.raises(SystemExit) as fallo:
        entorno.crear(tmp_path)
    assert "HTTPS_PROXY" in str(fallo.value)


# ------------------------------------------ y el menu, que es donde se ve el sintoma

menu = _modulo("menu")


def test_el_menu_no_instala_sin_salida_a_la_red(monkeypatch):
    """La tarjeta lo dice EN EL ACTO, y nombra la variable.

    Sin esto, el mensaje de `entorno.crear` viaja por el `stderr` del gestor y el menu
    solo se queda con su ULTIMA linea -- `_fallo` recorta a eso --, que es la menos
    util de las diez. Y para llegar ahi hay que esperar a que pip se rinda, que es lo
    que no pasa nunca cuando la conexion se queda a medias.
    """
    control = menu.Control()
    app = control.apps["clima"]
    monkeypatch.setattr(menu._servidor, "estado_del_puerto",
                        lambda _p: menu._servidor.LIBRE)
    monkeypatch.setattr(type(app), "instalada", lambda _s: False)
    monkeypatch.setattr(menu.entorno, "hay_salida_para_pip", lambda: False)
    monkeypatch.setattr(menu.subprocess, "run",
                        lambda *_a, **_k: pytest.fail("se lanzo pip sin salida"))

    control._preparar(app)

    assert app.fase == "fallo", f"la tarjeta quedo en {app.fase!r}"
    assert "HTTPS_PROXY" in app.detalle, (
        f"el detalle no nombra la variable que lo arregla: {app.detalle!r}")


def test_una_aplicacion_ya_instalada_no_pregunta_por_la_red(monkeypatch):
    """El sondeo es del INSTALADOR, no del arranque.

    Preguntarlo siempre metria hasta cinco segundos de espera -- y una dependencia de
    internet -- en la apertura de una aplicacion que ya tiene su entorno y no necesita
    bajar nada. Un tablero ya instalado abre sin red, y tiene que seguir haciendolo.
    """
    control = menu.Control()
    app = control.apps["clima"]
    monkeypatch.setattr(menu._servidor, "estado_del_puerto",
                        lambda _p: menu._servidor.LIBRE)
    monkeypatch.setattr(type(app), "instalada", lambda _s: True)
    monkeypatch.setattr(type(app), "construida", lambda _s: True)
    monkeypatch.setattr(menu.entorno, "hay_salida_para_pip",
                        lambda: pytest.fail("se sondeo la red con el entorno ya hecho"))
    monkeypatch.setattr(menu, "_lanzar", lambda *_a, **_k: None)
    monkeypatch.setattr(menu, "_esperar", lambda *_a, **_k: True)

    control._preparar(app)

    assert app.fase == "corriendo"
