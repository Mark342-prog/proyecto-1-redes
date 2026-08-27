
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
    """Convierte y valida un argumento de texto; lanza ValueError con un mensaje claro si es inválido."""
    if valor is None:
        raise ValueError(f"falta el campo obligatorio '{campo}'")
    if not isinstance(valor, str):
        raise ValueError(f"'{campo}' debe ser una cadena de texto, se recibió {type(valor).__name__}")
    limpio = _CONTROL_CHARS.sub(" ", valor).strip()
    if len(limpio) < minimo:
        raise ValueError(f"'{campo}' debe contener al menos {minimo} caracteres")
    if len(limpio) > maximo:
        raise ValueError(f"'{campo}' no puede superar los {maximo} caracteres")
    return limpio


DATOS_POR_DEFECTO = {
    "medicines": [
        {
            "name": "Paracetamol 500 mg",
            "symptoms": ["fiebre", "dolor de cabeza", "dolor leve", "fever", "headache"],
            "price": 2.50,
            "stock": 30,
            "prescription_required": False,
            "warning": "No exceder la dosis indicada en el empaque. Evitar en caso de enfermedad hepática grave."
        },
        {
            "name": "Ibuprofeno 200 mg",
            "symptoms": ["inflamacion", "dolor leve", "dolor de cabeza", "inflammation"],
            "price": 3.25,
            "stock": 20,
            "prescription_required": False,
            "warning": "Evitar durante el embarazo, con úlceras estomacales, enfermedad renal o anticoagulantes."
        },
        {
            "name": "Loratadina 10 mg",
            "symptoms": ["alergia", "estornudos", "goteo nasal", "allergy"],
            "price": 4.00,
            "stock": 16,
            "prescription_required": False,
            "warning": "Consultar a un profesional antes de usar durante el embarazo o con enfermedad hepática."
        },
        {
            "name": "Sales de rehidratación oral",
            "symptoms": ["deshidratacion", "diarrea", "vomitos", "dehydration", "diarrhea"],
            "price": 1.75,
            "stock": 25,
            "prescription_required": False,
            "warning": "Buscar atención médica si hay sangre en las heces, deshidratación severa, vómitos "
                       "persistentes o síntomas en bebés."
        },
        {
            "name": "Amoxicilina 500 mg",
            "symptoms": ["infeccion bacteriana", "bacterial infection"],
            "price": 8.50,
            "stock": 12,
            "prescription_required": True,
            "warning": "Solo con receta médica. Los antibióticos no deben usarse sin evaluación profesional."
        }
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
            texto = self.data_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"no se pudo leer el archivo de datos ({self.data_path}): {exc}") from exc
        try:
            data = json.loads(texto)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"el archivo de datos ({self.data_path}) está corrupto o no es JSON válido: {exc}"
            ) from exc
        if not isinstance(data, dict) or "medicines" not in data or "orders" not in data:
            raise RuntimeError(
                f"el archivo de datos ({self.data_path}) no tiene la estructura esperada "
                "('medicines' y 'orders'); considera borrarlo para regenerarlo"
            )
        return data

    def _guardar(self, data: dict[str, Any]) -> None:
        try:
            self.data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"no se pudo escribir el archivo de datos ({self.data_path}): {exc}") from exc

    @staticmethod
    def tool_definitions() -> list[dict[str, Any]]:
        return [
            {
                "name": "list_medicines",
                "description": "Lista el catálogo de la farmacia con precios, existencias y si requieren receta.",
                "inputSchema": {"type": "object", "additionalProperties": False}
            },
            {
                "name": "find_by_symptom",
                "description": (
                    "Busca posibles productos de venta libre según un síntoma simple. "
                    "Esto NO es un diagnóstico médico."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symptom": {
                            "type": "string",
                            "minLength": 2,
                            "description": "Síntoma en texto libre, p. ej. 'dolor de cabeza'."
                        }
                    },
                    "required": ["symptom"],
                    "additionalProperties": False
                }
            },
            {
                "name": "check_stock",
                "description": "Consulta precio, existencias y advertencia de un medicamento por nombre.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "minLength": 2,
                            "description": "Nombre (o parte del nombre) del medicamento."
                        }
                    },
                    "required": ["name"],
                    "additionalProperties": False
                }
            },
            {
                "name": "create_order",
                "description": "Crea un pedido simulado de un medicamento sin receta y reduce el inventario.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "minLength": 2, "description": "Nombre del medicamento a pedir."},
                        "quantity": {
                            "type": "integer", "minimum": 1, "maximum": 10,
                            "description": "Cantidad de unidades (1 a 10)."
                        },
                        "customer_name": {"type": "string", "minLength": 2, "description": "Nombre del cliente."}
                    },
                    "required": ["name", "quantity", "customer_name"],
                    "additionalProperties": False
                }
            }
        ]

    @staticmethod
    def _buscar(medicines: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
        consulta = name.casefold().strip()
        return next((item for item in medicines if consulta in item["name"].casefold()), None)

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta una herramienta por nombre. Lanza ValueError/KeyError en caso de error de negocio."""
        if not isinstance(arguments, dict):
            raise ValueError(f"'arguments' debe ser un objeto JSON, se recibió {type(arguments).__name__}")

        with self._lock:
            data = self._cargar()
            medicines = data["medicines"]

            if name == "list_medicines":
                return {
                    "medicines": medicines,
                    "notice": "Información únicamente; consulte a un profesional de salud ante cualquier duda."
                }

            if name == "find_by_symptom":
                symptom = _validar_texto(arguments.get("symptom"), "symptom").casefold()
                matches = [
                    item for item in medicines
                    if not item["prescription_required"]
                    and any(symptom in known.casefold() or known.casefold() in symptom for known in item["symptoms"])
                ]
                return {
                    "matches": matches,
                    "notice": (
                        "Estas son coincidencias del catálogo, no un diagnóstico. "
                        "Busque atención urgente ante síntomas graves, dificultad para respirar, "
                        "dolor en el pecho, confusión o pérdida de conciencia."
                    )
                }

            if name == "check_stock":
                nombre = _validar_texto(arguments.get("name"), "name")
                item = self._buscar(medicines, nombre)
                if not item:
                    raise ValueError(f"medicamento no encontrado: '{nombre}'")
                return item

            if name == "create_order":
                nombre = _validar_texto(arguments.get("name"), "name")
                customer = _validar_texto(arguments.get("customer_name"), "customer_name")
                quantity = arguments.get("quantity")
                if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 10:
                    raise ValueError("'quantity' debe ser un entero de 1 a 10")

                item = self._buscar(medicines, nombre)
                if not item:
                    raise ValueError(f"medicamento no encontrado: '{nombre}'")
                if item["prescription_required"]:
                    raise ValueError("este medicamento requiere receta y no se puede pedir por este medio")
                if item["stock"] < quantity:
                    raise ValueError(f"existencias insuficientes; solo hay {item['stock']} disponibles")

                item["stock"] -= quantity
                order = {
                    "order_id": f"ORD-{uuid.uuid4().hex[:8].upper()}",
                    "customer_name": customer,
                    "medicine": item["name"],
                    "quantity": quantity,
                    "total": round(item["price"] * quantity, 2),
                    "status": "simulated"
                }
                data["orders"].append(order)
                self._guardar(data)
                return {"order": order, "warning": item["warning"]}

            raise KeyError(f"herramienta desconocida: {name}")
