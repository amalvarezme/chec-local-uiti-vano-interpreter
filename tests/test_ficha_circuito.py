"""La ficha de cabecera del informe por circuito.

El revisor pidio abrir el informe con los valores generales del circuito -- aporte
UITI, vanos probables de causa de falla, longitud total/urbana/rural y numero de
transformadores -- y con la clasificacion de criticidad en TABLA, no solo en la barra
de 208 rotulos de 8 px que nadie puede leer.

Todo sale de fuentes que el informe YA tiene: `ranking_circuitos` para lo comparativo
y los shapefiles de `data/GEO` para lo fisico. Ningun numero nuevo se inventa aqui.
"""

from __future__ import annotations

import pandas as pd
import pytest

from chec_local_interpreter.ficha_circuito import (
    ficha_general,
    medidas_fisicas,
    tabla_clasificacion_html,
    tabla_ficha_html,
    razones_de_estudio,
    tabla_ventanas_html,
    vanos_de_mayor_impacto,
)


@pytest.fixture
def flota():
    """Tres circuitos con vanos suficientes para que el ranking agrupe."""
    filas = []
    for circuito, vanos, golpes in (("C1", 12, 5), ("C2", 6, 2), ("C3", 3, 1)):
        for v in range(vanos):
            for g in range(golpes):
                filas.append({
                    "CIRCUITO": circuito,
                    "FID_VANO": f"{circuito}-V{v}",
                    "UITI_VANO": 10.0 * (v + 1) + g,
                    "FECHA": f"2026-01-{(g % 28) + 1:02d}",
                })
    return pd.DataFrame(filas)


# --------------------------------------------------------------------- ficha general


def test_la_ficha_trae_el_puesto_y_el_total_de_circuitos(flota):
    ficha = ficha_general(flota, "C1")
    assert ficha["circuitos_totales"] == 3
    assert 1 <= ficha["posicion"] <= 3
    assert ficha["rango"].startswith("Riesgo ")


def test_la_ficha_separa_el_uiti_del_circuito_del_uiti_de_todos_los_circuitos(flota):
    ficha = ficha_general(flota, "C1")
    assert ficha["uiti_circuito"] > 0
    assert ficha["uiti_total"] >= ficha["uiti_circuito"]
    # El aporte del circuito al total, que es la lectura que el revisor pidio en el
    # resumen ejecutivo: "UiTi acumulado del circuito" contra "UiTi acumulado total".
    assert 0 < ficha["aporte_uiti_pct"] <= 100


def test_vanos_probables_de_causa_de_falla_no_es_el_conteo_de_eventos(flota):
    """El revisor pidio llamar a las cosas por su nombre.

    Un vano probable de causa de falla es un VANO que aparece en registros de
    interrupcion. `registros_vano_evento` cuenta FILAS: el mismo vano golpeado cinco
    veces son cinco registros y un solo vano. Confundirlos es como el informe termina
    diciendo que un circuito tiene 235 vanos cuando tiene 12.
    """
    ficha = ficha_general(flota, "C1")
    assert ficha["vanos_probables"] == 12
    assert ficha["registros_vano_evento"] == 60
    assert ficha["vanos_probables"] != ficha["registros_vano_evento"]


def test_la_ficha_de_un_circuito_ausente_no_revienta(flota):
    assert ficha_general(flota, "NO-EXISTE") == {}


def test_la_ficha_sin_datos_devuelve_vacio():
    assert ficha_general(pd.DataFrame(), "C1") == {}


# ------------------------------------------------------------------- medidas fisicas


def test_las_medidas_fisicas_faltantes_devuelven_vacio_en_vez_de_romper():
    """Sin `data/GEO` el informe pierde la longitud, no la cabecera entera."""
    assert medidas_fisicas("CIRCUITO-QUE-NO-ESTA-EN-NINGUN-SHAPEFILE") == {}


# ------------------------------------------------------------------------ tabla ficha


def test_la_tabla_de_la_ficha_nombra_los_vanos_probables_de_causa_de_falla(flota):
    html = tabla_ficha_html(ficha_general(flota, "C1"))
    assert "Vanos probables de causa de falla" in html
    assert "UITI acumulado del circuito" in html
    assert "<table" in html


def test_la_tabla_de_la_ficha_vacia_no_dibuja_nada():
    assert tabla_ficha_html({}) == ""


# ----------------------------------------------------------------- tabla clasificacion


