"""Input schema: parse raw JSON into a product, with Russian messages that name the field.

Errors stop the card (no name, wrong types). Warnings let it go on (an empty spec
was dropped, an unknown field was ignored, a long description was cut).
"""

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MAX_NAME_CHARS = 300
MAX_DESCRIPTION_CHARS = 6000
MAX_SPECS = 100
# A real product with the longest allowed description and 100 specs stays far below this.
MAX_INPUT_BYTES = 1_000_000


class InputError(Exception):
    def __init__(self, messages: list[str]):
        super().__init__("; ".join(messages))
        self.messages = messages


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    manufacturer: str = ""
    product_type: str = ""
    specs: dict[str, str] = Field(default_factory=dict)
    description: str = ""
    # "series": specs describe the whole product line, not this exact modification.
    specs_scope: Literal["model", "series"] = "model"
    source: dict[str, Any] = Field(default_factory=dict)

    @field_validator("manufacturer", "product_type", "description", mode="before")
    @classmethod
    def _null_to_empty(cls, value):
        return "" if value is None else value

    @field_validator("specs", mode="before")
    @classmethod
    def _null_specs_to_empty(cls, value):
        return {} if value is None else value


KNOWN_FIELDS = set(Product.model_fields)

FIELD_LABELS = {
    "name": "name (название)",
    "manufacturer": "manufacturer (производитель)",
    "product_type": "product_type (тип прибора)",
    "specs": "specs (характеристики)",
    "description": "description (описание)",
    "specs_scope": "specs_scope",
    "source": "source",
}


def parse_product(raw: str | bytes | Any) -> tuple[Product, list[str]]:
    """Return the product and warnings, or raise InputError with every problem found."""
    data = _load_json(raw) if isinstance(raw, str | bytes) else raw
    if not isinstance(data, dict):
        raise InputError([f"Ожидается JSON-объект с полями товара, получено: {_type_name(data)}."])
    if not data:
        raise InputError(["Пустой JSON-объект. Нужно хотя бы поле name (название)."])

    warnings: list[str] = []
    data = dict(data)
    for key in sorted(set(data) - KNOWN_FIELDS):
        warnings.append(f"Поле {key!r} не используется и пропущено.")
        del data[key]

    if isinstance(data.get("specs"), dict):
        data["specs"] = _clean_specs(data["specs"], warnings)

    description = data.get("description")
    if isinstance(description, str) and len(description.strip()) > MAX_DESCRIPTION_CHARS:
        data["description"] = _cut(description.strip(), MAX_DESCRIPTION_CHARS)
        warnings.append(
            f"Поле description (описание) длиннее {MAX_DESCRIPTION_CHARS} символов "
            f"({len(description.strip())}), использовано начало до {MAX_DESCRIPTION_CHARS}."
        )

    try:
        product = Product.model_validate(data)
    except ValidationError as exc:
        raise InputError([_ru_message(err) for err in exc.errors()]) from None
    return product, warnings


def _load_json(raw: str | bytes) -> Any:
    size = len(raw.encode("utf-8", "replace") if isinstance(raw, str) else raw)
    if size > MAX_INPUT_BYTES:
        raise InputError(
            [f"Вход слишком большой: {size} байт, допустимо до {MAX_INPUT_BYTES} байт."]
        )
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise InputError(["Вход не в кодировке UTF-8."]) from None
    if not raw.strip():
        raise InputError(["Пустой вход. Нужен JSON-объект с полями товара."])
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputError(
            [f"Некорректный JSON: {exc.msg} (строка {exc.lineno}, позиция {exc.colno})."]
        ) from None


def _clean_specs(specs: dict, warnings: list[str]) -> dict:
    """Drop empty values, stringify numbers, leave other wrong types for the schema to report."""
    cleaned = {}
    for key, value in specs.items():
        name = str(key).strip()
        if not name:
            warnings.append("В specs (характеристики) пропущена характеристика без названия.")
            continue
        if isinstance(value, bool):
            cleaned[name] = value
            continue
        if isinstance(value, int | float):
            value = str(value)
        if value is None or (isinstance(value, str) and not value.strip()):
            warnings.append(f"Характеристика {name!r} пустая и пропущена.")
            continue
        cleaned[name] = value
    if len(cleaned) > MAX_SPECS:
        raise InputError(
            [f"В specs (характеристики) {len(cleaned)} записей, допускается до {MAX_SPECS}."]
        )
    return cleaned


def _cut(text: str, limit: int) -> str:
    head = text[:limit]
    boundary = max(head.rfind(". "), head.rfind("\n"))
    return head[: boundary + 1].rstrip() if boundary > limit // 2 else head.rstrip()


def _ru_message(err: dict) -> str:
    loc = err["loc"]
    field = FIELD_LABELS.get(str(loc[0]), str(loc[0]))
    where = f"Характеристика {loc[1]!r}" if loc[0] == "specs" and len(loc) > 1 else f"Поле {field}"
    kind = err["type"]
    if kind == "missing":
        return f"{where}: обязательное поле отсутствует."
    if kind == "string_too_short":
        return f"{where}: пустое значение."
    if kind == "string_too_long":
        return f"{where}: длиннее {err['ctx']['max_length']} символов."
    if kind == "string_type":
        return f"{where}: ожидается строка, получено {_type_name(err['input'])}."
    if kind == "dict_type":
        got = _type_name(err["input"])
        return f"{where}: ожидается объект {{название: значение}}, получено {got}."
    if kind == "literal_error":
        return f"{where}: допустимые значения {err['ctx']['expected']}."
    return f"{where}: некорректное значение."


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    return {
        bool: "логическое значение",
        int: "число",
        float: "число",
        str: "строка",
        list: "список",
        dict: "объект",
    }.get(type(value), type(value).__name__)
