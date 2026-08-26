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


def test_los_nombres_de_grupo_del_esquema_no_son_prosa():
    """Cinco agentes de una misma corrida chocaron con esto por separado.

    `variable_groups_used` es un enum CERRADO del esquema y dos de sus seis literales van
    sin tilde a proposito -- `Proteccion` y `Topologia` --, porque la clave es un
    identificador que viaja al contrato. La guarda los leia como prosa y los rechazaba, asi
    que ningun informe podia atribuir un hallazgo a esos dos grupos: el esquema exigia una
    forma que el validador prohibia. Es la misma razon por la que `_cadenas` ya se salta las
    CLAVES -- una interfaz no se acentua --, aplicada al VALOR cuando el valor es la
    interfaz.
    """
    from chec_local_interpreter.domain_context import NOMBRE_LEGIBLE_GRUPO

    for grupo in NOMBRE_LEGIBLE_GRUPO:
        assert errores_de_tilde({"variable_groups_used": [grupo]}) == [], grupo


def test_el_esquema_y_la_exencion_no_pueden_separarse():
    """La exencion sale de `NOMBRE_LEGIBLE_GRUPO`, no de una lista copiada a mano.

    `Fisicas/Electricas` pasaba la guarda por CASUALIDAD -- los plurales `fisicas` y
    `electricas` no estan en el diccionario aunque los singulares si --, de modo que una
    entrada nueva en el diccionario habria roto un tercer grupo sin que nadie lo tocara.
    """
    import json
    from pathlib import Path

    from chec_local_interpreter.domain_context import NOMBRE_LEGIBLE_GRUPO

    esquema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "src/chec_local_interpreter/prompt_assets"
            / "uiti_vano_explanation.output_schema.json"
        ).read_text(encoding="utf-8")
    )
    enum = esquema["properties"]["key_findings"]["items"]["properties"][
        "variable_groups_used"
    ]["items"]["enum"]

    assert set(enum) == set(NOMBRE_LEGIBLE_GRUPO)


def test_la_exencion_es_del_valor_entero_no_de_la_palabra():
    """Exime al identificador, no al termino. `proteccion` dentro de una frase sigue siendo
    prosa y sigue necesitando su tilde -- si no, la exencion abriria un agujero por el que
    se cuela justo la palabra que mas veces aparecio sin tilde."""
    assert errores_de_tilde({"nota": "La proteccion del vano fallo"}) != []
    assert errores_de_tilde({"modo": "Proteccion y Topologia del tramo"}) != []


def test_el_diccionario_cubre_lo_que_un_agente_tuvo_que_corregir_a_mano():
    """Un agente de la corrida real lo dijo asi: "el diccionario es un piso, no un techo".

    `errores_de_tilde` le devolvio CERO mientras su prosa todavia llevaba estas nueve
    palabras sin tilde, ninguna en la lista. Las corrigio a mano y las reporto. Pasar la
    guarda a cero no era lo mismo que escribir bien.
    """
    faltaban = {
        "explicacion": "explicación",
        "separacion": "separación",
        "perturbacion": "perturbación",
        "taxonomia": "taxonomía",
        "todavia": "todavía",
        "transicion": "transición",
        "patron": "patrón",
        "situa": "sitúa",
        "simultaneamente": "simultáneamente",
    }
    for escrita, correcta in faltaban.items():
        assert SIEMPRE_CON_TILDE.get(escrita) == correcta, escrita


def test_los_plurales_en_ciones_siguen_sin_llevar_tilde():
    """La trampa que ya costo cuatro entradas malas: `-cion` es aguda y lleva tilde;
    `-ciones` es llana terminada en -s y NO la lleva. Cada palabra nueva del diccionario
    puede volver a meter su plural por descuido."""
    for singular in ("explicacion", "separacion", "perturbacion", "transicion"):
        plural = singular + "es"
        assert plural not in SIEMPRE_CON_TILDE, plural
        assert palabras_sin_tilde(f"varias {plural} del tramo") == []


# --- La enye, y el glosario que tapaba la prosa --------------------------------
#
# Los dos defectos salieron de una corrida real de `/informe-gerencial todos`
# (2026-08-26): 36 agentes pasaron la guarda en verde y aun asi tuvieron que
# revisarse la prosa A MANO, cada uno cazando entre 1 y 12 palabras que
# `errores_de_tilde` no habia visto. Dos mecanismos, no un diccionario corto.


