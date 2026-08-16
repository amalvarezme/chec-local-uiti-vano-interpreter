"""La barra de cerrar del simulador: el unico widget que la APLICACION agrega.

El tablero (`chec_tableros.simulador.tablero`) no sabe nada de esto, y es a
proposito: cerrar la aplicacion es apagar un servidor de Voila, y eso no existe
cuando el mismo tablero se arma dentro de un cuaderno. Entra por el parametro
`encabezado` de `construir()`.

Vivia como una cadena de 85 lineas dentro de `preparar.py`, inyectada en la celda
16 del cuaderno por un reemplazo de texto. Ninguna herramienta la veia como
codigo: no compilaba en su archivo, no se podia importar y un error de sintaxis
aqui solo aparecia al arrancar la aplicacion, dentro del kernel.
"""
from __future__ import annotations

import json
import os
import signal
import threading

import ipywidgets as widgets
from IPython.display import Javascript, display

# `window.close()` no siempre esta permitido: Chrome lo acepta cuando la pestania no
# tiene historial propio -- que es el caso de la que abre `abrir-en-terminal.command`,
# MEDIDO --, pero lo rechaza si el usuario navego dentro de ella, y Firefox lo rechaza
# por defecto. Por eso hay respaldo: si a los 400 ms la pestania sigue viva, se queda
# con el aviso de cerrado a pantalla completa en vez de con el tablero muerto, que es lo
# que se veria si esto se diera por hecho.
JS_CERRAR = """
window.close();
setTimeout(function () {
  if (window.closed) { return; }
  document.body.innerHTML =
    "<div style='font:17px/1.7 system-ui;padding:80px 40px;color:#2b2b2b'>" +
    "<b style='font-size:22px'>Simulador cerrado</b><br>" +
    "El servidor se detuvo. Ya puedes cerrar esta pestana.<br>" +
    "<span style='color:#666'>Para volver a abrirlo: Iniciar.app (macOS) o " +
    "iniciar.bat (Windows).</span></div>";
}, 400);
"""

# Cuanto se espera antes de mandar el SIGTERM. El mensaje que cierra la pestania sale
# por el socket del kernel, y SIGTERM a Voila se lleva por delante a ESE kernel --
# comprobado: apaga los siete que llegaron a estar vivos a la vez --, asi que matarlo
# de inmediato cortaria el mensaje antes de que salga y la pestania se quedaria abierta
# sobre un tablero sin servidor.
ESPERA_ANTES_DE_APAGAR = 0.8

VARIABLE_PID = "ARCHIVO_PID_06"

# La URL del menu, que `menu.py` ya ponia en el entorno de toda aplicacion que lanza y que
# hasta ahora no leia nadie. Es la unica via de apagado que no necesita NI el kernel NI el
# pid: la pide el navegador y la atiende el menu, que es otro proceso.
VARIABLE_MENU = "MENU_CRITICIDAD"

# Con que clave conoce el menu a esta aplicacion. Es la misma de `tableros.py`.
CLAVE_APP = "simulador"

# La marca por la que el JS encuentra el boton. Un `widgets.Button` no trae id estable, y
# `add_class` es lo unico que le deja una a la que agarrarse. Vive aqui, en un solo sitio:
# escrita dos veces -- en Python y en el guion -- se separan sin que nada falle.
CLASE_BOTON = "chec-cerrar-simulador"

