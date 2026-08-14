"""Lo que hace lenta la ventana de analisis en los tableros 03 y 04.

Estas pruebas no miden tiempo -- eso pide un navegador -- sino que fijan las tres
decisiones que salieron de medirlo con Chrome, para que no se deshagan solas en la
proxima edicion del panel:

  1. **Ninguna pasada dibuja dos veces lo mismo.** `aplicar()` corria 140 ms despues
     del manejador del deslizador y volvia a llamar a `dibujarMapa` y a
     `pintarPuntoActivo`, que el manejador acababa de ejecutar con los mismos
     argumentos: 234 ms por paso sin que cambiara un pixel.
  2. **Un `relayout` por pasada.** `dibujarReparto` hacia el suyo y `aplicar()` el
     suyo, con 125 y 116 ms.
  3. **El arrastre pinta por cuadro, no por evento.** El evento `input` se dispara
     en cada paso del arrastre; sin agrupar, seis pasos encargaban seis dibujados.

El porque de que esto importe tanto en el 04 y poco en el 03, medido: una llamada a
Plotly que cambia algo cuesta 130 ms en el 04 y 17 ms en el 03, y la diferencia son
los 111.000 puntos de la nube -- Plotly recalcula la figura ENTERA en cada llamada,
asi que la nube le cobra peaje incluso a las llamadas que no la tocan. Comprobado
por refutacion: vaciar la nube bajo un restyle del mapa de 139 a 32 ms, mientras que
convertir 35 de las 39 trazas WebGL a SVG no movio el piso, y recortar el payload
tampoco. Por eso lo que se persigue aqui es el NUMERO de llamadas.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CUADERNOS = RAIZ / "notebooks" / "base_apps"

# El panel de los dos tableros vive en la misma celda: la que arma el HTML y el
# JavaScript alrededor de la figura.
PANELES = {
    "03": (CUADERNOS / "03_uiti_vano_trayectorias_circuitos.ipynb", 7),
    "04": (CUADERNOS / "04_uiti_vano_trayectorias_vano.ipynb", 7),
}


def _panel(clave: str) -> str:
    ruta, celda = PANELES[clave]
    return "".join(json.loads(ruta.read_text(encoding="utf-8"))["cells"][celda]["source"])


def _cuerpo(fuente: str, nombre: str) -> str:
    """El cuerpo de una funcion de JavaScript, contando llaves.

    Buscar hasta la siguiente `function` fallaba con las funciones anidadas, que
    estos paneles usan mucho.
    """
    inicio = fuente.index(f"function {nombre}(")
    i = fuente.index("{", inicio)
    nivel = 0
    for j in range(i, len(fuente)):
        if fuente[j] == "{":
            nivel += 1
        elif fuente[j] == "}":
            nivel -= 1
            if nivel == 0:
                return fuente[inicio:j + 1]
    raise AssertionError(f"{nombre} no cierra sus llaves")


def _sin_prosa(texto: str) -> str:
    """El codigo sin comentarios. Una prueba que casa contra un comentario no vigila
    nada: el comentario puede decir lo correcto sobre codigo que hace lo contrario."""
    return "\n".join(l for l in texto.splitlines()
                     if not l.lstrip().startswith("//"))


@pytest.mark.parametrize("clave", sorted(PANELES))
def test_el_mapa_no_se_redibuja_con_los_mismos_argumentos(clave: str):
    """`dibujarMapa` tiene que cortar cuando nada de lo que dibuja cambio.

    Medido en el 04: la llamada cuesta 148 ms y se hacia DOS veces por paso de
    ventana -- una desde el manejador del deslizador, para que el mapa siguiera al
    dedo, y otra 140 ms despues desde `aplicar()`, con la ventana, el circuito y la
    seleccion identicos.

    La firma tiene que llevar las tres cosas de las que depende el dibujo: si le
    faltara la seleccion, marcar un vano no repintaria el mapa.
    """
    cuerpo = _sin_prosa(_cuerpo(_panel(clave), "dibujarMapa"))
    assert "FIRMA_MAPA" in cuerpo, (
        "dibujarMapa no recuerda lo que dibujo, asi que no puede saltarse una "
        "repeticion")
    assert re.search(r"if\s*\([^)]*firma\s*===\s*FIRMA_MAPA\s*\)\s*\{\s*return", cuerpo), (
        "dibujarMapa recuerda la firma pero no corta con ella")
    # Y la puerta de escape, que no es un adorno: los redibujados de arranque repiten
    # esta llamada con los mismos argumentos justamente porque el primero se pudo
    # perder mientras MapLibre montaba el subplot. Una firma sin `forzar` los cortaria
    # y dejaria el mapa vacio -- exactamente el fallo que esos reintentos evitan.
    assert re.search(r"function dibujarMapa\([^)]*\bforzar\b", cuerpo), (
        "dibujarMapa no deja forzar el dibujado, asi que la firma se come los "
        "redibujados de arranque de MapLibre")
    assert "!forzar" in cuerpo, "el parametro forzar existe pero no abre la puerta"
    # De que depende el dibujo. El circuito y la ventana estan siempre; la seleccion
    # solo en el 04, que es el que resalta vanos marcados.
    firma = cuerpo[cuerpo.index("var firma"):cuerpo.index("FIRMA_MAPA =") + 40]
    assert "circuito" in firma, "la firma del mapa ignora el circuito"
    assert re.search(r"\bw\b", firma), "la firma del mapa ignora la ventana"
    if clave == "04":
        assert "sel" in firma, "la firma del mapa ignora los vanos marcados"


def test_el_punto_activo_no_se_repinta_en_la_misma_ventana():
    """`pintarPuntoActivo` reescribe `marker.size` de 60 trazas: 127 ms, y corria dos
    veces por paso de ventana. Lo que dibuja depende SOLO de cual es la ventana
    activa, asi que repetirlo con la misma ventana no puede cambiar nada."""
    cuerpo = _sin_prosa(_cuerpo(_panel("04"), "pintarPuntoActivo"))
    assert "VENTANA_PINTADA" in cuerpo, (
        "pintarPuntoActivo no recuerda que ventana pinto")
    assert re.search(r"if\s*\(\s*w\s*===\s*VENTANA_PINTADA\s*\)\s*\{\s*return", cuerpo), (
        "pintarPuntoActivo recuerda la ventana pero no corta con ella")


def test_el_reparto_no_hace_su_propio_relayout():
    """Los rangos de eje y las anotaciones del reparto tienen que viajar en el
    `relayout` de `aplicar()`, no en uno aparte.

    Eran 125 ms y 116 ms medidos, uno detras del otro, cuando juntos cuestan lo que
    uno. `dibujarReparto` devuelve sus cambios de layout y quien la llama los funde.
    """
    cuerpo = _sin_prosa(_cuerpo(_panel("04"), "dibujarReparto"))
    assert "Plotly.relayout" not in cuerpo, (
        "dibujarReparto sigue haciendo su propio relayout en vez de devolver sus "
        "cambios para que aplicar() los funda con los suyos")
    assert re.search(r"return\s+\w+;?\s*\}$", cuerpo.strip()), (
        "dibujarReparto no devuelve sus cambios de layout")


@pytest.mark.parametrize("clave", sorted(PANELES))
def test_el_arrastre_pinta_por_cuadro_y_no_por_evento(clave: str):
    """El deslizador dispara `input` en cada paso del arrastre.

    Sin agrupar, un arrastre de seis ventanas encarga seis dibujados completos y el
    hilo principal se los come en serie: medido, 2.889 ms de CPU en el 04 y 472 ms
    en el 03. `requestAnimationFrame` deja uno solo por cuadro, y el ultimo estado
    es el que gana -- que es justo lo que el usuario esta pidiendo mientras arrastra.
    """
    panel = _panel(clave)
    i = panel.index("addEventListener('input'")
    manejador = _sin_prosa(panel[i:i + 1400])
    assert "requestAnimationFrame" in manejador, (
        f"el deslizador del {clave} dibuja una vez por evento de arrastre")


@pytest.mark.parametrize("clave", sorted(PANELES))
def test_el_mapa_escribe_sus_trazas_en_una_sola_llamada(clave: str):
    """Cada `restyle` que cambia algo cuesta un redibujado completo de la figura, asi
    que dos llamadas que escriben trazas distintas del MISMO mapa cuestan el doble
    que una que las escriba todas. El 03 hacia dos, de 36 y 21 ms."""
    cuerpo = _sin_prosa(_cuerpo(_panel(clave), "dibujarMapa"))
    assert cuerpo.count("Plotly.restyle") == 1, (
        f"dibujarMapa del {clave} reparte sus trazas en "
        f"{cuerpo.count('Plotly.restyle')} llamadas")
