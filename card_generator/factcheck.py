"""Fact check of the generated text against the input.

Every number, code, standard, interface, material, industry and promotional claim found
in the card must also be present in the input after normalisation. For series data a
sentence may not single out one value of a listed set unless it says it is about the
series. The check is lexical: it proves "this fragment occurs in the input", not that
the fragment is used in the right sense.
"""

import re
from dataclasses import dataclass

from card_generator.prompting import CardText
from card_generator.schema import Product

CHECKED_FIELDS = ("seo_title", "description", "search_queries", "commercial")

# Cyrillic letters that look Latin, so "РТ100" and "Pt100" or "М20х1,5" and "M20x1.5" compare
# equal. Applied to both sides, it cannot make an absent code look present.
_FOLD = str.maketrans(
    {
        "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k", "м": "m", "н": "h", "о": "o",
        "р": "p", "с": "c", "т": "t", "у": "y", "х": "x", "×": "x", "¼": "1/4", "½": "1/2",
        "¾": "3/4", "−": "-", "–": "-", "—": "-", " ": " ", ",": ".",
    }
)  # fmt: skip

_NUMBER = re.compile(r"(?<![\w])(?<!\d[.,])(\d{1,3}(?:[  ]\d{3})+|\d+(?:[.,]\d+)?)(?!\d)")
_TOKEN = re.compile(r"[\w/.,-]*\d[\w/.,-]*")
# A letter followed by a digit marks a code: "ДИ0,6-111-0,5", "Pt100", "M20x1,5", "IP65".
# "18об.%" or "2-х" are numbers with a glued unit and stay numbers.
_CODE_MARK = re.compile(r"[^\W\d_][-./]?\d")
_NAME_LIKE = re.compile(r"\d+[^\W\d_]{1,3}")
_STANDARD = re.compile(r"\b(гост(?:\s?р)?|ту|iso|din|en|iec)\s?\d[\d.\s-]*\d", re.IGNORECASE)
_UNIT = r"°\s?[cс]|%|мом|ком|ом|мпа|кпа|па|бар|мв|в|ма|а|квт|вт|гц|мм|см|м|кг|г|с|мин|ч|лет|бит/с"
_NUMBER_WITH_UNIT = re.compile(rf"{_NUMBER.pattern}\s?({_UNIT})?(?![а-яa-z])", re.IGNORECASE)

# Each pattern found in the card must also be found in the input.
VOCABULARY: dict[str, list[str]] = {
    "интерфейс": [
        r"modbus", r"\bhart\b", r"profibus", r"profinet", r"ethernet", r"canopen", r"ethercat",
        r"\bcan\b", r"\busb\b", r"bluetooth", r"wi-?fi", r"\bgsm\b", r"\blora", r"m-?bus",
        r"\bdcon\b", r"\brtu\b", r"\btcp\b", r"\bascii\b", r"токов\w* петл",
    ],
    "материал": [
        r"нержаве", r"\bстал[иьею]", r"латун", r"алюмини", r"пластик|пластмасс",
        r"полиамид", r"поликарбонат", r"полипропилен", r"бронз", r"\bмед(ь|ью|и\b|н)",
        r"титан", r"фторопласт", r"\bptfe\b", r"керамик", r"чугун", r"силикон", r"\baisi\b",
        r"платин", r"никел",
    ],
    "отрасль": [
        r"пищев", r"химическ", r"нефтехим", r"нефт", r"газов\w* (промышл|отрасл)", r"металлург",
        r"энергетик", r"\bжкх\b", r"водоканал", r"водоснабж|водоподготов", r"теплоснабж",
        r"теплов\w* пункт", r"котельн", r"фармацевт", r"медицин", r"строительств", r"агро",
        r"сельск\w* хозяйств", r"горнодобыв|горн\w* промышл|шахт", r"машиностро", r"судостро",
        r"авиац", r"атомн", r"целлюлоз", r"транспорт", r"лаборатор", r"металлообраб",
        r"деревообраб", r"текстильн", r"сварк|сварочн", r"вентиляц", r"кондиционир",
        r"холодильн", r"гидросистем|пневмосистем", r"автомобил",
    ],
    "непроверяемое утверждение": [
        r"\bлучш", r"\bсамы[йхем]", r"№\s?1\b|номер один", r"\bлидер", r"гаранти",
        r"в наличии|на складе", r"\bцен[аеуы]\b|руб\.|₽|скидк", r"доставк",
        r"срок\w* (поставк|изготовлени)", r"идеальн", r"уникальн", r"инновац",
        r"высококачествен", r"надежн", r"превосходн", r"безупречн", r"непревзойд",
    ],
}  # fmt: skip

SERIES_PICK = "одно значение из серии"
_LIST_GAP = re.compile(r"\s*(,|;|/|или|и)\s*")
SERIES_MARKERS = re.compile(
    r"сери[ияйюе]|исполнени|модификаци|на выбор|по заказу|в зависимости|вариант|доступн|"
    r"опционал|по данным для|выбор|выбира",
    re.IGNORECASE,
)

