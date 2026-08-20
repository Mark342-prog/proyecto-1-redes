"""Chatbot de terminal con Gemini conectado a servidores MCP, sin usar SDKs de LLM ni de MCP."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PROTOCOL_VERSION = "2025-11-25"


def load_dotenv() -> None:
    """Carga un pequeño archivo .env local sin agregar una dependencia de terceros."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


class InteractionLog:
    """Registra en disco (JSON Lines) todas las peticiones y respuestas MCP, como pide el enunciado."""

    def __init__(self) -> None:
        log_dir = ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        self.path = log_dir / f"mcp-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
        self._lock = threading.Lock()

    def write(self, server: str, direction: str, payload: dict[str, Any]) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "server": server,
            "direction": direction,
            "payload": payload
        }
        with self._lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        print(f"  [MCP {server} {direction}] {payload.get('method', 'response')}")


class McpClient:
    """Cliente MCP genérico: sirve tanto para servidores locales (stdio) como remotos (HTTP)."""

    def __init__(self, name: str, config: dict[str, Any], log: InteractionLog) -> None:
        self.name, self.config, self.log = name, config, log
        self.next_id = 1
        self.process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._stderr_lines: list[str] = []

    def start(self) -> None:
        if self.config["transport"] == "stdio":
            command = list(self.config["command"])
            if command[0] == "python":
                command[0] = sys.executable
            else:
                resolved = shutil.which(command[0])
                if resolved:
                    command[0] = resolved
            child_env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
            self.process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=child_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8"
            )

            threading.Thread(target=self._drain_stderr, daemon=True).start()
        self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "simple-pharmacy-chatbot", "version": "2.0.0"}
        })
        self.notify("notifications/initialized", {})

    def _drain_stderr(self) -> None:
        assert self.process and self.process.stderr
        for line in self.process.stderr:
            self._stderr_lines.append(line.rstrip())
            del self._stderr_lines[:-20]

    def _send(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        self.log.write(self.name, "request", payload)
        if self.config["transport"] == "stdio":
            assert self.process and self.process.stdin and self.process.stdout
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            if "id" not in payload:
                return None
            line = self.process.stdout.readline()
            if not line:
                detail = " | ".join(self._stderr_lines[-3:])
                message = f"el servidor {self.name} se cerró inesperadamente"
                if detail:
                    message += f" — causa reportada: {detail}"
                raise RuntimeError(message)
            response = json.loads(line)
        else:
            url = self.config.get("url") or os.getenv(self.config.get("url_env", ""), "")
            if not url:
                raise RuntimeError(f"falta la URL para {self.name} (revisa config.json / .env)")
            body = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": PROTOCOL_VERSION
                },
                method="POST"
            )
            with urllib.request.urlopen(request, timeout=30) as result:
                raw = result.read()
            response = json.loads(raw) if raw else None
        if response is not None:
            self.log.write(self.name, "response", response)
        return response

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            payload = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params}
            self.next_id += 1
            response = self._send(payload)
        if not response:
            raise RuntimeError("respuesta JSON-RPC vacía")
        if "error" in response:
            raise RuntimeError(response["error"]["message"])
        return response["result"]

    def notify(self, method: str, params: dict[str, Any]) -> None:
        with self._lock:
            self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def close(self) -> None:
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()


