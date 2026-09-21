
from __future__ import annotations

import json
from typing import Any

from pharmacy_core import PharmacyService

PROTOCOL_VERSION = "2025-11-25"
SERVER_INFO = {"name": "simple-pharmacy-mcp", "version": "1.0.0"}


class McpError(Exception):

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


class McpHandler:
    def __init__(self) -> None:
        self.service = PharmacyService()
        self.initialized = False

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(request, dict):
            return {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32600, "message": "Petición inválida: se esperaba un objeto JSON"}}

        method, params, request_id = request.get("method"), request.get("params") or {}, request.get("id")
        if request_id is None:  # notificación: sin "id", sin respuesta (p. ej. notifications/initialized)
            if method == "notifications/initialized":
                self.initialized = True
            return None

        try:
            if not isinstance(method, str) or not method:
                raise McpError(-32600, "Petición inválida: falta 'method' o no es una cadena")
            if not isinstance(params, dict):
                raise McpError(-32602, "'params' debe ser un objeto JSON")
            return {"jsonrpc": "2.0", "id": request_id, "result": self._dispatch(method, params)}
        except McpError as exc:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": exc.code, "message": str(exc)}}
        except Exception as exc:  # noqa: BLE001 - cualquier fallo se traduce a error JSON-RPC
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}

    def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        if method == "initialize":
            return {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}},
                     "serverInfo": SERVER_INFO}
        if method == "tools/list":
            return {"tools": self.service.tool_definitions()}
        if method == "tools/call":
            return self._call_tool(params)
        if method == "ping":
            return {}
        raise McpError(-32601, f"Método no soportado: {method}")

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise McpError(-32602, "Falta el nombre de la herramienta (name) o no es una cadena")
        try:
            result = self.service.call(name, params.get("arguments") or {})
        except KeyError as exc:
            raise McpError(-32601, str(exc)) from exc
        except (ValueError, TypeError) as exc:
            # Error de negocio (stock insuficiente, receta requerida, etc.): se
            # devuelve como resultado con isError=True, no como error de protocolo.
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "structuredContent": result, "isError": False
        }
