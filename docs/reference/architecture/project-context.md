# Contexto y Arquitectura: Simulador de Criticidad CHEC

**Propósito del Sistema:**
Desarrollo de modelos de Inteligencia Artificial (predictiva, generativa y agéntica) orientados al análisis de fallas en redes de distribución eléctrica de Nivel de Tensión 2. El objetivo es evaluar el impacto de estas fallas mediante UiTi y su ponderación por vano (`UITI_VANO`).

**Directriz para el Agente de IA:**
El agente debe utilizar este documento como contexto base (Knowledge Base) para:
1. Identificar e inferir posibles causas de fallos basadas en las variables del entorno y la infraestructura.
2. Analizar e interpretar el histórico de eventos y su propagación topológica.
3. Plantear y evaluar escenarios de simulación "*What-If*" (qué pasa si), alterando valores en las características para predecir mediante IA el aumento o disminución de `UITI_VANO`.

---

## 1. Entradas del Sistema: Base de Datos de Eventos

La fuente principal de información es una base de datos tabular. Cada **fila representa un evento de falla** y cada **columna representa una característica** asociada al fallo, la red, el entorno o el impacto demográfico.

### 1.1. Diccionario de Variables Estáticas y de Activos

| Variable | Descripción |
| :--- | :--- |
| **CIRCUITO** | Código del circuito al que pertenece el vano. |
| **FID_SW** | FID del equipo de maniobra/protección que opera si el vano falla. |
| **COD_EQ_PROTEGE** | Código del equipo que opera si el vano falla. |
| **FID_VANO** | FID (identificador espacial/único) del vano de red. |
| **T_USUS_EQ_PROT** | Total de usuarios desconectados cuando el equipo que protege abre. |
| **LVSW** | Longitud de red desde el vano hasta el equipo que opera durante la falla. |
| **CNT_VN** | Cantidad de vanos existentes desde el punto de falla hasta el equipo que lo protege. |
| **CNT_VN_SW** | Cantidad total de vanos protegidos por el equipo que opera. |
| **FECHA** | Fecha y hora exacta de la falla. |
| **DURACION** | Duración total de la interrupción. |
| **UITI** | Indicador UiTi (Usuarios Interrumpidos x Tiempo de Interrupción) presentado durante la falla. |
| **UITI_VANO** | UiTi de la falla ponderado por el aporte relativo del vano. |
| **TOT_USUS** | Total de usuarios afectados por la falla. |
| **CNT_TRF** | Cantidad de transformadores afectados en la falla. |
| **COD_CAUSA** | Código (estándar EPM) de la causa de falla. |
| **DESC_CAUSA** | Descripción textual de la causa de falla. |
| **TIPO** | Tipo de equipo que protege al vano (ej. reconectador, fusible). |
| **PORC_APORTE_VANO** | Ponderación del vano en el conjunto de vanos protegidos por el equipo. |
| **LONGITUD** | Longitud física del vano. |
| **CNT_FASES** | Cantidad de fases eléctricas del vano. |
| **CONDUCTOR** | Tipo/material del conductor de las fases del vano. |
| **CALIBRE_NEUTRO** | Calibre del cable neutro. |
| **NG_RED** | Indicador de si el vano posee cable de guarda o neutro. |
| **FECHA_OPERACION_VANO** | Fecha de entrada en operación (energización) del vano. |
| **X1, Y1** | Coordenadas espaciales iniciales del vano. |
| **X2, Y2** | Coordenadas espaciales finales del vano. |
| **COD_APOYO_FIN** | Código del apoyo (poste/torre) final del vano. |
| **FID_APOYO_FIN** | FID del apoyo final del vano. |
| **ALTURA** | Altura del apoyo final del vano. |
| **CANTIDAD_TIERRA** | Indicador de presencia de puesta a tierra en el apoyo. |
| **PROPIETARIO** | Entidad propietaria del apoyo. |
| **CLASE** | Clase mecánica o material del apoyo. |
| **ELEMENTO** | Tipo de elemento de soporte (poste, cámara, torre). |
| **NORMA** | Código de la estructura eléctrica estandarizada. |
| **VAL_CRIT_APOYO** | Calificación de criticidad basada en la clase de apoyo. |
| **FID_TRAFO** | FID del transformador ubicado en el apoyo final del vano. |
| **CODIGO** | Código del transformador en el apoyo final. |
| **CAPACIDAD_NOMINAL** | Capacidad nominal (kVA) del transformador. |
| **CNT_USUS** | Cantidad de usuarios conectados al transformador. |
| **FECHA_OPERACION_TRF**| Fecha de entrada en operación del transformador. |
| **PROMEDIO_KWH_TRF** | Promedio mensual de energía (consumo) del transformador. |
| **TIPO_TAX** | Tipo de taxonomía constructiva del vano. |
| **NR_T** | Nivel de riesgo asociado a la vegetación cercana al vano. |
| **LONG_CRUCETA** | Longitud de la cruceta instalada en el apoyo final. |
| **PROMEDIO_KWH_VANO** | Promedio mensual de energía que circula por el vano. |
| **DDT** | Densidad de Descargas a Tierra (rayos) promedio por año en la zona. |

