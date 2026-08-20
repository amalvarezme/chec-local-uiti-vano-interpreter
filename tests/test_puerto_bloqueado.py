"""Un puerto que el sistema NO DEJA TOMAR no es un puerto libre, y hoy se cuenta como tal.

## El sintoma

En Windows el menu abre, y al pulsar "Abrir" en cualquier tablero la tarjeta se queda
en "preparando" hasta agotar los 180 s y sale con "el servidor no respondio", que no
nombra ni el puerto ni la causa. La aplicacion nunca llego a servir.

## Por que pasa, leido en el codigo

Las dos maneras que tiene este paquete de preguntar por un puerto contestan MAL cuando
el sistema lo tiene reservado -- lo que en Windows hacen los rangos excluidos de
Hyper-V, WSL o Docker, y lo que en POSIX hace un puerto privilegiado:

  * `puerto_tomado` abre una conexion TCP. Un puerto reservado no tiene a nadie
    escuchando, asi que la rechaza igual que uno libre: contesta **"no esta tomado"**.
  * `puerto_libre` intenta atarse y, ante CUALQUIER `OSError`, pasa al candidato
    siguiente, que es el `0`. O sea que un puerto reservado se lee como uno ocupado y
    la aplicacion se va a un puerto al azar **sin decirlo** -- el mismo fallo que ese
    mismo docstring dice haber arreglado para el caso de `TIME_WAIT`.

De ahi salen los dos finales que se ven, uno por cada puerta de entrada:

  * **Desde el menu**, que pasa `--puerto 8801`: no hay caida a otro puerto, asi que el
    `bind` revienta con el error crudo dentro de la ventana de consola. El menu no mira
    esa ventana: mira si alguien toma el puerto, y espera los 180 s completos.
  * **Por doble clic**, que no pasa ninguno: la aplicacion arranca de verdad, en un
    puerto al azar que el menu no vigila y que no esta en ningun marcador.

Las dos cosas se leen desde la silla del usuario como "se queda cargando".

## Lo que se fija aqui

Que "no se puede atar" y "lo tiene otro" dejen de ser el mismo estado, y que el
bloqueado se diga por su nombre con el numero de puerto delante -- que es el dato que
hay que llevarle a quien administra la maquina para pedir el desbloqueo.
"""

from __future__ import annotations

import errno
import importlib.util
import os
import socket
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


servidor = _modulo("servidor")


def _puerto_que_el_sistema_niega() -> int | None:
    """Un puerto que ESTA maquina se niega a dar, o `None` si no hay ninguno.

    Provocar el bloqueo de verdad, sin parchear nada, es lo que hace que estas pruebas
    valgan. Pero como se consigue no es lo mismo en los dos sistemas:

      * En POSIX, un puerto privilegiado. El sistema se lo niega a un proceso sin
        privilegios con `EACCES`. Corriendo como root no se lo niega, y ahi no hay
        escenario que montar.
      * En Windows NO hay puertos privilegiados -- medido el 2026-08-20: un proceso sin
        elevar se ata al puerto 1 sin protestar --, asi que el `1` no sirve. Lo que si
        niega Windows son los RANGOS EXCLUIDOS que reservan Hyper-V, WSL o Docker, con
        `WSAEACCES`. Y ese es exactamente el caso por el que existe este fichero, asi
        que se busca uno de verdad en vez de darlo por imposible: donde haya rangos
        reservados, estas pruebas corren y comprueban el camino de Windows entero.

    Una maquina Windows sin ningun rango excluido no puede montar el escenario, y
    entonces se salta -- que es informacion honesta, y distinta de "aqui no pasa".
    """
    if os.name != "nt":
        es_root = hasattr(os, "geteuid") and os.geteuid() == 0
        return None if es_root else 1
    # El listado sale de `servidor._salida_de_netsh`, que es quien ya sabe pedirselo al
    # sistema; aqui solo se coge el principio del primer rango que aparezca.
    for linea in servidor._salida_de_netsh().splitlines():
        partes = linea.split()
        if len(partes) < 2:
            continue
        try:
            return int(partes[0])
        except ValueError:
            continue
    return None


