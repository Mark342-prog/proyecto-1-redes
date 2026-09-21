# Chatbot de Farmacia con MCP + Mistral AI

Chatbot (consola y web) que usa la **API de Mistral AI** (La Plateforme) y se
conecta a varios servidores **MCP (Model Context Protocol)**: dos oficiales
(Filesystem y Git), uno propio (catálogo/pedidos de una cadena de farmacias)
corriendo en local, y ese mismo servidor propio corriendo de forma remota.

No usa ningún SDK de LLM ni de MCP: todo el JSON-RPC y las llamadas HTTP están
escritos a mano con la librería estándar de Python, tal como pide el proyecto.

## 1. Cómo mapea con los objetivos del proyecto

| Requisito | Dónde está |
|---|---|
| Conexión con un LLM a nivel de su API | `chatbot.py` → `MistralApi` (POST directo a `https://api.mistral.ai/v1/chat/completions`) |
| Mantener contexto en una sesión | `history` se acumula en `run_chat_turn` (consola) y en `AppState.histories` por `sessionId` (web) |
| Log de todas las interacciones con servidores MCP | `chatbot.py` → `InteractionLog` escribe cada petición/respuesta en `logs/mcp-*.jsonl` |
| Servidores MCP locales oficiales (Filesystem y Git) | `config.json` → `sistema_archivos` y `git` |
| Servidor MCP propio, caso de uso de industria | `pharmacy_core.py` + `mcp_protocol.py` (catálogo/pedidos de farmacia) |
| Servidor MCP propio corriendo local | `pharmacy_server.py` (stdio) vía `config.json` → `farmacia_local` |
| Servidor MCP propio corriendo remoto | `remote_server.py` (HTTP) vía `config.json` → `farmacia_remota` |
| Análisis con Wireshark | Ver sección 7 |

## 2. Instalación

Requiere **Python 3.11+**. Para los servidores oficiales también necesitas:

- **Node.js** (para `npx`, usado por el servidor Filesystem)
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** (para `uvx`, usado por el servidor Git)

```bash
cd pharmacy-mcp-chatbot
cp .env.example .env
```

### Obtener la API key de Mistral

1. Crea una cuenta en https://console.mistral.ai y activa el plan gratuito
   **Experiment**. Pide verificación por SMS, pero **no** tarjeta de crédito.
2. Genera la key en https://console.mistral.ai/api-keys
3. Pégala en tu archivo `.env`:

```
MISTRAL_API_KEY=tu-api-key
MISTRAL_MODEL=mistral-small-latest
```

El plan Experiment es gratuito con límites de tasa, suficiente para este
proyecto. No hay dependencias de Python que instalar: todo es librería estándar.

### Verificar que la key funciona

```bash
curl https://api.mistral.ai/v1/chat/completions \
  -H "Authorization: Bearer TU_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "mistral-small-latest", "messages": [{"role": "user", "content": "hola"}]}'
```

Debe devolver un JSON con `choices[0].message.content`.

### Modelos disponibles

Los tres soportan **function calling**, que es lo que necesitan los servidores MCP:

| Modelo | Cuándo usarlo |
|---|---|
| `mistral-small-latest` | Por defecto: el más económico y rápido |
| `mistral-medium-latest` | Mejor razonamiento, si el small falla encadenando herramientas |
| `mistral-large-latest` | El más capaz, consume más cuota |

Se cambia solo con la variable `MISTRAL_MODEL` del `.env`; el código no cambia.

## 3. Pruebas automatizadas

Suite de pruebas unitarias (librería estándar `unittest`, sin dependencias):

```bash
python -m unittest discover -s tests -v
```

| Archivo | Qué prueba |
|---|---|
| `tests/test_pharmacy_core.py` | Catálogo, búsqueda por síntoma, existencias, pedidos, reglas de negocio (receta requerida, stock insuficiente, cantidades inválidas) y persistencia |
| `tests/test_mcp_protocol.py` | `initialize`, `notifications/initialized`, `tools/list`, `tools/call` (éxito, error de negocio vs. error de protocolo), métodos desconocidos, peticiones malformadas |
| `tests/test_chatbot_helpers.py` | `simplify_schema`, `safe_tool_name`, validación de `config.json`, parseo de `tool_calls`, formato de `tool_call_id` y respuesta de Mistral |

### Robustez incluida

- **Validación estricta de argumentos** en cada herramienta (tipos, longitudes, caracteres de control), en `pharmacy_core.py` y en `mcp_protocol.py` (defensa en profundidad).
- **Timeouts** en la comunicación con servidores stdio: si un servidor se cuelga, falla con un mensaje claro tras `timeout_seconds` (60s por defecto, configurable en `config.json`).
- **Reintentos con backoff exponencial** ante errores transitorios de Mistral (429 por límite de tasa, 5xx, problemas de red).
- **`tool_call_id` conforme a Mistral**: la API exige exactamente 9 caracteres alfanuméricos; cualquier id ausente o con otro formato se regenera automáticamente (`id_llamada_valido`), evitando un error 422 difícil de diagnosticar.
- **Parseo tolerante de `tool_calls`**: acepta `arguments` tanto en texto JSON como en objeto, y los campos dentro de `function` o al nivel superior.
- **Errores de herramienta no cortan la conversación**: si una llamada MCP falla, el error se le informa al modelo para que reaccione, en vez de abortar el turno.
- **Validación de `config.json`** al arrancar, con mensajes de error específicos.
- **Límites de tamaño de payload** (1 MB) en los endpoints HTTP.

