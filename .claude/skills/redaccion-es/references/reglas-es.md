# Reglas de redacción en español para este repositorio

Lo que el verificador no puede decidir solo. Se aplica a comentarios, docstrings, markdown
de cuadernos y texto de interfaz (paneles, títulos de figuras, `xlabel`, `ylabel`, marcas
de eje, botones).

## Tildes

- **Monosílabos con tilde diacrítica**: `él` (pronombre) / `el` (artículo); `sí` (afirmación
  o pronombre) / `si` (condicional); `más` (cantidad) / `mas` (pero); `dé` (verbo) / `de`
  (preposición); `sé` (saber o ser) / `se` (pronombre); `té` (bebida) / `te` (pronombre);
  `tú` (pronombre) / `tu` (posesivo); `mí` (pronombre) / `mi` (posesivo).
- **`solo` y los demostrativos no llevan tilde** desde 2010. `solo`, `este`, `ese`, `aquel`.
- **Interrogativos y exclamativos SIEMPRE con tilde**, también en preguntas indirectas:
  `qué`, `cuál`, `cómo`, `cuándo`, `dónde`, `cuánto`, `quién`, `por qué`.
  «No se sabe **cuántos** vanos» lleva tilde aunque no haya signos.
- **`por qué` / `porque` / `porqué` / `por que`**: pregunta y sustantivo llevan tilde
  (`¿por qué?`, `el porqué`); la causa va junta y sin tilde (`porque falla`).
- **Mayúsculas también se acentúan**: `ÍNDICE`, `ÚLTIMO`, `Á`.
- **Verbos con enclítico** cambian de regla: `dé` → `denos`; `mira` → `míralo`.

## Mayúsculas

- **Caso oración** en títulos, rótulos de eje, leyendas y botones. Solo la primera letra y
  los nombres propios. `Trayectorias de circuitos`, nunca `Trayectorias De Circuitos`.
- Los meses y los días **van en minúscula**: `enero`, `martes`.
- Las siglas se quedan como son: `UITI`, `MIL`, `CHEC`, `SHAP`.
- Un término del dominio en versalitas o mayúsculas dentro de una frase (`que HACER`) es
  énfasis deliberado, no un defecto: no se corrige sin preguntar.

## Signos

- `¿ ?` y `¡ !` **siempre en pareja**. Es la falta más frecuente al copiar del inglés.
- La pregunta puede abrir a mitad de frase: «Y entonces, ¿qué pasa si?».
- **Sin espacio antes** de `?`, `!`, `,`, `;`, `:`, `.`.
- Comillas: se prefieren las latinas `« »` en prosa; las inglesas `" "` valen dentro de
  código y de texto de interfaz.
- Los decimales van con **coma** en prosa (`5,7 veces`); en código y en ejes generados por
  la librería, se deja lo que la librería produzca.

## Concisión

- Cortar muletillas: `de manera que` → `para`; `con el fin de` → `para`; `en el caso de
  que` → `si`; `realizar una comprobación` → `comprobar`; `llevar a cabo` → `hacer`.
- Cortar redundancias: `subir arriba`, `bajar abajo`, `entrar adentro`, `crear un nuevo`,
  `accidente fortuito`, `dos mitades iguales`, `planificar de antemano`.
- Preferir el verbo al sustantivo: `hacer el cálculo de` → `calcular`.
- Una idea por oración. Si hay tres comas y dos guiones, casi siempre son dos oraciones.
- No hay que acortar lo que ya es claro. La brevedad es un medio, no el objetivo.

## Dialecto y registro

- Español **neutro y técnico**. Sin `vos`, `che`, `chévere`, `ahorita`, `platica`, `carro`
  cuando `vehículo` es lo que se quiere decir, ni diminutivos afectivos.
- Sin exclamaciones ni signos de entusiasmo en la interfaz.
- Sin anglicismos que tengan término asentado: `deployar` → `desplegar`; `feature` →
  `variable` o `característica` según el caso; `performance` → `rendimiento`; `chart` →
  `gráfico`. Se conservan los que son nombre propio de una tecnología (`commit`, `pull
  request`, `endpoint`, `hover`).

## Lo que NO se toca

- Nombres de variables, funciones, claves de diccionario, columnas de datos.
- Cadenas que se comparan, se parsean o se afirman en una prueba. Se busca la cadena en el
  repositorio antes de tocarla: si aparece dos veces, una de ellas puede ser una clave.
- Unidades, cifras, rangos, nombres de circuitos y códigos de la empresa.
- El texto que ya está bien. Reescribir lo correcto es ruido en el diff.

## Ancho de los rótulos

Un rótulo de eje o un título de panel corregido **cambia de ancho**. En este repositorio
los paneles se calculan a partir de anchos medidos, así que después de tocar un rótulo hay
que volver a medirlo — hay memoria del proyecto sobre rótulos que dejaron de caber. Ver
`tests/test_rotulos_sin_traslape.py`.