PUERTO_NEGADO = _puerto_que_el_sistema_niega()
sin_privilegios = pytest.mark.skipif(
    PUERTO_NEGADO is None,
    reason="esta maquina no niega ningun puerto: como root en POSIX, o en Windows sin "
           "ningun rango excluido de los que reservan Hyper-V, WSL o Docker")


@pytest.fixture()
def puerto_escuchando():
    """Un puerto con alguien detras, y su numero."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        yield s.getsockname()[1]


@pytest.fixture()
def puerto_sin_nadie():
    """Un numero de puerto que nadie tiene ahora mismo."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        numero = s.getsockname()[1]
    return numero


# ------------------------------------------------------- los tres estados posibles


def test_un_puerto_sin_nadie_esta_libre(puerto_sin_nadie: int):
    assert servidor.estado_del_puerto(puerto_sin_nadie) == servidor.LIBRE


def test_un_puerto_con_alguien_escuchando_esta_tomado(puerto_escuchando: int):
    """El estado que ya sabia distinguir `puerto_tomado`, y que se conserva."""
    assert servidor.estado_del_puerto(puerto_escuchando) == servidor.TOMADO


@sin_privilegios
def test_un_puerto_que_el_sistema_niega_esta_bloqueado():
    """El estado NUEVO, y el unico motivo de este archivo.

    Hasta ahora este caso se contestaba igual que `LIBRE` -- nadie escucha, la conexion
    se rechaza -- y por eso la aplicacion seguia adelante hasta reventar en el `bind`.
    """
    assert servidor.estado_del_puerto(PUERTO_NEGADO) == servidor.BLOQUEADO


def test_bloqueado_y_tomado_no_son_el_mismo_estado(puerto_escuchando: int):
    """Fijado a proposito: la reparacion es exactamente que dejen de confundirse.

    Un puerto ocupado se arregla cerrando lo que hay; uno bloqueado no se arregla desde
    esta maquina y hay que pedir permiso. Decirle al usuario "cierra eso" cuando no hay
    nada que cerrar es mandarlo a buscar lo que no existe.
    """
    assert servidor.TOMADO != servidor.BLOQUEADO


# ------------------------------------------- los dos codigos de "acceso denegado"


@pytest.mark.parametrize("error", [
    OSError(errno.EACCES, "Permission denied"),
    # Windows. `winerror` 10013 es `WSAEACCES`, y NO se da por hecho que Python lo
    # traduzca a `EACCES` en `errno`: esa correspondencia no se puede comprobar desde
    # macOS, asi que se miran los DOS atributos. Equivocarse en cual mirar deja el
    # arreglo sin efecto justo en el sistema para el que se escribio.
    OSError(errno.EACCES, "acceso denegado"),
])
def test_el_acceso_denegado_se_reconoce_por_errno(error: OSError):
    assert servidor._es_acceso_denegado(error) is True


def test_el_acceso_denegado_se_reconoce_tambien_por_winerror():
    """Un `OSError` que solo trae `winerror`, que es lo que puede llegar en Windows."""
    error = OSError()
    error.winerror = servidor.WSAEACCES
    assert servidor._es_acceso_denegado(error) is True


def test_un_puerto_ocupado_no_es_acceso_denegado():
    assert servidor._es_acceso_denegado(
        OSError(errno.EADDRINUSE, "Address already in use")) is False


# --------------------------------------- el puerto fijo no se cambia a escondidas


