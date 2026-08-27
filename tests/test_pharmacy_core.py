"""Pruebas unitarias de la lógica de negocio de la farmacia (pharmacy_core.py).

Cada prueba usa un archivo de datos temporal propio, para no interferir entre
sí ni con pharmacy_data.json del proyecto real.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pharmacy_core import PharmacyService  # noqa: E402


class BasePharmacyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        data_path = Path(self._tmp.name) / "datos_prueba.json"
        self.service = PharmacyService(data_path=data_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestListMedicines(BasePharmacyTest):
    def test_devuelve_catalogo_completo(self) -> None:
        result = self.service.call("list_medicines", {})
        self.assertIn("medicines", result)
        self.assertGreaterEqual(len(result["medicines"]), 1)
        self.assertIn("notice", result)


class TestFindBySymptom(BasePharmacyTest):
    def test_encuentra_por_sintoma_conocido(self) -> None:
        result = self.service.call("find_by_symptom", {"symptom": "dolor de cabeza"})
        nombres = [m["name"] for m in result["matches"]]
        self.assertIn("Paracetamol 500 mg", nombres)

    def test_no_incluye_medicamentos_con_receta(self) -> None:
        result = self.service.call("find_by_symptom", {"symptom": "infeccion bacteriana"})
        nombres = [m["name"] for m in result["matches"]]
        self.assertNotIn("Amoxicilina 500 mg", nombres)

    def test_sintoma_muy_corto_lanza_error(self) -> None:
        with self.assertRaises(ValueError):
            self.service.call("find_by_symptom", {"symptom": "a"})

    def test_falta_sintoma_lanza_error(self) -> None:
        with self.assertRaises(ValueError):
            self.service.call("find_by_symptom", {})

    def test_sintoma_no_texto_lanza_error(self) -> None:
        with self.assertRaises(ValueError):
            self.service.call("find_by_symptom", {"symptom": 123})

    def test_sintoma_sin_coincidencias(self) -> None:
        result = self.service.call("find_by_symptom", {"symptom": "xyzxyz"})
        self.assertEqual(result["matches"], [])


class TestCheckStock(BasePharmacyTest):
    def test_encuentra_medicamento_existente(self) -> None:
        item = self.service.call("check_stock", {"name": "Paracetamol"})
        self.assertEqual(item["name"], "Paracetamol 500 mg")
        self.assertIn("stock", item)
        self.assertIn("warning", item)

    def test_medicamento_inexistente_lanza_error(self) -> None:
        with self.assertRaises(ValueError):
            self.service.call("check_stock", {"name": "MedicamentoQueNoExiste"})

    def test_busqueda_insensible_a_mayusculas(self) -> None:
        item = self.service.call("check_stock", {"name": "paracetamol"})
        self.assertEqual(item["name"], "Paracetamol 500 mg")


class TestCreateOrder(BasePharmacyTest):
    def test_crea_pedido_y_descuenta_stock(self) -> None:
        antes = self.service.call("check_stock", {"name": "Paracetamol"})["stock"]
        result = self.service.call(
            "create_order", {"name": "Paracetamol", "quantity": 2, "customer_name": "Ana"}
        )
        despues = self.service.call("check_stock", {"name": "Paracetamol"})["stock"]
        self.assertEqual(despues, antes - 2)
        self.assertEqual(result["order"]["quantity"], 2)
        self.assertTrue(result["order"]["order_id"].startswith("ORD-"))
        self.assertAlmostEqual(result["order"]["total"], 2 * 2.50)

    def test_rechaza_medicamento_con_receta(self) -> None:
        with self.assertRaises(ValueError):
            self.service.call(
                "create_order", {"name": "Amoxicilina", "quantity": 1, "customer_name": "Ana"}
            )

    def test_rechaza_cantidad_fuera_de_rango(self) -> None:
        with self.assertRaises(ValueError):
            self.service.call(
                "create_order", {"name": "Paracetamol", "quantity": 0, "customer_name": "Ana"}
            )
        with self.assertRaises(ValueError):
            self.service.call(
                "create_order", {"name": "Paracetamol", "quantity": 11, "customer_name": "Ana"}
            )

    def test_rechaza_cantidad_no_entera(self) -> None:
        with self.assertRaises(ValueError):
            self.service.call(
                "create_order", {"name": "Paracetamol", "quantity": 1.5, "customer_name": "Ana"}
            )
        with self.assertRaises(ValueError):
            self.service.call(
                "create_order", {"name": "Paracetamol", "quantity": True, "customer_name": "Ana"}
            )

    def test_rechaza_stock_insuficiente(self) -> None:
        with self.assertRaises(ValueError):
            self.service.call(
                "create_order", {"name": "Paracetamol", "quantity": 999, "customer_name": "Ana"}
            )

    def test_rechaza_nombre_cliente_muy_corto(self) -> None:
        with self.assertRaises(ValueError):
            self.service.call(
                "create_order", {"name": "Paracetamol", "quantity": 1, "customer_name": "A"}
            )

    def test_rechaza_medicamento_inexistente(self) -> None:
        with self.assertRaises(ValueError):
            self.service.call(
                "create_order", {"name": "NoExiste", "quantity": 1, "customer_name": "Ana"}
            )

    def test_pedidos_persisten_entre_llamadas(self) -> None:
        self.service.call("create_order", {"name": "Paracetamol", "quantity": 1, "customer_name": "Ana"})
        # Nueva instancia apuntando al mismo archivo: debe ver el stock ya actualizado.
        otra_instancia = PharmacyService(data_path=self.service.data_path)
        item = otra_instancia.call("check_stock", {"name": "Paracetamol"})
        self.assertEqual(item["stock"], 29)


class TestValidacionGeneral(BasePharmacyTest):
    def test_herramienta_desconocida_lanza_key_error(self) -> None:
        with self.assertRaises(KeyError):
            self.service.call("herramienta_inexistente", {})

    def test_arguments_no_dict_lanza_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self.service.call("check_stock", ["no", "es", "un", "dict"])  # type: ignore[arg-type]

    def test_texto_demasiado_largo_lanza_error(self) -> None:
        with self.assertRaises(ValueError):
            self.service.call("check_stock", {"name": "x" * 500})

    def test_tool_definitions_tiene_las_cuatro_herramientas(self) -> None:
        nombres = {tool["name"] for tool in PharmacyService.tool_definitions()}
        self.assertEqual(nombres, {"list_medicines", "find_by_symptom", "check_stock", "create_order"})


if __name__ == "__main__":
    unittest.main()
