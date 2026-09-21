"""Pruebas unitarias de funciones auxiliares puras de chatbot.py.

No arrancan procesos ni llaman a la API: solo prueban lógica sin I/O
(simplify_schema, safe_tool_name, _validar_config, normalizar_tool_calls,
id_llamada_valido y la extracción de la respuesta de Mistral).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chatbot import (  # noqa: E402
    MistralApi, _validar_config, id_llamada_valido, normalizar_tool_calls, safe_tool_name, simplify_schema
)


class TestSimplifySchema(unittest.TestCase):
    def test_conserva_claves_permitidas(self) -> None:
        schema = {
            "type": "object", "description": "algo",
            "properties": {"x": {"type": "string", "minLength": 2}},
            "required": ["x"], "additionalProperties": False  # debe descartarse
        }
        result = simplify_schema(schema)
        self.assertNotIn("additionalProperties", result)
        self.assertEqual(result["type"], "object")
        self.assertEqual(result["required"], ["x"])

    def test_recursivo_en_properties_e_items(self) -> None:
        schema = {"type": "array", "items": {"type": "object", "properties": {"a": {"type": "string", "extra": 1}}}}
        self.assertNotIn("extra", simplify_schema(schema)["items"]["properties"]["a"])


class TestSafeToolName(unittest.TestCase):
    def test_combina_servidor_y_herramienta(self) -> None:
        self.assertEqual(safe_tool_name("farmacia_local", "list_medicines"), "farmacia_local__list_medicines")

    def test_reemplaza_caracteres_invalidos(self) -> None:
        self.assertRegex(safe_tool_name("sistema archivos!", "write file"), r"^[A-Za-z0-9_.:-]+$")

    def test_trunca_a_128_caracteres(self) -> None:
        self.assertLessEqual(len(safe_tool_name("s" * 200, "t" * 200)), 128)


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


class TestIdLlamadaValido(unittest.TestCase):
    """Mistral exige que tool_call_id sea exactamente 9 caracteres alfanuméricos."""

    def test_conserva_un_id_ya_valido(self) -> None:
        self.assertEqual(id_llamada_valido("abc123XYZ"), "abc123XYZ")

    def test_reemplaza_id_con_guion_bajo(self) -> None:
        generado = id_llamada_valido("call_abc")
        self.assertNotEqual(generado, "call_abc")
        self.assertRegex(generado, r"^[a-zA-Z0-9]{9}$")

    def test_reemplaza_id_de_longitud_incorrecta(self) -> None:
        self.assertRegex(id_llamada_valido("ab"), r"^[a-zA-Z0-9]{9}$")
        self.assertRegex(id_llamada_valido("a" * 20), r"^[a-zA-Z0-9]{9}$")

    def test_genera_id_cuando_falta(self) -> None:
        for valor in (None, "", 123, {}):
            self.assertRegex(id_llamada_valido(valor), r"^[a-zA-Z0-9]{9}$")


class TestNormalizarToolCalls(unittest.TestCase):
    def test_formato_estandar_con_argumentos_en_texto(self) -> None:
        message = {"tool_calls": [{
            "id": "abc123XYZ", "type": "function",
            "function": {"name": "check_stock", "arguments": '{"name": "Paracetamol"}'}
        }]}
        self.assertEqual(normalizar_tool_calls(message), [("abc123XYZ", "check_stock", {"name": "Paracetamol"})])

    def test_formato_con_campos_al_nivel_superior(self) -> None:
        message = {"tool_calls": [{"name": "check_stock", "arguments": {"name": "Ibuprofeno"}}]}
        (cid, nombre, args), = normalizar_tool_calls(message)
        self.assertRegex(cid, r"^[a-zA-Z0-9]{9}$")
        self.assertEqual((nombre, args), ("check_stock", {"name": "Ibuprofeno"}))

    def test_argumentos_json_invalido_se_convierten_en_dict_vacio(self) -> None:
        message = {"tool_calls": [{"function": {"name": "x", "arguments": "{no es json"}}]}
        (_, nombre, args), = normalizar_tool_calls(message)
        self.assertEqual((nombre, args), ("x", {}))

    def test_id_invalido_del_modelo_se_sustituye(self) -> None:
        message = {"tool_calls": [{"id": "call_0", "function": {"name": "x", "arguments": "{}"}}]}
        (cid, _, _), = normalizar_tool_calls(message)
        self.assertRegex(cid, r"^[a-zA-Z0-9]{9}$")

    def test_sin_tool_calls_devuelve_lista_vacia(self) -> None:
        self.assertEqual(normalizar_tool_calls({"content": "hola"}), [])

    def test_ignora_llamadas_sin_nombre_o_malformadas(self) -> None:
        message = {"tool_calls": [{"function": {"arguments": "{}"}}, "no soy un dict", {"name": "ok"}]}
        llamadas = normalizar_tool_calls(message)
        self.assertEqual(len(llamadas), 1)
        self.assertEqual(llamadas[0][1], "ok")

    def test_multiples_llamadas_conservan_orden_e_ids_validos(self) -> None:
        message = {"tool_calls": [
            {"id": "aaaaaaaaa", "function": {"name": "uno", "arguments": "{}"}},
            {"id": "bbbbbbbbb", "function": {"name": "dos", "arguments": '{"q": 1}'}}
        ]}
        self.assertEqual(
            normalizar_tool_calls(message),
            [("aaaaaaaaa", "uno", {}), ("bbbbbbbbb", "dos", {"q": 1})]
        )


class TestExtraerMensaje(unittest.TestCase):
    def test_respuesta_estandar(self) -> None:
        data = {"choices": [{"message": {"role": "assistant", "content": "hola"}}]}
        self.assertEqual(MistralApi._extraer_mensaje(data)["content"], "hola")

    def test_respuesta_con_tool_calls(self) -> None:
        data = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": []}}]}
        self.assertIn("tool_calls", MistralApi._extraer_mensaje(data))

    def test_error_de_la_api_lanza_runtime_error(self) -> None:
        with self.assertRaises(RuntimeError):
            MistralApi._extraer_mensaje({"error": {"message": "API key inválida"}})

    def test_sin_choices_lanza_runtime_error(self) -> None:
        with self.assertRaises(RuntimeError):
            MistralApi._extraer_mensaje({"choices": []})

    def test_respuesta_no_dict_lanza_runtime_error(self) -> None:
        with self.assertRaises(RuntimeError):
            MistralApi._extraer_mensaje("no soy un dict")


if __name__ == "__main__":
    unittest.main()
