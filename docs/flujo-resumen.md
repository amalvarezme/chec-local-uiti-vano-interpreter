# ¿Cómo funciona el proyecto? — Guía sencilla

> Versión sin jerga técnica. Si buscas el detalle con nombres de archivos, comandos y diagramas completos, ve a [`flujo-detallado.md`](./flujo-detallado.md).

## ¿Para qué sirve esto?

CHEC opera líneas eléctricas de distribución divididas en **circuitos**. Cada circuito tiene muchos tramos pequeños llamados **vanos**. Cuando algo falla (una caída de energía, un daño en un poste, etc.), el sistema registra ese evento y lo asocia a un indicador llamado **UITI_VANO**, que mide qué tan grave fue el impacto de esa falla para los usuarios conectados a ese tramo.

Este proyecto toma todo ese historial de eventos y responde dos preguntas:

1. **¿Qué tan crítico es cada circuito** comparado con los demás, y por qué?
2. **¿Qué variables influyen más** en que una falla sea grave (el clima, el tipo de conductor, la cantidad de usuarios, la antigüedad del equipo, etc.)?

Para responder esto se usan dos caminos que llegan a destinos distintos pero parten de la misma información.

## Camino 1 — El reporte de un circuito

Cuando alguien pide el análisis de un circuito, esto es lo que pasa, en orden:

1. **Se seleccionan los datos** del circuito y el periodo de tiempo pedido.
2. **Un sistema automático** (no una persona) revisa esos datos y detecta los puntos donde el impacto fue más alto.
3. **Tres "asistentes" de inteligencia artificial trabajan en paralelo**, cada uno mirando el mismo caso desde un ángulo distinto:
   - Uno explica **qué pasó** (diagnóstico histórico, en lenguaje natural).
   - Otro explica **qué variables pesaron más** en la predicción de un modelo estadístico entrenado previamente.
   - Un tercero hace una prueba de "**qué pasaría si**" cambiara una variable (por ejemplo, si el clima hubiera sido distinto).
4. Cuando los dos primeros terminan, **un cuarto asistente compara** ese análisis contra lo que dicen documentos técnicos de expertos humanos (informes en PDF), para señalar coincidencias o diferencias.
5. Con todo eso, se arma **un reporte en una página web** (HTML) que cualquier persona puede abrir en el navegador — sin necesidad de instalar nada.
6. Opcionalmente, ese reporte también se guarda en un archivo indexado, para poder buscarlo o relacionarlo con otros circuitos más adelante.

Este mismo proceso se puede pedir para **un circuito**, para **un grupo de circuitos** (por ejemplo, "todos los de riesgo alto"), o como **un informe gerencial** que resume varios circuitos representativos a la vez.

## Camino 2 — El panel visual en Databricks

Además del reporte por circuito, existe un **panel de control visual** (un "dashboard") hospedado en Databricks, una plataforma en la nube. Ahí se puede ver, con gráficos interactivos:

- Un mapa comparando qué tan críticos son todos los circuitos entre sí.
- Un mapa geográfico con los vanos, transformadores e interruptores de un circuito.
- La evolución diaria de eventos e impacto a lo largo del tiempo.

Para que ese panel exista, alguien ejecuta un proceso que:

1. **Copia los datos crudos** (el mismo historial de eventos) a un almacenamiento en la nube.
2. **Copia el código real del análisis** — no una versión aparte reescrita a mano, sino exactamente el mismo código que corre localmente, para que los números coincidan siempre con los del reporte por circuito.
3. **Reconstruye las mismas tablas de datos** dentro de la nube.
4. **Publica el panel visual** con esas tablas conectadas.

**Importante:** este panel en la nube es una **copia independiente**. Si alguien cambia algo en el análisis local, esa copia en Databricks no se actualiza sola — hay que volver a correr el proceso de copiado para que refleje el cambio.

## Lo que nunca se mezcla

La página web pública del proyecto (la que muestra los resultados de forma bonita para consulta general) **solo se genera y actualiza desde un computador local**, nunca desde la nube. Esto es intencional: evita que se acumulen archivos innecesarios o desactualizados en Databricks, y mantiene un único lugar responsable de esa publicación.

## Glosario rápido

| Término | En palabras simples |
|---|---|
| **Circuito** | Una línea eléctrica de distribución completa, con muchos tramos. |
| **Vano** | Un tramo pequeño dentro de un circuito, entre dos postes. |
| **UITI_VANO** | Un número que mide qué tan grave fue el impacto de una falla en un vano específico. |
| **Criticidad** | Qué tan grave es, en general, un circuito comparado con los demás (de "muy alto riesgo" a "riesgo bajo"). |
| **Agente de IA** | Un asistente automático que lee datos y redacta una explicación en lenguaje natural, siguiendo reglas estrictas de validación. |
| **Dashboard** | Un panel visual interactivo en la nube, con gráficos y mapas que se pueden filtrar. |
| **Databricks** | La plataforma en la nube donde vive ese panel visual. |
