"""El verificador de la skill `redaccion-es`.

Una skill que solo diga "revisa la redaccion" no sirve de nada sobre cientos de cadenas:
el ojo se cansa y lo mecanico se escapa. Por eso la skill trae un verificador, y por eso
el verificador tiene pruebas.

## Lo que se vigila aqui no es que encuentre cosas: es que NO invente

Un detector de redaccion con falsos positivos es peor que no tenerlo, porque obliga a
revisar a mano cada hallazgo y en dos rondas se deja de mirar. Asi que la mitad de estas
pruebas son casos que TIENEN que callar: identificadores ingleses, siglas del dominio,
expresiones regulares con `?`, y las palabras que en espaniol existen con tilde y sin
ella.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SKILL = RAIZ / ".claude" / "skills" / "redaccion-es"


def _revisar():
    ruta = SKILL / "assets" / "revisar.py"
    spec = importlib.util.spec_from_file_location("revisar_es", ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["revisar_es"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def _clases(texto: str) -> set[str]:
    return {h.clase for h in _revisar().revisar_texto(texto, "x", 1)}


# ------------------------------------------------------------------ la skill existe bien


def test_la_skill_declara_su_contrato():
    """Frontmatter completo y en una sola linea, como pide la guia de estilo."""
    texto = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert texto.startswith("---\n"), "la skill no lleva frontmatter"
    frente = texto.split("---")[1]
    for campo in ("name:", "description:", "license:", "author:", "version:"):
        assert campo in frente, f"al frontmatter le falta `{campo}`"
    renglon = [l for l in frente.splitlines() if l.startswith("description:")][0]
    valor = renglon.split("description:", 1)[1].strip().strip('"')
    # 250 es el maximo duro de `docs/skill-style-guide.md`, y se mide sobre el VALOR: la
    # linea entera incluye la clave y las comillas, que no son descripcion.
    assert len(valor) <= 250, f"la descripcion pasa del maximo duro de 250: {len(valor)}"
    assert valor.startswith("Trigger:"), "la descripcion no empieza por sus disparadores"


def test_la_skill_apunta_a_archivos_que_existen():
    """Una referencia rota en una skill no falla: simplemente no se lee."""
    texto = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    import re
    for destino in re.findall(r"\]\(([^)]+)\)", texto):
        if destino.startswith("http"):
            raise AssertionError(f"la skill referencia una URL externa: {destino}")
        assert (SKILL / destino).exists(), f"la skill apunta a algo que no existe: {destino}"


# -------------------------------------------------------------- lo que TIENE que atrapar


def test_atrapa_las_tildes_que_no_admiten_discusion():
    """Palabras cuya forma sin tilde no existe: no hay contexto que las salve."""
    assert "tilde" in _clases("El analisis de la aplicacion es tambien el maximo.")


def test_atrapa_el_interrogativo_de_una_pregunta_indirecta():
    """`cuantos` lleva tilde aunque no haya ningun `?` en la frase.

    Es el caso que mas se escapa a ojo, porque sin signos no parece una pregunta.

    Sale en `tilde-dudosa` y no en `tilde`: se atrapa igual -- que es lo que esta prueba
    defiende -- pero no se aplica solo. La diferencia la puso un error real; el detalle
    esta en `test_los_interrogativos_van_a_su_propia_clase_y_no_se_aplican_solos`.
    """
    assert "tilde-dudosa" in _clases("No se sabe cuantos vanos hay en la ventana.")


def test_atrapa_la_pregunta_sin_abrir():
    assert "signos" in _clases("Y entonces, que pasa si el vano falla?")


def test_atrapa_el_caso_titulo_aunque_lleve_una_sigla_en_medio():
    """En este dominio casi todo titulo lleva una -- UITI, MIL, CHEC --.

    Si la sigla cortara la racha, el detector se apagaria justo donde mas falta hace.
    """
    assert "mayusculas" in _clases("El Modelo MIL Congelado de la red")
    assert "mayusculas" in _clases("Trayectorias De Circuitos Criticos")


def test_atrapa_muletillas_y_redundancias():
    clases = _clases("Con el fin de llevar a cabo el subir arriba de la serie.")
    assert "verboseo" in clases and "redundancia" in clases


# ------------------------------------------------------- lo que TIENE que dejar en paz


def test_calla_ante_codigo_ingles():
    """Sin este filtro, cada identificador del repositorio seria un hallazgo."""
    assert not _clases("compute_feature_importance(x, n_estimators=100)")


def test_calla_ante_las_palabras_que_existen_de_las_dos_formas():
    """`periodo`/`período`, `solo`, `este`, `aun`, `calculo`/`cálculo`.

    Corregirlas seria inventarse cual queria el autor. La skill lo dice: lo que no es
    decidible se reporta, no se cambia -- y aqui ni siquiera se reporta, porque no hay
    nada que decidir sin leer la frase entera.
    """
    for frase in ("El periodo de la ventana es el que se analiza.",
                  "Solo este calculo se hace con la serie de la ventana.",
                  "El vano aun no tiene eventos en la ventana."):
        assert "tilde" not in _clases(frase), f"corrige de mas en: {frase!r}"


def test_calla_ante_los_titulos_reales_de_los_tableros():
    """Los cinco estan bien escritos. Si el detector los marcara, sobraria."""
    sys.path.insert(0, str(RAIZ / "aplicaciones" / "_comun"))
    try:
        import tableros
    finally:
        sys.path.pop(0)
    for t in tableros.TABLEROS:
        assert "mayusculas" not in _clases(t.titulo), (
            f"el detector marca un titulo que esta bien: {t.titulo!r}")


def test_calla_ante_un_signo_de_cierre_que_es_sintaxis():
    """El `?` de una expresion regular o de una URL no es una pregunta sin abrir."""
    assert "signos" not in _clases('el patron de la clave, con r"^(a|b)+?$" y su alternativa')


def test_el_que_conjuncion_no_lleva_tilde():
    """`que` atono es la palabra mas comun del idioma: un falso positivo aqui inunda el
    informe y lo vuelve inservible."""
    assert "tilde" not in _clases("La ventana que se elige define el conjunto que se dibuja.")


# --------------------------------------- lo que el verificador aprendio de un error real


def test_los_interrogativos_van_a_su_propia_clase_y_no_se_aplican_solos():
    """`que` atono es la palabra mas comun del idioma. Ninguna heuristica sin analisis
    sintactico separa "no se QUE pasa" de "la pregunta QUE se repite".

    Se separo en `tilde-dudosa` despues de que un corrector automatico, usando la clase
    `tilde` a secas, acentuara SIETE `que` de un parrafo donde uno solo lo necesitaba.
    """
    revisar = _revisar()
    assert "tilde-dudosa" not in revisar.AUTOMATICAS, (
        "los interrogativos se aplicarian solos, y cambian lo que la frase dice")
    assert revisar.AUTOMATICAS == {"tilde"}, (
        "alguna clase que necesita leer la frase entro en las automaticas")


def test_un_signo_lejano_no_arrastra_los_que_de_todo_el_bloque():
    """El bug original: `"¿" in antes and "?" in despues` sobre el BLOQUE entero.

    Un `¿...?` en el primer renglon marcaba todos los `que` de los veinte siguientes. El
    alcance es la FRASE.
    """
    bloque = ("Aqui va una pregunta: ¿que pasa si el vano falla?\n\n"
              "Y despues prosa normal que no pregunta nada, de modo que el modelo hace\n"
              "que el contexto reescale lo estructural, que es lo que usa la base.\n")
    dudosas = [h for h in _revisar().revisar_texto(bloque, "x", 1)
               if h.clase == "tilde-dudosa"]
    assert len(dudosas) <= 1, (
        f"un signo lejano contagia a los `que` de otras frases: {len(dudosas)} marcados")


def test_la_pregunta_como_sustantivo_no_dispara_la_indirecta():
    """"la pregunta que mas se repite" fue el falso positivo concreto que rompio un
    cuaderno: `pregunta` estaba en la lista de verbos y aqui es sustantivo."""
    texto = "Donde entra el grafo fijo, que es la pregunta que mas se repite."
    dudosas = [h for h in _revisar().revisar_texto(texto, "x", 1)
               if h.clase == "tilde-dudosa"]
    assert not dudosas, f"marca un `que` relativo como interrogativo: {dudosas}"


def test_cada_hallazgo_sabe_donde_esta():
    """Sin posicion, un corrector solo tiene la palabra -- y la parchea en todas partes.

    Es la causa raiz del episodio anterior, no un detalle de comodidad.
    """
    texto = "El analisis de la aplicacion tambien mide el maximo."
    for h in _revisar().revisar_texto(texto, "x", 1):
        assert h.columna >= 0, f"hallazgo sin posicion: {h}"
        assert texto[h.columna:h.columna + len(h.fragmento)].lower() == h.fragmento.lower(), (
            f"la posicion de {h.fragmento!r} no apunta a la palabra")


def test_una_palabra_en_mayusculas_sigue_en_mayusculas():
    """`.capitalize()` sobre `GEOMETRIA` devolvia `Geometria`.

    En este repositorio las mayusculas dentro de una frase son ENFASIS del autor, no un
    descuido: normalizarlas al acentuar cambia lo que el texto subraya. Y las mayusculas
    tambien llevan tilde, asi que la respuesta correcta es `GEOMETRÍA`.
    """
    revisar = _revisar()
    casos = {"GEOMETRIA": "GEOMETRÍA", "Geometria": "Geometría", "geometria": "geometría"}
    for entrada, salida in casos.items():
        h = [x for x in revisar.revisar_texto(f"la {entrada} de los centroides", "x", 1)
             if x.clase == "tilde"]
        assert h and h[0].sugerencia == salida, (
            f"{entrada!r} deberia acentuarse como {salida!r}, no como "
            f"{h[0].sugerencia if h else 'nada'!r}")
