# Arquitectura y Flujo de Operación: Simulador de Criticidad CHEC

Este documento describe la arquitectura multi-agente y el flujo de información del Simulador de Criticidad, basado en los conceptos del contexto del proyecto (`ContextoProyectoSimuladorCHEC.md`). El sistema emplea agentes de IA de diferentes capacidades (Low/High), técnicas de Recuperación de Información (RAG) para análisis documental, y un modelo M-GCECDL pre-entrenado para analizar causas de fallas, simular escenarios de mejora en redes de distribución eléctrica de Nivel de Tensión 2, y generar reportes de evidencias.

---

## 1. Flujo de Información y Análisis Multimodal

El proceso integra datos estructurados (tabulares) y no estructurados (texto de normativas y bitácoras), culminando en la generación de evidencias:

1. **Selección del circuito o vano de interés:** El usuario selecciona el activo que desea analizar.
2. **Identificación de puntos de interés:** El sistema consulta la base tabular para recuperar los eventos asociados al mismo **vano** o circuito durante los 12 meses anteriores.
3. **Traducción semántica y diagnóstico retrospectivo:** El sistema describe cada punto de interés usando el diccionario de variables, sus modos y relaciones definidos en `ContextoProyectoSimuladorCHEC.md`, y analiza la evolución de `UITI` y `UITI_VANO` a lo largo del tiempo. Además, considera la relación entre días criticos del circuito, y los cambios en cantidad de eventos y UITI y UITI_VANO.
4. **Análisis Documental y Normativo (RAG):** En paralelo al paso 3, el sistema consulta un repositorio de documentos (PDFs, textos, docs). Revisa:
   - **Bitácoras de Intervenciones:** Extrae el registro de mantenimientos programados (ej. podas, reposiciones) e intervenciones de mitigación asociadas a la zona en el último año.
   - **Normativa de Sistemas de Potencia:** Extrae los lineamientos técnicos aplicables a la infraestructura afectada.
5. **Diagnóstico Preliminar agéntico descriptivo mejorado (bítacoras, historial y normativa):** Se consolida el evento actual con el historial tabular y el registro documental para plantear hipótesis de fallos tempranas.
6. **Inferencia del Modelo M-GCECDL:** Un modelo de IA predictiva procesa las variables tabulares del evento actual y entrega:
   - La predicción matemática de `UITI_VANO`.
   - **Máscaras de relevancia (Feature Importance):** Valores de 0 a 1 indicando qué características tienen mayor peso estadístico.
7. **Cotejo Analítico a Tres Vías (Razonamiento Cruzado):** El sistema realiza un cruce crítico y justifica las causas combinando los patrones históricos, las justificaciones de bitácoras/normas y las máscaras del modelo ML. Coteja diagnósticos en puntos 3, 5 y 6.
8. **Identificación de Escenarios Guiados:** Basado en el cotejo, se presenta una lista filtrada de variables candidatas a intervenir, estrictamente guiadas y validadas por los hallazgos en las bitácoras y la norma.
9. **Simulación "*What-If*":** El usuario modifica los valores de las variables sugeridas en la interfaz.
10. **Reevaluación Predictiva:** El modelo M-GCECDL procesa el nuevo escenario y proyecta el nuevo valor de `UITI_VANO`.
11. **Generación de Reporte de Evidencias:** El sistema compila y redacta automáticamente un informe técnico formal. Este documento expone el razonamiento cruzado, las pruebas estadísticas (máscaras y proyecciones) y las evidencias documentales (citas de bitácoras y normativas) que justifican tanto las causas del fallo como la viabilidad del escenario de intervención propuesto.

---

## 2. Arquitectura de Agentes de IA

La arquitectura multimodelo utiliza agentes especializados con cargas cognitivas acordes a su tarea.

### Agente 1: Descriptor de Contexto (Modelo *Low/Fast*)
- **Rol:** Traductor Semántico.
- **Función:** Convierte la fila de la base de datos en un resumen narrativo de condiciones iniciales.

### Agente 2: Analista Histórico Estructurado (Modelo *High/Reasoning*)
- **Rol:** Analista Forense de Datos.
- **Función:** Analiza el historial numérico del último año. Identifica estacionalidad y patrones de degradación en `UITI` y `UITI_VANO`.

### Agente 3: Analista Documental y RAG (Modelo *High/Context-Heavy*)
- **Rol:** Especialista en Normativa y Operaciones.
- **Función:** Lee bitácoras, reportes de poda e incidencias desde una base de datos vectorial (Vector Store). Coteja si el mantenimiento operativo en terreno se ejecutó según la normativa vigente.

### Orquestador del Modelo M-GCECDL (API / No LLM)
- **Rol:** Puente de Inferencia ML.
- **Función:** Ejecuta el modelo pre-entrenado y retorna las predicciones numéricas y el tensor de máscaras de relevancia.

### Agente 4: Consultor de Criticidad y Causalidad (Modelo *High/Reasoning*)
- **Rol:** Investigador Principal.
- **Función:** Es el núcleo de síntesis. Recibe los inputs matemáticos (Agente 2 y Orquestador) y cualitativos (Agente 3). Construye la narrativa causal justificando el fallo de forma robusta.

