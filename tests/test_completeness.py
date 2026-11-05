from pathlib import Path

from card_generator.completeness import NO_DATA, analyze, detect_profile
from card_generator.schema import parse_product

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "inputs"


def load(name: str):
    product, _ = parse_product((EXAMPLES / name).read_bytes())
    return product


def statuses(report) -> dict[str, str]:
    return {f.key: f.status for f in report.fields}


def test_pressure_sensor_example():
    product = load("pd100_pressure_sensor.json")
    report = analyze(product)
    assert report.profile == "датчик давления"
    assert report.spec_rows == list(product.specs.items())
    assert statuses(report) == {
        "range": "description",
        "accuracy": "specs",
        "power": "specs",
        "output": "specs",
        "connection": "specs",
        "protection": "specs",
        "temperature": "specs",
    }
    assert report.missing == []
    assert any(c.startswith("Диапазон измерений: есть только в описании") for c in report.clarify)
    assert any("для серии" in c and product.name in c for c in report.clarify)
    assert report.enough_data


def test_gas_analyzer_example_marks_missing_fields():
    report = analyze(load("hobbit_gas_analyzer.json"))
    assert report.profile == "газоанализатор"
    assert statuses(report)["range"] == "specs"
    assert report.missing == [
        "Класс точности или погрешность",
        "Питание",
        "Выходной сигнал или интерфейс",
        "Степень защиты IP",
        "Рабочая температура",
    ]
    for label in report.missing:
        assert f"{label}: данных нет." in report.clarify
    missing_values = [f.value for f in report.fields if f.status == "missing"]
    assert missing_values == [NO_DATA] * 5
    assert report.enough_data


def test_spec_values_are_copied_as_is():
    specs = {"Диапазон измерений": "0–1,6 МПа", "Класс точности": "1,5", "Присоединение": "G1/2"}
    product, _ = parse_product({"name": "Манометр DM 02", "specs": specs})
    assert analyze(product).spec_rows == list(specs.items())


def test_empty_specs_and_no_description():
    product, _ = parse_product({"name": "Манометр DM 02", "manufacturer": "Манотомь"})
    report = analyze(product)
    assert report.spec_rows == []
    assert all(f.status == "missing" for f in report.fields)
    assert "Описание: данных нет." in report.clarify
    assert not any("для серии" in c for c in report.clarify)
    assert not report.enough_data


def test_only_name():
    product, _ = parse_product({"name": "ДТС025"})
    report = analyze(product)
    assert report.profile == "прибор КИП"
    assert len(report.missing) == 7
    assert "Производитель: данных нет." in report.clarify
    assert any(c.startswith("Тип прибора: не указан") for c in report.clarify)
    assert not report.enough_data


def test_long_description_alone_is_enough():
    product, _ = parse_product({"name": "ПД100", "description": "Датчик давления. " * 30})
    assert analyze(product).enough_data


def test_ip_code_found_in_value_under_any_name():
    product, _ = parse_product({"name": "Реле РД-2Р", "specs": {"Корпус": "IP42"}})
    [protection] = [f for f in analyze(product).fields if f.key == "protection"]
    assert protection.spec_names == ["Корпус"]


def test_profile_by_type_then_name():
    def profile(name, product_type=""):
        return detect_profile(parse_product({"name": name, "product_type": product_type})[0])[0]

    assert profile("ТМ-210Р", "манометр сварочный") == "показывающий манометр"
    assert profile("ТРМ501", "реле-регулятор с таймером") == "регулятор или контроллер"
    assert profile("ДТС025Л-РТ100", "термопреобразователь сопротивления") == "датчик температуры"
    assert profile("Блок питания БП14Б") == "блок питания"
    assert profile("Датчик давления ПД100", "") == "датчик давления"


def test_mechanical_gauge_does_not_ask_for_power():
    product, _ = parse_product({"name": "ТМ-210Р", "product_type": "манометр"})
    assert "Питание" not in analyze(product).missing
