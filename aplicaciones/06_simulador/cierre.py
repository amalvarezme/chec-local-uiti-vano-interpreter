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
    aviso = widgets.HTML("")
    # `Output` y no un `HTML`: el JavaScript de un `HTML` no se ejecuta -- ipywidgets
    # lo mete por `innerHTML`, y el navegador no corre los `<script>` que llegan asi.
    salida = widgets.Output()
    boton = widgets.Button(
        description="Cerrar", button_style="danger",
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

    boton.on_click(cerrar)
    return widgets.HBox(
        [boton, aviso, salida],
        layout=widgets.Layout(width="100%", justify_content="flex-end",
                              padding="4px 12px"))