@sin_privilegios
def test_el_puerto_preferido_bloqueado_no_cae_a_uno_al_azar():
    """Caer a otro puerto es lo que deja la aplicacion servida donde nadie la busca.

    El menu vigila el puerto del contrato -- 8801, 8802, ... -- y el marcador del
    usuario apunta ahi. Una aplicacion que arranca en el 54321 esta viva y es
    invisible: la tarjeta se queda en "preparando" hasta agotar el plazo.

    Se prefiere fallar y decir por que. Ese es el sentido de tener los puertos fijos.
    """
    with pytest.raises(SystemExit) as fallo:
        servidor.puerto_libre(PUERTO_NEGADO)
    assert str(PUERTO_NEGADO) in str(fallo.value), (
        f"el aviso no nombra el puerto: {fallo.value}")


def test_el_puerto_preferido_ocupado_si_puede_caer_a_otro(puerto_escuchando: int):
    """La caida de siempre se conserva: OCUPADO no es BLOQUEADO.

    Sin esta prueba, arreglar el bloqueo por la via de quitar la caida entera cambiaria
    el comportamiento del caso comun -- dos tableros abiertos a la vez -- sin que nada
    avisara.
    """
    otro = servidor.puerto_libre(puerto_escuchando)
    assert otro != puerto_escuchando


# ------------------------------------------------------------------- la alerta


@sin_privilegios
def test_revisar_puerto_sale_con_su_propio_codigo_cuando_esta_bloqueado(tmp_path: Path,
                                                                       capsys):
    """Un codigo de salida PROPIO, distinto del de "lo tiene otro".

    Los dos son distintos de cero -- eso es lo que deja el mensaje en pantalla en vez de
    cerrar la ventana --, pero no son el mismo problema y el lanzador tiene que poder
    distinguirlos sin leer el texto.
    """
    codigo = servidor.revisar_puerto(tmp_path, PUERTO_NEGADO, abrir=False,
                                     titulo="Clima")
    assert codigo == servidor.SALIDA_PUERTO_BLOQUEADO
    assert codigo != servidor.SALIDA_PUERTO_AJENO
    dicho = capsys.readouterr().out
    assert str(PUERTO_NEGADO) in dicho, f"el aviso no nombra el puerto: {dicho}"
    assert "bloquea" in dicho.lower(), f"el aviso no dice que esta bloqueado: {dicho}"


def test_el_aviso_de_bloqueo_lleva_lo_que_hay_que_pedir():
    """El aviso es lo unico que el usuario se lleva a quien administra la maquina.

    Tiene que traer las tres cosas sin las que esa conversacion no avanza: QUE puerto,
    que la maquina lo tiene RESERVADO -- no ocupado, no es cosa de cerrar nada -- y con
    que orden se comprueba desde el otro lado.
    """
    aviso = servidor.aviso_de_bloqueo(8866, "Simulador")
    assert "8866" in aviso
    assert "Simulador" in aviso
    assert "bloquea" in aviso.lower() or "reservad" in aviso.lower()
    assert "excludedportrange" in aviso, (
        "sin la orden de Windows, quien administra la maquina no tiene por donde "
        f"empezar: {aviso}")


# ------------------------------------------- quien se llevo el puerto, en Windows


def test_el_rango_reservado_de_windows_se_lee_de_netsh(monkeypatch):
    """`netsh` es lo unico que nombra al culpable, y su salida viene en columnas.

    Se parsea la salida real de `netsh interface ipv4 show excludedportrange
    protocol=tcp`: dos numeros por linea, inicio y fin, y el puerto cae dentro o no.
    """
    salida = (
        "Protocol tcp Port Exclusion Ranges\n"
        "\n"
        "Start Port    End Port\n"
        "----------    --------\n"
        "      1024        1123\n"
        "      8850        8949\n"
        "     50000       50059     *\n"
    )
    monkeypatch.setattr(servidor, "_salida_de_netsh", lambda: salida)
    assert servidor.rango_reservado(8866) == (8850, 8949)
    assert servidor.rango_reservado(8801) is None


