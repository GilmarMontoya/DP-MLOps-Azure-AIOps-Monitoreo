---
name: azureml-model-monitoring
description: Crea Model Monitoring de Azure Machine Learning (la pantalla Monitoring de ml.azure.com) sobre un modelo YA desplegado en un managed online endpoint — activa la data collection (model_inputs / model_outputs) en el deployment, genera trafico normal y con drift a proposito, y programa el monitor (data drift + data quality contra los datos de entrenamiento) con alertas por email. Pensado para aula: VM mas barata, Spark serverless solo mientras corre y skill de borrado. Usar cuando el usuario pida "monitorear el modelo", "model monitoring", "data drift", "prediction drift", "calidad de datos en produccion", "¿el modelo sigue prediciendo bien?", "la pantalla Monitoring de Azure ML esta vacia", "+ Add en Monitoring", o escriba /azureml-model-monitoring.
---

# Crear Model Monitoring sobre un endpoint de Azure ML

Responde la pregunta **"¿el modelo sigue prediciendo bien con los datos nuevos?"**.
No confundir con Azure Monitor (`/crear-azure-monitor`), que responde "¿el
endpoint está sano?" (latencia, errores, CPU). Son capas distintas.

Plantillas en `scripts/`: `deployment-data-collection.plantilla.yml`, `monitor.plantilla.yml`, `enviar_trafico.py`. Ejemplo real resuelto: Módulo 3 Sesión 6, carpeta `Azure-ML-Model-Monitoring/`.
Para desmontar: `/azureml-model-monitoring-cleanup`.

## Cómo funciona (explícaselo al usuario en 3 líneas si no lo tiene claro)

```
Cliente ─► Endpoint (data collection ON) ─► blob: model_inputs / model_outputs
                                                   │
Datos de entrenamiento (baseline) ─────────────────┤
                                                   ▼
            Monitor (schedule diario, Spark serverless) ─► dashboard en Monitoring + email
```

## Paso 1 — Requisitos y contexto

```bash
az account show --query name -o tsv
az ml workspace list --query "[].{ws:name, rg:resourceGroup, loc:location}" -o table
```

Si no hay sesión, pide al usuario `! az login`. En zsh **no metas `-g X -w Y` en
una variable** (no se separa en palabras): usa `G=...; WS=...` y `-g $G -w $WS`.

## Paso 2 — Elegir el endpoint y diagnosticarlo (solo lectura)

```bash
az ml online-endpoint list -g $G -w $WS --query "[].{name:name,traffic:traffic}" -o json
az ml online-deployment list -g $G -w $WS -e <ENDPOINT> \
  --query "[].{name:name,model:model,vm:instance_type,dc:data_collector,script:code_configuration.scoring_script}" -o json
```

- `dc: null` → la data collection está apagada. Es lo normal; se activa en el paso 3.
- `script: null` + modelo `mlflow_model` → **no-code deployment**. Azure ML
  instrumenta la recolección solo, no hace falta `score.py`.
- Si tiene `score.py` propio, la recolección necesita `azureml-ai-monitoring`
  (`Collector`) dentro del script: avísale al usuario, es otro flujo.
- Si hay varios endpoints, señala los que cobran 24/7 sin uso (con precio).

Averigua la **tarea**, el **target** y el **baseline** desde el job de AutoML:

```bash
az ml model show -g $G -w $WS -n <MODELO> -v <VER> --query "{type:type,job:job_name}" -o json
az ml job show -g $G -w $WS -n <JOB_AUTOML_PADRE> \
  --query "{task:task,target:target_column_name,train:training_data}" -o json
```

El `job_name` del modelo es un hijo (`..._272`); el padre es sin el sufijo.
El `training_data.path` dice qué data asset MLTable usar como baseline
(`azureml:<nombre>:<version>`).

## Paso 3 — Activar data collection

Escribe el YAML con el **mismo** nombre de deployment, modelo y VM (es un update):

```yaml
$schema: https://azuremlschemas.azureedge.net/latest/managedOnlineDeployment.schema.json
name: <DEPLOYMENT>
endpoint_name: <ENDPOINT>
model: azureml:<MODELO>:<VER>
instance_type: Standard_DS1_v2   # la mas barata que aceptan los managed online endpoints
instance_count: 1
data_collector:
  collections:
    model_inputs:
      enabled: 'True'
    model_outputs:
      enabled: 'True'
```

```bash
az ml online-deployment update -f deployment-data-collection.yml -g $G -w $WS
```

- Tarda ~10 min (córrelo en background). El endpoint sigue respondiendo.
- El aviso *"Standard_DS1_v2 may be too small… Minimum recommended DS3_v2"* es
  solo una recomendación: un modelo tabular de AutoML corre bien en DS1_v2
  ($0.086/h en brazilsouth). DS3_v2 cuesta ~4x.
- **Confirma con el usuario antes**: modifica un deployment real.

## Paso 4 — Generar tráfico

Sin tráfico el monitor no tiene nada que analizar. Usa
`scripts/enviar_trafico.py` (cópialo al proyecto) (adáptale `ENDPOINT`,
`DEPLOYMENT`, columnas y `aplicar_drift`):

```bash
uv run enviar_trafico.py --modo normal --filas 400
uv run enviar_trafico.py --modo drift  --filas 400
```

