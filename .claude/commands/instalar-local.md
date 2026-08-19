---
description: Revisa esta maquina y la deja lista para las tres cosas que el proyecto hace en local: correr el cuaderno mil_vano, abrir CriticidadCHEC con sus cinco tableros, y subirlo todo a Databricks con /subir-a-databricks. Diagnostica primero -- Python, git-lfs, insumos, entornos, puertos, salida a PyPI y la CLI de Databricks -- y solo instala lo que falta. Distingue macOS de Windows en cada paso. Pregunta una sola cosa: para cual de los tres destinos.
---

Sigue esta secuencia cuando se invoque `/instalar-local`.

## Lo que este comando hace, y lo que no

**Hace**: mirar que le falta a ESTA maquina y ponerlo, en el orden en que las cosas
dependen unas de otras. **No hace**: instalar lo que ya esta. Cada paso empieza
preguntando, y lo que ya esta en su sitio no se toca.

**No habla con Databricks.** Deja la CLI instalada y una sesion abierta; subir es
`/subir-a-databricks`, que es el unico comando que habla con el workspace.

## 0. Diagnostica antes de tocar nada

```
python3 scripts/diagnostico_local.py --json
```

En Windows, `py -3 scripts/diagnostico_local.py --json`.

Ese script corre con el **Python del sistema** y solo la biblioteca estandar, a
proposito: es lo primero que se ejecuta en una maquina recien clonada, donde todavia no
existe ningun entorno. Devuelve tres cosas:

- `revisiones`: catorce comprobaciones con `estado` (`listo` / `falta` / `aviso`),
  `detalle` y `arreglo` **para el sistema de esta maquina**;
- `destinos`: un veredicto por cada uno de los tres, con lo que le falta a cada uno;
- `sistema`: `macos`, `windows` u `otro`.

**No reimplementes ninguna de sus listas aqui.** El piso de Python lo declara
`aplicaciones/_comun/entorno.py`, los puertos los declara `menu.py`, y los insumos del
clon los declara el propio script — que es tambien de donde los lee
`tests/test_clon_limpio.py`. Una segunda copia en este archivo seria una segunda verdad,
y la que se desactualiza es siempre la copia.

Muestrale al usuario el informe legible (el mismo script sin `--json`) antes de seguir.

## 1. Pregunta, una sola vez

Con los tres veredictos a la vista, pregunta **para cual de los tres destinos** hay que
dejar lista la maquina:

1. **el cuaderno mil_vano (05)** — entorno raiz e insumos;
2. **las aplicaciones en local** — los seis entornos, los puertos y los datos de LFS;
3. **subir a Databricks** — la CLI, una sesion valida, y todo lo del punto 1.

Por defecto, los tres. Si un destino ya sale `listo`, dilo y no preguntes por el.

Y **para. Espera la respuesta.** Los pasos de abajo instalan gigabytes: no se empiezan
por suposicion.

## 2. Lo que no puedes instalar tu

Tres cosas necesitan a la persona delante, y las tres se piden con el prefijo `!` para
que corran en esta sesion:

| Que | Por que no puedes tu |
|---|---|
| **Python** por debajo del piso | instalarlo pide permisos de administrador y, en Windows, marcar *Add python.exe to PATH* en el instalador |
| **`databricks auth login`** | abre el navegador y pide credenciales |
| **Un puerto BLOQUEADO** | lo reserva el sistema (Hyper-V, WSL, Docker); lo levanta quien administra la maquina |

Para cada una, dale el comando exacto del campo `arreglo`, que ya viene resuelto para su
sistema, y explica en una linea que va a pasar. **Un puerto bloqueado no es un puerto
ocupado**: ocupado significa que hay algo escuchando; bloqueado significa que el sistema
no deja atarse a el, y ahi la aplicacion arrancaria en un puerto al azar, viva e
invisible para el menu.

## 3. git-lfs y los datos: primero, porque todo lo demas los lee

Si falta `git_lfs`, instalalo con el `arreglo` que da el diagnostico —
`brew install git-lfs && git lfs install` en macOS,
`winget install GitHub.GitLFS && git lfs install` en Windows — y despues:

```
git lfs install
git lfs pull
```

**Avisa antes: son ~900 MB** (el CSV de 566 MB, las bolsas de 199 MB y los shapefiles de
180). En una conexion de oficina son minutos.

