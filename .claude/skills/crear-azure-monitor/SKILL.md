---
name: crear-azure-monitor
description: Levanta la capa de observabilidad de Azure Monitor (Log Analytics Workspace, Application Insights, Action Group, alertas con umbral dinamico y Workbook) y la conecta a un recurso de Azure que el usuario YA tiene desplegado. Incluye tope de gasto diario para uso en aula. Usar cuando el usuario pida crear, configurar o levantar Azure Monitor / Log Analytics / Application Insights / alertas / observabilidad / AIOps en Azure — o cuando diga "quiero monitorear mi app", "necesito ver el consumo de mis recursos", "montar el lab de Azure Monitor", "configurar alertas de anomalias".
---

# Crear la capa de Azure Monitor sobre un recurso existente

Levanta observabilidad **sobre algo que ya existe**. Esta skill NO despliega la
aplicación a monitorear: se engancha a un recurso que el usuario ya tiene.

Material de clase equivalente en comandos sueltos: `Comandos-Azure-Monitor.md`
en la raíz del proyecto. Esta skill es la vía asistida; ese archivo es la vía
manual. Si cambias algo aquí, mantén los dos alineados.

Para desmontar lo que crea esta skill: `/eliminar-azure-monitor`.

## Lo que hay que tener claro antes de empezar

Si el usuario habla de "crear un Azure Monitor" o pregunta por el **tamaño de la
instancia**, corrígelo antes de ejecutar nada, en dos líneas:

> Azure Monitor no es un recurso y no tiene instancia ni SKU. Es una sombrilla
> sobre varios recursos que sí existen. Se paga por **GB ingeridos** ($2.30/GB
> en brazilsouth), no por hora. Lo que cuesta por hora es la app que monitoreas.

Un aula de 2 h con una app pequeña cuesta entre **$0.05 y $0.25** por alumno.

## Paso 1 — Requisitos

```bash
az account show && az extension add -n application-insights -y
```

- Si no hay sesión, **no ejecutes `az login` tú** (es interactivo, abre el
  navegador). Pide al usuario que escriba `! az login` y espera su confirmación.
- Confírmale en una línea qué suscripción está activa: todo se creará ahí.

## Paso 2 — Averiguar QUÉ se va a monitorear

Este es el paso que decide si el lab funciona. Sin un recurso destino no hay
datos y el alumno ve un dashboard vacío.

Si el usuario no lo indicó, busca candidatos y **ofrécele la lista**:

```bash
az resource list --query "[?type=='Microsoft.Web/sites' || type=='Microsoft.Compute/virtualMachines' || type=='Microsoft.ContainerInstance/containerGroups'].{nombre:name, tipo:type, rg:resourceGroup}" -o table
```

- Si hay **un solo** candidato obvio, propónlo y sigue.
- Si hay varios, pregunta cuál.
- Si **no hay ninguno**, detente. Dile que esta skill necesita un recurso ya
  desplegado y ofrécele desplegar primero una Web App de prueba (App Service B1,
  ~$0.018/h) o apuntar a otro recurso suyo. No inventes un destino.

Guarda el id completo. Todo lo demás depende de él:

```bash
TARGET_ID=$(az resource show -n <NOMBRE> -g <RG-DEL-RECURSO> --resource-type <TIPO> --query id -o tsv)
```

## Paso 3 — Datos que faltan

Pregunta solo lo que no puedas deducir. Usa estos defaults sin preguntar:

| Dato | Default |
|---|---|
| Resource group del lab | uno nuevo, `<algo>-aiops-lab` |
| Región | la misma del recurso destino |
| Retención | 30 días (mínimo, incluido, no cobra extra) |
| Tope diario | 1 GB/día |

Lo único que **sí** debes preguntar es el **correo** para las alertas. No uses
el correo del usuario sin confirmárselo.

## Paso 4 — Resource group y Log Analytics Workspace

```bash
az group create -n $RG -l $LOC --tags lab=aiops-azure-monitor

az monitor log-analytics workspace create \
  -g $RG -n log-aiops-lab -l $LOC \
  --retention-time 30 \
  --quota 1

LAWID=$(az monitor log-analytics workspace show -g $RG -n log-aiops-lab --query id -o tsv)
```

**`--quota 1` no es opcional en aula.** Es el tope de 1 GB/día. Si un alumno
olvida borrar, su exposición máxima queda en ~$2.30/día en vez de ilimitada.
Menciónaselo explícitamente al usuario cuando lo crees: es el argumento que lo
deja tranquilo para dejar a los alumnos crear recursos.

