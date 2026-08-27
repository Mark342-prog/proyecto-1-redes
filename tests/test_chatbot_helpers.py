"""Pruebas unitarias de funciones auxiliares puras de chatbot.py.

No arrancan ningún proceso ni llaman a Gemini: solo prueban lógica que no
depende de I/O (simplify_schema, safe_tool_name, _validar_config).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chatbot import _validar_config, safe_tool_name, simplify_schema  # noqa: E402


class TestSimplifySchema(unittest.TestCase):
    def test_conserva_claves_permitidas(self) -> None:
        schema = {
            "type": "object",
            "description": "algo",
            "properties": {"x": {"type": "string", "minLength": 2}},
            "required": ["x"],
            "additionalProperties": False  # debe descartarse: no está en la lista permitida
        }
        result = simplify_schema(schema)
        self.assertNotIn("additionalProperties", result)
        self.assertEqual(result["type"], "object")
        self.assertEqual(result["required"], ["x"])

    def test_recursivo_en_properties_e_items(self) -> None:
        schema = {
            "type": "array",
            "items": {"type": "object", "properties": {"a": {"type": "string", "extraCampo": 1}}}
        }
        result = simplify_schema(schema)
        self.assertNotIn("extraCampo", result["items"]["properties"]["a"])


class TestSafeToolName(unittest.TestCase):
    def test_combina_servidor_y_herramienta(self) -> None:
        self.assertEqual(safe_tool_name("farmacia_local", "list_medicines"), "farmacia_local__list_medicines")

    def test_reemplaza_caracteres_invalidos(self) -> None:
        nombre = safe_tool_name("sistema archivos!", "write file")
        self.assertRegex(nombre, r"^[A-Za-z0-9_.:-]+$")

    def test_trunca_a_128_caracteres(self) -> None:
        nombre = safe_tool_name("s" * 200, "t" * 200)
        self.assertLessEqual(len(nombre), 128)


class TestValidarConfig(unittest.TestCase):
    def test_config_valida_no_lanza(self) -> None:
        config = {"servers": {"a": {"transport": "stdio", "command": ["python", "x.py"]}}}
        self.assertEqual(_validar_config(config), config)

    def test_falta_servers_lanza(self) -> None:
        with self.assertRaises(RuntimeError):
            _validar_config({})

    def test_transport_invalido_lanza(self) -> None:
        with self.assertRaises(RuntimeError):
            _validar_config({"servers": {"a": {"transport": "ftp"}}})

    def test_stdio_sin_command_lanza(self) -> None:
        with self.assertRaises(RuntimeError):
            _validar_config({"servers": {"a": {"transport": "stdio"}}})

    def test_http_sin_url_lanza(self) -> None:
        with self.assertRaises(RuntimeError):
            _validar_config({"servers": {"a": {"transport": "http"}}})

    def test_http_con_url_env_es_valido(self) -> None:
        config = {"servers": {"a": {"transport": "http", "url_env": "MI_URL"}}}
        self.assertEqual(_validar_config(config), config)


if __name__ == "__main__":
    unittest.main()
