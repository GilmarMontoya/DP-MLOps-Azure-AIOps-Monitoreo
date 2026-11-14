"""
Genera el dashboard "AIOps — Suscripcion" para Azure Managed Grafana.

Descubre con Azure Resource Graph los recursos que existen HOY en la suscripcion
(endpoints y deployments de Azure ML, workspaces de ML, Web Apps) y arma los
paneles con sus metricas reales. Asi el dashboard sirve para cualquier alumno
sin editar nombres a mano.

Filas:
  1. Inventario          (Resource Graph)
  2. Salud               (Resource Health via Resource Graph)
  3. Endpoints ML        (Azure Monitor Metrics)
  4. Web Apps            (Azure Monitor Metrics)
  5. Jobs de Azure ML    (metricas del workspace)
  6. AIOps               (anomalias con KQL + alertas disparadas)

Uso:
  python3 generar_dashboard.py --law-id <resourceId del Log Analytics> --salida dashboard-aiops.json
"""

import argparse
import json
import subprocess

DS = {"type": "grafana-azure-monitor-datasource", "uid": "${ds}"}


SUB = ""  # se fija en main(): suscripcion activa de az CLI o --suscripcion


def az_tsv(*args: str) -> str:
    return subprocess.run(["az", *args, "-o", "tsv"], capture_output=True, text=True, check=True).stdout.strip()


def arg(query: str) -> list[dict]:
    """Consulta Azure Resource Graph con az CLI, acotada a la suscripcion SUB."""
    out = subprocess.run(
        ["az", "graph", "query", "-q", query, "--subscriptions", SUB, "--first", "500", "--query", "data", "-o", "json"],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def recurso(r: dict, namespace: str) -> dict:
    """Referencia de recurso en el formato del datasource Azure Monitor de Grafana.
    Para recursos anidados el resourceName es 'padre/hijo/nieto'."""
    partes = r["id"].split("/providers/")[1].split("/")
    nombre = "/".join(partes[2::2])
    return {
        "subscription": r["subscriptionId"], "resourceGroup": r["resourceGroup"],
        "metricNamespace": namespace, "resourceName": nombre, "region": r["location"],
    }


# --- constructores de queries --------------------------------------------------
def q_metric(ref: str, recursos: list[dict], ns: str, metrica: str, agg: str, alias: str = "{{resourcename}}") -> dict:
    return {
        "refId": ref, "datasource": DS, "queryType": "Azure Monitor",
        "subscription": recursos[0]["subscription"],
        "azureMonitor": {
            "region": recursos[0]["region"],  # obligatorio en consultas multi-recurso
            "resources": recursos, "metricNamespace": ns, "metricName": metrica,
            "aggregation": agg, "timeGrain": "auto", "dimensionFilters": [], "alias": alias,
        },
    }


def qm(recursos: list[dict], ns: str, metrica: str, agg: str) -> list[dict]:
    """Una query por recurso. Las consultas multi-recurso de Azure Monitor solo
    funcionan en algunos tipos (endpoints si; deployments, web apps y workspaces no)."""
    return [q_metric(chr(65 + i), [r], ns, metrica, agg, alias=r["resourceName"].split("/")[-1])
            for i, r in enumerate(recursos)]


def q_arg(ref: str, sub: str, query: str) -> dict:
    return {"refId": ref, "datasource": DS, "queryType": "Azure Resource Graph",
            "subscriptions": [sub], "azureResourceGraph": {"query": query, "resultFormat": "table"}}


def q_logs(ref: str, law_id: str, query: str, formato: str = "time_series") -> dict:
    return {"refId": ref, "datasource": DS, "queryType": "Azure Log Analytics",
            "azureLogAnalytics": {"query": query, "resources": [law_id], "resultFormat": formato}}


# --- constructores de paneles --------------------------------------------------
_id = iter(range(1, 1000))


def fila(titulo: str, y: int) -> dict:
    return {"type": "row", "title": titulo, "id": next(_id), "collapsed": False,
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}, "panels": []}


