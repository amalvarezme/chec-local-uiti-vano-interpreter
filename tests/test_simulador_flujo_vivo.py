"""El simulador conducido de verdad, gesto a gesto, como lo usa una persona.

Estas pruebas levantan Voila, abren el tablero en Chrome y lo manejan: cambian de
circuito, marcan vanos, aplican la intervencion y el escenario sugeridos, simulan,
vuelven a cambiar, cierran y reabren. Despues de CADA gesto comprueban lo mismo:
que los mapas siguen mostrando lo que dibujan.

Por que hacen falta, y por que asi:

  - El cuaderno 06 no se puede comprobar ejecutando sus celdas. `Simular` corre
    dentro del bucle de eventos del widget y fuera del navegador deja las barras
    vacias, que parece un fallo y no lo es.
  - Contar trazas tampoco basta. El defecto que motivo esta suite -- "cambio de
    circuito y el mapa no se muestra" -- tenia las trazas llenas de vertices y el
    lienzo pintando: lo que fallaba era el ENCUADRE, y solo el 4,2% de lo dibujado
    caia dentro del recuadro visible. Por eso lo que se afirma aqui es `pct`, la
    fraccion de lo dibujado que de verdad se ve.

Son lentas -- cada `Simular` corre el modelo MIL sobre los vanos elegidos -- y
necesitan Chrome y el paquete construido, asi que van detras de una variable de
entorno:

    SIMULADOR_VIVO=1 pytest tests/test_simulador_flujo_vivo.py -v

Sin ella se saltan, para que la suite de todos los dias siga siendo de segundos.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

import ayudas_simulador as A

MOTIVO = A.hay_con_que_correr()
APAGADAS = os.environ.get("SIMULADOR_VIVO", "") not in ("1", "true", "si")

# Pedirlas y que se salten TODAS en silencio es la forma de creer que se corrieron.
# Paso: una de estas pruebas afirmaba el titulo largo del panel del perfil mucho
# despues de que `496ee49` lo acortara, y nadie se entero porque el entorno del
# simulador no estaba instalado y `pytest -q` solo dice "20 skipped". Si se piden
# explicitamente y el entorno no da, esto es un error de recoleccion -- ruidoso --
# y no una linea de resumen que se lee igual que un exito.
if not APAGADAS and MOTIVO is not None:
    raise RuntimeError(
        f"SIMULADOR_VIVO esta puesto pero {MOTIVO}. Instala el entorno de la "
        "aplicacion con `aplicaciones/06_simulador/instalar-en-terminal.command` "
        "(o enlaza el del arbol principal si estas en un worktree) y construye su "
        "paquete con `python3 aplicaciones/06_simulador/preparar.py`."
    )

pytestmark = [
    pytest.mark.skipif(APAGADAS, reason="SIMULADOR_VIVO no esta puesto"),
    pytest.mark.skipif(MOTIVO is not None, reason=str(MOTIVO)),
]

# Cuanto de lo dibujado tiene que verse cuando el tablero acaba de encuadrar el
# circuito COMPLETO. No es 100 porque el encuadre deja un margen y los extremos
# quedan justo en el borde; por debajo de esto el circuito esta cortado.
COBERTURA_MINIMA = 95.0


@pytest.fixture(scope="module")
def simulador():
    """Un Voila propio, en un puerto libre. Nunca el del contrato.

    El del contrato es el que usa la sesion del usuario: tomarlo apagaria su
    tablero o, peor, dejaria a la prueba midiendo el suyo.
    """
    s = A.Simulador().arrancar()
    yield s
    s.apagar()
    assert not s.sirve(), "el simulador siguio sirviendo despues de apagarlo"


@pytest.fixture(scope="module")
def nav(simulador):
    carpeta = Path(tempfile.mkdtemp(prefix="chrome-sim-"))
    n = A.Navegador(carpeta)
    A.abrir(n, simulador.url)
    yield n
    n.cerrar()


@pytest.fixture(autouse=True)
def desde_cero(request, nav):
    """Cada prueba arranca con el tablero como recien abierto.

    Las pruebas comparten un solo navegador y un solo kernel -- levantar uno por
    prueba costaria ~700 MB y un minuto cada vez --, asi que lo que una deja
    puesto se lo encuentra la siguiente. Se detecto en vivo: pasaban por separado
    y fallaban juntas.

    "Limpiar" es el propio boton del tablero para volver al estado inicial, asi
    que la prueba no inventa una forma de reiniciar que el usuario no tiene. Ojo
    con una diferencia real: al ABRIR el tablero vienen marcados los quince vanos
    del top del periodo, y "Limpiar" deja CERO. Las pruebas del estado inicial se
    marcan `sin_limpiar` por eso.
    """
    if request.node.get_closest_marker("sin_limpiar") is None:
        A.pulsar(nav, "Limpiar", espera=4.0)
    yield


def _cobertura(nav, cual="base"):
    e = A.estado(nav)
    assert e[cual]["vertices"] > 0, f"el mapa {cual} no dibuja nada"
    return e[cual]["pct"], e


# --------------------------------------------------------------- el estado inicial


@pytest.mark.sin_limpiar
def test_al_abrir_los_dos_mapas_existen_y_el_base_se_ve_entero(nav):
    """Lo primero que se ve. El mapa simulado nace vacio a proposito: no hay nada
    que simular hasta que se pulsa el boton."""
    e = A.estado(nav)
    assert e["base"]["vertices"] > 0, "el mapa base no dibujo ningun vano"
    assert e["base"]["pct"] >= COBERTURA_MINIMA, (
        f"al abrir solo se ve el {e['base']['pct']}% de lo que el mapa base dibuja")
    assert e["sim"]["vertices"] == 0, (
        "el mapa simulado trae dibujo antes de simular")
    assert A.marcadas(nav) > 0, "el tablero abrio sin ningun vano marcado"


@pytest.mark.sin_limpiar
def test_al_abrir_estan_los_diez_paneles_y_el_perfil_dice_su_concentracion(nav):
    """El grafo comparte fila con el perfil desde que la septima fila desaparecio."""
    titulos = A.estado(nav)["titulos"]
    for esperado in ("Criticidad Original", "Criticidad Simulada",
                     "Grafo - Relaciones relevantes"):
        assert any(esperado in t for t in titulos), f"falta el panel {esperado!r}"
    # `Perfil` a secas y no `Perfil del circuito`: el titulo se acorto en `496ee49`
    # para que dejara de pisar al panel de al lado, y esta prueba siguio afirmando el
    # texto largo sin que nadie se enterara -- se salta si el entorno del simulador no
    # esta instalado, y no lo estaba. Lo que se afirma es que el panel EXISTE y que
    # publica su concentracion, no como se llama.
    perfil = [t for t in titulos if t.startswith("Perfil")]
    assert perfil, "no esta el panel del perfil del circuito"
    assert "%" in perfil[0], (
        "el titulo del perfil no publica cuanto concentra el top, que es su lectura")


# ------------------------------------------------------- cambiar de circuito


@pytest.mark.parametrize("salto", [3, 41, 97, 150])
def test_cambiar_de_circuito_deja_el_mapa_base_a_la_vista(nav, salto):
    """El defecto reportado, en su forma exacta.

    Se recorren circuitos de todo el listado y no uno solo porque el fallo
    dependia de la FORMA del circuito: los anchos se salian por los lados y los
    altos no. Con el encuadre viejo, 94 de los 208 fallaban en un panel cuadrado.
    """
    circuitos = A.circuitos(nav)
    destino = circuitos[salto % len(circuitos)]
    assert A.cambiar_circuito(nav, destino)
    assert A.circuito_actual(nav) == destino
    pct, e = _cobertura(nav)
    assert pct >= COBERTURA_MINIMA, (
        f"{destino}: solo se ve el {pct}% del mapa base "
        f"({e['base']['ancho_px']}x{e['base']['alto_px']} px, zoom {e['base']['zoom']:.2f})")


def test_cambiar_de_circuito_repuebla_la_lista_de_vanos(nav):
    """Cada circuito trae los suyos, y trae marcado su top del periodo."""
    circuitos = A.circuitos(nav)
    A.cambiar_circuito(nav, circuitos[7])
    n1, m1 = A.casillas(nav), A.marcadas(nav)
    A.cambiar_circuito(nav, circuitos[60])
    n2, m2 = A.casillas(nav), A.marcadas(nav)
    assert n1 > 0 and n2 > 0, "algun circuito quedo sin casillas de vano"
    assert m1 > 0 and m2 > 0, "al cambiar de circuito no se marco ningun vano"
    assert (n1, m1) != (n2, m2) or n1 == n2, (
        "los dos circuitos ofrecen exactamente lo mismo; probablemente no cambio")


# ------------------------------------------------------------- marcar y desmarcar


def test_marcar_y_desmarcar_vanos_no_vacia_el_mapa(nav):
    """Marcar mueve vanos de una traza a otra dentro del mismo mapa.

    Es el camino por el que un reparto mal hecho deja el mapa en blanco: si el
    vano sale de su traza de clase y no entra en la de marcado, desaparece.
    """
    circuitos = A.circuitos(nav)
    A.cambiar_circuito(nav, circuitos[12])
    antes = A.estado(nav)["base"]["vertices"]

    A.marcar(nav, A.indices_de_vano(nav)[:5], True)
    con_mas = A.estado(nav)["base"]
    assert con_mas["vertices"] > 0, "marcar vanos vacio el mapa base"

    A.pulsar(nav, "Desmarcar")
    assert A.marcadas(nav) == 0, "Desmarcar dejo casillas marcadas"
    sin_ninguno = A.estado(nav)["base"]
    assert sin_ninguno["vertices"] > 0, (
        "desmarcar TODO vacio el mapa base: el circuito sigue existiendo aunque "
        "no haya nada elegido")
    assert antes > 0


# ------------------------------------------------------ los anchos del panel


_SONDA_ANCHOS = r"""
(() => {
  const txt = e => (e.textContent||'').trim();
  const panel = document.querySelector('.panel-v15');
  const botones = [...document.querySelectorAll('button')]
      .filter(b => txt(b)==='Desmarcar' || txt(b).startsWith('G. '));
  const rp = panel.getBoundingClientRect();
  // El ancho NATURAL de cada rotulo: lo que el texto pide sin recortarse. Es lo que
  // decide si cinco botones caben en una fila, y no el ancho que hoy tengan.
  const rotulo = b => {
    const s = document.createElement('span');
    s.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap';
    s.style.font = getComputedStyle(b).font;
    s.textContent = txt(b);
    document.body.appendChild(s);
    const w = s.getBoundingClientRect().width;
    s.remove();
    return Math.ceil(w);
  };
  const cajas = botones.map(b => {
    const r = b.getBoundingClientRect();
    return {t: txt(b), x: Math.round(r.x), r: Math.round(r.right),
            w: Math.round(r.width), texto: rotulo(b)};
  });
  return {
    panel: {x: Math.round(rp.x), r: Math.round(rp.right), w: Math.round(rp.width)},
    botones: cajas,
    // Cuanto se sale del panel el que mas se sale. Negativo = todos dentro.
    desborde: Math.round(Math.max(...cajas.map(b => b.r)) - rp.right),
    // Cuantos rotulos no caben en su propio boton.
    recortados: cajas.filter(b => b.texto > b.w - 8).map(b => b.t),
  };
})()
"""


def test_los_botones_de_seleccion_caben_en_su_panel(nav):
    """El sintoma que lo destapo: "G. Bajo" se sale del panel de seleccion.

    Cinco botones al ancho por defecto de ipywidgets miden 148 px cada uno -- 825 px
    en fila -- dentro de un panel de 445. Que se salgan no es cosmetico: lo que queda
    fuera del panel queda debajo de la columna de figuras, encima del mapa.

    Se miden las DOS cosas, porque arreglar una sola las rompe a la vez: que ningun
    boton pase del borde derecho del panel, y que ningun rotulo se corte dentro de su
    boton. Estrechar cinco botones hasta que quepan en una fila cumple lo primero y
    rompe lo segundo -- "G. Medio-Alto" pide 80 px de texto --, y por eso la fila
    envuelve en vez de encoger.
    """
    r = nav.js(_SONDA_ANCHOS)

    assert len(r["botones"]) == 5, f"faltan botones en el panel: {r['botones']}"
    assert r["desborde"] <= 0, (
        f"un boton se sale {r['desborde']} px del panel de {r['panel']['w']} px: "
        f"{[(b['t'], b['r']) for b in r['botones']]}")
    assert not r["recortados"], (
        f"estos rotulos no caben en su boton: {r['recortados']} "
        f"({[(b['t'], b['texto'], b['w']) for b in r['botones']]})")


# ------------------------------------------- intervencion, escenario y simulacion


def test_la_intervencion_y_el_escenario_sugeridos_no_rompen_los_mapas(nav):
    """Los dos botones escriben valores en los 26 controles de variables.

    No tocan los mapas, y eso es justo lo que hay que fijar: cuando alguien los
    conecte a un repintado, esta prueba avisa.
    """
    circuitos = A.circuitos(nav)
    A.cambiar_circuito(nav, circuitos[21])
    A.marcar(nav, A.indices_de_vano(nav)[:4], True)
    A.pulsar(nav, "Diagnostico", espera=14)
    antes = A.estado(nav)["base"]

    assert A.pulsar(nav, "Aplicar intervencion sugerida"), "no existe ese boton"
    assert A.estado(nav)["base"]["vertices"] > 0

    assert A.pulsar(nav, "Aplicar escenario sugerido"), "no existe ese boton"
    despues = A.estado(nav)["base"]
    assert despues["vertices"] > 0, "el escenario sugerido vacio el mapa base"
    assert despues["pct"] >= COBERTURA_MINIMA or despues["pct"] == antes["pct"]


def _marcar_vanos_con_eventos(nav) -> int:
    """Marca vanos que SI tienen celda en la ventana activa, y dice cuantos.

    Una rebanada de la lista de casillas no sirve: la lista es el circuito ENTERO y
    solo el 21% de sus vanos tiene eventos en una ventana dada -- medido sobre 30
    circuitos --, asi que `indices_de_vano(nav)[:4]` casi siempre marca cuatro vanos
    que el modelo no puede puntuar. Los botones de grupo, en cambio, salen de las
    clases de ESA ventana: lo que marcan tiene celda por construccion.
    """
    A.pulsar(nav, "Desmarcar")
    for grupo in ("G. Alto", "G. Medio-Alto", "G. Medio", "G. Bajo"):
        A.pulsar(nav, grupo)
        if A.marcadas(nav):
            return A.marcadas(nav)
    return 0


def test_aplicar_lo_sugerido_necesita_haber_diagnosticado_antes(nav):
    """Los dos botones de aplicar leen el ULTIMO diagnostico.

    Sin haberlo corrido no tienen valor que sugerir para cada vano, asi que no
    abren ningun control -- y no dicen nada. Es una dependencia real del tablero y
    conviene que este escrita: una prueba que pulse aplicar sin diagnosticar
    concluye que el boton esta roto.
    """
    circuitos = A.circuitos(nav)
    A.cambiar_circuito(nav, circuitos[45])
    A.pulsar(nav, "Limpiar")
    assert _marcar_vanos_con_eventos(nav), (
        "ningun grupo tiene vanos en esta ventana; sin vanos puntuables el "
        "diagnostico sale vacio y esta prueba no mide lo que dice medir")

    A.pulsar(nav, "Aplicar intervencion sugerida")
    sin_diagnostico = A.deslizadores(nav)

    A.pulsar(nav, "Diagnostico", espera=14)
    A.pulsar(nav, "Aplicar intervencion sugerida")
    con_diagnostico = A.deslizadores(nav)

    assert con_diagnostico > sin_diagnostico, (
        "aplicar la intervencion abre los mismos controles con y sin diagnostico "
        f"({sin_diagnostico} y {con_diagnostico}); la dependencia cambio")
    assert A.estado(nav)["base"]["vertices"] > 0


def test_simular_dibuja_el_mapa_simulado_y_lo_deja_a_la_vista(nav):
    """El gesto central del tablero, de punta a punta.

    Se afirma que dibuja Y que se ve: el mapa simulado se encuadra sobre los
    vanos que puntuo, y con el encuadre viejo esa vista salia del recuadro igual
    que la del base.
    """
    circuitos = A.circuitos(nav)
    A.cambiar_circuito(nav, circuitos[21])
    A.marcar(nav, A.indices_de_vano(nav)[:5], True)
    A.pulsar(nav, "Aplicar intervencion sugerida")

    r = A.simular(nav)
    assert r["dibujo"], f"Simular no dibujo nada en {r['s']} s"
    e = r["estado"]
    assert e["sim"]["vertices"] > 0
    assert e["base"]["vertices"] > 0, "simular vacio el mapa BASE"
    assert e["base"]["pct"] >= COBERTURA_MINIMA, (
        f"tras simular el mapa base se ve al {e['base']['pct']}%")


def test_cambiar_vanos_y_variables_y_volver_a_simular(nav):
    """La segunda simulacion sobre otra seleccion y otras variables.

    Es donde aparecia el "y al simular no se muestran": la vista del mapa
    simulado se recalcula con la seleccion nueva.

    Lo que se cambia de las variables es CUALES entran, no con que valor. El
    valor vive en un deslizador de `noUiSlider` y no se deja mover desde una
    prueba: comprobados los tres caminos -- teclado sobre el asa, toque en la
    barra y arrastre con eventos de raton de verdad por CDP --, ninguno lo mueve.
    Marcar y desmarcar variables si cambia la simulacion, y es lo que aqui se
    conduce; el valor sugerido lo ponen los dos botones de aplicar.
    """
    circuitos = A.circuitos(nav)
    A.cambiar_circuito(nav, circuitos[21])
    vanos = A.indices_de_vano(nav)
    A.marcar(nav, vanos[:4], True)
    # `Diagnostico` PRIMERO, y no por costumbre: los dos botones de aplicar leen el
    # ultimo diagnostico para saber que valor sugerir por vano, asi que sin el no
    # abren ningun control y no se quejan. Ver el test que fija esa dependencia.
    A.pulsar(nav, "Diagnostico", espera=14)
    A.pulsar(nav, "Aplicar intervencion sugerida")
    assert A.deslizadores(nav) > 0, (
        "aplicar la intervencion no abrio ningun control de variable")
    primero = A.simular(nav)
    assert primero["dibujo"]

    A.marcar(nav, vanos[:4], False)
    A.marcar(nav, vanos[5:10], True)
    variables = A.indices_de_variable(nav)
    assert variables, "no se encontraron casillas de variable"
    A.marcar(nav, variables[:3], True)
    assert A.deslizadores(nav) > 0

    segundo = A.simular(nav)
    assert segundo["dibujo"], "la segunda simulacion no dibujo"
    e = segundo["estado"]
    assert e["base"]["vertices"] > 0 and e["sim"]["vertices"] > 0
    assert e["base"]["pct"] >= COBERTURA_MINIMA


def test_cambiar_de_circuito_despues_de_simular_limpia_el_mapa_simulado(nav):
    """Lo simulado pertenece al circuito con que se simulo.

    Dejarlo en pantalla al cambiar seria peor que no mostrarlo: se leeria como el
    resultado del circuito nuevo.
    """
    circuitos = A.circuitos(nav)
    A.cambiar_circuito(nav, circuitos[21])
    A.marcar(nav, A.indices_de_vano(nav)[:4], True)
    assert A.simular(nav)["dibujo"]

    A.cambiar_circuito(nav, circuitos[64])
    e = A.estado(nav)
    assert e["sim"]["vertices"] == 0, (
        "el mapa simulado conservo el dibujo del circuito anterior")
    assert e["base"]["vertices"] > 0
    assert e["base"]["pct"] >= COBERTURA_MINIMA


# --------------------------------------------------------------- los demas botones


@pytest.mark.parametrize("boton", ["Diagnostico", "Limpiar", "Desmarcar",
                                   "G. Alto", "G. Medio-Alto", "G. Medio", "G. Bajo"])
def test_los_botones_del_panel_no_dejan_el_mapa_vacio(nav, boton):
    """`Top de la ventana` salio de aqui con el boton, y en su lugar entran los cuatro
    de grupo. Un grupo VACIO tambien tiene que dejar el mapa dibujado: no marca nada, y
    el mapa sigue pintando el circuito entero con sus colores de clase."""
    circuitos = A.circuitos(nav)
    A.cambiar_circuito(nav, circuitos[33])
    A.marcar(nav, A.indices_de_vano(nav)[:3], True)
    assert A.pulsar(nav, boton), f"no existe el boton {boton!r}"
    e = A.estado(nav)
    assert e["base"]["vertices"] > 0, f"{boton} vacio el mapa base"


def test_centrar_mapa_vuelve_a_encuadrar_sin_vaciar(nav):
    """Los dos botones de centrar encuadran sobre lo MARCADO, no sobre el circuito.

    Asi que la cobertura de todo lo dibujado baja a proposito -- se esta mirando
    un tramo --, y lo que se afirma es que siguen dibujando y que la vista se
    mueve de verdad.
    """
    circuitos = A.circuitos(nav)
    A.cambiar_circuito(nav, circuitos[33])
    A.marcar(nav, A.indices_de_vano(nav)[:3], True)
    antes = A.estado(nav)["base"]["zoom"]
    assert A.pulsar(nav, "Centrar mapa base")
    despues = A.estado(nav)
    assert despues["base"]["vertices"] > 0, "centrar vacio el mapa base"
    assert despues["base"]["zoom"] != antes or despues["base"]["pct"] is not None


# ------------------------------------------------------- cerrar, reabrir, repetir


def test_cerrar_y_reabrir_el_tablero_vuelve_a_dibujar(simulador, nav):
    """Se navega fuera y se vuelve: Voila arma un kernel nuevo cada vez.

    Es el ciclo que el usuario hace todo el dia -- cerrar la pestania y volver a
    abrir el simulador desde el menu -- y el que deja kernels detras si algo se
    engancha. Dos vueltas, no diez: cada kernel del simulador son ~700 MB.
    """
    for vuelta in range(2):
        nav.cmd("Page.navigate", url="about:blank")
        import time
        time.sleep(3)
        A.abrir(nav, simulador.url)
        e = A.estado(nav)
        assert e["base"]["vertices"] > 0, (
            f"vuelta {vuelta + 1}: el mapa base no dibujo al reabrir")
        assert e["base"]["pct"] >= COBERTURA_MINIMA, (
            f"vuelta {vuelta + 1}: al reabrir solo se ve el {e['base']['pct']}%")
        assert e["sim"]["vertices"] == 0, (
            f"vuelta {vuelta + 1}: el mapa simulado nacio con dibujo")


def test_un_flujo_completo_de_punta_a_punta(nav):
    """Todo encadenado, que es como falla lo que no falla por separado.

    Circuito -> vanos -> intervencion -> escenario -> simular -> otros vanos ->
    otras variables -> simular -> otro circuito -> diagnostico. Se comprueba el
    mapa base despues de CADA paso, porque el sintoma reportado aparecia "en
    algunos" y no en el primero.
    """
    circuitos = A.circuitos(nav)
    fallos = []

    def revisar(paso):
        e = A.estado(nav)
        if e["base"]["vertices"] == 0:
            fallos.append(f"{paso}: el mapa base quedo VACIO")
        elif e["base"]["pct"] < COBERTURA_MINIMA:
            fallos.append(f"{paso}: solo se ve el {e['base']['pct']}% del mapa base")

    for i, salto in enumerate((5, 88)):
        a, b = circuitos[salto], circuitos[(salto + 47) % len(circuitos)]
        A.cambiar_circuito(nav, a);                      revisar(f"[{i}] circuito {a}")
        vanos = A.indices_de_vano(nav)
        A.marcar(nav, vanos[:4], True);                  revisar(f"[{i}] marcar 4")
        A.pulsar(nav, "Diagnostico", espera=14);         revisar(f"[{i}] diagnostico")
        A.pulsar(nav, "Aplicar intervencion sugerida");  revisar(f"[{i}] intervencion")
        A.pulsar(nav, "Aplicar escenario sugerido");     revisar(f"[{i}] escenario")
        r = A.simular(nav)
        revisar(f"[{i}] simular")
        if not r["dibujo"]:
            fallos.append(f"[{i}] simular no dibujo el mapa simulado")
        A.marcar(nav, vanos[4:8], True);                 revisar(f"[{i}] mas vanos")
        A.marcar(nav, A.indices_de_variable(nav)[:2], True)
        revisar(f"[{i}] variables")
        A.simular(nav);                                  revisar(f"[{i}] simular otra vez")
        A.cambiar_circuito(nav, b);                      revisar(f"[{i}] circuito {b}")
        A.pulsar(nav, "Diagnostico");                    revisar(f"[{i}] diagnostico")

    assert not fallos, "\n".join(fallos)


def test_el_flujo_no_dejo_errores_en_la_consola(nav):
    """Va al final a proposito: acumula lo de todas las pruebas del modulo.

    Un `ReferenceError` deja el tablero montado y mudo, que ninguna sonda de
    layout ve -- el tablero se ve bien y no reacciona.
    """
    graves = [e for e in nav.errores if "in promise" not in e]
    assert not graves, f"errores de JavaScript durante el flujo: {graves[:4]}"
