"""Prompt files, message assembly and parsing of the model's JSON reply."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template

from pydantic import BaseModel, ValidationError, field_validator

from card_generator.completeness import Completeness
from card_generator.schema import Product

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "prompts"
DEFAULT_PROMPT = "card_v2"
DATA_TAG = "product_data"


class ReplyFormatError(Exception):
    """The model answered, but not with the JSON object the prompt asked for."""


class CardText(BaseModel):
    seo_title: str
    description: str
    search_queries: list[str]
    commercial: str

    @field_validator("seo_title", "description", "commercial")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("пустое значение")
        return value

    @field_validator("search_queries")
    @classmethod
    def _strip_queries(cls, value: list[str]) -> list[str]:
        return [q.strip() for q in value if q.strip()]


@dataclass(frozen=True)
class Prompt:
    version: str
    system: str
    user: Template


def load_prompt(version: str = DEFAULT_PROMPT) -> Prompt:
    text = (PROMPTS_DIR / f"{version}.md").read_text(encoding="utf-8")
    parts = re.split(r"^## (system|user)\s*$", text, flags=re.MULTILINE)
    sections = dict(zip(parts[1::2], (p.strip() for p in parts[2::2]), strict=True))
    return Prompt(version, sections["system"], Template(sections["user"]))


def build_messages(prompt: Prompt, product: Product, report: Completeness) -> list[dict]:
    if product.specs_scope == "series":
        scope_note = (
            "Характеристики во входе относятся ко всей серии, а не только к этой модификации."
        )
    else:
        scope_note = "Характеристики во входе относятся к этой модели."
    user = prompt.user.substitute(
        product=render_product(product),
        scope_note=scope_note,
        missing=", ".join(report.missing) or "все ожидаемые поля есть",
    )
    return [{"role": "system", "content": prompt.system}, {"role": "user", "content": user}]


def render_product(product: Product) -> str:
    lines = [
        f"Название: {product.name}",
        f"Производитель: {product.manufacturer or 'данных нет'}",
        f"Тип прибора: {product.product_type or 'данных нет'}",
        "Характеристики:",
    ]
    lines += [f"- {name}: {value}" for name, value in product.specs.items()] or ["данных нет"]
    lines += ["Описание:", product.description or "данных нет"]
    # A closing tag inside the data would let injected text escape the data block.
    return re.sub(rf"</?\s*{DATA_TAG}\s*>", " ", "\n".join(lines), flags=re.IGNORECASE)


def parse_reply(text: str) -> CardText:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ReplyFormatError("в ответе нет JSON-объекта")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ReplyFormatError(f"JSON не разбирается: {exc.msg}") from None
    try:
        return CardText.model_validate(data)
    except ValidationError as exc:
        fields = ", ".join(str(err["loc"][0]) for err in exc.errors())
        raise ReplyFormatError(f"поля не по схеме: {fields}") from None