### 1.2. Variables de Series Temporales (Climáticas)
*Nota Crítica:* El sufijo `_{i}` indica que la variable se evalúa en 12 ventanas horarias previas al evento (`i = 0...11`). Esto permite capturar la **acumulación de estrés ambiental** antes de la disrupción.

| Variable | Descripción |
| :--- | :--- |
| **prep_{i}** | Precipitación total acumulada durante la hora precedente, en mm. |
| **clouds_{i}** | Cobertura nubosa total, expresada como porcentaje del cielo cubierto. |
| **wind_spd_{i}** | Velocidad instantánea del viento a 10 metros, en km/h. |
| **wind_gust_spd_{i}** | Velocidad máxima de las ráfagas a 10 metros, en km/h. |
| **temp_{i}** | Temperatura instantánea del aire a 2 metros, en °C. |
| **pres_{i}** | Presión atmosférica reducida al nivel del mar, en hPa. |
| **sp_{i}** | Presión atmosférica en la superficie, en hPa. |
| **rh_{i}** | Humedad relativa del aire a 2 metros, en %. |
| **solar_rad_{i}** | Radiación solar de onda corta, en W/m². |

---

## 2. Agrupación Lógica: Modos de las Variables de Entrada

Para facilitar el análisis multimodal y el procesamiento por redes neuronales o agentes, el **grafo completo representa 156 nodos** subdivididos en 6 modos conceptuales. Este número no corresponde a una etapa de reducción del dataset: combina las 48 variables no climáticas con las 9 familias climáticas representadas en 12 ventanas cada una.

### Modo A: Evento, Impacto e Indicadores (8 variables)
Representa la "verdad terreno" (*ground truth*) de las fallas operativas. Captura la duración, el impacto, las causas, `UITI` y el objetivo ponderado `UITI_VANO`.
*Variables:* `FECHA`, `DURACION`, `UITI`, `UITI_VANO`, `TOT_USUS`, `CNT_TRF`, `COD_CAUSA`, `DESC_CAUSA`.

### Modo B: Infraestructura de Protección y Maniobra (5 variables)
Agrupa los equipos encargados de detectar, despejar y aislar las fallas (interruptores, reconectadores, fusibles). Define la lógica de segmentación física y la cantidad de usuarios potencialmente expuestos ante la apertura de un equipo.
*Variables:* `FID_SW`, `COD_EQ_PROTEGE`, `TIPO`, `CNT_VN_SW`, `T_USUS_EQ_PROT`.

### Modo C: Topología y Configuración Espacial (9 variables)
Define la geometría de la red, la pertenencia a circuitos específicos y las métricas de distancia e impacto ponderado de cada vano respecto a su nodo de protección. **Fundamental para algoritmos de grafos y agentes de enrutamiento.**
*Variables:* `CIRCUITO`, `FID_VANO`, `X1`, `Y1`, `X2`, `Y2`, `LVSW`, `CNT_VN`, `PORC_APORTE_VANO`.

### Modo D: Características Físicas y Eléctricas del Vano (8 variables)
Variables técnico-constructivas del tramo de red aérea o subterránea. Determinan la capacidad de conducción, los límites térmicos y la susceptibilidad del conductor a fallas mecánicas o eléctricas.
*Variables:* `FECHA_OPERACION_VANO`, `LONGITUD`, `CNT_FASES`, `CONDUCTOR`, `CALIBRE_NEUTRO`, `NG_RED`, `PROMEDIO_KWH_VANO`, `TIPO_TAX`.

### Modo E: Activos (Apoyo Final y Transformador) (16 variables)
Detalla la infraestructura de soporte físico (postes, torres) al final del vano y los activos de transformación de distribución asociados. Proporciona contexto sobre el estado constructivo y la carga promedio de los usuarios terminales.
*Variables:* `COD_APOYO_FIN`, `FID_APOYO_FIN`, `PROPIETARIO`, `CLASE`, `ELEMENTO`, `NORMA`, `ALTURA`, `LONG_CRUCETA`, `CANTIDAD_TIERRA`, `VAL_CRIT_APOYO`, `FID_TRAFO`, `CODIGO`, `CAPACIDAD_NOMINAL`, `CNT_USUS`, `FECHA_OPERACION_TRF`, `PROMEDIO_KWH_TRF`.

