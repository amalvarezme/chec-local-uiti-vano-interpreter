"""El boton de cerrar del simulador no puede depender de que el kernel siga vivo.

## El fallo, reproducido antes de arreglarlo

Con CriticidadCHEC levantado y el simulador abierto, se mato el kernel a proposito y se
pulso Cerrar por CDP. Resultado a lo largo de ocho segundos:

    {"cerrando": false, "cerrado": false, "sinProceso": false}

Ni "Cerrando...", ni "Simulador cerrado", ni el aviso de que no encontro el proceso.
SILENCIO, y el servidor en pie. Es exactamente lo que se reporto: se pulsa y no pasa nada.

## Por que

`widgets.Button` manda su clic por el comm al kernel. Sin kernel no hay quien lo atienda,
y el widget no avisa: se queda mudo. Y el kernel se va solo por dos caminos normales:

  * Voila lo recicla a los 180 s de inactividad (`cull_idle_timeout=180` en `app.py`), que
    es lo que pasa tras una desconexion pasajera -- la tapa del portatil, el wifi;
  * o se cae por memoria: cada kernel de esta aplicacion pesa ~780 MB medidos, y el propio
    `app.py` documenta haber visto siete vivos a la vez.

## El arreglo

El clic deja de necesitar al kernel. Se engancha un manejador en el NAVEGADOR, en fase de
captura sobre el mismo boton, que:

  * escribe "Cerrando..." en el acto, para que nunca parezca inerte;
  * le pide al menu que detenga la aplicacion, cuando la aplicacion se lanzo desde el menu
    -- `MENU_CRITICIDAD` ya viajaba en el entorno desde `menu.py` y no lo leia nadie;
  * y corre el mismo JS de cierre de pestania de siempre.

El camino del kernel se queda: es el unico que hay cuando el simulador se abre solo, sin
menu. Con menu corren los dos y el resultado es el mismo -- uno manda SIGTERM a Voila y el
otro se lo pide al menu --, que es lo que se quiere de un boton de apagado.

El JS se muestra por un `Output` y no por un `HTML`: `cierre.py` ya documenta que el
JavaScript de un `widgets.HTML` NO se ejecuta, porque ipywidgets lo inyecta por
`innerHTML`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CIERRE = RAIZ / "aplicaciones" / "06_simulador" / "cierre.py"


def _fuente() -> str:
    return CIERRE.read_text(encoding="utf-8")


def test_el_boton_se_puede_encontrar_desde_el_navegador():
    """Sin una clase propia, el JS no tiene por donde agarrarlo.

    Un `widgets.Button` no trae id estable; `add_class` es lo que le pone una marca que
    el navegador pueda buscar.
    """
    fuente = _fuente()
    assert re.search(r"add_class\(", fuente), (
        "el boton no lleva una clase por la que el JS pueda encontrarlo")
    assert re.search(r"CLASE_BOTON\s*=", fuente), (
        "la clase no se declara en un solo sitio; escrita dos veces se separan")


def test_hay_un_camino_de_cierre_que_no_pasa_por_el_kernel():
    """Un manejador en el navegador, en fase de CAPTURA.

    En captura y no en burbuja para que corra aunque el widget se coma el evento, y para
    que el aviso salga antes que nada.
    """
    fuente = _fuente()
    assert "addEventListener('click'" in fuente, "no hay manejador de clic en el navegador"
    # La bandera de captura es el tercer argumento del `addEventListener`, y va al final
    # del cuerpo del manejador -- no a doscientos caracteres del nombre. Se busca el cierre
    # completo, que es lo que de verdad lo registra en captura.
    assert re.search(r"\}, true\);", fuente), (
        "el manejador no se registra en fase de captura; en burbuja se lo puede comer el "
        "widget antes de que corra")


def test_le_pide_al_menu_que_detenga_la_aplicacion():
    """`MENU_CRITICIDAD` ya viajaba en el entorno y no lo leia nadie.

    Es la unica via de apagado que no necesita ni el kernel ni el pid: la pide el
    navegador y la atiende el menu, que es otro proceso.
    """
    fuente = _fuente()
    assert "MENU_CRITICIDAD" in fuente, (
        "el cierre no usa la URL del menu, que ya viajaba en el entorno")
    # Sin la barra delante: la URL del menu ya la trae, y el guion se la anade si falta.
    # Exigirla aqui obligaria a duplicarla y a que las dos coincidieran.
    assert re.search(r"'detener\?app='", fuente), (
        "no se le pide al menu que detenga la aplicacion")
    assert re.search(r'menu\.endswith\("/"\)', fuente), (
        "nadie normaliza la barra final de la URL del menu; sin eso sale `...8800detener`")
    assert "fetch(" in fuente, "la peticion al menu no se manda desde el navegador"


def test_el_aviso_lo_escribe_el_navegador_y_no_el_kernel():
    """Con el kernel muerto, `aviso.value = ...` no llega a ninguna parte.

    Por eso el "Cerrando..." tiene que escribirlo el propio JS en el DOM.
    """
    fuente = _fuente()
    js = fuente[fuente.index("JS_ENGANCHE"):] if "JS_ENGANCHE" in fuente else ""
    assert js, "no existe el guion que engancha el boton en el navegador"
    assert "innerHTML" in js or "textContent" in js, (
        "el guion del navegador no escribe el aviso por su cuenta")


def test_el_camino_del_kernel_sigue_ahi():
    """Sin menu -- el simulador abierto solo -- es el unico que queda."""
    fuente = _fuente()
    assert "boton.on_click(cerrar)" in fuente, (
        "se fue el camino del kernel, que es el unico cuando no hay menu")
    assert "signal.SIGTERM" in fuente, "ya no se manda SIGTERM al pid de Voila"


def test_el_guion_se_muestra_por_un_output():
    """El JavaScript de un `widgets.HTML` NO se ejecuta: ipywidgets lo mete por innerHTML.

    Es la misma razon por la que la barra ya tenia un `Output` para el JS de cierre, y
    esta escrita en el modulo desde antes.
    """
    fuente = _fuente()
    assert re.search(r"with salida:\s*\n\s*display\(Javascript\(JS_ENGANCHE", fuente), (
        "el guion de enganche no se muestra por el `Output`")


# ---------------------------------------------------------------------------
# Y que de verdad apague, no solo que lo diga
# ---------------------------------------------------------------------------


def test_apagar_mata_el_proceso_de_verdad():
    """Lo de arriba fija la FORMA del apagado; esto comprueba el efecto.

    Se levanta un proceso que no se iria solo, se le pasa su pid a `apagar()` y se
    comprueba que muere. Es la unica de estas pruebas que no puede pasar leyendo el
    archivo, y por eso vale: una rama de Windows mal escrita --- un `taskkill` con los
    argumentos cambiados de sitio --- pasaria las de texto sin apagar nada.
    """
    import subprocess
    import sys as _sys
    import time

    sys.path.insert(0, str(RAIZ / "aplicaciones" / "06_simulador"))
    try:
        import cierre
    finally:
        sys.path.pop(0)

    proceso = subprocess.Popen([_sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        cierre.apagar(proceso.pid)
        for _ in range(50):
            if proceso.poll() is not None:
                break
            time.sleep(0.1)
        assert proceso.poll() is not None, "el proceso sigue vivo tras apagar()"
    finally:
        if proceso.poll() is None:
            proceso.kill()
            proceso.wait()


def test_apagar_no_revienta_con_un_pid_que_ya_no_existe():
    """El pid del archivo se queda rancio con facilidad. Levantar una traza dentro del
    kernel por eso dejaria la pestania sobre un tablero muerto y sin aviso."""
    sys.path.insert(0, str(RAIZ / "aplicaciones" / "06_simulador"))
    try:
        import cierre
    finally:
        sys.path.pop(0)
    cierre.apagar(999_999)
