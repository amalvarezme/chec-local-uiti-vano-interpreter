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
`/app-criticidad-chec`.

Reemplaza a cuatro apps y cuatro comandos. El motivo no es la elegancia: el workspace
**topa en tres apps**, así que el cuarto tablero no cabía nunca y el orquestador lo dejaba
sin desplegar en cada corrida.

**No construye nada.** Los paneles se construyen antes de subir, con
`chec_tableros.<modulo>.construir()` —el mismo código que corre la aplicación de
escritorio— y viajan ya empaquetados al Volume. Por eso esta app arranca en segundos y sus
dependencias son tres, ninguna de datos.

**El simulador no está aquí**, y no por tamaño: su botón *Simular* corre el modelo MIL de
PyTorch sobre lo que el usuario elija. Necesita un intérprete vivo; esto sirve archivos.

### Cómo se prueba sin Databricks

`tests/test_app_criticidad_chec.py` monta la app sobre un Volume de mentira: sustituye la
única llamada que este entorno no puede hacer —`files.download`— por una lectura de disco,
y comprueba todo lo que hay encima: el enrutado, la negociación de gzip, las cabeceras de
caché, que una pieza no pueda salirse de su carpeta y que un 404 y un 502 signifiquen
cosas distintas.

Lo que esas pruebas **no** pueden decir: si el Volume se deja leer de verdad, si el grant
está puesto y si el contenedor arranca. Eso es una corrida real, y por eso el comando
exige una bitácora.
