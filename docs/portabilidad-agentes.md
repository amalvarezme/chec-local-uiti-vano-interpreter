# Portabilidad de los comandos: Claude Code, OpenCode y VS Code Copilot

Los comandos de este repositorio se pueden manejar desde tres editores. Solo uno de
ellos tiene el contrato; los otros dos tienen un puntero.

## Quien manda

`.claude/` es la fuente. Ahi viven los diez skills, los tres comandos invocables y los
cuatro roles, completos: persona, invariantes, secuencia de corrida, forma de la salida.
Nada de eso se copia a ningun lado.

Lo que si se copia es el **nombre y el punto de entrada**, porque cada editor los busca
en una ruta distinta y con un frontmatter distinto:

| | Claude Code | OpenCode | VS Code Copilot |
|---|---|---|---|
| Comandos | `.claude/skills/*/SKILL.md`, `.claude/commands/*.md` | `.opencode/command/*.md` | `.github/prompts/*.prompt.md` |
| Roles | `.claude/agents/*.md` | `.opencode/agent/*.md` | `.github/agents/*.agent.md` |
| Reglas del proyecto | `.claude/agents/rules/invariants.md` | `AGENTS.md` + `opencode.json` | `.github/copilot-instructions.md` + `AGENTS.md` |
| Invocacion | `/report DON23L14` | `/report DON23L14` | `/report DON23L14` |

Los espejos de las dos columnas de la derecha estan **generados**. Cada uno dice tres
cosas y ninguna mas: como se teclea en ese editor, cual es el archivo canonico que hay
que leer antes de hacer nada, y que limites no se cruzan.

## Como se regenera

```bash
PYTHONPATH=src .venv/bin/python scripts/portabilidad_agentes.py generar
PYTHONPATH=src .venv/bin/python scripts/portabilidad_agentes.py verificar
```

`generar` escribe los espejos que faltan, reescribe los que quedaron distintos y borra los
que sobraron cuando un skill se retira. `verificar` no toca nada y sale con 1 nombrando el
archivo que se desvio.

La descripcion de cada espejo se lee del frontmatter canonico, asi que renombrar o
redescribir un skill se propaga con una corrida y sin editar nada mas. Lo unico que se
declara a mano es la pista de argumentos, en el diccionario `ARGUMENT_HINTS` del script:
un skill nuevo sin pista hace fallar `generar` nombrandolo, que es la unica forma barata
de obligar a decidir como se invoca desde los otros dos editores.

## Por que hay un generador y no once archivos escritos a mano

Porque ya se intento a mano. Hubo un arbol de espejos escritos a mano en julio de 2026 y
se murio sin que nadie lo notara. De diez skills canonicos llego a tener siete; `clima`,
`redaccion-es` y `vault-circuito` nunca tuvieron espejo. No habia nada que lo revisara,
asi que la unica forma de enterarse era abrir la carpeta y contar.

Un espejo escrito a mano es una promesa. `scripts/portabilidad_agentes.py` mas
`tests/test_portabilidad_agentes.py` son un mecanismo: un skill nuevo sin espejo, un
espejo editado a mano y un espejo huerfano ponen la suite en rojo, cada uno con su
nombre.

## Como se etiqueta el modelo en el informe

El informe dice con que modelo se genero. El contrato compartido lo resuelve en este
orden: banderas explicitas, luego `CHEC_LLM_PROVIDER` / `CHEC_LLM_MODEL`, luego
`Desconocido`.

No hay lectura de sesiones por runtime. Un adaptador anterior si la tenia: leia el
historial de sesiones de su runtime y su `settings.json`. Funcionaba, y aun asi era la
forma equivocada —cada runtime nuevo habria necesitado su propio lector, cada uno
adivinando el formato privado en disco de otra herramienta. El adaptador sabe con que
modelo esta corriendo, asi que el adaptador lo dice:

```bash
PYTHONPATH=src .venv/bin/python -m chec_local_interpreter.report_contract render \
  <circuito> --run-dir <run_dir> --runtime opencode \
  --provider opencode --model anthropic/claude-opus-5
```

Omitir las dos banderas esta permitido y el informe queda etiquetado `Desconocido`. Eso
es honesto. Inventar un valor por defecto que nadie verifico, no.

## Lo que un espejo nunca puede tener

`tests/test_portabilidad_agentes.py` lo revisa, pero la regla es mas simple que la prueba:
si un espejo empieza a explicar **como** se calcula algo, el espejo esta mal. Los espejos
no llaman a `build_daily_series`, no importan modulos de dominio, no duplican la
preparacion ni el render. Apuntan al archivo que si lo hace.