def panel(tipo: str, titulo: str, targets: list[dict], x: int, y: int, w: int, h: int = 8,
          unidad: str | None = None, desc: str = "", extra: dict | None = None) -> dict:
    p = {"type": tipo, "title": titulo, "description": desc, "id": next(_id), "datasource": DS,
         "targets": targets, "gridPos": {"h": h, "w": w, "x": x, "y": y},
         "fieldConfig": {"defaults": {"unit": unidad} if unidad else {}, "overrides": []}, "options": {}}
    if extra:
        p.update(extra)
    return p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--law-id", required=True, help="resourceId del Log Analytics del lab")
    ap.add_argument("--salida", default="dashboard-aiops.json")
    ap.add_argument("--suscripcion", help="id de la suscripcion (por defecto, la activa en az CLI)")
    a = ap.parse_args()

    global SUB
    SUB = a.suscripcion or az_tsv("account", "show", "--query", "id")

    endpoints = arg("Resources | where type =~ 'microsoft.machinelearningservices/workspaces/onlineendpoints' | project id, subscriptionId, resourceGroup, location")
    deps = arg("Resources | where type =~ 'microsoft.machinelearningservices/workspaces/onlineendpoints/deployments' | project id, subscriptionId, resourceGroup, location")
    wss = arg("Resources | where type =~ 'microsoft.machinelearningservices/workspaces' | where kind != 'Hub' and kind != 'Project' | project id, subscriptionId, resourceGroup, location")
    webs = arg("Resources | where type =~ 'microsoft.web/sites' | project id, subscriptionId, resourceGroup, location")
    sub = SUB
    if not (endpoints or webs or wss):
        print("Aviso: no hay endpoints de Azure ML, Web Apps ni workspaces de ML en esta suscripcion.\n"
              "       El dashboard tendra inventario, estado, anomalias y alertas; las filas de metricas\n"
              "       apareceran al volver a correr este script cuando existan esos recursos.")

    NS_EP = "microsoft.machinelearningservices/workspaces/onlineendpoints"
    NS_DEP = "microsoft.machinelearningservices/workspaces/onlineendpoints/deployments"
    NS_WS = "microsoft.machinelearningservices/workspaces"
    NS_WEB = "microsoft.web/sites"

    p, y = [], 0

    # 1. Inventario
    p.append(fila("1 · Inventario — ¿qué tengo levantado?", y)); y += 1
    p.append(panel("stat", "Recursos en la suscripción", [q_arg("A", sub, "Resources | summarize Recursos=count()")], 0, y, 4, 5))
    p.append(panel("stat", "Servicios que cobran por hora", [q_arg("A", sub,
        "Resources | where type in~ ('microsoft.machinelearningservices/workspaces/onlineendpoints/deployments','microsoft.web/serverfarms','microsoft.search/searchservices','microsoft.dashboard/grafana','microsoft.compute/virtualmachines') | summarize Activos=count()")],
        4, y, 4, 5, desc="Deployments de endpoints, App Service Plans, AI Search, Grafana y VMs: cobran aunque nadie los use."))
    p.append(panel("table", "Inventario por resource group", [q_arg("A", sub,
        "Resources | summarize Cantidad=count() by ResourceGroup=resourceGroup, Tipo=type, Region=location | order by ResourceGroup asc")],
        8, y, 16, 17))
    p.append(panel("piechart", "Recursos por región", [q_arg("A", sub, "Resources | summarize n=count() by location")], 0, y + 5, 8, 12,
                   extra={"options": {"reduceOptions": {"values": True, "calcs": ["lastNotNull"], "fields": "/^n$/"},
                                      "pieType": "donut", "displayLabels": ["percent"],
                                      "legend": {"show": True, "displayMode": "table", "placement": "bottom", "values": ["value", "percent"]}}}))
    y += 17

    # 2. Salud
    p.append(fila("2 · Salud — ¿está disponible?", y)); y += 1
    p.append(panel("table", "Estado de los servicios que cobran", [q_arg("A", sub,
        "Resources | where type in~ ('microsoft.machinelearningservices/workspaces/onlineendpoints','microsoft.machinelearningservices/workspaces/onlineendpoints/deployments','microsoft.web/sites','microsoft.web/serverfarms','microsoft.search/searchservices','microsoft.dashboard/grafana','microsoft.compute/virtualmachines') "
        "| project Servicio=name, Tipo=tostring(split(type,'/')[-1]), ResourceGroup=resourceGroup, Region=location, SKU=coalesce(tostring(sku.name), tostring(properties.sku.name), ''), "
        "Estado=coalesce(tostring(properties.state), tostring(properties.provisioningState), tostring(properties.status)) | order by Tipo asc")],
        0, y, 24, 8, desc="Running/Stopped, Succeeded/Failed. Lo que está aquí y Running cobra por hora."))
    y += 8

    # 3. Endpoints ML
    if endpoints:
        p.append(fila("3 · Endpoints de Azure ML — ¿responden bien?", y)); y += 1
        eps = [recurso(r, NS_EP) for r in endpoints]
        dps = [recurso(r, NS_DEP) for r in deps]
        p.append(panel("timeseries", "Requests por minuto", qm(eps, NS_EP, "RequestsPerMinute", "Average"), 0, y, 8))
        p.append(panel("timeseries", "Latencia (ms)", qm(eps, NS_EP, "RequestLatency", "Average"), 8, y, 8, unidad="ms"))
        p.append(panel("timeseries", "Eventos de data collection / min", qm(eps, NS_EP, "DataCollectionEventsPerMinute", "Average"), 16, y, 8,
                       desc="Lo que alimenta al Model Monitoring (tarea 1)."))
        y += 8
        if dps:
            p.append(panel("timeseries", "CPU % por deployment (VM)", qm(dps, NS_DEP, "CpuUtilizationPercentage", "Average"), 0, y, 8, unidad="percent"))
            p.append(panel("timeseries", "Memoria % por deployment (VM)", qm(dps, NS_DEP, "CpuMemoryUtilizationPercentage", "Average"), 8, y, 8, unidad="percent"))
            p.append(panel("stat", "Instancias por deployment", qm(dps, NS_DEP, "DeploymentCapacity", "Average"), 16, y, 8,
                           desc="Cada instancia es una VM cobrando 24/7."))
            y += 8

    # 4. Web Apps
    if webs:
        p.append(fila("4 · Web Apps (App Service)", y)); y += 1
        ws_ = [recurso(r, NS_WEB) for r in webs]
        p.append(panel("timeseries", "Requests", qm(ws_, NS_WEB, "Requests", "Total"), 0, y, 8))
        p.append(panel("timeseries", "Errores HTTP 5xx", qm(ws_, NS_WEB, "Http5xx", "Total"), 8, y, 8))
        p.append(panel("timeseries", "Tiempo de respuesta (s)", qm(ws_, NS_WEB, "HttpResponseTime", "Average"), 16, y, 8, unidad="s"))
        y += 8

    # 5. Jobs de Azure ML
    if wss:
        p.append(fila("5 · Jobs de Azure ML — entrenamientos y monitores", y)); y += 1
        wr = [recurso(r, NS_WS) for r in wss]
        p.append(panel("timeseries", "Corridas completadas", qm(wr, NS_WS, "Completed Runs", "Total"), 0, y, 8,
                       extra={"fieldConfig": {"defaults": {"custom": {"drawStyle": "bars"}}, "overrides": []}}))
        p.append(panel("timeseries", "Corridas fallidas", qm(wr, NS_WS, "Failed Runs", "Total"), 8, y, 8,
                       extra={"fieldConfig": {"defaults": {"custom": {"drawStyle": "bars"}, "color": {"mode": "fixed", "fixedColor": "red"}}, "overrides": []}}))
        p.append(panel("timeseries", "Nodos activos de cómputo", qm(wr, NS_WS, "Active Nodes", "Average"), 16, y, 8,
                       desc="Clusters de entrenamiento: si queda > 0 sin jobs, algo no se apagó."))
        y += 8

    # 6. AIOps
    p.append(fila("6 · AIOps — anomalías y alertas", y)); y += 1
    kql_anom = (
        "let datos = union isfuzzy=true\n"
        "  (AmlOnlineEndpointTrafficLog | project TimeGenerated, Servicio=tostring(split(_ResourceId,'/')[-1])),\n"
        "  (AppServiceHTTPLogs | project TimeGenerated, Servicio=tostring(split(_ResourceId,'/')[-1]));\n"
        "datos\n"
        "| make-series Requests=count() default=0 on TimeGenerated from $__timeFrom to $__timeTo step 5m by Servicio\n"
        "| extend (Anomalia, Score, Esperado) = series_decompose_anomalies(Requests, 1.5)\n"
        "| mv-expand TimeGenerated to typeof(datetime), Requests to typeof(long), Esperado to typeof(double), Anomalia to typeof(int)\n"
        "| extend Pico_anomalo = iff(Anomalia != 0, todouble(Requests), real(null))\n"
        "| project TimeGenerated, Servicio, Requests, Esperado, Pico_anomalo\n"
        "| order by TimeGenerated asc"
    )
    p.append(panel("timeseries", "Tráfico vs. lo esperado — anomalías detectadas (ML en KQL)",
                   [q_logs("A", a.law_id, kql_anom)], 0, y, 16, 10,
                   desc="series_decompose_anomalies aprende estacionalidad y tendencia; los puntos marcan lo anómalo.",
                   extra={"fieldConfig": {"defaults": {}, "overrides": [
                       {"matcher": {"id": "byRegexp", "options": ".*Pico_anomalo.*"},
                        "properties": [{"id": "custom.drawStyle", "value": "points"}, {"id": "custom.pointSize", "value": 12},
                                       {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]},
                       {"matcher": {"id": "byRegexp", "options": ".*Esperado.*"},
                        "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}}]}]}}))
    p.append(panel("table", "Alertas disparadas (Azure Monitor)", [q_arg("A", sub,
        "alertsmanagementresources | where type =~ 'microsoft.alertsmanagement/alerts' "
        "| project Inicio=todatetime(properties.essentials.startDateTime), Regla=tostring(properties.essentials.alertRule), "
        "Severidad=tostring(properties.essentials.severity), Estado=tostring(properties.essentials.monitorCondition), "
        "Recurso=tostring(split(tostring(properties.essentials.targetResource),'/')[-1]) | order by Inicio desc | take 50")],
        16, y, 8, 10, desc="Incluye las alertas con umbral dinámico (ML) del lab de Azure Monitor."))
    y += 10
    p.append(panel("table", "Reglas de alerta configuradas", [q_arg("A", sub,
        "resources | where type =~ 'microsoft.insights/metricalerts' "
        "| mv-expand c = properties.criteria.allOf "
        "| project Regla=name, ResourceGroup=resourceGroup, Metrica=tostring(c.metricName), "
        "Umbral=iff(tostring(c.criterionType)=='DynamicThresholdCriterion','Dinámico (ML)', strcat('Estático ', tostring(c.threshold))), "
        "Habilitada=tostring(properties.enabled)")],
        0, y, 24, 7))

    dashboard = {
        "title": "AIOps — Suscripción", "uid": "aiops-suscripcion", "tags": ["aiops", "azure"],
        "timezone": "browser", "schemaVersion": 39, "refresh": "1m",
        "time": {"from": "now-24h", "to": "now"},
        "templating": {"list": [{"name": "ds", "label": "Datasource", "type": "datasource",
                                 "query": "grafana-azure-monitor-datasource", "hide": 0}]},
        "panels": p,
    }
    json.dump({"dashboard": dashboard, "overwrite": True}, open(a.salida, "w"), ensure_ascii=False, indent=1)
    print(f"{a.salida}: {len(p)} paneles · {len(endpoints)} endpoints · {len(deps)} deployments · {len(webs)} web apps · {len(wss)} workspaces ML")


if __name__ == "__main__":
    main()
