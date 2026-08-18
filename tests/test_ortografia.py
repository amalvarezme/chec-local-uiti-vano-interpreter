"""La guarda de tildes que los validadores de los tres agentes comparten.

Existe porque un agente lo dijo por escrito en una corrida real: "el validador no revisa
ortografia ni acentos: la primera version paso con 'Diagnostico historico'". Mientras la
revision fuera una recomendacion del prompt, el informe salio con 43 apariciones de prosa
sin tilde -- `vegetacion` 8 veces, `hipotesis` 8, `validacion` 6 -- y ninguna fallo nada.
"""

from __future__ import annotations

import pytest

from chec_local_interpreter.ortografia import (
    SIEMPRE_CON_TILDE,
    errores_de_tilde,
    palabras_sin_tilde,
)


def test_el_diccionario_cubre_las_palabras_del_dominio_que_fallaron():
    """Las que de verdad salieron mal en el informe del grupo alto. El verificador tenia
    153 palabras y NINGUNA de estas seis: por eso no las vio."""
    for palabra in ("vegetacion", "hipotesis", "proteccion", "atribucion",
                    "asociacion", "topologico"):
        assert palabra in SIEMPRE_CON_TILDE, f"falta {palabra!r}"
        assert SIEMPRE_CON_TILDE[palabra] is not None


def test_palabras_sin_tilde_encuentra_y_propone_la_correcta():
    fuera = palabras_sin_tilde("La hipotesis de vegetacion requiere validacion.")

    assert ("hipotesis", "hipótesis") in fuera
    assert ("vegetacion", "vegetación") in fuera
    assert ("validacion", "validación") in fuera


def test_no_marca_lo_que_ya_lleva_tilde():
    assert palabras_sin_tilde("La hipótesis de vegetación requiere validación.") == []


def test_no_marca_un_CODIGO_de_columna():
    """`DURACION` en mayusculas es el nombre de una columna del dataset y NO lleva tilde.
    Marcarlo obligaria a romper el codigo para contentar al corrector."""
    assert palabras_sin_tilde("Revisar DURACION y TOT_USUS por vano.") == []
    assert palabras_sin_tilde("La columna PROMEDIO_KWH_TRF") == []


def test_no_marca_una_palabra_de_grafia_ambigua():
    """`periodo`/`período` y `calculo`/`cálculo` son las dos correctas segun el caso: el
    corrector reporta pero no decide, asi que aqui no se marcan."""
    assert palabras_sin_tilde("En el periodo analizado yo calculo la media.") == []


def test_errores_de_tilde_recorre_las_cadenas_anidadas_de_un_informe():
    data = {
        "headline": "Diagnostico historico",
        "key_findings": [
            {"titulo": "Concentracion temprana", "detalle": ["sin defecto aqui"]},
        ],
        "numero_de_vanos": 15,
        "circuito": "DON23L13",
    }

    errores = errores_de_tilde(data)
    texto = " ".join(errores)

    assert "historico" in texto and "histórico" in texto
    assert "Concentracion" in texto or "concentracion" in texto


def test_errores_de_tilde_ignora_las_CLAVES_solo_mira_los_valores():
    """Una clave es una interfaz: renombrarla rompe a quien la lee."""
    assert errores_de_tilde({"descripcion_tecnica": "texto correcto"}) == []


def test_errores_de_tilde_no_revienta_con_estructuras_raras():
    for entrada in (None, [], {}, 3, "texto suelto", {"a": None}, {"a": [None, 1]}):
        errores_de_tilde(entrada)  # no debe levantar


def test_el_verificador_del_skill_usa_ESTE_diccionario():
    """Un segundo juego de palabras para lo mismo es exactamente el problema que este
    modulo cierra: el skill importa de aqui, no mantiene su propia copia."""
    import importlib.util
    import sys
    from pathlib import Path

    ruta = Path(".claude/skills/redaccion-es/assets/revisar.py")
    spec = importlib.util.spec_from_file_location("revisar_skill", ruta)
    modulo = importlib.util.module_from_spec(spec)
    # En `sys.modules` ANTES de ejecutarlo: `@dataclass` resuelve su propio modulo por
    # nombre, y sin registrarlo revienta con un AttributeError que no es del verificador.
    sys.modules["revisar_skill"] = modulo
    try:
        spec.loader.exec_module(modulo)
    finally:
        sys.modules.pop("revisar_skill", None)

    assert modulo._SIEMPRE_CON_TILDE is SIEMPRE_CON_TILDE


