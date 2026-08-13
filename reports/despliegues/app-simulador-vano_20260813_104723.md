# Bitacora de despliegue

| | |
|---|---|
| Comando | /app-simulador-vano |
| Cuaderno | notebooks/old_version/06_uiti_vano_explicabilidad_simulador.ipynb |
| Inicio | 2026-08-13 10:47:23 |
| Cierre | 2026-08-13 11:18:55 |
| Estado final | **INCOMPLETO** |

## Resumen

- **2 pasos**: 1 ok, 1 omitido
- **0 restricciones**

## Restricciones y errores

Sin restricciones registradas.

## Pasos

| # | Paso | Estado | Detalle |
|---|---|---|---|
| 0 | Datos de entrada del usuario | `ok` | Nombre de la app confirmado: simulador-vano (cumple el patron 2-30 caracteres, minusculas y guiones). Quedo pendiente la URL del workspace: el usuario pidio que el destino se pregunte en CADA corrida y no se deduzca de cual perfil del CLI reporta sesion vigente, asi que no se preselecciono ninguno. |
| 1-9 | Resto de la corrida (perfil, preflight, paquete, subida, app, despliegue, verificacion) | `omitido` | No se ejecutaron: el usuario detuvo la corrida antes de entregar la URL del workspace. Sin workspace no hay perfil que resolver, y todo lo demas cuelga de eso. No se creo, modifico ni borro nada en ningun workspace de Databricks; tampoco se construyo el paquete local. |

## Detalle por paso

### Paso 0 -- Datos de entrada del usuario  `ok`

```
databricks auth profiles
```

```
amalvarezme@unal.edu.co (Default)  https://dbc-37136961-b637.cloud.databricks.com  NO
andresmarino07@gmail.com           https://dbc-24ddce05-76d1.cloud.databricks.com  NO
azure-chec                         https://adb-418048194347500.0.azuredatabricks.net  YES
```


## Cierre

Corrida detenida por instruccion explicita del usuario en el paso 0. No es una restriccion externa: no se encontro ningun bloqueo de permisos, cupo ni plataforma, sencillamente no se llego a intentar nada.
