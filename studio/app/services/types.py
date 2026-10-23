"""Matriz canonica de tipos do Studio.

Ponto unico de verdade que liga:
  * o nome logico usado no construtor visual,
  * o tipo Python usado na anotacao da rota gerada,
  * o fragmento de schema OpenAPI,
  * o tipo nativo do SQL Server / SQLite lido na introspeccao.
"""

from __future__ import annotations

import datetime as _dt
import uuid as _uuid
from typing import Any, Literal

from pydantic import Field, create_model

TYPE_STRING = "string"
TYPE_INTEGER = "integer"
TYPE_NUMBER = "number"
TYPE_BOOLEAN = "boolean"
TYPE_DATE = "date"
TYPE_DATETIME = "datetime"
TYPE_UUID = "uuid"
TYPE_OBJECT = "object"
TYPE_ARRAY = "array"
TYPE_BINARY = "binary"
TYPE_TIME = "time"

SCALAR_TYPES = (
    TYPE_STRING,
    TYPE_INTEGER,
    TYPE_NUMBER,
    TYPE_BOOLEAN,
    TYPE_DATE,
    TYPE_DATETIME,
    TYPE_UUID,
    TYPE_BINARY,
    TYPE_TIME,
)
PARAMETER_TYPES = (*SCALAR_TYPES, TYPE_ARRAY)
ALL_TYPES = (*SCALAR_TYPES, TYPE_ARRAY, TYPE_OBJECT)

_PYTHON_TYPES: dict[str, Any] = {
    TYPE_STRING: str,
    TYPE_INTEGER: int,
    # `float` (e nao `Decimal`) de proposito: o Pydantic serializa `Decimal` como
    # *string* no JSON, o que contradiz o tipo logico "number" declarado no construtor
    # visual e o contrato OpenAPI. Com `float` a resposta sai como numero real.
    TYPE_NUMBER: float,
    TYPE_BOOLEAN: bool,
    TYPE_DATE: _dt.date,
    TYPE_DATETIME: _dt.datetime,
    TYPE_UUID: _uuid.UUID,
    TYPE_BINARY: str,  # base64
    TYPE_TIME: _dt.time,
    TYPE_OBJECT: dict[str, Any],
}

# Tipos que o FastAPI/OpenAPI representa de forma nao trivial: recebem schema explicito.
_JSON_SCHEMA: dict[str, dict[str, Any]] = {
    TYPE_NUMBER: {"type": "number", "format": "double"},
    TYPE_UUID: {"type": "string", "format": "uuid"},
    TYPE_DATE: {"type": "string", "format": "date"},
    TYPE_DATETIME: {"type": "string", "format": "date-time"},
    TYPE_TIME: {"type": "string", "format": "time"},
    TYPE_BINARY: {"type": "string", "format": "byte"},
}

# Mapa de tipos nativos -> tipo logico do Studio.
_NATIVE_TO_STUDIO: dict[str, str] = {
    # Inteiros
    "int": TYPE_INTEGER, "bigint": TYPE_INTEGER, "smallint": TYPE_INTEGER,
    "tinyint": TYPE_INTEGER, "integer": TYPE_INTEGER, "mediumint": TYPE_INTEGER,
    # Decimais
    "decimal": TYPE_NUMBER, "numeric": TYPE_NUMBER, "money": TYPE_NUMBER,
    "smallmoney": TYPE_NUMBER, "float": TYPE_NUMBER, "real": TYPE_NUMBER,
    "double": TYPE_NUMBER,
    # Booleanos
    "bit": TYPE_BOOLEAN, "bool": TYPE_BOOLEAN, "boolean": TYPE_BOOLEAN,
    # Datas
    "date": TYPE_DATE,
    "datetime": TYPE_DATETIME, "datetime2": TYPE_DATETIME, "smalldatetime": TYPE_DATETIME,
    "datetimeoffset": TYPE_DATETIME, "timestamp": TYPE_DATETIME,
    # Hora
    "time": TYPE_TIME,
    # Texto
    "char": TYPE_STRING, "nchar": TYPE_STRING, "varchar": TYPE_STRING,
    "nvarchar": TYPE_STRING, "text": TYPE_STRING, "ntext": TYPE_STRING,
    "xml": TYPE_STRING, "sysname": TYPE_STRING, "uniqueidentifier": TYPE_UUID,
    # Binarios
    "binary": TYPE_BINARY, "varbinary": TYPE_BINARY, "image": TYPE_BINARY, "blob": TYPE_BINARY,
}


class UnsupportedTypeError(ValueError):
    """Tipo logico desconhecido na matriz do Studio."""