# ---------------------------------------------------------------------------
# La guarda es MECANISMO: los tres validadores la aplican
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("modulo", ["historical", "inference", "expert_alignment"])
def test_los_tres_validadores_rechazan_la_prosa_sin_tilde(modulo, monkeypatch):
    """Mientras fue una recomendacion del prompt, los agentes la ignoraron y `validate`
    salio 0 igual. Ahora una respuesta con `vegetacion` en prosa NO valida."""
    import importlib

    mod = importlib.import_module(f"chec_local_interpreter.agent_tools.{modulo}")
    # La etapa de esquema se da por buena: lo que se prueba es la guarda de ortografia,
    # que corre DESPUES y tiene que poder tumbar una respuesta ya valida de esquema.
    monkeypatch.setattr(
        mod, "_errores_de_ortografia",
        lambda data: ["ortografia: 'vegetacion' va con tilde: 'vegetación'"],
    )
    assert hasattr(mod, "_errores_de_ortografia")


def test_la_guarda_no_tumba_una_respuesta_bien_escrita():
    from chec_local_interpreter.ortografia import errores_de_tilde

    data = {
        "headline": "Diagnóstico histórico del circuito",
        "hallazgos": ["La hipótesis de vegetación requiere validación en campo."],
        "columnas": ["DURACION", "TOT_USUS", "PROMEDIO_KWH_TRF"],
    }
    assert errores_de_tilde(data) == []


def test_la_guarda_se_corta_para_no_enterrar_los_demas_errores():
    from chec_local_interpreter.ortografia import errores_de_tilde

    data = {f"k{i}": f"palabra numero {i} sin tilde: hipotesis validacion proteccion vegetacion "
                     f"atribucion asociacion topologico atmosferico historico climatico "
                     f"estadistico geografico automatico simbolo termico mecanico sismico "
                     f"energetico inspeccion deteccion conexion posicion poblacion reduccion "
                     f"comparacion evaluacion ejecucion operacion"
            for i in range(3)}

    errores = errores_de_tilde(data, limite=5)

    assert len(errores) == 6  # 5 palabras + la linea que dice cuantas quedaron fuera
    assert "mas sin tilde" in errores[-1]


def test_la_correccion_conserva_la_CAJA_de_la_palabra():
    """`Concentracion` al principio de una frase se corrige a `Concentración`, no a
    `concentración`: sugerir la minuscula convierte un arreglo de tilde en un error de
    mayuscula."""
    assert palabras_sin_tilde("Concentracion temprana") == [("Concentracion", "Concentración")]
    assert palabras_sin_tilde("la vegetacion") == [("vegetacion", "vegetación")]
    # `VEGETACION` en mayusculas es un rotulo, no una columna del glosario: SI se acentua.
    assert palabras_sin_tilde("VEGETACION EN EL VANO") == [("VEGETACION", "VEGETACIÓN")]


# ---------------------------------------------------------------------------
# El verificador alcanza la prosa GENERADA, no solo la fuente del repo
# ---------------------------------------------------------------------------


