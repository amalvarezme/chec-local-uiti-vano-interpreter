# CriticidadCHEC — el menú

Una sola ventana desde la que abrir, vigilar y cerrar los cinco tableros de criticidad
por vano. No dibuja ninguno: los **lanza**, cada uno en su propio proceso, con su propio
entorno y su propio puerto.

## Uso

| macOS | Windows | qué hace |
|---|---|---|
| nada: `Iniciar.app` lo hace solo | `instalar.bat` (doble clic) | una sola vez: crea su entorno (~20 MB) |
| **`Iniciar.app`** (doble clic) | **`iniciar.bat`** (doble clic) | levanta el menú en <http://127.0.0.1:8800/> y lo abre |

> **A qué le doy doble clic:** en **macOS**, a `Iniciar.app`; en **Windows**, a
> `iniciar.bat`. Hacen lo mismo que el `abrir-en-terminal.command` de al lado, y la
> diferencia es que funcionan **siempre**: a un `.command` lo abre la aplicación que
> LaunchServices tenga atada a esa extensión, y eso lo fija cada máquina — con Ghostty
> instalado le toca Ghostty, que se declara *editor* de `.command`, y entonces el doble
> clic **no ejecuta nada**: abre el archivo en un editor. `Iniciar.app` no se puede
> desviar así: LaunchServices no lo abre con otra aplicación, lo **lanza**, y abre
> siempre una ventana nueva de Terminal que se cierra sola al cerrar el tablero. En
> Windows no hace falta nada de esto: un `.bat` lo ejecuta el intérprete de órdenes del
> sistema.
>
> `abrir-en-terminal.command` se conserva para lanzarlo a mano desde una terminal, y es
> el camino de Linux. Se llamaba `iniciar.command` y se renombró justo por esto: con ese
> nombre, y al lado de `Iniciar.app`, el doble clic caía ahí.

`Ctrl+C` en la ventana cierra el menú **y todas las aplicaciones que hubiera abierto**.

## Qué gobierna

| aplicación | puerto |
|---|---|
| Nube por vano y clima | 8801 |
| Agrupamiento de vanos | 8802 |
| Trayectorias de circuitos | 8803 |
| Trayectorias de vanos | 8804 |
| Simulador de riesgo por vano | 8866 |

Son los mismos puertos que fija `.claude/commands/_contrato-apps-locales.md`, y no por
estética: si el menú abriera clima en otro puerto, una instancia lanzada a mano y otra
lanzada desde el menú convivirían sin verse, cada una construyendo y sirviendo por su
lado. Con el puerto compartido, el menú **reconoce** una aplicación que ya estaba
abierta en vez de duplicarla.

## Los tres botones

- **Abrir** — prepara la aplicación si hace falta (crear su entorno son minutos la
  primera vez; construir su tablero, ~71 s) y la abre **en una pestaña nueva**.
- **Volver al menú** — aparece arriba en cada tablero abierto desde aquí. Apaga *esa*
  aplicación y cierra su pestaña, dejando a la vista el menú, que nunca se fue.
- **Cerrar** — el otro botón de esa misma barra. Apaga *esa* aplicación igual que
  *Volver al menú* y cierra su pestaña, sin devolver al usuario al menú.

Y en la página del menú, aparte de esos tres:

- **Detener** — apaga una sola aplicación sin tocar su pestaña.
- **Cerrar todo** — el **único** botón que apaga las cinco aplicaciones y el menú.
  Ningún botón dentro de un tablero puede hacerlo: desde un tablero solo se apaga el
  tablero que se está mirando.

## Por qué una pestaña por aplicación y no una sola

Porque una pestaña que navega acumula historial propio, y **eso es justo lo que impide
que un script la cierre**. Con una pestaña por aplicación, cada tablero nace de un
`window.open()` del menú, y una ventana que abrió un script sí la puede cerrar un
script — sin condiciones. Es lo que hace que *Volver al menú* cierre la pestaña de
verdad en vez de dejar un aviso de despedida.

Por eso el JavaScript del menú abre la pestaña **dentro del manejador del clic**, antes
de preguntarle nada al servidor: un `window.open()` que no cuelga de un gesto del
usuario lo bloquea el navegador, y preparar una aplicación puede tardar minutos.
La pestaña se abre en blanco con un mensaje de espera y recibe la URL cuando el
servidor contesta que ya responde.

## Por qué no tiene dependencias

`requirements.txt` no declara ni un paquete. El menú lanza a las otras como **procesos
hijos** precisamente para no tener que importarlas: hacerlo le costaría la unión de las
cinco listas —`torch` incluido, 1,6 GB— sólo para dibujar un menú. Así su entorno pesa
unos 20 MB y cada aplicación sigue aislada en el suyo.

## Cómo apaga

Por la puerta de cada aplicación, no a señalazos: un `POST /apagar` a su puerto, que es
exactamente lo que hace su propio botón de cerrar. Así sale con código 0 cerrando su
socket, por el camino ya probado. `SIGTERM` queda de respaldo para la que no conteste, y
`SIGKILL` para la que ni aun así se vaya.

El simulador es la excepción: no lo sirve el servidor estático sino Voila, que no tiene
ruta de apagado, así que a ése se le manda `SIGTERM` directamente — que es lo que su
propio botón acaba haciendo.

## Requisitos

Python 3.10+. El menú no toca `data/` nunca; las aplicaciones que abre sí lo necesitan
para **construirse** la primera vez (`git lfs pull`).
