"""Card as JSON for systems and as Markdown for a content manager."""

from card_generator.completeness import NO_DATA, FieldCheck
from card_generator.pipeline import (
    DESCRIPTION_MAX,
    DESCRIPTION_MIN,
    QUERIES_MAX,
    QUERIES_MIN,
    TITLE_MAX,
    Card,
)

STATUS_TEXT = {
    "ok": "проверки пройдены, нужна вычитка",
    "needs_review": "требует проверки, см. раздел «Требует проверки»",
    "not_enough_data": "недостаточно данных, текст не составлен",
}


def key_specs(card: Card) -> list[dict]:
    """Expected fields with values copied from the input, or the "no data" mark."""
    specs = card.product.specs
    return [
        {"field": f.label, "status": f.status, "value": _field_value(f, specs)}
        for f in card.completeness.fields
    ]


def to_dict(card: Card) -> dict:
    text = card.text
    return {
        "status": card.status,
        "product": {
            "name": card.product.name,
            "manufacturer": card.product.manufacturer or NO_DATA,
            "product_type": card.product.product_type or NO_DATA,
            "profile": card.completeness.profile,
        },
        "seo_title": text.seo_title if text else None,
        "description": text.description if text else None,
        "key_specs": key_specs(card),
        "specs": [{"name": n, "value": v} for n, v in card.completeness.spec_rows],
        "specs_scope": card.product.specs_scope,
        "search_queries": text.search_queries if text else [],
        "commercial": text.commercial if text else None,
        "clarify": card.completeness.clarify,
        "needs_review": card.flags,
        "input_warnings": card.input_warnings,
        "lengths": card.lengths,
        "meta": {
            "prompt_version": card.prompt_version,
            "model": card.attempts[-1].completion.model if card.attempts else None,
            "attempts": len(card.attempts),
            "first_attempt_problems": card.attempts[0].problems if card.attempts else [],
            "prompt_tokens": sum(a.completion.prompt_tokens for a in card.attempts),
            "completion_tokens": sum(a.completion.completion_tokens for a in card.attempts),
            "latency_s": round(sum(a.completion.latency_s for a in card.attempts), 2),
        },
    }


def to_markdown(card: Card) -> str:
    text = card.text
    lines = [f"# {card.product.name}", "", f"Статус: {STATUS_TEXT[card.status]}.", ""]
    if card.flags:
        lines += ["## Требует проверки", ""] + [f"- **{f}**" for f in card.flags] + [""]
    if text:
        n_title, n_desc = len(text.seo_title), len(text.description)
        lines += [
            f"## SEO-заголовок ({n_title} из {TITLE_MAX} символов)",
            "",
            text.seo_title,
            "",
            f"## Описание ({n_desc} символов, норма {DESCRIPTION_MIN}–{DESCRIPTION_MAX})",
            "",
            text.description,
            "",
        ]
    lines += ["## Ключевые характеристики", ""]
    if card.product.specs_scope == "series":
        lines += ["Значения во входе указаны для серии, а не для конкретной модификации.", ""]
    lines += ["| Характеристика | Значение |", "|---|---|"]
    for row in key_specs(card):
        value = row["value"]
        if row["status"] == "missing":
            value = f"**{value}**"
        lines.append(f"| {_cell(row['field'])} | {_cell(value)} |")
    lines.append("")
    if text:
        n_q = len(text.search_queries)
        lines += [f"## Поисковые запросы ({n_q}, норма {QUERIES_MIN}–{QUERIES_MAX})", ""]
        lines += [f"- {q}" for q in text.search_queries] + [""]
        lines += ["## Для менеджера: кому подходит и какие задачи решает", "", text.commercial, ""]
    if card.completeness.clarify:
        lines += ["## Уточнить у поставщика", ""] + [f"- {c}" for c in card.completeness.clarify]
        lines.append("")
    if card.input_warnings:
        lines += ["## Предупреждения по входным данным", ""]
        lines += [f"- {w}" for w in card.input_warnings] + [""]
    lines += ["## Все характеристики из входа", ""]
    if card.completeness.spec_rows:
        lines += ["| Характеристика | Значение |", "|---|---|"]
        lines += [f"| {_cell(n)} | {_cell(v)} |" for n, v in card.completeness.spec_rows]
    else:
        lines.append(NO_DATA)
    return "\n".join(lines).rstrip() + "\n"


def _field_value(check: FieldCheck, specs: dict[str, str]) -> str:
    if check.status != "specs":
        return check.value
    if len(check.spec_names) == 1:
        return specs[check.spec_names[0]]
    return "; ".join(f"{name}: {specs[name]}" for name in check.spec_names)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
