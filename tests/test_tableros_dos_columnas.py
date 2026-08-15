"""Los cuatro visores en dos columnas: controles al 30% a la izquierda, figuras al 70%.

Los cuatro tableros estaticos (01, 02, 03 y 04) nacieron con el panel de control como una
BARRA HORIZONTAL encima de la figura. Con figuras de 960 a 1.700 px de alto, elegir un
circuito y ver que le hace al mapa son dos gestos en extremos opuestos del scroll -- el
mismo problema que ya se corrigio en el simulador, y con la misma solucion.

## Por que el contrato vive aqui y no en un modulo compartido

Los cuatro cuadernos no importan NADA de `src/`: son autocontenidos a proposito, porque
ademas de alimentar las aplicaciones locales se despliegan como apps de Databricks, donde
el arbol del repositorio no esta. Un `from chec_local_interpreter import ...` los romperia
alli.

Asi que el bloque de CSS viaja COPIADO en los cuatro, y lo que impide que se separen es
esta prueba: exige que las cuatro copias sean identicas byte a byte. Por eso el CSS no
puede nombrar la clase del panel de cada tablero -- `.panel-clima`, `.panel-agrup`,
`.panel-tray`, `.panel-v` --, y usa `[class^="panel-"]`, que es lo que permite que el
mismo texto sirva para los cuatro.

## Las dos propiedades que no son obvias

  * **`min-width: 0` en las dos columnas.** Un hijo de flex trae `min-width: auto`, o sea
    que no puede encogerse por debajo de su contenido. El div de plotly y las casillas del
    panel tienen ancho minimo propio, asi que sin esta linea las columnas se pasan del 30
    y del 70 y la pagina scrollea a lo ancho.
  * **El panel deja de ser una fila.** Los cuatro paneles son `display:flex` con
    `flex-wrap:wrap` pensados para ocupar el ancho entero. Metidos en una columna estrecha
    sin cambiarles la direccion, cada control se queda en su ancho minimo y el conjunto
    hace una escalera de una columna con huecos.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
BASE = RAIZ / "notebooks" / "base_apps"

# El cuaderno, la celda que ensambla el tablero exportado, y el nombre de la variable que
# lleva el panel y la que lleva la figura. El 02 se llama distinto porque exporta SOLO su
# tablero de vanos: el de circuitos es un paso intermedio que solo se lee en el cuaderno.
TABLEROS = [
    ("01_uiti_vano_clima.ipynb", "PANEL_HTML", "FIGURA_HTML"),
    ("02_uiti_vano_kmeans.ipynb", "PANEL_VANO_HTML", "FIGURA_VANO_SOLA"),
    ("03_uiti_vano_trayectorias_circuitos.ipynb", "PANEL_HTML", "FIGURA_HTML"),
    ("04_uiti_vano_trayectorias_vano.ipynb", "PANEL_HTML", "FIGURA_HTML"),
]
CUADERNOS = [t[0] for t in TABLEROS]


def _fuente(nombre: str) -> str:
    """Todo el codigo del cuaderno, en un solo texto."""
    documento = json.loads((BASE / nombre).read_text(encoding="utf-8"))
    return "\n".join("".join(c["source"]) for c in documento["cells"]
                     if c["cell_type"] == "code")


def _css(nombre: str) -> str:
    """El bloque `CSS_DOS_COLUMNAS` del cuaderno, tal cual."""
    fuente = _fuente(nombre)
    bloque = re.search(r"CSS_DOS_COLUMNAS = ('''|\"\"\")(.*?)\1", fuente, re.S)
    assert bloque, f"{nombre} no define `CSS_DOS_COLUMNAS`"
    return bloque.group(2)


def _regla(css: str, selector: str) -> str:
    """El cuerpo de una regla del bloque, para preguntarle por sus propiedades."""
    regla = re.search(rf"{re.escape(selector)}\s*(?:,[^{{]*)?{{([^}}]*)}}", css)
    assert regla, f"el CSS no lleva una regla para `{selector}`"
    return regla.group(1)


# ------------------------------------------------- una sola copia, en cuatro cuadernos


def test_las_cuatro_copias_del_css_son_identicas():
    """Byte a byte. Es lo unico que sustituye al modulo compartido que no pueden importar.

    Si alguna vez hace falta que un tablero se separe, el sitio de decirlo es esta prueba
    -- con el motivo escrito --, no una edicion silenciosa en un solo cuaderno.
    """
    copias = {nombre: _css(nombre) for nombre in CUADERNOS}
    distintas = {n: c for n, c in copias.items() if c != copias[CUADERNOS[0]]}
    assert not distintas, (
        f"estos cuadernos llevan un CSS_DOS_COLUMNAS distinto al del "
        f"{CUADERNOS[0]}: {sorted(distintas)}")


def test_el_css_no_nombra_la_clase_de_ningun_panel():
    """`[class^="panel-"]` y no `.panel-clima`.

    Las cuatro clases son distintas, asi que nombrar una sola haria imposible que las
    cuatro copias fueran iguales -- y el tablero que no se llamara asi se quedaria con su
    panel en fila dentro de una columna del 30%.
    """
    css = _css(CUADERNOS[0])
    nombradas = re.findall(r"\.panel-[a-z]+", css)
    assert not nombradas, f"el CSS compartido nombra clases de un tablero concreto: {nombradas}"


# ------------------------------------------------------------------ las dos columnas


@pytest.mark.parametrize("nombre", CUADERNOS)
def test_los_controles_declaran_su_ancho_con_un_30_por_ciento_por_defecto(nombre: str):
    """En porcentaje -- estos tableros se ven de 1.280 a 1.900 px -- y por variable.

    El bloque va copiado en los cuatro cuadernos y esta misma suite exige que las copias
    sean identicas, asi que el reparto NO puede escribirse aqui: un tablero que quiera
    otro lo declara en su marcado (`style="--ancho-controles: 25%"`). El 30% es el valor
    de respaldo para el que no diga nada.
    """
    cuerpo = _regla(_css(nombre), ".cuerpo-2col > .col-controles")
    assert "var(--ancho-controles, 30%)" in cuerpo, (
        f"{nombre} no toma el ancho de los controles de `--ancho-controles`: "
        f"{cuerpo.strip()!r}")


@pytest.mark.parametrize("nombre", CUADERNOS)
def test_las_figuras_se_quedan_con_lo_que_sobre(nombre: str):
    """`flex: 1 1 0` y no un 70% escrito.

    Un porcentaje fijo en la columna de figuras y otro en la de controles son dos numeros
    que tienen que sumar 100 para siempre; el dia que uno cambie, el otro no se entera y
    queda una franja muerta o un desborde. Que una sea fija y la otra tome el resto lo
    hace imposible por construccion.
    """
    cuerpo = _regla(_css(nombre), ".cuerpo-2col > .col-figuras")
    assert re.search(r"flex:\s*1\s+1\s+0", cuerpo), (
        f"{nombre}: la columna de figuras no toma el resto del ancho: {cuerpo.strip()!r}")
    assert "%" not in cuerpo, (
        f"{nombre}: la columna de figuras declara un ancho propio ({cuerpo.strip()!r}); "
        "eso obliga a mantener dos numeros que suman 100")


@pytest.mark.parametrize("nombre", CUADERNOS)
@pytest.mark.parametrize("selector", [".col-controles", ".col-figuras"])
def test_las_columnas_pueden_encoger_por_debajo_de_su_contenido(nombre: str, selector: str):
    """`min-width: 0`, que es lo que apaga el `min-width: auto` de todo hijo de flex.

    Sin el, el ancho minimo del div de plotly manda sobre el 70% declarado y la pagina
    scrollea a lo ancho.
    """
    cuerpo = _regla(_css(nombre), selector)
    assert re.search(r"min-width:\s*0", cuerpo), (
        f"{selector} de {nombre} no lleva `min-width: 0`; el 30/70 declarado no se cumple")


@pytest.mark.parametrize("nombre", CUADERNOS)
def test_el_panel_deja_de_ser_una_barra_horizontal(nombre: str):
    """Dentro de la columna estrecha, los controles van uno bajo otro."""
    cuerpo = _regla(_css(nombre), '.cuerpo-2col > .col-controles > [class^="panel-"]')
    assert re.search(r"flex-direction:\s*column", cuerpo), (
        f"el panel de {nombre} sigue siendo una fila dentro de una columna del 30%")


# --------------------------------------------------------------------- el ensamblaje


@pytest.mark.parametrize("nombre,panel,figura", TABLEROS)
def test_el_panel_va_en_la_columna_izquierda_y_la_figura_en_la_derecha(
        nombre: str, panel: str, figura: str):
    """Y en ese orden: en un flex el orden del marcado es el orden en pantalla."""
    fuente = _fuente(nombre)
    # El `style` es opcional: lo lleva el tablero que declara un reparto propio.
    apertura = re.search(r'<div class="cuerpo-2col"(?: style="[^"]*")?>', fuente)
    assert apertura, f'{nombre} no envuelve su tablero en `<div class="cuerpo-2col">`'
    izquierda = f'<div class="col-controles">{{{panel}}}'
    # La columna de figuras puede llevar algo ANTES de la figura -- el clima le pone su
    # barra con el boton de encuadre --, asi que se busca la apertura y la figura, no una
    # cadena pegada.
    derecha = re.search(
        rf'<div class="col-figuras">(\{{\w+\}})*\{{{figura}\}}', fuente)
    assert izquierda in fuente, f"{nombre}: la columna izquierda no lleva {panel}"
    assert derecha, f"{nombre}: la columna derecha no lleva {figura}"
    derecha = derecha.group(0)
    # En un flex el orden del marcado ES el orden en pantalla, asi que esto no es estilo.
    assert apertura.start() < fuente.index(izquierda) < fuente.index(derecha), (
        f"{nombre}: las figuras van antes que los controles")


@pytest.mark.parametrize("nombre", CUADERNOS)
def test_ningun_texto_sigue_mandando_al_usuario_hacia_arriba(nombre: str):
    """El 01 rotulaba "Elegir circuito y variable en el panel de arriba".

    Es la clase de resto que ninguna medida de cajas encuentra: la pagina se ve perfecta
    y el subtitulo manda a mirar donde ya no hay nada. Se descubrio en la captura, no en
    las medidas, y por eso queda escrito aqui.
    """
    fuente = _fuente(nombre)
    restos = re.findall(r"panel de (?:arriba|encima|la parte superior)", fuente)
    assert not restos, (
        f"{nombre} sigue diciendole al usuario que el panel esta arriba: {restos}")


@pytest.mark.parametrize("nombre,panel,figura", TABLEROS)
def test_ya_nadie_pega_el_panel_encima_de_la_figura(nombre: str, panel: str, figura: str):
    """La disposicion vieja era literalmente `PANEL + FIGURA`, sin nada en medio.

    Dejarla en pie no daria error: daria dos tableros distintos en el mismo repositorio.
    """
    fuente = _fuente(nombre)
    assert f"{panel} + {figura}" not in fuente, (
        f"{nombre} sigue pegando {panel} encima de {figura}: esa es la disposicion vieja")
