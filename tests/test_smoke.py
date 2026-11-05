import os
from pathlib import Path

import pytest

import card_generator
from card_generator.llm import GigaChatClient
from card_generator.pipeline import make_card

ROOT = Path(__file__).resolve().parent.parent


def test_package_imports():
    assert card_generator is not None


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to call GigaChat")
def test_live_card_for_example():
    raw = (ROOT / "examples" / "inputs" / "hobbit_gas_analyzer.json").read_bytes()
    card = make_card(raw, GigaChatClient.from_env())
    assert card.status in {"ok", "needs_review"}
    assert card.text is not None
