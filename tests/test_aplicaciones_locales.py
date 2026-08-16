"""Contrato de las aplicaciones locales de `aplicaciones/`.

Las seis aplicaciones no comparten codigo por herencia sino por convencion: el
gestor descubre la carpeta desde el directorio de trabajo, busca `requirements.txt`
para reconocerla, y vuelve a lanzar `construir.py` o `app.py` con el interprete del
entorno de esa carpeta. Nada de eso esta declarado en ningun sitio, asi que una
aplicacion nueva a la que le falte una pieza no falla al importarse: falla en la
maquina de quien le da doble clic, con el error del lanzador, que es el peor sitio
posible para enterarse.

Estas pruebas fijan esa convencion sobre las carpetas REALES. No construyen ningun
tablero -- eso cuesta minutos y lee 540 MB --; comprueban que las piezas estan y que
apuntan a donde dicen.

Los botones de cerrar tienen pruebas propias porque en los tres casos son DOS extremos
que viven en archivos distintos y solo funcionan si coinciden:

  - el boton suelto llama a una ruta (`empaquetar`) que atiende otro modulo (`servidor`);
  - la barra del menu lleva horneada la URL del menu, que decide `menu.py`;
  - los puertos del catalogo del menu tienen que ser los del contrato de `/app-local-*`.

Cuando uno de esos pares se separa el sintoma es siempre el mismo y siempre mudo: algo
que parece cerrarse y deja el proceso vivo, o dos instancias de la misma aplicacion en
puertos distintos sin que ninguna sepa de la otra.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
APPS = RAIZ / "aplicaciones"
CUADERNOS = RAIZ / "notebooks" / "base_apps"

# Las piezas sin las cuales el lanzador no llega a ninguna parte, en CUALQUIER
# aplicacion. `preparar.py` no esta: solo lo tiene el simulador, que congela un paquete
# en vez de un HTML.
PIEZAS = (
    "app.py",
    "requirements.txt",
    "README.md",
    "abrir-en-terminal.command",
    "iniciar.bat",
    "instalar-en-terminal.command",
    "instalar.bat",
)

# CriticidadCHEC es de otra especie: no dibuja ningun tablero, no ejecuta ningun
# cuaderno y no tiene dependencias. Gobierna a las demas. Separarlo aqui es lo que
# permite que las pruebas de los visores sigan siendo exigentes en vez de aflojarse
# hasta que el menu tambien pase.
MENU = "00_criticidad_chec"


def _aplicaciones() -> list[Path]:
    return sorted(
        d for d in APPS.iterdir()
        if d.is_dir() and not d.name.startswith((".", "_"))
    )


def _ids(rutas: list[Path]) -> list[str]:
    return [r.name for r in rutas]


TODAS = _aplicaciones()
VISORES = [a for a in TODAS if a.name != MENU]
# Los que empaquetan un HTML estatico. El simulador queda fuera: sirve el cuaderno con
# un kernel vivo y no empaqueta plotly.js ni tiene `panel/`.
ESTATICOS = [a for a in VISORES if a.name != "06_simulador"]


def test_estan_las_seis_aplicaciones():
    """Fija la lista. Sin esto, las pruebas parametrizadas de abajo pasarian
    triunfalmente sobre una carpeta vacia si alguien renombrara `aplicaciones/`."""
    assert _ids(TODAS) == [
        "00_criticidad_chec",
        "01_clima",
        "02_agrupamiento_vanos",
        "03_trayectorias_circuitos",
        "04_trayectorias_vanos",
        "06_simulador",
    ]


@pytest.mark.parametrize("app", VISORES, ids=_ids(VISORES))
def test_cada_visor_trae_su_constructor(app: Path):
    """Solo los visores construyen algo. El menu no tiene `construir.py` a proposito:
    lo que abre son las otras aplicaciones, cada una con el suyo."""
    assert (app / "construir.py").is_file()


def test_el_menu_no_construye_nada():
    """Al reves que la de arriba, y por eso va aparte: si algun dia el menu apareciera
    con un `construir.py`, seria que se le colgo trabajo que no le toca."""
    assert not (APPS / MENU / "construir.py").exists()


@pytest.mark.parametrize("app", TODAS, ids=_ids(TODAS))
@pytest.mark.parametrize("pieza", PIEZAS)
def test_cada_aplicacion_trae_todas_sus_piezas(app: Path, pieza: str):
    assert (app / pieza).is_file(), f"{app.name} no tiene {pieza}"


@pytest.mark.parametrize("app", TODAS, ids=_ids(TODAS))
def test_los_lanzadores_llaman_al_gestor_de_la_carpeta_de_al_lado(app: Path):
    """Los cuatro lanzadores se pisan en el directorio de trabajo primero (`cd` a la
    carpeta del script) y despues llaman al gestor por ruta relativa. Ese `cd` es lo
    que hace que `gestor` encuentre la aplicacion: la deduce del cwd. En macOS
    `Terminal.app` abre un `.command` en la carpeta del usuario, no en la del
    archivo, asi que sin el `cd` el gestor buscaria la aplicacion en `~`."""
    for sh_nombre, bat_nombre, orden in (
            ("abrir-en-terminal.command", "iniciar.bat", "iniciar"),
            ("instalar-en-terminal.command", "instalar.bat", "instalar")):
        sh = (app / sh_nombre).read_text(encoding="utf-8")
        bat = (app / bat_nombre).read_text(encoding="utf-8")
        assert 'cd "$(dirname "$0")"' in sh, f"{app.name}/{sh_nombre} no se situa"
        assert 'cd /d "%~dp0"' in bat, f"{app.name}/{bat_nombre} no se situa"
        assert f"_comun/gestor.py {orden}" in sh, f"{app.name}/{sh_nombre}"
        assert f"_comun\\gestor.py {orden}" in bat, f"{app.name}/{bat_nombre}"


@pytest.mark.parametrize("app", VISORES, ids=_ids(VISORES))
def test_cada_visor_nombra_un_cuaderno_que_existe(app: Path):
    """El nombre del cuaderno se resuelve contra `CUADERNOS_APPS` en tiempo de
    ejecucion, asi que uno renombrado o archivado no rompe nada hasta que alguien
    intenta construir -- y para entonces ya creo el entorno virtual y espero. Aqui
    cuesta un `is_file()`.

    Se busca en TODOS los `.py` de la carpeta y no solo en `construir.py`: los
    cuatro visores estaticos lo declaran ahi, pero el simulador lo declara en
    `preparar.py`, que es quien congela su paquete. Fijar el archivo concreto
    convertiria esa diferencia legitima en un fallo."""
    nombres = {
        m.group(1)
        for py in sorted(app.glob("*.py"))
        for m in re.finditer(r"['\"]([\w.]+\.ipynb)['\"]",
                             py.read_text(encoding="utf-8"))
    }
    assert nombres, f"{app.name} no nombra ningun cuaderno en sus .py"
    # Se cuentan los que RESUELVEN, no los que se nombran. El simulador nombra dos --
    # el cuaderno fuente y la copia parcheada que el mismo escribe -- y esa segunda no
    # vive en `notebooks/` ni tiene por que. Lo que se fija es que haya exactamente
    # una fuente: cero significa que el cuaderno se renombro o se archivo a otro sitio.
    fuentes = {n for n in nombres if (CUADERNOS / n).is_file()}
    assert len(fuentes) == 1, (
        f"{app.name} nombra {sorted(nombres)} y de esos resuelven en {CUADERNOS}: "
        f"{sorted(fuentes) or 'ninguno'}. Una aplicacion sirve exactamente un cuaderno.")


@pytest.mark.parametrize("app", TODAS, ids=_ids(TODAS))
def test_cada_aplicacion_justifica_su_requirements(app: Path):
    """`requirements.txt` de estas aplicaciones no es una lista de paquetes sino la
    justificacion de por que cada entorno pesa lo que pesa. Un archivo sin una sola
    linea de comentario es la senal de que alguien lo copio de otra aplicacion sin
    revisar si esas dependencias son las suyas."""
    lineas = (app / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert any(l.lstrip().startswith("#") for l in lineas), f"{app.name}/requirements.txt"


@pytest.mark.parametrize("app", VISORES, ids=_ids(VISORES))
def test_cada_visor_declara_al_menos_un_paquete(app: Path):
    """El menu queda fuera: no tiene dependencias y su archivo existe solo para que el
    gestor reconozca la carpeta. Un visor sin paquetes, en cambio, no podria ni
    ejecutar su cuaderno."""
    lineas = (app / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert any(l.strip() and not l.lstrip().startswith("#") for l in lineas)


def test_el_menu_no_arrastra_dependencias():
    """Es su rasgo de diseno, no un descuido. El menu lanza a las otras como procesos
    hijos precisamente para no tener que importarlas: hacerlo le costaria la UNION de
    las cinco listas -- torch incluido -- solo para dibujar un menu."""
    lineas = (APPS / MENU / "requirements.txt").read_text(encoding="utf-8").splitlines()
    paquetes = [l for l in lineas if l.strip() and not l.lstrip().startswith("#")]
    assert paquetes == [], f"el menu declara {paquetes}"


def test_plotly_va_clavado_en_los_tableros_que_comparten_su_bundle():
    """Los cuatro visores estaticos empaquetan el plotly.js que trae plotly.py, con
    el hash de su contenido en el nombre. Comparten esa descarga en el cache del
    navegador SOLO si producen bytes identicos, y eso exige la misma version exacta.
    Con `>=`, instalarlos en semanas distintas da cuatro copias de ~4,7 MB."""
    versiones = {}
    for app in ESTATICOS:
        texto = (app / "requirements.txt").read_text(encoding="utf-8")
        clavada = re.search(r"^plotly==([\d.]+)$", texto, re.M)
        assert clavada, f"{app.name} no clava la version de plotly"
        versiones[app.name] = clavada.group(1)
    assert len(set(versiones.values())) == 1, f"versiones de plotly distintas: {versiones}"


def test_el_boton_de_cerrar_llama_a_la_ruta_que_el_servidor_atiende():
    """Los dos extremos viven en archivos distintos y solo coinciden porque
    `empaquetar` importa la constante de `servidor`. La prueba fija esa importacion:
    si alguien escribe la ruta a mano en el HTML, el boton pasa a llamar a una ruta
    que devuelve 404 y el tablero se queda servido con el proceso vivo."""
    sys.path.insert(0, str(APPS / "_comun"))
    try:
        import empaquetar
        import servidor
    finally:
        sys.path.pop(0)

    html = empaquetar._inyectar_boton_cerrar("<html><body>x</body></html>")
    assert f"fetch('{servidor.RUTA_APAGADO}'" in html
    assert "method: 'POST'" in html, (
        "tiene que ser POST: un GET que apaga el servidor lo dispara el prefetch del "
        "propio navegador y el tablero se cerraria solo")
    assert 'id="cerrar-tablero"' in html
    assert "window.close()" in html


def _sin_comentarios(texto: str) -> str:
    """Quita los comentarios `//` de JavaScript y los `<!-- -->` de HTML.

    Lo que estas pruebas afirman es lo que el usuario LEE, y un comentario que explique
    por que ya no existe "Cerrar todo" contiene esas dos palabras: sin este filtro, la
    prueba se dispara contra la explicacion del arreglo en vez de contra el fallo.
    """
    import re

    texto = re.sub(r"<!--.*?-->", "", texto, flags=re.S)
    return "\n".join(l for l in texto.splitlines() if not l.lstrip().startswith("//"))


def _comun(nombre: str):
    sys.path.insert(0, str(APPS / "_comun"))
    try:
        return __import__(nombre)
    finally:
        sys.path.pop(0)


def test_el_menu_gobierna_a_todos_los_visores_y_solo_a_ellos():
    """Una aplicacion nueva que no entre al catalogo existe pero es invisible desde el
    menu, y nadie lo nota hasta que alguien la busca ahi. Al reves, una entrada que
    apunte a una carpeta borrada revienta al pulsar Abrir, no al arrancar."""
    catalogo = _comun("menu").catalogo()
    assert sorted(a.carpeta.name for a in catalogo.values()) == _ids(VISORES)
    for app in catalogo.values():
        assert app.carpeta.is_dir(), f"{app.clave} apunta a {app.carpeta}"


def test_los_puertos_del_menu_son_los_que_fija_el_contrato():
    """Los mismos puertos que `/app-local-*`, y no por estetica: si el menu abriera
    clima en otro puerto, una instancia lanzada a mano y otra lanzada desde el menu
    convivirian sin verse, cada una construyendo y sirviendo por su lado."""
    contrato = (RAIZ / ".claude" / "commands" / "_contrato-apps-locales.md").read_text(
        encoding="utf-8")
    declarados = dict(re.findall(r"\|\s*`([\w_]+)`\s*\|\s*\*\*(\d{4})\*\*\s*\|", contrato))
    assert declarados, "no se pudieron leer los puertos del contrato"
    for app in _comun("menu").catalogo().values():
        assert declarados.get(app.carpeta.name) == str(app.puerto), (
            f"{app.carpeta.name}: el menu usa {app.puerto} y el contrato "
            f"{declarados.get(app.carpeta.name)}")


def test_la_barra_del_menu_quita_el_boton_de_cerrar_suelto():
    """Los dos juntos son una trampa: el suelto apaga el servidor y deja la pestana
    abierta sobre un tablero muerto, que es peor que volver al menu y peor que cerrar.
    Cuando hay menu, manda la barra."""
    servidor = _comun("servidor")
    empaquetar = _comun("empaquetar")
    html = empaquetar._inyectar_boton_cerrar("<html><body>x</body></html>")
    assert 'id="cerrar-tablero"' in html

    con_barra = servidor._con_barra_de_menu(html.encode("utf-8"),
                                            "http://127.0.0.1:8800/").decode("utf-8")
    # UN solo boton: "Volver al menu" hacia lo mismo que "Cerrar" con los procesos --
    # el mismo `POST /apagar` a SU puerto -- y solo se diferenciaba en donde dejaba al
    # usuario. Eso no daba para un segundo boton.
    assert 'id="bm-volver"' not in con_barra
    assert 'id="bm-cerrar"' in con_barra
    # El boton suelto sigue en el documento, pero el guion de la barra lo retira al
    # cargar: quitarlo del HTML exigiria volver a parsear el armazon entero.
    assert "getElementById('cerrar-tablero')" in con_barra
    assert ".remove()" in con_barra
    # La URL del menu sigue viajando literal aunque ya no la navegue nadie: es lo que
    # distingue a un tablero lanzado por CriticidadCHEC de uno abierto por su cuenta, y
    # de eso depende que salga esta barra y no el boton suelto.
    assert "var MENU = 'http://127.0.0.1:8800/';" in con_barra


def test_el_boton_de_la_barra_solo_apaga_su_propio_tablero():
    """Ningun boton de un tablero puede apagar a los demas.

    La barra ofrecia "Cerrar todo", que mandaba un `sendBeacon` al `/apagar-todo` del
    menu: desde el tablero de clima se apagaban los otros cuatro y el menu. Ahora ese
    boton es "Cerrar" y manda un `POST /apagar` a SU puerto, que se lleva su servidor y
    lo que cuelgue de el. El unico apagado general vive en la pagina del menu.
    """
    servidor = _comun("servidor")
    con_barra = _sin_comentarios(servidor._con_barra_de_menu(
        b"<html><body>x</body></html>", "http://127.0.0.1:8800/").decode("utf-8"))
    assert "apagar-todo" not in con_barra, "la barra sigue pudiendo apagarlo todo"
    assert "sendBeacon" not in con_barra
    assert ">Cerrar</button>" in con_barra
    assert "Cerrar todo" not in con_barra
    # Ni el rotulo ni el tooltip pueden prometer lo que ya no hace.
    assert "TODAS" not in con_barra
    # Los dos caminos pasan por la puerta del propio tablero y por ninguna otra.
    assert con_barra.count(f"fetch('{servidor.RUTA_APAGADO}'") == 1


def test_la_barra_falla_si_no_encuentra_donde_ponerse():
    servidor = _comun("servidor")
    with pytest.raises(SystemExit, match="barra del menu"):
        servidor._con_barra_de_menu(b"<html>sin cierre", "http://127.0.0.1:8800/")


class _Trasto:
    """Doble de un widget: guarda como lo construyeron y no hace nada mas."""

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.hijos = args[0] if args else []
        self.disabled = False
        self.value = ""

    def on_click(self, _funcion):
        pass


def _ejecutar_bloque_de_cierre(menu: str) -> dict:
    """Ejecuta el bloque que el simulador inyecta, con widgets de mentira.

    Es la unica manera barata de probar esta rama: la de verdad exige Voila, un kernel
    y PyTorch cargado. Lo que se decide aqui -- que botones existen -- se decide al
    ejecutar el bloque, antes de que nada de eso importe.
    """
    import types

    preparar = _cargar_preparar()
    widgets = types.SimpleNamespace(
        HTML=_Trasto, Output=_Trasto, Button=_Trasto, HBox=_Trasto, Layout=_Trasto)
    espacio = {"widgets": widgets, "_JS_CERRAR": "window.close();"}
    entorno_previo = os.environ.get("MENU_CRITICIDAD")
    if menu:
        os.environ["MENU_CRITICIDAD"] = menu
    else:
        os.environ.pop("MENU_CRITICIDAD", None)
    try:
        exec(compile(preparar._BOTON_CERRAR, "cierre", "exec"), espacio)  # noqa: S102
    finally:
        if entorno_previo is None:
            os.environ.pop("MENU_CRITICIDAD", None)
        else:
            os.environ["MENU_CRITICIDAD"] = entorno_previo
    return espacio


def _cargar_preparar():
    sys.path.insert(0, str(APPS / "_comun"))
    sys.path.insert(0, str(APPS / "06_simulador"))
    try:
        return __import__("preparar")
    finally:
        sys.path.pop(0)
        sys.path.pop(0)


def test_el_simulador_sin_menu_trae_solo_su_boton_de_cerrar():
    espacio = _ejecutar_bloque_de_cierre("")
    botones = [b.kwargs.get("description") for b in espacio["_BOTONES_CIERRE"]]
    assert botones == ["Cerrar"]


def test_el_simulador_lleva_un_solo_boton_venga_de_donde_venga():
    """Lanzado desde el menu tenia dos, y hacian lo MISMO con los procesos.

    El simulador no lo sirve `servidor.py` sino Voila, asi que no recibe la barra
    inyectada: sus botones son widgets. Antes la decision se tomaba dentro del kernel
    leyendo la variable de entorno del menu; ahora no hay nada que decidir.
    """
    for menu in ("http://127.0.0.1:8800/", ""):
        espacio = _ejecutar_bloque_de_cierre(menu)
        botones = [b.kwargs.get("description") for b in espacio["_BOTONES_CIERRE"]]
        assert botones == ["Cerrar"], f"con menu={menu!r} salen {botones}"


def test_el_simulador_no_puede_apagar_a_las_demas_aplicaciones():
    """Su segundo boton mandaba un `sendBeacon` al `/apagar-todo` del menu, asi que
    cerrar el simulador se llevaba por delante los otros cuatro tableros y el menu. El
    apagado general es del menu y de nadie mas; aqui solo se manda `SIGTERM` al pid que
    dejo escrito ESTA aplicacion."""
    codigo = (APPS / "06_simulador" / "preparar.py").read_text(encoding="utf-8")
    assert "apagar-todo" not in codigo, "el simulador sigue pudiendo apagarlo todo"
    assert "sendBeacon" not in codigo
    assert "_JS_CERRAR_TODO" not in codigo

    for menu in ("", "http://127.0.0.1:8800/"):
        espacio = _ejecutar_bloque_de_cierre(menu)
        descripciones = [b.kwargs.get("description") for b in espacio["_BOTONES_CIERRE"]]
        assert "Cerrar todo" not in descripciones


def test_la_barra_del_simulador_lleva_siempre_el_aviso_y_la_salida():
    """`_CERRAR_SALIDA` es un `Output` y no un `HTML` por una razon que se pierde facil:
    el JavaScript de un `HTML` no se ejecuta -- ipywidgets lo mete por `innerHTML` --,
    asi que sin el `Output` ningun boton podria cerrar la pestania."""
    for menu in ("", "http://127.0.0.1:8800/"):
        espacio = _ejecutar_bloque_de_cierre(menu)
        hijos = espacio["_BARRA_CERRAR"].hijos
        assert espacio["_CERRAR_AVISO"] in hijos
        assert espacio["_CERRAR_SALIDA"] in hijos


def test_preparar_se_vigila_a_si_mismo_como_insumo():
    """`preparar.py` ESCRIBE la copia parcheada del cuaderno. Sin el en la lista de
    insumos, cambiar un bloque inyectado -- la barra de cierre, el silenciador -- no
    mueve ninguna otra huella, y la aplicacion seguiria sirviendo la copia vieja sin
    dar ningun error. Es el mismo fallo que se corrigio con `Variables_simular.xlsx`."""
    preparar = _cargar_preparar()
    assert any(p.name == "preparar.py" for p in preparar.INSUMOS_POR_CONTENIDO)


def test_inyectar_el_boton_falla_si_no_encuentra_donde_ponerlo():
    """El fallo tiene que ser ruidoso. Un documento sin `</body>` que se empaquetara
    igual daria un tablero sin boton de cerrar, y eso solo se nota cuando alguien lo
    busca para cerrarlo."""
    sys.path.insert(0, str(APPS / "_comun"))
    try:
        import empaquetar
    finally:
        sys.path.pop(0)
    with pytest.raises(ValueError, match="boton de cerrar"):
        empaquetar._inyectar_boton_cerrar("<html>sin cierre")


# --------------------------------------------------------------------- paleta

# Los cuadernos que emiten CSS propio. El 06 queda fuera: su tablero son widgets y su
# estilo lo pone `vano_widgets.py`, no una hoja embebida.
CUADERNOS_CON_CSS = (
    "01_uiti_vano_clima",
    "02_uiti_vano_kmeans",
    "03_uiti_vano_trayectorias_circuitos",
    "04_uiti_vano_trayectorias_vano",
)


def _css_de_los_cuadernos() -> str:
    import json
    partes = []
    for nombre in CUADERNOS_CON_CSS:
        nb = json.loads((CUADERNOS / f"{nombre}.ipynb").read_text(encoding="utf-8"))
        partes += ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    return "\n".join(partes)


@pytest.mark.parametrize("token", sorted(_comun("paleta").TOKENS))
def test_cada_color_de_la_paleta_sale_de_los_cuadernos(token: str):
    """Los cuadernos son la FUENTE de la paleta; `_comun/paleta.py` solo la copia para
    que las piezas agregadas despues -- el boton de cerrar, la barra del menu, la pagina
    de CriticidadCHEC -- no inventen la suya.

    Esta prueba es la que sostiene esa afirmacion. Sin ella, `paleta.py` seria otra
    copia mas, libre de separarse en silencio: cada pieza se ve bien por separado y el
    desajuste solo canta cuando estan juntas, que es justo cuando ya nadie las revisa.
    """
    paleta = _comun("paleta")
    assert paleta.TOKENS[token] in _css_de_los_cuadernos(), (
        f"{token} = {paleta.TOKENS[token]} no aparece en el CSS de ningun cuaderno")


@pytest.mark.parametrize("pieza", ["boton", "barra", "menu"])
def test_lo_que_se_agrega_encima_no_usa_colores_de_su_cosecha(pieza: str):
    """Las tres piezas que el usuario ve por encima de los tableros. Un azul de
    Material o un verde de GitHub aqui no rompen nada -- por eso se cuelan --, solo
    hacen que el conjunto se vea ensamblado de trozos."""
    import re

    servidor = _comun("servidor")
    piezas = {
        "boton": lambda: _comun("empaquetar")._inyectar_boton_cerrar(
            "<html><body>x</body></html>"),
        "barra": lambda: servidor._con_barra_de_menu(
            b"<html><body>x</body></html>", "http://127.0.0.1:8800/").decode("utf-8"),
        "menu": lambda: _comun("menu_pagina").pagina(),
    }
    texto = piezas[pieza]()
    permitidos = set(_comun("paleta").TOKENS.values())
    usados = set(re.findall(r"#[0-9a-fA-F]{3,6}\b|rgb\([^)]+\)", texto))
    assert not (usados - permitidos), f"colores fuera de la paleta: {sorted(usados - permitidos)}"
    assert not re.findall(r"__[A-Z_]+__", texto), "quedaron marcadores sin resolver"


def test_el_menu_no_sigue_el_tema_del_sistema():
    """Los cinco tableros fijan fondo blanco y no responden a `prefers-color-scheme`.
    Un menu que si lo hiciera se pondria oscuro de noche y mandaria al usuario a un
    tablero blanco de un clic, que es el salto que este trabajo vino a quitar."""
    pagina = _comun("menu_pagina").pagina()
    assert "prefers-color-scheme" not in pagina
    assert "color-scheme" not in pagina
    assert f"background: {_comun('paleta').FONDO}" in pagina


def test_el_menu_no_explica_como_funciona_por_encima_de_la_lista():
    """La portada del menu llevaba dos parrafos describiendo el mecanismo -- un proceso
    y un puerto por tablero, que hace cada boton --. Es documentacion, y su sitio son
    los README: en la pantalla solo empuja hacia abajo lo unico que se viene a hacer,
    que es la lista de aplicaciones."""
    pagina = _comun("menu_pagina").pagina()
    for frase in ("su propio proceso", "los abre, los vigila", "en su propia pestana",
                  "apaga\n     las cinco aplicaciones", "Cada tablero abre"):
        assert frase not in pagina, f"la pagina del menu todavia explica: {frase!r}"
    # Lo que si tiene que quedar: el titulo y el unico boton que apaga todo.
    assert "<h1>CriticidadCHEC</h1>" in pagina
    assert 'id="cerrar-todo"' in pagina


def test_la_pestania_que_espera_a_un_tablero_solo_dice_cargando():
    """Mientras la aplicacion se prepara, la pestania recien abierta contaba la historia
    entera -- "Preparando X", el detalle vivo del avance, y un parrafo sobre entornos y
    minutos --. Ahora dice "Cargando..." y nada mas; el avance con su detalle sigue
    estando en la tarjeta del menu, que es donde se puede leer sin perder de vista el
    resto."""
    guion = _sin_comentarios(_guiones_emitidos()["pagina del menu"])
    assert "Cargando..." in guion
    for frase in ("Preparando ", "Un momento", "No cierres esta", "entorno"):
        assert frase not in guion, f"la pestania de espera todavia dice: {frase!r}"
    # Y el detalle del avance ya no se escribe dentro de esa pestania.
    assert "getElementById('p')" not in guion


def _guiones_emitidos() -> dict[str, str]:
    """El JavaScript de las tres piezas que se agregan encima de los tableros."""
    servidor = _comun("servidor")
    piezas = {
        "boton suelto": _comun("empaquetar")._inyectar_boton_cerrar(
            "<html><body>x</body></html>"),
        "barra del menu": servidor._con_barra_de_menu(
            b"<html><body>x</body></html>", "http://127.0.0.1:8800/").decode("utf-8"),
        "pagina del menu": _comun("menu_pagina").pagina(),
    }
    import re
    return {n: "\n".join(re.findall(r"<script>(.*?)</script>", h, re.S))
            for n, h in piezas.items()}


@pytest.mark.parametrize("pieza", ["boton suelto", "barra del menu", "pagina del menu"])
def test_la_paleta_no_se_cuela_sin_escapar_en_una_cadena_de_javascript(pieza: str):
    """`FUENTE` vale `system-ui, -apple-system, 'Segoe UI', sans-serif` -- con comillas
    SIMPLES. Sustituida dentro de una cadena de JavaScript delimitada por comillas
    simples, la cierra antes de tiempo y el guion entero deja de parsear.

    Paso de verdad al pintar el menu con la paleta, y el sintoma no se parece a un
    error: la pagina se dibuja, el estilo se ve bien y la lista de aplicaciones
    sencillamente nunca se llena. Por eso existe `FUENTE_JS`, y por eso esta prueba
    mira el JS emitido y no el codigo fuente."""
    paleta = _comun("paleta")
    js = _guiones_emitidos()[pieza]
    assert paleta.FUENTE not in js, (
        "la fuente entro sin escapar en el JavaScript: usa __FUENTE_JS__ ahi")


@pytest.mark.parametrize("pieza", ["boton suelto", "barra del menu", "pagina del menu"])
def test_el_javascript_que_se_agrega_encima_parsea(pieza: str):
    """La red de seguridad de la de arriba: comprueba el resultado en vez del sintoma
    concreto, asi que atrapa tambien la proxima forma de romperlo. Se salta donde no
    haya node, porque no es una dependencia del proyecto."""
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("node"):
        pytest.skip("no hay node para validar el JavaScript")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8",
                                     delete=False) as archivo:
        archivo.write(_guiones_emitidos()[pieza])
        ruta = archivo.name
    hecho = subprocess.run(["node", "--check", ruta], capture_output=True, text=True)
    assert hecho.returncode == 0, hecho.stderr[:600]


def test_puerto_libre_pregunta_lo_mismo_que_el_servidor():
    """El sondeo no puede ser mas estricto que el servidor que va detras.

    `_Servidor` pone `allow_reuse_address`, asi que toma sin problema un puerto que
    quedo en TIME_WAIT -- que es exactamente el estado en el que queda el puerto justo
    despues de cerrar el tablero. `puerto_libre` sondeaba SIN esa opcion, asi que
    contestaba "ocupado" a un puerto que el servidor si habria tomado, y se iba a uno
    aleatorio SIN DECIRLO: cerrar el tablero y volver a abrirlo lo mandaba a otra URL,
    y el marcador del usuario dejaba de servir. Medido: `puerto_libre(57212)` devolvia
    57214.
    """
    import socket

    servidor = _comun("servidor")

    # Se fabrica el TIME_WAIT: quien cierra primero la conexion se queda con el.
    escucha = socket.socket()
    escucha.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    escucha.bind(("127.0.0.1", 0))
    puerto = escucha.getsockname()[1]
    escucha.listen(1)
    cliente = socket.create_connection(("127.0.0.1", puerto))
    conexion, _ = escucha.accept()
    conexion.close()
    cliente.close()
    escucha.close()

    crudo = socket.socket()
    try:
        crudo.bind(("127.0.0.1", puerto))
        pytest.skip("este sistema no dejo el puerto en TIME_WAIT; la prueba no aplica")
    except OSError:
        pass
    finally:
        crudo.close()

    assert servidor.puerto_libre(puerto) == puerto


@pytest.mark.parametrize("app", VISORES, ids=_ids(VISORES))
def test_cada_visor_prefiere_el_puerto_que_le_da_el_contrato(app: Path):
    """El puerto preferido tiene que ser el del contrato, y no un 8765 comun a todos.

    Con el 8765 compartido pasaban dos cosas, las dos mudas: abrir DOS tableros por
    doble clic mandaba el segundo a un puerto aleatorio, y un tablero abierto asi no lo
    reconocia CriticidadCHEC -- que lo busca en el puerto del contrato --, con lo que el
    menu levantaba una segunda copia de la misma aplicacion.
    """
    contrato = (RAIZ / ".claude" / "commands" / "_contrato-apps-locales.md").read_text(
        encoding="utf-8")
    declarados = dict(re.findall(r"\|\s*`([\w_]+)`\s*\|\s*\*\*(\d{4})\*\*\s*\|", contrato))
    esperado = declarados[app.name]

    codigo = (app / "app.py").read_text(encoding="utf-8")
    encontrado = re.search(r"^PUERTO\s*=\s*(\d{4})", codigo, re.M)
    assert encontrado, f"{app.name}/app.py no declara PUERTO"
    assert encontrado.group(1) == esperado, (
        f"{app.name} prefiere {encontrado.group(1)} y el contrato dice {esperado}")


# ------------------------------------------------- los visores y sus datos de origen


@pytest.mark.parametrize("app", ESTATICOS, ids=_ids(ESTATICOS))
def test_el_visor_construido_registra_de_que_insumos_salio(app: Path):
    """Sin esto, cambiar los datos no cambia el tablero y nadie se entera.

    Los cuatro visores CONGELAN el resultado del cuaderno en un HTML. El simulador ya
    guardaba la huella de sus insumos y se reconstruia solo; estos no guardaban
    ninguna, y su unica condicion para reconstruir era que faltara `index.html`. O
    sea: se actualizaba `Indicadores_vano_v3.csv`, se abria el tablero, y el tablero
    seguia dibujando los datos viejos **sin dar ningun error** -- que es la forma mas
    cara posible de equivocarse, porque las cifras se ven bien.

    Se salta si el visor no esta construido: `panel/` esta en `.gitignore`, asi que un
    clon recien hecho -- o un runner de CI -- no lo tiene, y ahi no hay nada que
    comprobar todavia. Lo que no puede pasar es que la prueba falle por eso y se acabe
    borrando la unica que vigila esto.
    """
    ruta = app / "panel" / "manifiesto.json"
    if not ruta.exists():
        pytest.skip("este visor no esta construido en esta maquina")
    manifiesto = json.loads(ruta.read_text(encoding="utf-8"))
    insumos = manifiesto.get("insumos")
    assert insumos, f"{app.name}: el manifiesto no registra insumos"
    assert "Indicadores_vano_v3.csv" in insumos, (
        f"{app.name}: no vigila el dataset, que es lo que mas cambia")


@pytest.mark.parametrize("app", ESTATICOS, ids=_ids(ESTATICOS))
def test_un_visor_al_dia_no_se_reconstruye(app: Path, tmp_path: Path):
    """El otro lado del trato: vigilar no puede volverse reconstruir siempre. Un visor
    tarda entre 4 y 8 s en construirse, y hacerlo en cada apertura anularia el motivo
    de que exista el paquete.

    Se arma un manifiesto con las huellas de AHORA en vez de mirar el panel que haya
    en disco. La version anterior hacia lo segundo y era un falso positivo esperando:
    un panel construido ayer queda legitimamente obsoleto en cuanto alguien toca
    `src/` -- que es a diario --, y la prueba lo denunciaba como si la maquinaria de
    huellas estuviera rota. Medido: fallaba en la primera corrida tras cualquier
    cambio en `src/` y pasaba en la segunda, porque otra prueba habia reconstruido
    los paneles por el camino. Un fallo que se arregla solo al repetir es peor que
    ninguno: ensena a repetir.
    """
    construccion = _comun("construccion")
    cuaderno = _cuaderno_de(app)
    (tmp_path / "index.html").write_text("", encoding="utf-8")
    (tmp_path / "manifiesto.json").write_text(
        json.dumps({"insumos": construccion.huellas_actuales(cuaderno)}),
        encoding="utf-8")
    assert construccion.motivo_de_reconstruccion(tmp_path, cuaderno) is None


@pytest.mark.parametrize("app", ESTATICOS, ids=_ids(ESTATICOS))
def test_mover_el_dataset_obliga_a_reconstruir_el_visor(app: Path):
    """Se compara contra un manifiesto con la huella del CSV falseada, que es lo que
    veria la aplicacion despues de que alguien actualice los datos."""
    huellas = _comun("huellas")
    construccion = _comun("construccion")

    actuales = construccion.huellas_actuales(_cuaderno_de(app))
    guardadas = dict(actuales)
    guardadas["Indicadores_vano_v3.csv"] = {"bytes": 1, "mtime_ns": 1}

    motivo = huellas.motivo_de_reconstruccion(guardadas, actuales)
    assert motivo and "Indicadores_vano_v3.csv" in motivo


def _cuaderno_de(app: Path) -> str:
    """El cuaderno que declara `construir.py`, leido sin importarlo: importarlo tira
    del `_comun` de la aplicacion y del cuaderno entero."""
    texto = (app / "construir.py").read_text(encoding="utf-8")
    return re.search(r'^CUADERNO\s*=\s*"([^"]+)"', texto, re.M).group(1)


def test_todo_insumo_que_el_simulador_exige_esta_ademas_vigilado():
    """El invariante que evita que este hueco vuelva a abrirse.

    `_verificar_insumos` lista lo que hace falta para CONSTRUIR el paquete, y las dos
    tuplas de huellas listan lo que se vigila para saber si hay que reconstruirlo. Que
    una lista crezca y la otra no es exactamente como se cuela un tablero que sirve
    datos viejos sin dar ningun error -- ya paso dos veces: con
    `Variables_simular.xlsx` primero, y despues con `Variables_seleccion.xlsx`, que se
    exigia y no se vigilaba aunque alimenta la celda 4, que si viaja congelada.
    """
    import ast

    fuente = (APPS / "06_simulador" / "preparar.py").read_text(encoding="utf-8")
    arbol = ast.parse(fuente)

    def nombres_de(bloque: ast.AST) -> set[str]:
        """Los nombres de archivo que aparecen como literales dentro del bloque."""
        return {n.value for n in ast.walk(bloque)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and "." in n.value and "/" not in n.value and " " not in n.value}

    exigidos, vigilados = set(), set()
    for nodo in arbol.body:
        if isinstance(nodo, ast.FunctionDef) and nodo.name == "_verificar_insumos":
            exigidos = nombres_de(nodo)
        if isinstance(nodo, ast.Assign) and any(
                getattr(t, "id", "").startswith("INSUMOS_") for t in nodo.targets):
            vigilados |= nombres_de(nodo)

    assert exigidos, "no se pudo leer _verificar_insumos"
    # Los shapefiles se nombran sin extension en la tupla, que la compone aparte.
    vigilados |= {f"{n}.{e}" for n in ("MVLINSEC", "GDBCHEC_TRANSFOR", "SWITCHES")
                  for e in ("shp", "dbf")}
    sin_vigilar = {n for n in exigidos if n.endswith((".csv", ".xlsx", ".pt", ".joblib",
                                                      ".json", ".shp"))} - vigilados
    assert not sin_vigilar, (
        f"exigidos para construir pero no vigilados: {sorted(sin_vigilar)}")


# ------------------------------------- el codigo de las librerias es un insumo mas


def test_las_cinco_vigilan_el_codigo_de_las_librerias():
    """El punto ciego mas ancho que tenian, medido: 67 archivos bajo `src/` y CERO
    vigilados.

    Las cinco aplicaciones CONGELAN el resultado de un cuaderno -- los cuatro visores en
    un HTML, el simulador en su paquete -- y ese cuaderno importa
    `chec_local_interpreter` y `chec_impacto`. Cambiar `clases_para`, las capas del mapa
    o la construccion de ventanas no movia ninguna huella, asi que la aplicacion seguia
    sirviendo lo anterior sin dar ningun error. Es el mismo fallo que ya obligo a
    vigilar `empaquetar.py` y `preparar.py`, un nivel mas abajo.

    Cuesta 1,4 ms por arranque, medidos sobre los 67 archivos: nada frente a los 0,06 s
    que tarda un visor en servirse.
    """
    construccion = _comun("construccion")
    huellas_visor = construccion.huellas_actuales("01_uiti_vano_clima.ipynb")

    sys.path.insert(0, str(APPS / "06_simulador"))
    try:
        preparar = __import__("preparar")
    finally:
        sys.path.pop(0)
    huellas_simulador = preparar.huellas_actuales()

    for nombre, huellas in (("los visores", huellas_visor),
                            ("el simulador", huellas_simulador)):
        arboles = {k: v for k, v in huellas.items() if k.endswith("/")}
        assert arboles, f"{nombre} no vigila ningun arbol de codigo"
        assert "src/" in arboles, f"{nombre} no vigila src/: {sorted(arboles)}"
        # Y que de verdad haya mirado dentro, no que la carpeta exista.
        assert arboles["src/"].get("archivos", 0) > 20, (
            f"{nombre} vigila src/ pero solo vio {arboles['src/']} archivos")


def test_vigilar_el_codigo_no_cuesta_mas_que_servir_el_tablero():
    """La comprobacion corre en CADA apertura, antes de decidir si reconstruir. Un
    visor ya construido se sirve en 0,06 s medidos; si comprobar costara mas que eso,
    la defensa saldria mas cara que el fallo del que protege."""
    import time

    huellas = _comun("huellas")
    raiz = RAIZ / "src"
    t0 = time.perf_counter()
    for _ in range(3):
        huellas.huella_de_arbol(raiz)
    promedio = (time.perf_counter() - t0) / 3

    assert promedio < 0.05, f"la huella de src/ tarda {promedio*1000:.0f} ms"

def test_el_simulador_local_no_deja_un_kernel_caliente_en_reposo():
    """El simulador local NO precalienta kernel, y es una decision medida.

    `--preheat_kernel=True` deja un kernel ya ejecutado esperando a la primera
    peticion. Medido A/B en esta maquina, pidiendo la pagina como la pide el menu -- de
    inmediato, en cuanto el puerto contesta --:

        con precalentado : 4,78 s de espera, 1.694 MB tras servir (3 procesos)
        sin precalentado : 4,45 s de espera,   931 MB tras servir (2 procesos)

    La espera NO mejora. El puerto queda atado a los 0,77 s y el kernel precalentado
    tarda bastante mas en estar listo, asi que la primera peticion no lo alcanza y Voila
    levanta uno nuevo igual. Lo unico que quedaba era el kernel de reserva que nadie usa:
    763 MB permanentes en la portatil de una persona a cambio de nada medible.

    En el despliegue de servidor (`.claude/commands/app-simulador-vano.md`) el trato es
    el contrario y por eso ahi sigue encendido: alli el kernel caliente lo aprovechan
    muchas visitas, la memoria es del cluster, y nadie abre la pagina en el mismo
    segundo en que arranca el servicio.

    `--pool_size` no se queda huerfano: sin precalentado no hay reserva que dimensionar.

    Se mira el ARGUMENTO y no el texto del archivo: el comentario que explica por que
    ya no se precalienta nombra las dos banderas, y buscarlas a secas se dispara contra
    la explicacion en vez de contra el fallo.
    """
    codigo = (APPS / "06_simulador" / "app.py").read_text(encoding="utf-8")
    assert '"--preheat_kernel' not in codigo, (
        "el simulador local volvio a precalentar: son 780 MB en reposo")
    assert '"--pool_size' not in codigo, (
        "sin precalentado, `--pool_size` dimensiona una reserva que no existe")
    # Lo que SI tiene que seguir: reciclar el kernel de una pestania cerrada. Sin esto
    # cada recarga deja atras otros 780 MB -- se llegaron a ver siete vivos a la vez.
    assert "--MappingKernelManager.cull_idle_timeout=180" in codigo
    assert "--MappingKernelManager.cull_connected=False" in codigo


def test_el_paquete_del_simulador_comprueba_que_las_bolsas_siguen_al_csv():
    """El unico desajuste de datos que las huellas NO pueden ver.

    `TABLA` sale del CSV y `BAG_INDEX` del cache de bolsas del cuaderno 05. Los dos se
    vigilan y los dos disparan reconstruccion, pero una huella contesta "cambio algun
    insumo?" y no "siguen hablando del mismo mes?". Actualizar el CSV sin volver a correr
    el 05 reconstruye la aplicacion, muestra los eventos nuevos y los puntua con las
    bolsas anteriores -- y nada falla.

    `construir_paquete` es el sitio donde comprobarlo, y el unico: es el momento en que
    las dos mitades estan en la mano a la vez, y corre exactamente cuando el CSV cambia.
    Comprobarlo en cada arranque en cambio costaria cargar las bolsas de 199 MB para
    contestar una pregunta que solo cambia al reconstruir.
    """
    codigo = (APPS / "06_simulador" / "preparar.py").read_text(encoding="utf-8")
    assert "desajuste_bolsas_vs_tabla" in codigo, (
        "el paquete se congela sin comprobar que las bolsas siguen al CSV")
    cuerpo = codigo[codigo.index("def construir_paquete("):]
    cuerpo = cuerpo[: cuerpo.index("\ndef ")]
    assert "desajuste_bolsas_vs_tabla" in cuerpo, (
        "la comprobacion tiene que correr DENTRO de construir_paquete, que es donde "
        "TABLA y BAG_INDEX estan los dos en la mano")
    # Y tiene que ABORTAR, no avisar: un paquete congelado con las dos mitades hablando
    # de meses distintos es exactamente lo que esto viene a impedir.
    assert "SystemExit" in cuerpo