def test_la_tabla_de_clasificacion_numera_la_ubicacion_de_cada_circuito(flota):
    html = tabla_clasificacion_html(flota, "C1")
    # El numero de ubicacion, que es lo que el revisor pidio ver en la tabla Y en la
    # grafica para poder cruzar las dos.
    assert "Ubicación" in html
    for circuito in ("C1", "C2", "C3"):
        assert circuito in html


def test_la_tabla_de_clasificacion_marca_el_circuito_del_informe(flota):
    html = tabla_clasificacion_html(flota, "C2")
    assert "fila-destacada" in html


def test_la_tabla_de_clasificacion_sin_datos_no_dibuja_nada():
    assert tabla_clasificacion_html(pd.DataFrame(), "C1") == ""


# --------------------------------------------------------------------- tabla ventanas


def test_la_tabla_de_ventanas_trae_fechas_uiti_registros_y_vanos(flota):
    html = tabla_ventanas_html(flota, "C1")
    for encabezado in ("Ventana", "Desde", "Hasta", "UITI", "Registros", "Vanos"):
        assert encabezado in html


def test_la_tabla_de_ventanas_advierte_que_no_son_aditivas(flota):
    """Las once ventanas se traslapan quince dias: sumarlas cuenta dos veces.

    Es el error que ya cambio el top 15 de 74 circuitos una vez. La advertencia va
    PEGADA a la tabla, no en un parrafo tres secciones mas arriba.
    """
    html = tabla_ventanas_html(flota, "C1")
    assert "no son aditivos" in html or "no se suman" in html


class TestRazonesDeEstudio:
    """Por que entro cada ventana al estudio, con los MISMOS tres criterios que la
    eligieron: la ultima, la de mayor UITI y la de mas vanos tocados.

    La tabla marcaba "estudiada a fondo" y nada mas, asi que el lector veia tres ventanas
    señaladas sin saber por que esas tres. Reconstruir el motivo aqui es honesto porque
    se hace con la misma regla y sobre los mismos numeros que uso el selector.

    Ojo con el superlativo: el selector aplica cada criterio sobre LO QUE QUEDA, no sobre
    la serie entera, asi que el ganador de un criterio puede no ser su maximo global. Ver
    `TestRazonesNoAfirmanUnMaximoGlobalFalso` mas abajo.
    """

    def _reg(self, w, uv, vanos, n=1):
        return {"w": w, "uv": uv, "vanos": vanos, "n": n}

    @property
    def _serie(self):
        # V2 concentra el UITI en pocos vanos; V1 lo reparte entre muchos; V5 es la
        # ultima. Los tres criterios caen en ventanas DISTINTAS a proposito: si
        # coincidieran, cualquier asignacion pasaria la prueba.
        return [
            self._reg("V1", 40.0, 30),    # mas vanos
            self._reg("V2", 100.0, 5),    # mas UITI
            self._reg("V3", 10.0, 4),
            self._reg("V4", 0.0, 0),      # sin eventos
            self._reg("V5", 8.0, 6),      # la ultima CON eventos
        ]

    def test_cada_criterio_nombra_su_ventana(self):
        razones = razones_de_estudio(self._serie, ("V1", "V2", "V5"))

        assert "última" in razones["V5"], razones["V5"]
        # La razon de la ultima ES una pregunta -- la que esa ventana contesta -- y va
        # con sus dos signos, igual que los encabezados del informe.
        assert "¿cómo está el circuito hoy?" in razones["V5"], razones["V5"]
        assert "UITI" in razones["V2"], razones["V2"]
        assert "vanos" in razones["V1"], razones["V1"]

    def test_las_tres_razones_son_distintas(self):
        """Tres ventanas con el mismo texto no explican nada."""
        razones = razones_de_estudio(self._serie, ("V1", "V2", "V5"))

        assert len(set(razones.values())) == 3

    def test_una_ventana_no_estudiada_no_recibe_razon(self):
        razones = razones_de_estudio(self._serie, ("V1", "V2", "V5"))

        assert "V3" not in razones and "V4" not in razones

    def test_la_ultima_se_mide_sobre_las_ventanas_CON_eventos(self):
        """V4 va despues de V3 pero no registro nada. La ultima del circuito es la ultima
        en la que hubo algo, que es la que el selector toma."""
        serie = self._serie + [self._reg("V6", 0.0, 0)]

        razones = razones_de_estudio(serie, ("V5",))

        assert "última" in razones["V5"]

    def test_una_ventana_que_gana_dos_criterios_no_se_cuenta_dos_veces(self):
        """Si la de mas UITI es tambien la de mas vanos, el informe estudia DOS ventanas
        y la tercera no existe. La razon de la segunda tiene que ser una sola."""
        serie = [self._reg("V1", 100.0, 30), self._reg("V2", 5.0, 2)]

        razones = razones_de_estudio(serie, ("V1", "V2"))

        assert len(set(razones.values())) == 2
        assert "última" in razones["V2"]

    def test_una_ventana_estudiada_sin_criterio_lo_dice_sin_inventar(self):
        """Una corrida vieja pudo estudiar otras ventanas. Adjudicarle un criterio que no
        la eligio seria inventar el motivo; se marca y se deja."""
        razones = razones_de_estudio(self._serie, ("V1", "V2", "V3", "V5"))

        assert razones["V3"] and "UITI" not in razones["V3"]
        assert "vanos" not in razones["V3"] and "última" not in razones["V3"]

    def test_sin_ventanas_estudiadas_no_devuelve_nada(self):
        assert razones_de_estudio(self._serie, ()) == {}


