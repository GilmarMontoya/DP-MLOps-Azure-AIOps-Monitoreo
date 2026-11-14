# Model Monitoring en Azure ML — comandos del lab

Vía manual del lab. La vía asistida es `/azureml-model-monitoring` y `/azureml-model-monitoring-cleanup`.

Pregunta que responde: **¿el modelo sigue prediciendo bien con los datos nuevos?**
Se ve en **ml.azure.com → Monitoring**.

```bash
G=datapath-mlops18-kaic
WS=ws-datapath-mlops18-kaic
```

## 1. Activar data collection en el deployment (~10 min)

```bash
az ml online-deployment update -f deployment-data-collection.yml -g $G -w $WS
```

Crea dos data assets: `endpoint-voting-ensemble-mlops-modelo-voting-ensemble-mlops18-model_inputs` y `...-model_outputs`.

## 2. Mandar tráfico al endpoint

```bash
uv run enviar_trafico.py --modo normal --filas 400   # se parece al entrenamiento
uv run enviar_trafico.py --modo drift  --filas 400   # +15 años, +25% BMI, 70% fumadores, una sola región
```

## 3. Crear el monitor (la primera corrida arranca sola)

```bash
az ml schedule create -f monitor-voting-ensemble.yml -g $G -w $WS
```

Seguir la corrida (~15-20 min):

```bash
az ml job list -g $G -w $WS --max-results 3 --query "[].{name:name,exp:experiment_name,status:status}" -o table
```

Volver a correrlo en clase sin esperar al día siguiente:

```bash
az ml schedule trigger -n monitor-voting-ensemble-mlops -g $G -w $WS
```

## Costos (brazilsouth, pago por uso)

| Qué | VM | Precio | Cuándo cobra |
|---|---|---|---|
| Endpoint | Standard_DS1_v2 | $0.086/h | 24/7 mientras exista |
| Monitor | Spark serverless standard_e4s_v3 | ~$0.47/h | solo mientras corre cada ejecución |

## LIMPIEZA

```bash
az ml schedule disable -n monitor-voting-ensemble-mlops -g $G -w $WS
az ml schedule delete  -n monitor-voting-ensemble-mlops -g $G -w $WS
# apagar la recoleccion: poner enabled: 'False' en deployment-data-collection.yml y
az ml online-deployment update -f deployment-data-collection.yml -g $G -w $WS
# (opcional) borrar el endpoint completo, lo que mas cuesta:
# az ml online-endpoint delete -n endpoint-voting-ensemble-mlops -g $G -w $WS --yes
```
