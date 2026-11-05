from datetime import UTC, datetime
from pathlib import Path

from card_generator.sources import build_input, find_offer, read_shop_name

FIXTURES = Path(__file__).parent / "fixtures"
FETCHED = datetime(2026, 11, 5, 11, 0, tzinfo=UTC)


def _build():
    feed = FIXTURES / "feed_sample.xml"
    html = (FIXTURES / "product_page.html").read_text(encoding="utf-8")
    return build_input(find_offer(feed, "1001"), html, FETCHED, read_shop_name(feed))


def test_offer_fields_map_to_input():
    data = _build()
    assert data["name"] == "ДТС025Л-РТ100.В4.320"
    assert data["manufacturer"] == "ОВЕН"
    assert data["product_type"] == "термосопротивление"
    assert data["specs_scope"] == "series"
    assert data["source"]["offer_id"] == "1001"
    assert data["source"]["page_fetched_at"] == "2026-11-05T11:00:00+00:00"


def test_quick_specs_and_table_are_merged_without_overwrite():
    specs = _build()["specs"]
    assert specs["Выходной сигнал"] == "Сопротивление 50, 100, 1000 Ом"
    assert specs["Взрывозащита"] == "Общепромышленное"
    assert specs["Номинальная статическая характеристика (НСХ)"] == (
        "50М; Pt100; 100М; Pt500, Pt1000"
    )
    assert specs["Диапазон измеряемых температур, класс допуска А"] == ("–50…+100 °C; –60…+450 °C")
    assert "Характеристики" not in specs


def test_matrix_table_keeps_column_names_per_row():
    specs = _build()["specs"]
    assert specs["Модификация: ДТС025Л-РТ100.В4.320"] == "Кол-во каналов: 2; Ток, мА: 290"
    assert specs["Модификация: ДТС025Л-РТ100.В4.500"] == "Кол-во каналов: 4; Ток, мА: 145"


def test_page_noise_does_not_reach_input():
    data = _build()
    text = data["description"] + " ".join(data["specs"].values())
    for noise in ("Купить", "В наличии", "руб.", "показать все", "\xa0"):
        assert noise not in text
    assert data["description"].splitlines() == [
        "ДТС025 — термопреобразователь сопротивления. НСХ по ГОСТ 6651-2009:",
        "ТСП Pt100, Pt500, Pt1000",
        "Корпус пластиковый.",
    ]
