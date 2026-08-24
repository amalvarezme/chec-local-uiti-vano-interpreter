"""El SKILL.md de `inference` documentaba una forma que su propio esquema rechaza.

Dos agentes distintos lo reportaron por su cuenta durante la corrida del 2026-08-24, y los
dos siguieron el esquema en vez del SKILL. Tenian razon:

* `hipotesis_modelo_predictivo` estaba documentado como `{periodo_completo, puntos_criticos}`
  y el esquema exige `{ventanas_estudiadas, plan_de_intervencion}`;
* el enum de `rule` decia `02_circuit_scenario_interpreter` y el valido es
  `02_window_scenario_interpreter` -- que ademas es el nombre real del archivo en
  `.claude/skills/inference/prompt/`, asi que el SKILL citaba una ruta inexistente.

`tests/test_prompt_schema_parity.py` ya vigila los PLAYBOOKS (`prompt/*.md`), que son lo que
se ensambla en el bundle. El SKILL.md es otra superficie -- la que lee el agente para saber
que hacer -- y quedaba fuera de esa guarda. Un agente que se fie de el escribe una respuesta
que `validate` tumba.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SKILL = RAIZ / ".claude" / "skills" / "inference" / "SKILL.md"
ESQUEMA = RAIZ / "src" / "chec_local_interpreter" / "prompt_assets" / "inference.output_schema.json"
PLAYBOOKS = RAIZ / ".claude" / "skills" / "inference" / "prompt"


@pytest.fixture(scope="module")
def texto():
    return SKILL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def esquema():
    return json.loads(ESQUEMA.read_text(encoding="utf-8"))


def _linea_de_la_hipotesis(texto: str) -> str:
    """El renglon del SKILL que describe `hipotesis_modelo_predictivo`.

    Acotar aqui NO es cosmetico. `periodo_completo` y `puntos_criticos` siguen siendo
    valores VALIDOS en otro campo -- son las dos `seccion` de `discusion_grafos` --, asi
    que buscarlos en todo el archivo marca menciones legitimas. Lo retirado es que sean
    las subclaves de la HIPOTESIS.
    """
    for linea in texto.splitlines():
        if "`hipotesis_modelo_predictivo`:" in linea:
            return linea
    raise AssertionError("el SKILL no describe `hipotesis_modelo_predictivo`")


def test_las_subclaves_de_la_hipotesis_son_las_del_esquema(texto, esquema):
    requeridas = esquema["properties"]["hipotesis_modelo_predictivo"]["required"]
    assert set(requeridas) == {"ventanas_estudiadas", "plan_de_intervencion"}, requeridas
    linea = _linea_de_la_hipotesis(texto)
    for clave in requeridas:
        assert clave in linea, f"el SKILL no nombra `{clave}` donde describe la hipotesis"
    assert "periodo_completo" not in linea, "el SKILL sigue dando la forma retirada"
    assert "puntos_criticos" not in linea, "el SKILL sigue dando la forma retirada"


def test_las_dos_secciones_del_grafo_siguen_nombrandose(texto):
    """La otra cara de la prueba anterior: esos dos nombres SI tienen un uso valido.

    Si alguien los borra del archivo entero para hacer pasar la guarda de arriba, se
    lleva por delante la descripcion de `discusion_grafos`.
    """
    assert "periodo_completo" in texto and "puntos_criticos" in texto


def test_el_skill_no_nombra_una_regla_que_el_esquema_rechaza(texto, esquema):
    valido = json.dumps(esquema)
    assert "02_window_scenario_interpreter" in valido
    assert "02_circuit_scenario_interpreter" not in valido
    assert "02_circuit_scenario_interpreter" not in texto, (
        "el SKILL nombra un `rule` que el esquema no acepta")


def test_todo_playbook_que_el_skill_cita_existe(texto):
    """La razon por la que el nombre viejo importa: era tambien una RUTA."""
    import re
    citados = set(re.findall(r"\.claude/skills/inference/prompt/([\w.]+\.md)", texto))
    assert citados, "el SKILL deberia citar sus playbooks"
    faltan = sorted(n for n in citados if not (PLAYBOOKS / n).is_file())
    assert not faltan, f"el SKILL cita playbooks que no existen: {faltan}"
