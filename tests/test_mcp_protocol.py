"""Pruebas unitarias del núcleo de protocolo MCP (mcp_protocol.py), sin usar
ningún transporte real: se llama directamente a McpHandler.handle().
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pharmacy_core  # noqa: E402
from mcp_protocol import McpHandler, PROTOCOL_VERSION  # noqa: E402


class BaseMcpTest(unittest.TestCase):
    def setUp(self) -> None:
        # Cada prueba usa su propio archivo de datos, aislado de las demás.
        self._tmp = tempfile.TemporaryDirectory()
        self._data_path = Path(self._tmp.name) / "datos.json"
        self.handler = McpHandler()
        self.handler.service = pharmacy_core.PharmacyService(data_path=self._data_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestInitialize(BaseMcpTest):
    def test_initialize_devuelve_info_del_servidor(self) -> None:
        response = self.handler.handle({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {}}
        })
        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["protocolVersion"], PROTOCOL_VERSION)
        self.assertIn("serverInfo", response["result"])

    def test_notification_no_devuelve_respuesta(self) -> None:
        response = self.handler.handle({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        self.assertIsNone(response)
        self.assertTrue(self.handler.initialized)


class TestToolsList(BaseMcpTest):
    def test_tools_list_devuelve_cuatro_herramientas(self) -> None:
        response = self.handler.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        nombres = {tool["name"] for tool in response["result"]["tools"]}
        self.assertEqual(nombres, {"list_medicines", "find_by_symptom", "check_stock", "create_order"})


class TestToolsCall(BaseMcpTest):
    def test_llamada_exitosa_incluye_structured_content(self) -> None:
        response = self.handler.handle({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "list_medicines", "arguments": {}}
        })
        self.assertNotIn("error", response)
        self.assertFalse(response["result"]["isError"])
        self.assertIn("medicines", response["result"]["structuredContent"])

    def test_error_de_negocio_se_devuelve_como_isError_no_como_error_protocolo(self) -> None:
        response = self.handler.handle({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "check_stock", "arguments": {"name": "NoExiste"}}
        })
        self.assertNotIn("error", response)
        self.assertTrue(response["result"]["isError"])

    def test_herramienta_inexistente_da_error_de_protocolo(self) -> None:
        response = self.handler.handle({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "no_existe", "arguments": {}}
        })
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32601)

    def test_falta_name_da_error_de_protocolo(self) -> None:
        response = self.handler.handle({
            "jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"arguments": {}}
        })
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32602)

    def test_name_no_string_da_error_de_protocolo(self) -> None:
        response = self.handler.handle({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": 123, "arguments": {}}
        })
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32602)


class TestMetodosYFormatosInvalidos(BaseMcpTest):
    def test_metodo_desconocido(self) -> None:
        response = self.handler.handle({"jsonrpc": "2.0", "id": 8, "method": "metodo/rara", "params": {}})
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32601)

    def test_ping(self) -> None:
        response = self.handler.handle({"jsonrpc": "2.0", "id": 9, "method": "ping", "params": {}})
        self.assertEqual(response["result"], {})

    def test_params_no_dict_da_error(self) -> None:
        response = self.handler.handle({"jsonrpc": "2.0", "id": 10, "method": "tools/list", "params": ["no", "dict"]})
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32602)

    def test_request_no_dict_da_error_invalid_request(self) -> None:
        response = self.handler.handle(["no", "soy", "un", "objeto"])  # type: ignore[arg-type]
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32600)

    def test_falta_method_da_error(self) -> None:
        response = self.handler.handle({"jsonrpc": "2.0", "id": 11, "params": {}})
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32600)


if __name__ == "__main__":
    unittest.main()
