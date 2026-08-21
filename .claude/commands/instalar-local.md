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

- `revisiones`: dieciseis comprobaciones con `estado` (`listo` / `falta` / `aviso`),
  `detalle` y `arreglo` **para el sistema de esta maquina**;
- `destinos`: un veredicto por cada uno de los tres, con lo que le falta a cada uno;
- `sistema`: `macos`, `windows` u `otro`.

**No reimplementes ninguna de sus listas aqui.** El piso de Python lo declara
`aplicaciones/_comun/entorno.py`, los puertos los declara `menu.py`, y los insumos del
clon los declara el propio script — que es tambien de donde los lee
`tests/test_clon_limpio.py`. Una segunda copia en este archivo seria una segunda verdad,
y la que se desactualiza es siempre la copia.

Muestrale al usuario el informe legible (el mismo script sin `--json`) antes de seguir.

**Y si `runtime_vc` o `rutas_largas` salieron en `falta`, pidelas AQUI, antes de la
pregunta del paso 1.** Las dos necesitan a quien administre la maquina, que puede tardar
en aparecer, y ninguna depende de la respuesta: `runtime_vc` bloquea los tres destinos, y
`rutas_largas` bloquea `06_simulador` se elija lo que se elija. El gate del paso 1 detiene
las INSTALACIONES, que son gigabytes; no detiene una peticion que no descarga nada y que
conviene tener en marcha mientras se decide el resto. Los comandos exactos, en el paso 2.

**Pero no las pidas antes de diagnosticar.** El redistribuible de Visual C++ ya viene
puesto en buena parte de las maquinas Windows -- lo instala medio catalogo de software --,
y pedir una elevacion a ciegas gasta el favor del administrador en la mayoria que no la
necesita. El diagnostico cuesta segundos y contesta por ESTA maquina.

## 1. Pregunta, una sola vez

Con los tres veredictos a la vista, pregunta **para cual de los tres destinos** hay que
dejar lista la maquina:

1. **el cuaderno mil_vano (05)** — entorno raiz e insumos;
2. **las aplicaciones en local** — los seis entornos, los puertos y los datos de LFS;
3. **subir a Databricks** — la CLI, una sesion valida, y todo lo del punto 1.

Por defecto, los tres. Si un destino ya sale `listo`, dilo y no preguntes por el.

Y **para. Espera la respuesta.** Los pasos de abajo instalan gigabytes: no se empiezan
por suposicion.

El gate es para lo que descarga. Las dos peticiones de administrador ya salieron al final
del paso 0 y no esperan aqui.

## 2. Lo que no puedes instalar tu

Cinco cosas necesitan a la persona delante, y las cinco se piden con el prefijo `!`
para que corran en esta sesion:

| Que | Por que no puedes tu |
|---|---|
| **Python** por debajo del piso | instalarlo pide permisos de administrador y, en Windows, marcar *Add python.exe to PATH* en el instalador |
| **`databricks auth login`** | abre el navegador y pide credenciales |
| **Un puerto BLOQUEADO** | lo reserva el sistema (Hyper-V, WSL, Docker); lo levanta quien administra la maquina |
| **El runtime de Visual C++** (solo Windows) | pide elevacion; sin el, `import torch` muere con `WinError 126` sobre `c10.dll` y pip no tiene nada que arreglar |
| **`LongPathsEnabled`** (solo Windows) | escribe en `HKLM`, asi que pide elevacion; sin el, la instalacion del simulador aborta con `WinError 206` |

Las dos ultimas son de Windows y NO son paquetes de pip, y las dos se disfrazan de otra
cosa -- por eso las mira el diagnostico y no el ojo. Sin el runtime de Visual C++,
`pip check` sale limpio, los paquetes estan todos y `torch` sigue sin cargar: reinstalar
`requirements.txt` son 1,9 GB que dejan la maquina exactamente igual. Y con
`LongPathsEnabled` en 0, la instalacion del simulador aborta a mitad y deja el `.venv`
CREADO y a medias, que es justo el estado que un diagnostico perezoso da por bueno.

Las dos son de quien administra la maquina, no tuyas ni del usuario, y conviene decirlo
al pedirlas: si no hay administrador a mano, el destino `aplicaciones` se queda en cinco
de seis y los otros dos no salen en absoluto.

