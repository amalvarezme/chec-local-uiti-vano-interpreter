"""Como se construye cada `<li>` del informe por circuito.

Los agentes entregan PROSA; el informe la parte en items. Esa particion es de la capa
de render, no del modelo de lenguaje, asi que es aqui donde se puede exigir que cada
item se lea como una frase entera y empiece como empieza una frase.

Medido sobre los 12 informes de la corrida 20260820, antes de este arreglo:

* **87 de 1.153 items (7,5 %) empezaban en minuscula** -- `la`, `el`, `y`, `un`, `por`.
* **99 items terminaban en `;`**, que es la huella del mismo defecto: el separador
  partia tambien en punto y coma, y un punto y coma no cierra una frase. De ahi salian
  los trozos que empezaban por `y en los grupos Topologia...` o `aun asi, se trata de...`.

Las tildes NO estan aqui: `ortografia.py` ya las obliga en los tres agentes, y el mismo
barrido sobre esos 12 informes encontro CERO palabras sin tilde. Ese mecanismo ya existe
y funciona; duplicarlo aqui seria una segunda fuente de verdad.
"""

from __future__ import annotations

import pytest

from chec_local_interpreter.plotting import _lista_a_items, _texto_a_items


def items(html: str) -> list[str]:
    import re
    return re.findall(r"<li>(.*?)</li>", html, re.S)


class TestMayusculaInicial:
    def test_una_frase_suelta_empieza_en_mayuscula(self):
        assert items(_texto_a_items("la ventana pico es V9."))[0].startswith("La ")

    def test_cada_item_de_una_lista_empieza_en_mayuscula(self):
        html = _lista_a_items(["primer hallazgo.", "segundo hallazgo."])
        assert [i[0] for i in items(html)] == ["P", "S"]

    def test_no_toca_lo_que_ya_venia_en_mayuscula(self):
        assert items(_texto_a_items("La ventana pico es V9."))[0].startswith("La ")

    @pytest.mark.parametrize("codigo", ["uiti_acumulado", "n_obs", "x1_y1"])
    def test_no_capitaliza_un_codigo_del_dataset(self, codigo):
        """`UITI_acumulado` no existe: es el nombre de una columna.

        La regla es la misma de `ortografia.py` -- un `_` o un digito delatan al
        codigo --, y por eso no hace falta mantener una lista de excepciones.
        """
        html = _texto_a_items(f"{codigo} sube en la ventana V9.")
        assert items(html)[0].startswith(codigo)

    def test_no_capitaliza_un_numero(self):
        assert items(_texto_a_items("45 eventos frente a 31 de la red."))[0].startswith("45")


class TestElPuntoYComaNoCierraUnaFrase:
    def test_no_parte_en_punto_y_coma(self):
        """Partir ahi produce un trozo que no es una frase.

        Este es el caso real que salio en BOA23L14: la oracion se partia en el `;` y el
        segundo trozo empezaba por `y en los grupos Topologia y Activos...`.
        """
        texto = ("En el grupo Evento/Impacto destacan DURACION y TOT_USU; "
                 "y en los grupos Topologia y Activos aparece PORC_APORTE_VANO.")
        assert len(items(_texto_a_items(texto))) == 1

    def test_si_parte_en_punto(self):
        """Con frases largas: por debajo de 150 caracteres se agrupan a proposito."""
        larga = "Este circuito acumula eventos por encima del promedio de la red " * 3
        assert len(items(_texto_a_items(f"{larga.strip()}. {larga.strip()}."))) == 2

    def test_ningun_item_termina_en_punto_y_coma(self):
        texto = "Una cosa; otra cosa; una tercera. Y una frase aparte."
        assert not [i for i in items(_texto_a_items(texto)) if i.endswith(";")]


class TestLoQueNoCambia:
    def test_el_texto_vacio_no_produce_lista(self):
        assert _texto_a_items("") == ""
        assert _lista_a_items([]) == ""

    def test_se_sigue_respetando_el_tope_de_items(self):
        larga = "Este circuito acumula eventos por encima del promedio de la red " * 3
        texto = ". ".join([larga.strip()] * 4) + "."
        assert len(items(_texto_a_items(texto, max_items=2))) == 2

    def test_las_frases_cortas_se_siguen_agrupando(self):
        """No es un defecto: un item de tres palabras no se lee como un hallazgo.

        El agrupador junta frases hasta unos 150 caracteres, que son las dos lineas
        visuales del contenedor. Esta prueba fija esa conducta para que el arreglo del
        punto y coma no se lleve por delante lo que si estaba bien.
        """
        assert len(items(_texto_a_items("Una. Dos. Tres. Cuatro."))) == 1

    def test_se_sigue_escapando_el_html(self):
        assert "&lt;script&gt;" in _lista_a_items(["<script>alert(1)</script>"])


# ---------------------------------------------------------------------------
# La otra mitad del problema: la REDUNDANCIA, que no se arregla en el render
#
# El informe abre con cuatro bloques seguidos -- Resumen Ejecutivo, Hallazgos,
# Caracterizacion del Circuito y Sintesis del Periodo -- y los cuatro salen del MISMO
# agente, `historical`. Su contrato decia que campos entregar, pero no que decia cada
# uno que no dijeran los otros, y el agente respondia a los cuatro con los mismos
# hechos redactados de otra manera.
#
# Medido sobre los 12 informes de la corrida 20260820: 11 pares de items de secciones
# distintas con mas del 60 % de solapamiento, y el patron dominante era
# `Resumen Ejecutivo` repitiendo `Caracterizacion del Circuito`:
#
#     A: CHI23L18 aparece ... como circuito de criticidad Riesgo Medio-Alto, en la
#        posicion 11 de 208 circuitos de la flota, con 45 eventos frente a ...
#     B: CHI23L18 se caracteriza ... como circuito de criticidad Riesgo Medio-Alto,
#        ubicado en la posicion 11 dentro de una flota de 208 circuitos, ...
#
# Deduplicar eso en el render seria tarde y a ciegas: son parrafos distintos con el
# mismo contenido, y borrar uno deja la seccion vacia. El reparto tiene que estar en el
# contrato, que es donde se decide QUE escribe cada campo.
# ---------------------------------------------------------------------------

from pathlib import Path

CONTRATO = (Path(__file__).resolve().parents[1]
            / ".claude" / "skills" / "historical" / "prompt" / "07_base_output_contract.md")

CAMPOS_NARRATIVOS = (
    "executive_summary",
    "key_findings",
    "circuit_characterization",
    "period_synthesis",
)


class TestElContratoRepartElTrabajo:
    def test_el_contrato_existe(self):
        assert CONTRATO.is_file(), CONTRATO

    def test_hay_una_seccion_que_reparte_los_cuatro_campos(self):
        texto = CONTRATO.read_text(encoding="utf-8")
        assert "## Reparto entre los campos narrativos" in texto

    @pytest.mark.parametrize("campo", CAMPOS_NARRATIVOS)
    def test_el_reparto_nombra_cada_campo(self, campo):
        texto = CONTRATO.read_text(encoding="utf-8")
        reparto = texto.split("## Reparto entre los campos narrativos", 1)[-1]
        reparto = reparto.split("\n## ", 1)[0]
        assert campo in reparto, f"el reparto no dice que escribe `{campo}`"

    def test_el_reparto_prohibe_repetir_un_hecho_ya_dicho(self):
        texto = CONTRATO.read_text(encoding="utf-8")
        reparto = texto.split("## Reparto entre los campos narrativos", 1)[-1]
        reparto = reparto.split("\n## ", 1)[0].lower()
        assert "no repitas" in reparto or "no vuelvas a" in reparto
