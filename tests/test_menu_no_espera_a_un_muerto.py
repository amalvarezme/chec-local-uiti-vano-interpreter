"""Una apertura que fracasa deja de bloquear su tarjeta diez minutos.

Cuando CriticidadCHEC lanza una aplicacion en su propia ventana de Terminal -- que es lo
que hace en macOS con las cinco -- **no le queda ningun proceso que vigilar**: lo lanzo
Terminal.app. El menu se queda entonces esperando a que alguien tome el puerto, y la
espera de `_esperar` solo sabe rendirse antes de tiempo mirando un proceso que aqui es
`None`.

Consecuencia medida sobre el codigo: si la aplicacion no llega a servir -- porque abortio
al construir, porque su entorno esta a medias, o por lo que sea --, el menu espera el
plazo COMPLETO. Eran 600 segundos. Y durante esos diez minutos la tarjeta se queda en
"preparando", y `abrir()` devuelve en el acto sin volver a intentarlo:

    if app.viva() or app.fase == "preparando":
        return self.estado_de(app)

O sea: el boton no responde y no hay forma de reintentar. Es exactamente el sintoma de
"no me deja abrir la aplicacion desde el menu".

La ventana SI es observable: su trampolin se llama `chec-<clave>-<marca>-ventana.sh` y
vive en la tabla de procesos mientras la ventana trabaja. Con eso, una apertura que muere
se nota en segundos en vez de en diez minutos.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
COMUN = RAIZ / "aplicaciones" / "_comun"


def _modulo(nombre: str):
    """Los modulos de `aplicaciones/_comun` no son un paquete: se cargan por ruta."""
    if str(COMUN) not in sys.path:
        sys.path.insert(0, str(COMUN))
    especificacion = importlib.util.spec_from_file_location(
        nombre, COMUN / f"{nombre}.py")
    modulo = importlib.util.module_from_spec(especificacion)
    sys.modules[nombre] = modulo
    especificacion.loader.exec_module(modulo)
    return modulo


terminal = _modulo("terminal")


# ------------------------------------------------- la ventana, vista desde fuera


def test_una_ventana_abierta_se_reconoce_por_su_etiqueta(monkeypatch):
    """`chec-<clave>-...-ventana.sh` en la tabla de procesos: esa ventana trabaja."""
    temporal = str(terminal._carpeta_temporal()).rstrip("/")
    monkeypatch.setattr(terminal, "_tabla_de_procesos", lambda: [
        (101, 1, f"/bin/bash {temporal}/chec-simulador-abc123-ventana.sh"),
        (102, 1, "/usr/bin/something else"),
    ])
    assert terminal.ventana_viva("simulador") is True


def test_sin_ventana_de_esa_etiqueta_la_apertura_se_da_por_terminada(monkeypatch):
    """La de OTRA aplicacion no cuenta: cada tarjeta espera por la suya."""
    temporal = str(terminal._carpeta_temporal()).rstrip("/")
    monkeypatch.setattr(terminal, "_tabla_de_procesos", lambda: [
        (101, 1, f"/bin/bash {temporal}/chec-clima-abc123-ventana.sh"),
    ])
    assert terminal.ventana_viva("simulador") is False


def test_un_trampolin_de_otra_carpeta_no_cuenta(monkeypatch):
    """El mismo criterio que ya usa el barrido de `cerrar_ventanas`: manda la RUTA.

    Un `grep chec-simulador-ventana.sh` en la tabla de procesos lleva ese texto en su
    propia linea de comando, y sin mirar la carpeta se contaria a si mismo.
    """
    monkeypatch.setattr(terminal, "_tabla_de_procesos", lambda: [
        (101, 1, "/bin/bash /otro/sitio/chec-simulador-abc-ventana.sh"),
    ])
    assert terminal.ventana_viva("simulador") is False


# --------------------------------------------- la espera, que deja de ser ciega


def test_la_espera_se_rinde_cuando_la_ventana_desaparece():
    """Y no antes de haberla visto viva: abrir una ventana tarda un momento.

    Rendirse por no verla todavia convertiria cada apertura normal en un fallo.
    """
    menu = _modulo("menu")
    estados = iter([False, True, True, False])
    t0 = __import__("time").perf_counter()
    logrado = menu._esperar(1, limite=30.0, sigue_viva=lambda: next(estados, False))
    assert logrado is False, "la espera no se rindio al desaparecer la ventana"
    assert __import__("time").perf_counter() - t0 < 10.0, (
        "la espera se rindio, pero tarde: el plazo completo sigue mandando")


def test_una_ventana_que_nunca_aparece_no_agota_el_plazo_entero(monkeypatch):
    """Si pasada la gracia no hay ventana, la apertura no llego a arrancar.

    La gracia se acorta aqui a proposito: lo que se fija es que el corte lo decida ELLA
    y no el plazo, no cuantos segundos dura. Con la de verdad esta prueba tardaria 20 s
    en decir lo mismo.
    """
    menu = _modulo("menu")
    monkeypatch.setattr(menu, "_GRACIA_DE_LA_VENTANA", 1.0)
    t0 = __import__("time").perf_counter()
    logrado = menu._esperar(1, limite=600.0, sigue_viva=lambda: False)
    assert logrado is False
    transcurrido = __import__("time").perf_counter() - t0
    assert transcurrido < 5.0, (
        "sin ventana en ningun momento, la espera sigue durando el plazo completo")
    assert transcurrido >= 1.0, (
        "se rindio antes de darle a la ventana su gracia para aparecer")


def test_el_menu_vigila_la_ventana_cuando_no_tiene_proceso():
    """`_preparar` tiene que PASARLE ese vigilante a la espera.

    Sin el, la aplicacion en ventana cae en el unico caso que `_esperar` no sabe cortar:
    `proceso is None`, y entonces el plazo completo es la unica salida.
    """
    fuente = (COMUN / "menu.py").read_text(encoding="utf-8")
    assert "sigue_viva=" in fuente, (
        "`_preparar` no le pasa a la espera ninguna forma de saber si la ventana murio")
    assert "limite=600.0" not in fuente, (
        "sigue habiendo una espera de 600 s: diez minutos con la tarjeta bloqueada")
