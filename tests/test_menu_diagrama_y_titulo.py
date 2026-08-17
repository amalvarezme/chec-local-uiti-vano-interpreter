"""El menu: fuentes un punto mas chicas, titulo en el panel, y un diagrama que se ve.

Cinco cambios pedidos y uno que salio al medirlos:

1. Todas las fuentes del menu bajan un punto.
2. El diagrama cambia tres bloques de texto por frases en castellano llano.
3. Se va la seccion 6 -- las cuatro lecturas -- y el pie que la remataba.
4. La columna izquierda crece un 25%.
5. "Cerrar todo" y el titulo del panel doblan su tamanio; el titulo ademas se centra en
   esa columna y pasa a decir "IA + Criticidad CHEC".

## El defecto que aparecio al ir a cambiar los tamanios (el punto 6)

La hoja de estilos DEL SVG nunca se aplico. `_diagrama` fue un f-string y sus llaves iban
escapadas (`{{ ... }}`); al quitarle el prefijo `f` -- porque chocaba con `.format` -- las
llaves dobles se quedaron, y `Template.substitute` no las toca. Lo que se servia era:

    .db {{ font: 11.5px ...; fill: #2b2b2b; }}

o sea un bloque cuyo contenido es OTRO bloque. El navegador lo parsea sin quejarse y se
queda con seis reglas VACIAS. Medido en Chrome sobre la pagina servida:

    .dn -> font-size 15px, fill rgb(0,0,0)        (declarado: 10px, $TENUE)
    path.fl -> stroke none, marker-end none        (declarado: $BORDE_FUERTE, flecha)

Consecuencias, las dos invisibles en el codigo: el texto del diagrama se dibujaba al 15px
que hereda del `body` -- por eso se veia apretado dentro de cajas calculadas para 10-12,5
-- y las flechas NO EXISTIAN. Un `path` sin `stroke` y con el `fill` negro por defecto no
pinta nada cuando es una linea. Solo sobrevivian las tres del canal, que llevan su estilo
en linea.

Por eso las pruebas de aqui miran la hoja de estilos y no solo el texto: un diagrama puede
estar entero en el fuente y no verse.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
COMUN = RAIZ / "aplicaciones" / "_comun"


def _comun(nombre: str):
    sys.path.insert(0, str(COMUN))
    try:
        return __import__(nombre)
    finally:
        sys.path.pop(0)


def _pagina() -> str:
    return _comun("menu_pagina").pagina()


def _svg() -> str:
    pagina = _pagina()
    return pagina[pagina.index("<svg"):pagina.index("</svg>")]


# ------------------------------------------------- la hoja del diagrama, que si se aplica


def test_la_hoja_del_diagrama_no_lleva_llaves_dobles():
    """`{{` en el CSS servido es un bloque dentro de otro: el navegador lo vacia.

    No es una diferencia de estilo. Medido en Chrome, las seis reglas del SVG se
    parseaban y quedaban SIN declaraciones: el texto salia a 15px negro y las flechas
    no se dibujaban.
    """
    svg = _svg()
    hoja = svg[svg.index("<style>"):svg.index("</style>")]
    assert "{{" not in hoja and "}}" not in hoja, (
        "la hoja del diagrama sigue con las llaves escapadas del f-string que ya no es; "
        "el navegador se queda con reglas vacias")


def test_las_flechas_del_diagrama_declaran_su_trazo():
    """Una flecha es un `path` sin area: sin `stroke` no pinta nada."""
    svg = _svg()
    hoja = svg[svg.index("<style>"):svg.index("</style>")]
    regla = re.search(r"\.fl\s*\{([^}]*)\}", hoja)
    assert regla, "no hay regla `.fl` para las flechas"
    assert "stroke" in regla.group(1) and "marker-end" in regla.group(1), (
        f"la flecha no declara trazo ni punta: {regla.group(1).strip()}")
    assert svg.count('class="fl"') >= 4, "el diagrama se quedo sin flechas"


def test_ningun_texto_del_diagrama_queda_en_gris_sobre_un_fondo_saturado():
    """`.dn` es $TENUE, pensado para leerse sobre blanco o sobre el panel claro.

    Sobre las dos cajas de fondo saturado -- $ACENTO y $ACENTO_CLARO -- da 1,9:1 y 2,6:1.
    Mientras la hoja estuvo inerte esto no se notaba: todo salia negro. Al arreglarla,
    esos subtitulos eran lo unico que empeoraba.
    """
    svg = _svg()
    for relleno in ("$ACENTO_CLARO", _comun("paleta").ACENTO_CLARO,
                    _comun("paleta").ACENTO):
        for hueco in re.finditer(re.escape(f'fill="{relleno}"'), svg):
            # Del `rect` hasta el siguiente `<rect` o `<path`: los textos de esa caja.
            resto = svg[hueco.end():]
            corte = min((i for i in (resto.find("<rect"), resto.find("<path"))
                         if i >= 0), default=len(resto))
            for texto in re.finditer(r'<text[^>]*class="dn"[^>]*>', resto[:corte]):
                assert "style=\"fill:" in texto.group(0), (
                    f"un `.dn` gris cae sobre un fondo saturado: {texto.group(0)}")


def test_no_quedan_clases_declaradas_que_nadie_use():
    """`.db` y `.fp` sobreviven a los recortes sin que ningun elemento las lleve.

    Una regla muerta en una hoja que ademas estuvo inerte es justo lo que no se nota:
    nadie la ve fallar porque nadie la usa.
    """
    svg = _svg()
    hoja = svg[svg.index("<style>"):svg.index("</style>")]
    for clase in re.findall(r"\.(\w+)\s*\{", hoja):
        assert f'class="{clase}"' in svg, (
            f"la hoja del diagrama declara `.{clase}` y ningun elemento la usa")


# ------------------------------------------------------------ las fuentes, un punto menos


def test_las_fuentes_del_panel_izquierdo_bajan_dos_puntos():
    """Solo las del panel IZQUIERDO. Las tres que no bajan tienen su motivo cada una.

    Se comprueban los valores de LLEGADA y no una resta: el tamanio anterior ya no esta
    en ninguna parte, asi que una prueba que restara tendria que llevar escrita la tabla
    vieja y se quedaria desfasada al siguiente ajuste.
    """
    pagina = _pagina()
    hoja = pagina[pagina.index("<style>"):pagina.index("</style>")]
    esperado = {
        ".portada h1": "font-size: 44px",       # 48 -> 46 -> 44
        ".tarjeta": "font-size: 40px",          # 44 -> 42 -> 40
        ".desc": "font-size: 31px",             # 35 -> 33 -> 31
        ".aviso": "font-size: 7px",             # 11 -> 9 -> 7
        ".tarjeta button": "font-size: 34px",   # 38 -> 36 -> 34
    }
    for selector, declaracion in esperado.items():
        regla = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", hoja)
        assert regla, f"no existe la regla `{selector}`"
        assert declaracion in regla.group(1), (
            f"`{selector}` no baja a `{declaracion}`: {regla.group(1).strip()}")


def test_lo_que_no_esta_en_el_panel_izquierdo_no_se_encoge_con_el():
    """Tres tamanios se quedan donde estaban, y ninguno por descuido.

      * `body` y `button` son la base de la PAGINA, no del panel. Moverlas arrastraria
        cosas que nadie pidio, empezando por el boton de la cabecera.
      * `h1` a secas es la pantalla de despedida, que ni siquiera esta en la portada.
      * "Elaborado por" SALE del panel izquierdo en este mismo cambio: se va debajo del
        diagrama. No le toca el -2 del panel que abandona ni el +1 del que la recibe,
        que es solo para el SVG.
    """
    pagina = _pagina()
    hoja = pagina[pagina.index("<style>"):pagina.index("</style>")]
    for selector, declaracion in (("body", "font: 14px/1.55"),
                                  (r"\bh1", "font-size: 24px"),
                                  (r"\bbutton", "font-size: 12px"),
                                  (r"\.logos \.firma span", "font-size: 25px")):
        regla = re.search(selector + r"\s*\{([^}]*)\}", hoja)
        assert regla, f"no existe la regla `{selector}`"
        assert declaracion in regla.group(1), (
            f"`{selector}` se movio y no tenia por que: {regla.group(1).strip()}")


def test_las_fuentes_del_diagrama_suben_un_punto():
    """El SVG va al reves que el panel izquierdo: +1 donde el otro lleva -2.

    No es una incoherencia. Son dos columnas con trabajos distintos: la izquierda es una
    lista de cinco cosas que se pulsan y ya venia sobredimensionada al triple; la derecha
    es un texto que hay que leer entero, y ademas se escala a lo ancho de su columna.
    """
    svg = _svg()
    hoja = svg[svg.index("<style>"):svg.index("</style>")]
    for clase, tamanio in ((".dt", "12.5px"), (".dn", "10px"), (".dh", "10.5px")):
        regla = re.search(re.escape(clase) + r"\s*\{([^}]*)\}", hoja)
        assert regla, f"no existe la regla `{clase}` del diagrama"
        assert tamanio in regla.group(1), (
            f"`{clase}` no sube a {tamanio}: {regla.group(1).strip()}")


# --------------------------------------------------------------- los textos del diagrama


def test_el_bloque_del_modelo_dice_que_es_en_castellano_llano():
    """"bolsa", "FiLM" y "compuertas por arista" son vocabulario del que entrena el modelo.

    La portada la abre quien va a usar el tablero, no quien lo entreno: describe QUE hace
    el modelo, no como esta armado por dentro.
    """
    svg = _svg()
    for pieza in ("Modelo de IA predictiva restringida por la física",
                  "para estudiar las posibles causas de los fallos a nivel vano"):
        assert pieza in svg, f"el bloque del modelo no dice {pieza!r}"
    for jerga in ("Modelo MIL congelado", "la bolsa es el par vano", "FiLM",
                  "compuertas por arista"):
        assert jerga not in svg, f"el diagrama sigue con la jerga del entrenamiento: {jerga!r}"


def test_los_dos_estudios_se_nombran_por_lo_que_sirven():
    """No por su tecnica: "min-max", "barrido", "no es SHAP" contestaban una pregunta que
    la portada no plantea."""
    svg = _svg()
    for pieza in ("Sensibilidad de las variables", "para disminuir el impacto en UITI",
                  "Diagnóstico semi-automático", "de los vanos más críticos"):
        assert pieza in svg, f"el diagrama no dice {pieza!r}"
    for viejo in ("min-max", "SHAP", "barre cada variable", "completa con los de mayor UITI"):
        assert viejo not in svg, f"el diagrama sigue explicando la tecnica: {viejo!r}"


def test_se_va_la_seccion_de_las_cuatro_lecturas_y_su_pie():
    """El diagrama acaba en la pregunta.

    Las cuatro lecturas eran el diagrama contando lo que se ve al abrir el tablero, que
    es justo lo que el tablero ya muestra. Y el pie era una moraleja.
    """
    svg = _svg()
    for pieza in ("LAS CUATRO LECTURAS", "Mapa simulado", "UITI medido contra simulado",
                  "Grafo de relaciones", "Costo del plan",
                  "unirlos es tu decision"):
        assert pieza not in svg, f"el diagrama sigue llevando {pieza!r}"
    assert "LA PREGUNTA" in svg, "se fue tambien la pregunta, que es donde acaba el camino"


def test_el_lienzo_se_encoge_con_lo_que_se_quito():
    """Un `viewBox` que siga contando 792 de alto deja un tercio de aire en blanco.

    Y no es aire inocente: el SVG se escala a lo ancho de su columna, asi que el alto de
    mas encoge el dibujo entero para caber en una pantalla.
    """
    svg = _svg()
    caja = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
    assert caja, "el diagrama no declara `viewBox`"
    alto = int(caja.group(2))
    assert alto < 600, f"el lienzo sigue alto para lo que dibuja: {alto}"
    ultimo = max(int(y) + int(h) for y, h in
                 re.findall(r'<rect [^>]*y="(\d+)"[^>]*height="(\d+)"', svg))
    assert ultimo <= alto <= ultimo + 30, (
        f"el lienzo ({alto}) no ajusta al ultimo bloque ({ultimo})")


# ------------------------------------------------------- la columna, el boton y el titulo


def test_la_columna_izquierda_crece_un_cuarto():
    """760 -> 950 px."""
    pagina = _pagina()
    regla = re.search(r"\.portada\s*\{([^}]*)\}", pagina)
    assert regla, "la portada no declara su rejilla"
    assert "950px" in regla.group(1), (
        f"la columna de botones no crece un 25%: {regla.group(1).strip()}")


def test_el_punto_de_apilado_sube_con_la_columna():
    """Una columna de 950 px dentro de un umbral de 1.240 deja al diagrama con 260.

    El umbral no es decorativo: dice a partir de que ancho las dos columnas caben. Y se
    CALCULA, no se estima -- el ancho al que el SVG sale a escala 1:1 es la suma de los
    rellenos, la columna, el hueco y el `viewBox` --. Con 1.480, que era una estimacion,
    a 1.500 px de ventana el diagrama salia medido al 0,92 y su letra de 9 a 8,3.
    """
    pagina = _pagina()
    izq = int(re.search(r"grid-template-columns: (\d+)px", pagina).group(1))
    ancho_vb = int(re.search(r'viewBox="0 0 (\d+) ', pagina).group(1))
    relleno = int(re.search(r"body \{[^}]*padding: (\d+)px", pagina).group(1)) * 2
    relleno += int(re.search(r"\.envoltura \{[^}]*padding: \d+px (\d+)px", pagina).group(1)) * 2
    hueco = int(re.search(r"\.portada \{[^}]*gap: (\d+)px", pagina, re.S).group(1))
    umbral = re.search(r"@media \(max-width: (\d+)px\)", pagina)
    assert umbral, "la portada no declara su punto de apilado"
    assert int(umbral.group(1)) >= relleno + izq + hueco + ancho_vb, (
        f"el umbral de apilado ({umbral.group(1)}px) deja al diagrama por debajo de su "
        f"tamanio: hacen falta {relleno + izq + hueco + ancho_vb}px")


def test_cerrar_todo_dobla_su_tamanio():
    """El doble del boton base, que acaba de bajar a 12px."""
    pagina = _pagina()
    regla = re.search(r"#cerrar-todo\s*\{([^}]*)\}", pagina)
    assert regla, "`Cerrar todo` no tiene regla propia"
    assert "font-size: 24px" in regla.group(1), (
        f"el texto de `Cerrar todo` no dobla: {regla.group(1).strip()}")
    assert "padding: 12px 24px" in regla.group(1), (
        f"la caja de `Cerrar todo` no dobla con su texto: {regla.group(1).strip()}")


def test_cada_columna_lleva_su_titulo_centrado():
    """Dos titulos, uno por columna, y del MISMO tamanio.

    Del mismo tamanio no por simetria: son los dos encabezados de la portada y estan uno
    al lado del otro. Con tamanios distintos, el mas grande se lee como titulo de la
    pagina y el otro como subtitulo suyo, que es justo lo que no son.
    """
    pagina = _pagina()
    assert "<h1>IA + Criticidad CHEC</h1>" in pagina, (
        "el titulo de la izquierda no dice `IA + Criticidad CHEC`")
    assert "<h1>¿Cómo funciona el simulador?</h1>" in pagina, (
        "la columna del diagrama no tiene titulo")
    izq, der = pagina.index('class="col-izq"'), pagina.index('class="col-der"')
    assert izq < pagina.index("<h1>") < pagina.index('id="lista"'), (
        "el titulo de la izquierda no encabeza su columna")
    assert der < pagina.index("¿Cómo funciona") < pagina.index("<svg"), (
        "el titulo de la derecha no va dentro de su columna y encima del diagrama")
    # UNA regla para los dos. Escritos aparte se separan al primer ajuste de uno solo.
    regla = re.search(r"\.portada h1\s*\{([^}]*)\}", pagina)
    assert regla, "los dos titulos de la portada no comparten regla"
    assert "text-align: center" in regla.group(1), (
        f"los titulos no se centran en su columna: {regla.group(1).strip()}")


def test_la_firma_del_labia_se_va_debajo_del_diagrama():
    """El logo de CHEC se queda a la izquierda; la firma cruza a la derecha.

    Son dos cosas distintas y ahora se ve: la marca del producto encabeza la columna de
    lo que se abre, y quien lo hizo firma al pie de lo que explica como funciona.
    """
    pagina = _pagina()
    der = pagina.index('class="col-der"')
    assert pagina.index('class="marca"') < der, (
        "el logo de CHEC se fue de la columna izquierda")
    assert pagina.index('class="firma"') > pagina.index("</svg>"), (
        "la firma del LabIA no esta debajo del diagrama")
    assert "Elaborado por" in pagina[pagina.index("</svg>"):], (
        "el rotulo `Elaborado por` no viajo con su logo")


def test_el_logo_del_labia_dobla():
    """78 -> 156 px, y solo el logo: el rotulo se queda de rotulo."""
    pagina = _pagina()
    regla = re.search(r"\.logos \.firma img\s*\{([^}]*)\}", pagina)
    assert regla, "el logo de la firma no tiene regla propia"
    assert "height: 156px" in regla.group(1), (
        f"el logo del LabIA no dobla: {regla.group(1).strip()}")


def test_la_firma_no_arrastra_la_separacion_que_ya_no_necesita():
    """`margin-top: 30px` existia para despegarla del logo de CHEC, que tenia encima.

    Debajo del diagrama no tiene nada encima dentro de su caja, asi que ese margen se
    suma al `padding-top` del bloque y abre un hueco que nadie pidio. Se ata al hermano
    que lo justificaba en vez de dejarlo suelto.
    """
    pagina = _pagina()
    # Lo que sobra es el MARGEN, no el selector: `.logos .firma` sigue haciendo falta para
    # la caja flexible que alinea el rotulo con el logo, y eso vale en las dos columnas.
    suelta = re.search(r"^\.logos \.firma \{([^}]*)\}", pagina, re.M)
    assert suelta, "la firma perdio la caja que alinea su rotulo con su logo"
    assert "margin-top" not in suelta.group(1), (
        f"la separacion sigue suelta y se aplica donde no hay logo encima: "
        f"{suelta.group(1).strip()}")
    assert re.search(r"\.marca \+ \.firma\s*\{[^}]*margin-top", pagina), (
        "nadie separa la firma del logo de CHEC cuando si van juntos")


def test_la_despedida_no_hereda_los_titulos_de_la_portada():
    """`.cerrado h1` es otra pantalla: la de "CriticidadCHEC cerrado".

    Tocar el `h1` a secas se la habria llevado por delante sin que nadie lo pidiera -- y
    sin que ninguna prueba lo notara, porque esa pantalla la escribe el JavaScript. Por
    eso los de la portada van bajo `.portada h1` y no sobre `h1`.
    """
    pagina = _pagina()
    regla = re.search(r"\bh1\s*\{([^}]*)\}", pagina)
    assert regla and "font-size: 24px" in regla.group(1), (
        "el `h1` base ya no vale 24px; la despedida hereda el tamanio de la portada")


def test_la_cabecera_solo_lleva_el_boton():
    """Sin el titulo, la cabecera es una sola cosa: el boton, arriba a la derecha."""
    pagina = _pagina()
    cabecera = pagina[pagina.index("<header>"):pagina.index("</header>")]
    assert "<h1>" not in cabecera, "el titulo sigue en la cabecera"
    assert 'id="cerrar-todo"' in cabecera, "`Cerrar todo` se fue de la cabecera"
    regla = re.search(r"\bheader\s*\{([^}]*)\}", pagina)
    assert regla and "flex-end" in regla.group(1), (
        f"la cabecera no empuja su unico hijo a la derecha: {regla.group(1).strip()}")