# --- El camino que NO pasa por el kernel ---------------------------------------------
# El boton es un `widgets.Button`: su clic viaja por el comm al kernel. Sin kernel no hay
# quien lo atienda, y el widget no avisa -- se queda mudo. MEDIDO: con el kernel muerto se
# pulsa Cerrar y durante ocho segundos no aparece ni "Cerrando...", ni "Simulador cerrado",
# ni el aviso de que no encontro el proceso. Y el servidor sigue en pie.
#
# El kernel se va solo por dos caminos normales, ninguno de ellos un fallo:
#   * Voila lo recicla a los 180 s de inactividad (`cull_idle_timeout` en `app.py`), que es
#     lo que deja una desconexion pasajera: la tapa del portatil, el wifi;
#   * o se cae por memoria -- cada kernel de esta aplicacion pesa ~780 MB medidos, y el
#     propio `app.py` documenta haber visto siete vivos a la vez.
#
# Asi que el clic se atiende TAMBIEN en el navegador, en fase de CAPTURA: corre antes que
# el widget y corre aunque el widget ya no exista al otro lado. Escribe el aviso el mismo,
# porque `aviso.value` es otra cosa que necesita kernel.
JS_ENGANCHE = """
(function () {
  var MENU = %(menu)s, CLAVE = %(clave)s, CLASE = %(clase)s;
  // Marca de que el guion llego a correr, para poder comprobarlo desde fuera.
  window.__chec_cierre_enganchado = true;
  // DELEGACION sobre `document`, y no `addEventListener` sobre el boton. El guion se
  // muestra desde un `Output` cuya salida forma parte del estado inicial de los widgets,
  // asi que corre ANTES de que el boton exista en el DOM: buscarlo en ese momento
  // devolvia null y el enganche se perdia en silencio -- MEDIDO, el arreglo no hacia nada
  // hasta cambiar a esto. Delegando no hay orden que respetar.
  document.addEventListener('click', function (ev) {
    var boton = ev.target && ev.target.closest ? ev.target.closest('.' + CLASE) : null;
    if (!boton) { return; }
    // Primero el aviso, y lo escribe el navegador: con el kernel muerto un `aviso.value`
    // desde Python no llega a ninguna parte, y el boton parecia inerte.
    var caja = boton.parentNode || document.body;
    var nota = caja.querySelector('.chec-aviso-cierre');
    if (!nota) {
      nota = document.createElement('span');
      nota.className = 'chec-aviso-cierre';
      nota.style.cssText = 'font:16px/1.6 system-ui;padding:8px;color:#2b2b2b';
      caja.appendChild(nota);
    }
    nota.innerHTML = '<b>Cerrando el simulador...</b>';
    // Y despues se le pide al menu que la detenga. `keepalive` porque la pestania se esta
    // cerrando: sin el, el navegador cancela la peticion en vuelo.
    if (MENU) {
      try {
        fetch(MENU + 'detener?app=' + encodeURIComponent(CLAVE),
              {method: 'POST', keepalive: true}).catch(function () {});
      } catch (e) { /* sin menu no hay a quien pedirselo; queda el camino del kernel */ }
    }
    setTimeout(function () { %(cerrar)s }, 400);
  }, true);
})();
"""


