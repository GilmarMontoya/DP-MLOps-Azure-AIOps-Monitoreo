# ==================== Azure Monitor para AIOps — vía manual ====================
#
# Hay DOS formas de hacerlo. Elige una:
#
#   FORMA A (manual)  -> los comandos de este archivo.
#   FORMA B (asistida)-> dentro de Claude Code escribe:  /crear-azure-monitor
#                        y la skill del proyecto hace todo esto por ti.
#
# Para desmontar todo al final del aula:  /eliminar-azure-monitor
# (o la sección "LIMPIEZA" al final de este archivo).


# ========================= LO PRIMERO: desarmar un mito =========================
#
# "Voy a crear UN Azure Monitor y elijo el tamaño de la instancia."
#
# NO. Azure Monitor NO es un recurso. No tiene instancia, ni SKU, ni precio por
# hora. Es una SOMBRILLA sobre varios recursos que sí existen:
#
#   Log Analytics Workspace  -> la base de datos de logs. Se paga por GB.
#   Application Insights     -> APM para apps. Se apoya en el workspace de arriba.
#   Action Groups            -> a quién se avisa cuando algo pasa.
#   Metric Alerts            -> las reglas. Aquí vive el "AI" de AIOps.
#   Workbooks                -> los dashboards. Gratis.
#
# Lo que cuesta por hora es la APP que monitoreas, no el monitoreo.


# ============================ PRECIOS REALES (brazilsouth, USD) =================
#
#   Ingesta Analytics Logs .............. $2.30 / GB
#   Ingesta Basic Logs .................. $1.00 / GB
#   Retención más allá de 31 días ....... $0.20 / GB / mes
#   Alerta métrica cada 5 min ........... $0.15 / mes
#   Dynamic Threshold ................... $0.10 / mes
#   Workbooks ........................... gratis
#
# Un aula de 2 horas con una app pequeña ingiere 20-100 MB.
# Costo por alumno: entre $0.05 y $0.25. Prácticamente nada.
#
# Consulta los precios vigentes tú mismo (API pública, sin login):
curl -s "https://prices.azure.com/api/retail/prices?\$filter=serviceName%20eq%20'Log%20Analytics'%20and%20armRegionName%20eq%20'brazilsouth'" | python3 -m json.tool


# ============================== Requisitos previos ==============================
# Paso 0: sesión de Azure activa y la extensión de App Insights.
az account show
az extension add -n application-insights -y     # idempotente


# ============================== Variables =======================================
# Ajusta estas cuatro líneas y el resto del archivo funciona tal cual.
# TARGET_ID es el recurso YA EXISTENTE que vas a monitorear (una Web App, una VM,
# un endpoint de Azure ML...). Sin esto no hay datos que mostrar.

RG=Datapath-MLOps-15-Kevin-Inofuente
LOC=brazilsouth
EMAIL=tu-correo@ejemplo.com
TARGET_ID=$(az webapp show -n TU-WEB-APP -g EL-RG-DE-TU-APP --query id -o tsv)


# ============================ Paso 1 — Resource Group ===========================
az group create -n $RG -l $LOC --tags lab=aiops-azure-monitor


# ====================== Paso 2 — Log Analytics Workspace ========================
#
# --retention-time 30 : 30 días es el mínimo y va incluido, no se cobra extra.
# --quota 1           : TOPE DE 1 GB/DÍA. Es la red de seguridad del aula.
#                       Si un alumno olvida borrar, su exposición máxima queda
#                       en ~$2.30/día en vez de ilimitada. NO LO OMITAS.

az monitor log-analytics workspace create \
  -g $RG -n log-aiops-lab -l $LOC \
  --retention-time 30 \
  --quota 1

LAWID=$(az monitor log-analytics workspace show -g $RG -n log-aiops-lab --query id -o tsv)


# ====================== Paso 3 — Application Insights ===========================
#
# TRAMPA: NO pongas --retention-time aquí. Si App Insights está conectado a un
# workspace ("workspace-based", que es lo correcto hoy), HEREDA la retención del
# workspace. Si lo pones, el comando falla con:
#   "Retention time can be set only when Application Insights is not connected
#    to a Log Analytics workspace."

