---
name: instalar-azure-mcp
description: Instala y verifica el Azure MCP Server en Claude Code mediante el plugin oficial de Microsoft (azure@claude-plugins-official), comprobando antes los requisitos (Node, Azure CLI, az login, suscripcion). Usar cuando el usuario pida instalar, configurar, conectar o verificar el MCP de Azure / Azure MCP Server / el plugin de Azure — o cuando diga "quiero conectar Claude con Azure", "no me aparecen las herramientas de Azure", "instalar la MCP de Azure", "azure mcp no conecta".
---

# Instalar el Azure MCP Server en Claude Code

Instala el plugin oficial `azure` de Microsoft, que envuelve el paquete npm
`@azure/mcp` — el mismo servidor MCP que documenta Microsoft Learn.

Material de clase equivalente en comandos sueltos: `Comandos.md` en la raíz del
proyecto. Esta skill es la vía asistida; ese archivo es la vía manual. Si
cambias algo aquí, mantén los dos alineados.

## Antes de empezar

Ejecuta los pasos **en orden** y no avances si uno falla: cada paso depende del
anterior. Ve informando al usuario qué encontraste en cada verificación, en una
línea, sin volcar la salida cruda de los comandos.

## Paso 1 — Requisitos

```bash
node --version && npx --version && az version
```

- Si falta Node (v18+): detente e indica que lo instale desde nodejs.org o con
  `brew install node`. El MCP se ejecuta con `npx`, sin Node no arranca.
- Si falta `az`: detente e indica `brew install azure-cli` (macOS) o la guía de
  Microsoft para Windows/Linux.

## Paso 2 — Sesión de Azure

```bash
az account show
```

El MCP **no usa tokens ni claves propias**: reutiliza la sesión del Azure CLI.

- Si el comando falla o no hay sesión, **no ejecutes `az login` tú**: es
  interactivo y abre el navegador. Pide al usuario que lo escriba él en la
  sesión con `! az login`, y espera a que confirme antes de seguir.
- Si hay sesión, confírmale en una línea qué suscripción y tenant están activos,
  porque todo lo que haga el MCP irá contra esa suscripción.
- Si el usuario dice que esa no es la suscripción correcta:
  `az account list --output table` y luego `az account set --subscription "<nombre-o-id>"`.

## Paso 3 — Comprobar si ya está instalado

```bash
claude plugin list && claude mcp list 2>&1 | grep -i azure
```

Si el plugin `azure` ya aparece como enabled y el MCP conecta, no reinstales:
informa que ya está listo y salta al Paso 6 (prueba real).

## Paso 4 — Instalar

```bash
claude plugin marketplace add anthropics/claude-plugins-official
claude plugin install azure@claude-plugins-official
```

El primer comando es idempotente; si el marketplace ya existe solo avisa.

Ámbito: por defecto se instala en scope `user` (disponible en todos los
proyectos del usuario). Si el usuario quiere limitarlo a esta carpeta, añade
`--scope project`. Pregúntaselo solo si menciona el tema; si no, usa el
default.

## Paso 5 — Reiniciar

El MCP **no aparece hasta reiniciar Claude Code**. No puedes hacerlo tú.
Dile explícitamente al usuario que salga (`/exit` o Ctrl+C dos veces) y vuelva
a entrar con `claude`, y que al volver te pida verificar.

## Paso 6 — Verificar (tras el reinicio)

```bash
claude plugin list && claude mcp list
```

`azure` debe salir como enabled y el servidor MCP como Connected. Luego propón
una prueba real, por ejemplo pedirle *"lista mis resource groups de Azure"*.

Si el MCP aparece pero falla al usarlo, casi siempre es el Paso 2: sesión de
Azure caducada. Que repita `az login`.

## Modo solo lectura (recomendado en aula)

El plugin arranca el servidor **sin** `--read-only`: puede crear y borrar
recursos reales, con los permisos RBAC del usuario como único límite. Si el
usuario es alumno, está en una sesión de clase, o pide algo seguro / sin riesgo,
**ofrécele esta alternativa antes de instalar el plugin**:

```bash
claude mcp add azure -- npx -y @azure/mcp@latest server start --read-only
```

Es el mismo servidor MCP, sin capacidad de escritura, sin las skills de
Microsoft y sin coste de contexto. Se puede acotar más a servicios concretos:

```bash
claude mcp add azure -- npx -y @azure/mcp@latest server start --read-only \
  --namespace storage --namespace monitor --namespace group --namespace acr
```

No instales las dos vías a la vez: ambas registran un servidor llamado `azure` y
entran en conflicto.

## Desinstalar

```bash
claude plugin uninstall azure@claude-plugins-official   # si fue por plugin
claude mcp remove azure                                 # si fue por claude mcp add
```

## Qué cubre y qué NO

Aclara esto si el usuario pregunta para qué sirve, y **siempre** si pide usar el
MCP para tareas de Azure Machine Learning.

**No cubre Azure ML.** En la categoría "AI and Machine Learning" el servidor
solo expone `foundry`, `search`, `speech` y `sreagent`. No hay herramientas para
workspaces, jobs, compute clusters, model registry ni online/batch endpoints de
Azure ML. Para eso se sigue usando `az ml` y el SDK de Python.

Sí cubre (útil en este módulo):

| Namespace | Para qué |
|---|---|
| `storage` | revisar outputs de batch endpoints en el blob |
| `monitor` | consultar logs con KQL y depurar un endpoint que falla |
| `acr` | ver las imágenes de los environments |
| `group`, `subscription`, `role` | inventario de recursos y permisos |
| `pricing`, `advisor` | costo del compute cluster y qué apagar |
| `deploy`, `bicepschema`, `azureterraform` | infraestructura como código |

## Notas

- El plugin y `claude mcp add` levantan **el mismo** paquete: el `.mcp.json` del
  plugin es literalmente `npx -y @azure/mcp@latest server start`. La diferencia
  es que el plugin añade 28 skills de Azure y un hook, y que esas skills cuestan
  ~6.3k tokens siempre activos en cada sesión (con `claude mcp add`, cero).
- `@azure/mcp` está en beta (3.0.0-beta.x): los nombres de herramientas pueden
  cambiar entre versiones.
- Las herramientas que exponen secretos (Key Vault, connection strings) piden
  confirmación explícita del usuario antes de devolver nada.
