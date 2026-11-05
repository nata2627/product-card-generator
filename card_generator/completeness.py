"""Deterministic part of the card: the spec table, expected fields and what to clarify.

Nothing here calls the model. The spec table is the input copied as is, so the model
never writes a technical value into it.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from card_generator.expected_fields import DEFAULT_PROFILE, FIELDS, PROFILES
from card_generator.schema import Product

NO_DATA = "данных нет"
# Below both thresholds the card would be prose without facts, so the model is not called.
MIN_SPECS = 3
MIN_DESCRIPTION_CHARS = 300

Status = Literal["specs", "description", "missing"]


@dataclass
class FieldCheck:
    key: str
    label: str
    status: Status
    spec_names: list[str] = field(default_factory=list)

    @property
    def value(self) -> str:
        if self.status == "specs":
            return "см. " + ", ".join(f"«{name}»" for name in self.spec_names)
        if self.status == "description":
            return "упомянуто только в описании"
        return NO_DATA


@dataclass
class Completeness:
    profile: str
    spec_rows: list[tuple[str, str]]
    fields: list[FieldCheck]
    clarify: list[str]
    enough_data: bool

    @property
    def missing(self) -> list[str]:
        return [f.label for f in self.fields if f.status == "missing"]


def analyze(product: Product) -> Completeness:
    profile, keys = detect_profile(product)
    description = _norm(product.description)
    fields = [_check(FIELDS[key], product.specs, description) for key in keys]

    clarify = []
    if not product.manufacturer:
        clarify.append("Производитель: данных нет.")
    if not product.product_type:
        clarify.append("Тип прибора: не указан, чек-лист полей подобран по названию.")
    if not product.description:
        clarify.append("Описание: данных нет.")
    for f in fields:
        if f.status == "missing":
            clarify.append(f"{f.label}: данных нет.")
        elif f.status == "description":
            clarify.append(
                f"{f.label}: есть только в описании, проверить и внести в характеристики."
            )
    if product.specs_scope == "series" and product.specs:
        clarify.append(
            "Характеристики указаны для серии. Уточнить значения для модификации "
            f"«{product.name}» перед публикацией."
        )

    enough = len(product.specs) >= MIN_SPECS or len(product.description) >= MIN_DESCRIPTION_CHARS
    return Completeness(
        profile=profile,
        spec_rows=list(product.specs.items()),
        fields=fields,
        clarify=clarify,
        enough_data=enough,
    )


def detect_profile(product: Product) -> tuple[str, list[str]]:
    for text in (product.product_type, product.name):
        norm = _norm(text)
        for name, pattern, keys in PROFILES:
            if norm and re.search(pattern, norm):
                return name, keys
    return DEFAULT_PROFILE


def _check(expected, specs: dict[str, str], description: str) -> FieldCheck:
    names = [
        name
        for name, value in specs.items()
        if re.search(expected.spec_name, _norm(name))
        or (expected.spec_value and re.search(expected.spec_value, _norm(value)))
    ]
    if names:
        return FieldCheck(expected.key, expected.label, "specs", names)
    if description and re.search(expected.description, description):
        return FieldCheck(expected.key, expected.label, "description")
    return FieldCheck(expected.key, expected.label, "missing")


def _norm(text: str) -> str:
    return text.lower().replace("ё", "е")