az monitor app-insights component create \
  --app appi-aiops-lab -g $RG -l $LOC \
  --workspace "$LAWID" \
  --application-type web

CS=$(az monitor app-insights component show --app appi-aiops-lab -g $RG --query connectionString -o tsv)


# ================== Paso 4 — Cablear App Insights a la app ======================
#
# Esto es lo que casi todo el mundo olvida. Puedes tener Log Analytics y App
# Insights creados y NO VER NADA, porque la app no sabe que existen.
# (Salta este paso si tu target no es una Web App.)

az webapp config appsettings set -n TU-WEB-APP -g EL-RG-DE-TU-APP --settings \
  APPLICATIONINSIGHTS_CONNECTION_STRING="$CS" \
  ApplicationInsightsAgent_EXTENSION_VERSION="~3" \
  XDT_MicrosoftApplicationInsights_Mode="recommended"


# ================ Paso 5 — Diagnostic settings -> Log Analytics =================
#
# App Insights trae telemetría de APLICACIÓN. Los diagnostic settings traen los
# logs de PLATAFORMA. Son cosas distintas y necesitas las dos.
#
# Primero mira qué categorías soporta tu recurso (cambian según el tipo):
az monitor diagnostic-settings categories list --resource "$TARGET_ID" -o table

az monitor diagnostic-settings create \
  --name diag-aiops-lab \
  --resource "$TARGET_ID" \
  --workspace "$LAWID" \
  --logs '[{"category":"AppServiceHTTPLogs","enabled":true},
           {"category":"AppServiceConsoleLogs","enabled":true},
           {"category":"AppServiceAppLogs","enabled":true},
           {"category":"AppServicePlatformLogs","enabled":true}]' \
  --metrics '[{"category":"AllMetrics","enabled":true}]'


# ========================== Paso 6 — Action Group ===============================
# A quién se le avisa. Sin esto las alertas se disparan y nadie se entera.

az monitor action-group create \
  -n ag-aiops-lab -g $RG \
  --short-name aiopslab \
  --action email docente "$EMAIL"

AGID=$(az monitor action-group show -n ag-aiops-lab -g $RG --query id -o tsv)


# =============== Paso 7 — Alertas con UMBRAL DINÁMICO (el AIOps) ================
#
# Aquí está la diferencia entre monitoreo clásico y AIOps.
#
#   Umbral estático:  "avísame si CPU > 80%"        <- tú eliges el número
#   Umbral dinámico:  "avísame si CPU es ANORMAL"   <- lo aprende un modelo ML
#
# El umbral dinámico aprende el patrón histórico del recurso, entiende
# estacionalidad (noches, fines de semana) y ajusta solo. No hay que calibrar.
#
# GRAMÁTICA de --condition (el orden importa y es contraintuitivo):
#
#   {avg|min|max|total|count} METRICA {>|><|<} dynamic SENSIBILIDAD N of M
#                                              ^^^^^^^
#                             la palabra "dynamic" va DESPUÉS del operador
#
#   SENSIBILIDAD: low | medium | high
#   "2 of 4" = alerta si 2 de las últimas 4 evaluaciones violan el umbral.
#              Subir N reduce falsos positivos y retrasa la detección.

az monitor metrics alert create -n alert-aiops-5xx -g $RG \
  --scopes "$TARGET_ID" --severity 2 \
  --description "Anomalia en errores HTTP 5xx (umbral dinamico ML)" \
  --condition "total Http5xx > dynamic medium 2 of 4" \
  --window-size 5m --evaluation-frequency 5m --action "$AGID"

az monitor metrics alert create -n alert-aiops-latencia -g $RG \
  --scopes "$TARGET_ID" --severity 3 \
  --description "Anomalia en tiempo de respuesta (umbral dinamico ML)" \
  --condition "avg HttpResponseTime > dynamic medium 2 of 4" \
  --window-size 5m --evaluation-frequency 5m --action "$AGID"

az monitor metrics alert create -n alert-aiops-memoria -g $RG \
  --scopes "$TARGET_ID" --severity 3 \
  --description "Anomalia en consumo de memoria (umbral dinamico ML)" \
  --condition "avg AverageMemoryWorkingSet > dynamic medium 2 of 4" \
  --window-size 5m --evaluation-frequency 5m --action "$AGID"

