"""Servidor MCP local: JSON-RPC delimitado por líneas sobre stdin/stdout (transporte 'stdio').

El chatbot lo lanza como subproceso, escribe una petición JSON por línea en su
entrada estándar y lee la respuesta de la salida estándar.
"""

from __future__ import annotations

import json
import sys

from mcp_protocol import McpHandler


def main() -> None:
    handler = McpHandler()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = handler.handle(request)
        except json.JSONDecodeError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Error de parseo"}}
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
