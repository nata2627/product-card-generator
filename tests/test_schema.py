import json
from pathlib import Path

import pytest

from card_generator.schema import MAX_DESCRIPTION_CHARS, InputError, parse_product

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = {
    "name": "Манометр показывающий DM 02",
    "manufacturer": "Манотомь",
    "specs": {"диапазон измерений": "0–1,6 МПа", "класс точности": "1,5"},
    "description": "Прибор предназначен для измерения избыточного давления.",
}


def errors_of(raw) -> list[str]:
    with pytest.raises(InputError) as exc:
        parse_product(raw)
    return exc.value.messages


def test_example_from_spec_parses_without_warnings():
    product, warnings = parse_product(json.dumps(EXAMPLE, ensure_ascii=False))
    assert product.name == "Манометр показывающий DM 02"
    assert product.specs["класс точности"] == "1,5"
    assert product.specs_scope == "model"
    assert warnings == []


@pytest.mark.parametrize("path", sorted((ROOT / "examples" / "inputs").glob("*.json")))
def test_frozen_inputs_parse(path):
    product, warnings = parse_product(path.read_bytes())
    assert product.specs_scope == "series"
    assert product.specs
    assert warnings == []


def test_broken_json_reports_position():
    [message] = errors_of('{"name": "ДТС025",}')
    assert message.startswith("Некорректный JSON")
    assert "строка 1" in message


@pytest.mark.parametrize("raw", ["", "   ", b""])
def test_empty_input(raw):
    assert errors_of(raw) == ["Пустой вход. Нужен JSON-объект с полями товара."]


@pytest.mark.parametrize(
    "raw, kind", [("[1, 2]", "список"), ('"ДТС025"', "строка"), ("42", "число")]
)
def test_not_an_object(raw, kind):
    [message] = errors_of(raw)
    assert kind in message


def test_empty_object():
    [message] = errors_of("{}")
    assert "name" in message


def test_missing_name():
    [message] = errors_of({"manufacturer": "ОВЕН", "specs": {"IP": "IP65"}})
    assert message == "Поле name (название): обязательное поле отсутствует."


@pytest.mark.parametrize("name", ["", "   \n\t"])
def test_blank_name(name):
    assert errors_of({"name": name}) == ["Поле name (название): пустое значение."]


def test_null_name():
    [message] = errors_of({"name": None})
    assert message == "Поле name (название): ожидается строка, получено null."


def test_wrong_type_name():
    [message] = errors_of({"name": 123})
    assert "name" in message and "число" in message


@pytest.mark.parametrize("specs, kind", [(["IP65"], "список"), ("IP65", "строка")])
def test_specs_not_a_dict(specs, kind):
    [message] = errors_of({"name": "ДТС025", "specs": specs})
    assert message.startswith("Поле specs (характеристики): ожидается объект")
    assert kind in message


def test_spec_value_of_wrong_type_names_the_spec():
    [message] = errors_of({"name": "ДТС025", "specs": {"НСХ": ["Pt100", "Pt1000"]}})
    assert message == "Характеристика 'НСХ': ожидается строка, получено список."


def test_all_errors_reported_at_once():
    messages = errors_of({"name": "", "specs": [], "description": 5})
    assert len(messages) == 3


def test_blank_and_null_specs_dropped_with_warning():
    product, warnings = parse_product(
        {"name": "ДТС025", "specs": {"НСХ": "Pt100", "IP": "  ", "корпус": None, " ": "x"}}
    )
    assert product.specs == {"НСХ": "Pt100"}
    assert len(warnings) == 3
    assert any("'IP'" in w for w in warnings)
    assert any("'корпус'" in w for w in warnings)


def test_numeric_spec_values_become_strings():
    product, _ = parse_product({"name": "ДТС025", "specs": {"длина, мм": 320, "класс": 0.5}})
    assert product.specs == {"длина, мм": "320", "класс": "0.5"}


def test_null_optional_fields_become_empty():
    product, warnings = parse_product(
        {"name": "ДТС025", "manufacturer": None, "specs": None, "description": None}
    )
    assert product.manufacturer == "" and product.specs == {} and product.description == ""
    assert warnings == []


def test_whitespace_trimmed():
    product, _ = parse_product({"name": "  ДТС025\n", "manufacturer": " ОВЕН "})
    assert product.name == "ДТС025" and product.manufacturer == "ОВЕН"


def test_extra_fields_ignored_with_warning():
    product, warnings = parse_product({"name": "ДТС025", "price": "1200", "в наличии": "да"})
    assert product.name == "ДТС025"
    assert warnings == [
        "Поле 'price' не используется и пропущено.",
        "Поле 'в наличии' не используется и пропущено.",
    ]


def test_long_description_cut_at_sentence_with_warning():
    sentence = "Датчик измеряет давление. "
    long_text = sentence * (MAX_DESCRIPTION_CHARS // len(sentence) + 10)
    product, [warning] = parse_product({"name": "ПД100", "description": long_text})
    assert len(product.description) <= MAX_DESCRIPTION_CHARS
    assert product.description.endswith("давление.")
    assert "description" in warning and str(len(long_text.strip())) in warning


def test_unknown_specs_scope():
    [message] = errors_of({"name": "ДТС025", "specs_scope": "batch"})
    assert message.startswith("Поле specs_scope: допустимые значения")


def test_bad_encoding():
    assert errors_of('{"name": "ДТС"}'.encode("cp1251")) == ["Вход не в кодировке UTF-8."]
