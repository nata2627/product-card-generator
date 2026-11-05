"""From raw input to a checked card: validate, analyse, generate, check, retry once, fit the
description length in a separate call, flag what is left."""

from dataclasses import dataclass, field
from typing import Literal

from card_generator.completeness import Completeness, analyze
from card_generator.factcheck import check_facts, strip_instructions
from card_generator.llm import LLM, Completion, LLMError
from card_generator.prompting import (
    CardText,
    Prompt,
    ReplyFormatError,
    build_length_messages,
    build_messages,
    load_prompt,
    parse_plain_reply,
    parse_reply,
)
from card_generator.schema import Product, parse_product

TITLE_MAX = 70
DESCRIPTION_MIN, DESCRIPTION_MAX = 800, 1200
QUERIES_MIN, QUERIES_MAX = 3, 5
MAX_ATTEMPTS = 2
LENGTH_PROMPT = "length_v1"
MAX_LENGTH_CALLS = 2

Status = Literal["ok", "needs_review", "not_enough_data"]


@dataclass
class Attempt:
    completion: Completion
    text: CardText | None = None
    facts: list[str] = field(default_factory=list)
    lengths: list[str] = field(default_factory=list)
    format_error: str | None = None

    @property
    def problems(self) -> list[str]:
        head = [self.format_error] if self.format_error else []
        return head + self.facts + self.lengths


@dataclass
class Card:
    product: Product
    completeness: Completeness
    prompt_version: str
    input_warnings: list[str] = field(default_factory=list)
    text: CardText | None = None
    # Problems left after the retry; each one needs a human look before publishing.
    flags: list[str] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    # The attempt the card text comes from: a retry can come back worse than the first answer.
    used_attempt: Attempt | None = None
    # Separate calls that only resize the description, and the fact problems of the final text.
    length_attempts: list[Attempt] = field(default_factory=list)
    final_facts: list[str] = field(default_factory=list)

    @property
    def calls(self) -> list[Attempt]:
        return self.attempts + self.length_attempts

    @property
    def status(self) -> Status:
        if self.text is None:
            return "not_enough_data"
        return "needs_review" if self.flags else "ok"

    @property
    def lengths(self) -> dict[str, int]:
        if self.text is None:
            return {}
        return {
            "seo_title": len(self.text.seo_title),
            "description": len(self.text.description),
            "search_queries": len(self.text.search_queries),
        }


def make_card(raw, llm: LLM, prompt: Prompt | None = None, draft_anyway: bool = False) -> Card:
    """Raise InputError for bad input and LLMError when the model cannot be used."""
    prompt = prompt or load_prompt()
    product, warnings = parse_product(raw)
    clean, removed = strip_instructions(product.description)
    if removed:
        product = product.model_copy(update={"description": clean})
        warnings.append(
            "Из описания исключены предложения, похожие на команды для модели: "
            + " ".join(f"«{s}»" for s in removed)
        )
    report = analyze(product)
    card = Card(product, report, prompt.version, warnings)
    if not report.enough_data and not draft_anyway:
        return card

    messages = build_messages(prompt, product, report)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        completion = llm.complete(messages)
        try:
            text = parse_reply(completion.text)
            current = Attempt(
                completion, text, [str(v) for v in check_facts(text, product)], check_lengths(text)
            )
        except ReplyFormatError as exc:
            current = Attempt(completion, format_error=f"Ответ не по формату: {exc}.")
        card.attempts.append(current)
        if not current.problems:
            break
        if attempt < MAX_ATTEMPTS:
            messages = messages + [
                {"role": "assistant", "content": completion.text},
                {"role": "user", "content": retry_request(current.problems)},
            ]
    answered = [a for a in card.attempts if a.text is not None]
    if not answered:
        raise LLMError(f"Модель {MAX_ATTEMPTS} раза ответила не по формату карточки.")

    # Fewer fact problems first, then fewer length problems; on a tie the later answer wins.
    best = min(reversed(answered), key=lambda a: (len(a.facts), len(a.lengths)))
    card.used_attempt = best
    text, facts = best.text, best.facts
    if not DESCRIPTION_MIN <= len(text.description) <= DESCRIPTION_MAX:
        text, facts = fit_description(card, llm, text, facts)
    card.final_facts = facts
    card.text, card.flags = enforce_limits(text, facts + check_lengths(text))
    return card


