
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
        """Procesa una petición y devuelve la respuesta, o None si era una notificación."""
        if not isinstance(request, dict):
            # No hay "id" fiable que devolver si el mensaje ni siquiera es un objeto.
            return {
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32600, "message": "Petición inválida: se esperaba un objeto JSON"}
            }

        method = request.get("method")
        params = request.get("params") or {}
        request_id = request.get("id")

        if request_id is None:
            self._handle_notification(method, params)
            return None

        try:
            if not isinstance(method, str) or not method:
                raise McpError(-32600, "Petición inválida: falta 'method' o no es una cadena")
            if not isinstance(params, dict):
                raise McpError(-32602, "'params' debe ser un objeto JSON")
            result = self._dispatch(method, params)
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except McpError as exc:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": exc.code, "message": str(exc)}}
        except Exception as exc:  # noqa: BLE001 - cualquier fallo se traduce a error JSON-RPC
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}

    def _handle_notification(self, method: str | None, params: dict[str, Any]) -> None:
        if method == "notifications/initialized":
            self.initialized = True
        # Otras notificaciones (p. ej. notifications/cancelled) se ignoran de forma segura.

    def _dispatch(self, method: str | None, params: dict[str, Any]) -> Any:
        if method == "initialize":
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO
            }

        if method == "tools/list":
            return {"tools": self.service.tool_definitions()}

        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str) or not name:
                raise McpError(-32602, "Falta el nombre de la herramienta (name) o no es una cadena")
            try:
                result = self.service.call(name, arguments)
            except KeyError as exc:
                raise McpError(-32601, str(exc)) from exc
            except (ValueError, TypeError) as exc:

                return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
            return {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "structuredContent": result,
                "isError": False
            }

        if method == "ping":
            return {}

        raise McpError(-32601, f"Método no soportado: {method}")