def test_la_tabla_de_ventanas_dice_por_que_se_estudio_cada_una(flota):
    """La columna nueva de la seccion 2.2: el motivo, no una marca."""
    html = tabla_ventanas_html(flota, "C1", estudiadas=("V1",))

    assert "¿Por qué se estudió?" in html


def test_la_tabla_de_ventanas_sin_datos_no_dibuja_nada():
    assert tabla_ventanas_html(pd.DataFrame(), "C1") == ""


# ---------------------------------------------------------------------- vanos impacto


def test_los_vanos_de_mayor_impacto_separan_uiti_de_apariciones(flota):
    """Dos criterios distintos y su interseccion, que es lo que el revisor pidio.

    Un vano puede concentrar UITI en una sola salida grande y otro puede aparecer en
    todas las ventanas con poco. Los que estan en las DOS listas son los que no
    dependen de cual criterio se eligio.
    """
    resultado = vanos_de_mayor_impacto(flota, "C1", tope=5)
    assert len(resultado["por_uiti"]) == 5
    assert len(resultado["por_apariciones"]) == 5
    assert set(resultado["coincidentes"]) <= (
        {v["fid"] for v in resultado["por_uiti"]}
        & {v["fid"] for v in resultado["por_apariciones"]}
    )


def test_los_vanos_de_mayor_impacto_sin_datos_devuelven_listas_vacias():
    resultado = vanos_de_mayor_impacto(pd.DataFrame(), "C1")
    assert resultado == {"por_uiti": [], "por_apariciones": [], "coincidentes": []}


# --------------------------------------------------------------------- afectacion


from chec_local_interpreter.ficha_circuito import tipo_de_afectacion  # noqa: E402


class TestTipoDeAfectacion:
    """Comentario 18, subseccion 2.1: sostenida o puntual.

    Se CALCULA y no se le pide al agente. Es un umbral sobre la serie por ventana --
    en cuantas hubo actividad y que fraccion del UITI se lleva la mayor --, y un modelo
    contestando eso sobre los mismos numeros puede dar una respuesta distinta en cada
    corrida sin que nada haya cambiado.
    """

    def _serie(self, valores):
        return [{"w": f"V{i+1}", "periodo": "", "uv": v, "n": 10, "vanos": 5}
                for i, v in enumerate(valores)]

    def test_actividad_repartida_en_todas_las_ventanas_es_sostenida(self):
        resultado = tipo_de_afectacion(self._serie([100.0] * 11))
        assert resultado["tipo"] == "sostenida"
        assert resultado["ventanas_con_actividad"] == 11

    def test_todo_el_uiti_en_una_ventana_es_puntual(self):
        resultado = tipo_de_afectacion(self._serie([0.0] * 10 + [1000.0]))
        assert resultado["tipo"] == "puntual"
        assert resultado["ventanas_con_actividad"] == 1

    def test_la_ventana_de_mayor_aporte_viene_nombrada(self):
        resultado = tipo_de_afectacion(self._serie([10.0, 900.0, 10.0]))
        assert resultado["ventana_pico"] == "V2"
        assert resultado["pct_ventana_pico"] > 90

    def test_una_serie_vacia_no_afirma_nada(self):
        """Sin datos no hay tipo. Devolver "puntual" por defecto seria inventar."""
        assert tipo_de_afectacion([]) == {}
        assert tipo_de_afectacion([{"w": "V1", "uv": 0.0}]) == {}

    def test_el_bloque_html_nombra_las_dos_cifras_que_lo_sostienen(self):
        """Un veredicto sin sus numeros al lado no se puede discutir."""
        from chec_local_interpreter.ficha_circuito import afectacion_html

        html = afectacion_html(tipo_de_afectacion(self._serie([100.0] * 11)))
        assert "sostenida" in html
        assert "11" in html          # ventanas con actividad
        assert "%" in html           # fraccion de la ventana mayor

    def test_sin_afectacion_no_se_dibuja_el_bloque(self):
        from chec_local_interpreter.ficha_circuito import afectacion_html

        assert afectacion_html({}) == ""