# ¿Qué métricas tiene tu recurso? Esto las lista:
az monitor metrics list-definitions --resource "$TARGET_ID" --query "[].name.value" -o tsv


# ====================== Paso 8 — KQL: consultar los datos =======================
#
# Espera 5-15 min tras el cableado antes de esperar datos.

# 8a. ¿CUÁNTO ESTOY CONSUMIENDO? (la consulta que responde a "monitorear el gasto")
az monitor log-analytics query -w "$LAWID" --analytics-query "
Usage
| where TimeGenerated > ago(24h)
| where IsBillable == true
| summarize GB = round(sum(Quantity)/1024, 4) by DataType
| order by GB desc" -o table

# 8b. Volumen de peticiones
az monitor log-analytics query -w "$LAWID" --analytics-query "
AppServiceHTTPLogs
| summarize Peticiones = count() by bin(TimeGenerated, 5m)
| order by TimeGenerated asc" -o table

# 8c. DETECCIÓN DE ANOMALÍAS EN KQL — sin entrenar nada, sin ML Studio.
#     series_decompose_anomalies separa tendencia + estacionalidad y marca
#     los puntos que se salen. El 1.5 es la sensibilidad (menor = más estricto).
az monitor log-analytics query -w "$LAWID" --analytics-query "
AppServiceHTTPLogs
| make-series Peticiones = count() default=0 on TimeGenerated from ago(24h) to now() step 30m
| extend (anomalias, score, baseline) = series_decompose_anomalies(Peticiones, 1.5)
| mv-expand TimeGenerated, Peticiones, baseline, anomalias
| where toint(anomalias) != 0" -o table

# 8d. Otras funciones de AIOps que valen la pena en clase:
#     autocluster()             -> agrupa patrones comunes en los errores
#     basket()                  -> encuentra combinaciones frecuentes de atributos
#     series_decompose_forecast -> pronostica la serie
#     diffpatterns()            -> qué distingue el periodo malo del bueno


# =========================== Paso 9 — Workbook ==================================
#
# TRAMPA: el workbook se crea por REST, no con `az resource create`, porque
# necesita "kind": "shared" a NIVEL DE RECURSO (fuera de "properties").
# Además el "name" debe ser un GUID, no un nombre legible.
#
# Y OJO: nunca uses `az resource tag` sobre un workbook. Hace GET+PUT y el GET
# no devuelve serializedData -> te BORRA el contenido del dashboard.
# Para etiquetarlo usa PATCH:
#   az rest --method patch --url ".../workbooks/$GUID?api-version=2022-04-01" \
#           --body '{"tags":{"lab":"aiops-azure-monitor"}}'
#
# La creación completa del workbook está en la skill /crear-azure-monitor
# (arma el JSON con Python). Si lo quieres a mano, es más cómodo desde el portal:
#   Azure Portal -> Monitor -> Workbooks -> New


# ============================== Verificación ====================================
az resource list -g $RG -o table
az monitor metrics alert list -g $RG -o table
az monitor log-analytics workspace show -g $RG -n log-aiops-lab \
  --query "{retencionDias:retentionInDays, topeGBdia:workspaceCapping.dailyQuotaGb}" -o tsv


# ================================ LIMPIEZA ======================================
#
# IMPORTANTE: borrar el resource group NO basta. El cableado del Paso 4 y 5 vive
# en el RG de TU APP, no en el del lab. Si solo borras el RG, tu app se queda
# apuntando a un App Insights que ya no existe.
#
# Orden correcto — primero descablear, después borrar:

# 1) Quitar el diagnostic setting del recurso monitoreado
az monitor diagnostic-settings delete --name diag-aiops-lab --resource "$TARGET_ID"

# 2) Quitar los app settings de la Web App
az webapp config appsettings delete -n TU-WEB-APP -g EL-RG-DE-TU-APP \
  --setting-names APPLICATIONINSIGHTS_CONNECTION_STRING \
                  ApplicationInsightsAgent_EXTENSION_VERSION \
                  XDT_MicrosoftApplicationInsights_Mode

# 3) Ahora sí, borrar el resource group del lab
az group delete -n $RG --yes --no-wait

# 4) Confirmar
az group list -o table
