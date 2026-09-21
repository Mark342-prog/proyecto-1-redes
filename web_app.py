
from __future__ import annotations

import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from chatbot import InteractionLog, MistralApi, load_clients, load_dotenv, run_chat_turn


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_BODY_BYTES = 1_000_000  # límite defensivo de tamaño de cuerpo (/api/chat y /api/reset)


class AppState:
    def __init__(self) -> None:
        load_dotenv()
        self.log = InteractionLog()
        self.clients, self.tools, self.routes = load_clients(self.log)
        if not self.clients:
            raise RuntimeError("No se pudo iniciar ningún servidor MCP")
        self.api = MistralApi()
        self.histories: dict[str, list[dict]] = {}
        self.lock = threading.Lock()

    def chat(self, session_id: str, message: str) -> str:
        with self.lock:
            history = self.histories.setdefault(session_id, [])
            previous_size = len(history)
            try:
                return run_chat_turn(message, history, self.api, self.clients, self.tools, self.routes)
            except Exception:
                del history[previous_size:]
                raise

    def reset(self, session_id: str) -> None:
        with self.lock:
            self.histories.pop(session_id, None)

    def close(self) -> None:
        for client in self.clients.values():
            client.close()


class WebHandler(BaseHTTPRequestHandler):
    state: AppState
    static_files = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/styles.css": ("styles.css", "text/css; charset=utf-8"),
        "/app.js": ("app.js", "text/javascript; charset=utf-8")
    }

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/health":
            self._json(200, {"status": "ok", "provider": "mistral",
                             "model": self.state.api.model, "mcpServers": list(self.state.clients)})
            return
        file_info = self.static_files.get(self.path)
        if not file_info:
            self._json(404, {"error": "No encontrado"})
            return
        filename, content_type = file_info
        self._send(200, (STATIC / filename).read_bytes(), content_type)

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "Content-Length inválido"})
            return
        if length < 0 or length > MAX_BODY_BYTES:
            self._json(413, {"error": "El cuerpo de la petición es demasiado grande"})
            return
        try:
            raw_body = self.rfile.read(length) or b"{}"
            data = json.loads(raw_body)
            if not isinstance(data, dict):
                self._json(400, {"error": "Se esperaba un objeto JSON"})
                return
            session_id = str(data.get("sessionId") or uuid.uuid4())[:100]
            if self.path == "/api/reset":
                self.state.reset(session_id)
                self._json(200, {"ok": True, "sessionId": session_id})
                return
            if self.path != "/api/chat":
                self._json(404, {"error": "No encontrado"})
                return
            message = str(data.get("message", "")).strip()
            if not 1 <= len(message) <= 1000:
                self._json(400, {"error": "El mensaje debe contener entre 1 y 1000 caracteres."})
                return
            answer = self.state.chat(session_id, message)
            self._json(200, {"answer": answer, "sessionId": session_id})
        except json.JSONDecodeError:
            self._json(400, {"error": "JSON inválido"})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"WEB {self.address_string()} {fmt % args}")


def main() -> None:
    state = AppState()
    WebHandler.state = state
    port = int(os.getenv("WEB_PORT", "8000"))
    host = os.getenv("WEB_HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), WebHandler)
    print(f"Frontend: http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        state.close()


if __name__ == "__main__":
    main()
