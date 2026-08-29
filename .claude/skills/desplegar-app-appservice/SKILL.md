---
name: desplegar-app-appservice
description: Despliega una app web de Python (Flask/FastAPI) desde un repositorio de GitHub a Azure App Service con CI/CD por GitHub Actions, creando el Resource Group, el App Service Plan y la Web App, y verificando que la app responde de verdad. Usar cuando el usuario pida desplegar, publicar, subir o poner en produccion una app Flask / FastAPI / Python en Azure App Service — o cuando diga "desplegar el aplicativo de Iris", "subir mi modelo a Azure", "conectar mi repo de GitHub con App Service", "publicar mi API de ML".
---

# Desplegar una app Python a Azure App Service desde GitHub

Crea la infraestructura, conecta GitHub Actions y **verifica que la app responde**.

Probado end-to-end con la app Flask de clasificación Iris
(`Azure-WebApps/Problema-Iris-ML-Flask`). Los errores documentados aquí no son
teóricos: los seis ocurrieron en un despliegue real.

Para monitorear la app una vez desplegada: `/crear-azure-monitor`.

## Regla que gobierna todo este flujo

> **Un deploy en verde NO significa que la app funcione.**

GitHub Actions puede terminar con ✅ y la app devolver 503. Son dos etapas
distintas: *publicar los archivos* y *arrancar el contenedor*. Nunca declares el
despliegue exitoso sin hacer una petición HTTP real. El Paso 8 no es opcional.

## Paso 1 — Requisitos

```bash
az account show && gh auth status
```

- Sin sesión de Azure: pide al usuario `! az login` (es interactivo, no lo
  ejecutes tú) y espera confirmación.
- Sin sesión de GitHub: `! gh auth login`. Necesita scopes **`repo`** y
  **`workflow`**; sin `workflow` no se puede escribir en `.github/workflows/`.

## Paso 2 — Validar la app antes de tocar Azure

Revisa el repositorio o la carpeta local y comprueba:

| Qué | Por qué |
|---|---|
| `requirements.txt` existe | Oryx lo necesita para instalar dependencias |
| Hay un `app.py` con un objeto llamado `app` | Es la convención que Oryx autodetecta |
| Versiones **pinneadas** (`==`) | Un modelo `.pkl` cargado con otra versión de scikit-learn revienta al deserializar |
| Tamaño del `.pkl` | Si supera ~100 MB, Git LFS o Azure Storage, no el repo |

Avisa de estas dos trampas si las encuentras, **sin arreglarlas por tu cuenta**:

- **`Procfile`**: es sintaxis de Heroku. **Azure App Service lo ignora.** Si dice
  `web: python app.py`, eso no es lo que se ejecuta. No lo borres — puede que el
  usuario lo use en otro lado — pero explícale que en Azure no hace nada.
- **`app.py` sin bloque `if __name__ == "__main__": app.run()`**: es correcto y
  deseable en producción. Gunicorn importa el objeto `app`, no ejecuta el
  archivo. Menciónalo porque contradice lo que el alumno hizo en local con
  `flask run`.

## Paso 3 — Datos que faltan

Defaults que puedes usar sin preguntar:

| Dato | Default |
|---|---|
| Resource group | uno nuevo, `<proyecto>-app` |
| SKU | **B1** (~$0.018/h) |
| Runtime | `PYTHON:3.11` |
| Rama | `main` |

Pregunta solo el **repositorio** (`owner/repo`) y el **nombre de la Web App**,
que es global en `azurewebsites.net`. Compruébalo antes de intentar crearlo:

```bash
az rest --method post \
  --url "https://management.azure.com/subscriptions/$SUB/providers/Microsoft.Web/checknameavailability?api-version=2023-12-01" \
  --body '{"name":"<NOMBRE>","type":"Microsoft.Web/sites"}' \
  --query "{libre:nameAvailable, razon:message}" -o tsv
```

Sobre **F1 (Free) vs B1**: F1 cuesta $0 pero tiene cuota de 60 min de CPU/día,
**no soporta Always On** y la app se duerme — vas a ver cold starts de 20-30 s a
mitad de la demo. Si el lab incluye monitoreo, usa B1: una app dormida no genera
telemetría. Ofrece F1 solo si el usuario pide costo cero explícitamente.