def normalize_type(type_name: str | None) -> str:
    """Valida e normaliza o nome logico do tipo."""
    candidate = (type_name or TYPE_STRING).strip().lower()
    if candidate == "str":
        candidate = TYPE_STRING
    if candidate == "int":
        candidate = TYPE_INTEGER
    if candidate == "bool":
        candidate = TYPE_BOOLEAN
    if candidate not in ALL_TYPES:
        raise UnsupportedTypeError(
            f"tipo '{type_name}' nao suportado. Tipos validos: {', '.join(ALL_TYPES)}"
        )
    return candidate


def studio_type_from_native(native_type: str, *, max_length: int | None = None) -> str:
    """Converte um tipo nativo do banco alvo para o tipo logico do Studio."""
    key = (native_type or "").strip().lower()
    # Remove parametros: "nvarchar(100)" -> "nvarchar"
    if "(" in key:
        key = key.split("(", 1)[0]
    return _NATIVE_TO_STUDIO.get(key, TYPE_STRING)


def python_type_for(
    type_name: str,
    *,
    item_type: str | None = None,
    enum_values: list[Any] | None = None,
) -> Any:
    """Devolve o objeto de tipo Python usado na anotacao da rota gerada."""
    normalized = normalize_type(type_name)

    if enum_values:
        values = tuple(enum_values)
        if all(isinstance(value, str) for value in values):
            return Literal[values]  # type: ignore[valid-type]
        base = _PYTHON_TYPES[normalized]
        return Literal[values]  # type: ignore[valid-type]

    if normalized == TYPE_ARRAY:
        inner = python_type_for(item_type or TYPE_STRING)
        return list[inner]  # type: ignore[valid-type]

    return _PYTHON_TYPES[normalized]


def json_schema_for(type_name: str, *, item_type: str | None = None,
                    enum_values: list[Any] | None = None) -> dict[str, Any] | None:
    """Schema OpenAPI explicito, quando o tipo nao for trivial para o Pydantic."""
    normalized = normalize_type(type_name)
    if enum_values:
        return {"enum": list(enum_values)}
    if normalized == TYPE_ARRAY:
        inner = json_schema_for(item_type or TYPE_STRING) or {"type": "string"}
        return {"type": "array", "items": inner}
    if normalized == TYPE_OBJECT:
        return {"type": "object", "additionalProperties": True}
    return _JSON_SCHEMA.get(normalized)


def build_response_model(
    name: str,
    fields: list[dict[str, Any]],
    *,
    envelope: str = "object",
    extra_fields: list[dict[str, Any]] | None = None,
):
    """Cria dinamicamente o modelo Pydantic de resposta.

    ``fields`` e a lista de campos declarados no construtor visual. Cada item aceita:
    ``name``, ``type``, ``item_type``, ``description``, ``nullable``, ``enum``,
    ``alias`` e ``example``.

    ``envelope``:
      * ``object``  -> o modelo representa a linha;
      * ``list``    -> o modelo representa a linha e o envelope de lista e aplicado
        pelo FastAPI via ``list[Model]`` (responsabilidade do chamador);
      * ``paginated`` -> acrescenta ``items``/``total``/``page``/``page_size``.
    """
    definitions: dict[str, tuple[Any, Any]] = {}

    for spec in extra_fields or []:
        definitions[spec["name"]] = _field_for(spec)

    for spec in fields:
        definitions[spec["name"]] = _field_for(spec)

    if envelope == "paginated":
        item_model = create_model(f"{name}Item", **definitions)  # type: ignore[call-overload]
        return create_model(
            f"{name}Page",  # type: ignore[call-overload]
            items=(list[item_model], Field(default_factory=list)),  # type: ignore[valid-type]
            total=(int, Field(default=0, description="Itens devolvidos neste envelope.")),
            page=(int, Field(default=1)),
            page_size=(int, Field(default=0)),
            has_more=(
                bool,
                Field(
                    default=False,
                    description=(
                        "Verdadeiro quando o banco devolveu mais linhas do que o limite "
                        "configurado, indicando que ha proxima pagina."
                    ),
                ),
            ),
        )

    return create_model(name, **definitions)  # type: ignore[call-overload]


def _field_for(spec: dict[str, Any]) -> tuple[Any, Any]:
    """Monta ``(anotacao, default)`` para um campo do modelo dinamico."""
    type_name = spec.get("type", TYPE_STRING)
    annotation: Any = python_type_for(
        type_name,
        item_type=spec.get("item_type"),
        enum_values=spec.get("enum"),
    )
    if spec.get("nullable", True):
        annotation = annotation | None

    default = spec.get("default")
    description = spec.get("description") or None
    alias = spec.get("alias") or None
    example = spec.get("example")

    if spec.get("required"):
        return annotation, Field(..., description=description, alias=alias, examples=[example] if example else None)
    return annotation, Field(default=default, description=description, alias=alias,
                             examples=[example] if example else None)
