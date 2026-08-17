"""La portada de CriticidadCHEC: botones a la izquierda, logos debajo, diagrama a la derecha.

El menu era una columna centrada de 880 px con las cinco tarjetas y nada mas. Ahora es una
portada: a la izquierda la columna de botones con los logos de CHEC y del LabIA debajo, y a
la derecha un diagrama de bloques que resume que hace la aplicacion.

## Por que los logos van EMBEBIDOS y no enlazados

El menu sirve UNA pagina y nada mas: no tiene ruta para archivos estaticos, asi que un
`<img src="/logos/checlogo.png">` daria 404. Y aunque la tuviera, la aplicacion se abre
desde una carpeta cualquiera del disco del usuario: la unica forma de que los logos viajen
con la pagina pase lo que pase es que viajen DENTRO de ella, como `data:` URI.

## Por que el diagrama es SVG inline y no una imagen

Porque es texto: se lee en el diff, se corrige sin abrir un editor de imagenes, y hereda la
paleta de la marca desde el mismo sitio que el resto de la pagina. Una captura habria que
rehacerla cada vez que cambie un nombre.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
COMUN = RAIZ / "aplicaciones" / "_comun"
LOGOS = RAIZ / "site" / "assets" / "site" / "logos"


def _comun(nombre: str):
    sys.path.insert(0, str(COMUN))
    try:
        return __import__(nombre)
    finally:
        sys.path.pop(0)


def _pagina() -> str:
    return _comun("menu_pagina").pagina()


# ------------------------------------------------------------------- las dos columnas


def test_la_portada_va_en_dos_columnas():
    """Los botones a la izquierda y el diagrama a la derecha."""
    pagina = _pagina()
    assert 'class="portada"' in pagina, "la portada ya no se parte en dos columnas"
    izq = pagina.index('class="col-izq"')
    der = pagina.index('class="col-der"')
    assert izq < der, "la columna del diagrama va antes que la de los botones"
    assert pagina.index('id="lista"') < pagina.index('class="logos"'), (
        "los logos no van DEBAJO de los botones")
    assert pagina.index('class="logos"') < der, (
        "los logos se salieron de la columna izquierda")


def test_la_columna_de_botones_no_se_estira():
    """Ancho fijo: las tarjetas son una lista de cinco, no un lienzo.

    Sin tope, en una pantalla ancha la columna se lleva la mitad y el diagrama -- que es
    lo que hay que leer de un vistazo -- se queda con una franja.
    """
    estilo = _pagina()
    regla = re.search(r"\.portada\s*\{([^}]*)\}", estilo)
    assert regla, "la portada no declara su rejilla"
    assert "grid-template-columns" in regla.group(1), (
        f"la portada no reparte sus dos columnas: {regla.group(1).strip()}")


# --------------------------------------------------------------------------- los logos


def test_los_logos_viajan_dentro_de_la_pagina():
    """`data:` URI y no una ruta: el menu no sirve archivos estaticos.

    Un `<img src="/logos/...">` daria 404, y una ruta del disco depende de desde donde se
    haya abierto la aplicacion.
    """
    pagina = _pagina()
    incrustados = re.findall(r'src="data:image/png;base64,[A-Za-z0-9+/=]{200,}"', pagina)
    assert len(incrustados) == 2, (
        f"tendrian que viajar DOS logos embebidos; hay {len(incrustados)}")
    assert "src=\"/" not in pagina and "src='./" not in pagina, (
        "algun logo se enlaza por ruta; el menu no sirve archivos estaticos")


def test_los_logos_son_los_del_repositorio():
    """No se copian a otra carpeta: se leen de donde ya viven."""
    fuente = (COMUN / "menu_pagina.py").read_text(encoding="utf-8")
    assert "checlogo.png" in fuente and "logo_labIA.png" in fuente, (
        "la pagina no nombra los logos de CHEC y del LabIA")
    assert (LOGOS / "checlogo.png").is_file() and (LOGOS / "logo_labIA.png").is_file(), (
        "los logos que la pagina nombra no estan en el repositorio")


def test_una_pagina_sin_logos_no_revienta():
    """Si un logo falta, la portada sale igual y sin su imagen.

    El menu es lo unico que el usuario tiene para arrancar los tableros: que no se abra
    porque falta un PNG decorativo seria cambiar un adorno por la aplicacion entera.
    """
    fuente = (COMUN / "menu_pagina.py").read_text(encoding="utf-8")
    assert re.search(r"def _logo\(", fuente), "no hay un lector de logos aparte"
    cuerpo = fuente[fuente.index("def _logo("):]
    assert "is_file()" in cuerpo.split("\n\n\n")[0], (
        "el lector de logos no comprueba que el archivo exista")


# ------------------------------------------------------------------------- el diagrama


def test_el_diagrama_es_svg_en_linea():
    """Texto y no imagen: se lee en el diff y hereda la paleta."""
    pagina = _pagina()
    assert "<svg" in pagina, "la portada no lleva diagrama"
    assert "viewBox" in pagina, (
        "el diagrama no declara `viewBox`; sin el no escala con su columna")


def test_el_diagrama_explica_el_simulador_con_su_vocabulario_real():
    """El diagrama dejo de listar los cinco tableros para explicar el simulador.

    Aqui se fijaban ademas "Modelo MIL", "Sensibilidad min-max" y "no es SHAP". Esa
    exigencia se cayo a proposito: las tres eran el diagrama explicando la TECNICA -- que
    arquitectura tiene el modelo, que algoritmo corre el estudio, con cual no confundirlo
    -- a un lector que viene a saber que hace el tablero. Ahora los tres bloques lo dicen
    en castellano llano y su contrato vive en `test_menu_diagrama_y_titulo.py`.

    Lo que SI sigue siendo contrato es el vocabulario de la INTERFAZ: `Diagnostico`,
    `Intervencion`, `Escenario` y `Simular` son botones que existen, no invenciones de la
    portada. Un diagrama que renombre lo que el usuario va a ver es peor que no tenerlo.
    """
    pagina = _pagina()
    svg = pagina[pagina.index("<svg"):pagina.index("</svg>")]
    for pieza in ("Intervencion", "Escenario", "¿Qué pasa si…?", "Simular"):
        assert pieza in svg, f"el diagrama no nombra {pieza!r}"


def _sin_tildes(texto: str) -> str:
    """Para comparar rotulos con nombres de botones sin que una tilde cuente como otro nombre."""
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def test_los_botones_que_el_diagrama_nombra_existen_de_verdad():
    """Si el tablero renombra un boton, la portada tiene que enterarse.

    La comparacion PLIEGA las tildes. El rotulo del diagrama dice "Diagnóstico" y el
    boton del tablero `Diagnostico`: quien lee el diagrama encuentra el boton igual, asi
    que exigir los mismos bytes convertiria una diferencia ortografica en un fallo de
    contrato -- y empujaria a "arreglarlo" cambiando un texto que el usuario escribio.
    """
    tablero = (RAIZ / "src" / "chec_tableros" / "simulador" / "tablero.py").read_text(
        encoding="utf-8")
    svg = _sin_tildes(_pagina())
    for boton in ("Diagnostico", "Simular"):
        assert f"description='{boton}'" in tablero, (
            f"el simulador ya no tiene un boton {boton!r}; la portada lo sigue nombrando")
        assert boton in svg, f"la portada dejo de nombrar el boton {boton!r}"


def test_el_diagrama_usa_la_paleta_y_no_colores_de_su_cosecha():
    """Un azul de plantilla aqui no rompe nada -- por eso se cuela -- y deja la portada
    ensamblada de trozos."""
    pagina = _pagina()
    svg = pagina[pagina.index("<svg"):pagina.index("</svg>")]
    usados = set(re.findall(r"#[0-9a-fA-F]{6}|rgb\(\d+,\s*\d+,\s*\d+\)", svg))
    permitidos = set(_comun("paleta").TOKENS.values()) | {"#fff", "#ffffff"}
    assert not (usados - permitidos), (
        f"el diagrama usa colores fuera de la paleta: {sorted(usados - permitidos)}")
