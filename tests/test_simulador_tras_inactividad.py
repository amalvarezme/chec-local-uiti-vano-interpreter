"""El simulador despues de irse a otra cosa y volver, y cuando pierde su kernel.

## Lo que se reporto

"Al abrir los tableros y dejar de tener actividad, o abrir otros programas en el pc,
y volver al navegador, ya no tienen funcionalidad."

De los cinco tableros, este es el unico con un interprete de Python detras, asi que es
el unico que puede quedarse sin nadie al otro lado. Los otros cuatro se comprueban en
`test_tableros_tras_inactividad.py` y aguantan los tres gestos.

## Lo que se midio, y lo que resulto no ser

Los tres gestos del navegador **no** lo rompen, y eso hay que fijarlo para que nadie
vuelva a perseguir por ahi:

  * pestania congelada 200 s -- mas que los 180 s del reciclado de Voila --: vuelve;
  * sin red 240 s: vuelve;
  * recargar la pagina: vuelve.

En los tres, la conexion SI se cae -- queda en la consola el
`Connection lost, reconnecting in 0 seconds.` de `@jupyterlab/services` -- y el primer
reintento la recupera, porque su espera inicial es de cero segundos.

## Lo que si lo rompe

Que se muera el kernel, que es lo que `cierre.py` ya documentaba como frecuente: lo
recicla Voila a los 180 s sin conexiones, o se cae por memoria (~780 MB cada uno, y
cada recarga deja el anterior vivo). Medido tres veces:

  * `jupyter_client` levanta OTRO kernel con el mismo id, vacio: nunca ejecuto el
    cuaderno, asi que no tiene ni el tablero ni sus widgets;
  * el navegador se reconecta a el sin protestar;
  * la pagina se queda ENTERA en pantalla, con sus controles, y muda: `Limpiar` deja
    los quince vanos marcados donde estaban, y cambiar de circuito no repuebla nada;
  * y no se decia en ninguna parte. Ni en la pantalla, ni en el titulo: lo unico que
    quedaba era un `console.warn` que nadie mira.

Recargar la pagina lo recupera del todo -- tambien medido --, que es justo lo que el
usuario no tenia como saber. De ahi el vigilante de `cierre.py`: le pregunta al kernel
cuantos comms tiene -- 730 con el tablero montado, 0 en el resucitado -- al volver a la
pestania y al pulsar algo, y si son cero levanta el aviso con su boton de recargar. Su
contrato de codigo vive en `test_simulador_aviso_sin_kernel.py`; aqui se comprueba
contra el tablero de verdad, en los dos sentidos: que salga cuando tiene que salir, y
que NO salga en los tres gestos que se recuperan solos.

Son lentas: levantan Voila, Chrome y se pasan minutos congeladas o sin red.

    SIMULADOR_VIVO=1 pytest tests/test_simulador_tras_inactividad.py -v
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

import ayudas_navegador as N
import ayudas_simulador as A

MOTIVO = A.hay_con_que_correr()
APAGADAS = os.environ.get("SIMULADOR_VIVO", "") not in ("1", "true", "si")

# Igual que `test_simulador_flujo_vivo.py`: pedirlas y que se salten en silencio es la
# forma de creer que se corrieron.
if not APAGADAS and MOTIVO is not None:
    raise RuntimeError(
        f"SIMULADOR_VIVO esta puesto pero {MOTIVO}. Instala el entorno de la "
        "aplicacion con `aplicaciones/06_simulador/instalar-en-terminal.command` y "
        "construye su paquete con `python3 aplicaciones/06_simulador/preparar.py`.")

pytestmark = [
    pytest.mark.skipif(APAGADAS, reason="SIMULADOR_VIVO no esta puesto"),
    pytest.mark.skipif(MOTIVO is not None, reason=str(MOTIVO)),
]

# Por encima de los 180 s de `cull_idle_timeout` de `app.py`: si el reciclado fuera lo
# que deja mudo al tablero, con este plazo se veria.
CONGELADA = 200.0
SIN_RED = 240.0


@pytest.fixture(scope="module")
def simulador():
    """Un Voila propio, en un puerto libre. Nunca el del contrato.

    El del contrato es el que usa la sesion del usuario: tomarlo apagaria su tablero.
    """
    s = A.Simulador().arrancar()
    yield s
    s.apagar()


@pytest.fixture(scope="module")
def nav(simulador):
    n = N.Navegador(Path(tempfile.mkdtemp(prefix="chrome-sim-quieto-")))
    A.abrir(n, simulador.url)
    N.espiar_consola(n)
    yield n
    n.cerrar()


# La marca del aviso, la misma que declara `cierre.CLASE_SIN_KERNEL`. Se busca un
# ELEMENTO PROPIO y no unas palabras sueltas: la primera version de esta prueba
# buscaba "conexion", "recarga", "no responde" en todo el texto de la pagina y paso
# en verde con el kernel muerto... porque una de esas palabras ya estaba en el
# tablero desde antes. Una prueba que pasa por lo que ya habia no mide nada.
MARCA_SIN_KERNEL = "chec-sin-kernel"


def _aviso_en_pantalla(nav) -> str:
    return nav.js("""
    (function () {
      var n = document.querySelector('.%s');
      return n ? (n.innerText || '').trim() : '';
    })()
    """ % MARCA_SIN_KERNEL)


def _sigue_vivo(nav, cuando: str) -> None:
    """Contesta el tablero Y no hay aviso de conexion perdida.

    Las dos mitades, siempre juntas. El aviso se levanta al volver a la pestania y al
    pulsar algo, que es exactamente lo que hacen estas pruebas: si se equivocara,
    saldria encima de un tablero que funciona -- peor que no avisar -- y ninguna
    comprobacion de "responde" lo notaria, porque el tablero responde igual.
    """
    r = A.responde(nav)
    assert r["ok"], f"{cuando}, el tablero no contesta: {r}"
    falso = _aviso_en_pantalla(nav)
    assert not falso, (
        f"{cuando}, el tablero contesta pero salio el aviso de motor perdido: {falso!r}")


# --------------------------------------------------------- lo que NO lo rompe


def test_recien_abierto_responde(nav):
    """La linea base. Sin esto, lo que digan las demas no significa nada."""
    _sigue_vivo(nav, "recien abierto")


def test_sobrevive_a_la_pestania_congelada_mas_que_el_reciclado(nav):
    """Irse a otro programa. Chrome congela la pestania y le cierra el WebSocket.

    Con 200 s se pasa del `cull_idle_timeout=180` de `app.py` a proposito: el
    reintento del frontend arranca con espera CERO, asi que recupera la conexion en
    cuanto la pestania despierta.
    """
    N.congelar(nav, CONGELADA)
    _sigue_vivo(nav, f"tras {CONGELADA:.0f} s con la pestania congelada")
    assert any("Connection lost" in a for a in N.avisos(nav)), (
        "la conexion no llego a caerse: el gesto no esta midiendo lo que dice medir")


def test_sobrevive_a_quedarse_sin_red(nav):
    """La tapa del portatil, el wifi que cambia de red."""
    N.sin_red(nav, SIN_RED)
    _sigue_vivo(nav, f"tras {SIN_RED:.0f} s sin red")


def test_sobrevive_a_recargar_la_pagina(nav, simulador):
    """Recargar levanta un kernel NUEVO y deja vivo el anterior. Ver `app.py`."""
    A.abrir(nav, simulador.url)
    N.espiar_consola(nav)
    _sigue_vivo(nav, "tras recargar la pagina")


# ------------------------------------------------------------- lo que si lo rompe


def _kernel_de_la_pagina(nav) -> str:
    """El id del kernel de ESTA pestania, leido de su propia configuracion."""
    return nav.js("""
    (function () {
      var n = document.getElementById('jupyter-config-data');
      return n ? (JSON.parse(n.textContent).kernelId || '') : '';
    })()
    """)


def _pid_del_kernel(kid: str) -> int | None:
    """El proceso de ese kernel, por su archivo de conexion. Nunca por `getppid`."""
    r = subprocess.run(["pgrep", "-fl", "ipykernel_launcher"],
                       capture_output=True, text=True)
    for linea in r.stdout.splitlines():
        pid, _, resto = linea.partition(" ")
        if re.search(rf"kernel-{re.escape(kid)}\.json", resto):
            return int(pid)
    return None


def test_si_el_kernel_se_muere_el_tablero_deja_de_contestar(nav, simulador):
    """El defecto, reproducido: sin kernel el tablero se queda entero y mudo.

    No se simula "algo parecido": se mata el kernel DE ESTA pestania, identificado
    por su id. Es lo que hace Voila al reciclarlo y lo que hace el sistema cuando se
    queda sin memoria.
    """
    kid = _kernel_de_la_pagina(nav)
    assert kid, "la pagina no publica el id de su kernel"
    pid = _pid_del_kernel(kid)
    assert pid, f"no se encontro el proceso del kernel {kid}"

    _sigue_vivo(nav, "antes de matarle el kernel")
    subprocess.run(["kill", "-9", str(pid)], check=True)
    time.sleep(20)

    r = A.responde(nav)
    assert not r["ok"], (
        "el tablero contesto sin kernel: o `jupyter_client` recupero el estado de los "
        f"widgets -- que seria una noticia -- o esta sonda dejo de medir. {r}")


def test_si_el_kernel_se_muere_la_pagina_lo_dice(nav):
    """Lo que le faltaba al tablero: decirlo, y decir que recargar lo arregla.

    Va DESPUES de la que mata el kernel a proposito -- comparten el modulo y su
    orden --, asi que cuando esta corre ya no hay kernel. El aviso lo levanta el
    vigilante de `cierre.py` cuando el kernel contesta que no tiene ningun comm: la
    prueba anterior ya pulso `Limpiar`, y ese clic es el que lo dispara.
    """
    aviso = nav.js("""
    (function () {
      var n = document.querySelector('.%s, #%s');
      return n ? (n.innerText || '').trim() : '';
    })()
    """ % (MARCA_SIN_KERNEL, MARCA_SIN_KERNEL))
    assert aviso, (
        "la pagina no dice en ninguna parte que se quedo sin motor de calculo: no "
        f"existe ningun elemento con la marca {MARCA_SIN_KERNEL!r}")
    assert "recarg" in aviso.lower(), (
        f"el aviso no dice como recuperarlo, que es recargar la pagina: {aviso!r}")
