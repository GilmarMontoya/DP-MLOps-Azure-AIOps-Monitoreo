# ==================== Instalar el Azure MCP Server en Claude Code ====================
#
# Hay DOS formas de hacerlo. Elige una:
#
#   FORMA A (manual)  -> los comandos de este archivo.
#   FORMA B (asistida)-> dentro de Claude Code escribe:  /instalar-azure-mcp
#                        y la skill del proyecto hace todo esto por ti.
#
# Lo que instalamos es el plugin oficial "azure" de Microsoft, que por dentro
# levanta el paquete npm @azure/mcp (el mismo que documenta Microsoft Learn:
# https://learn.microsoft.com/es-es/azure/developer/azure-mcp-server/overview)


# ============================== Requisitos previos ==============================
# Paso 1: Verificamos que tenemos Node (el MCP se ejecuta con npx)
node --version        # debe salir v18 o superior
npx --version

# Paso 2: Verificamos que tenemos el Azure CLI
az version

# Paso 3: Iniciamos sesion en Azure  <-- IMPORTANTE
# El MCP NO pide tokens ni claves: reutiliza esta sesion del Azure CLI.
# Si no haces login, el MCP instala bien pero todas las herramientas fallan.
az login

# Paso 4: Confirmamos con que suscripcion vamos a trabajar
az account show

# Paso 5 (solo si tienes varias suscripciones): fijamos la que usaremos
az account list --output table
az account set --subscription "NOMBRE-O-ID-DE-TU-SUSCRIPCION"


# =========================== Instalamos el plugin ===============================
# Paso 6: Agregamos el marketplace oficial de Anthropic
# (si ya lo tienes, el comando simplemente avisa que ya existe)
claude plugin marketplace add anthropics/claude-plugins-official

# Paso 7: Instalamos el plugin de Azure
claude plugin install azure@claude-plugins-official

# Paso 7-bis: La MISMA instalacion, pero desde adentro de Claude Code.
# Si ya tienes una sesion abierta, escribe esto en el chat en vez del Paso 7:
#     /plugin install azure@claude-plugins-official

# Paso 8: Reiniciamos Claude Code  <-- OBLIGATORIO
# El MCP no aparece hasta reiniciar la sesion.
# Sal con Ctrl+C dos veces (o /exit) y vuelve a entrar con:
claude


# ============================== Verificamos =====================================
# Paso 9: El plugin debe aparecer como "enabled"
claude plugin list

# Paso 10: El servidor MCP "azure" debe aparecer como "Connected"
claude mcp list

# Paso 11: Prueba real, ya dentro de Claude Code. Escribe en el chat:
#     Lista mis resource groups de Azure
#     Muestrame las storage accounts de mi suscripcion


# ==================== ALTERNATIVA: el MCP sin el plugin =========================
# Esto instala EXACTAMENTE el mismo servidor MCP, pero sin las skills de
# Microsoft y dejandote controlar los flags. Util si quieres modo solo-lectura.

# Opcion 1 - completo (equivale a lo que hace el plugin):
claude mcp add azure -- npx -y @azure/mcp@latest server start

# Opcion 2 - solo lectura, recomendado para alumnos:
# Con --read-only el MCP no puede crear, modificar ni borrar nada en Azure.
claude mcp add azure -- npx -y @azure/mcp@latest server start --read-only

# Opcion 3 - solo lectura y limitado a los servicios que nos interesan:
claude mcp add azure -- npx -y @azure/mcp@latest server start --read-only \
  --namespace storage --namespace monitor --namespace group --namespace acr


# ================================ Desinstalar ===================================
# Si instalaste por plugin:
claude plugin uninstall azure@claude-plugins-official

# Si instalaste con "claude mcp add":
claude mcp remove azure


# ==================================== NOTAS =====================================
#
# NOTA 1 — Plugin vs "claude mcp add": es el MISMO servidor.
#   El plugin de Microsoft por dentro contiene este archivo .mcp.json:
#
#       {
#         "mcpServers": {
#           "azure": {
#             "command": "npx",
#             "args": ["-y", "@azure/mcp@latest", "server", "start"]
#           }
#         }
#       }
#
#   O sea, mismo paquete y mismo comando que la doc de Microsoft. La diferencia
#   es que el plugin ADEMAS trae 28 skills de Azure (azure-deploy,
#   azure-diagnostics, azure-cost, azure-prepare...) y un hook.
#   Coste: esas 28 skills anaden ~6.3k tokens SIEMPRE ACTIVOS a cada sesion de
#   Claude Code, uses Azure o no. Con "claude mcp add" ese coste es cero.
#
# NOTA 2 — El plugin arranca SIN --read-only.
#   Es decir, puede crear y borrar recursos reales, limitado unicamente por los
#   permisos RBAC de tu usuario en Azure. Para clase, si no quieres sustos, usa
#   la Opcion 2 de la seccion ALTERNATIVA.
#   Los secretos (Key Vault, connection strings) siempre piden confirmacion
#   explicita antes de mostrarse.
#
# NOTA 3 — Ambito de instalacion (--scope).
#   Por defecto el plugin se instala en "user": queda disponible en TODOS tus
#   proyectos. Si lo quieres solo en esta carpeta:
#
#       claude plugin install azure@claude-plugins-official --scope project
#
# NOTA 4 — El Azure MCP Server NO cubre Azure Machine Learning.
#   Revisando la tabla de herramientas, en "AI and Machine Learning" solo hay
#   foundry, search, speech y sreagent. NO hay tools para workspaces, jobs,
#   compute clusters, model registry ni online/batch endpoints de Azure ML.
#   Para todo eso seguimos usando "az ml" y el SDK de Python.
#
#   Lo que si nos sirve del MCP en este modulo:
#       storage   -> revisar los outputs de los batch endpoints en el blob
#       monitor   -> consultar logs con KQL para depurar un endpoint que falla
#       acr       -> ver las imagenes de los environments
#       group     -> inventario de recursos de la sesion
#       pricing   -> cuanto nos esta costando el compute cluster
#       advisor   -> que recursos deberiamos apagar
#
# NOTA 5 — La doc de Microsoft no lista Claude Code entre los editores
#   soportados (solo VS Code, Cursor, IntelliJ...). Es un tema de cobertura de
#   documentacion, no una limitacion: el README del repo microsoft/mcp si
#   documenta la instalacion como plugin de Claude Code.
#
# NOTA 6 — A la fecha, @azure/mcp va en la version 3.0.0-beta.39. Es BETA:
#   los nombres de las herramientas todavia pueden cambiar entre versiones.