def test_sin_netsh_no_se_inventa_ningun_rango(monkeypatch):
    """Fuera de Windows -- y en un Windows donde `netsh` no conteste -- se dice que no
    se sabe, que es distinto de decir que no hay rango."""
    monkeypatch.setattr(servidor, "_salida_de_netsh", lambda: "")
    assert servidor.rango_reservado(8866) is None


# ------------------------------------------ y el menu, que es donde se ve el sintoma

menu = _modulo("menu")


def test_el_menu_no_lanza_nada_con_el_puerto_bloqueado(monkeypatch):
    """La tarjeta falla EN EL ACTO y nombra el puerto, en vez de esperar 180 s.

    Es la mitad que el usuario ve. `_preparar` instalaba el entorno, construia el
    tablero y lanzaba la ventana antes de descubrir que el puerto no se podia tomar --
    y ni siquiera lo descubria: se quedaba esperando a que alguien lo tomara, con el
    `bind` ya reventado dentro de una ventana de consola que el menu no mira.

    Preguntar primero cuesta un `bind` de prueba y ahorra los tres minutos.
    """
    control = menu.Control()
    app = control.apps["clima"]
    monkeypatch.setattr(menu._servidor, "estado_del_puerto",
                        lambda _p: menu._servidor.BLOQUEADO)
    # El rango se fija en vez de preguntarselo al sistema, por dos razones. La primera
    # es que asi el detalle no depende de que ESTA maquina tenga rangos excluidos. La
    # segunda es que el `subprocess.run` de abajo se parchea sobre el MODULO, que es el
    # mismo objeto para todo el proceso: en Windows `rango_reservado` consulta `netsh`
    # por ahi, se comia el parche y la tarjeta acababa mostrando el mensaje del propio
    # centinela -- una prueba que fallaba diciendo que se habia lanzado la aplicacion
    # cuando lo unico que habia corrido era la consulta que redacta el aviso. En macOS
    # no se veia: alli esa rama devuelve "" sin llamar a nadie.
    monkeypatch.setattr(menu._servidor, "rango_reservado", lambda _p: None)

    def _no_se_lanza(*_a, **_k):
        raise AssertionError("se lanzo la aplicacion con el puerto bloqueado")

    monkeypatch.setattr(menu, "_lanzar", _no_se_lanza)
    monkeypatch.setattr(menu.subprocess, "run", _no_se_lanza)

    control._preparar(app)

    assert app.fase == "fallo", f"la tarjeta quedo en {app.fase!r}"
    assert str(app.puerto) in app.detalle, (
        f"el detalle de la tarjeta no nombra el puerto: {app.detalle!r}")
    assert "bloquea" in app.detalle.lower(), (
        f"el detalle no dice que el puerto esta bloqueado: {app.detalle!r}")


def test_el_menu_sigue_adelante_con_el_puerto_libre(monkeypatch):
    """El guardia nuevo no puede quedarse con el caso normal.

    Sin esta prueba, un `estado_del_puerto` que se equivocara al alza -- o un puerto en
    `TIME_WAIT` leido como bloqueado -- dejaria el menu sin abrir ninguna aplicacion, y
    el sintoma seria el mismo que se esta arreglando.
    """
    control = menu.Control()
    app = control.apps["clima"]
    monkeypatch.setattr(menu._servidor, "estado_del_puerto",
                        lambda _p: menu._servidor.LIBRE)
    monkeypatch.setattr(type(app), "instalada", lambda _s: True)
    monkeypatch.setattr(type(app), "construida", lambda _s: True)
    lanzadas = []
    monkeypatch.setattr(menu, "_lanzar",
                        lambda a, *_a, **_k: lanzadas.append(a.clave))
    monkeypatch.setattr(menu, "_esperar", lambda *_a, **_k: True)

    control._preparar(app)

    assert lanzadas == ["clima"], "el menu no lanzo la aplicacion con el puerto libre"
    assert app.fase == "corriendo"