SERIES_AS_MODEL = "значение серии приписано модели"
# "резьба M20x1,5, предусмотренная в данной модели": a series value claimed for this exact
# product. Series markers in the same sentence do not excuse it.
THIS_MODEL = re.compile(
    r"\b(данн|эт|конкретн)\w*\s+(модел|модификаци|исполнени|версии)", re.IGNORECASE
)

INSTRUCTION = re.compile(
    r"игнорир|забудь|не учитывай|(предыдущ|прошл|все)\w* (инструкц|правил|указани)|"
    r"\bнапиши,? что\b|\bукажи,? что\b|ты (теперь|должен)|system prompt|ignore (all|previous)|"
    r"disregard",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Violation:
    field: str
    kind: str
    fragment: str

    def __str__(self) -> str:
        if self.kind == SERIES_AS_MODEL:
            return (
                f"{self.field}: значение из перечня для серии приписано этой модели "
                f"({self.fragment})"
            )
        if self.kind == SERIES_PICK:
            return (
                f"{self.field}: из перечня для серии выбрано одно значение без пометки "
                f"«в серии» ({self.fragment})"
            )
        return f"{self.field}: {self.kind} «{self.fragment}» нет во входных данных"


def strip_instructions(text: str) -> tuple[str, list[str]]:
    """Remove sentences that address the model, so they reach neither the prompt nor the facts."""
    kept, removed = [], []
    for sentence in _sentences(text):
        (removed if INSTRUCTION.search(sentence) else kept).append(sentence)
    return (" ".join(kept) if removed else text), removed


def check_facts(card: CardText, product: Product) -> list[Violation]:
    source = _input_text(product)
    folded_source = fold(source)
    compact_source = compact(source)
    source_numbers = _numbers(source)
    groups = _series_groups(product) if product.specs_scope == "series" else []

    violations: list[Violation] = []
    for field, text in _field_texts(card):
        found = []
        for raw, value in _numbers(text, raw=True):
            if value not in source_numbers:
                found.append(("число", raw))
        for m in _STANDARD.finditer(text):
            if compact(m.group(0)) not in compact_source:
                found.append(("стандарт", m.group(0)))
        for m in _TOKEN.finditer(text):
            code = m.group(0).strip("./,-")
            if _CODE_MARK.search(code) and compact(code) not in compact_source:
                kind = "код IP" if code.lower().startswith("ip") else "код или обозначение"
                found.append((kind, code))
        folded = fold(text)
        for kind, patterns in VOCABULARY.items():
            for pattern in patterns:
                folded_pattern = fold(pattern)
                hit = re.search(folded_pattern, folded)
                if hit and not re.search(folded_pattern, folded_source):
                    found.append((kind, _word_at(text, hit.start())))
        found += _series_picks(text, groups, [product.name, product.manufacturer or ""])
        for kind, fragment in dict.fromkeys(found):
            violations.append(Violation(field, kind, fragment))
    return violations


def fold(text: str) -> str:
    return text.lower().translate(_FOLD)


def compact(text: str) -> str:
    return re.sub(r"[^\w/.]", "", fold(text)).replace("_", "")


def _input_text(product: Product) -> str:
    parts = [product.name, product.manufacturer, product.product_type, product.description]
    parts += [f"{name}: {value}" for name, value in product.specs.items()]
    return "\n".join(parts)


def _field_texts(card: CardText):
    for field in CHECKED_FIELDS:
        value = getattr(card, field)
        if isinstance(value, list):
            for item in value:
                yield field, item
        else:
            yield field, value


def _numbers(text: str, raw: bool = False):
    """Standalone numbers; digits inside codes are not facts on their own."""
    # "260x240x120 мм" and "Ø50" are numbers, not codes.
    text = re.sub(r"(?<=\d)\s?[xх×]\s?(?=\d)", " x ", text)
    text = re.sub(r"(?<!\w)[ØøOО∅](?=\d{2})", " ", text)
    text = _TOKEN.sub(lambda m: " " if _CODE_MARK.search(m.group(0)) else m.group(0), text)
    found = [(m.group(1), _num(m.group(1))) for m in _NUMBER.finditer(_unfold_ranges(text))]
    return found if raw else {value for _, value in found}


def _unfold_ranges(text: str) -> str:
    # "0...1,6" and "4–20" are two numbers; make the separator a space so both are matched.
    return re.sub(r"(?<=\d)(\.{2,3}|…|[-–—])(?=[+\-−–]?\d)", " ", text)


def _num(raw: str) -> float:
    return round(float(re.sub(r"[  ]", "", raw).replace(",", ".")), 6)


def _word_at(text: str, start: int) -> str:
    m = re.match(r"[\w№₽.-]+", text[start:])
    return m.group(0).rstrip(".") if m else text[start : start + 10]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _signature(piece: str, shared_unit: str) -> frozenset:
    """Numbers with units in one alternative; text alternatives are kept as folded words."""
    pairs = {
        (_num(m.group(1)), fold(m.group(2) or shared_unit).replace(" ", ""))
        for m in _NUMBER_WITH_UNIT.finditer(_unfold_ranges(piece))
    }
    # Bare numbers ("2 – двухпроводная") match too much; such pieces compare as text.
    if pairs and all(unit for _, unit in pairs) and not _CODE_MARK.search(piece):
        return frozenset(pairs)
    # In 'опционально G1/2"' or "M20х1,5 по ГОСТ 2405-88" the code alone names the option.
    # A piece with its own label ("RS-485 Опционально: Ethernet") mixes a standard value
    # with options and stays whole.
    codes = [t.strip("./,-") for t in _TOKEN.findall(piece) if _CODE_MARK.search(t)]
    if codes and ":" not in piece:
        return frozenset({fold(codes[0])})
    return frozenset({fold(piece.strip(" .;,"))})


def _series_groups(product: Product) -> list[tuple[str, list[frozenset]]]:
    """Spec values that list alternatives: "50, 100, 1000 Ом" or "50М; 50П; Pt100".

    The page adapter also joins different columns with "; " ("3500 г; 260x240x120 мм"),
    so only uniform lists count: all pieces short and either all text or all with the
    same units.
    """
    groups = []
    for name, value in product.specs.items():
        pieces = [p.strip() for p in re.split(r";|,(?!\d)", value) if p.strip()]
        if len(pieces) < 2 or any(len(p) > 25 for p in pieces[1:]) or len(pieces[0]) > 40:
            continue
        last = _NUMBER_WITH_UNIT.findall(_unfold_ranges(pieces[-1]))
        shared_unit = last[-1][1] if last and last[-1][1] else ""
        signatures = [_signature(p, shared_unit) for p in pieces]
        if all(_NAME_LIKE.fullmatch(p) or _CODE_MARK.search(p) for p in pieces):
            # "50М; 50П; Pt100" is a list of names, even though "50М" reads like 50 metres.
            signatures = [
                frozenset({fold(p.strip(" .;,"))}) if _is_numeric(sig) else sig
                for p, sig in zip(pieces, signatures, strict=True)
            ]
        kinds = {frozenset(unit for _, unit in s) if _is_numeric(s) else "text" for s in signatures}
        if len(kinds) == 1 and len(set(signatures)) >= 2:
            groups.append((name, signatures))
    return groups


def _is_numeric(signature: frozenset) -> bool:
    return all(isinstance(item, tuple) for item in signature)


def _series_picks(text: str, groups, names: list[str]) -> list[tuple[str, str]]:
    picks = []
    for sentence in _sentences(text):
        claims_model = bool(THIS_MODEL.search(sentence))
        if SERIES_MARKERS.search(sentence) and not claims_model:
            continue
        # The product name may contain one of the values ("РТ100") and the maker may share
        # its name with a protocol ("ОВЕН"); a mention of either alone is not a pick.
        without_name = sentence
        for name in filter(None, names):
            without_name = re.sub(re.escape(name), " ", without_name, flags=re.IGNORECASE)
        folded = _dehyphen(fold(without_name))
        tokens = _unit_tokens(_unfold_ranges(without_name))
        for spec_name, signatures in groups:
            hits = [s for s in signatures if _matches(s, tokens, folded)]
            if hits and claims_model:
                picks.append((SERIES_AS_MODEL, f"{spec_name}: {sentence}"))
                break
            # Naming two or more values reads as a description of the range, not a pick.
            if len(hits) == 1:
                picks.append((SERIES_PICK, f"{spec_name}: {sentence}"))
                break
    return picks


def _unit_tokens(text: str) -> set[tuple[float, str]]:
    """Numbers with units; in "0,5 или 1,0 %" the unit is shared by the whole list."""
    tokens, pending, prev_end = set(), [], None
    for m in _NUMBER_WITH_UNIT.finditer(text):
        if prev_end is not None and not _LIST_GAP.fullmatch(text[prev_end : m.start()]):
            pending = []
        value, unit = _num(m.group(1)), fold(m.group(2) or "").replace(" ", "")
        tokens.add((value, unit))
        if unit:
            tokens |= {(v, unit) for v in pending}
            pending = []
        else:
            pending.append(value)
        prev_end = m.end()
    return tokens


def _matches(signature: frozenset, tokens: set, folded: str) -> bool:
    for item in signature:
        if isinstance(item, str):
            if not re.search(rf"(?<!\w){re.escape(_dehyphen(item))}(?!\w)", folded):
                return False
        elif item not in tokens:
            return False
    return True


def _dehyphen(text: str) -> str:
    """Treat "ModBus-RTU" and "Modbus RTU" as the same value."""
    return re.sub(r"(?<=\w)-(?=\w)", " ", text)