- Obtiene URL y key con `az` en tiempo de ejecución: nunca las escribas en un
  archivo ni las imprimas.
- Payload de un modelo MLflow: `{"input_data": {"columns", "index", "data"}}`
  (`df.to_json(orient="split")`).

Verifica que aparecieron los data assets de producción:

```bash
az ml data list -g $G -w $WS --query "[?contains(name,'model_')].name" -o tsv
# <endpoint>-<deployment>-model_inputs / -model_outputs
```

**Trampa:** la predicción de un modelo MLflow se guarda en una columna llamada
`"0"`, no con el nombre del target (`charges`). Por eso *prediction drift* contra
los datos de entrenamiento no cuadra directo; arranca con data drift + data
quality. Para revisar el esquema real descarga un blob de
`modelDataCollector/<endpoint>/<deployment>/model_outputs/` con
`az storage blob download --auth-mode key`.

## Paso 4b — Cuota de vCPU para Spark (revisar SIEMPRE antes de crear)

El monitor corre en Spark serverless (`standard_e4s_v3`, 4 vCPU por nodo,
driver + executor ⇒ **≥ 8 vCPU libres**) y consume la cuota regional de Azure
ML. Si no cabe, los pasos quedan en **Queued para siempre, sin error** (pasó:
45+ min en cola con 14/20 vCPU usadas).

```bash
SUB=$(az account show --query id -o tsv)
az rest --method get --url "https://management.azure.com/subscriptions/$SUB/providers/Microsoft.MachineLearningServices/locations/<region>/usages?api-version=2024-04-01" \
  --query "value[?currentValue>\`0\`].{q:name.localizedValue,uso:currentValue,limite:limit}" -o table
```

- Cada endpoint reserva **el doble** de sus vCPU (para upgrades sin corte):
  un D2as_v4 ocupa 4. Las **compute instances detenidas también ocupan** cuota.
- Si `limite - uso` de *Total Cluster Dedicated Regional vCPUs* es < 8: libera
  (endpoints sin uso, compute instances viejas) **con confirmación del usuario**,
  o pide aumento de cuota.
- La lista de Monitoring muestra el estado de la corrida **más reciente**: si
  disparaste una manual y la cancelaste, sale "Canceled" aunque la automática
  siga corriendo. Revisa *Job history* del monitor.

## Paso 5 — Crear el monitor

Pide el **correo** para las alertas (la CLI lo exige: sin él falla con
*"The value for '.emails' is missing"*). No lo asumas: ofrece el de
`az account show --query user.name` y que el usuario confirme.

Plantilla: `scripts/monitor.plantilla.yml`. Lo esencial:

```yaml
$schema: http://azureml/sdk-2-0/Schedule.json
name: monitor-<algo>
tags: {lab: model-monitoring}
trigger: {type: recurrence, frequency: day, interval: 1}
create_monitor:
  compute: {instance_type: standard_e4s_v3, runtime_version: "3.4"}
  monitoring_target:
    ml_task: regression            # classification | regression
    endpoint_deployment_id: azureml:<ENDPOINT>:<DEPLOYMENT>
  monitoring_signals:
    data_drift_vs_entrenamiento:
      type: data_drift
      reference_data:
        input_data: {path: azureml:<BASELINE>:<VER>, type: mltable}
        data_context: training
      features: [<solo las features, SIN el target>]
      alert_enabled: true
      metric_thresholds:
        numerical: {jensen_shannon_distance: 0.1}
        categorical: {jensen_shannon_distance: 0.1}
    calidad_de_datos:
      type: data_quality
      reference_data: (igual que arriba)
      features: [...]
      alert_enabled: true
      metric_thresholds:
        numerical: {null_value_rate: 0.05, out_of_bounds_rate: 0.03}
        categorical: {null_value_rate: 0.05, out_of_bounds_rate: 0.03}
  alert_notification:
    emails: [<CORREO>]
```

```bash
az ml schedule create -f monitor-<algo>.yml -g $G -w $WS
```

- Lista `features` explícita: si el baseline trae el target y producción no,
  la comparación se ensucia.
- `standard_e4s_v3` es el mínimo de Spark serverless; cobra solo mientras corre.
- **Sin `start_time` la primera ejecución arranca sola al crear el monitor.**
  No hagas `az ml schedule trigger` además: duplica la corrida y el costo. Si
  pasa, cancela una con `az ml job cancel`.

## Paso 6 — Seguir la ejecución y cerrar

```bash
az ml job list -g $G -w $WS --max-results 3 --query "[].{name:name,exp:experiment_name,status:status}" -o table
```

Tarda ~15-20 min (arranque de Spark + cálculo). Cuando termine, dile al usuario:

1. **Dónde verlo**: ml.azure.com → **Monitoring** → el monitor → resumen por
   señal, drift por feature, historial. Y el email si se pasó un umbral.
2. Que corre **una vez al día**; para repetir en clase: `az ml schedule trigger -n <monitor>`.
3. Costos: endpoint 24/7 (lo que ya pagaba) + Spark solo durante cada corrida
   + storage mínimo de lo recolectado.
4. Para desmontar: `/azureml-model-monitoring-cleanup`.
