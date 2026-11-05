import json

import pytest
from fastapi.testclient import TestClient

from card_generator import __main__ as cli
from card_generator.llm import LLMError
from card_generator.pipeline import make_card
from card_generator.render import to_dict, to_markdown
from card_generator.web import create_app
from tests.test_pipeline import PRODUCT, FakeLLM, reply


def test_json_carries_values_as_is_and_no_data_marks():
    data = to_dict(make_card(PRODUCT, FakeLLM(reply())))
    assert data["status"] == "ok"
    rows = {r["field"]: r["value"] for r in data["key_specs"]}
    assert rows["Диапазон измерений"] == "0–1,6 МПа"
    assert rows["Класс точности или погрешность"] == "1,5"
    assert rows["Степень защиты IP"] == "данных нет"
    assert "Степень защиты IP: данных нет." in data["clarify"]
    assert data["lengths"]["seo_title"] == len(data["seo_title"])
    assert data["meta"]["attempts"] == 1


def test_markdown_shows_flags_lengths_and_no_data():
    bad = reply(commercial="Класс точности 0,5.")
    md = to_markdown(make_card(PRODUCT, FakeLLM(bad, bad)))
    assert md.startswith("# Манометр DM 02\n")
    assert "## Требует проверки" in md
    assert "«0,5»" in md
    assert "из 70 символов" in md
    assert "| Степень защиты IP | **данных нет** |" in md
    assert "## Уточнить у поставщика" in md


def test_markdown_without_text_when_data_is_short():
    md = to_markdown(make_card({"name": "Манометр DM 02"}, FakeLLM()))
    assert "недостаточно данных" in md
    assert "## Описание" not in md
    assert "## Все характеристики из входа\n\nданных нет" in md


def test_pipe_in_values_does_not_break_the_table():
    data = {**PRODUCT, "specs": {**PRODUCT["specs"], "исполнение": "А | Б"}}
    md = to_markdown(make_card(data, FakeLLM(reply())))
    assert "| исполнение | А \\| Б |" in md


@pytest.fixture
def fake_cli(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "CALL_LOG", tmp_path / "calls.jsonl")

    def use(*replies):
        monkeypatch.setattr(
            cli.GigaChatClient, "from_env", classmethod(lambda c: FakeLLM(*replies))
        )

    return use


def test_cli_writes_json_and_markdown(fake_cli, tmp_path, capsys):
    fake_cli(reply())
    source = tmp_path / "gauge.json"
    source.write_text(json.dumps(PRODUCT, ensure_ascii=False), encoding="utf-8")
    assert cli.main([str(source), "-o", str(tmp_path / "out")]) == 0
    assert json.loads((tmp_path / "out" / "gauge.json").read_text())["status"] == "ok"
    assert (tmp_path / "out" / "gauge.md").read_text().startswith("# Манометр DM 02")
    assert "# Манометр DM 02" in capsys.readouterr().out
    assert json.loads((tmp_path / "calls.jsonl").read_text())["attempts"] == 1


def test_cli_reports_bad_input_without_traceback(fake_cli, tmp_path, capsys):
    source = tmp_path / "broken.json"
    source.write_text('{"name": ', encoding="utf-8")
    assert cli.main([str(source)]) == 2
    err = capsys.readouterr().err
    assert "Некорректный JSON" in err and "Traceback" not in err


def test_cli_missing_file(fake_cli, capsys):
    assert cli.main(["nope.json"]) == 2
    assert "Файл не найден" in capsys.readouterr().err


def test_cli_reports_model_error(monkeypatch, tmp_path, capsys):
    def no_key(cls):
        raise LLMError("Нет ключа GIGACHAT_AUTH_KEY. Заполните .env по README, шаг 3.")

    monkeypatch.setattr(cli.GigaChatClient, "from_env", classmethod(no_key))
    source = tmp_path / "gauge.json"
    source.write_text(json.dumps(PRODUCT, ensure_ascii=False), encoding="utf-8")
    assert cli.main([str(source)]) == 1
    assert "Нет ключа" in capsys.readouterr().err


def client(*replies) -> TestClient:
    return TestClient(create_app(lambda: FakeLLM(*replies)))


def test_form_page_opens():
    page = client().get("/")
    assert page.status_code == 200
    assert "Сгенерировать" in page.text


def test_empty_form_is_a_readable_error_not_500():
    body = {"name": "", "manufacturer": "", "product_type": "", "specs": {}, "description": ""}
    res = client().post("/api/card", json=body)
    assert res.status_code == 422
    assert res.json() == {"errors": ["Поле name (название): пустое значение."]}


def test_broken_json_body():
    res = client().post("/api/card", content=b"{oops")
    assert res.status_code == 422
    assert res.json()["errors"][0].startswith("Некорректный JSON")


def test_card_from_form():
    res = client(reply()).post("/api/card", json=PRODUCT)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["markdown"].startswith("# Манометр DM 02")


def test_model_error_is_502_with_message():
    def down():
        raise LLMError("Нет соединения с GigaChat.")

    res = TestClient(create_app(down)).post("/api/card", json=PRODUCT)
    assert res.status_code == 502
    assert res.json() == {"errors": ["Ошибка модели: Нет соединения с GigaChat."]}
