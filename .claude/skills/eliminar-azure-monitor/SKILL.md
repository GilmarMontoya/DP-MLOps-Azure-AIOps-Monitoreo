---
name: eliminar-azure-monitor
description: Desmonta de forma segura la capa de Azure Monitor creada por /crear-azure-monitor — descablea el recurso monitoreado (diagnostic settings y app settings), borra Log Analytics Workspace, Application Insights, Action Group, alertas y Workbook, y confirma que no quedo nada facturando. Usar cuando el usuario pida eliminar, borrar, desmontar, apagar o limpiar Azure Monitor / Log Analytics / Application Insights / las alertas / el lab de observabilidad — o cuando diga "ya termine el aula", "borra lo que creamos en Azure", "no quiero que me sigan cobrando", "limpiar los recursos del laboratorio".
---

# Eliminar la capa de Azure Monitor

Desmonta lo que creó `/crear-azure-monitor`. Pensado para ejecutarse al final
del aula.

Material de clase equivalente en comandos sueltos: la sección **LIMPIEZA** de
`Comandos-Azure-Monitor.md`.

## Regla de oro

**Borrar el resource group NO basta**, y borrar de más es peor que no borrar.

El cableado (diagnostic settings y app settings) vive en el resource group de
**la app monitoreada**, no en el del lab. Si solo borras el RG del lab, la app
del alumno se queda apuntando a un Application Insights que ya no existe.

Y al revés: un Log Analytics Workspace puede pertenecer a **otro servicio**. Los
workspaces de Azure Machine Learning se crean solos junto al workspace de ML y
tienen nombres autogenerados tipo `datapathmlops11105792654`. **Borrar uno de
esos rompe el workspace de ML.** Nunca borres por tipo de recurso: borra solo lo
que esté etiquetado.

## Paso 1 — Inventariar antes de tocar nada

```bash
az resource list --tag lab=aiops-azure-monitor --query "[].{nombre:name, tipo:type, rg:resourceGroup}" -o table
az group list --tag lab=aiops-azure-monitor --query "[].name" -o table
```

- Si **no aparece nada**, no borres nada por tu cuenta. Probablemente el lab se
  creó a mano sin etiquetas. Pregúntale al usuario el nombre del resource group
  y verifica su contenido con `az resource list -g <RG> -o table` antes de seguir.
- Si aparecen recursos **fuera** del RG del lab, señálalos: pueden ser de otro
  lab o de otra persona.

## Paso 2 — Localizar el recurso que se está monitoreando

Necesitas saber a qué se cableó para poder descablearlo. Búscalo por el
diagnostic setting que crea la skill:

```bash
az resource list --query "[?type=='Microsoft.Web/sites'].id" -o tsv | while read -r ID; do
  N=$(az monitor diagnostic-settings list --resource "$ID" --query "value[?name=='diag-aiops-lab'].name" -o tsv 2>/dev/null)
  [ -n "$N" ] && echo "cableado -> $ID"
done
```

Si el destino no era una Web App, pregúntale al usuario cuál era.

## Paso 3 — Descablear PRIMERO

Antes de borrar nada del lab.

```bash
# a) quitar el diagnostic setting del recurso monitoreado
az monitor diagnostic-settings delete --name diag-aiops-lab --resource "$TARGET_ID"

# b) quitar los app settings de la Web App (si aplica)
az webapp config appsettings delete -n <APP> -g <RG-APP> \
  --setting-names APPLICATIONINSIGHTS_CONNECTION_STRING \
                  ApplicationInsightsAgent_EXTENSION_VERSION \
                  XDT_MicrosoftApplicationInsights_Mode
```

`az webapp config appsettings delete` reinicia la app. Avísale al usuario antes
de ejecutarlo si la app es algo que le importa.

## Paso 4 — Confirmar con el usuario

Muéstrale la lista exacta del Paso 1 y **espera su confirmación explícita**. El
borrado de un Log Analytics Workspace se lleva los logs con él.

Si el usuario quiere conservar los datos, dile que puede exportarlos antes:

```bash
az monitor log-analytics query -w "$LAWID" --analytics-query \
  "Usage | where TimeGenerated > ago(24h)" -o json > consumo.json
```

## Paso 5 — Borrar

Si todo el lab está en su propio resource group (el caso normal), una sola
orden:

```bash
az group delete -n <RG-DEL-LAB> --yes --no-wait
```

Si el lab **comparte** resource group con otras cosas, borra recurso por recurso
usando la etiqueta, nunca el RG completo:

```bash
# alertas primero: dependen del action group
az resource list --tag lab=aiops-azure-monitor \
  --query "[?type=='microsoft.insights/metricalerts'].id" -o tsv | xargs -r -I{} az resource delete --ids {}

# luego el resto
az resource list --tag lab=aiops-azure-monitor \
  --query "[?type!='microsoft.insights/metricalerts'].id" -o tsv | xargs -r -I{} az resource delete --ids {}
```

El **Workbook** no siempre sale en `az resource list`. Bórralo aparte:

```bash
az resource list -g <RG> --resource-type Microsoft.Insights/workbooks --query "[].id" -o tsv \
  | xargs -r -I{} az resource delete --ids {} --api-version 2022-04-01
```

## Paso 6 — Verificar que no quedó nada facturando

```bash
az resource list --tag lab=aiops-azure-monitor -o table
az group list -o table
```

El borrado de un resource group es asíncrono. Si usaste `--no-wait`, el RG
aparece en estado `Deleting` unos minutos: eso es normal, no lo vuelvas a
lanzar.

Cierra confirmándole al usuario dos cosas concretas:

1. Que el recurso monitoreado quedó **descableado y funcionando** (no huérfano).
2. Que ya no hay ingesta y por tanto no hay más cobro.

## Un workspace borrado se puede recuperar (por poco tiempo)

Si el usuario se arrepiente, un Log Analytics Workspace queda en **soft-delete
14 días** y se puede recuperar recreándolo con el mismo nombre en el mismo
resource group y región:

```bash
az monitor log-analytics workspace recover -g <RG> -n <NOMBRE>
```

Menciónalo solo si hace falta. Pasados los 14 días, los datos no vuelven.

## Qué NO borrar nunca

| Recurso | Por qué |
|---|---|
| Workspaces con nombre autogenerado (`datapathmlops...`) | pertenecen a un workspace de Azure ML; borrarlos lo rompe |
| `Application Insights Smart Detection` (action group) | lo crea Azure solo; se regenera y borrarlo no ahorra nada |
| Cualquier recurso **sin** la etiqueta `lab=aiops-azure-monitor` | no lo creó esta skill |
