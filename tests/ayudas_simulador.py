"""Conducir el simulador de verdad: Voila en un puerto, Chrome por CDP.

El cuaderno 06 NO se puede comprobar ejecutando sus celdas: `Simular` corre dentro
del bucle de eventos del widget y, fuera del navegador, deja las barras vacias --
que parece un fallo y no lo es. Y el defecto que motivo estas pruebas es todavia
mas invisible desde Python: los mapas tenian sus trazas llenas y el lienzo pintaba,
pero el zoom apuntaba a otro sitio. Solo se ve conduciendo el DOM y midiendo el
recuadro visible.

Este modulo es el arnes -- arrancar, esperar, hablar, medir. Lo que se comprueba
vive en `test_simulador_flujo_vivo.py`.

Todo va con eventos de verdad: `ipywidgets` sincroniza su modelo con el kernel a
traves del evento, asi que escribir la propiedad sin dispararlo cambia lo que se ve
y no lo que el kernel cree.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

# El navegador y los gestos de "irse y volver". Se reexportan al final de este modulo
# para que `A.Navegador` siga siendo lo que era: hay pruebas que lo llaman asi.
from ayudas_navegador import (  # noqa: F401
    CHROME,
    Navegador,
    avisos,
    congelar,
    espiar_consola,
    puerto_libre,
    sin_red,
)

RAIZ = Path(__file__).resolve().parents[1]
APP = RAIZ / "aplicaciones" / "06_simulador"
ESPERA_CORTA = 2.5
ESPERA_MEDIA = 6.0
ESPERA_SIMULAR = 120.0


def hay_con_que_correr() -> str | None:
    """El motivo por el que estas pruebas no se pueden correr aqui, o None."""
    if not CHROME.is_file():
        return "no hay Google Chrome para conducir el tablero"
    if not (APP / ".venv" / "bin" / "python").is_file():
        return "el entorno del simulador no esta instalado"
    if not (APP / "paquete" / "geo.json").is_file():
        return "el paquete del simulador no esta construido"
    try:
        import websocket  # noqa: F401
    except ImportError:
        return "falta websocket-client para hablar por CDP"
    return None


# --------------------------------------------------------------------- el servidor


class Simulador:
    """El simulador servido por Voila, en su propio puerto.

    Se levanta con `--puerto` explicito y NO con el puerto por defecto: el del
    contrato es el que usa el tablero del usuario, y una prueba que lo tomara
    apagaria su sesion o se colgaria de ella.
    """

    def __init__(self, puerto: int | None = None):
        self.puerto = puerto or puerto_libre()
        self.proceso: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.puerto}/"

    def arrancar(self, limite: float = 240.0) -> "Simulador":
        self.proceso = subprocess.Popen(
            [str(APP / ".venv" / "bin" / "python"), str(APP / "app.py"),
             "--no-abrir", "--puerto", str(self.puerto)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        t0 = time.time()
        while time.time() - t0 < limite:
            time.sleep(2.0)
            try:
                with urllib.request.urlopen(self.url, timeout=4) as r:
                    if r.status == 200:
                        return self
            except Exception:
                pass
        self.apagar()
        raise RuntimeError(f"el simulador no respondio en {limite:.0f} s")

    def apagar(self) -> None:
        """Se apaga el GRUPO, no el proceso: Voila deja kernels detras.

        Cada kernel del simulador son ~700 MB. Matar solo al padre los dejaria
        huerfanos, que es justo lo que el paso 9 de `PROBAR-EN-WINDOWS.md`
        persigue en el otro sistema.
        """
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
                self.proceso.wait(timeout=15)
                break
            except subprocess.TimeoutExpired:
                continue
        self.proceso = None

    def sirve(self) -> bool:
        try:
            with urllib.request.urlopen(self.url, timeout=3) as r:
                return r.status == 200
        except Exception:
            return False


# ------------------------------------------------------------------- el navegador
#
# Vive en `ayudas_navegador.py` y se importa arriba. Salio de aqui porque conducir
# Chrome no tiene nada de simulador: los cuatro tableros estaticos se conducen igual.


_UTILES = """
window.__u = {
  fig: function () { return document.querySelector('.js-plotly-plot'); },
  boton: function (texto) {
    var n = document.querySelectorAll('button');
    for (var i = 0; i < n.length; i++) {
      if ((n[i].textContent || '').trim().indexOf(texto) >= 0) { return n[i]; }
    }
    return null;
  },
};
'ok'
"""


def abrir(nav: Navegador, url: str, limite: float = 300.0) -> float:
    """Carga el tablero y espera a que su figura este montada. Devuelve los segundos."""
    t0 = time.time()
    nav.cmd("Page.navigate", url=url)
    while time.time() - t0 < limite:
        time.sleep(1.0)
        try:
            if nav.js("(function(){var g=document.querySelector('.js-plotly-plot');"
                      "return !!(g && g._fullLayout && g.data && g.data.length);})()"):
                nav.js(_UTILES)
                # Los mapas de MapLibre montan despues que la figura.
                time.sleep(4)
                return round(time.time() - t0, 1)
        except Exception:
            pass
    raise RuntimeError(f"el tablero no monto su figura en {limite:.0f} s")


# ------------------------------------------------------------------------- gestos


def _clic(nav: Navegador, expr: str) -> bool:
    return nav.js(f"""
    (function () {{
      var el = {expr};
      if (!el) {{ return false; }}
      el.scrollIntoView({{block: 'center'}});
      el.click();
      return true;
    }})()
    """)


def circuitos(nav: Navegador) -> list[str]:
    return nav.js("Array.from(document.querySelector('select').options)"
                  ".map(function(o){return o.value;})")


def circuito_actual(nav: Navegador) -> str:
    return nav.js("document.querySelector('select').value")


def cambiar_circuito(nav: Navegador, valor: str, espera: float = ESPERA_MEDIA) -> bool:
    v = json.dumps(valor)
    ok = nav.js("""
    (function () {
      var sel = document.querySelector('select');
      if (!sel) { return false; }
      sel.value = %s;
      sel.dispatchEvent(new Event('change', {bubbles: true}));
      return sel.value === %s;
    })()
    """ % (v, v))
    time.sleep(espera)
    return bool(ok)


def marcadas(nav: Navegador) -> int:
    return nav.js("document.querySelectorAll('input[type=checkbox]:checked').length")


def casillas(nav: Navegador) -> int:
    return nav.js("document.querySelectorAll('input[type=checkbox]').length")


def marcar(nav: Navegador, indices, valor: bool = True,
           espera: float = ESPERA_CORTA) -> int:
    n = nav.js("""
    (function () {
      var idx = %s, quiero = %s, n = 0;
      var cajas = document.querySelectorAll('input[type=checkbox]');
      idx.forEach(function (i) {
        var c = cajas[i];
        if (c && c.checked !== quiero) { c.click(); n++; }
      });
      return n;
    })()
    """ % (json.dumps(list(indices)), "true" if valor else "false"))
    time.sleep(espera)
    return int(n)


def pulsar(nav: Navegador, texto: str, espera: float = ESPERA_MEDIA) -> bool:
    ok = _clic(nav, f"window.__u.boton({json.dumps(texto)})")
    time.sleep(espera)
    return bool(ok)


def _indices_por_etiqueta(nav: Navegador) -> dict[str, list[int]]:
    """Las casillas repartidas por lo que son, leyendo su etiqueta.

    Todas son `input[type=checkbox]` en el mismo documento, asi que por indice no
    se distinguen. Los vanos se rotulan con su FID, que es solo digitos; las
    variables con su nombre; las actividades del contrato empiezan por su costo.
    Sin este reparto, una prueba que marca "los primeros cuatro" empieza a marcar
    variables en cuanto le toca un circuito con pocos vanos.
    """
    return nav.js("""
    (function () {
      var out = {vanos: [], variables: [], actividades: []};
      document.querySelectorAll('input[type=checkbox]').forEach(function (c, i) {
        var lab = c.closest('label') || c.parentElement;
        var t = ((lab ? lab.textContent : '') || '').trim();
        if (/^\\d+$/.test(t)) { out.vanos.push(i); }
        else if (t.charAt(0) === '$') { out.actividades.push(i); }
        else { out.variables.push(i); }
      });
      return out;
    })()
    """)


def indices_de_vano(nav: Navegador) -> list[int]:
    return _indices_por_etiqueta(nav)["vanos"]


def indices_de_variable(nav: Navegador) -> list[int]:
    return _indices_por_etiqueta(nav)["variables"]


def deslizadores(nav: Navegador) -> int:
    """Cuantos controles de valor hay abiertos.

    Es lo que se puede afirmar del valor de una variable desde una prueba: los
    controles son deslizadores de `noUiSlider`, y NO se dejan mover por CDP --
    comprobados los tres caminos, teclado sobre el asa, toque en la barra y
    arrastre con eventos de raton de verdad, ninguno mueve el valor. Lo que si se
    conduce es CUALES variables entran a la simulacion, que es lo que las casillas
    deciden, y los dos botones de aplicar, que abren controles con el valor
    sugerido.
    """
    # El primero es el deslizador de la ventana, que no es una variable.
    return max(0, int(nav.js("document.querySelectorAll('.noUi-target').length")) - 1)


def responde(nav: Navegador) -> dict:
    """Dos gestos que SOLO puede contestar el kernel, uno en cada sentido.

    `Limpiar` desmarca los quince vanos del top; cambiar de circuito vuelve a marcar
    el top del nuevo. Las casillas las pinta el navegador, pero CUALES quedan
    marcadas lo decide el tablero, que corre en el kernel. Sin kernel el gesto se ve
    -- el boton se hunde -- y no pasa nada.

    Se necesitan los dos sentidos: quedarse solo con `Limpiar` daria por vivo a un
    tablero que ya estaba en cero, y quedarse solo con el cambio de circuito daria
    por vivo a uno que ya tenia sus quince marcados.

    Un `Simular` no sirve como sonda: el mapa simulado CONSERVA lo ultimo que dibujo,
    asi que "tiene vertices" se cumple igual con el kernel muerto.
    """
    al_entrar = marcadas(nav)
    pulsar(nav, "Limpiar", espera=6.0)
    tras_limpiar = marcadas(nav)

    actual = circuito_actual(nav)
    destino = next((c for c in circuitos(nav) if c != actual), None)
    cambiar_circuito(nav, destino, espera=10.0)
    tras_cambiar = marcadas(nav)
    dibujo = estado(nav)["base"]["vertices"]
    return {"ok": bool(tras_limpiar == 0 and tras_cambiar > 0 and dibujo > 0),
            "marcadas_al_entrar": al_entrar, "tras_limpiar": tras_limpiar,
            "tras_cambiar_circuito": tras_cambiar, "circuito": destino,
            "vertices_base": dibujo}


def simular(nav: Navegador, limite: float = ESPERA_SIMULAR) -> dict:
    """Pulsa Simular y espera a que el mapa simulado deje de estar vacio."""
    t0 = time.time()
    _clic(nav, 'window.__u.boton("Simular")')
    while time.time() - t0 < limite:
        time.sleep(2.0)
        e = estado(nav)
        if e["sim"]["vertices"] > 0:
            return {"dibujo": True, "s": round(time.time() - t0, 1), "estado": e}
    return {"dibujo": False, "s": round(time.time() - t0, 1), "estado": estado(nav)}


# -------------------------------------------------------------------- la medicion

_ESTADO = """
(function () {
  var g = window.__u.fig(), fl = g._fullLayout;
  var W = fl.width - fl.margin.l - fl.margin.r;
  var H = fl.height - fl.margin.t - fl.margin.b;
  function mercY(lat) {
    var s = Math.sin(lat * Math.PI / 180);
    return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
  }
  function invMercY(y) {
    var n = Math.PI * (1 - 2 * y);
    return 180 / Math.PI * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
  }
  var out = {figura: [fl.width, fl.height]};
  [['map', 'base'], ['map2', 'sim']].forEach(function (par, k) {
    var cfg = fl[par[0]];
    if (!cfg) { out[par[1]] = {vertices: 0, dentro: 0, pct: null}; return; }
    var dx = cfg.domain.x, dy = cfg.domain.y;
    var wpx = (dx[1] - dx[0]) * W, hpx = (dy[1] - dy[0]) * H;
    // MapLibre: a zoom z el mundo mide 512 * 2^z pixeles.
    var mundo = 512 * Math.pow(2, cfg.zoom);
    var cx = (cfg.center.lon + 180) / 360, cy = mercY(cfg.center.lat);
    var caja = {oeste: (cx - wpx / 2 / mundo) * 360 - 180,
                este: (cx + wpx / 2 / mundo) * 360 - 180,
                norte: invMercY(cy - hpx / 2 / mundo),
                sur: invMercY(cy + hpx / 2 / mundo)};
    var dentro = 0, total = 0, porTraza = {};
    g.data.forEach(function (t) {
      if (t.type !== 'scattermap') { return; }
      if (((t.subplot === 'map2') ? 1 : 0) !== k) { return; }
      var la = t.lat || [], lo = t.lon || [], n = 0;
      for (var i = 0; i < la.length; i++) {
        if (la[i] === null || lo[i] === null) { continue; }
        total++; n++;
        if (lo[i] >= caja.oeste && lo[i] <= caja.este &&
            la[i] <= caja.norte && la[i] >= caja.sur) { dentro++; }
      }
      if (n) { porTraza[t.name || '?'] = n; }
    });
    out[par[1]] = {ancho_px: Math.round(wpx), alto_px: Math.round(hpx),
                   zoom: cfg.zoom, vertices: total, dentro: dentro,
                   pct: total ? Math.round(1000 * dentro / total) / 10 : null,
                   trazas: porTraza};
  });
  out.titulos = (g.layout.annotations || []).map(function (a) {
    return (a.text || '').replace(/<[^>]*>/g, ''); }).filter(function (t) { return t; });
  return out;
})()
"""


def estado(nav: Navegador) -> dict:
    """Lo que se puede afirmar del tablero: los dos mapas y sus recuadros.

    `pct` es la clave: que fraccion de lo DIBUJADO cae dentro de lo que el mapa
    MUESTRA. Contar vertices no basta -- el defecto que estas pruebas fijan tenia
    las trazas llenas y el 4,2% a la vista.
    """
    return nav.js(_ESTADO)
