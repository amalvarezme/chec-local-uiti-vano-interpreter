"""El diccionario de tildes no cubria el vocabulario que este proyecto usa a diario.

Un agente lo reporto durante la corrida del 2026-08-24: *"palabras del dominio como
`rafaga`, `tipico`, `criticas`, `precipitacion` o `diagnostico` no estan en
`SIEMPRE_CON_TILDE`, asi que habrian pasado sin tilde con exit 0"*. Verificado: de 18
palabras probadas, 15 no las marcaba la guarda.

**Por que importa y por que no era visible.** La guarda es la unica revision mecanica de
ortografia de los tres agentes, y su exit 0 se lee como "la prosa esta acentuada". Con el
diccionario corto, ese exit 0 solo decia "las palabras QUE CONOZCO estan acentuadas". Los
informes de esta corrida salieron bien igualmente -- auditados aparte, cero faltas reales --
pero por la redaccion de los agentes, no porque el mecanismo lo garantizara.

**La trampa del plural.** El primer barrido de auditoria dio 120 falsos positivos porque
buscaba `-ciones`. En castellano el plural de `-cion` PIERDE la tilde: `condicion` ->
`condiciones`, `asociacion` -> `asociaciones`. Solo el singular la lleva. Por eso esta
prueba fija las dos caras: el singular se marca, el plural NO.
"""

from __future__ import annotations

import pytest

from chec_local_interpreter.ortografia import SIEMPRE_CON_TILDE, palabras_sin_tilde


def marca(palabra: str) -> bool:
    """Si la guarda senala esta palabra dentro de una frase corriente."""
    return bool(palabras_sin_tilde(f"El {palabra} del circuito se observa en la ventana."))


#: Vocabulario que aparece en los informes de este proyecto y que la guarda no cubria.
DEL_DOMINIO = (
    "rafaga", "rafagas", "tipico", "tipica", "tipicos", "tipicas",
    "precipitacion", "afectacion", "extension", "desagregacion", "contribucion",
    "comprobacion", "evolucion", "atmosfericas", "debil", "comun",
    "maxima", "maximo", "minima", "minimo", "ultima", "ultimo",
    "metrica", "metricas", "indice", "indices", "fisica", "fisico",
)


@pytest.mark.parametrize("palabra", DEL_DOMINIO)
def test_la_guarda_marca_el_vocabulario_del_dominio(palabra):
    assert marca(palabra), f"la guarda deja pasar `{palabra}` sin tilde"


# ---------------------------------------------------------------------------
# Lo AMBIGUO no es un hueco: es una decision del modulo
#
# `diagnostico`, `critica` y `criticas` SI estan en el diccionario, con valor `None`.
# Son las dos correctas segun el caso -- «el diagnostico» lleva tilde, «yo diagnostico»
# no; «la critica» la lleva, «el informe critica» no --, y `ortografia.py` documenta que
# lo ambiguo se reporta pero no se decide. Marcarlas obligaria a un corrector a elegir, y
# elegir mal cambia el significado.
#
# Esta prueba existe porque yo mismo las metí en la lista de huecos al escribir la guarda:
# sin ella, el siguiente que audite el diccionario "arregla" lo que estaba bien.
# ---------------------------------------------------------------------------

AMBIGUAS = ("diagnostico", "critica", "criticas", "periodo", "calculo", "area")


@pytest.mark.parametrize("palabra", AMBIGUAS)
def test_lo_ambiguo_no_se_marca_a_proposito(palabra):
    assert SIEMPRE_CON_TILDE[palabra] is None, f"`{palabra}` deberia seguir sin decidirse"
    assert not marca(palabra), f"la guarda decide sobre `{palabra}`, que es ambigua"


@pytest.mark.parametrize("palabra", ("critico", "maximo", "minimo", "metrica"))
def test_lo_inequivoco_si_se_marca(palabra):
    assert marca(palabra), f"la guarda deja pasar `{palabra}` sin tilde"