**Pero las dos no se piden igual, y la diferencia la decide quien dispara el UAC.**

- **El runtime de Visual C++ LANZALO TU.** `winget install Microsoft.VCRedist.2015+.x64
  --accept-package-agreements` arranca sin elevacion: es el instalador el que pide el
  UAC por su cuenta -- dice `El instalador solicitara que se ejecute como administrador.
  Espere una indicacion.` --, asi que basta con que haya alguien delante para aprobar el
  dialogo. El usuario no escribe nada; solo mira la pantalla. Medido el 2026-08-20:
  salio 0, y `runtime_vc` y `entorno_raiz` pasaron los dos a `listo` de una vez y sin
  descargar un byte del `requirements.txt`.
- **`LongPathsEnabled` NO.** Escribir en `HKLM` desde una consola sin elevar falla con
  `Acceso denegado al Registro solicitado` y **no abre ningun dialogo**: no hay nada que
  aprobar. Esa si tiene que correrla una consola que YA este elevada, o no corre.

Asi que avisale que mire la pantalla y lanza el runtime tu mismo. Es el que bloquea los
tres destinos, y es el unico de los cinco de esta tabla que puedes empujar sin esperar.

**Y `rutas_largas` tiene una segunda salida que no pasa por el administrador: acortar la
ruta del clon.** Contra `MAX_PATH` consigue lo mismo que el registro -- lo que desborda es
`len(raiz) + 187`, y los 187 no se pueden tocar --, y no pide permisos a nadie. El clon
tiene que caber en 61 caracteres.

Si `rutas_largas` salio en `falta`, ofrece esto ANTES de pedir el registro, porque se
resuelve en el acto y la elevacion puede tardar dias:

```
mover-a-ruta-corta.bat        # doble clic, en la raiz del clon
```

Mide donde quedo y, si cabe, no toca nada y lo dice. Si no cabe, propone `C:\CHEC\<carpeta>`
y mueve cuando el usuario escriba `SI`. El `.bat` existe porque un `.ps1` no se ejecuta con
doble clic, porque el directorio actual no puede estar dentro de lo que se mueve, y porque
sin `pause` la ventana se cierra encima del resultado; las tres las resuelve el.

**Tiene que ser antes de instalar.** Los `.venv` llevan su ruta absoluta dentro, asi que
mover un clon ya instalado los rompe -- el script lo comprueba y se frena. Despues de
instalar, mover cuesta rehacer los seis entornos: ~6 GB.

**Solo `06_simulador` trae `torch`** -- miralo en su `requirements.txt` si dudas --, y la
cola de 187 caracteres que desborda `MAX_PATH` son las licencias de terceros de `kineto`,
que las pone `torch` y nadie mas. De ahi salen las dos cosas que SI puedes adelantar
mientras se consigue al administrador:

- los **cinco visores** no dependen de ninguna de las dos correcciones;
- el **entorno de la raiz** tampoco depende de `LongPathsEnabled`: su cola es 26
  caracteres mas corta -- los 26 de `aplicaciones\06_simulador\` --, y por eso
  `METAS` en el diagnostico no lista `rutas_largas` bajo `cuaderno`.

Asi que no te quedes esperando: pide las dos correcciones y, mientras llegan, instala el
entorno de la raiz y los cinco visores. Lo unico que queda de verdad detenido es el
simulador.

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

**Dos `falta` distintos, dos respuestas distintas.** El `arreglo` que da el diagnostico es
el mismo para los dos, asi que lee el `detalle` antes de aplicarlo:

- *no existe* -- instalalo con el comando de arriba;
- *existe pero no importa `torch`* -- **no reinstales**. Los paquetes estan todos y
  correctos; lo que falta es el runtime de Visual C++, que es del sistema y no de pip. Esa
  revision pasa sola en cuanto entre el redistribuible, sin bajar nada. Reinstalar aqui
  son 1,9 GB que dejan la maquina exactamente igual -- el desperdicio que advierte el
  paso 2.

## 5. Los seis entornos de las aplicaciones

Uno por aplicacion, y es a proposito: el visor de tableros no necesita `torch` y el
simulador no necesita `scikit-learn` en tiempo de ejecucion. Un entorno unico los
obligaria a instalar la union.

Se hace con el lanzador de cada aplicacion, que es lo mismo que hara el usuario despues:

- **macOS**: doble clic en `aplicaciones/<app>/instalar-en-terminal.command`
- **Windows**: doble clic en `aplicaciones/<app>/instalar.bat`

**Si `rutas_largas` salio en `falta`, instala CINCO y deja `06_simulador` para despues.**
Es la unica que trae `torch`, asi que es la unica que desborda `MAX_PATH`: lanzarla ahora
aborta con `WinError 206` y deja su `.venv` creado y a medias -- exactamente el estado que
advierte el paso 2. Los cinco visores entran sin tocar el registro. Vuelve por el
simulador cuando el administrador ponga `LongPathsEnabled` y se reinicie la sesion.

Desde la terminal, una por una y con su codigo de salida a la vista -- quita
`06_simulador` de la lista si todavia falta `rutas_largas`:

```
# macOS; en Windows, lo mismo con `py -3` desde git-bash
for d in 00_criticidad_chec 01_clima 02_agrupamiento_vanos 03_trayectorias_circuitos 04_trayectorias_vanos 06_simulador; do
  python3 aplicaciones/_comun/gestor.py instalar --app "aplicaciones/$d"
  echo "===== $d SALIO CON $? ====="
