"""Levanta el simulador del cuaderno 06 con Voila, en local.

## Por que Voila y no una reescritura

El tablero del cuaderno 06 son ~1.900 lineas de `ipywidgets` sobre un
`go.FigureWidget`: mapas, 220 casillas, controles de las 26 variables simulables y
un `asyncio` de rebote. Voila sirve ESE cuaderno tal cual, asi que el cuaderno sigue
siendo la unica fuente de verdad. Reescribirlo en Dash o Streamlit obligaria a
mantener dos tableros que tienen que coincidir para siempre.

## Por que no puede ser un HTML estatico como 01 y 02

Porque el boton "Simular" corre el modelo MIL de PyTorch sobre los vanos elegidos y
con los valores que el usuario escribe. El espacio de entrada son 26 variables sobre
hasta 10 vanos: no hay respuesta que precomputar. Necesita un interprete de Python
vivo, y por eso esta aplicacion pesa lo que pesa y las otras dos no.
"""
import argparse
import os
import subprocess
import sys
import threading
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI.parent / "_comun"))

import entorno  # noqa: E402
import servidor  # noqa: E402
from preparar import (  # noqa: E402
    COPIA,
    CUADERNO,
    NOMBRE_KERNEL,
    NOMBRE_KERNEL_VISIBLE,
    PAQUETE,
)


def _asegurar_kernel() -> None:
    """Registra el kernel de esta aplicacion dentro de su propio entorno.

    `--sys-prefix` y no `--user`: el kernel queda bajo el `.venv` de la aplicacion, asi
    que solo lo ve quien arranca desde ahi y no se cuela en la lista de kernels de
    Jupyter del usuario. Es idempotente, y se comprueba antes para no pagar el arranque
    de un subproceso en cada inicio.
    """
    destino = Path(sys.prefix) / "share" / "jupyter" / "kernels" / NOMBRE_KERNEL
    if (destino / "kernel.json").exists():
        return
    print(f"Registrando el kernel {NOMBRE_KERNEL} en el entorno de la aplicacion.")
    subprocess.run(
        [sys.executable, "-m", "ipykernel", "install", "--sys-prefix",
         "--name", NOMBRE_KERNEL, "--display-name", NOMBRE_KERNEL_VISIBLE],
        check=True,
    )


