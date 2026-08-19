# `aplicaciones/databricks/` — lo que corre en el servidor, no aquí

Las carpetas numeradas de `aplicaciones/` (`01_clima`, `06_simulador`…) son
**aplicaciones de escritorio**: tienen su entorno, sus lanzadores y un puerto fijo, y
corren en la máquina de quien las abre.

Esto es otra cosa. Aquí vive el código que se **sube** a Databricks y corre allá, dentro
del contenedor de una Databricks App. No tiene `.venv`, ni `Iniciar.app`, ni puerto: sus
dependencias las instala Databricks a partir de su `requirements.txt`.

Se distingue por el nombre, y a propósito: la convención de `aplicaciones/` es que **una
aplicación local empieza por un número**. `tests/test_aplicaciones_locales.py` se apoya en
eso — antes seleccionaba «todo lo que no empiece por `.` o `_`», reclamó esta carpeta como
propia y le exigió un `Iniciar.app` que nunca va a tener.

## `criticidad_chec/`

Los cuatro tableros estáticos —clima, agrupamiento, trayectorias de circuitos y
trayectorias de vanos— servidos como **una sola app con cuatro rutas**. Lo publica
`/subir-a-databricks`.

Reemplaza a cuatro apps y cuatro comandos. El motivo no es la elegancia: el workspace
**topa en tres apps**, así que el cuarto tablero no cabía nunca y el orquestador lo dejaba
sin desplegar en cada corrida.

**No construye nada.** Los paneles se construyen antes de subir, con
`chec_tableros.<modulo>.construir()` —el mismo código que corre la aplicación de
escritorio— y viajan ya empaquetados al Volume. Por eso esta app arranca en segundos y sus
dependencias son tres, ninguna de datos.

**El simulador no está en esta app**, y no por tamaño: su botón *Simular* corre el modelo
MIL de PyTorch sobre lo que el usuario elija. Necesita un intérprete vivo; esto sirve
archivos. Va en la carpeta de al lado.

## `simulador/`

La segunda app: el simulador servido con **Voila** sobre `src/chec_tableros/simulador/`,
que sigue siendo la única fuente de verdad. Tres archivos y ninguno es un tablero:

| Archivo | Qué hace |
|---|---|
| `arranque.py` | baja el paquete precalculado del Volume al disco local del contenedor y hace `execvp` a Voila |
| `app.yaml` | el `command`, y las dos variables que `arranque.py` lee |
| `requirements.txt` | lo que Databricks instala; sale de auditar los imports reales, no de adivinar |

**Estos tres archivos vivieron dentro de un `.md`.** El comando retirado
`/app-simulador-vano` los llevaba como bloques de código, y al fundir los cuatro comandos
de Databricks en `/subir-a-databricks` (commit `1c0aa56`) se perdieron con él: sobrevivió
la etapa que los sube y no lo que los escribía, así que durante dos días esa etapa mandaba
subir tres archivos inexistentes. Código que sólo vive en un Markdown es código que
ninguna herramienta ve — que es la misma razón por la que existe
`scripts/empacar_app_databricks.py`.

**El paquete se precalcula fuera.** El cuaderno tal cual lee 909 MB al arrancar y deja
2.867 MB residentes; con el paquete son 94,5 MB leídos y 579 MB residentes. Como Voila le
da un kernel propio a cada sesión, eso es lo que fija el techo: sin paquete, una app MEDIUM
aguanta **una** sesión; con paquete, seis o siete.

### Cómo se prueba sin Databricks

`tests/test_app_simulador_databricks.py` no puede levantar la app —necesita un Volume y un
kernel—, así que fija lo que sí se puede comprobar desde aquí y es justo lo que se rompe en
silencio: que los tres archivos existan, que todo lo que `arranque.py` importa viaje o esté
declarado, que **las dos variables de entorno que lee estén puestas** en el `app.yaml`, y
que a Voila no se le pase `--base_url`.

Esa de las variables era un defecto real del original: el `app.yaml` sólo fijaba
`PAQUETE_06`, así que `VOLUME_06` caía a su valor por defecto —el Volume de
`workspace.default`, un catálogo que en CHEC no existe (D1)— y la app arrancaba sin
encontrar su paquete.

### Cómo se prueba sin Databricks

`tests/test_app_criticidad_chec.py` monta la app sobre un Volume de mentira: sustituye la
única llamada que este entorno no puede hacer —`files.download`— por una lectura de disco,
y comprueba todo lo que hay encima: el enrutado, la negociación de gzip, las cabeceras de
caché, que una pieza no pueda salirse de su carpeta y que un 404 y un 502 signifiquen
cosas distintas.

Lo que esas pruebas **no** pueden decir: si el Volume se deja leer de verdad, si el grant
está puesto y si el contenedor arranca. Eso es una corrida real, y por eso el comando
exige una bitácora.