## Paso 4 — Infraestructura, con fallback de región

**Trampa real:** muchas suscripciones tienen **0 VMs de cuota** para Basic en
ciertas regiones. En una suscripción de prueba, `brazilsouth` falló con
*"Amount required for this deployment (Total VMs): 1"* y hubo que usar
`canadacentral`.

No asumas la región. Recorre candidatas hasta que una funcione:

```bash
az group create -n $RG -l $LOC --tags lab=app-appservice -o none

for LOC in <region-preferida> canadacentral centralus eastus; do
  if az appservice plan create -g $RG -n $PLAN --is-linux --sku B1 -l $LOC -o none 2>/dev/null; then
    echo "plan creado en $LOC"; break
  fi
  echo "sin cuota en $LOC"
done

az webapp create -g $RG -p $PLAN -n $APP --runtime "PYTHON:3.11"
```

El resource group y el plan pueden estar en regiones distintas; no es un error.

## Paso 5 — Configurar la Web App

```bash
az webapp config appsettings set -g $RG -n $APP --settings \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true \
  ENABLE_ORYX_BUILD=true -o none

az webapp config set -g $RG -n $APP --always-on true -o none
```

### ⚠️ NO pongas un startup command personalizado

Es tentador escribir `--startup-file "gunicorn --bind=0.0.0.0 app:app"`.
**Rompe el despliegue.**

Oryx comprime el build (`CompressDestinationDir="true"`) y deja en `wwwroot`
solo un `output.tar.zst`; el script de arranque que él genera lo extrae en
`/tmp` y ejecuta gunicorn **desde ahí**. Un comando propio corre desde
`wwwroot`, donde no existe `app.py`, y el contenedor muere con **exit code 3**.

Síntoma exacto: deploy verde, luego 503, y `wwwroot` contiene únicamente
`output.tar.zst`, `oryx-manifest.toml`, `requirements.txt` y `hostingstart.html`.

Déjalo vacío. Oryx genera el comando correcto solo.

Si ya lo pusiste, `az webapp config set --startup-file ""` **no lo limpia**.
Hay que forzarlo por REST:

```bash
az rest --method patch \
  --url "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Web/sites/$APP/config/web?api-version=2023-12-01" \
  --body '{"properties":{"appCommandLine":""}}'
az webapp restart -g $RG -n $APP
```

## Paso 6 — Habilitar autenticación básica

En suscripciones nuevas viene **deshabilitada por defecto**, y el despliegue por
publish profile falla con un 401 poco descriptivo. Compruébalo y actívala:

```bash
az rest --method put \
  --url "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Web/sites/$APP/basicPublishingCredentialsPolicies/scm?api-version=2023-12-01" \
  --body '{"properties":{"allow":true}}'
```

Dile al usuario qué implica: habilita una credencial de larga vida en el
endpoint SCM de **esta** app. Es lo que hace el portal de Azure por defecto y es
aceptable para clase. En producción, lo correcto es OIDC con federated
credentials (sin secretos), pero requiere crear un app registration en Entra ID,
permiso que muchos alumnos no tienen.

## Paso 7 — Conectar GitHub Actions

```bash
az webapp deployment github-actions add \
  -g $RG -n $APP \
  --repo "<owner>/<repo>" --branch main \
  --runtime "PYTHON|3.11" \
  --token "$(gh auth token)" --force
```

Esto hace tres cosas bien: sube el publish profile como secret, enlaza el
Deployment Center y crea un workflow.

### ⚠️ El workflow que genera está roto — hay que reemplazarlo

Usa `azure/appservice-build@v2`, que ejecuta un **Oryx de noviembre de 2020**
dentro de un contenedor cuyo glibc es demasiado viejo para Python 3.11:

