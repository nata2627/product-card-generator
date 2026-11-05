"""Which fields a card for a given instrument type is expected to have.

Deliberately small: seven common fields and a handful of profiles picked by keywords
in the product type or name. Anything unrecognised gets all seven fields.
Patterns run on lowercased text with "ё" replaced by "е".
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExpectedField:
    key: str
    label: str
    # Matched against spec names.
    spec_name: str
    # Matched against the description; a hit there is reported as "only in description".
    description: str
    # Matched against spec values, only where a value is unambiguous on its own (IP codes).
    spec_value: str = ""


FIELDS = {
    f.key: f
    for f in [
        ExpectedField(
            "range",
            "Диапазон измерений",
            # Gas formulas as spec names hold measuring ranges in gas analyser tables.
            r"диапазон (измер|показ)|предел\w* измер|верхний предел|\bвпи\b|"
            r"^(o2|co2?|h2s|ch4|nh3|no2?|so2|cl2)\b",
            r"диапазон\w* измер|предел\w* измер|верхний предел",
            spec_value=r"диапазон (измер|показ)",
        ),
        ExpectedField(
            "accuracy",
            "Класс точности или погрешность",
            r"класс\w* (точност|допуск)|погрешност|воспроизводимост",
            r"класс\w* точност|погрешност",
        ),
        ExpectedField(
            "power",
            "Питание",
            r"питани|питающ|входное напряжение",
            r"напряжени\w* питани|питани\w* от",
        ),
        ExpectedField(
            "output",
            "Выходной сигнал или интерфейс",
            r"выходн\w* (сигнал|ток|напряжен|элемент)|интерфейс|протокол|"
            r"номинальная статическая|импульсный выход|контакт",
            r"выходн\w* сигнал|интерфейс|rs-?485|modbus|4\s*(\.\.\.|…|-|–)\s*20\s*ма",
        ),
        ExpectedField(
            "connection",
            "Присоединение или монтаж",
            r"присоединени|резьб|штуцер|монтаж|крепление|исполнение корпуса",
            r"присоединени|резьб|штуцер|монтаж",
        ),
        ExpectedField(
            "protection",
            "Степень защиты IP",
            r"степень защиты",
            r"\bip\s?-?\d{2}\b",
            spec_value=r"\bip\s?-?\d{2}\b",
        ),
        ExpectedField(
            "temperature",
            "Рабочая температура",
            r"рабоч\w* (диапазон )?температур|температур\w* окружающ|условия эксплуатации",
            r"температур\w* окружающ|рабоч\w* температур",
        ),
    ]
}

ALL = list(FIELDS)

# Order matters: the first profile whose pattern matches wins.
# Each profile lists field keys; a mechanical gauge has no power or output, for example.
PROFILES: list[tuple[str, str, list[str]]] = [
    (
        "частотный преобразователь",
        r"преобразователь частоты|частотн",
        "power output protection temperature".split(),
    ),
    (
        "блок питания",
        r"блок\w* питания",
        "power output connection protection temperature".split(),
    ),
    (
        "модуль ввода-вывода",
        r"модул\w* (ввода|вывода)",
        "power output connection protection temperature".split(),
    ),
    (
        "регулятор или контроллер",
        r"регулятор|контроллер",
        "accuracy power output connection protection temperature".split(),
    ),
    (
        "датчик температуры",
        r"термопреобразовател|термоэлектрическ|термопар|термосопротивл|датчик\w* температуры",
        "range accuracy output connection protection temperature".split(),
    ),
    (
        "портативный измеритель",
        r"мультиметр|клещи|тестер",
        "range accuracy power protection temperature".split(),
    ),
    (
        "газоанализатор",
        r"газоанализатор|сигнализатор газ",
        "range accuracy power output protection temperature".split(),
    ),
    (
        "счетчик или расходомер",
        r"счетчик|расходомер",
        "range accuracy output connection protection temperature".split(),
    ),
    (
        "реле давления",
        r"реле давления|прессостат",
        "range accuracy output connection protection temperature".split(),
    ),
    (
        "показывающий манометр",
        r"манометр|напоромер|тягомер|вакуумметр",
        "range accuracy connection protection temperature".split(),
    ),
    ("датчик давления", r"давлени", ALL),
]

DEFAULT_PROFILE = ("прибор КИП", ALL)
