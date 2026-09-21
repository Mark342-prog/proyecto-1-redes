
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PROTOCOL_VERSION = "2025-11-25"


def load_dotenv() -> None:
    """Carga un .env local simple, sin depender de una librería externa."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


class InteractionLog:

    def __init__(self) -> None:
        log_dir = ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        self.path = log_dir / f"mcp-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
        self._lock = threading.Lock()

    def write(self, server: str, direction: str, payload: dict[str, Any]) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "server": server, "direction": direction, "payload": payload
        }
        with self._lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        print(f"  [MCP {server} {direction}] {payload.get('method', 'response')}")


class McpClient:

    def __init__(self, name: str, config: dict[str, Any], log: InteractionLog) -> None:
        self.name, self.config, self.log = name, config, log
        self.next_id = 1
        self.process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._stderr_lines: list[str] = []
        # Cola alimentada por un hilo lector: permite un get(timeout=...) real,
        # a diferencia de un readline() bloqueante (funciona igual en Windows).
        self._stdout_queue: "queue.Queue[str | None]" = queue.Queue()
        self.timeout = float(config.get("timeout_seconds", 60))

    def start(self) -> None:
        if self.config["transport"] == "stdio":
            command = list(self.config["command"])
            # "npx"/"uvx" en Windows son shims (.cmd) que subprocess no localiza
            # sin shutil.which(); "python" se fija al intérprete actual.
            command[0] = sys.executable if command[0] == "python" else (shutil.which(command[0]) or command[0])
            env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")  # evita romper acentos en Windows
            try:
                self.process = subprocess.Popen(
                    command, cwd=ROOT, env=env, text=True, encoding="utf-8",
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
            except OSError as exc:
                raise RuntimeError(f"no se pudo lanzar el proceso para '{self.name}' ({command[0]}): {exc}") from exc
            threading.Thread(target=self._pump_stderr, daemon=True).start()
            threading.Thread(target=self._pump_stdout, daemon=True).start()
        self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "simple-pharmacy-chatbot", "version": "3.0.0"}
        })
        self.notify("notifications/initialized", {})

    def _pump_stderr(self) -> None:
        for line in self.process.stderr:  # type: ignore[union-attr]
            self._stderr_lines.append(line.rstrip())
            del self._stderr_lines[:-20]

    def _pump_stdout(self) -> None:
        for line in self.process.stdout:  # type: ignore[union-attr]
            self._stdout_queue.put(line)
        self._stdout_queue.put(None)  # señal de EOF para desbloquear lecturas pendientes

    def _closed_message(self) -> str:
        detail = " | ".join(self._stderr_lines[-3:])
        return f"el servidor {self.name} se cerró inesperadamente" + (f" — causa: {detail}" if detail else "")

    def _send_stdio(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        assert self.process and self.process.stdin
        if self.process.poll() is not None:
            raise RuntimeError(self._closed_message())
        try:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError(f"{self._closed_message()} (al escribir: {exc})") from exc
        if "id" not in payload:
            return None
        try:
            line = self._stdout_queue.get(timeout=self.timeout)
        except queue.Empty:
            raise RuntimeError(f"el servidor {self.name} no respondió en {self.timeout:.0f}s") from None
        if line is None:
            raise RuntimeError(self._closed_message())
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"el servidor {self.name} envió una respuesta que no es JSON válido: {exc}") from exc

    def _send_http(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        url = self.config.get("url") or os.getenv(self.config.get("url_env", ""), "")
        if not url:
            raise RuntimeError(f"falta la URL para {self.name} (revisa config.json / .env)")
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": PROTOCOL_VERSION
            }
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as result:
                raw = result.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"el servidor remoto {self.name} respondió con error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"no se pudo conectar con el servidor remoto {self.name}: {exc.reason}") from exc
        try:
            return json.loads(raw) if raw else None
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"el servidor {self.name} envió una respuesta que no es JSON válido: {exc}") from exc

    def _send(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        self.log.write(self.name, "request", payload)
        response = self._send_stdio(payload) if self.config["transport"] == "stdio" else self._send_http(payload)
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
    """Conserva el subconjunto de JSON Schema que aceptan las declaraciones de herramienta."""
    allowed = {"type", "description", "properties", "required", "items", "enum", "minimum", "maximum"}
    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in allowed:
            continue
        if key == "properties":
            result[key] = {n: simplify_schema(c) for n, c in value.items()}
        elif key == "items" and isinstance(value, dict):
            result[key] = simplify_schema(value)
        else:
            result[key] = value
    return result


_ID_HERRAMIENTA = re.compile(r"^[a-zA-Z0-9]{9}$")


def id_llamada_valido(bruto: Any) -> str:
    if isinstance(bruto, str) and _ID_HERRAMIENTA.match(bruto):
        return bruto
    return uuid.uuid4().hex[:9]


def normalizar_tool_calls(message: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:

    llamadas: list[tuple[str, str, dict[str, Any]]] = []
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        funcion = call.get("function") if isinstance(call.get("function"), dict) else call
        nombre = funcion.get("name")
        if not isinstance(nombre, str) or not nombre:
            continue
        argumentos = funcion.get("arguments")
        if isinstance(argumentos, str):
            try:
                argumentos = json.loads(argumentos or "{}")
            except json.JSONDecodeError:
                argumentos = {}
        llamadas.append((
            id_llamada_valido(call.get("id")),
            nombre,
            argumentos if isinstance(argumentos, dict) else {}
        ))
    return llamadas


class MistralApi:
    URL = "https://api.mistral.ai/v1/chat/completions"
    RETRYABLE_STATUS = {429, 500, 502, 503, 504}
    MAX_INTENTOS = 3
    SYSTEM_PROMPT = (
        "Eres un asistente breve de una farmacia educativa. Usa las herramientas disponibles para consultar "
        "el catálogo, las existencias o crear pedidos; no inventes datos de medicamentos. "
        "No diagnostiques ni recomiendes medicamentos con receta. Ante síntomas graves aconseja atención "
        "profesional urgente. Responde siempre en el idioma del usuario."
    )

    def __init__(self) -> None:
        self.api_key = os.getenv("MISTRAL_API_KEY", "")
        self.model = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

    def send(self, history: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        """Envía el historial y devuelve el mensaje del modelo (dict con 'content' y/o 'tool_calls')."""
        if not self.api_key or "replace" in self.api_key:
            raise RuntimeError("Configura MISTRAL_API_KEY en el archivo .env antes de conversar.")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": self.SYSTEM_PROMPT}] + history,
            "max_tokens": 700,
            "temperature": 0.2
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        for intento in range(1, self.MAX_INTENTOS + 1):
            request = urllib.request.Request(self.URL, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    return self._extraer_mensaje(json.loads(response.read()))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Mistral devolvió una respuesta que no es JSON válido: {exc}") from exc
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                error = RuntimeError(f"Error de la API de Mistral {exc.code}: {detail}")
                retryable = exc.code in self.RETRYABLE_STATUS
            except (urllib.error.URLError, TimeoutError) as exc:
                reason = getattr(exc, "reason", "tiempo de espera agotado")
                error, retryable = RuntimeError(f"No se pudo conectar con Mistral: {reason}"), True

            if not retryable or intento == self.MAX_INTENTOS:
                raise error
            time.sleep(2 ** (intento - 1))  # backoff: 1s, 2s, 4s...

    @staticmethod
    def _extraer_mensaje(data: Any) -> dict[str, Any]:
        """Obtiene choices[0].message y traduce los errores de la API a mensajes claros."""
        if not isinstance(data, dict):
            raise RuntimeError("Mistral devolvió una respuesta con formato inesperado")
        if isinstance(data.get("error"), dict):
            raise RuntimeError(f"Mistral rechazó la petición: {data['error'].get('message', data['error'])}")
        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise RuntimeError(f"Mistral no devolvió respuesta utilizable: {data}")
        message = choices[0].get("message")
        return message if isinstance(message, dict) else {"role": "assistant", "content": str(message or "")}


def safe_tool_name(server: str, tool: str) -> str:
    """Genera un nombre de función único y válido a partir de servidor + herramienta."""
    return re.sub(r"[^A-Za-z0-9_.:-]", "_", f"{server}__{tool}")[:128]


def _validar_config(config: Any) -> dict[str, Any]:
    """Valida la forma de config.json y da mensajes claros en vez de un KeyError críptico."""
    if not isinstance(config, dict) or not isinstance(config.get("servers"), dict):
        raise RuntimeError("config.json debe contener un objeto 'servers' con la lista de servidores MCP")
    for name, sc in config["servers"].items():
        if not isinstance(sc, dict):
            raise RuntimeError(f"config.json: la entrada '{name}' debe ser un objeto")
        transport = sc.get("transport")
        if transport not in ("stdio", "http"):
            raise RuntimeError(f"config.json: '{name}.transport' debe ser 'stdio' o 'http' (se recibió {transport!r})")
        if transport == "stdio":
            command = sc.get("command")
            if not isinstance(command, list) or not command or not all(isinstance(c, str) for c in command):
                raise RuntimeError(f"config.json: '{name}.command' debe ser una lista de cadenas no vacía")
        elif not sc.get("url") and not sc.get("url_env"):
            raise RuntimeError(f"config.json: '{name}' con transport 'http' necesita 'url' o 'url_env'")
    return config


def load_clients(log: InteractionLog) -> tuple[dict[str, McpClient], list[dict[str, Any]], dict[str, tuple[str, str]]]:
    """Lee config.json, arranca cada servidor MCP habilitado y arma la lista de herramientas del modelo."""
    config_path = ROOT / "config.json"
    try:
        config = _validar_config(json.loads(config_path.read_text(encoding="utf-8")))
    except FileNotFoundError as exc:
        raise RuntimeError(f"no se encontró {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{config_path} no es JSON válido: {exc}") from exc

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
                # Formato de herramienta estándar (estilo OpenAI), que es el
                # que acepta el endpoint /v1/chat/completions de Mistral.
                api_tools.append({
                    "type": "function",
                    "function": {
                        "name": exposed,
                        "description": f"[{name}] {tool.get('description', '')}",
                        "parameters": simplify_schema(tool["inputSchema"])
                    }
                })
        except Exception as exc:
            client.close()
            print(f"Aviso: no se pudo iniciar {name}: {exc}")
    return clients, api_tools, routes


def run_chat_turn(
    prompt: str, history: list[dict[str, Any]], api: MistralApi,
    clients: dict[str, McpClient], api_tools: list[dict[str, Any]], routes: dict[str, tuple[str, str]]
) -> str:
    """Envía un mensaje al modelo y resuelve, en bucle, las llamadas a herramientas MCP que pida."""
    history.append({"role": "user", "content": prompt})
    for _ in range(5):
        message = api.send(history, api_tools)
        calls = normalizar_tool_calls(message)
        texto = (message.get("content") or "").strip()

        if not calls:
            return texto or "El modelo respondió sin contenido de texto."

        # Se reconstruye el mensaje del asistente para que el modelo vea, en la
        # siguiente vuelta, qué herramientas pidió y con qué identificadores.
        history.append({
            "role": "assistant", "content": texto,
            "tool_calls": [
                {"id": cid, "type": "function",
                 "function": {"name": nombre, "arguments": json.dumps(args, ensure_ascii=False)}}
                for cid, nombre, args in calls
            ]
        })

        for call_id, nombre, argumentos in calls:
            if nombre not in routes:
                resultado: Any = {"isError": True, "message": f"Herramienta desconocida: {nombre}"}
            else:
                server_name, original_name = routes[nombre]
                try:
                    resultado = clients[server_name].request(
                        "tools/call", {"name": original_name, "arguments": argumentos}
                    )
                except Exception as exc:  # el error se le informa al modelo en vez de cortar la conversación
                    resultado = {"isError": True, "message": str(exc)}
            history.append({
                "role": "tool", "tool_call_id": call_id, "name": nombre,
                "content": json.dumps(resultado, ensure_ascii=False)
            })
    raise RuntimeError("El modelo alcanzó el límite de llamadas a herramientas para este mensaje.")


def _procesar_comando(prompt: str, history: list[dict[str, Any]], routes: dict, clients: dict) -> bool:
    """Maneja los comandos /clear, /tools y /call. Devuelve True si el prompt era un comando."""
    if prompt == "/clear":
        history.clear()
        print("Contexto limpiado.\n")
    elif prompt == "/tools":
        print("\n".join(f"- {name}" for name in routes) + "\n")
    elif prompt.startswith("/call "):
        try:
            _, tool_name, raw = prompt.split(" ", 2)
            server_name, original_name = routes[tool_name]
            result = clients[server_name].request("tools/call", {"name": original_name, "arguments": json.loads(raw)})
            print(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        except Exception as exc:
            print(f"Error: {exc}\n")
    else:
        return False
    return True


def main() -> None:
    load_dotenv()
    log = InteractionLog()
    clients, api_tools, routes = load_clients(log)
    if not clients:
        raise SystemExit("No se pudo iniciar ningún servidor MCP.")
    api = MistralApi()
    history: list[dict[str, Any]] = []
    print("\nChatbot de Farmacia Simple - Mistral AI")
    print(f"Modelo: {api.model}")
    print("Comandos: /tools, /call HERRAMIENTA {json}, /clear, /exit")
    print(f"Registro MCP: {log.path}\n")
    try:
        while True:
            prompt = input("Tú: ").strip()
            if not prompt:
                continue
            if prompt == "/exit":
                break
            if _procesar_comando(prompt, history, routes, clients):
                continue
            history_size = len(history)
            try:
                print(f"Asistente: {run_chat_turn(prompt, history, api, clients, api_tools, routes)}\n")
            except Exception as exc:
                del history[history_size:]
                print(f"Error: {exc}\n")
    finally:
        for client in clients.values():
            client.close()


if __name__ == "__main__":
    main()