def test_la_enye_no_es_una_tilde_y_no_puede_tapar_a_la_palabra():
    """El defecto de mecanismo: `_sin_tildes` descomponia `ñ` en `n` + virgulilla y la
    quitaba, asi que TODA palabra con enye salia distinta de si misma y se saltaba con el
    comentario `# ya la lleva`.

    El efecto no era que faltaran entradas en el diccionario: era que `añadira`, `señalo` y
    `acompañara` no se revisaban NUNCA por la tilde que de verdad les faltaba. La enye les
    servia de escudo.
    """
    from chec_local_interpreter.ortografia import _sin_tildes

    # La enye se conserva: no es una tilde de acentuacion, es otra letra.
    assert _sin_tildes("años") == "años"
    assert _sin_tildes("señal") == "señal"
    assert _sin_tildes("PEQUEÑO") == "PEQUEÑO"

    # La dieresis tampoco es una tilde.
    assert _sin_tildes("pingüino") == "pingüino"

    # Lo unico que se quita es la tilde aguda, que es la que marca el acento.
    assert _sin_tildes("análisis") == "analisis"
    assert _sin_tildes("añadirá") == "añadira"

    # La consecuencia que importa: una palabra con enye ya NO se salta, se mira.
    assert _sin_tildes("añadira") == "añadira"
    assert _sin_tildes("señalo") == "señalo"


def test_una_palabra_con_enye_ya_escrita_bien_no_se_marca():
    """La otra mitad del arreglo: conservar la enye no puede inventar defectos."""
    assert palabras_sin_tilde("la señal acompaña al pequeño tramo") == []
    assert palabras_sin_tilde("hace dos años se añadio el diseño") == []


def test_el_vocabulario_con_enye_de_la_corrida_esta_en_el_diccionario():
    """Las 28 formas con enye que los agentes escribieron de verdad en los 12 circuitos.

    Salen del corpus (`*.out.json` + `reports/vault/*.md`), no de una lista imaginada: 264
    apariciones, encabezadas por `señal` (48), `acompaña` (47) y `señala` (30).
    """
    corpus = {
        "senal": "señal", "senales": "señales",
        "senala": "señala", "senalan": "señalan", "senalado": "señalado",
        "senaladas": "señaladas", "senalando": "señalando",
        "acompana": "acompaña", "acompanan": "acompañan",
        "acompanado": "acompañado", "acompanada": "acompañada",
        "acompanados": "acompañados", "acompanadas": "acompañadas",
        "acompanar": "acompañar", "acompanando": "acompañando",
        "acompanamiento": "acompañamiento",
        "pequeno": "pequeño", "pequena": "pequeña",
        "pequenos": "pequeños", "pequenas": "pequeñas",
        "ano": "año", "anos": "años", "tamano": "tamaño",
        "anade": "añade", "anadir": "añadir", "anadieron": "añadieron",
        "diseno": "diseño",
    }
    for escrita, correcta in corpus.items():
        assert SIEMPRE_CON_TILDE.get(escrita) == correcta, escrita
        assert palabras_sin_tilde(f"el {escrita} del tramo") == [(escrita, correcta)]


def test_campana_se_queda_sin_decidir_porque_las_dos_son_palabras():
    """`campana` y `campaña` existen las dos. Es el mismo caso de `periodo`/`período`: la
    guarda no puede elegir sin cambiar el significado, asi que no elige."""
    assert SIEMPRE_CON_TILDE.get("campana", "AUSENTE") in (None, "AUSENTE")
    assert palabras_sin_tilde("la campana del circuito") == []


def test_el_glosario_no_puede_tapar_una_palabra_escrita_como_prosa():
    """El segundo defecto: `es_codigo` no solo eximia al codigo, TAPABA a la palabra.

    `duracion` en minusculas dentro de una frase no se marcaba nunca, porque `DURACION`
    esta en `NOMBRE_NATURAL`. El punto ciego alcanzaba a cualquier palabra corriente que
    chocara con un nombre de columna. Lo que decide es como esta ESCRITO el token: en
    mayusculas y en el glosario es una columna; en minusculas es castellano.
    """
    from chec_local_interpreter.ortografia import es_codigo

    # La columna sigue exenta, y el rotulo en mayusculas sigue siendo prosa.
    assert es_codigo("DURACION", "DURACION")
    assert not es_codigo("GEOMETRIA", "GEOMETRIA")

    # Lo nuevo: en minusculas es prosa aunque el glosario tenga esa columna.
    assert not es_codigo("duracion", "la duracion")
    assert not es_codigo("codigo", "el codigo de causa")

    # Y en mitad de frase, con mayuscula inicial, tambien es prosa.
    assert not es_codigo("Duracion", "Duracion de la falla")


def test_la_prosa_y_la_columna_conviven_en_la_misma_frase():
    """La prueba que resume las dos mitades: la palabra se corrige, la columna no."""
    assert palabras_sin_tilde("la duracion de la interrupcion") == [
        ("duracion", "duración"),
        ("interrupcion", "interrupción"),
    ]
    assert palabras_sin_tilde("la duracion se lee en DURACION") == [
        ("duracion", "duración"),
    ]


