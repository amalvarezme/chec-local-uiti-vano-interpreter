"""Conducir los cuatro tableros ESTATICOS: levantar el suyo, cargarlo y moverle algo.

El simulador tiene su arnes aparte (`ayudas_simulador.py`) porque tiene un kernel
detras. Estos cuatro no: son un HTML congelado con su `datos.json` al lado, servido
por `aplicaciones/_comun/servidor.py`. Lo unico que hace falta saber de cada uno es
cual es su figura y cual es su control principal, que es lo que hay en `PANELES`.

Que el control sea el de cada tablero y no un clic generico importa: lo que se quiere
comprobar es que el tablero RESPONDE, y la respuesta se mide en la figura -- que
cambie el numero de valores dibujados --, no en que el DOM acepte el evento. Un
`select` al que nadie escucha tambien cambia de valor.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

from ayudas_navegador import Navegador, puerto_libre

RAIZ = Path(__file__).resolve().parents[1]
APLICACIONES = RAIZ / "aplicaciones"


class Panel:
    """Un tablero estatico: su carpeta, su figura y como se le mueve algo."""

    def __init__(self, carpeta: str, figura: str, control: str, *, fechas: bool = False):
        self.carpeta = carpeta
        self.figura = figura
        self.control = control
        # 02 no elige circuito: acota un rango de fechas con dos `input[type=date]`.
        self.fechas = fechas

    @property
    def ruta(self) -> Path:
        return APLICACIONES / self.carpeta

    def __repr__(self) -> str:
        return f"<Panel {self.carpeta}>"


PANELES: tuple[Panel, ...] = (
    Panel("01_clima", "clima-nube-vano", "cl-circuito"),
    Panel("02_agrupamiento_vanos", "agrupamiento-vanos", "va-desde", fechas=True),
    Panel("03_trayectorias_circuitos", "trayectorias-circuitos", "tr-circuito"),
    Panel("04_trayectorias_vanos", "vano-ventana", "v4-circuito"),
)


def motivo_para_saltar(panel: Panel) -> str | None:
    """Por que este tablero no se puede conducir aqui, o None."""
    from ayudas_navegador import CHROME

    if not CHROME.is_file():
        return "no hay Google Chrome para conducir el tablero"
    if not (panel.ruta / ".venv" / "bin" / "python").is_file():
        return f"el entorno de {panel.carpeta} no esta instalado"
    if not (panel.ruta / "panel" / "index.html").is_file():
        return f"el panel de {panel.carpeta} no esta construido"
    try:
        import websocket  # noqa: F401
    except ImportError:
        return "falta websocket-client para hablar por CDP"
    return None


class Servido:
    """El tablero servido en un puerto propio. Nunca el del contrato.

    El del contrato -- 8801..8804 -- es el que usa la sesion del usuario: tomarlo
    apagaria su tablero o dejaria a la prueba midiendo el suyo.
    """

    def __init__(self, panel: Panel, puerto: int | None = None):
        self.panel = panel
        self.puerto = puerto or puerto_libre()
        self.proceso: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.puerto}/"

    def arrancar(self, limite: float = 240.0) -> "Servido":
        self.proceso = subprocess.Popen(
            [str(self.panel.ruta / ".venv" / "bin" / "python"),
             str(self.panel.ruta / "app.py"),
             "--no-abrir", "--puerto", str(self.puerto)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        t0 = time.time()
        while time.time() - t0 < limite:
            time.sleep(1.0)
            if self.sirve():
                return self
        self.apagar()
        raise RuntimeError(f"{self.panel.carpeta} no respondio en {limite:.0f} s")

    def sirve(self) -> bool:
        try:
            with urllib.request.urlopen(self.url, timeout=3) as r:
                return r.status == 200
        except Exception:
            return False

    def apagar_por_su_puerta(self) -> None:
        """El `POST /apagar` del boton de cerrar del propio tablero."""
        try:
            peticion = urllib.request.Request(self.url + "apagar", method="POST",
                                              data=b"")
            urllib.request.urlopen(peticion, timeout=5).read()
        except Exception:
            # El servidor se apaga mientras contesta: que la respuesta se pierda por
            # el camino es lo normal, no un fallo.
            pass
        time.sleep(2.0)

    def apagar(self) -> None:
        import os
        import signal
        if self.proceso is None:
            return
        for senal in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(os.getpgid(self.proceso.pid), senal)
            except (ProcessLookupError, PermissionError):
                break
            try:
                self.proceso.wait(timeout=10)
                break
            except subprocess.TimeoutExpired:
                continue
        self.proceso = None


def cargar(nav: Navegador, servido: Servido, limite: float = 240.0) -> float:
    """Navega al tablero y espera a que su figura este montada. Devuelve los segundos."""
    figura = json.dumps(servido.panel.figura)
    t0 = time.time()
    nav.cmd("Page.navigate", url=servido.url)
    while time.time() - t0 < limite:
        time.sleep(1.0)
        try:
            if nav.js("(function(){var g=document.getElementById(%s);"
                      "return !!(g && g._fullLayout && g.data && g.data.length);})()"
                      % figura):
                # Los mapas de MapLibre montan despues que la figura.
                time.sleep(3.0)
                return round(time.time() - t0, 1)
        except Exception:
            pass
    raise RuntimeError(
        f"{servido.panel.carpeta}: no monto la figura en {limite:.0f} s")


_HUELLA = """
(function () {
  var g = document.getElementById(%s);
  if (!g || !g.data) { return null; }
  var trazas = 0, valores = 0;
  g.data.forEach(function (t) {
    trazas++;
    ['x', 'y', 'lat', 'lon'].forEach(function (k) {
      if (t[k] && t[k].length) { valores += t[k].length; }
    });
  });
  return {trazas: trazas, valores: valores};
})()
"""


def huella(nav: Navegador, panel: Panel) -> dict | None:
    """Cuanto hay dibujado ahora mismo. Es lo que tiene que cambiar al mover algo."""
    return nav.js(_HUELLA % json.dumps(panel.figura))


_MOVER_SELECT = """
(function () {
  var s = document.getElementById(%s);
  if (!s) { return {ok: false, motivo: 'no esta el control'}; }
  var otras = Array.prototype.map.call(s.options, function (o) { return o.value; })
    .filter(function (v) { return v !== s.value; });
  if (!otras.length) { return {ok: false, motivo: 'una sola opcion'}; }
  s.value = otras[0];
  s.dispatchEvent(new Event('change', {bubbles: true}));
  return {ok: true, valor: s.value};
})()
"""

# 02 acota por fechas. Se ALTERNA entre el minimo y el maximo: fijarlo siempre al
# maximo hace que el segundo gesto no cambie nada, y una prueba lo lee como "el
# tablero no reacciono" cuando lo que paso es que no se le pidio nada.
_MOVER_FECHA = """
(function () {
  var d = document.getElementById(%s);
  if (!d) { return {ok: false, motivo: 'no esta el control'}; }
  var antes = d.value;
  d.value = (antes === d.min) ? d.max : d.min;
  d.dispatchEvent(new Event('change', {bubbles: true}));
  return {ok: d.value !== antes, valor: d.value, antes: antes};
})()
"""


def mover(nav: Navegador, panel: Panel, espera: float = 5.0) -> dict:
    """Mueve el control principal del tablero y dice si la figura le hizo caso."""
    antes = huella(nav, panel)
    plantilla = _MOVER_FECHA if panel.fechas else _MOVER_SELECT
    gesto = nav.js(plantilla % json.dumps(panel.control))
    time.sleep(espera)
    despues = huella(nav, panel)
    return {"gesto": gesto, "antes": antes, "despues": despues,
            "responde": bool(gesto and gesto.get("ok") and antes != despues)}