def _hace_falta_construir() -> str | None:
    """Devuelve el motivo por el que hay que (re)construir, o None si no hace falta."""
    manifiesto = PAQUETE / "manifiesto.json"
    if not manifiesto.exists() or not COPIA.exists():
        return "todavia no esta construido"
    import hashlib
    import json

    sha_actual = hashlib.sha1(CUADERNO.read_bytes()).hexdigest()
    sha_paquete = json.loads(manifiesto.read_text("utf-8")).get("cuaderno_sha1")
    if sha_actual != sha_paquete:
        # No es paranoia: el paquete congela objetos que salen de las celdas de
        # arranque, y el resto del cuaderno los consume suponiendo su forma. Un
        # cuaderno editado con un paquete viejo es la unica manera de que el tablero
        # dibuje datos que ya no corresponden sin que nada de error.
        return "el cuaderno 06 cambio desde la ultima construccion"
    return None


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--no-abrir", action="store_true")
    analizador.add_argument("--puerto", type=int, default=None)
    analizador.add_argument("--reconstruir", action="store_true")
    args = analizador.parse_args()

    motivo = "reconstruccion pedida" if args.reconstruir else _hace_falta_construir()
    if motivo:
        print(f"Construyendo el simulador: {motivo}.\n")
        import runpy

        runpy.run_path(str(AQUI / "construir.py"), run_name="__main__")
        print()

    voila = entorno.ejecutable_del_venv(AQUI, "voila")
    if not voila.exists():
        raise SystemExit(
            f"No se encontro voila en {voila}. Vuelve a correr instalar."
        )
    _asegurar_kernel()

    puerto = args.puerto or servidor.puerto_libre(8866)
    # El boton de cerrar del tablero corre DENTRO del kernel, y para detener la
    # aplicacion tiene que senalar al proceso de Voila, no al suyo: matar el kernel
    # dejaria el servidor en pie sirviendo una pagina muerta.
    #
    # El kernel no puede deducir ese pid. `os.getppid()` daria el padre, que hoy es
    # Voila pero es una suposicion sobre como jupyter_client lanza los kernels, y
    # mandar SIGTERM a un pid supuesto puede matar un proceso ajeno. Asi que se le
    # pasa por escrito: la RUTA del archivo se conoce antes de lanzar nada y viaja en
    # el entorno; el pid se escribe dentro en cuanto existe.
    archivo_pid = AQUI / ".servidor.pid"
    ambiente = dict(
        os.environ,
        PAQUETE_06=str(PAQUETE),
        ARCHIVO_PID_06=str(archivo_pid),
        # El cuaderno hace `setdefault` sobre esta variable, asi que ponerla aqui es lo
        # que manda la aplicacion a su copia del catalogo en vez de a `data/`.
        RUTA_VARIABLES_SIMULAR=str(PAQUETE / "Variables_simular.xlsx"),
    )

    comando = [
        str(voila), str(COPIA),
        f"--port={puerto}",
        # Solo 127.0.0.1: el simulador no tiene autenticacion, y escuchar en todas las
        # interfaces lo publicaria a la red de la oficina sin decirlo.
        "--Voila.ip=127.0.0.1",
        # Sin esto, un fallo dentro de una celda deja la pagina en blanco y el motivo
        # solo aparece en la terminal, que el usuario no esta mirando.
        "--VoilaConfiguration.show_tracebacks=True",
        # Un kernel ya ejecutado esperando ANTES de que llegue la primera peticion.
        # Medido sobre esta aplicacion: con el, la pagina responde en 4 ms; sin el,
        # en 6,0 s -- que es lo que cuesta arrancar el kernel, importar PyTorch y
        # construir el tablero. Ese costo se paga mientras el navegador todavia abre.
        "--preheat_kernel=True",
        # Uno, no mas: cada kernel en espera ocupa memoria sin que nadie lo mire, y
        # esta aplicacion es de un usuario en una portatil, no un servidor compartido.
        "--pool_size=1",
        # Recicla el kernel de una pestania CERRADA a los tres minutos. `cull_connected`
        # se deja en False a proposito, al reves que en el despliegue de servidor: alli
        # interesa recuperar memoria de una pestania olvidada, pero aqui mataria la
        # sesion de alguien que dejo el tablero abierto leyendolo, y el tablero se
        # quedaria mudo sin decir por que.
        #
        # Tres minutos y no diez: cada kernel de esta aplicacion pesa ~780 MB residentes
        # (medido), y cada recarga de la pagina levanta uno nuevo sin cerrar el anterior.
        # Con el plazo de diez minutos se llego a SIETE kernels vivos a la vez -- 5,4 GB
        # en una portatil -- solo por recargar la pestania mientras se probaba. El plazo
        # sigue siendo holgado frente al otro caso que importa: una desconexion pasajera
        # -- la tapa del portatil, el wifi -- recupera su kernel al volver si vuelve
        # dentro de esos tres minutos.
        "--MappingKernelManager.cull_idle_timeout=180",
        "--MappingKernelManager.cull_interval=30",
        "--MappingKernelManager.cull_connected=False",
    ]
    # Voila abre el navegador por su cuenta, pero con el modulo `webbrowser`, que en
    # macOS le habla al navegador por Apple Events y falla en silencio si nadie
    # concedio el permiso de Automatizacion. Se le quita ese trabajo y se usa el mismo
    # lanzador que las otras dos aplicaciones, que ya evita ese camino.
    comando.append("--no-browser")
    url = f"http://127.0.0.1:{puerto}/"
    print(f"\n  Simulador servido en  {url}")
    print("  El primer arranque tarda unos segundos mientras se carga el modelo.")
    print("  Deja esta ventana abierta mientras lo usas. Ctrl+C para detenerlo.\n")

    if not args.no_abrir:
        # Mas espera que en 01 y 02: aqui el navegador no puede llegar antes de que
        # Voila levante su servidor, que primero arranca un kernel y ejecuta el
        # cuaderno entero.
        def _abrir() -> None:
            if not servidor.abrir_navegador(url):
                print(f"  No se pudo abrir el navegador solo: copia {url} y pegalo.")

        threading.Timer(6.0, _abrir).start()

    # Popen y no `run`: hace falta el pid de Voila para dejarselo al boton de cerrar.
    proceso = subprocess.Popen(comando, env=ambiente)
    archivo_pid.write_text(str(proceso.pid), encoding="utf-8")
    try:
        return proceso.wait()
    except KeyboardInterrupt:
        proceso.terminate()
        proceso.wait()
        print("\n  Detenido.")
        return 0
    finally:
        # El pid de un proceso muerto se reasigna, asi que un archivo olvidado apunta
        # tarde o temprano a otra cosa. Se borra pase lo que pase.
        archivo_pid.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