Esto es lo que separa un clon que funciona de uno que parece funcionar. Sin `git lfs
pull` los archivos **existen** — con 134 bytes que dicen
`version https://git-lfs.github.com/spec/v1` — y el fallo aparece mucho despues: un
tablero que no construye, o peor, un puntero subido al Volume como si fueran datos.

Comprueba el resultado listando tamanios, no fiandote del codigo de salida:
```
python3 scripts/diagnostico_local.py --json
```
y mira que `datos` y `datos_lfs` salgan `listo`.

## 4. El entorno de la raiz — el cuaderno 05 y los paneles de Databricks

Hace falta para **dos** de los tres destinos, y conviene decirlo porque no es evidente:
corre el cuaderno 05, y ademas es el que construye los cuatro paneles que
`/subir-a-databricks` sube (etapa 4b) y el paquete del simulador (etapa 4c).

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt          # macOS
py -3 -m venv .venv && .venv\Scripts\pip install -r requirements.txt        # Windows
```

**Avisa: pesa ~1,9 GB y `torch` domina la descarga** (116 MB de rueda en Windows, solo
CPU). En Windows no hace falta compilador: todas las ruedas grandes — `torch`,
`geopandas`, `pyarrow`, `scipy` — existen para `win_amd64`.

Si el diagnostico marco `red` en `falta`, **esto no va a funcionar y no va a fallar
rapido**: pip se queda reintentando. Pon primero la variable de proxy que dice el
`arreglo`, y recuerda que en Windows hay que abrir una consola NUEVA despues de `setx`.

## 5. Los seis entornos de las aplicaciones

Uno por aplicacion, y es a proposito: el visor de tableros no necesita `torch` y el
simulador no necesita `scikit-learn` en tiempo de ejecucion. Un entorno unico los
obligaria a instalar la union.

Se hace con el lanzador de cada aplicacion, que es lo mismo que hara el usuario despues:

- **macOS**: doble clic en `aplicaciones/<app>/instalar-en-terminal.command`
- **Windows**: doble clic en `aplicaciones/<app>/instalar.bat`

Desde la terminal, para las seis de una:
```
for d in aplicaciones/0*/; do python3 aplicaciones/_comun/gestor.py instalar --app "$d"; done
```

`gestor.py` tambien corre con el Python del sistema — es quien CREA los entornos, asi que
no puede vivir dentro de uno. Antes de lanzar pip comprueba que haya salida a PyPI, para
que una maquina sin proxy configurado no se quede colgada sin decir por que.

**El simulador es el mas pesado (~1,6 GB)**; los cuatro visores rondan los 600 MB cada
uno. Con los seis, cuenta ~4 GB.

## 6. La CLI de Databricks

Instalala si falta:

- **macOS**: `brew tap databricks/tap && brew install databricks`
- **Windows**: `winget install Databricks.DatabricksCLI`

El diagnostico no se conforma con que exista: comprueba que
`databricks apps create --help` acepte `--compute-size`. Una CLI vieja llega hasta la
etapa 4 de `/subir-a-databricks` y muere ahi con un error de argumentos.

La sesion la abre el usuario, con el prefijo `!`:
```
databricks auth login --host <URL del workspace>
```

**No elijas tu el workspace.** `/subir-a-databricks` lo pregunta en cada corrida y deriva
el perfil de la URL (contrato C0). Aqui solo hace falta que exista **una** sesion valida;
cual se use es decision de esa corrida, no de esta.

Un perfil con `valid: false` es un token vencido, no una configuracion rota: el mismo
`auth login` lo renueva.

## 7. Vuelve a diagnosticar y reporta

```
python3 scripts/diagnostico_local.py
```

Sale **0** si los tres destinos quedaron listos, **1** si a alguno le falta algo. Reporta:

- que se instalo y que ya estaba;
- los tres veredictos, uno por linea;
- lo que quedo pendiente y **de quien depende** — el usuario (contrasena, navegador) o
  quien administra la maquina (un puerto reservado);
- los avisos, que no tumban nada pero conviene leer: RAM justa, disco justo, un puerto
  ocupado por algo que ya esta abierto.

**Que el diagnostico salga 0 no es lo mismo que haber abierto un tablero.** Si el destino
era las aplicaciones, cierra sugiriendo el doble clic en
`aplicaciones/00_criticidad_chec/` — `Iniciar.app` en macOS, `iniciar.bat` en Windows —,
que es la comprobacion de verdad y cuesta segundos.