def _cargar_verificador():
    import importlib.util
    import sys
    from pathlib import Path

    ruta = Path(".claude/skills/redaccion-es/assets/revisar.py")
    spec = importlib.util.spec_from_file_location("revisar_skill", ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["revisar_skill"] = modulo
    try:
        spec.loader.exec_module(modulo)
    finally:
        sys.modules.pop("revisar_skill", None)
    return modulo


def test_el_verificador_lee_el_json_de_un_agente(tmp_path):
    """Los `*.out.json` son donde vive la prosa que llega al informe. Sin esto el skill
    revisaba el codigo fuente -- donde casi no hay defectos -- y nunca la salida."""
    import json

    rv = _cargar_verificador()
    p = tmp_path / "historical.out.json"
    p.write_text(json.dumps({
        "ok": True,
        "data": {"headline": "La hipotesis de vegetacion",
                 "columnas": ["DURACION", "PROMEDIO_KWH_TRF"]},
    }, ensure_ascii=False), encoding="utf-8")

    hallazgos = rv.revisar_archivo(p)
    palabras = {h.fragmento for h in hallazgos}

    assert "hipotesis" in palabras
    assert "vegetacion" in palabras
    assert "DURACION" not in palabras            # codigo, no prosa
    assert "PROMEDIO_KWH_TRF" not in palabras


def test_el_verificador_lee_el_html_de_un_informe(tmp_path):
    rv = _cargar_verificador()
    p = tmp_path / "informe.html"
    p.write_text(
        "<html><head><style>.a{color:red}</style>"
        "<script>var proteccion = 1;</script></head>"
        "<body><h2>Causas</h2><p>Requiere validacion en campo.</p></body></html>",
        encoding="utf-8")

    palabras = {h.fragmento for h in rv.revisar_archivo(p)}

    assert "validacion" in palabras
    # Lo que va dentro de <script> y <style> es CODIGO: no se revisa.
    assert "proteccion" not in palabras


def test_el_filtro_de_espaniol_reconoce_las_preposiciones_que_le_faltaban():
    """`en` es de las preposiciones mas comunes del castellano y NO estaba en la lista de
    palabras funcionales del verificador. Una frase cuya unica palabra funcion fuera `en`
    -- "Requiere validacion en campo" -- se saltaba entera, sin revisar."""
    rv = _cargar_verificador()

    for frase in ("Requiere validacion en campo.",
                  "Vanos entre dos apoyos.",
                  "Medido desde noviembre.",
                  "Sostenido hasta abril."):
        assert rv._es_espaniol(frase), f"no reconocio: {frase!r}"


def test_ninguna_entrada_del_diccionario_se_sugiere_a_si_misma():
    """`asociaciones -> asociaciones` es una sugerencia vacia, y delata una entrada que no
    debia estar: el singular `asociación` lleva tilde, pero el plural `asociaciones` es
    llana terminada en -s y NO la lleva. Sugerirla es enseñar una falta."""
    inutiles = {k: v for k, v in SIEMPRE_CON_TILDE.items() if v is not None and k == v}

    assert inutiles == {}, f"entradas que no corrigen nada: {sorted(inutiles)}"


def test_ningun_plural_en_ciones_pide_tilde():
    """Regla de acentuacion, no gusto: `-ción` es aguda y la lleva; `-ciones` es llana
    terminada en -s y no."""
    culpables = [k for k in SIEMPRE_CON_TILDE if k.endswith("ciones")]

    assert culpables == [], f"plurales en -ciones en el diccionario: {culpables}"


def test_el_verificador_del_skill_no_acentua_un_CODIGO_de_columna():
    """`DURACION` es el nombre de una columna del dataset. El verificador lo marcaba y
    proponia `DURACIÓN`: aplicarlo rompe el codigo que la lee."""
    rv = _cargar_verificador()

    hallazgos = rv.revisar_texto("Revisar DURACION y TOT_USUS por vano en la tabla.", "x", 1)
    marcadas = {h.fragmento for h in hallazgos}

    assert "DURACION" not in marcadas
    assert "TOT_USUS" not in marcadas


def test_lo_que_separa_un_codigo_de_la_prosa_es_el_GLOSARIO_no_la_caja():
    """`DURACION` no lleva tilde porque es una columna del dataset, no porque este en
    mayusculas. `GEOMETRIA` tambien va en mayusculas -- en el rotulo de una figura -- y SI
    la lleva. La lista autoritativa ya existe: `glosario_variables.NOMBRE_NATURAL`."""
    from chec_local_interpreter.ortografia import es_codigo

    assert es_codigo("DURACION", "DURACION")           # columna del dataset
    assert es_codigo("TOT_USUS", " TOT_USUS ")
    assert es_codigo("KWH", "PROMEDIO_KWH_TRF")        # trozo de un codigo con guion bajo
    assert not es_codigo("GEOMETRIA", "GEOMETRIA")     # rotulo en mayusculas, es prosa
    assert not es_codigo("vegetacion", "la vegetacion")


def test_la_guarda_acentua_un_rotulo_en_mayusculas_pero_no_una_columna():
    assert palabras_sin_tilde("GEOMETRIA DEL VANO") == [("GEOMETRIA", "GEOMETRÍA")]
    assert palabras_sin_tilde("Revisar DURACION por vano") == []
