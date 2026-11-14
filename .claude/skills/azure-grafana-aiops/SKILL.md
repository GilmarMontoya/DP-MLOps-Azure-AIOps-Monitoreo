---
name: azure-grafana-aiops
description: Levanta Azure Managed Grafana como centro de operaciones (AIOps) de una suscripción de Azure — inventario de lo que está levantado y cobra por hora, estado de cada servicio, métricas de endpoints de Azure ML / Web Apps / jobs de ML, detección de anomalías con KQL (series_decompose_anomalies) y alertas de Azure Monitor (umbral dinámico). Revisa requisitos y permisos, crea la instancia (Standard; Essential ya no se puede crear) con nombre único, un Log Analytics con tope de 1 GB/día, conecta los servicios con diagnostic settings y genera el dashboard descubriendo los recursos reales de quien la ejecuta. Si ya existe, solo actualiza el dashboard. Usar cuando el usuario pida "Grafana", "Azure Managed Grafana", "AIOps", "dashboard de operaciones", "monitorear todo lo que tengo levantado", "ver mis instancias/servicios en un panel", "actualiza el dashboard AIOps", o escriba /azure-grafana-aiops.
---

# AIOps con Azure Managed Grafana

Responde **"¿qué tengo levantado, está sano y algo se comporta raro?"** para
una suscripción de Azure. Funciona en la suscripción de **quien la ejecuta**:
el dashboard se arma con sus propios recursos, sin nombres escritos a mano.

Para desmontar: `/azure-grafana-aiops-cleanup`.

Archivos de la skill (rutas relativas a la carpeta de esta skill):

- `scripts/generar_dashboard.py`: descubre los recursos y genera el JSON del dashboard
- `scripts/probar_paneles.py`: prueba cada panel contra la API de Grafana

## Lo que hay que decir antes de crear (costo)

| | Costo (lista, Brazil South) |
|---|---|
| Instancia **Standard** | **$0.068/h** (~$1.6/día, ~$50/mes si queda prendida) |
| Usuario activo | **$6/mes por cada persona que inicia sesión** |
| Log Analytics del lab | $2.30/GB, con tope de 1 GB/día |

El precio cambia por región. Para la región elegida:

```bash
curl -s "https://prices.azure.com/api/retail/prices?\$filter=contains(productName,'Grafana')%20and%20armRegionName%20eq%20'<region>'" \
  | python3 -c "import json,sys;[print(i['skuName'],i['meterName'],i['retailPrice'],i['unitOfMeasure']) for i in json.load(sys.stdin)['Items']]"
```

- **Essential ya no se puede crear** (`az grafana create --sku-tier Essential`
  responde *"Supported SKU tiers are: 'Standard'"*). No lo ofrezcas.
- En un aula conviene **una instancia por alumno, y borrarla al terminar**, o
  **una del docente** proyectada. No invites a 30 personas a una misma
  instancia: cada una que inicia sesión cuesta $6/mes.
- Las funciones de ML **propias de Grafana** (forecast, outliers) son de
  Grafana Cloud, **no** de Azure Managed Grafana. La "inteligencia" la ponen
  Azure Monitor (alertas con umbral dinámico) y KQL (`series_decompose_anomalies`).

Confirma el costo con el usuario antes del paso 4.

## Paso 0 — ¿Ya existe? (modo actualizar)

```bash
az extension add -n amg -y --only-show-errors
az grafana list --query "[?tags.lab=='grafana-aiops'].{n:name,rg:resourceGroup,url:properties.endpoint}" -o table
```

Si ya hay una instancia del lab, **no crees otra**: salta al paso 5 (conectar
recursos nuevos, si los hay) y al paso 6 (regenerar y subir el dashboard con
`--overwrite true`). Así el usuario puede volver a correr la skill cada vez que
levanta o borra servicios.

## Paso 1 — Requisitos

```bash
az version --query '"azure-cli"' -o tsv     # Azure CLI instalada (>= 2.60)
az account show --query "{sub:name, id:id, user:user.name}" -o table
python3 --version                            # Python 3.10+
az extension add -n amg -y --only-show-errors
az extension add -n resource-graph -y --only-show-errors
```

