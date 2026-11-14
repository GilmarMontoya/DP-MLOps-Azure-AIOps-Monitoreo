---
name: azureml-model-monitoring-cleanup
description: Desmonta de forma segura lo que crea /azureml-model-monitoring en Azure Machine Learning — cancela corridas en curso, deshabilita y borra el schedule del monitor, apaga la data collection del deployment (o borra el endpoint si el usuario lo pide) y opcionalmente archiva los data assets de produccion, sin tocar los datos de entrenamiento ni el modelo. Usar cuando el usuario pida eliminar, borrar, apagar o limpiar el model monitoring / el monitor de drift / la data collection — o cuando diga "ya termine el aula", "no quiero que me siga cobrando el monitor", "borra el monitor", o escriba /azureml-model-monitoring-cleanup.
---

# Eliminar Model Monitoring

Desmonta lo que creó `/azureml-model-monitoring`. Pensado para el final del aula.
Comandos sueltos equivalentes: sección **LIMPIEZA** de
`Comandos-Model-Monitoring.md` del proyecto (si existe).

## Qué cuesta y qué no

| Recurso | ¿Cobra? | Acción |
|---|---|---|
| Schedule del monitor | Spark serverless en cada corrida diaria | **Borrar siempre** |
| Data collection | Storage por lo recolectado (centavos) | Apagar |
| Endpoint / deployment | **VM 24/7** — lo más caro | Solo si el usuario lo pide |
| Data assets `*-model_inputs/outputs` | Storage mínimo | Archivar (opcional) |
| Baseline de entrenamiento y modelo | — | **Nunca tocar** |

## Paso 1 — Inventario (solo lectura)

```bash
G=<rg>; WS=<workspace>
az ml schedule list -g $G -w $WS --query "[].{name:name,enabled:is_enabled,tags:tags}" -o table
az ml job list -g $G -w $WS --max-results 10 \
  --query "[?starts_with(experiment_name,'monitor-')].{name:name,status:status}" -o table
az ml online-deployment list -g $G -w $WS -e <ENDPOINT> --query "[].{name:name,dc:data_collector}" -o json
```

Ojo: `az ml schedule list` también muestra schedules de **reentrenamiento** u
otros labs. Borra solo los que tengan `tags.lab == model-monitoring` o el nombre
que el usuario confirme. Muéstrale la lista antes de borrar.

## Paso 2 — Cancelar corridas en curso

```bash
az ml job cancel -n <JOB_RUNNING> -g $G -w $WS
```

## Paso 3 — Borrar el monitor

Hay que deshabilitarlo antes de borrarlo:

```bash
az ml schedule disable -n <MONITOR> -g $G -w $WS
az ml schedule delete  -n <MONITOR> -g $G -w $WS   # no tiene --yes; no borra las corridas pasadas
```

## Paso 4 — Apagar la data collection

Reusa el YAML del deployment con `enabled: 'False'` en las dos colecciones y:

```bash
az ml online-deployment update -f deployment-data-collection.yml -g $G -w $WS
```

(~10 min, en background.) **Si el usuario quiere borrar el endpoint completo**,
salta este paso y hazlo con confirmación explícita, mostrando su costo por hora:

```bash
az ml online-endpoint delete -n <ENDPOINT> -g $G -w $WS --yes
```

## Paso 5 — Data assets de producción (opcional)

Se archivan (no se borran: Azure ML no borra data assets por CLI):

```bash
az ml data archive -n <ENDPOINT>-<DEPLOYMENT>-model_inputs  -g $G -w $WS
az ml data archive -n <ENDPOINT>-<DEPLOYMENT>-model_outputs -g $G -w $WS
```

Los blobs quedan en `workspaceblobstore/modelDataCollector/<endpoint>/`. Solo
bórralos si el usuario lo pide; nunca borres el storage account del workspace.

## Paso 6 — Verificar y cerrar

```bash
az ml schedule list -g $G -w $WS -o table
az ml online-deployment show -g $G -w $WS -e <ENDPOINT> -n <DEPLOYMENT> --query data_collector -o json
```

Resume en pocas líneas qué se borró, qué quedó (y si sigue cobrando, cuánto
por hora) y que la pantalla Monitoring de ml.azure.com debe verse vacía otra vez.
