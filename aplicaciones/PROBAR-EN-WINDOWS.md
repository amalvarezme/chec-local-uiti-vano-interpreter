# Cómo probar las aplicaciones en Windows

Las aplicaciones locales se desarrollan en macOS y se usan también en Windows. Los tres
fallos de Windows que aparecieron el 2026-08-13 —`signal.SIGKILL`, `SO_REUSEADDR` y los
finales de línea de los `.bat`— **no se ven leyendo el código en un Mac**, y ninguno
habría fallado en las pruebas de aquí. Esta nota es el plan para que no dependa de la
suerte.

El **nivel 1 ya está montado** (`.github/workflows/windows.yml`). El nivel 2 sigue
siendo una propuesta, con los números medidos.

---

## Nivel 1 — GitHub Actions en `windows-latest` ✅

Es lo barato y lo permanente, y **está montado** en `.github/workflows/windows.yml`.
Vuelto a medir el 2026-08-19, esta vez sobre un **clon de verdad** —`git clone` sin
`git lfs pull`, o sea con punteros de 134 bytes, y sin los `panel/` construidos, que
están en `.gitignore`—:

| | |
|---|---|
| pruebas que corren | **187 pasan, 4 se saltan, 3 quedan fuera** |
| dependencias | `pytest ipywidgets numpy` |
| datos | **ninguno**. No hace falta `git lfs pull` |
| tiempo | 0,55 s de pruebas; ~1 min de reloj con checkout e instalación |

**Los números de la propuesta de agosto ya no valían, y conviene saber por qué.** Decía
«152 pasan» y «solo `pytest`». Medido hoy con sólo `pytest`: 188 pasan y **6 fallan**,
porque `test_aplicaciones_locales.py` creció hacia el simulador y ahora importa
`ipywidgets` y `numpy`. Con esos dos quedan 3, y ésos necesitan la pila real
(`preparar.py` → la derivación → matplotlib y torch): son los tres `--deselect` del
workflow, nombrados uno a uno ahí mismo. **No se saltan en silencio** —en la suite
completa de macOS corren enteros—, y esa distinción no es cosmética: en este repositorio
ya hubo un arnés que afirmaba un título obsoleto durante semanas porque su prueba estaba
saltada y se leía como pasada.

Se añadieron además dos archivos que no estaban en la propuesta y que sí valen en
Windows: `test_piso_de_python.py` (el piso de 3.11 contra las ruedas reales) y
`test_app_simulador_databricks.py` (sólo lee archivos).

**`--noconftest` no es opcional, y conviene saber por qué.** `tests/conftest.py` tiene un
fixture `autouse` que importa la pila de agent-tools (pandas, matplotlib, pdfplumber), y
eso arrastra medio repositorio a unas pruebas que solo leen archivos. El arreglo limpio
sería hacer esos imports perezosos; mientras tanto, la bandera.

**Lo que este nivel atrapa**: constantes que en Windows no existen, opciones de socket que
allí significan lo contrario, rutas, finales de línea. O sea: exactamente la clase de
fallo que ya apareció una vez.

**Lo que NO puede**: no hay escritorio. Ni doble clic, ni navegador, ni ventana de consola
cerrándose sola.

---

## Nivel 2 — una Windows de verdad, para la mitad gráfica

Hay cuatro cosas que solo se pueden ver con una pantalla delante:

1. el doble clic en `iniciar.bat` abre una consola nueva;
2. el navegador abre solo (`os.startfile`);
3. el botón de cerrar del tablero cierra puerto, proceso **y** consola;
4. *Cerrar todo* del menú se lleva las cinco aplicaciones sin dejar huérfanos, y el
   *Cerrar* de un tablero se lleva **solo ese**, dejando los demás en pie.

### Si es en una VM sobre este Mac

El Mac es **arm64**, así que sería Windows 11 ARM64:

| | licencia del hipervisor | fricción |
|---|---|---|
| **VMware Fusion** | gratis para uso personal | media — la recomendada |
| **UTM** | gratis (QEMU) | alta, la instalación pide paciencia |
| **Parallels Desktop** | ~USD 100/año | baja, descarga el ISO ARM solo |

