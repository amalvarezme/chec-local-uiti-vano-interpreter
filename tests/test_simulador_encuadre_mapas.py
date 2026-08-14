"""Por que los mapas del simulador "no se muestran" en algunos circuitos.

El sintoma reportado -- cambio de circuito y el mapa base o el simulado no
aparecen -- no es un mapa vacio. Medido conduciendo el tablero en Chrome: las
trazas llevan sus 932 a 9.761 vertices, el lienzo pinta, y aun asi solo el 4,2%
de lo dibujado cae DENTRO del recuadro que el mapa muestra.

La causa esta escrita en el propio cuaderno: el zoom sale SOLO del alto del
subplot, porque con `autosize` el ancho lo decide el navegador y el cuaderno no
lo conoce. Un circuito cuya caja es mas ancha que alta -- despues de Mercator --
se sale por los lados sin que nada avise, y el mapa se lee como que no fue al
circuito que se pidio.

Cuanto pesa, contado sobre los 208 circuitos con geometria y el subplot de
566 px de alto que la figura tiene hoy:

    ancho del mapa   ventana        circuitos que se salen   el peor pide
        281 px        ~ 700 px          192 de 208             5,41x
        566 px        ~1.345 px          94 de 208             2,69x
        700 px        ~1.650 px          57 de 208             2,17x
      1.020 px        ~2.370 px          21 de 208             1,49x

O sea que ni en una pantalla de 2.370 px el problema desaparece. La correccion
es encuadrar tambien por el ancho, tomando como ancho el ALTO: es el suelo que
garantiza que nada se sale mientras el panel sea al menos cuadrado, y solo puede
alejar el zoom, nunca acercarlo.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CUADERNO = (RAIZ / "notebooks" / "base_apps" /
            "06_uiti_vano_explicabilidad_simulador.ipynb")
GEO_EMPAQUETADA = RAIZ / "aplicaciones" / "06_simulador" / "paquete" / "geo.json"

TESELA_PX = 512
# El alto del subplot de mapa: `height` de la figura por el alto de su dominio.
# Medido en el navegador sobre la figura construida.
ALTO_MAPA_PX = 566.0


def _fuente() -> str:
    nb = json.loads(CUADERNO.read_text(encoding="utf-8"))
    return "\n".join("".join(c["source"]) for c in nb["cells"]
                     if c["cell_type"] == "code")


def _mercator_y(lat: float) -> float:
    s = math.sin(math.radians(lat))
    return 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)


def test_el_cuaderno_encuadra_por_las_dos_dimensiones():
    """Los cuatro sitios que encuadran tienen que pasar ancho Y alto.

    Pasar solo el alto es exactamente el defecto: `centro_y_zoom` toma la
    restriccion que se queda sin sitio primero, y con una sola conocida no hay
    nada que la longitud pueda hacer valer.
    """
    fuente = _fuente()
    llamadas = [m.start() for m in re.finditer(r"centro_y_zoom\(", fuente)]
    assert llamadas, "el cuaderno ya no encuadra con centro_y_zoom"
    for inicio in llamadas:
        trozo = fuente[inicio:inicio + 320]
        assert "alto_px=" in trozo, "una llamada a centro_y_zoom no pasa el alto"
        assert "ancho_px=" in trozo, (
            "una llamada a centro_y_zoom no pasa el ancho: el circuito se sale "
            "por los lados y el mapa se lee como que no cambio de circuito")


def test_el_ancho_que_se_asume_es_un_suelo_declarado():
    """No un numero suelto: tiene que decir de donde sale y que garantiza."""
    fuente = _fuente()
    assert "_ancho_del_mapa_px" in fuente, (
        "el ancho asumido no tiene nombre propio, asi que no se puede razonar "
        "sobre el ni cambiarlo en un solo sitio")


@pytest.mark.skipif(not GEO_EMPAQUETADA.is_file(),
                    reason="el paquete del simulador no esta construido")
def test_ningun_circuito_se_sale_del_mapa_con_el_encuadre_nuevo():
    """La prueba que habria cazado esto: los 208 circuitos, uno por uno.

    Se reproduce la aritmetica del encuadre y se comprueba que la caja del
    circuito cabe dentro del recuadro que el mapa muestra. Con el encuadre viejo
    -- solo el alto -- 94 de los 208 fallaban en un panel cuadrado.
    """
    geo = json.loads(GEO_EMPAQUETADA.read_text(encoding="utf-8"))["geo"]
    ancho_px = alto_px = ALTO_MAPA_PX          # el suelo: panel al menos cuadrado
    margen = 0.9

    se_salen = []
    for circuito, info in geo.items():
        bounds = info.get("bounds")
        if not bounds or len(bounds) != 4:
            continue
        lat_min, lat_max, lon_min, lon_max = (float(v) for v in bounds)
        fx = max(abs(lon_max - lon_min) / 360.0, 1e-12)
        fy = max(abs(_mercator_y(lat_min) - _mercator_y(lat_max)), 1e-12)
        # El zoom lo fija la dimension que se queda sin sitio primero.
        zoom = min(ancho_px * margen / (TESELA_PX * fx),
                   alto_px * margen / (TESELA_PX * fy))
        mundo = TESELA_PX * zoom
        if fx * mundo > ancho_px + 0.5 or fy * mundo > alto_px + 0.5:
            se_salen.append(circuito)

    assert not se_salen, (
        f"{len(se_salen)} circuitos siguen sin caber en su mapa: "
        f"{se_salen[:6]}")


@pytest.mark.skipif(not GEO_EMPAQUETADA.is_file(),
                    reason="el paquete del simulador no esta construido")
def test_encuadrar_solo_por_el_alto_si_dejaba_circuitos_fuera():
    """La contraprueba, para que la de arriba no pase por casualidad.

    Si esta empieza a fallar es que los datos cambiaron y ya no hay circuitos
    anchos, no que el encuadre mejorara: la de arriba dejaria de probar nada y
    hay que revisar las dos juntas.
    """
    geo = json.loads(GEO_EMPAQUETADA.read_text(encoding="utf-8"))["geo"]
    margen = 0.9
    fuera = 0
    for info in geo.values():
        bounds = info.get("bounds")
        if not bounds or len(bounds) != 4:
            continue
        lat_min, lat_max, lon_min, lon_max = (float(v) for v in bounds)
        fx = max(abs(lon_max - lon_min) / 360.0, 1e-12)
        fy = max(abs(_mercator_y(lat_min) - _mercator_y(lat_max)), 1e-12)
        zoom_solo_alto = ALTO_MAPA_PX * margen / (TESELA_PX * fy)
        if fx * TESELA_PX * zoom_solo_alto > ALTO_MAPA_PX:
            fuera += 1
    assert fuera > 50, (
        f"solo {fuera} circuitos se salian con el encuadre viejo; la prueba de "
        "arriba ya no demuestra nada")