def simplify_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Conserva solo el subconjunto de OpenAPI que aceptan las declaraciones de función de Gemini."""
    allowed = {"type", "description", "properties", "required", "items", "enum", "minimum", "maximum"}
    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in allowed:
            continue
        if key == "properties":
            result[key] = {name: simplify_schema(child) for name, child in value.items()}
        elif key == "items" and isinstance(value, dict):
            result[key] = simplify_schema(value)
        else:
            result[key] = value
    return result


class GeminiApi:
    def __init__(self) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

    def send(self, history: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.api_key or self.api_key == "replace-me":
            raise RuntimeError("Configura GEMINI_API_KEY en el archivo .env antes de conversar.")
        payload: dict[str, Any] = {
            "contents": history,
            "systemInstruction": {
                "parts": [{
                    "text": (
                        "Eres un asistente breve de una farmacia educativa. Usa las herramientas para consultar "
                        "catálogo, existencias o pedidos. No diagnostiques ni recomiendes medicamentos con receta. "
                        "Ante síntomas graves aconseja atención profesional urgente. Responde en el idioma del usuario."
                    )
                }]
            },
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 700}
        }
        if tools:
            payload["tools"] = [{"functionDeclarations": tools}]
        model = urllib.parse.quote(self.model, safe="")
        request = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Error de la API de Gemini {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"No se pudo conectar con Gemini: {exc.reason}") from exc


def safe_tool_name(server: str, tool: str) -> str:
    """Genera un nombre de función único y válido para Gemini a partir de servidor + herramienta."""
    return re.sub(r"[^A-Za-z0-9_.:-]", "_", f"{server}__{tool}")[:128]


def load_clients(log: InteractionLog) -> tuple[dict[str, McpClient], list[dict[str, Any]], dict[str, tuple[str, str]]]:
    """Lee config.json, arranca cada servidor MCP habilitado y arma la lista de herramientas para Gemini."""
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    clients: dict[str, McpClient] = {}
    api_tools: list[dict[str, Any]] = []
    routes: dict[str, tuple[str, str]] = {}
    for name, server_config in config["servers"].items():
        if not server_config.get("enabled", True):
            continue
        client = McpClient(name, server_config, log)
        try:
            client.start()
            clients[name] = client
            for tool in client.request("tools/list", {})["tools"]:
                exposed = safe_tool_name(name, tool["name"])
                routes[exposed] = (name, tool["name"])
                api_tools.append({
                    "name": exposed,
                    "description": f"[{name}] {tool.get('description', '')}",
                    "parameters": simplify_schema(tool["inputSchema"])
                })
        except Exception as exc:
            client.close()
            print(f"Aviso: no se pudo iniciar {name}: {exc}")
    return clients, api_tools, routes


def run_gemini_turn(
    prompt: str,
    history: list[dict[str, Any]],
    gemini: GeminiApi,
    clients: dict[str, McpClient],
    api_tools: list[dict[str, Any]],
    routes: dict[str, tuple[str, str]]
) -> str:
    """Envía un mensaje a Gemini y resuelve, en bucle, las llamadas a herramientas MCP que pida."""
    history.append({"role": "user", "parts": [{"text": prompt}]})
    for _ in range(5):
        answer = gemini.send(history, api_tools)
        candidates = answer.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"Gemini no devolvió una respuesta: {answer.get('promptFeedback', answer)}")
        content = candidates[0].get("content") or {"role": "model", "parts": []}
        history.append(content)
        parts = content.get("parts") or []
        calls = [part["functionCall"] for part in parts if "functionCall" in part]
        if not calls:
            text = "".join(part.get("text", "") for part in parts).strip()
            return text or "Gemini respondió sin contenido de texto."

        responses = []
        for call in calls:
            if call["name"] not in routes:
                result = {"isError": True, "message": "Herramienta desconocida"}
            else:
                server_name, original_name = routes[call["name"]]
                result = clients[server_name].request(
                    "tools/call",
                    {"name": original_name, "arguments": call.get("args") or {}}
                )
            function_response: dict[str, Any] = {
                "name": call["name"],
                "response": {"mcpResult": result}
            }
            if call.get("id"):
                function_response["id"] = call["id"]
            responses.append({"functionResponse": function_response})
        history.append({"role": "user", "parts": responses})
    raise RuntimeError("Gemini alcanzó el límite de llamadas a herramientas para este mensaje.")


def main() -> None:
    load_dotenv()
    log = InteractionLog()
    clients, api_tools, routes = load_clients(log)
    if not clients:
        raise SystemExit("No se pudo iniciar ningún servidor MCP.")
    gemini = GeminiApi()
    history: list[dict[str, Any]] = []
    print("\nChatbot de Farmacia Simple - Gemini")
    print("Comandos: /tools, /call HERRAMIENTA {json}, /clear, /exit")
    print(f"Registro MCP: {log.path}\n")
    try:
        while True:
            prompt = input("Tú: ").strip()
            if not prompt:
                continue
            if prompt == "/exit":
                break
            if prompt == "/clear":
                history.clear()
                print("Contexto limpiado.\n")
                continue
            if prompt == "/tools":
                print("\n".join(f"- {name}" for name in routes) + "\n")
                continue
            if prompt.startswith("/call "):
                try:
                    _, tool_name, raw = prompt.split(" ", 2)
                    server_name, original_name = routes[tool_name]
                    result = clients[server_name].request(
                        "tools/call", {"name": original_name, "arguments": json.loads(raw)}
                    )
                    print(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
                except Exception as exc:
                    print(f"Error: {exc}\n")
                continue
            history_size = len(history)
            try:
                text = run_gemini_turn(prompt, history, gemini, clients, api_tools, routes)
                print(f"Asistente: {text}\n")
            except Exception as exc:
                del history[history_size:]
                print(f"Error: {exc}\n")
    finally:
        for client in clients.values():
            client.close()


if __name__ == "__main__":
    main()
