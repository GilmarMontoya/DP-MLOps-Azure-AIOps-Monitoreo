---
name: azure-grafana-aiops-cleanup
description: Desmonta lo que crea /azure-grafana-aiops — quita los diagnostic settings diag-grafana-aiops de endpoints y Web Apps (viven en OTROS resource groups), borra la instancia de Azure Managed Grafana y el Log Analytics del lab borrando su resource group etiquetado, y verifica que nada siga cobrando. Usar cuando el usuario pida borrar, eliminar, apagar o limpiar Grafana / el dashboard AIOps / el lab de AIOps, o diga "ya terminé la clase", "no quiero que me siga cobrando Grafana", o escriba /azure-grafana-aiops-cleanup.
---

# Eliminar el lab de AIOps con Grafana

Grafana Standard cobra **por hora mientras exista** (~$0.068/h en brazilsouth).
Hay que borrarlo al terminar el aula.

## Regla de oro

Borrar el resource group del lab **no basta**: los diagnostic settings viven en
los recursos monitoreados (otros RG). Si no se quitan, quedan apuntando a un
Log Analytics que ya no existe. Y nunca borres por tipo de recurso: solo lo
etiquetado `lab=grafana-aiops` y los settings llamados `diag-grafana-aiops`.

## Paso 1 — Inventario (solo lectura)

Confirma primero en qué suscripción estás (todo se busca solo ahí):

```bash
az account show --query "{sub:name, id:id}" -o table
SUB=$(az account show --query id -o tsv)
az extension add -n amg -y --only-show-errors; az extension add -n resource-graph -y --only-show-errors
az group list --tag lab=grafana-aiops --query "[].name" -o tsv
az resource list --tag lab=grafana-aiops --query "[].{n:name,t:type,rg:resourceGroup}" -o table
```

Busca los diagnostic settings del lab en endpoints y Web Apps:

```bash
for id in $(az graph query -q "Resources | where type in~ ('microsoft.machinelearningservices/workspaces/onlineendpoints','microsoft.web/sites') | project id" --subscriptions $SUB --query "data[].id" -o tsv); do
  az monitor diagnostic-settings show --name diag-grafana-aiops --resource "$id" --query id -o tsv 2>/dev/null
done
```

Muéstrale al usuario la lista y confirma antes de borrar.

- Si no aparece nada etiquetado, **no borres por tu cuenta**: probablemente se
  creó a mano. Pregunta el nombre del RG y revisa su contenido con
  `az resource list -g <RG> -o table` antes de seguir.
- Si hay **varios** RG con la etiqueta (varias corridas), lista todos y pregunta.

## Paso 2 — Quitar los diagnostic settings

```bash
az monitor diagnostic-settings delete --name diag-grafana-aiops --resource <ID>
```

Solo los que se llamen `diag-grafana-aiops`. Otros settings (de otro lab) no se tocan.

## Paso 3 — Borrar el resource group del lab

Contiene Grafana y el Log Analytics `law-aiops-grafana`. Verifica que solo tenga eso:

```bash
az resource list -g <RG_LAB> -o table
az group delete -n <RG_LAB> --yes --no-wait
```

## Paso 4 — Verificar

```bash
az group show -n <RG_LAB> --query properties.provisioningState -o tsv   # Deleting → luego NotFound
az graph query -q "Resources | where type =~ 'microsoft.dashboard/grafana' | project name, resourceGroup" --subscriptions $SUB -o table
```

Resume: qué se borró, que Grafana deja de cobrar al terminar el borrado
(~5 min) y que los endpoints y Web Apps siguen funcionando igual (solo dejaron
de mandar logs al lab). Si el usuario quiere bajar más el costo, recuérdale los
endpoints de Azure ML que cobran 24/7.