## Paso 5 — Application Insights

```bash
az monitor app-insights component create \
  --app appi-aiops-lab -g $RG -l $LOC \
  --workspace "$LAWID" \
  --application-type web
```

**No añadas `--retention-time`.** Siendo workspace-based hereda la retención del
workspace, y el comando falla con *"Retention time can be set only when
Application Insights is not connected to a Log Analytics workspace"*.

## Paso 6 — Cablear (el paso que todo el mundo olvida)

Sin esto, los recursos existen y no llega ni un dato.

```bash
CS=$(az monitor app-insights component show --app appi-aiops-lab -g $RG --query connectionString -o tsv)
```

**Si el destino es una Web App**, conéctale App Insights:

```bash
az webapp config appsettings set -n <APP> -g <RG-APP> --settings \
  APPLICATIONINSIGHTS_CONNECTION_STRING="$CS" \
  ApplicationInsightsAgent_EXTENSION_VERSION="~3" \
  XDT_MicrosoftApplicationInsights_Mode="recommended"
```

**Para cualquier destino**, manda los logs de plataforma al workspace. Consulta
primero las categorías, que cambian según el tipo de recurso:

```bash
az monitor diagnostic-settings categories list --resource "$TARGET_ID" -o table
```

Luego crea el setting con las categorías que existan (no las adivines):

```bash
az monitor diagnostic-settings create \
  --name diag-aiops-lab --resource "$TARGET_ID" --workspace "$LAWID" \
  --logs '[{"category":"AppServiceHTTPLogs","enabled":true}, ...]' \
  --metrics '[{"category":"AllMetrics","enabled":true}]'
```

Anota el nombre `diag-aiops-lab`: `/eliminar-azure-monitor` lo necesita.

## Paso 7 — Action Group

```bash
az monitor action-group create -n ag-aiops-lab -g $RG \
  --short-name aiopslab --action email docente "<CORREO>"

AGID=$(az monitor action-group show -n ag-aiops-lab -g $RG --query id -o tsv)
```

## Paso 8 — Alertas con umbral dinámico

Aquí está el contenido de AIOps del lab. Explícale la diferencia al usuario:

> Umbral **estático**: "avísame si CPU > 80%" — el número lo eliges tú.
> Umbral **dinámico**: "avísame si CPU es anormal" — lo aprende un modelo que
> entiende estacionalidad y se recalibra solo.

La gramática de `--condition` es contraintuitiva: `dynamic` va **después** del
operador.

```
{avg|min|max|total|count} METRICA {>|><|<} dynamic {low|medium|high} N of M
```

Comprueba qué métricas existen antes de crear reglas:

```bash
az monitor metrics list-definitions --resource "$TARGET_ID" --query "[].name.value" -o tsv
```

Para una Web App, estas tres funcionan y cubren error, latencia y consumo:

```bash
az monitor metrics alert create -n alert-aiops-5xx -g $RG --scopes "$TARGET_ID" \
  --severity 2 --description "Anomalia en errores HTTP 5xx (umbral dinamico ML)" \
  --condition "total Http5xx > dynamic medium 2 of 4" \
  --window-size 5m --evaluation-frequency 5m --action "$AGID"

az monitor metrics alert create -n alert-aiops-latencia -g $RG --scopes "$TARGET_ID" \
  --severity 3 --description "Anomalia en tiempo de respuesta (umbral dinamico ML)" \
  --condition "avg HttpResponseTime > dynamic medium 2 of 4" \
  --window-size 5m --evaluation-frequency 5m --action "$AGID"

az monitor metrics alert create -n alert-aiops-memoria -g $RG --scopes "$TARGET_ID" \
  --severity 3 --description "Anomalia en consumo de memoria (umbral dinamico ML)" \
  --condition "avg AverageMemoryWorkingSet > dynamic medium 2 of 4" \
  --window-size 5m --evaluation-frequency 5m --action "$AGID"
```

Si el destino no es una Web App, elige métricas equivalentes de la lista real.

## Paso 9 — Workbook

Se crea por REST: necesita `"kind": "shared"` a nivel de recurso, fuera de
`properties`, y el nombre debe ser un GUID. `az resource create` no sirve.

Arma el JSON con Python (`$LAWID` y una ruta de salida como argumentos):