def fit_description(card: Card, llm: LLM, text: CardText, facts: list[str]):
    """Resize the description alone and check its facts again.

    A full retry trades length against facts; a call that only rewrites one field to a
    given size keeps the rest of the card as it is. The new text is taken only if it fits
    and brings no fact problem the current text did not have; otherwise the second call
    gets the exact problems, as in the main retry.
    """
    prompt = load_prompt(LENGTH_PROMPT)
    messages = build_length_messages(
        prompt, card.product, text.description, DESCRIPTION_MIN, DESCRIPTION_MAX
    )
    for _ in range(MAX_LENGTH_CALLS):
        completion = llm.complete(messages)
        description = parse_plain_reply(completion.text)
        if not description:
            card.length_attempts.append(Attempt(completion, format_error="Пустой ответ."))
            continue
        candidate = text.model_copy(update={"description": description})
        found = [str(v) for v in check_facts(candidate, card.product)]
        lengths = check_lengths(candidate)
        card.length_attempts.append(Attempt(completion, candidate, found, lengths))
        new_facts = [f for f in found if f not in facts]
        if not new_facts and not lengths:
            return candidate, found
        messages = messages + [
            {"role": "assistant", "content": completion.text},
            {"role": "user", "content": length_retry_request(new_facts + lengths)},
        ]
    # No call hit the range: keep the text that came out of the fact check.
    return text, facts


def check_lengths(text: CardText) -> list[str]:
    problems = []
    if len(text.seo_title) > TITLE_MAX:
        problems.append(
            f"seo_title: получилось {len(text.seo_title)} символов, нужно не больше {TITLE_MAX}"
        )
    if not DESCRIPTION_MIN <= len(text.description) <= DESCRIPTION_MAX:
        problems.append(
            f"description: получилось {len(text.description)} символов, "
            f"нужно {DESCRIPTION_MIN}–{DESCRIPTION_MAX}"
        )
    if not QUERIES_MIN <= len(text.search_queries) <= QUERIES_MAX:
        problems.append(
            f"search_queries: получилось {len(text.search_queries)}, "
            f"нужно {QUERIES_MIN}–{QUERIES_MAX}"
        )
    return problems


def retry_request(problems: list[str]) -> str:
    lines = "\n".join(f"- {p}" for p in problems)
    return (
        f"В черновике найдены проблемы:\n{lines}\n\n"
        "Исправь только эти места. Значение, которого нет во входных данных, убери, "
        "а не заменяй другим. Значение из перечня для серии подай как вариант серии. "
        "Ответь тем же JSON-объектом целиком."
    )


def length_retry_request(problems: list[str]) -> str:
    lines = "\n".join(f"- {p}" for p in problems)
    return (
        f"В новом тексте найдены проблемы:\n{lines}\n\n"
        "Исправь их и ответь всем описанием целиком, только текстом."
    )


def enforce_limits(text: CardText, problems: list[str]) -> tuple[CardText, list[str]]:
    """Fix what can be fixed without the model; everything else becomes a flag."""
    flags = list(problems)
    if len(text.seo_title) > TITLE_MAX:
        cut = text.seo_title[: TITLE_MAX + 1].rsplit(" ", 1)[0].rstrip(" ,.-–")
        text = text.model_copy(update={"seo_title": cut[:TITLE_MAX]})
        flags = [f for f in flags if not f.startswith("seo_title: получилось")]
        flags.append(f"seo_title: обрезан до {len(text.seo_title)} символов по границе слова")
    if len(text.search_queries) > QUERIES_MAX:
        text = text.model_copy(update={"search_queries": text.search_queries[:QUERIES_MAX]})
        flags = [f for f in flags if not f.startswith("search_queries: получилось")]
    return text, flags
