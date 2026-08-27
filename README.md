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