```python
import json, sys
law, out = sys.argv[1], sys.argv[2]
def kql(title, q, vis="timechart", size=0):
    return {"type":3,"content":{"version":"KqlItem/1.0","query":q,"size":size,
            "title":title,"queryType":0,
            "resourceType":"microsoft.operationalinsights/workspaces",
            "visualization":vis},"name":title[:20]}
wb = {"version":"Notebook/1.0","items":[
  {"type":1,"content":{"json":"# Consumo y salud — Lab AIOps"},"name":"titulo"},
  kql("Peticiones en el tiempo",
      "AppServiceHTTPLogs\n| summarize Peticiones = count() by bin(TimeGenerated, 5m)\n| order by TimeGenerated asc"),
  kql("Consumo facturable por tipo de dato (GB)",
      "Usage\n| where TimeGenerated > ago(24h)\n| where IsBillable == true\n| summarize GB = round(sum(Quantity)/1024, 4) by DataType\n| order by GB desc", vis="barchart", size=1),
  kql("Deteccion de anomalias (series_decompose_anomalies)",
      "AppServiceHTTPLogs\n| make-series Peticiones = count() default=0 on TimeGenerated from ago(24h) to now() step 30m\n| extend (anomalias, score, baseline) = series_decompose_anomalies(Peticiones, 1.5)\n| project TimeGenerated, Peticiones, baseline, anomalias", vis="linechart"),
  kql("Codigos de respuesta HTTP",
      "AppServiceHTTPLogs\n| where TimeGenerated > ago(24h)\n| summarize Total = count() by ScStatus\n| order by Total desc", vis="piechart", size=1),
 ],
 "fallbackResourceIds":[law],
 "$schema":"https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json"}
json.dump({"location":"<LOC>","kind":"shared","properties":{
    "displayName":"Lab AIOps — Consumo y salud",
    "serializedData":json.dumps(wb),
    "version":"Notebook/1.0","sourceId":law,"category":"workbook"}}, open(out,"w"))
```

```bash
GUID=$(uuidgen | tr 'A-Z' 'a-z')
az rest --method put \
  --url "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Insights/workbooks/$GUID?api-version=2022-04-01" \
  --body @<ruta-json>
```

Si el destino no es una Web App, ajusta las tablas del KQL (`AppServiceHTTPLogs`
solo existe para App Service). `Usage` sirve siempre.

## Paso 10 — Etiquetar

Deja todo marcado para que `/eliminar-azure-monitor` no tenga que adivinar:

```bash
for ID in $(az resource list -g $RG --query "[?type!='microsoft.insights/workbooks'].id" -o tsv); do
  az resource tag --ids "$ID" --tags lab=aiops-azure-monitor --is-incremental -o none
done
```

**Nunca uses `az resource tag` sobre un workbook**: hace GET+PUT y el GET no
devuelve `serializedData`, así que te **borra el contenido del dashboard**.
Etiquétalo con PATCH:

```bash
az rest --method patch \
  --url "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Insights/workbooks/$GUID?api-version=2022-04-01" \
  --body '{"tags":{"lab":"aiops-azure-monitor"}}'
```

## Paso 11 — Cerrar

Verifica y resume:

```bash
az resource list -g $RG -o table
az monitor metrics alert list -g $RG -o table
```

Dile al usuario, en pocas líneas:

1. Qué se creó y en qué resource group.
2. Que **los datos tardan 5-15 minutos** en aparecer. Sin esto va a creer que
   falló.
3. El tope de 1 GB/día que lo protege.
4. Que para desmontar todo ejecute `/eliminar-azure-monitor`.

Ofrécele una consulta de humo para cuando pasen los minutos:

```bash
az monitor log-analytics query -w "$LAWID" --analytics-query \
  "Usage | where TimeGenerated > ago(1h) | summarize GB=round(sum(Quantity)/1024,4) by DataType" -o table
```

## Notas

- Los **Workbooks son gratis**. Si el usuario pregunta por Azure Managed Grafana,
  explícale que Grafana no recolecta nada: es solo visualización sobre estos
  mismos datos, cuesta ~$0.043/h y tarda varios minutos en desplegar. Para un
  aula de 2 h, los Workbooks cubren el caso sin costo ni espera.
- Estas alertas viven en el **plano de control** de Azure. Funcionan igual sobre
  un endpoint de Azure ML que sobre una Web App: cambia la métrica, no el patrón.
- Funciones KQL que valen la pena mostrar en clase: `series_decompose_anomalies`,
  `series_decompose_forecast`, `autocluster`, `basket`, `diffpatterns`.
