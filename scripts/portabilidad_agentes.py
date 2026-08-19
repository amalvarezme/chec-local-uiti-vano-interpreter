#!/usr/bin/env python3
"""Portabilidad de los comandos del proyecto a VS Code Copilot y a OpenCode.

## Por que existe

`.claude/` es el contrato canonico: diez skills, tres comandos invocables y cuatro
roles. Cada runtime de agente los descubre en una ruta propia y con un frontmatter
propio, asi que para que el proyecto se pueda manejar desde otro editor hay que
publicar los mismos nombres en `.opencode/` y en `.github/`.

El intento anterior fue `.pi/`: espejos escritos a mano. Se cayo sola. De diez
skills canonicos solo siete llegaron a tener espejo, `clima`, `redaccion-es` y
`vault-circuito` nunca lo tuvieron, y nadie se entero porque nada lo revisaba.
Un espejo a mano es una promesa; esto es un mecanismo.

De ahi las dos reglas de este script:

1. **El texto que se puede derivar, se deriva.** La descripcion de cada espejo se
   lee del frontmatter canonico. Renombrar o redescribir un skill actualiza los
   cuatro espejos con una corrida, sin tocarlos.
2. **La deriva es un fallo de prueba, no un descuido.** `verificar` regenera en
   memoria y compara byte a byte. `tests/test_portabilidad_agentes.py` lo corre,
   asi que un skill nuevo sin espejo pone la suite en rojo.

## Uso

    PYTHONPATH=src .venv/bin/python scripts/portabilidad_agentes.py generar
    PYTHONPATH=src .venv/bin/python scripts/portabilidad_agentes.py verificar

`generar` escribe; `verificar` no toca nada y sale con 1 si algo quedo distinto,
nombrando cada archivo que falta o que cambio.

## Lo que este script NO hace

No copia logica de negocio. Los espejos son punteros: dicen como se invoca la cosa
en ese runtime, donde esta el contrato completo, y que limites no se cruzan. Todo
lo demas se lee del archivo canonico en tiempo de ejecucion. Si un espejo empieza
a explicar como se calcula algo, el espejo esta mal.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

REPO_ROOT = Path(__file__).resolve().parents[1]

GENERATED_BY = "scripts/portabilidad_agentes.py"

# Cada entrada invocable necesita una pista de argumentos. Es un diccionario
# explicito y no una heuristica sobre el texto canonico a proposito: cuando
# alguien agrega un skill, `generar` falla nombrandolo, y esa es la unica forma
# barata de obligar a decidir como se invoca desde los otros dos editores.
ARGUMENT_HINTS: dict[str, str] = {
    "app-local-criticidadCHEC": "",
    "clima": "",
    "expert-alignment": "[args from the active workflow]",
    "historical": "[args from the active workflow]",
    "inference": "[args from the active workflow]",
    "informe-gerencial": "<grupo> [fecha_inicio fecha_fin]",
    "limpiar-corridas": "",
    "pdf-discussion-extraction": "[args from the active workflow]",
    "redaccion-es": "[ruta ...]",
    "report": "<circuito> [fecha_inicio fecha_fin]",
    "reporte-lote": "<grupo> [fecha_inicio fecha_fin]",
    "subir-a-databricks": "",
    "vault-circuito": "<circuito>",
}

# Entradas que reparten trabajo entre sub-agentes. Solo esas reciben el bloque de
# delegacion, que es donde vive lo aprendido a golpes: un worker de solo lectura
# no puede cerrar un rol, y un prompt compartido entre tres workers identicos deja
# la corrida colgada sin decirlo.
DELEGATING_ENTRIES = frozenset({"report", "reporte-lote", "informe-gerencial"})

# Skills internos: se publican para que el orquestador los pueda encadenar, pero
# no se anuncian como algo que el usuario teclee.
INTERNAL_ENTRIES = frozenset({"vault-circuito"})

Kind = Literal["entry", "role"]


@dataclass(frozen=True)
class Unit:
    """Una unidad canonica de `.claude/` con su espejo pendiente."""

    kind: Kind
    name: str
    canonical: str  # ruta relativa a la raiz del repo
    description: str
    uses_report_contract: bool

    @property
    def title(self) -> str:
        return self.name


@dataclass(frozen=True)
class Runtime:
    """Donde y como publica sus espejos un runtime concreto."""

    key: str
    label: str
    entry_dir: str
    entry_suffix: str
    role_dir: str
    role_suffix: str
    invocation: str  # como se teclea la entrada, con {name}
    cwd_note: str
    args_note: str
    delegation_note: str
    role_frontmatter_extra: tuple[str, ...]
    entry_frontmatter_extra: tuple[str, ...]

    def entry_path(self, name: str) -> Path:
        return REPO_ROOT / self.entry_dir / f"{name}{self.entry_suffix}"

    def role_path(self, name: str) -> Path:
        return REPO_ROOT / self.role_dir / f"{name}{self.role_suffix}"


OPENCODE = Runtime(
    key="opencode",
    label="OpenCode",
    entry_dir=".opencode/command",
    entry_suffix=".md",
    role_dir=".opencode/agent",
    role_suffix=".md",
    invocation="/{name}",
    cwd_note=(
        "**Repository root.** Resolve it with `git rev-parse --show-toplevel 2>/dev/null || pwd` "
        "and run every command from there. Do not trust the process working directory: in "
        "OpenCode Desktop it can resolve to the app data directory instead of the project."
    ),
    args_note="Everything typed after the command name arrives as `$ARGUMENTS`.",
    delegation_note=(
        "**Subagents.** The role mirrors under `.opencode/agent/` are the ones to dispatch with "
        "the `task` tool -- one explicit task per role, with the role name and its "
        "`<run_dir>/<role>.bc.json` on the first line. Never launch several identical workers "
        "with a shared prompt that forces each one to guess whether it is `historical`, "
        "`inference` or `expert-alignment`; that ambiguity has to be cancelled and relaunched "
        "before render. A worker that cannot run Bash cannot finish a role either -- it leaves "
        "the run stalled without saying so -- so check the agent's permissions before delegating, "
        "and author the role in the parent session when in doubt."
    ),
    role_frontmatter_extra=("mode: subagent",),
    entry_frontmatter_extra=(),
)

COPILOT = Runtime(
    key="copilot",
    label="VS Code Copilot",
    entry_dir=".github/prompts",
    entry_suffix=".prompt.md",
    role_dir=".github/agents",
    role_suffix=".agent.md",
    invocation="/{name}",
    cwd_note=(
        "**Repository root.** Resolve it with `git rev-parse --show-toplevel 2>/dev/null || pwd` "
        "and run every command from there, not from whatever file happens to be open in the "
        "editor."
    ),
    args_note=(
        "Arguments typed after the command name reach this prompt. If none arrive, ask the user "
        "for them before running anything -- never guess a circuit, a band or a date window."
    ),
    delegation_note=(
        "**Subagents.** The role mirrors under `.github/agents/` are the ones to hand each role "
        "to -- one explicit invocation per role, naming the role and its "
        "`<run_dir>/<role>.bc.json` up front. Never dispatch several identical workers with a "
        "shared prompt that forces each one to guess which role it is. A role that cannot run "
        "terminal commands cannot finish: it leaves the run stalled without saying so, so author "
        "the role in the main session when the subagent lacks that access."
    ),
    role_frontmatter_extra=(),
    entry_frontmatter_extra=("agent: agent",),
)

RUNTIMES = (OPENCODE, COPILOT)


def _frontmatter_description(path: Path) -> str:
    """Devuelve la `description` del frontmatter YAML, en una sola linea.

    Se parsea a mano y no con PyYAML porque solo hace falta un campo y porque el
    generador tiene que poder correr sin dependencias instaladas.
    """

    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path} no abre con frontmatter YAML")
    end = text.index("\n---", 3)
    block = text[4:end]

    lines = block.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        value = line[len("description:"):].strip()
        # Las descripciones largas se envuelven en varias lineas indentadas.
        for continuation in lines[index + 1:]:
            if continuation[:1] not in {" ", "\t"} or not continuation.strip():
                break
            value += " " + continuation.strip()
        if value[:1] in {'"', "'"} and value[-1:] == value[:1]:
            value = value[1:-1]
        return " ".join(value.split())
    raise ValueError(f"{path} no declara `description` en su frontmatter")


def _yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def discover_units() -> list[Unit]:
    """Inventaria `.claude/`: skills y comandos como entradas, agentes como roles."""

    units: list[Unit] = []

    for skill in sorted((REPO_ROOT / ".claude" / "skills").glob("*/SKILL.md")):
        units.append(_unit("entry", skill.parent.name, skill))

    for command in sorted((REPO_ROOT / ".claude" / "commands").glob("*.md")):
        # Los archivos con guion bajo son contratos compartidos que se leen desde
        # otro comando, no cosas que alguien teclee. `_contrato-despliegue-databricks`
        # es el unico hoy, y publicarlo como comando invitaria a invocarlo suelto.
        if command.name.startswith("_"):
            continue
        units.append(_unit("entry", command.stem, command))

    for role in sorted((REPO_ROOT / ".claude" / "agents").glob("*.md")):
        units.append(_unit("role", role.stem, role))

    return units


def _unit(kind: Kind, name: str, path: Path) -> Unit:
    return Unit(
        kind=kind,
        name=name,
        canonical=path.relative_to(REPO_ROOT).as_posix(),
        description=_frontmatter_description(path),
        uses_report_contract="report_contract" in path.read_text(encoding="utf-8"),
    )


def _shared_boundaries() -> list[str]:
    return [
        "No external LLM API call. The agent reading this file is the one that reasons; "
        "the Python side only builds context and validates shape.",
        "No automatic publishing and no `site/assets/site/results/` mutation. Publishing is a "
        "separate, deliberate action.",
        "No model training and no Optuna search.",
        "No business logic here. Preparation, simulation, inference, alignment, validation and "
        "rendering stay in the canonical pipeline.",
        "Generated technical artifacts stay in English unless the user asks otherwise.",
    ]


def _header(unit: Unit, runtime: Runtime) -> list[str]:
    role_or_entry = "role" if unit.kind == "role" else "command"
    return [
        f"# {unit.title} -- {runtime.label} mirror",
        "",
        f"Generated by `{GENERATED_BY}`. Edit the canonical contract and re-run `generar`; "
        f"edits made straight to this file are overwritten on the next run.",
        "",
        f"This is a thin mirror. It gives {runtime.label} its own discovery path for a "
        f"{role_or_entry} that is fully defined somewhere else, and it holds no domain rule "
        f"of its own.",
        "",
        "## Read this first",
        "",
        f"- `{unit.canonical}` is the complete contract: persona, invariants, run sequence and "
        f"output shape. Read it before doing anything.",
    ]


def render_entry(unit: Unit, runtime: Runtime) -> str:
    hint = ARGUMENT_HINTS[unit.name]
    invocation = runtime.invocation.format(name=unit.name)
    invocation_line = f"{invocation} {hint}".rstrip()

    lines: list[str] = ["---", f"description: {_yaml_quote(unit.description)}"]
    if hint:
        lines.append(f"argument-hint: {_yaml_quote(hint)}")
    lines.extend(runtime.entry_frontmatter_extra)
    lines.extend(["---", ""])

    lines.extend(_header(unit, runtime))
    if unit.uses_report_contract:
        lines.extend([
            "- `src/chec_local_interpreter/report_pipeline.py` owns report-domain behavior.",
            "- `src/chec_local_interpreter/report_contract.py` owns the normalized "
            "request/outcome shape every runtime shares. Go through it; do not import the "
            "domain modules directly.",
        ])
    lines.extend(["", "## Invocation", "", "```text", invocation_line, "```", ""])
    if unit.name in INTERNAL_ENTRIES:
        lines.append(
            "This one is internal: the report flows chain it themselves. Publishing it here "
            "keeps the chain working in this runtime, not to invite a direct call."
        )
        lines.append("")
    lines.append(runtime.args_note)
    lines.extend(["", "## Runtime notes", ""])
    lines.append(f"- {runtime.cwd_note}")
    lines.append(
        "- **Environment.** Every CLI verb runs as `PYTHONPATH=src .venv/bin/python -m ...`. Do "
        "not reach for bare `python`/`python3` first, and do not report the environment as "
        "missing just because they cannot import `chec_local_interpreter`: the virtualenv-"
        "prefixed form is this repository's supported local command."
    )
    if unit.name in DELEGATING_ENTRIES:
        lines.append(f"- {runtime.delegation_note}")
    if unit.uses_report_contract:
        lines.extend(_report_contract_notes(unit, runtime))
    lines.extend(["", "## Boundaries", ""])
    lines.extend(f"- {item}" for item in _shared_boundaries())
    lines.append("")
    return "\n".join(lines)


def _report_contract_notes(unit: Unit, runtime: Runtime) -> list[str]:
    """Las tres cosas que el contrato compartido exige y que un espejo puede romper."""

    return [
        "- **Preflight through the shared contract**, then state the resolved circuit and window "
        "once and wait for confirmation:",
        "",
        "  ```bash",
        "  PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract preflight "
        f"<circuito> [fecha_inicio fecha_fin] --runtime {runtime.key}",
        "  ```",
        "",
        "- **Measured token usage and duration, before render.** If this runtime hands you a "
        "structured token total for a role, pass it straight through with `record-usage "
        "--run-dir <run_dir> --stage <role> --total <n>`; if it does not, omit that stage and "
        "let the renderer label the total as estimated. Never scrape prose, session history or "
        "output sizes for a number. Duration is yours either way: note your own wall clock "
        "around each dispatch and call `record-duration --run-dir <run_dir> --stage <role> "
        "--seconds <delta>`. Then run `verify-usage` with explicit expected/executed roles.",
        "- **Name the model that actually ran.** The report labels the orchestrating model, and "
        "the shared contract resolves it from explicit flags first, then `CHEC_LLM_PROVIDER` / "
        "`CHEC_LLM_MODEL`, then `Desconocido`. There is no per-runtime session sniffing any "
        "more, so say it out loud:",
        "",
        "  ```bash",
        "  PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract render "
        f"<circuito> --run-dir <run_dir> --runtime {runtime.key} --provider <provider> "
        "--model <model>",
        "  ```",
        "",
        "  Leaving both out is allowed and honest -- the report says `Desconocido`. Inventing a "
        "default is not.",
        "- Return the local HTML report path. Do not publish.",
    ]


def render_role(unit: Unit, runtime: Runtime) -> str:
    lines: list[str] = ["---", f"description: {_yaml_quote(unit.description)}"]
    lines.extend(runtime.role_frontmatter_extra)
    lines.extend(["---", ""])

    lines.extend(_header(unit, runtime))
    skill = f".claude/skills/{unit.name}/SKILL.md"
    if (REPO_ROOT / skill).exists():
        lines.append(f"- `{skill}` is the reasoning contract for the same role.")
    lines.append("- `.claude/agents/rules/invariants.md` holds the invariants every role obeys.")
    lines.extend([
        "",
        "## Runtime notes",
        "",
        f"- {runtime.cwd_note}",
        "- **Environment.** Run the role's two CLI verbs as `PYTHONPATH=src .venv/bin/python -m "
        f"chec_local_interpreter.agent_tools.{unit.name} build-context` and `... validate`. Bare "
        "`python`/`python3` is not this repository's supported local command.",
        "- **Tool budget.** Reading files and running those two verbs is the whole job. The role "
        "authors the JSON answer itself and writes it through the validator; it never calls an "
        "external LLM and never reaches for a tool the canonical role does not grant.",
        "- Cite only what the structured context already contains. A date, a "
        "`critical_point_id`, a variable or a summary that is not in context does not go in the "
        "answer.",
        "",
        "## Boundaries",
        "",
    ])
    lines.extend(f"- {item}" for item in _shared_boundaries())
    lines.append("")
    return "\n".join(lines)


def build_mirrors() -> dict[Path, str]:
    """Todos los espejos que deberian existir, en memoria."""

    units = discover_units()
    missing_hints = sorted(
        unit.name for unit in units if unit.kind == "entry" and unit.name not in ARGUMENT_HINTS
    )
    if missing_hints:
        raise SystemExit(
            "Falta la pista de argumentos de: "
            + ", ".join(missing_hints)
            + f"\nAgregala en ARGUMENT_HINTS dentro de {GENERATED_BY}."
        )

    mirrors: dict[Path, str] = {}
    for runtime in RUNTIMES:
        for unit in units:
            if unit.kind == "entry":
                mirrors[runtime.entry_path(unit.name)] = render_entry(unit, runtime)
            else:
                mirrors[runtime.role_path(unit.name)] = render_role(unit, runtime)
    return mirrors


def _managed_paths() -> Iterable[Path]:
    for runtime in RUNTIMES:
        for directory in (runtime.entry_dir, runtime.role_dir):
            base = REPO_ROOT / directory
            if base.exists():
                yield from sorted(base.glob(f"*{runtime.entry_suffix}"))
                yield from sorted(base.glob(f"*{runtime.role_suffix}"))


def generar() -> int:
    mirrors = build_mirrors()
    expected = set(mirrors)

    written = 0
    for path, content in sorted(mirrors.items()):
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
            written += 1

    # Un skill retirado deja su espejo huerfano. Se borra aqui, no en la proxima
    # sesion que lo note: el caso `.pi` fue justamente el inverso, espejos que
    # nadie sincronizaba en ninguna direccion.
    removed = 0
    for path in set(_managed_paths()) - expected:
        path.unlink()
        removed += 1

    print(f"{len(mirrors)} espejos; {written} escritos, {removed} retirados")
    return 0


def verificar() -> int:
    mirrors = build_mirrors()
    problems: list[str] = []

    for path, content in sorted(mirrors.items()):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if not path.exists():
            problems.append(f"falta: {relative}")
            continue
        current = path.read_text(encoding="utf-8")
        if current != content:
            diff = "\n".join(
                difflib.unified_diff(
                    current.splitlines(), content.splitlines(),
                    fromfile=f"{relative} (en disco)", tofile=f"{relative} (esperado)",
                    lineterm="", n=1,
                )
            )
            problems.append(f"cambio: {relative}\n{diff}")

    for path in set(_managed_paths()) - set(mirrors):
        problems.append(f"sobra: {path.relative_to(REPO_ROOT).as_posix()}")

    if problems:
        print("\n".join(problems))
        print(f"\n{len(problems)} problema(s). Corre `generar` para reescribir los espejos.")
        return 1

    print(f"{len(mirrors)} espejos al dia")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts/portabilidad_agentes.py",
        description="Genera y verifica los espejos de .claude/ para OpenCode y VS Code Copilot.",
    )
    parser.add_argument("verbo", choices=("generar", "verificar"))
    args = parser.parse_args(argv)
    return generar() if args.verbo == "generar" else verificar()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