Las tres necesitan además una licencia de Windows para uso no evaluativo.

> **La VM sería ARM y las máquinas de CHEC son x64.** Para lo que hay que probar aquí
> —`cmd.exe`, sockets, señales, finales de línea, el doble clic— esa diferencia no
> importa. Para las ruedas binarias de PyTorch y geopandas del **simulador**, sí. La VM
> sirve para los cuatro tableros estáticos y el menú; el cuaderno 06 conviene verlo en
> una x64 real.

### O, más barato: la máquina de alguien en CHEC

Es la que de verdad importa, y no cuesta licencia ni disco. Diez pasos:

1. `git clone` y `git lfs pull`.
2. Doble clic en `aplicaciones\01_clima\instalar.bat`. Termina sin error.
3. Doble clic en `iniciar.bat`. **Se abre una consola nueva** y, tras la construcción, el
   navegador en `http://127.0.0.1:8801/`.
4. Botón **Cerrar**. Se cierra la pestaña, el puerto queda libre y **la consola se
   cierra sola**.
5. Volver a dar doble clic. Abre en **el mismo 8801**, sin reconstruir, en menos de un
   segundo.
6. Mover la fecha de `data\Indicadores_vano_v3.csv` y abrir otra vez: tiene que imprimir
   *«Reconstruyendo el tablero: cambio Indicadores_vano_v3.csv…»*.
7. Doble clic en `aplicaciones\00_criticidad_chec\iniciar.bat`. El menú abre en 8800.
8. Abrir dos tableros desde el menú. Cada uno en su puerto (8801, 8802) y en su pestaña.
   El botón **Cerrar** del primero libera **solo el 8801**: el 8802 y el menú siguen.
9. **Cerrar todo**, en el menú. Los puertos que quedaran quedan libres y no queda ningún
   `python.exe` vivo (mirar el Administrador de tareas).
10. Repetir el paso 7. Todo vuelve a abrir: ningún puerto quedó bloqueado.
11. En el **simulador** (`aplicaciones\06_simulador\iniciar.bat`): *Simular* y después
    *Guardar*. El panel tiene que contestar con una ruta bajo
    `C:\Users\<tu-usuario>\CriticidadCHEC\simulaciones`, y ahí tienen que estar los dos
    archivos — el `.html` y el `.simchec.json.gz`. Abrir el `.html` con doble clic: las
    tildes de las descripciones del contrato se ven bien (se escribe en UTF-8 explícito;
    con la codificación por defecto de Windows saldrían rotas, y **solo** en Windows).
    Después *Limpiar* y *Cargar*: los vanos, las variables y las actividades vuelven.

Si algo falla, lo útil es el número de puerto y el texto exacto de la consola.

> **Lo que el paso 11 vigila** es el nombre del archivo, no el guardado. La etiqueta de
> ventana del tablero lleva dos puntos (`V10: 2024-06-01 a …`) y Windows los rechaza en
> un nombre de archivo: `nombre_de_archivo` los sustituye, y
> `test_simulaciones_guardadas.py` lo fija desde macOS. Lo que **no** se puede
> comprobar desde aquí es la carpeta personal — `Path.home()` — cuando el usuario tiene
> Documentos redirigidos a OneDrive. Por eso las simulaciones cuelgan de
> `~\CriticidadCHEC` y no de `~\Documents`.

---

## Lo que ya está cubierto sin Windows

`tests/test_windows_aplicaciones.py` corre en macOS y comprueba, leyendo el código, que
no se tomen decisiones que allí son imposibles o peligrosas:

- nada de `SIGKILL`, `killpg`, `getpgid` ni `start_new_session` fuera de una rama que
  pregunte por la plataforma;
- `SO_REUSEADDR` y `allow_reuse_address`, siempre detrás de esa pregunta;
- los seis pares de `.bat`, con su `cd /d "%~dp0"` y su `pause`;
- los finales de línea, fijados en `.gitattributes`.

No sustituye a correr en Windows, pero es lo que evita que el próximo cambio reabra
exactamente el mismo agujero.
