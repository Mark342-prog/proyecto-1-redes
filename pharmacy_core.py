
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any

MAX_TEXT_LENGTH = 200  
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")  


def _validar_texto(valor: Any, campo: str, minimo: int = 2, maximo: int = MAX_TEXT_LENGTH) -> str:
    
    if valor is None:
        raise ValueError(f"falta el campo obligatorio '{campo}'")
    if not isinstance(valor, str):
        raise ValueError(f"'{campo}' debe ser una cadena de texto, se recibió {type(valor).__name__}")
    limpio = _CONTROL_CHARS.sub(" ", valor).strip()
    if not minimo <= len(limpio) <= maximo:
        raise ValueError(f"'{campo}' debe tener entre {minimo} y {maximo} caracteres")
    return limpio


def _medicina(name: str, symptoms: list[str], price: float, stock: int, prescription: bool, warning: str) -> dict:
    return {
        "name": name, "symptoms": symptoms, "price": price, "stock": stock,
        "prescription_required": prescription, "warning": warning
    }


DATOS_POR_DEFECTO = {
    "medicines": [
        _medicina("Paracetamol 500 mg", ["fiebre", "dolor de cabeza", "dolor leve", "fever", "headache"], 2.50, 30,
                  False, "No exceder la dosis indicada en el empaque. Evitar en caso de enfermedad hepática grave."),
        _medicina("Ibuprofeno 200 mg", ["inflamacion", "dolor leve", "dolor de cabeza", "inflammation"], 3.25, 20,
                  False, "Evitar durante el embarazo, con úlceras estomacales, enfermedad renal o anticoagulantes."),
        _medicina("Loratadina 10 mg", ["alergia", "estornudos", "goteo nasal", "allergy"], 4.00, 16,
                  False, "Consultar a un profesional antes de usar durante el embarazo o con enfermedad hepática."),
        _medicina("Sales de rehidratación oral", ["deshidratacion", "diarrea", "vomitos", "dehydration", "diarrhea"],
                  1.75, 25, False, "Buscar atención médica si hay sangre en las heces, deshidratación severa, "
                                   "vómitos persistentes o síntomas en bebés."),
        _medicina("Amoxicilina 500 mg", ["infeccion bacteriana", "bacterial infection"], 8.50, 12,
                  True, "Solo con receta médica. Los antibióticos no deben usarse sin evaluación profesional."),
    ],
    "orders": []
}


class PharmacyService:

    def __init__(self, data_path: str | Path | None = None) -> None:
        configurado = data_path or os.getenv("PHARMACY_DATA")
        self.data_path = Path(configurado) if configurado else Path(__file__).with_name("pharmacy_data.json")
        self._lock = threading.Lock()
        if not self.data_path.exists():
            self._guardar(DATOS_POR_DEFECTO)

    def _cargar(self) -> dict[str, Any]:
        try:
            data = json.loads(self.data_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise RuntimeError(f"no se pudo leer el archivo de datos ({self.data_path}): {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"el archivo de datos ({self.data_path}) está corrupto o no es JSON válido: {exc}") from exc
        if not isinstance(data, dict) or "medicines" not in data or "orders" not in data:
            raise RuntimeError(
                f"el archivo de datos ({self.data_path}) no tiene la estructura esperada; considera borrarlo"
            )
        return data

    def _guardar(self, data: dict[str, Any]) -> None:
        try:
            self.data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"no se pudo escribir el archivo de datos ({self.data_path}): {exc}") from exc

    @staticmethod
    def tool_definitions() -> list[dict[str, Any]]:
        texto = lambda desc, minimo=2: {"type": "string", "minLength": minimo, "description": desc}
        return [
            {
                "name": "list_medicines",
                "description": "Lista el catálogo de la farmacia con precios, existencias y si requieren receta.",
                "inputSchema": {"type": "object", "additionalProperties": False}
            },
            {
                "name": "find_by_symptom",
                "description": "Busca posibles productos de venta libre según un síntoma simple. "
                               "Esto NO es un diagnóstico médico.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"symptom": texto("Síntoma en texto libre, p. ej. 'dolor de cabeza'.")},
                    "required": ["symptom"], "additionalProperties": False
                }
            },
            {
                "name": "check_stock",
                "description": "Consulta precio, existencias y advertencia de un medicamento por nombre.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"name": texto("Nombre (o parte del nombre) del medicamento.")},
                    "required": ["name"], "additionalProperties": False
                }
            },
            {
                "name": "create_order",
                "description": "Crea un pedido simulado de un medicamento sin receta y reduce el inventario.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": texto("Nombre del medicamento a pedir."),
                        "quantity": {"type": "integer", "minimum": 1, "maximum": 10, "description": "Cantidad de unidades (1 a 10)."},
                        "customer_name": texto("Nombre del cliente.")
                    },
                    "required": ["name", "quantity", "customer_name"], "additionalProperties": False
                }
            }
        ]

    @staticmethod
    def _buscar(medicines: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
        consulta = name.casefold()
        return next((item for item in medicines if consulta in item["name"].casefold()), None)

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise ValueError(f"'arguments' debe ser un objeto JSON, se recibió {type(arguments).__name__}")
        with self._lock:
            data = self._cargar()
            metodo = getattr(self, f"_tool_{name}", None)
            if metodo is None:
                raise KeyError(f"herramienta desconocida: {name}")
            return metodo(data, arguments)

    @staticmethod
    def _tool_list_medicines(data: dict, _args: dict) -> dict:
        return {
            "medicines": data["medicines"],
            "notice": "Información únicamente; consulte a un profesional de salud ante cualquier duda."
        }

    def _tool_find_by_symptom(self, data: dict, args: dict) -> dict:
        symptom = _validar_texto(args.get("symptom"), "symptom").casefold()
        matches = [
            item for item in data["medicines"]
            if not item["prescription_required"]
            and any(symptom in s.casefold() or s.casefold() in symptom for s in item["symptoms"])
        ]
        return {
            "matches": matches,
            "notice": "Estas son coincidencias del catálogo, no un diagnóstico. Busque atención urgente ante "
                      "síntomas graves, dificultad para respirar, dolor en el pecho, confusión o pérdida de conciencia."
        }

    def _tool_check_stock(self, data: dict, args: dict) -> dict:
        nombre = _validar_texto(args.get("name"), "name")
        item = self._buscar(data["medicines"], nombre)
        if not item:
            raise ValueError(f"medicamento no encontrado: '{nombre}'")
        return item

    def _tool_create_order(self, data: dict, args: dict) -> dict:
        nombre = _validar_texto(args.get("name"), "name")
        customer = _validar_texto(args.get("customer_name"), "customer_name")
        quantity = args.get("quantity")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 10:
            raise ValueError("'quantity' debe ser un entero de 1 a 10")

        item = self._buscar(data["medicines"], nombre)
        if not item:
            raise ValueError(f"medicamento no encontrado: '{nombre}'")
        if item["prescription_required"]:
            raise ValueError("este medicamento requiere receta y no se puede pedir por este medio")
        if item["stock"] < quantity:
            raise ValueError(f"existencias insuficientes; solo hay {item['stock']} disponibles")

        item["stock"] -= quantity
        order = {
            "order_id": f"ORD-{uuid.uuid4().hex[:8].upper()}", "customer_name": customer, "medicine": item["name"],
            "quantity": quantity, "total": round(item["price"] * quantity, 2), "status": "simulated"
        }
        data["orders"].append(order)
        self._guardar(data)
        return {"order": order, "warning": item["warning"]}