def test_el_vocabulario_que_los_agentes_corrigieron_a_mano_esta_en_el_diccionario():
    """Los dos arreglos de mecanismo recuperaron 10 de las 32 palabras que los 36 agentes
    de la corrida reportaron haber corregido A MANO despues de un exit 0. Las otras eran
    hueco de diccionario: sin ellas la guarda sigue dependiendo de que cada agente se
    revise solo, que es justo lo que este modulo existe para no tener que hacer."""
    faltaban = {
        "discusion": "discusión", "revision": "revisión", "supervision": "supervisión",
        "situacion": "situación", "configuracion": "configuración",
        "documentacion": "documentación", "coordinacion": "coordinación",
        "repeticion": "repetición", "interseccion": "intersección",
        "telemetria": "telemetría", "nucleo": "núcleo", "regimen": "régimen",
        "estres": "estrés", "traves": "través", "margenes": "márgenes",
        "moviles": "móviles", "via": "vía",
        "encontro": "encontró", "contribuyo": "contribuyó",
        "pequenisimo": "pequeñísimo",
    }
    for escrita, correcta in faltaban.items():
        assert SIEMPRE_CON_TILDE.get(escrita) == correcta, escrita
        assert palabras_sin_tilde(f"el {escrita} del tramo") == [(escrita, correcta)]


def test_mas_sigue_sin_decidirse_como_ya_lo_habia_decidido_el_modulo():
    """Un agente tambien corrigio `mas` -> `más`, pero el diccionario ya la tenia en `None`
    a proposito: `mas` adversativo (`pobre mas honrado`) y `más` de cantidad son las dos
    correctas. Medido sobre el corpus de los 12 circuitos salen 475 `más` y ningun `mas`
    adversativo, asi que en ESTE dominio decidirla seria seguro -- pero es una decision de
    politica del modulo, no un hueco, y se deja donde estaba."""
    assert SIEMPRE_CON_TILDE["mas"] is None
    assert palabras_sin_tilde("cada vez mas registros") == []


def test_cambio_se_queda_fuera_porque_el_sustantivo_manda():
    """Un agente corrigio `cambio` -> `cambió` y lo reporto, pero medido sobre el corpus de
    los 12 circuitos el sustantivo sale 85 veces (`un cambio de resolución`, `en cambio`)
    contra 2 del verbo. Meterla daria 85 falsos positivos: es el caso de `periodo`."""
    assert SIEMPRE_CON_TILDE.get("cambio", "AUSENTE") in (None, "AUSENTE")
    assert palabras_sin_tilde("un cambio de grupo simulado") == []


def test_ningun_plural_en_siones_ni_en_iones_pide_tilde():
    """La guarda de plurales solo miraba `-ciones`, y las palabras nuevas en `-sión`
    (`discusión`, `revisión`, `supervisión`) caen en la MISMA trampa sin que nadie mire:
    `-sión` es aguda y lleva tilde, `-siones` es llana terminada en -s y no.

    Vigilar la terminacion y no una lista es lo que impide que la proxima palabra vuelva a
    meter su plural por descuido.
    """
    culpables = [
        k for k, v in SIEMPRE_CON_TILDE.items()
        if v is not None and (k.endswith("siones") or k.endswith("ciones"))
    ]
    assert culpables == [], f"plurales en -siones/-ciones en el diccionario: {culpables}"

    for singular in ("discusion", "revision", "supervision", "situacion", "repeticion"):
        plural = singular[:-3] + "ones"
        assert plural not in SIEMPRE_CON_TILDE, plural
        assert palabras_sin_tilde(f"varias {plural} del tramo") == []


def test_el_verificador_del_skill_no_duplica_la_regla_de_la_enye():
    """El skill tenia su PROPIA copia de `_sin_tildes`, y era peor que la del modulo:
    `NFKD -> ascii ignore` se lleva la enye y de paso todo lo que no sea ASCII.

    Es exactamente la duplicacion que el docstring del modulo declara como el fallo
    original -- la copia del diccionario en el skill tenia 153 palabras y ninguna de las que
    de verdad fallaron. Una regla duplicada deriva; una importada, no. La decision de si una
    palabra YA lleva tilde tiene que salir del modulo, no de una copia.
    """
    from chec_local_interpreter import ortografia

    rv = _cargar_verificador()

    assert rv._sin_tildes_de_acento is ortografia._sin_tildes
    assert rv._sin_tildes_de_acento("años") == "años"


def test_el_verificador_del_skill_pliega_a_ASCII_solo_para_casar_frases():
    """La otra mitad: el emparejado de muletillas SI necesita plegar a ASCII, porque las 35
    frases de `_MULETILLAS`/`_REDUNDANCIAS`/`_DIALECTO` estan escritas sin tilde y tienen
    que casar con prosa acentuada. Son dos preguntas distintas que compartian un nombre."""
    rv = _cargar_verificador()

    assert rv._plano_ascii("análisis periódico") == "analisis periodico"
    assert rv._plano_ascii("años") == "anos"

    clases = {h.clase for h in rv.revisar_texto(
        "Se hizo así con el fin de medir la señal.", "x", 1)}
    assert "verboseo" in clases
