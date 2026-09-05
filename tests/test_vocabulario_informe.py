"""El vocabulario del informe, normalizado al pintar.

El revisor pidio dos cambios de palabra: "circuitos de la flota" pasa a "circuitos
totales", y "ventana pico" y "ventana de mayor impacto" dejan de leerse como dos cosas
distintas cuando son la misma.

Se hace al RENDER, igual que `nombrar_prosa_en_datos`, y por la misma razon: el
`.out.json` es el artefacto que el propio `validate` del agente acepto, y reescribirlo
lo separaria de su validacion. La ventaja practica es que las quince corridas ya
archivadas se vuelven a pintar con el vocabulario nuevo sin volver a gastar un token.
"""

from __future__ import annotations

from chec_local_interpreter.vocabulario_informe import (
    normalizar_vocabulario,
    normalizar_vocabulario_en_datos,
)


class TestFlota:
    def test_circuitos_de_la_flota_pasa_a_circuitos_totales(self):
        texto = "DON23L13 ocupa la posición 1 entre los 208 circuitos de la flota."
        assert "circuitos totales" in normalizar_vocabulario(texto)
        assert "flota" not in normalizar_vocabulario(texto)

    def test_una_flota_de_doscientos_ocho_pasa_a_un_total_de(self):
        texto = "en la posición 1 de una flota de 208, con 235 eventos"
        salida = normalizar_vocabulario(texto)
        assert "de un total de 208" in salida
        assert "flota" not in salida

    def test_dentro_de_su_flota_pasa_a_dentro_del_total_de_circuitos(self):
        texto = "de magnitud atípica dentro de su flota: 235 eventos"
        salida = normalizar_vocabulario(texto)
        assert "dentro del total de circuitos" in salida
        assert "flota" not in salida

    def test_la_forma_capitalizada_conserva_la_mayuscula(self):
        assert normalizar_vocabulario("La flota completa se compara.").startswith(
            "El total de circuitos"
        )


class TestVentanaPico:
    def test_ventana_pico_se_nombra_por_su_aporte(self):
        """El revisor no entendia la diferencia con la ventana de mayor impacto.

        No hay diferencia: las dos son la ventana con mas UITI acumulado. El informe
        se queda con UN nombre para que no parezca que son dos criterios.
        """
        salida = normalizar_vocabulario("la ventana pico del período")
        assert "ventana de mayor aporte UITI" in salida

    def test_ventana_de_mayor_impacto_usa_el_mismo_nombre(self):
        a = normalizar_vocabulario("la ventana pico del período")
        b = normalizar_vocabulario("la ventana de mayor impacto del período")
        assert a == b

    def test_un_pico_de_la_serie_no_es_una_ventana_y_no_se_toca(self):
        """`pico` suelto describe la forma de la serie y es castellano correcto.

        La confusion que el revisor senalo estaba en el NOMBRE de una ventana, no en
        la palabra. Una regla sobre `pico` a secas deja frases como "un pico temprano
        en V2" ilegibles sin arreglar nada.
        """
        texto = "La serie describe un pico temprano en V2 y un valle en V4"
        assert normalizar_vocabulario(texto) == texto


class TestRecorridoDeDatos:
    def test_recorre_diccionarios_y_listas(self):
        datos = {"executive_summary": ["entre los 208 circuitos de la flota"]}
        salida = normalizar_vocabulario_en_datos(datos)
        assert salida["executive_summary"] == ["entre los 208 circuitos totales"]

    def test_las_claves_de_identidad_quedan_intactas(self):
        """`circuito` lleva un codigo, no prosa: tocarlo rompe a su consumidor.

        Se reutiliza la misma lista que ya protege `nombrar_prosa_en_datos`, para que
        las dos pasadas no puedan divergir sobre que es prosa y que es identidad.
        """
        datos = {"circuito": "FLOTA23L01", "run_dir": "/tmp/flota/pico"}
        salida = normalizar_vocabulario_en_datos(datos)
        assert salida["circuito"] == "FLOTA23L01"
        assert salida["run_dir"] == "/tmp/flota/pico"

    def test_no_muta_la_entrada(self):
        datos = {"texto": "los circuitos de la flota"}
        normalizar_vocabulario_en_datos(datos)
        assert datos["texto"] == "los circuitos de la flota"

    def test_los_valores_que_no_son_texto_pasan_tal_cual(self):
        datos = {"n": 3, "ok": True, "nada": None}
        assert normalizar_vocabulario_en_datos(datos) == datos


class TestNoDestruye:
    def test_una_palabra_que_contiene_flota_no_se_toca(self):
        """`flotante` contiene `flota`. Una regla sin frontera de palabra lo parte."""
        assert normalizar_vocabulario("el neutro flotante") == "el neutro flotante"

    def test_texto_vacio_o_nulo_no_revienta(self):
        assert normalizar_vocabulario("") == ""
        assert normalizar_vocabulario(None) == ""
