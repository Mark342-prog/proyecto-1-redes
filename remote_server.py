
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mcp_protocol import McpHandler, PROTOCOL_VERSION

HANDLER = McpHandler()
MAX_BODY_BYTES = 1_000_000  # límite defensivo (1 MB) contra Content-Length falso/excesivo


def _rpc_error(code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": message}}


class RemoteMcpHandler(BaseHTTPRequestHandler):
    server_version = "SimplePharmacyMCP/1.0"

    def _json(self, status: int, body: dict | None) -> None:
        encoded = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if body is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("MCP-Protocol-Version", PROTOCOL_VERSION)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        if encoded:
            self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "ok", "service": "simple-pharmacy-mcp"})
        else:
            self._json(405, {"error": "Use POST /mcp"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/mcp":
            self._json(404, {"error": "No encontrado"})
            return
        # Protección básica contra "DNS rebinding": solo se aceptan orígenes locales.
        origin = self.headers.get("Origin")
        if origin and not origin.startswith(("http://localhost", "http://127.0.0.1")):
            self._json(403, {"error": "Origen no permitido"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, _rpc_error(-32700, "Content-Length inválido"))
            return
        if not 0 <= length <= MAX_BODY_BYTES:
            self._json(413, _rpc_error(-32600, "Cuerpo demasiado grande"))
            return
        try:
            raw_body = self.rfile.read(length)
            payload = json.loads(raw_body) if raw_body else {}
            if not isinstance(payload, dict):
                self._json(400, _rpc_error(-32600, "Se esperaba un objeto JSON-RPC"))
                return
            response = HANDLER.handle(payload)
            self._json(202 if response is None else 200, response)  # 202 = notificación sin respuesta
        except (ValueError, json.JSONDecodeError):
            self._json(400, _rpc_error(-32700, "Error de parseo"))

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"HTTP {self.address_string()} {fmt % args}")


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), RemoteMcpHandler)
    print(f"Servidor MCP remoto: http://localhost:{port}/mcp")
    server.serve_forever()


if __name__ == "__main__":
    main()
