"""Núcleo del protocolo MCP (JSON-RPC 2.0) compartido por el servidor local y el remoto.

Este módulo NO conoce el transporte (stdio o HTTP): solo recibe un diccionario
JSON-RPC ya decodificado y devuelve otro diccionario. Así, pharmacy_server.py y remote_server.py únicamente se
encargan de leer/escribir bytes y delegan toda la lógica del protocolo aquí.
"""

from __future__ import annotations

import json
from typing import Any

from pharmacy_core import PharmacyService

PROTOCOL_VERSION = "2025-11-25"

SERVER_INFO = {"name": "simple-pharmacy-mcp", "version": "1.0.0"}


class McpError(Exception):
    """Error de protocolo con código JSON-RPC, para poder responder con {"error": ...}."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


class McpHandler:
    """Traduce peticiones JSON-RPC del protocolo MCP a llamadas del servicio de farmacia."""

    def __init__(self) -> None:
        self.service = PharmacyService()
        self.initialized = False

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Procesa una petición y devuelve la respuesta, o None si era una notificación."""
        method = request.get("method")
        params = request.get("params") or {}
        request_id = request.get("id")
        if request_id is None:
            self._handle_notification(method, params)
            return None

        try:
            result = self._dispatch(method, params)
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except McpError as exc:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": exc.code, "message": str(exc)}}
        except Exception as exc:  # noqa: BLE001 - cualquier fallo se traduce a error JSON-RPC
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}

    def _handle_notification(self, method: str | None, params: dict[str, Any]) -> None:
        if method == "notifications/initialized":
            self.initialized = True

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
            if not name:
                raise McpError(-32602, "Falta el nombre de la herramienta (name)")
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