def barra(*, js: str | None = None) -> widgets.HBox:
    """El boton de cerrar con su aviso, listo para el `encabezado` del tablero.

    UN solo boton, venga de donde venga. Hubo dos cuando lo lanzaba el menu --
    "Volver al menu" y "Cerrar" -- y hacian lo MISMO con los procesos: el mismo
    SIGTERM al pid que dejo escrito `app.py`, que se lleva Voila y sus kernels.
    Solo se diferenciaban en donde dejaban al usuario, y eso no daba para un
    segundo boton.

    Apagar las cinco aplicaciones sigue siendo cosa del "Cerrar todo" del menu y
    de nadie mas: desde aqui se cerraba tambien lo que el usuario no estaba
    mirando.
    """
    # El verde de la marca, el mismo `ACENTO` de `aplicaciones/_comun/paleta.py`. Escrito
    # y no importado porque `cierre.py` corre dentro del kernel de Voila, y el cuaderno que
    # este sirve solo pone `APP_06` y `RAIZ_SRC_06` en el `sys.path`: `_comun` no esta ahi.
    # Lo que impide que se separen es `test_simulador_grafo_abajo.py`, que compara estos
    # valores contra los de la paleta.
    #
    # Va en un `widgets.HTML` y no en `button_style`: un `<style>` inyectado por innerHTML
    # SI lo aplica el navegador -- lo que no ejecuta son los `<script>` --, y asi se puede
    # fijar tambien el color del texto.
    ESTILO = widgets.HTML(
        "<style>"
        ".chec-cerrar-simulador {"
        " background: rgb(0,128,36) !important; color: #fff !important;"
        " border: 1px solid rgb(0,128,36) !important; font-weight: 600; }"
        ".chec-cerrar-simulador:hover {"
        " background: rgb(0,102,29) !important; border-color: rgb(0,102,29) !important; }"
        "</style>")
    aviso = widgets.HTML("")
    # `Output` y no un `HTML`: el JavaScript de un `HTML` no se ejecuta -- ipywidgets
    # lo mete por `innerHTML`, y el navegador no corre los `<script>` que llegan asi.
    salida = widgets.Output()
    boton = widgets.Button(
        # Sin `button_style`: "danger" es el ROJO de Jupyter, que no es un color de este
        # proyecto. El verde se pone abajo por CSS, que ademas permite fijar el color del
        # texto -- `ButtonStyle` no siempre lo expone.
        description="Cerrar",
        tooltip="Apaga el simulador y cierra esta pestania",
        layout=widgets.Layout(width="130px"))

    def cerrar(_boton) -> None:
        ruta = os.environ.get(VARIABLE_PID)
        # El pid se lee del archivo que escribio `app.py`, NUNCA de `os.getppid()`: el
        # padre de un kernel es una suposicion sobre como jupyter_client lo lanzo, y
        # mandar SIGTERM a un pid supuesto puede matar un proceso que no es la
        # aplicacion.
        if not ruta or not os.path.exists(ruta):
            aviso.value = (
                "<p style='color:#c62828;font:14px system-ui'>No se encontro el "
                "proceso de la aplicacion. Cierrala desde la terminal con Ctrl+C.</p>")
            return
        with open(ruta, encoding="utf-8") as f:
            pid = int(f.read().strip())
        boton.disabled = True
        aviso.value = ("<div style='font:16px/1.6 system-ui;padding:8px;color:#2b2b2b'>"
                       "<b>Cerrando el simulador...</b></div>")
        with salida:
            display(Javascript(js or JS_CERRAR))
        threading.Timer(ESPERA_ANTES_DE_APAGAR, os.kill, (pid, signal.SIGTERM)).start()

    # El camino del kernel se queda: es el UNICO cuando el simulador se abre solo, sin
    # menu, y es el que manda el SIGTERM al pid de Voila.
    boton.on_click(cerrar)

    # Y encima, el que no lo necesita. La clase es por donde el JS encuentra el boton.
    boton.add_class(CLASE_BOTON)
    menu = os.environ.get(VARIABLE_MENU) or ""
    if menu and not menu.endswith("/"):
        menu += "/"
    # El guion se muestra por el `Output` y no por un `HTML` por la misma razon que el JS
    # de cierre: ipywidgets mete el HTML por `innerHTML`, y el navegador NO ejecuta los
    # `<script>` que llegan asi.
    #
    # Corre UNA vez, al construir la barra -- cuando el kernel esta vivo por definicion --,
    # y lo que deja atras es un manejador que ya vive en el navegador. De ahi que siga
    # funcionando cuando el kernel se va.
    with salida:
        display(Javascript(JS_ENGANCHE % {
            "menu": json.dumps(menu or None),
            "clave": json.dumps(CLAVE_APP),
            "clase": json.dumps(CLASE_BOTON),
            "cerrar": js or JS_CERRAR,
        }))

    return widgets.HBox(
        [ESTILO, boton, aviso, salida],
        layout=widgets.Layout(width="100%", justify_content="flex-end",
                              padding="4px 12px"))
