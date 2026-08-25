"""RED/GREEN tests for `simulaciones_guardadas`: what a saved simulation IS.

The simulator's "Guardar" button answers two different questions with two
different artefacts, and the whole module exists because they must not be the
same file:

  1. **What did we decide?** -- a self-contained HTML report with the eight
     panels frozen as they were, plus the four tables a work order is approved
     on: which vanos, which variables at which values, which contract
     activities at which cost, and the measured-against-simulated UITI.
  2. **How do I get back here?** -- a record small enough to keep hundreds of,
     that "Cargar" turns back into a live dashboard.

The second one does NOT store the figures. Everything on screen is derived from
the model run over the inputs, so storing the panels would be storing a
function's return value next to its arguments -- two sources of truth that drift
the moment the model is retrained. The record stores the INPUTS and a summary of
what came out; loading replays the run. The `sello` is what makes that honest:
it carries the sha1 of the artefacts the run used, so a record replayed against
a retrained model SAYS SO instead of quietly producing different numbers under
the old name.

The summary travels anyway, and that is not a contradiction with the paragraph
above: it is what lets the HTML report be rebuilt -- and what a load can compare
against -- without a model in the room.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from chec_local_interpreter.simulaciones_guardadas import (
    ESQUEMA,
    EXTENSION,
    GRANO_CIRCUITO,
    OTRA_VERSION,
    SELLO_DISTINTO,
    actividades_por_vano,
    deserializar,
    informe_html,
    nombre_de_archivo,
    registro_de_simulacion,
    serializar,
    variables_por_vano,
    veredicto_del_sello,
)


# --------------------------------------------------------------------- fixtures


def _registro(**cambios):
    """Un registro completo y pequenio: dos vanos, dos variables, dos actividades.

    Se arma con el constructor publico y no como diccionario literal, para que una
    prueba no pueda afirmar una forma que el constructor ya no produce.
    """
    datos = dict(
        circuito="DON23L14",
        ventana_i=9,
        ventana_etiqueta="V10",
        ventana_periodo="2024-06-01 a 2024-09-01",
        vanos=["12345678", "87654321"],
        variables=[
            {"vano": "12345678", "knob_id": "NR_T", "variable": "Numero de arboles",
             "grupo": "Intervencion", "unidad": "arboles", "valor": 116.0},
            {"vano": "87654321", "knob_id": "NR_T", "variable": "Numero de arboles",
             "grupo": "Intervencion", "unidad": "arboles", "valor": 40.0},
            {"vano": "12345678", "knob_id": "PRECIP", "variable": "Precipitacion",
             "grupo": "Escenario", "unidad": "mm", "valor": 12.5},
        ],
        actividades=[
            {"vano": "12345678", "actividad": "PODA EN REDES RURALES TIPO A",
             "repeticiones": 2, "costo_unitario": 141736.0, "subtotal": 283472.0,
             "descripcion": "Poda de arboles hasta 3 m del conductor."},
            {"vano": "87654321", "actividad": "CAMBIO DE AISLADOR",
             "repeticiones": 1, "costo_unitario": 52000.0, "subtotal": 52000.0,
             "descripcion": "Reemplazo de aislador de porcelana."},
        ],
        uiti=[
            {"vano": "12345678", "observado": 100.0, "simulado": 60.0, "error": 8.0,
             "clase_observado": 3, "clase_simulado": 1},
            {"vano": "87654321", "observado": 50.0, "simulado": 55.0, "error": 4.0,
             "clase_observado": 1, "clase_simulado": 2},
        ],
        total_uiti={"observado": 900.0, "simulado": 860.0, "error": 12.0},
        costo_total=335472.0,
        reduccion=35.0,
        desviacion=12.0,
        cambian=2,
        n_vanos=2,
        sello={"mil_vano_ventana_v1.pt": "205273e9"},
        creado_en="2026-08-25T10:00:00",
    )
    datos.update(cambios)
    return registro_de_simulacion(**datos)


# ------------------------------------------------------- el registro y su forma


def test_el_registro_declara_su_esquema_y_su_sello():
    """Sin version de esquema, un archivo de hoy leido por el simulador de manana
    se interpreta con reglas que ya no son las suyas y falla en el sitio equivocado."""
    reg = _registro()
    assert reg["esquema"] == ESQUEMA
    assert reg["sello"] == {"mil_vano_ventana_v1.pt": "205273e9"}
    assert reg["creado_en"] == "2026-08-25T10:00:00"


def test_el_registro_guarda_la_seleccion_completa():
    reg = _registro()
    assert reg["seleccion"]["circuito"] == "DON23L14"
    assert reg["seleccion"]["ventana_i"] == 9
    assert reg["seleccion"]["ventana_etiqueta"] == "V10"
    assert reg["seleccion"]["vanos"] == ["12345678", "87654321"]


def test_el_registro_es_serializable_a_json_puro():
    """Nada de numpy ni de pandas dentro. Un `float64` de numpy no es serializable
    y el fallo saldria al escribir el archivo, o sea despues de haber dicho que se
    guardo."""
    json.dumps(_registro())


# ------------------------------------------------------------ ida y vuelta al disco


def test_serializar_y_deserializar_devuelven_el_mismo_registro():
    reg = _registro()
    assert deserializar(serializar(reg)) == reg


def test_lo_serializado_es_gzip_de_json_utf8():
    """El formato no es un detalle privado: quien audite una decision tiene que poder
    abrir el archivo sin este programa. `gzip` de JSON lo abre cualquiera."""
    crudo = gzip.decompress(serializar(_registro()))
    assert json.loads(crudo.decode("utf-8"))["esquema"] == ESQUEMA


def test_el_registro_pesa_pocos_kilobytes():
    """La razon de ser del formato. Con dos vanos tiene que caber holgadamente por
    debajo de lo que costaria congelar una sola de las ocho figuras."""
    assert len(serializar(_registro())) < 4096


def test_deserializar_rechaza_un_esquema_futuro():
    futuro = _registro()
    futuro["esquema"] = ESQUEMA + 1
    with pytest.raises(ValueError, match="esquema"):
        deserializar(serializar(futuro))


def test_deserializar_rechaza_un_archivo_que_no_es_del_simulador():
    with pytest.raises(ValueError):
        deserializar(gzip.compress(json.dumps({"hola": 1}).encode("utf-8")))


# --------------------------------------------------- reponer las entradas al cargar


def test_variables_por_vano_reconstruye_la_rejilla():
    """Lo que "Cargar" tiene que devolverle al panel: para cada vano, que control
    abrir y en que valor."""
    assert variables_por_vano(_registro()) == {
        "12345678": {"NR_T": 116.0, "PRECIP": 12.5},
        "87654321": {"NR_T": 40.0},
    }


def test_actividades_por_vano_reconstruye_las_repeticiones():
    assert actividades_por_vano(_registro()) == {
        "12345678": {"PODA EN REDES RURALES TIPO A": 2},
        "87654321": {"CAMBIO DE AISLADOR": 1},
    }


def test_el_grano_de_circuito_sobrevive_al_viaje():
    """Sin vanos marcados el simulador pregunta por el circuito entero y guarda sus
    valores bajo una clave que NO es un fid. Si esa clave no vuelve tal cual, cargar
    una simulacion de circuito completo repone cero controles y no dice por que."""
    reg = _registro(
        vanos=[],
        variables=[{"vano": GRANO_CIRCUITO, "knob_id": "NR_T",
                    "variable": "Numero de arboles", "grupo": "Intervencion",
                    "unidad": "arboles", "valor": 80.0}],
        actividades=[],
    )
    assert variables_por_vano(reg) == {GRANO_CIRCUITO: {"NR_T": 80.0}}


# ------------------------------------------------------------- el sello y su verdicto


def test_el_sello_igual_no_avisa_nada():
    assert veredicto_del_sello(_registro(), {"mil_vano_ventana_v1.pt": "205273e9"}) is None


def test_un_modelo_reentrenado_se_dice_al_cargar():
    """El defecto que esto impide: cargar una simulacion de julio contra el modelo de
    agosto devuelve numeros distintos bajo el mismo nombre, sin una sola senal."""
    aviso = veredicto_del_sello(_registro(), {"mil_vano_ventana_v1.pt": "otro"})
    assert aviso is not None
    assert aviso["clase"] == SELLO_DISTINTO
    assert "mil_vano_ventana_v1.pt" in aviso["mensaje"]


def test_un_registro_de_otra_version_del_esquema_tambien_se_dice():
    viejo = _registro()
    viejo["esquema"] = ESQUEMA - 1 if ESQUEMA > 1 else ESQUEMA
    if ESQUEMA == 1:
        pytest.skip("todavia no hay una version anterior del esquema")
    aviso = veredicto_del_sello(viejo, {"mil_vano_ventana_v1.pt": "205273e9"})
    assert aviso["clase"] == OTRA_VERSION


# ----------------------------------------------------------------- nombre de archivo


def test_el_nombre_lleva_circuito_ventana_y_fecha():
    nombre = nombre_de_archivo(_registro())
    assert nombre.startswith("DON23L14_V10_2026-08-25")
    assert nombre.endswith(EXTENSION)


def test_el_nombre_no_trae_caracteres_que_windows_rechace():
    r"""Windows rechaza `\ / : * ? " < > |` en un nombre de archivo, y la etiqueta de
    ventana del tablero lleva dos puntos (`V10: 2024-06-01 a ...`). Un nombre que
    funciona en macOS y revienta en Windows es exactamente lo que esta prueba impide."""
    nombre = nombre_de_archivo(_registro(circuito="DON/23:L14"))
    assert not set(nombre) & set('\\/:*?"<>|')


def test_el_nombre_es_estable_para_el_mismo_registro():
    reg = _registro()
    assert nombre_de_archivo(reg) == nombre_de_archivo(reg)


# ------------------------------------------------------------------ el informe HTML


def test_el_informe_trae_las_cuatro_tablas():
    html = informe_html(_registro(), figuras_html="<div id='figura'></div>")
    for titulo in ("Vanos y variables simuladas", "Actividades de contrato por vano",
                   "UITI medido contra UITI simulado"):
        assert titulo in html


def test_el_informe_embebe_las_figuras_que_le_dan():
    html = informe_html(_registro(), figuras_html="<div id='LA-FIGURA'></div>")
    assert "id='LA-FIGURA'" in html


def test_la_tabla_de_variables_dice_vano_variable_y_valor():
    html = informe_html(_registro(), figuras_html="")
    assert "Numero de arboles" in html
    assert "116" in html
    assert "12345678" in html


def test_la_tabla_de_actividades_trae_costo_unitario_y_descripcion():
    html = informe_html(_registro(), figuras_html="")
    assert "PODA EN REDES RURALES TIPO A" in html
    assert "141.736" in html          # costo unitario, formato espaniol
    assert "283.472" in html          # costo total de la actividad
    assert "Poda de arboles hasta 3 m del conductor." in html


def test_la_tabla_de_uiti_calcula_el_porcentaje_de_mejora_y_de_subida():
    """La columna que convierte dos numeros en una decision. Un vano que BAJA de 100
    a 60 mejora 40%; uno que SUBE de 50 a 55 empeora 10%, y el signo tiene que
    distinguirse a simple vista o la tabla se lee como si todo hubiera mejorado."""
    html = informe_html(_registro(), figuras_html="")
    assert "40,0" in html     # (100 - 60) / 100
    assert "10,0" in html     # (50 - 55) / 50, empeora


def test_la_tabla_de_uiti_totaliza_las_dos_columnas():
    html = informe_html(_registro(), figuras_html="")
    assert "900" in html and "860" in html


def test_un_uiti_observado_en_cero_no_revienta_el_porcentaje():
    """Division por cero disfrazada: un vano medido en 0 existe -- es un vano sin UITI
    acumulado en la ventana -- y el informe tiene que decir que no hay porcentaje, no
    tumbarse al generarlo."""
    reg = _registro(uiti=[{"vano": "12345678", "observado": 0.0, "simulado": 3.0,
                           "error": 1.0, "clase_observado": 0, "clase_simulado": 0}])
    html = informe_html(reg, figuras_html="")
    assert "12345678" in html


def test_el_informe_escapa_lo_que_viene_del_libro_de_costos():
    """Las descripciones las edita una persona en Excel. Un `<` suelto rompia el panel
    del simulador por esta misma razon, y aqui rompería el informe entero."""
    reg = _registro(actividades=[
        {"vano": "12345678", "actividad": "PODA <A>", "repeticiones": 1,
         "costo_unitario": 10.0, "subtotal": 10.0,
         "descripcion": "Sirve para vanos con <3 m de despeje"}])
    html = informe_html(reg, figuras_html="")
    assert "<3 m de despeje" not in html
    assert "&lt;3 m de despeje" in html


def test_el_informe_nombra_circuito_ventana_y_fecha_de_la_corrida():
    html = informe_html(_registro(), figuras_html="")
    assert "DON23L14" in html
    assert "V10" in html
    assert "2024-06-01 a 2024-09-01" in html


def test_el_informe_dice_que_el_uiti_simulado_lo_estima_un_modelo():
    """Las dos columnas son cantidades de naturaleza distinta -- una medicion y una
    prediccion --, y el tablero lo publica con su `+-`. Un informe que las pusiera
    lado a lado sin decirlo convertiria el sesgo del modelo en ahorro."""
    html = informe_html(_registro(), figuras_html="")
    assert "±" in html or "&plusmn;" in html


def test_un_informe_sin_actividades_lo_dice_en_vez_de_dejar_la_tabla_vacia():
    html = informe_html(_registro(actividades=[], costo_total=0.0), figuras_html="")
    assert "Actividades de contrato por vano" in html
    assert "no lleva actividades de contrato" in html


def test_el_informe_es_un_documento_html_completo():
    html = informe_html(_registro(), figuras_html="")
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert html.rstrip().lower().endswith("</html>")


def test_el_informe_declara_utf8():
    """Sin el `charset`, los nombres del contrato con tilde se ven rotos al abrir el
    archivo con doble clic en Windows."""
    assert 'charset="utf-8"' in informe_html(_registro(), figuras_html="").lower()


def test_el_informe_no_pide_nada_por_red():
    """Se abre con doble clic desde una carpeta, a veces sin internet y a veces desde
    una descarga del Volume de Databricks. Todo lo que necesite tiene que viajar
    dentro."""
    html = informe_html(_registro(), figuras_html="")
    assert "http://" not in html and "https://" not in html


# ------------------------------------------------------------------------ el sello


class _Tensor:
    """Lo minimo de un tensor de torch que `sello_del_modelo` toca. Se usa un doble
    y no torch para que la prueba del sello no arrastre 1,2 s de import."""

    def __init__(self, datos: bytes):
        self._datos = datos

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self

    def tobytes(self):
        return self._datos


class _Modelo:
    def __init__(self, pesos):
        self._pesos = pesos

    def state_dict(self):
        return {k: _Tensor(v) for k, v in self._pesos.items()}


def test_el_sello_nombra_las_tres_cosas_que_pueden_cambiar_los_numeros():
    from chec_local_interpreter.simulaciones_guardadas import sello_del_modelo

    sello = sello_del_modelo(_Modelo({"w": b"123"}), ["A", "B"], ["k1", "k2"])
    assert set(sello) == {"modelo MIL", "variables del modelo",
                          "catálogo de variables simulables"}
    assert all(isinstance(v, str) and v for v in sello.values())


def test_el_mismo_modelo_produce_el_mismo_sello():
    from chec_local_interpreter.simulaciones_guardadas import sello_del_modelo

    a = sello_del_modelo(_Modelo({"w": b"123"}), ["A"], ["k"])
    b = sello_del_modelo(_Modelo({"w": b"123"}), ["A"], ["k"])
    assert a == b


def test_reentrenar_cambia_el_sello_del_modelo_y_solo_ese():
    """Es la senial que hace honesto el "cargar y volver a simular": distinguir un
    modelo reentrenado de un catalogo editado importa, porque el segundo no cambia
    los numeros de las variables que si sobreviven."""
    from chec_local_interpreter.simulaciones_guardadas import sello_del_modelo

    antes = sello_del_modelo(_Modelo({"w": b"123"}), ["A"], ["k"])
    despues = sello_del_modelo(_Modelo({"w": b"456"}), ["A"], ["k"])
    assert antes["modelo MIL"] != despues["modelo MIL"]
    assert antes["variables del modelo"] == despues["variables del modelo"]


def test_el_orden_de_los_pesos_no_cambia_el_sello():
    """`state_dict` no garantiza orden entre versiones de torch, y un sello que
    cambiara por eso avisaria de un reentrenamiento que nunca ocurrio."""
    from chec_local_interpreter.simulaciones_guardadas import sello_del_modelo

    a = sello_del_modelo(_Modelo({"a": b"1", "b": b"2"}), ["A"], ["k"])
    b = sello_del_modelo(_Modelo({"b": b"2", "a": b"1"}), ["A"], ["k"])
    assert a == b


def test_un_modelo_que_no_expone_state_dict_no_tumba_el_guardado():
    """El sello es una cortesia, no un requisito. Un artefacto que no deje mirarse
    deja el sello vacio y el registro se guarda igual: perder la simulacion por no
    poder firmarla seria un pesimo negocio."""
    from chec_local_interpreter.simulaciones_guardadas import sello_del_modelo

    sello = sello_del_modelo(object(), ["A"], ["k"])
    assert sello["modelo MIL"] == ""
    assert sello["variables del modelo"]


def test_un_sello_vacio_no_dispara_el_aviso():
    """Un sello que no se pudo calcular no puede leerse como "el modelo cambio"."""
    from chec_local_interpreter.simulaciones_guardadas import sello_del_modelo

    reg = _registro(sello=sello_del_modelo(object(), ["A"], ["k"]))
    assert veredicto_del_sello(reg, sello_del_modelo(object(), ["A"], ["k"])) is None


# ------------------------------------------------- la cifra que el informe publica


def test_una_simulacion_que_empeora_dice_sube_y_no_baja_menos():
    """`reduccion` es `medido - simulado` y sale NEGATIVA cuando el escenario empeora
    esos vanos. Publicado como "baja -59,4" se lee como una errata y esconde el
    desenlace. Es un resultado legitimo: no todo escenario mejora."""
    html = informe_html(_registro(reduccion=-59.4, desviacion=5.0), figuras_html="")
    assert "sube <b>59,4</b>" in html
    assert "-59,4" not in html


def test_una_mejora_sigue_diciendo_baja():
    html = informe_html(_registro(reduccion=35.0, desviacion=5.0), figuras_html="")
    assert "baja <b>35,0</b>" in html


def test_un_desfase_mayor_que_el_cambio_se_dice():
    """El `+-` es el desfase acumulado del modelo y en estos datos puede ser del orden
    de la propia diferencia. Publicar la reduccion sola la haria pasar por un
    resultado firme."""
    html = informe_html(_registro(reduccion=10.0, desviacion=40.0), figuras_html="")
    assert "no sostiene" in html


def test_el_informe_separa_los_vanos_marcados_de_los_que_el_modelo_puntuo():
    """Medido sobre 30 circuitos, solo el 21% de las casillas de vano tienen eventos
    en una ventana dada. Publicar solo el segundo numero ponia "Vanos simulados: 2"
    encima de un plan de quince, y se lee como si trece se hubieran perdido."""
    reg = _registro(vanos=[f"1000000{i}" for i in range(15)], n_vanos=2)
    html = informe_html(reg, figuras_html="")
    assert "Vanos marcados:</b> 15" in html
    assert "modelo puntúa):</b> 2" in html


def test_una_corrida_sobre_el_circuito_entero_no_habla_de_vanos_marcados():
    reg = _registro(vanos=[], n_vanos=40)
    html = informe_html(reg, figuras_html="")
    assert "todo el circuito" in html