class TestTablaClasificacionConVariosCircuitos:
    """El informe gerencial resalta un GRUPO, no un circuito.

    `plot_ranking_circuitos` ya admitia las dos formas -- un nombre o una lista -- y la
    tabla que la acompana tenia que admitir las mismas, o las dos piezas marcarian
    conjuntos distintos sobre la misma figura.
    """

    def test_una_lista_marca_todos_sus_circuitos(self, flota):
        html = tabla_clasificacion_html(flota, ["C1", "C3"])
        assert html.count("fila-destacada") >= 4  # dos filas, en la tabla corta y larga

    def test_un_nombre_suelto_sigue_funcionando(self, flota):
        html = tabla_clasificacion_html(flota, "C1")
        assert "fila-destacada" in html

    def test_una_lista_vacia_no_marca_nada(self, flota):
        html = tabla_clasificacion_html(flota, [])
        assert "fila-destacada" not in html


class TestRazonesNoAfirmanUnMaximoGlobalFalso:
    """Los criterios se aplican SOBRE LO QUE QUEDA, no sobre las once ventanas.

    `razones_de_estudio` se escribio creyendo lo contrario -- su propio docstring decia
    que "el selector elige el maximo GLOBAL de cada criterio" -- y por eso rotulaba al
    ganador con un superlativo absoluto. Medido en HER23L16: la tabla llamaba a V10 "el
    episodio mas extendido del periodo" con 258 vanos, teniendo V11 (275) y V9 (267) dos
    filas mas arriba en la MISMA tabla. El lector compara la columna y la explicacion se
    le cae.

    La ultima ventana entra siempre y se lleva su etiqueta antes que nadie, asi que basta
    con que la ultima gane un criterio para que el rotulo de ese criterio caiga en una
    ventana que no es el maximo de la serie.
    """

    def _reg(self, w, uv, vanos, n=1):
        return {"w": w, "uv": uv, "vanos": vanos, "n": n}

    @property
    def _serie_her23l16(self):
        # Los numeros reales de HER23L16 en la corrida del 2026-09-06: la ultima ventana
        # es ademas la de mas vanos de todo el periodo.
        return [
            self._reg("V8", 135657.31, 197),
            self._reg("V9", 208852.53, 267),   # mas UITI de todas
            self._reg("V10", 76246.26, 258),   # tercera en vanos, no primera
            self._reg("V11", 88325.00, 275),   # la ultima, y la mas ancha de todas
        ]

    def test_el_rotulo_de_vanos_no_dice_maximo_del_periodo_cuando_no_lo_es(self):
        razones = razones_de_estudio(self._serie_her23l16, ("V9", "V10", "V11"))

        assert "restantes" in razones["V10"], razones["V10"]
        assert "del período" not in razones["V10"], razones["V10"]

    def test_el_rotulo_de_uiti_no_dice_maximo_del_periodo_cuando_no_lo_es(self):
        """Mismo defecto en el primer criterio: si la ultima ventana es ademas la de mas
        UITI, el rotulo de UITI cae en la segunda y no en el maximo de la serie."""
        serie = [
            self._reg("V1", 50.0, 30),
            self._reg("V2", 40.0, 10),
            self._reg("V3", 100.0, 12),   # la ultima, y el UITI mas alto de todas
        ]

        razones = razones_de_estudio(serie, ("V1", "V2", "V3"))

        assert "última" in razones["V3"], razones["V3"]
        assert "restantes" in razones["V2"], razones["V2"]

    def test_cuando_si_es_el_maximo_de_la_serie_lo_dice_sin_rodeos(self):
        """La salvedad solo aparece cuando hace falta: rotular de relativo un maximo real
        le quita fuerza a la unica lectura que la tabla si sostiene."""
        serie = [
            self._reg("V1", 100.0, 12),   # mas UITI de todas
            self._reg("V2", 10.0, 30),    # mas vanos de todas
            self._reg("V3", 8.0, 5),      # la ultima
        ]

        razones = razones_de_estudio(serie, ("V1", "V2", "V3"))

        assert "restantes" not in razones["V1"], razones["V1"]
        assert "restantes" not in razones["V2"], razones["V2"]
        assert "del período" in razones["V1"] and "del período" in razones["V2"]
