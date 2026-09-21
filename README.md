# Pharmacy MCP Chatbot

A command-line (and optional web) chatbot that acts as an **MCP host**: it talks
to a Large Language Model through its HTTP API and connects to several
**Model Context Protocol (MCP)** servers, both local and remote.

The whole MCP protocol layer — JSON-RPC 2.0 message formatting, the
initialization handshake, tool discovery and tool invocation — is implemented
**by hand using only the Python standard library**. No MCP SDKs (FastMCP or
similar) and no LLM SDKs are used.

> Versión en español: [README.es.md](README.es.md)

---

## Table of contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Requirements](#requirements)
4. [Installation](#installation)
5. [Configuration](#configuration)
6. [Usage](#usage)
7. [Pharmacy MCP server specification](#pharmacy-mcp-server-specification)
8. [Remote deployment](#remote-deployment)
9. [Capturing traffic with Wireshark](#capturing-traffic-with-wireshark)
10. [Testing](#testing)
11. [Project structure](#project-structure)
12. [Known limitations](#known-limitations)

---

## Features

| # | Feature | Where it lives |
|---|---|---|
| 1 | LLM connection through its raw HTTP API (Mistral AI) | `chatbot.py` → `MistralApi` |
| 2 | Conversation context kept across the session | `run_chat_turn()` keeps the message history |
| 3 | Log of every MCP request and response | `InteractionLog` → `logs/mcp-*.jsonl` |
| 4 | Official MCP servers: **Filesystem** and **Git** | `config.json` → `sistema_archivos`, `git` |
| 5 | Custom **local** MCP server (pharmacy use case) | `pharmacy_server.py` (stdio transport) |
| 6 | Same custom server running **remotely** on Google Cloud Run | `remote_server.py` (HTTP transport) |
| — | Web UI (optional) | `web_app.py` + `static/` |

### Industry use case

A pharmacy chain offers a chatbot so customers can describe their symptoms,
get **over-the-counter** product suggestions from the catalog, check stock and
place a (simulated) order. The server enforces basic safety rules: it never
suggests or sells prescription-only medicines, and every symptom lookup
includes a notice that it is not a medical diagnosis.

---

## Architecture

```
                         ┌──────────────────────┐
                         │   Mistral AI API     │
                         │ /v1/chat/completions │
                         └──────────▲───────────┘
                                    │ HTTPS (tool calling)
┌───────────────────────────────────┴──────────────────────────────────┐
│                       chatbot.py  (MCP host)                         │
│          MCP client written by hand · JSON-RPC 2.0 · logging         │
└────┬──────────────────┬────────────────────┬─────────────────────┬───┘
     │ stdio            │ stdio              │ stdio               │ HTTPS
     ▼                  ▼                    ▼                     ▼
┌────────────┐   ┌────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ Filesystem │   │    Git     │   │ Pharmacy (local) │   │ Pharmacy (remote)│
│ (official) │   │ (official) │   │pharmacy_server.py│   │ remote_server.py │
└────────────┘   └────────────┘   └──────────────────┘   │ Google Cloud Run │
                                                         └──────────────────┘
```

Both pharmacy servers share the same business logic (`pharmacy_core.py`) and
the same protocol layer (`mcp_protocol.py`). Only the **transport** differs,
so the chatbot uses the remote server exactly like the local one — switching
between them is a one-line change in `config.json`.

### Message flow for one user prompt

1. The user types a message; it is appended to the conversation history.
2. The history and the list of available MCP tools are sent to the LLM.
3. If the LLM requests a tool, the chatbot routes it to the right MCP server
   with a JSON-RPC `tools/call` request and logs the request and the response.
4. The tool result is appended to the history as a `tool` message and the LLM
   is called again (up to 5 rounds per prompt).
5. When the LLM answers with plain text, it is shown to the user.

---

## Requirements

- **Python 3.11+** — no third-party Python packages are needed.
- **Node.js** — provides `npx`, used to launch the official Filesystem server.
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** — provides
  `uvx`, used to launch the official Git server.
- A **Mistral AI API key** — free "Experiment" plan at
  [console.mistral.ai](https://console.mistral.ai) (phone verification, no
  credit card).

---

## Installation

```bash
git clone <your-repository-url>
cd proyecto-1-redes
cp .env.example .env        # on Windows PowerShell: copy .env.example .env
```

Edit `.env` and set your API key:

```
MISTRAL_API_KEY=your-api-key
MISTRAL_MODEL=mistral-small-latest
```

Verify the key works before running the chatbot:

```bash
curl https://api.mistral.ai/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "mistral-small-latest", "messages": [{"role": "user", "content": "hello"}]}'
```

The Git MCP server needs an existing Git repository to operate on. The project
ships with one at `workspace/demo-repo`; if yours is missing, create it with:

```bash
git init workspace/demo-repo
```

> **Windows note:** if `uvx` is installed but the Git server fails with
> `WinError 2`, `uvx` is not on the `PATH` seen by Python. Either add
> `%USERPROFILE%\.local\bin` to your `PATH`, or put the full path to `uvx.exe`
> in the `command` of the `git` server in `config.json`.

---

## Configuration

### Environment variables (`.env`)

| Variable | Used by | Description |
|---|---|---|
| `MISTRAL_API_KEY` | chatbot | Mistral API key (required) |
| `MISTRAL_MODEL` | chatbot | Model name. Default: `mistral-small-latest` |
| `PHARMACY_REMOTE_URL` | chatbot | URL of the remote MCP server, ending in `/mcp` |
| `PHARMACY_DATA` | pharmacy server | Path of the JSON data file. Default: `pharmacy_data.json` |
| `PORT` | remote server | Listening port. Default: `8080` |
| `WEB_HOST`, `WEB_PORT` | web UI | Default: `127.0.0.1:8000` |

`.env` is listed in `.gitignore` and must never be committed.

### MCP servers (`config.json`)

Each entry defines one MCP server. `stdio` servers are launched as
subprocesses; `http` servers are reached over the network.

```json
{
  "servers": {
    "farmacia_local": {
      "transport": "stdio",
      "command": ["python", "pharmacy_server.py"],
      "enabled": false
    },
    "sistema_archivos": {
      "transport": "stdio",
      "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "./workspace"],
      "enabled": true
    },
    "git": {
      "transport": "stdio",
      "command": ["uvx", "mcp-server-git", "--repository", "./workspace/demo-repo"],
      "enabled": true
    },
    "farmacia_remota": {
      "transport": "http",
      "url_env": "PHARMACY_REMOTE_URL",
      "enabled": true
    }
  }
}
```

Optional per-server key: `timeout_seconds` (default `60`) — how long the
client waits for a server response before failing.

To switch between the local and the remote pharmacy server, flip the
`enabled` flags of `farmacia_local` and `farmacia_remota`. No code changes are
needed.

### Choosing a model

All of these support function calling, which the MCP integration requires:

| Model | When to use |
|---|---|
| `mistral-small-latest` | Default. Cheapest and fastest; handled all project scenarios in testing |
| `mistral-medium-latest` | If the small model struggles to chain several tools |
| `mistral-large-latest` | Most capable; uses more of the free quota |

---

## Usage

### Console chatbot

```bash
python chatbot.py
```

On startup, the chatbot performs the MCP handshake with every enabled server
and prints each message:

```
  [MCP farmacia_remota request] initialize
  [MCP farmacia_remota response] response
  [MCP farmacia_remota request] notifications/initialized
  [MCP farmacia_remota request] tools/list
  [MCP farmacia_remota response] response
```

Available commands:

| Command | Description |
|---|---|
| `/tools` | List every tool exposed by the connected MCP servers |
| `/call TOOL {json}` | Call a tool directly, bypassing the LLM |
| `/clear` | Clear the conversation context |
| `/exit` | Quit and shut down all MCP server subprocesses |

### Example 1 — General knowledge and context

```
You: Who was Alan Turing?
Assistant: Alan Turing was a British mathematician and computer scientist...

You: When was he born?
Assistant: He was born on June 23, 1912.
```

The second question works because the whole conversation history is sent to
the LLM on every turn.

### Example 2 — Pharmacy server

```
You: I have a headache, what do you recommend?
  [MCP farmacia_remota request] tools/call
  [MCP farmacia_remota response] response
Assistant: For a headache we have Paracetamol 500 mg and Ibuprofen 200 mg
available... If the pain is severe or comes with other serious symptoms,
seek urgent medical attention.
```

### Example 3 — Filesystem + Git servers

```
You: create a README.md file in demo-repo with the title "Proyecto MCP",
     add it to the git repository and commit it with the message "commit inicial"
  [MCP sistema_archivos request] tools/call
  [MCP sistema_archivos response] response
  [MCP git request] tools/call
  [MCP git response] response
  ...
Assistant: Done! README.md was created, staged and committed.
```

Verify the result independently of the chatbot:

```bash
git -C workspace/demo-repo log --stat
```

### Example 4 — Calling a tool directly

```
You: /call farmacia_remota__check_stock {"name": "Loratadina"}
```

### MCP interaction log

Every JSON-RPC message exchanged with every MCP server is appended to
`logs/mcp-YYYYMMDD-HHMMSS.jsonl`, one JSON object per line:

```json
{"timestamp": "2026-09-20T19:51:52+00:00", "server": "git", "direction": "request",
 "payload": {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "git_commit", "arguments": {"message": "commit inicial"}}}}
```

The console shows a one-line summary of each message; the file holds the full
payloads.

### Web UI (optional)

```bash
python web_app.py
```

Open <http://127.0.0.1:8000>. The web UI reuses exactly the same logic as the
console chatbot and keeps a separate history per browser session.

---

## Pharmacy MCP server specification

### General information

| Field | Value |
|---|---|
| Server name | `simple-pharmacy-mcp` |
| Server version | `1.0.0` |
| MCP protocol version | `2025-11-25` |
| Message format | JSON-RPC 2.0 |
| Declared capabilities | `{"tools": {"listChanged": false}}` |

### Transports

**Local — stdio** (`pharmacy_server.py`)

The host launches the server as a subprocess and exchanges newline-delimited
JSON-RPC messages over its standard input and output.

```bash
python pharmacy_server.py
```

**Remote — HTTP** (`remote_server.py`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/mcp` | Receives a JSON-RPC message and returns the JSON-RPC response |
| `GET` | `/health` | Health check: `{"status": "ok", "service": "simple-pharmacy-mcp"}` |

Request headers: `Content-Type: application/json`,
`MCP-Protocol-Version: 2025-11-25`.

| HTTP status | Meaning |
|---|---|
| `200` | Request processed; body contains the JSON-RPC response |
| `202` | Notification accepted; no body |
| `400` | Malformed JSON, invalid `Content-Length`, or body is not a JSON object |
| `403` | `Origin` header not allowed (DNS-rebinding protection) |
| `404` | Unknown path |
| `405` | `GET` on a path other than `/health` |
| `413` | Body larger than 1 MB |

### JSON-RPC methods

| Method | Type | Description |
|---|---|---|
| `initialize` | Request | Handshake; returns `protocolVersion`, `capabilities`, `serverInfo` |
| `notifications/initialized` | Notification | Client confirms the handshake is complete (no response) |
| `tools/list` | Request | Returns the four tools with their JSON Schema |
| `tools/call` | Request | Executes a tool by name |
| `ping` | Request | Liveness check; returns `{}` |

### Tools

#### `list_medicines`

Lists the full catalog with price, stock and prescription status.

- **Parameters:** none

#### `find_by_symptom`

Finds over-the-counter products matching a symptom. Prescription-only
medicines are never returned. **This is not a medical diagnosis.**

| Parameter | Type | Required | Constraints |
|---|---|---|---|
| `symptom` | string | yes | 2–200 characters |

#### `check_stock`

Returns price, stock and safety warning for a medicine. Matching is
case-insensitive and accepts partial names (e.g. `"parace"`).

| Parameter | Type | Required | Constraints |
|---|---|---|---|
| `name` | string | yes | 2–200 characters |

#### `create_order`

Creates a simulated order and decreases the stock.

| Parameter | Type | Required | Constraints |
|---|---|---|---|
| `name` | string | yes | 2–200 characters |
| `quantity` | integer | yes | 1–10 |
| `customer_name` | string | yes | 2–200 characters |

Business rules: rejects prescription-only medicines, rejects orders larger
than the available stock.

### Example exchange

Request:

```json
{"jsonrpc": "2.0", "id": 3, "method": "tools/call",
 "params": {"name": "find_by_symptom", "arguments": {"symptom": "dolor de cabeza"}}}
```

Response:

```json
{"jsonrpc": "2.0", "id": 3, "result": {
  "content": [{"type": "text", "text": "{\"matches\": [...], \"notice\": \"...\"}"}],
  "structuredContent": {"matches": ["..."], "notice": "Estas son coincidencias del catálogo, no un diagnóstico..."},
  "isError": false
}}
```

### Error handling

> The server's catalog data, notices and error messages are in Spanish, since
> the pharmacy targets Spanish-speaking customers. The LLM answers in the
> user's language.

The server distinguishes two kinds of errors, as recommended by the MCP
specification:

**Protocol errors** are returned as a JSON-RPC `error` object:

| Code | Meaning |
|---|---|
| `-32700` | Parse error (invalid JSON) |
| `-32600` | Invalid request (not an object, missing `method`) |
| `-32601` | Method not found, or unknown tool |
| `-32602` | Invalid params (e.g. missing tool `name`) |
| `-32000` | Unexpected server error |

**Tool (business) errors** — medicine not found, prescription required,
insufficient stock, invalid arguments — are returned as a *successful*
JSON-RPC response with `"isError": true`, so the LLM can read the reason and
react instead of the conversation breaking:

```json
{"jsonrpc": "2.0", "id": 5, "result": {
  "content": [{"type": "text", "text": "este medicamento requiere receta y no se puede pedir por este medio"}],
  "isError": true
}}
```

---

## Remote deployment

The remote server is deployed on **Google Cloud Run**. Only the three files it
needs (`pharmacy_core.py`, `mcp_protocol.py`, `remote_server.py`) are copied
into the container image; the chatbot keeps running on the user's machine.

```bash
gcloud run deploy farmacia-mcp --source . --region us-central1 \
  --allow-unauthenticated --port 8080 --max-instances 1
```

Then point the chatbot to it in `.env`:

```
PHARMACY_REMOTE_URL=https://<your-service>.run.app/mcp
```

Step-by-step instructions, verification commands and log inspection are in
**[DEPLOY.md](DEPLOY.md)**.

---

## Capturing traffic with Wireshark

The Cloud Run endpoint only accepts **HTTPS**, so a capture against it shows
encrypted TLS records and the JSON-RPC messages cannot be read. To analyse the
protocol, run the **same** remote server locally over plain HTTP:

1. Start the server: `python remote_server.py` (listens on port 8080).
2. In `.env`, set `PHARMACY_REMOTE_URL=http://localhost:8080/mcp`.
3. In Wireshark, capture on the **loopback** interface
   (on Windows: *Adapter for loopback traffic capture*, installed with Npcap).
4. Apply the display filter `tcp.port == 8080` (or `http` to see only HTTP).
5. Run `python chatbot.py` and send a few prompts.

How to classify each JSON-RPC message in the HTTP bodies:

| Category | How to recognise it | Examples |
|---|---|---|
| **Synchronization** (handshake) | Sent once at startup | `initialize` and its response, `notifications/initialized` |
| **Request** | Has `method` **and** `id` | `tools/list`, `tools/call` |
| **Notification** | Has `method` but **no** `id`; server replies `202` with no body | `notifications/initialized` |
| **Response** | Has `result` or `error`, and the same `id` as its request | Any server reply |

---

## Testing

The project includes 62 unit tests using only the standard `unittest` module:

```bash
python -m unittest discover -s tests -v
```

| File | Covers |
|---|---|
| `tests/test_pharmacy_core.py` | Catalog, symptom search, stock, orders, business rules, persistence |
| `tests/test_mcp_protocol.py` | Handshake, `tools/list`, `tools/call`, protocol vs. tool errors, malformed requests |
| `tests/test_chatbot_helpers.py` | Schema simplification, tool naming, `config.json` validation, tool-call parsing, Mistral response handling |

### Robustness

- **Strict input validation** in every tool (types, lengths, control characters).
- **Timeouts** on stdio servers: a hung server fails with a clear message
  instead of freezing the chatbot.
- **Retries with exponential backoff** on transient LLM API errors
  (HTTP 429 and 5xx, network failures).
- **Tool errors never abort a turn**: they are reported back to the LLM.
- **Mistral-compatible tool call IDs**: Mistral requires exactly 9
  alphanumeric characters; IDs in any other format are regenerated.
- **Payload size limit** (1 MB) on every HTTP endpoint.

---

## Project structure

```
chatbot.py            MCP host: hand-written MCP client + Mistral API client
web_app.py            Optional web UI server reusing the chatbot logic
pharmacy_core.py      Pharmacy business logic (transport-independent)
mcp_protocol.py       JSON-RPC 2.0 / MCP protocol handler (shared)
pharmacy_server.py    Local transport: MCP over stdio
remote_server.py      Remote transport: MCP over HTTP
config.json           Which MCP servers to start and how
Dockerfile            Container image for the remote server
DEPLOY.md             Google Cloud Run deployment guide
.env.example          Environment variable template
static/               Web UI (HTML, CSS, JavaScript)
tests/                Unit tests
workspace/            Folder exposed to the Filesystem server (contains demo-repo/)
logs/                 MCP interaction logs (created at runtime)
```

---

## Known limitations

- **Ephemeral remote state.** On Cloud Run the inventory lives in a file
  inside the container. When the instance is recycled after inactivity,
  orders are lost and stock resets. A production version would use a managed
  database such as Cloud SQL or Firestore.
- **Cold starts.** After a period without traffic, the first request to Cloud
  Run takes a few seconds while the container starts.
- **No authentication on the remote server.** The endpoint is public, which
  is acceptable for this academic project but not for production.
- **Free-tier rate limits.** The Mistral "Experiment" plan allows roughly one
  request per second. A prompt that chains several tools makes several LLM
  calls; occasional HTTP 429 responses are retried automatically.
- **Simulated orders.** No payment or real inventory system is involved.