done
```

```
# Windows, desde PowerShell
foreach ($d in '00_criticidad_chec','01_clima','02_agrupamiento_vanos','03_trayectorias_circuitos','04_trayectorias_vanos') {
  py -3 aplicaciones\_comun\gestor.py instalar --app "aplicaciones\$d"
  "===== $d SALIO CON $LASTEXITCODE ====="
}
```

Despues, un `grep "SALIO CON"` sobre la salida da una linea por aplicacion y te ahorra
leer las miles de pip. **No uses `for d in aplicaciones/0*/` a secas**: no para cuando una
falla, su codigo de salida es solo el de la ultima, y el mensaje de la que aborto se va
scroll arriba. Y ni con los codigos en 0 des las seis por buenas sin volver a
diagnosticar, que ahora comprueba el `requirements.txt` de cada aplicacion y no solo que
la carpeta exista.

**Si una quedo a medias, no la reinstales encima: rehazla.** `gestor.py instalar --recrear
--app <carpeta>` borra el entorno y lo vuelve a crear desde cero. Correr `instalar` a
secas sobre un `.venv` a medias suele bastar -- pip completa lo que falte --, pero si lo
que quedo corto fue el entorno mismo, que es el caso del `WinError 206`, pip no tiene
donde instalar y el fallo se repite identico. Ante la duda, `--recrear`: cuesta una
descarga que ya esta en la cache de pip.

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

**En Windows `winget` la deja en el PATH de USUARIO, y la consola actual no lo relee.**
Hasta abrir una consola nueva el diagnostico no la encuentra, y el paso 7 reportaria como
ausente lo que se acaba de instalar. Es la misma trampa que el `setx` del paso 4.

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

**Desde una consola nueva** si acabas de instalar algo con `winget` o `brew`, o leeras un
PATH viejo y te creeras un `falta` que ya no existe.

Sale **0** si los tres destinos quedaron listos, **1** si a alguno le falta algo. Reporta:

- que se instalo y que ya estaba;
- los tres veredictos, uno por linea;
- lo que quedo pendiente y **de quien depende** — el usuario (contrasena, navegador) o
  quien administra la maquina (un puerto reservado);
- los avisos, que no tumban nada pero conviene leer: RAM justa, disco justo, un puerto
  ocupado por algo que ya esta abierto.

**`falta` no es lo mismo que roto.** Un `.venv` que existe y solo falla el `import torch`
esta completo: lo que falta es el runtime de Visual C++. Dilo asi al reportar, porque la
diferencia es si al usuario le quedan cinco minutos de administrador o 1,9 GB de descarga.

**Que el diagnostico salga 0 no es lo mismo que haber abierto un tablero.** Si el destino
era las aplicaciones, cierra sugiriendo el doble clic en
`aplicaciones/00_criticidad_chec/` — `Iniciar.app` en macOS, `iniciar.bat` en Windows —,
que es la comprobacion de verdad y cuesta segundos.