```
Oryx Version: 0.2.20201112.1
python3.11: /lib/x86_64-linux-gnu/libm.so.6: version `GLIBC_2.29' not found
```

Sobrescríbelo. Primero lee el nombre real del secret (lleva un hash aleatorio):

```bash
SECRET=$(gh secret list -R <owner>/<repo> --json name --jq '.[0].name')
SHA=$(gh api repos/<owner>/<repo>/contents/.github/workflows/<archivo>.yml --jq '.sha')
```

Genera el workflow correcto — compila en el runner y deja que Oryx construya en
la plataforma:

```yaml
name: Build and deploy Python app to Azure Web App
on:
  push:
    branches: [main]
  workflow_dispatch:
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          python -m venv antenv
          source antenv/bin/activate
          pip install -r requirements.txt
      - uses: actions/upload-artifact@v4
        with:
          name: python-app
          path: |
            .
            !antenv/
  deploy:
    runs-on: ubuntu-latest
    needs: build
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: python-app
      - uses: azure/webapps-deploy@v3
        with:
          app-name: '<APP>'
          slot-name: 'Production'
          publish-profile: ${{ secrets.<SECRET> }}
```

Súbelo con la Contents API (no hace falta clonar el repo):

```bash
gh api --method PUT "repos/<owner>/<repo>/contents/.github/workflows/<archivo>.yml" \
  -f message="Corrige workflow de despliegue" \
  -f content="$(base64 < wf.yml | tr -d '\n')" -f sha="$SHA" -f branch=main
```

El push dispara la ejecución.

## Paso 8 — Verificar de verdad

```bash
ID=$(gh run list -R <owner>/<repo> --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $ID -R <owner>/<repo> --exit-status
```

Si falla: `gh run view $ID -R <repo> --log-failed | tail -30`.

Cuando esté en verde, **prueba la app**. El contenedor tarda en extraer el
build, así que reintenta en vez de concluir que falló:

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  --retry 12 --retry-delay 15 --retry-all-errors --max-time 120 "https://$APP.azurewebsites.net/"
```

Prueba también un endpoint de inferencia real, no solo la home:

```bash
curl -s -X POST "https://$APP.azurewebsites.net/api" \
  -H "Content-Type: application/json" -d '{"sl":5.1,"sw":3.5,"pl":1.4,"pw":0.2}'
```

Si devuelve una predicción coherente, ahí sí está desplegado.

## Diagnóstico cuando devuelve 503

En orden, porque el primero resuelve la mayoría:

**1. ¿Se extrajo la app?**

```bash
CREDS=$(az webapp deployment list-publishing-credentials -g $RG -n $APP --query "{u:publishingUserName,p:publishingPassword}" -o tsv)
U=$(echo "$CREDS"|cut -f1); P=$(echo "$CREDS"|cut -f2)
curl -s -u "$U:$P" "https://$APP.scm.azurewebsites.net/api/vfs/site/wwwroot/"
```

Si solo ves `output.tar.zst` y `hostingstart.html`, es el startup command del
Paso 5. Bórralo por REST.

**2. Logs del contenedor**

```bash
az webapp log config -g $RG -n $APP --docker-container-logging filesystem --level verbose
curl -s -u "$U:$P" "https://$APP.scm.azurewebsites.net/api/logs/docker"
```

`exit code 3` = gunicorn no pudo importar la app (falta dependencia, error de
sintaxis, o `.pkl` incompatible).

**3. Estado del despliegue**

```bash
curl -s -u "$U:$P" "https://$APP.scm.azurewebsites.net/api/deployments"
```

## Tabla de errores verificados

| Síntoma | Causa | Solución |
|---|---|---|
| `Total VMs: 1` al crear el plan | Cuota 0 en esa región | Otra región (Paso 4) |
| 401 al desplegar | Basic auth deshabilitada | Paso 6 |
| `GLIBC_2.29 not found` | `appservice-build@v2` = Oryx 2020 | Reemplazar workflow (Paso 7) |
| Deploy verde + 503, `wwwroot` sin `app.py` | Startup command personalizado | Vaciarlo por REST (Paso 5) |
| `Procfile` ignorado | Es de Heroku | Informativo, no se arregla |
| App duerme, sin telemetría | F1 sin Always On | B1 + `--always-on true` |

## Cerrar

Resume al usuario: URL, resource group, región, costo por hora, y que **cada
push a `main` redespliega solo**.

Ofrece encadenar `/crear-azure-monitor` apuntando a esta Web App: es el destino
natural y esa skill pide exactamente un recurso ya desplegado.

Para borrar todo:

```bash
az group delete -n $RG --yes --no-wait
```

Recuérdale que el App Service Plan sigue cobrando aunque la app esté detenida:
**parar la Web App no ahorra nada**, hay que borrar el plan.
