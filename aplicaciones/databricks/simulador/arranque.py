"""Baja el paquete del Volume al disco local y arranca Voila sobre el cuaderno.

## Por que al disco local y no leyendo `/Volumes` directamente

Dos razones, y las dos se midieron antes de escribir esto. El montaje FUSE de un Volume
dentro del contenedor de una app **no esta garantizado** -- contesta 403 (contrato D2) --,
asi que la unica lectura fiable es la Files API de Unity Catalog. Y ademas el mapeo en
memoria de `X_inst.npy` (88 MB de los 94,5 del paquete) necesita un archivo local de
verdad: sobre uno local, el cache de paginas del sistema lo comparte entre todos los
kernels de Voila; sobre una descarga en memoria, cada kernel pagaria sus 88 MB.

## Por que hay un paquete, y no se deriva aqui

El cuaderno tal cual lee **909 MB** al arrancar (CSV 540 + `bolsas_mil_full.joblib` 190 +
shapefiles 180) y deja **2.867 MB** residentes. Con el paquete precalculado son **94,5 MB**
leidos y **579 MB** residentes. Como Voila le da un kernel propio a cada sesion, eso es lo
que fija el techo: sin paquete, una app MEDIUM (2 vCPU / 6 GB) aguanta UNA sesion; con
paquete, seis o siete.

El paquete se construye en la maquina que despliega, con `aplicaciones/06_simulador/
construir.py`, y se sube al Volume. No con un job de Databricks: un job necesitaria
primero los 909 MB espejados en el Volume y despues gastaria computo del cluster para
producir 94,5 MB.
"""
import json
import os
import pathlib
import time

from databricks.sdk import WorkspaceClient

# La carpeta del Volume donde `/subir-a-databricks` dejo el paquete. Entra por entorno
# porque el catalogo y el esquema se RESUELVEN en cada despliegue (contrato C):
# `workspace.default` no existe en todos los workspaces, y el de CHEC es uno de los que
# no lo tiene (D1). `app.yaml` trae el valor resuelto.
VOLUMEN = os.environ.get("VOLUME_06",
                         "/Volumes/workspace/default/chec-simulador/paquete_06")
# Donde se deja la copia local. Dentro del contenedor y efimera: se vuelve a bajar en
# cada arranque en frio, y eso son ~0,3 s de lectura contra 94,5 MB de red.
DESTINO = pathlib.Path(os.environ.get("PAQUETE_06", "/tmp/paquete_06"))
PUERTO = os.environ.get("DATABRICKS_APP_PORT", "8000")

DESTINO.mkdir(parents=True, exist_ok=True)
cliente = WorkspaceClient()
t0 = time.perf_counter()
manifiesto = json.loads(cliente.files.download(f"{VOLUMEN}/manifiesto.json").contents.read())
for nombre, meta in manifiesto["archivos"].items():
    local = DESTINO / nombre
    # Un reinicio del proceso no vuelve a bajar lo que ya esta entero. Se compara el
    # TAMANO y no solo la existencia: una descarga cortada deja un archivo que existe.
    if local.exists() and local.stat().st_size == meta["bytes"]:
        continue
    with open(local, "wb") as f:
        f.write(cliente.files.download(f"{VOLUMEN}/{nombre}").contents.read())
    if local.stat().st_size != meta["bytes"]:
        raise SystemExit(f"{nombre}: {local.stat().st_size} bytes, "
                         f"se esperaban {meta['bytes']}")

_megas = sum(m["bytes"] for m in manifiesto["archivos"].values()) / 1024 / 1024
# Esta linea es la que se busca en `databricks apps logs` para separar "el permiso del
# Volume no llego" de "el kernel no arranco". Sin ella los dos se ven igual.
print(f"paquete listo en {time.perf_counter() - t0:.1f} s ({_megas:.1f} MB) "
      f"| construido {manifiesto['construido_en']}", flush=True)

# El catalogo de variables simulables NO viaja congelado dentro del paquete como los
# demas objetos: `preparar.py` lo copia como archivo suelto, justo para que editarlo se
# note sin reconstruir nada. El precio de esa decision es que alguien tiene que decirle
# al tablero DONDE quedo, y ese alguien es el lanzador.
#
# Sin esta linea, `ruta_variables_simular()` devuelve la ruta relativa
# `data/Variables_simular.xlsx`, que se resuelve contra el directorio de trabajo del
# proceso. En este contenedor no hay ningun `data/`: el panel arranca sin saber que
# variables ofrecer y el error apunta a una ruta que aqui no significa nada. La
# aplicacion local lo pone desde siempre (`aplicaciones/06_simulador/app.py`); esta se
# quedo sin ponerlo.
#
# Cuelga de `DESTINO` -- la copia local del paquete -- y no del Volume, por lo mismo que
# el resto: el montaje FUSE de `/Volumes` dentro del contenedor no esta garantizado
# (contrato D2).
#
# `execvp` hereda el entorno del proceso, asi que escribirlo aqui es lo que lo hace
# llegar a Voila y de ahi al kernel del tablero.
os.environ["RUTA_VARIABLES_SIMULAR"] = str(DESTINO / "Variables_simular.xlsx")

# `os.execvp` y no `subprocess.run`: Voila tiene que quedar como hijo DIRECTO del
# proceso de la plataforma para que sus senales le lleguen, y un lanzador que se queda
# vivo detras se las come y ademas deja una copia residente de si mismo.
#
# **Sin `--base_url`.** La documentacion de proxy inverso de Voila lo usa porque Apache
# monta la app bajo un subcamino; Databricks Apps hace proxy en la RAIZ, y ahi un
# `base_url` deja todos los assets en 404 -- la pagina se ve en blanco y parece un fallo
# del kernel.
os.execvp("voila", [
    "voila", str(pathlib.Path(__file__).parent / "06_simulador.ipynb"),
    f"--port={PUERTO}", "--no-browser", "--Voila.ip=0.0.0.0",
    "--VoilaConfiguration.show_tracebacks=True",
    # Un kernel caliente esperando: el primer visitante no paga los 2,1 s de imports ni
    # los 0,3 s del paquete. Aqui SI vale la pena, al reves que en la aplicacion local
    # (ver `aplicaciones/06_simulador/app.py`): alli costaba 763 MB de un kernel que la
    # unica visitante -- la persona que hizo doble clic -- no llegaba a aprovechar.
    "--preheat_kernel=True", "--pool_size=1",
    # Cada sesion son ~648 MB. Una pestania olvidada los retiene hasta que se recicla, y
    # `cull_connected` es lo que hace que una pestania ABIERTA pero quieta tambien
    # cuente: sin el, un navegador dejado abierto nunca libera su kernel.
    "--MappingKernelManager.cull_idle_timeout=900",
    "--MappingKernelManager.cull_interval=120",
    "--MappingKernelManager.cull_connected=True",
])