### Modo F: Entorno, Riesgo y Clima (110 nodos en el grafo)
Factores exógenos y ambientales que actúan como estresores físicos y disparadores principales (*triggers*) de fallas mecánicas y dieléctricas. El grafo conserva las 9 familias climáticas disponibles y representa 12 horas por familia (108 nodos dinámicos), además de `NR_T` y `DDT`.
*Nodos climáticos del grafo:* `NR_T`, `DDT`, `prep_{i}`, `temp_{i}`, `wind_gust_spd_{i}`, `wind_spd_{i}`, `clouds_{i}`, `pres_{i}`, `sp_{i}`, `rh_{i}`, `solar_rad_{i}`, con `i = 0...11`.

---

## 3. Grafo No Dirigido: Análisis de Dependencias e Interacciones

Para conectar los 156 nodos representados en el grafo completo en un modelo cohesivo (ej. Graph Neural Networks o inferencia bayesiana), se modelan las interacciones fundamentales. Dada la expansión temporal del clima, las series temporales se conectan a "nodos concentradores" (hubs) que representan el estrés ambiental general, o se conectan secuencialmente para modelar la acumulación del riesgo.

### 3.1. Tabla Descriptiva de Conexiones Clave (Reglas Físico/Lógicas)
El agente debe aplicar estas reglas de causalidad y propagación al razonar sobre la red:

| Grupo Origen | Grupo Destino | Tipo de Relación / Peso | Justificación Técnica (Dominio Eléctrico) |
| :--- | :--- | :--- | :--- |
| **Series Climáticas** (`temp_{i}`, `prep_{i}`, etc.) | **Nodos de Riesgo** (Modo F) | Acumulación Ambiental (0.85) | *Física Atmosférica:* Las variables climáticas de horas previas (ej. lluvias continuas `prep_3` a `prep_0`) saturan el suelo y contaminan aisladores. El viento en ráfagas interactúa dinámicamente con la temperatura (dilatación de conductores). |
| **Entorno y Riesgo** (`NR_T`, `DDT`, `wind_gust_spd_0`) | **Eventos / Causa** (`COD_CAUSA`, `DESC_CAUSA`) | Causa Directa (0.90) | *Física de Potencia:* La interacción final entre riesgo vegetal, descargas directas y ráfagas en el *instante cero* rompe el aislamiento dieléctrico o mecánico, desencadenando la falla. |
| **Físicas y Eléctricas** (`CONDUCTOR`, `LONGITUD`, etc.)| **Eventos / Causa** (`COD_CAUSA`) | Susceptibilidad Material (0.80) | *Estructural/Eléctrica:* El cable de guarda (`NG_RED`) mitiga rayos. Un conductor desnudo fallará fácilmente ante el toque de una rama; uno semiaislado resistirá. Mayor longitud incrementa el área de exposición. |
| **Topología** (`LVSW`, `CNT_VN`, `CIRCUITO`, `FID_VANO`) | **Protección** (`FID_SW`, `COD_EQ_PROTEGE`) | Propagación de Falla (0.95) | *Lógica de Protección:* Cuando el vano falla, la falla viaja eléctricamente buscando la protección más cercana. La distancia (`LVSW`) y cantidad de vanos (`CNT_VN`) determinan qué equipo debe operar para aislar el daño. |
| **Activos Finales** (`VAL_CRIT_APOYO`, `ALTURA`, etc.) | **Entorno y Riesgo** (`NR_T`) | Vulnerabilidad Estructural (0.75) | *Mecánica/Estructural:* La altura del poste interactúa con el dosel de los árboles. La norma y clase del poste determinan si soporta la tensión de un árbol cayendo o colapsa. |
| **Carga y Consumo** (`CAPACIDAD_NOMINAL`, `CNT_USUS`) | **Impacto** (`TOT_USUS`, `CNT_TRF`) | Impacto Demográfico (0.85) | *Consumo/Socioeconomía:* La cantidad de usuarios conectados al transformador y su demanda de energía dictan directamente la magnitud del corte. |
| **Protección** (`TIPO`, `T_USUS_EQ_PROT`) | **Impacto** (`DURACION`, `TOT_USUS`) | Aislamiento y Tiempos (0.80) | *Operativa:* Operación de fusible = duración larga (requiere visita a terreno). Reconectador = duración corta. El equipo operado determina el total de usuarios desconectados (`TOT_USUS`). |
| **Eventos** (`DURACION`, `TOT_USUS`) | **Impacto** (`UITI`) | Cálculo del Impacto (1.00) | UiTi relaciona la duración del evento con el total de usuarios afectados. |
| **Impacto y Topología** (`UITI`, `PORC_APORTE_VANO`) | **Objetivo por vano** (`UITI_VANO`) | Ponderación por Vano (1.00) | UiTi se distribuye según el aporte relativo del vano para obtener el objetivo de análisis. |
| **Atributos Espaciales** (`X1`, `Y1`, `X2`, `Y2`) | **Topología** (`FID_VANO`) | Geometría de Red (1.00) | *Sistemas de Información Geográfica (SIG):* Las coordenadas definen la existencia física, trazado y longitud del tramo. |
