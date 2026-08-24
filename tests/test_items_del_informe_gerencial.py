"""Los items del informe GERENCIAL, que los escribe otro modulo.

El arreglo de `plotting._texto_a_items` no llega aqui: el informe gerencial lo renderiza
`informe_gerencial_contract`, con sus propios productores de `<li>`. Medido sobre el
informe de la flota del 2026-08-24, 130 items: **10 empezaban en minuscula y 7 terminaban
en punto y coma**.

**Por que el arreglo NO es el mismo que en `plotting`.** Alli el corte por `;` era el
defecto, porque partia una frase corriente en trozos. Aqui es DELIBERADO y esta
documentado en `_hypothesis_clauses`: las hipotesis de causa de estos agentes son una
enumeracion larga separada por punto y coma, y no cortarlas devuelve el muro de texto que
ese codigo vino a resolver.

**Y por eso las subvinetas de la hipotesis son la UNICA excepcion a la mayuscula.** Se
intento capitalizarlas y rompio dos cosas a la vez: la garantia de que reunirlas
reproduce el original exacto, y el propio castellano -- «y (2) una exposicion...» quedaba
como «Y (2) una exposicion...». Van verbatim. Lo que si se capitaliza es todo lo demas:
los items sueltos del anexo y los rotulos de causa y estrategia.

Los otros cuatro items en minuscula eran los rotulos de causa compartida
(`topologico/recurrencia de vanos`), que son CLAVES de agrupacion en minuscula a
proposito. La clave no se toca; lo que se capitaliza es lo que se DIBUJA.
"""

from __future__ import annotations

import re

import pytest

from chec_local_interpreter.informe_gerencial_contract import (_annex_html,
                                                               _hypothesis_clauses)


def items(html: str) -> list[str]:
    return [re.sub(r"<[^>]+>", "", m).strip()
            for m in re.findall(r"<li[^>]*>(.*?)</li>", html, re.S)]


HIPOTESIS = ("La causa probable combina vegetacion y clima; en el modo Proteccion y "
             "Topologia, los vanos protegidos por el equipo aportan; y en el modo "
             "Evento, la duracion de la interrupcion acompana.")


class TestLasClausulasDeLaHipotesis:
    """La UNICA excepcion a "todo item empieza con mayuscula", y por que.

    Estas subvinetas no son items independientes: son clausulas de UNA frase, partidas
    para que se lean. El modulo garantiza -- y `test_annex_hypothesis_split_into_subitems`
    lo exige -- que reunirlas reproduce el original exacto, palabra por palabra.

    Capitalizarlas rompe esa garantia y ademas escribe PEOR castellano. La clausula real
    de la corrida del 2026-08-24 era «y (2) una exposicion topologica recurrente...», y
    capitalizada quedaba «Y (2) una exposicion...». La mayuscula va donde empieza una
    frase, no donde continua una enumeracion.
    """

    def test_se_siguen_partiendo_por_punto_y_coma(self):
        """El corte es deliberado: sin el, la hipotesis es un parrafo ilegible en una celda."""
        assert len(_hypothesis_clauses(HIPOTESIS)) >= 3

    def test_las_clausulas_van_VERBATIM(self):
        """Reunirlas reproduce el original: ni mayuscula ni `;` retirado."""
        original = " ".join(HIPOTESIS.split())
        assert " ".join(_hypothesis_clauses(HIPOTESIS)) == original

    def test_una_continuacion_conserva_su_minuscula(self):
        """La aguja concreta: una clausula que empieza por `y` NO se capitaliza."""
        clausulas = _hypothesis_clauses(HIPOTESIS)
        continuaciones = [c for c in clausulas if c.lower().startswith("y ")]
        assert continuaciones, "el caso de prueba deberia traer una continuacion"
        assert all(c[0].islower() for c in continuaciones)

    def test_no_se_pierde_ni_se_trunca_texto(self):
        juntas = " ".join(_hypothesis_clauses(HIPOTESIS)).lower()
        for palabra in ("vegetacion", "proteccion", "topologia", "duracion", "acompana"):
            assert palabra in juntas


class TestLosItemsDelAnexo:
    def test_un_item_suelto_empieza_en_mayuscula(self):
        html = _annex_html([{"circuito": "AAA11L11",
                             "resumen": ["primer hallazgo del circuito."]}])
        sueltos = [i for i in items(html) if "hallazgo" in i]
        assert sueltos and sueltos[0].startswith("Primer")

    def test_las_subvinetas_de_la_hipotesis_van_verbatim(self):
        """Contrapartida de `TestLasClausulasDeLaHipotesis`: el render tampoco las toca."""
        html = _annex_html([{
            "circuito": "AAA11L11",
            "resumen": [{"label": "Hipótesis de causa",
                         "items": ["en el modo Entorno, la vegetacion aporta",
                                   "y en el modo Evento, la duracion acompana"]}],
        }])
        # Solo la sublista: el `<li>` externo engloba el rotulo y la anidada.
        anidada = re.search(r"<ul class='annex-subitems'>(.*?)</ul>", html, re.S)
        assert anidada, "no se rendearon las subvinetas"
        sub = items(anidada.group(1))
        assert sub == ["en el modo Entorno, la vegetacion aporta",
                       "y en el modo Evento, la duracion acompana"]
