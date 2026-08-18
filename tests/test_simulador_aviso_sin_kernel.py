"""El simulador tiene que DECIR cuando se queda sin motor de calculo.

## El defecto

Medido tres veces: cuando el kernel del simulador se muere -- lo recicla Voila a los
180 s sin conexiones, o se cae por memoria --, `jupyter_client` levanta otro con el
mismo id pero VACIO, el navegador se reconecta sin protestar, y la pagina se queda
entera en pantalla y muda. `Limpiar` deja los quince vanos marcados donde estaban.
No se avisa en ninguna parte: lo unico que queda es un `console.warn`.

Recargar lo recupera del todo. El usuario no tiene como saberlo.

## Como se detecta, y los dos detectores que se cayeron antes

Lo que se pregunta es un HECHO, no una heuristica: un kernel con el tablero montado
tiene un comm abierto por cada widget; el kernel resucitado no tiene ninguno. Medido
sobre el tablero de verdad: **730 comms con el kernel vivo, 0 tras matarlo**.
`comm_info_request` es de los pocos mensajes que Voila permite (ver
`allowed_message_types` en `voila/app.py`), y contesta esa cuenta.

Antes se probaron dos detectores mas obvios, y los dos se cayeron AL MEDIRLOS:

  * envolver `window.WebSocket` para ver las reconexiones: no ve nada, porque el
    bundle no pasa por el global al reconectar;
  * mirar la consola: dice exactamente lo mismo -- `Connection lost, reconnecting` --
    en una reconexion sana (pestania congelada, sin red) que en una fatal.

## Por que solo al volver a la pestania

Preguntarle al kernel le refresca su `last_activity`, y preguntar en un temporizador
mantendria vivo para siempre el kernel de una pestania olvidada -- justo lo que el
`cull_idle_timeout=180` de `app.py` existe para evitar, con ~780 MB por kernel--. Se
pregunta cuando la pestania VUELVE a estar visible, que es el momento del reporte
("vuelvo al navegador y ya no responde") y en el que el tablero si se esta usando.

Estas pruebas leen la fuente. El comportamiento contra el tablero de verdad lo fija
`test_simulador_tras_inactividad.py`, que mata el kernel y exige el aviso.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CIERRE = RAIZ / "aplicaciones" / "06_simulador" / "cierre.py"


def _fuente() -> str:
    return CIERRE.read_text(encoding="utf-8")


def _guion() -> str:
    """Solo el vigilante, para no confundirlo con el guion del boton de cerrar."""
    fuente = _fuente()
    assert "JS_VIGILANTE" in fuente, "no existe el vigilante de la conexion"
    ini = fuente.index("JS_VIGILANTE")
    fin = fuente.index("def barra(")
    return fuente[ini:fin]


def test_la_marca_del_aviso_se_declara_en_un_solo_sitio():
    """Escrita dos veces -- en Python y en el guion -- se separan sin que nada falle.

    Es la misma regla que `CLASE_BOTON`, y es la marca por la que la prueba viva
    encuentra el aviso en la pagina.
    """
    fuente = _fuente()
    assert re.search(r'CLASE_SIN_KERNEL\s*=\s*"chec-sin-kernel"', fuente), (
        "la marca del aviso no se declara como constante")
    # En el guion entra sustituida, no escrita a mano.
    assert "%(sin_kernel)s" in _guion(), (
        "el guion escribe la marca a mano en vez de recibirla")


def test_le_pregunta_al_kernel_por_sus_comms():
    """El unico hecho que distingue un kernel vivo del resucitado.

    Medido: 730 comms con el tablero montado, 0 despues de matarlo. Un kernel que
    contesta `kernel_info_request` no prueba nada -- el vacio tambien contesta --,
    y por eso no vale como sonda.
    """
    guion = _guion()
    assert "comm_info_request" in guion, (
        "el vigilante no pregunta por los comms, que es lo unico que distingue un "
        "kernel con el tablero montado de uno resucitado vacio")
    assert "comm_info_reply" in guion, "el vigilante no lee la respuesta"
    assert "kernelId" in guion, (
        "el vigilante no lee el id del kernel de la configuracion de la pagina")


def test_solo_pregunta_cuando_se_vuelve_a_la_pestania():
    """Preguntar en un temporizador mantendria vivo el kernel de una pestania olvidada.

    Eso vaciaria el `cull_idle_timeout=180` de `app.py`, que existe porque cada
    kernel pesa ~780 MB. Y el momento del reporte es justo ese: volver al navegador.
    """
    guion = _guion()
    assert "visibilitychange" in guion, (
        "el vigilante no se engancha a la vuelta a la pestania")
    assert not re.search(r"setInterval\s*\(", guion), (
        "el vigilante pregunta en un temporizador: eso le refresca la actividad al "
        "kernel y deja sin efecto el reciclado de los 180 s")


def test_tambien_revisa_al_pulsar_algo_y_con_freno():
    """Volver a la pestania no basta.

    Si el kernel se cae por memoria con la pestania delante, no hay ningun
    `visibilitychange` que dispare nada, y el usuario se entera por donde se entera
    siempre: pulsa y no pasa nada. El freno existe porque cada pregunta le refresca
    al kernel su `last_activity`, y sin el un usuario activo dejaria sin efecto el
    reciclado que protege la memoria.
    """
    guion = _guion()
    assert "addEventListener('click'" in guion, (
        "el vigilante no revisa cuando el usuario pulsa algo")
    assert re.search(r"\}, true\);", guion), (
        "el manejador del clic no va en fase de captura; en burbuja se lo puede comer "
        "el widget antes de que corra")
    assert "%(freno)s" in guion, "el freno entre preguntas no entra sustituido"
    fuente = _fuente()
    assert re.search(r"FRENO_VIGILANTE_S\s*=\s*\d+", fuente), (
        "el freno no se declara como constante con su motivo")


def test_solo_avisa_con_una_respuesta_concluyente():
    """Un socket que no abre no prueba que el tablero este muerto.

    Avisar por un fallo de red seria un aviso falso encima de un tablero que
    funciona, que es peor que no avisar.
    """
    guion = _guion()
    assert re.search(r"comms\s*===?\s*0|=== 0|length === 0|!comms", guion), (
        "el vigilante no condiciona el aviso a que la respuesta sea CERO comms")


def test_el_aviso_lo_escribe_el_navegador_y_ofrece_recargar():
    """Con el kernel muerto, nada que dependa de Python llega a la pantalla.

    Es la misma razon por la que el "Cerrando..." del boton de cerrar lo escribe el
    JS: `aviso.value` desde el kernel no llega a ninguna parte.
    """
    guion = _guion()
    assert "innerHTML" in guion or "textContent" in guion, (
        "el aviso no lo escribe el propio navegador")
    assert "location.reload" in guion, (
        "el aviso no ofrece recargar, que es lo unico que recupera el tablero")
    assert re.search(r"[Rr]ecarg", guion), (
        "el aviso no dice en castellano que hay que recargar")


def test_el_vigilante_se_muestra_por_un_output():
    """El JavaScript de un `widgets.HTML` NO se ejecuta: ipywidgets lo mete por
    `innerHTML`. Es lo mismo que ya documenta el guion del boton de cerrar."""
    fuente = _fuente()
    assert re.search(r"display\(Javascript\(JS_VIGILANTE", fuente), (
        "el vigilante no se muestra por el `Output` que ejecuta JavaScript")


def test_el_vigilante_corre_aunque_el_boton_de_cerrar_no_este():
    """En Databricks la barra va sin boton de cerrar, y el tablero se queda igual de
    mudo cuando pierde su kernel. El aviso no puede colgar de la pieza que alli no
    existe."""
    fuente = _fuente()
    cuerpo = fuente[fuente.index("def barra("):]
    orden_vigilante = cuerpo.index("JS_VIGILANTE")
    # Se muestra dentro del mismo `Output`, sin condicionarlo a nada del boton.
    trozo = cuerpo[max(0, orden_vigilante - 400):orden_vigilante]
    assert "if " not in trozo.split("with salida:")[-1], (
        "el vigilante esta detras de una condicion; tiene que mostrarse siempre")