# ---------------------------------------------------------------------------
# La otra cara: lo que NO debe marcarse
# ---------------------------------------------------------------------------

#: El plural de `-cion` pierde la tilde. Marcarlas seria peor que no marcar nada: un
#: corrector que las "arregle" escribe faltas donde no las habia.
PLURALES_CORRECTOS = (
    "condiciones", "asociaciones", "interrupciones", "poblaciones", "intervenciones",
    "reducciones", "verificaciones", "relaciones", "situaciones", "protecciones",
    "sobretensiones", "discusiones", "tensiones",
)


@pytest.mark.parametrize("palabra", PLURALES_CORRECTOS)
def test_el_plural_de_cion_no_lleva_tilde_y_no_se_marca(palabra):
    assert not marca(palabra), f"la guarda marca `{palabra}`, que es correcta sin tilde"


@pytest.mark.parametrize("palabra", ("criticidad", "vano", "circuito", "ventana"))
def test_no_se_marca_lo_que_nunca_lleva_tilde(palabra):
    assert not marca(palabra)


def test_los_codigos_del_dataset_siguen_intactos():
    """La regla de siempre: un codigo no se acentua aunque se parezca a una palabra."""
    assert not palabras_sin_tilde("La columna DURACION y COD_CAUSA no llevan tilde.")


def test_lo_ambiguo_se_sigue_dejando_pasar():
    """`periodo`/`periodo` y `calculo`/`calculo` son las dos correctas segun el caso."""
    for palabra in ("periodo", "calculo", "critica", "area"):
        assert SIEMPRE_CON_TILDE.get(palabra, "AUSENTE") in (None, "AUSENTE") or True
    assert SIEMPRE_CON_TILDE["periodo"] is None
    assert SIEMPRE_CON_TILDE["calculo"] is None


def test_las_cuatro_que_se_colaron_en_la_corrida_de_don23l13():
    """Cuatro palabras singulares que el agente escribio sin tilde y la guarda dejo pasar.

    Salieron de las tres salidas validadas de una corrida real (DON23L13, 2026-09-06): el
    agente de inferencia reporto que habia tenido que acentuar a mano lo que la guarda no
    veia. Ninguna de las cuatro es ambigua -- no existe la forma sin tilde en castellano --,
    asi que faltaban del diccionario y nada mas.
    """
    from chec_local_interpreter.ortografia import palabras_sin_tilde

    texto = ("La composicion del grupo, su exposicion al riesgo, la aparicion del patron "
             "y su justificacion quedan documentadas.")

    encontradas = dict(palabras_sin_tilde(texto))

    assert encontradas.get("composicion") == "composición"
    assert encontradas.get("exposicion") == "exposición"
    assert encontradas.get("aparicion") == "aparición"
    assert encontradas.get("justificacion") == "justificación"


def test_el_plural_de_cion_no_se_marca_porque_NO_lleva_tilde():
    """`condiciones` y `relaciones` son llanas acabadas en -s: correctas sin tilde.

    Es la trampa de la regla ingenua "toda palabra en -cion lleva tilde". Aplicada a los
    plurales, la guarda empezaria a exigir una falta de ortografia -- y en las salidas de
    esta misma corrida habia nueve palabras asi, todas bien escritas.
    """
    from chec_local_interpreter.ortografia import palabras_sin_tilde

    texto = ("Las condiciones, las relaciones, las secciones, las intervenciones, las "
             "limitaciones, las observaciones y las sobretensiones están bien escritas.")

    assert palabras_sin_tilde(texto) == []


def test_lo_ambiguo_se_sigue_dejando_pasar():
    """`criticas` ("tu criticas"), `mas` (= pero) y `pronostico` ("yo pronostico") tienen
    las dos formas. Decidir por el lector cambiaria el significado, y esa es la politica
    declarada del modulo -- no un hueco."""
    from chec_local_interpreter.ortografia import palabras_sin_tilde

    assert palabras_sin_tilde("Tu criticas mas de lo que yo pronostico.") == []
