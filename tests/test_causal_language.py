"""Pin the shared causal-language guard's matching behavior.

Broadens the pilot's bare `\\bcausa\\b` check (pilot Known Limitation #3) to
also catch plural and adjective forms, while still never flagging unrelated
Spanish words that merely contain "causa" as a substring (e.g. "encausar").
"""

from __future__ import annotations

from chec_local_interpreter.causal_language import find_causal_language


def test_finds_bare_singular_noun():
    assert find_causal_language("La vegetación es la causa directa del evento.")


def test_finds_plural_noun():
    assert find_causal_language("Estas son las causas probables del comportamiento.")


def test_finds_adjective_singular_form():
    assert find_causal_language("Existe una relación causal entre las variables.")


def test_finds_adjective_plural_form():
    assert find_causal_language("Los factores causales fueron identificados.")


def test_finds_causante_and_causantes():
    assert find_causal_language("El agente causante del evento fue identificado.")
    assert find_causal_language("Los agentes causantes del evento fueron identificados.")


def test_finds_causada_and_causadas_and_causado_and_causados():
    assert find_causal_language("La falla fue causada por sobretensión.")
    assert find_causal_language("Las fallas fueron causadas por sobretensión.")
    assert find_causal_language("El evento fue causado por sobretensión.")
    assert find_causal_language("Los eventos fueron causados por sobretensión.")


def test_finds_causalidad_noun_and_plural():
    assert find_causal_language("El modelo demuestra causalidad entre las variables.")
    assert find_causal_language("Existen causalidades múltiples en el sistema.")


def test_finds_causo_and_causo_with_accent():
    assert find_causal_language("El evento causó una interrupción del servicio.")
    assert find_causal_language("el evento causo una interrupcion del servicio")


def test_finds_known_phrases():
    assert find_causal_language("El análisis demuestra causalidad entre ambas series.")
    assert find_causal_language("Este resultado prueba causal del comportamiento.")


def test_does_not_flag_unrelated_word_encausar():
    matches = find_causal_language("El equipo procederá a encausar el proceso operativo.")
    assert matches == []


def test_does_not_flag_empty_or_none_text():
    assert find_causal_language("") == []
    assert find_causal_language(None) == []


def test_returns_the_offending_terms():
    matches = find_causal_language("La causa principal y las causas secundarias.")
    assert "causa" in [m.lower() for m in matches]
    assert "causas" in [m.lower() for m in matches]
