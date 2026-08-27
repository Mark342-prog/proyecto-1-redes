# Chatbot de Farmacia con MCP + Gemini

## 1. Instalación

Requiere **Python 3.11+**. Para los servidores oficiales también necesitas:

- **Node.js** (para `npx`, usado por el servidor Filesystem)
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** (para `uvx`, usado por el servidor Git)

```bash
cd pharmacy-mcp-chatbot
cp .env.example .env
```

Edita `.env` y coloca tu `GEMINI_API_KEY` (gratis en https://aistudio.google.com/apikey,
no requiere tarjeta). No hay dependencias de Python que instalar: todo es
librería estándar.

---

Servidor MCP: simple-pharmacy-mcp

Caso de uso: cadena de farmacias — consulta de catálogo, búsqueda por síntoma, verificación de existencias y creación de pedidos simulados.

1. Información general

Campo	Valor
Nombre del servidor	simple-pharmacy-mcp
Versión	1.0.0
Versión del protocolo MCP	2025-11-25
Formato de mensajes	JSON-RPC 2.0
Capacidades declaradas	{"tools": {"listChanged": false}}

2. Transportes implementados

a) Local (stdio) — pharmacy_server.py

El cliente lanza el servidor como subproceso y se comunica por stdin/stdout, un mensaje JSON por línea.
Comando: python pharmacy_server.py

b) Remoto (Streamable HTTP) — remote_server.py

Endpoint principal: POST /mcp — recibe y responde JSON-RPC.
Endpoint de salud: GET /health — responde {"status": "ok", "service": "simple-pharmacy-mcp"}.
Headers de la petición: Content-Type: application/json, MCP-Protocol-Version: 2025-11-25.
Códigos de respuesta: 200 (respuesta con resultado), 202 (notificación, sin cuerpo de respuesta), 400 (error de parseo), 403 (origen no permitido), 404 (ruta inválida).
Protección: valida el header Origin, solo acepta localhost/127.0.0.1 (evita DNS rebinding).

3. Métodos JSON-RPC soportados

Método	Tipo	Descripción
initialize	Petición	Handshake inicial; devuelve protocolVersion, capabilities, serverInfo
notifications/initialized	Notificación	Confirma que el cliente terminó el handshake
tools/list	Petición	Devuelve las 4 herramientas disponibles con su inputSchema
tools/call	Petición	Ejecuta una herramienta por nombre
ping	Petición	Verifica que el servidor sigue vivo

4. Herramientas (tools) expuestas

list_medicines

Parámetros: ninguno.
Devuelve: lista completa del catálogo (nombre, precio, existencias, si requiere receta).

find_by_symptom

Parámetros: symptom (string, mínimo 2 caracteres, requerido).
Devuelve: medicamentos de venta libre que coinciden con el síntoma, más un aviso de que no es un diagnóstico.

check_stock

Parámetros: name (string, mínimo 2 caracteres, requerido).
Devuelve: precio, existencias y advertencia de ese medicamento.

create_order

Parámetros: name (string, requerido), quantity (entero 1–10, requerido), customer_name (string, mínimo 2 caracteres, requerido).
Devuelve: pedido simulado (order_id, total, estado) y reduce el inventario.
Reglas de negocio: rechaza medicamentos con receta obligatoria; rechaza si no hay existencias suficientes.

---

## 3. Pruebas automatizadas

El proyecto incluye una suite de pruebas unitarias (librería estándar `unittest`,
sin dependencias externas) que cubre la lógica de negocio, el protocolo MCP y
las funciones auxiliares del chatbot:

```bash
python -m unittest discover -s tests -v
```

| Archivo | Qué prueba |
|---|---|
| `tests/test_pharmacy_core.py` | Catálogo, búsqueda por síntoma, existencias, creación de pedidos, reglas de negocio (receta requerida, stock insuficiente, cantidades inválidas) y persistencia en disco |
| `tests/test_mcp_protocol.py` | `initialize`, `notifications/initialized`, `tools/list`, `tools/call` (éxito, error de negocio vs. error de protocolo), métodos desconocidos, peticiones malformadas |
| `tests/test_chatbot_helpers.py` | `simplify_schema`, `safe_tool_name`, validación de `config.json` |

## 4. Ejecutar el chatbot en consola

```bash
python chatbot.py
```

Al iniciar verás cómo se lanzan y saludan (`initialize`) los servidores
`farmacia_local`, `sistema_archivos` y `git` (uno por uno, como subprocesos).
Comandos útiles:

- `/tools` — lista todas las herramientas disponibles, con su servidor de origen.
- `/call HERRAMIENTA {"clave": "valor"}` — llama una herramienta directamente, sin pasar por Gemini.
- `/clear` — borra el contexto de la conversación.
- `/exit` — termina el programa (cierra todos los subprocesos MCP).

### Ejemplo — caso de uso de farmacia

```
Tú: tengo dolor de cabeza, ¿qué me recomiendas?
Asistente: Según el catálogo, Paracetamol 500 mg o Ibuprofeno 200 mg pueden
ayudar con dolor de cabeza leve. Esto no es un diagnóstico...
```
