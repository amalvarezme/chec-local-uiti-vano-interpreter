# ¿Cómo funciona el proyecto? — Guía sencilla

> Versión sin jerga técnica. Si buscas el detalle con nombres de archivos, comandos y diagramas
> completos, ve a [`flujo-detallado.md`](./flujo-detallado.md).

## ¿Para qué sirve esto?

CHEC opera líneas eléctricas de distribución divididas en **circuitos**. Cada circuito tiene muchos
tramos pequeños llamados **vanos**. Cuando algo falla —una caída de energía, un daño en un poste—
el sistema registra ese evento y lo asocia a un indicador llamado **UITI_VANO**, que mide qué tan
grave fue el impacto para los usuarios conectados a ese tramo.

El proyecto toma todo ese historial y responde tres preguntas:

1. **¿Qué tan crítico es cada circuito** comparado con los demás, y por qué?
2. **¿Qué variables influyen más** en que una falla sea grave: el clima, el tipo de conductor, la
   cantidad de usuarios, la antigüedad del equipo.
3. **¿Qué pasaría si** se interviniera un vano concreto — y cuánto costaría esa intervención.

Todo sale del mismo archivo de historial. De ahí para adelante hay cuatro piezas.

## Pieza 1 — El modelo que predice

Un modelo estadístico aprende a estimar el impacto de un vano durante una ventana de tiempo, a
partir de los eventos que ocurrieron ahí. Se entrena una vez, se guarda en un archivo, y de ahí en
adelante **todo lo demás solo lo lee**: ni el reporte ni el simulador pueden reentrenarlo. Eso está
verificado automáticamente, no es una promesa.

Una cosa que el proyecto dice en voz alta en vez de esconder: el modelo **ordena bien** —acierta
cuáles vanos son peores que cuáles— pero **su nivel corre alto**, cerca de un 34%. Por eso, cada
vez que se muestra una predicción al lado de una medición real, se muestra también ese margen de
error. Un número del modelo nunca se presenta como si fuera una medición.

## Pieza 2 — Los asistentes que redactan

Cuatro asistentes de inteligencia artificial escriben las explicaciones en lenguaje natural. Cada
uno mira el mismo caso desde un ángulo distinto:

- Uno explica **qué pasó** en ese circuito durante ese periodo.
- Otro explica **qué dice el modelo**: qué variables mueven el impacto de cada vano, cuál es el
  vano crítico y qué plan tendría sentido sobre él.
- Un tercero **compara** todo eso contra lo que dicen los informes técnicos de expertos humanos, en
  PDF, para señalar coincidencias y diferencias.
- Un cuarto se encarga de **leer esos PDF** y decidir qué párrafos son discusión técnica aprovechable.

Ninguno inventa: cada asistente recibe un paquete de datos ya seleccionado por el programa y solo
puede citar lo que viene ahí. Además, cada uno revisa su propia respuesta contra una plantilla
antes de entregarla. Si no pasa la revisión, se reintenta o se guarda como falla explícita — nunca
se publica algo sin validar.

## Pieza 3 — Los reportes

Cuando alguien pide el análisis de un circuito, esto es lo que pasa:

1. Se confirman el circuito y las fechas. Si el circuito no existe o no hubo eventos en ese
   periodo, se avisa y se para ahí mismo.
2. El programa selecciona los datos y arma el contexto, incluido lo que el modelo predice para
   **hasta tres ventanas de tiempo** del circuito.
3. Los dos primeros asistentes trabajan **en paralelo**; cuando terminan, entra el que compara
   contra los informes de expertos.
4. Se arma **un reporte en una página HTML** que cualquiera abre en el navegador, sin instalar nada.
5. El reporte también se guarda en un archivo indexado, para poder buscarlo y relacionarlo con
   otros circuitos más adelante.

Lo mismo se puede pedir para **un circuito**, para **un grupo entero** (por ejemplo, todos los de
riesgo alto) o como **un informe gerencial** que sintetiza varios circuitos representativos a la vez.

## Pieza 4 — Las aplicaciones

Seis aplicaciones de escritorio, para Mac y para Windows, **sin conexión a internet y sin
servidor**. Se abren con doble clic:

| Aplicación | Qué muestra |
|---|---|
| **CriticidadCHEC** | El menú: abre, vigila y cierra las otras cinco desde una sola ventana |
| **Clima** | Cada vano sobre el mapa, con las variables de clima y su serie de tiempo |
| **Agrupamiento de vanos** | Qué vanos se parecen entre sí por impacto acumulado y número de eventos |
| **Trayectorias de circuitos** | Cómo se mueve cada circuito en el tiempo, con una ventana deslizante |
| **Trayectorias de vanos** | Lo mismo, un nivel más abajo |
| **Simulador** | *Qué pasaría si* se cambia una variable de un vano — y cuánto cuesta esa intervención |

Las cinco primeras se preparan una vez y después abren en menos de un segundo, porque todo el
cálculo ya está hecho y la interacción vive en el navegador. El **simulador** es distinto: cada vez
que se presiona "Simular" vuelve a preguntarle al modelo, así que necesita el programa corriendo
por detrás.

Todas vigilan sus datos: si cambia el historial de eventos, el modelo o la lista de variables, se
reconstruyen solas la próxima vez que se abren. No hay que acordarse de nada.

## La misma cosa, pero en la nube

Las mismas aplicaciones se pueden publicar en **Databricks**, la plataforma en la nube de CHEC,
para que se abran desde una dirección web sin instalar nada en el computador. Un comando copia los
datos, sube el código y publica cada tablero.

Tres cosas que conviene saber:

- **Es una copia independiente.** Si alguien cambia el análisis local, la nube no se entera sola:
  hay que volver a subir.
- **Caben tres aplicaciones a la vez.** El espacio de trabajo tiene ese tope, así que se publican
  por prioridad.
- **El estado de la nube no es durable.** Un espacio verificado como completo un día apareció vacío
  al siguiente, así que el proceso siempre comprueba antes de dar algo por hecho.

Y una regla de fondo: cuando el proceso choca con un permiso que no tiene, **no se detiene** —
lo anota y sigue. Así, al final, entrega la lista completa de lo que hace falta pedirle al
administrador, en vez de morir en el primer obstáculo.

## Glosario rápido

| Término | En palabras simples |
|---|---|
| **Circuito** | Una línea eléctrica de distribución completa, con muchos tramos. |
| **Vano** | Un tramo pequeño dentro de un circuito, entre dos postes. |
| **UITI_VANO** | Un número que mide qué tan grave fue el impacto de una falla en un vano. |
| **Ventana** | Un periodo de tiempo recortado del historial, para mirar el circuito por tramos. |
| **Criticidad** | Qué tan grave es un circuito comparado con los demás, de riesgo bajo a muy alto. |
| **Modelo** | Un programa que aprendió del historial a estimar el impacto de un vano. |
| **Agente de IA** | Un asistente que lee datos ya seleccionados y redacta una explicación, con reglas estrictas de validación. |
| **Databricks** | La plataforma en la nube donde se publican las aplicaciones. |