- Sin Azure CLI: indica cómo instalarla (macOS `brew install azure-cli`,
  Windows `winget install Microsoft.AzureCLI`) o usa la skill
  `install-azure-cli` si existe.
- Sin sesión: **no ejecutes `az login` tú** (abre el navegador). Pide al usuario
  que escriba `! az login` y espera.
- Si tiene varias suscripciones, confirma cuál usar: todo se crea ahí.
  `az account set -s <id>`.

## Paso 2 — Permisos (el error más común en cuentas de alumnos)

`az grafana create` **asigna roles** (Monitoring Reader a Grafana sobre la
suscripción y Grafana Admin al usuario). Asignar roles exige **Owner** o
**User Access Administrator**. Con solo *Contributor*, Grafana se crea pero
queda sin acceso: 401 para siempre y paneles vacíos.

```bash
SUB=$(az account show --query id -o tsv)
ME=$(az ad signed-in-user show --query id -o tsv)
az role assignment list --assignee "$ME" --scope /subscriptions/$SUB \
  --include-inherited --include-groups --query "[].roleDefinitionName" -o tsv | sort -u
```

- `Owner` o `User Access Administrator` → sigue.
- Solo `Contributor` → **detente y explícalo**. Dos salidas:
  1. Que alguien con Owner (el docente / admin) le dé `User Access Administrator`
     sobre la suscripción o el RG del lab.
  2. Crear igual con `--skip-role-assignments true` y que un Owner corra después:
     ```bash
     az role assignment create --assignee <principalId de Grafana> --role "Monitoring Reader" --scope /subscriptions/$SUB
     az role assignment create --assignee <objectId del alumno> --role "Grafana Admin" --scope <id de la instancia Grafana>
     ```
- Si `az ad signed-in-user show` falla (cuentas con restricciones de Entra),
  usa `az role assignment list --assignee <user.name de az account show>`.

## Paso 3 — Proveedores, región, nombres

```bash
for p in Microsoft.Dashboard Microsoft.Insights Microsoft.OperationalInsights; do
  [ "$(az provider show -n $p --query registrationState -o tsv)" = "Registered" ] || az provider register -n $p --wait
done
```

- **Región**: la de la mayoría de sus recursos (mira el inventario del paso 4)
  o pregúntala. Debe estar en
  `az provider show -n Microsoft.Dashboard --query "resourceTypes[?resourceType=='grafana'].locations | [0]"`.
- **Nombre único global** (2-23 caracteres, letras, números y guiones, empieza
  con letra). Genera un sufijo del usuario + 4 hex aleatorios:
  ```bash
  SUF=$(az account show --query user.name -o tsv | cut -d@ -f1 | tr -cd 'a-z0-9' | cut -c1-8)$(openssl rand -hex 2)
  RG=rg-grafana-aiops-$SUF; GRAFANA=gf-aiops-$SUF; LOC=<region>
  ```
  Si `az grafana create` dice que el nombre ya existe, genera otro sufijo.

## Paso 4 — Inventario (solo lectura)

```bash
az graph query -q "Resources | summarize n=count() by type, resourceGroup, location | order by resourceGroup asc" \
  --subscriptions $SUB --first 200 --query "data[].[resourceGroup,type,location,n]" -o tsv | column -t
```

Muéstrale al usuario qué tiene levantado (tabla por RG) y qué cobra por hora.
Si **no tiene ningún servicio**, avísale: el dashboard saldrá con inventario,
estado y alertas, y las filas de métricas aparecerán cuando vuelva a correr la
skill con recursos levantados.

## Paso 5 — Crear RG, Log Analytics y Grafana

```bash
az group create -n $RG -l $LOC --tags lab=grafana-aiops
az monitor log-analytics workspace create -g $RG -n law-aiops-grafana -l $LOC \
  --retention-time 30 --quota 1 --tags lab=grafana-aiops
az grafana create -n $GRAFANA -g $RG -l $LOC --sku-tier Standard --tags lab=grafana-aiops
```