### Agente 5: Simulador y Evaluador de Escenarios (Modelo *Low/Fast*)
- **Rol:** Asistente Interactiva "What-If".
- **Función:** Gestiona la simulación iterativa con el usuario y ejecuta la reevaluación con el modelo M-GCECDL, validando matemáticamente si la intervención mejora la red.

### Agente 6: Redactor de Informes Técnicos (Modelo *High/Generative*)
- **Rol:** Generador de Reportes de Evidencia.
- **Función:** Toma la síntesis causal del Agente 4 y los resultados de simulación del Agente 5 para estructurar un reporte final técnico, claro y detallado. Expone argumentación sustentada en normativas, bitácoras operativas y validaciones de IA, listo para entrega a tomadores de decisión o entes regulatorios.

---

## 3. Diagrama de Arquitectura Multimodal y Flujo

El siguiente gráfico ilustra la interacción ampliada, integrando el flujo de repositorios documentales, simulación, y la consolidación en un reporte final.

```mermaid
graph TD
    %% Definición de Estilos
    classDef user fill:#f9f2f4,stroke:#333,stroke-width:2px;
    classDef agentLow fill:#d9edf7,stroke:#31708f,stroke-width:2px;
    classDef agentHigh fill:#dff0d8,stroke:#3c763d,stroke-width:2px;
    classDef db fill:#fcf8e3,stroke:#8a6d3b,stroke-width:2px;
    classDef model fill:#e2e2ea,stroke:#666,stroke-width:2px,stroke-dasharray: 5 5;
    classDef doc fill:#e2eedd,stroke:#5cb85c,stroke-width:2px;
    classDef outputDoc fill:#fff2cc,stroke:#d6b656,stroke-width:2px;

    %% Nodos
    User([Usuario / Operador]):::user
    DB[(Base de Datos Tabular)]:::db
    DocStore[(Repositorio Documental RAG\nNormas, PDFs, Bitácoras)]:::doc
    Contexto[Contexto.md KB]:::db
    
    A1[Agente 1: Descriptor\nModelo Low]:::agentLow
    A2[Agente 2: Analista Tabular\nModelo High]:::agentHigh
    A3[Agente 3: Analista Documental\nModelo High]:::agentHigh
    A4[Agente 4: Consultor Causalidad\nModelo High]:::agentHigh
    A5[Agente 5: Simulador Escenarios\nModelo Low]:::agentLow
    A6[Agente 6: Redactor Informes\nModelo High]:::agentHigh
    
    MP{{Modelo M-GCECDL\nPre-entrenado}}:::model
    Reporte[[Reporte de Evidencias\ny Razonamientos]]:::outputDoc

    %% Flujo Inicial
    User -->|1. Selecciona Evento| A1
    Contexto -.->|Diccionarios| A1
    Contexto -.->|Reglas Sistema| A4
    
    A1 -->|2. Descripción| A2
    A1 -->|2. Filtros Búsqueda| A3
    
    %% Flujo Histórico y Documental
    A2 -->|3a. Consulta 12 Meses| DB
    DB -->|Historial UITI y UITI_VANO| A2
    
    A3 -->|3b. Búsqueda Textos| DocStore
    DocStore -->|Normativa y Bitácoras| A3
    
    %% Inferencia ML
    A1 -->|Fila Actual| MP
    MP -->|4. Máscaras Relevancia| A4
    
    %% Cotejo Centralizado
    A2 -->|Patrones Numéricos| A4
    A3 -->|Justificación Documental| A4
    
    A4 -->|5. Cotejo: Análisis Causal| A4
    A4 -->|6. Opciones Intervención| A5
    A5 -->|Sugiere Opciones| User
    
    %% Ciclo de Simulación y Reporte
    User -->|7. Modifica Valores (What-If)| A5
    A5 -->|Nuevo Escenario| MP
    MP -->|Retorna Nuevo UITI_VANO| A5
    
    A4 -->|Síntesis Causal| A6
    A5 -->|Resultados de Simulación| A6
    
    A6 -->|8. Compila Argumentos| Reporte
    Reporte -->|Entrega Final| User
```

## Resumen del Ciclo de Valor Ampliado
1. **Comprender:** Desde la taxonomía numérica de fallas (`Agente 1`).
2. **Contextualizar Multimodalmente:** Cruzando el historial numérico de degradación (`Agente 2`) con la "historia operativa" registrada en bitácoras y regulada en normas (`Agente 3`).
3. **Validar Causas:** Contrastando el raciocinio humano/LLM cualitativo con inferencias matemáticas estrictas (`Agente 4` + `Modelo M-GCECDL`).
4. **Actuar Inteligentemente:** Diseñando simulaciones fundamentadas operativa y normativamente (`Agente 5`).
5. **Documentar y Soportar:** Generando de forma automática un reporte técnico exhaustivo que cristaliza las evidencias encontradas y los razonamientos inferidos (`Agente 6`), cerrando la brecha entre el análisis de IA y la toma de decisiones empresariales.