## 4. Ejecutar el chatbot en consola

```bash
python chatbot.py
```

Comandos disponibles:

- `/tools` — lista todas las herramientas disponibles y su servidor de origen.
- `/call HERRAMIENTA {"clave": "valor"}` — llama una herramienta directo, sin pasar por el modelo.
- `/clear` — borra el contexto de la conversación.
- `/exit` — cierra todo.

### Ejemplo — caso de uso de farmacia

```
Tú: tengo dolor de cabeza, ¿qué me recomiendas?
Asistente: Según el catálogo, Paracetamol 500 mg o Ibuprofeno 200 mg pueden
ayudar con dolor de cabeza leve. Esto no es un diagnóstico...
```

### Ejemplo — Filesystem + Git

```
Tú: crea un archivo README.md en demo-repo con el título "Proyecto MCP",
    agrégalo al repositorio git y haz un commit con el mensaje "commit inicial"
```

> **Nota:** si `mistral-small-latest` no encadena bien las herramientas en el
> escenario de Filesystem + Git, sé más explícito en la instrucción o cambia
> `MISTRAL_MODEL` a `mistral-medium-latest` o `mistral-large-latest` en el `.env`.
> El código no cambia: solo la variable de entorno.

## 5. Ejecutar el chatbot como app web

```bash
python web_app.py
```

Abre http://127.0.0.1:8000. El frontend (`static/`) habla con `web_app.py` por
`POST /api/chat`, que reutiliza la misma lógica de la consola (`run_chat_turn`),
con un historial por `sessionId`.

## 6. Desplegar el servidor MCP remoto

> Guía detallada paso a paso en **[DEPLOY.md](DEPLOY.md)** (Google Cloud Run,
> incluye verificación, logs y limitaciones conocidas).

`remote_server.py` expone el mismo servicio de farmacia por HTTP
(`POST /mcp`, `GET /health`), sin dependencias externas. Con Google Cloud Run:

```dockerfile
# Dockerfile
FROM python:3.12-slim
COPY . /app
WORKDIR /app
CMD ["python", "remote_server.py"]
```

```bash
gcloud run deploy farmacia-mcp --source . --region us-central1 \
  --allow-unauthenticated --port 8080
```

(En Render/Railway el flujo es equivalente: subir el repo y usar
`python remote_server.py` como comando de arranque; inyectan `PORT` solos.)

Cuando tengas la URL pública:

1. Ponla en `.env` como `PHARMACY_REMOTE_URL=https://.../mcp`.
2. En `config.json`, pon `"enabled": true` en `farmacia_remota` (y `false` en
   `farmacia_local` si quieres usar solo la versión remota).
3. Corre `python chatbot.py`: usará el servidor remoto igual que el local, sin
   cambiar una línea de código — la única diferencia es el `transport` en
   `config.json` (`http` en vez de `stdio`).

## 7. Captura y análisis con Wireshark

Con el servidor remoto corriendo localmente (`python remote_server.py`) y el
chatbot apuntando a `http://localhost:8080/mcp`, captura en la interfaz de
loopback con el filtro:

```
tcp.port == 8080
```

Cómo identificar cada mensaje en el cuerpo JSON-RPC:

- **Petición** (cliente → servidor): tiene `"method"` y `"id"`. Espera respuesta.
- **Notificación** (cliente → servidor): tiene `"method"` pero **no** `"id"`
  (ej. `notifications/initialized`; el servidor responde `202 Accepted` sin cuerpo).
- **Respuesta** (servidor → cliente): tiene `"result"` o `"error"` y el mismo
  `"id"` de la petición que la originó.

Secuencia típica de sincronización: `initialize` (petición/respuesta) →
`notifications/initialized` (notificación) → `tools/list` → una o varias `tools/call`.

## 8. Estructura del proyecto

```
chatbot.py           Cliente MCP genérico + orquestación con Mistral AI (consola)
web_app.py            Mismo chatbot, expuesto como app web
pharmacy_core.py      Lógica de negocio de la farmacia (independiente del transporte)
mcp_protocol.py        Traducción JSON-RPC <-> PharmacyService (compartida)
pharmacy_server.py    Transporte local: MCP sobre stdio
remote_server.py       Transporte remoto: MCP sobre HTTP
config.json             Qué servidores MCP arrancar y cómo
Dockerfile               Imagen del servidor MCP remoto (solo para la nube)
DEPLOY.md                 Guía de despliegue en Google Cloud Run
static/                  Frontend web (HTML/CSS/JS)
tests/                    Pruebas unitarias (unittest, sin dependencias externas)
logs/                     Se genera solo: bitácora de interacciones MCP
workspace/                Carpeta permitida para el servidor Filesystem (incluye demo-repo/)
```