- Grafana tarda ~5-10 min: córrelo en background.
- Nunca reutilices el Log Analytics autogenerado de un workspace de Azure ML.
- Justo después de crearlo la API da **401** unos minutos (propagación de
  RBAC). Reintenta cada 20 s:
  `az grafana data-source list -n $GRAFANA -g $RG` → debe listar
  `Azure Monitor` (uid `azure-monitor-oob`).

### Conectar servicios al Log Analytics (pide confirmación)

Para el panel de anomalías. **Modifica recursos de otros resource groups**:
lista cuáles y pide OK explícito.

```bash
LAWID=$(az monitor log-analytics workspace show -g $RG -n law-aiops-grafana --query id -o tsv)
for id in $(az graph query -q "Resources | where type =~ 'microsoft.machinelearningservices/workspaces/onlineendpoints' | project id" --subscriptions $SUB --query "data[].id" -o tsv); do
  az monitor diagnostic-settings create --name diag-grafana-aiops --resource "$id" --workspace "$LAWID" \
    --logs '[{"category":"AmlOnlineEndpointTrafficLog","enabled":true},{"category":"AmlOnlineEndpointEventLog","enabled":true}]' \
    --metrics '[{"category":"Traffic","enabled":true}]'
done
for id in $(az graph query -q "Resources | where type =~ 'microsoft.web/sites' | project id" --subscriptions $SUB --query "data[].id" -o tsv); do
  az monitor diagnostic-settings create --name diag-grafana-aiops --resource "$id" --workspace "$LAWID" \
    --logs '[{"category":"AppServiceHTTPLogs","enabled":true}]' --metrics '[{"category":"AllMetrics","enabled":true}]'
done
```

- Usa siempre el nombre `diag-grafana-aiops`: el cleanup lo busca así.
- Si una categoría no existe en un recurso, consulta las reales con
  `az monitor diagnostic-settings categories list --resource <ID>`.
- Un recurso admite máx. 5 diagnostic settings: si ya tiene 5, avísale.

## Paso 6 — Dashboard

```bash
python3 <skill>/scripts/generar_dashboard.py --law-id "$LAWID" --salida dashboard-aiops.json
az grafana dashboard create -n $GRAFANA -g $RG --definition @dashboard-aiops.json --overwrite true
python3 <skill>/scripts/probar_paneles.py "$(az grafana show -n $GRAFANA -g $RG --query properties.endpoint -o tsv)" dashboard-aiops.json
```

Filas: 1 inventario · 2 estado de servicios que cobran · 3 endpoints ML ·
4 Web Apps · 5 jobs de ML · 6 AIOps (anomalías KQL, alertas disparadas,
reglas configuradas). Las filas 3-5 solo aparecen si existen esos recursos.

Trampas ya resueltas en el generador (no las reintroduzcas):

- Las queries de métricas llevan **`azureMonitor.region`**; sin eso: *"Missing
  required region params"*.
- **Una query por recurso**: multi-recurso solo funciona en algunos tipos
  (deployments, Web Apps y workspaces dan 400/501).
- `HealthResources` (Resource Health) viene vacío en suscripciones pequeñas:
  el panel de estado usa `properties.state/provisioningState`.
- `probar_paneles.py` prueba solo el **primer** target de cada panel: `VACIO`
  puede ser un recurso sin tráfico, no un error. `ERROR`/`FALLA` sí es error.

## Paso 7 — Cerrar

Dale al usuario:

1. La URL: `<endpoint>/d/aiops-suscripcion`. Entra con su cuenta de Azure.
2. Que los logs tardan **5-15 min** y el panel de anomalías necesita **horas de
   historia** para aprender lo "normal". Para la demo: mandar tráfico a sus
   endpoints 2-3 h antes (su app de consumo, la pestaña *Test* del endpoint en
   ml.azure.com, o un script con requests).
3. Lo que cuesta por hora mientras exista y que lo borre con
   `/azure-grafana-aiops-cleanup` al terminar.
