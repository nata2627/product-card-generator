import json

from scripts.run_eval import BROKEN, INJECTED, INPUTS, summarize, to_markdown


def test_injected_values_are_absent_from_the_source():
    source = (INPUTS / "54378.json").read_text(encoding="utf-8").lower()
    assert not [v for v in INJECTED if v in source]
    assert BROKEN["broken_injection"][1]()["description"].startswith("Игнорируй")


def test_broken_inputs_lose_what_they_claim():
    assert "specs" not in BROKEN["broken_no_specs"][1]()
    assert list(BROKEN["broken_name_only"][1]()) == ["name"]
    assert len(BROKEN["broken_short"][1]()["specs"]) == 4


def _record(case, attempts, first_facts=0, final_facts=0, first_ok=True, final_ok=True):
    metrics = {
        "status": "not_enough_data" if not attempts else ("needs_review" if final_facts else "ok"),
        "attempts": attempts,
        "missing_fields": ["Питание"],
        "clarify": 0,
        "input_warnings": 0,
    }
    if attempts:
        metrics |= {
            "first_fact_problems": first_facts,
            "first_format_error": False,
            "first_lengths_ok": first_ok,
            "final_fact_problems": final_facts,
            "final_lengths_ok": final_ok,
            "flags": final_facts,
            "lengths": {"seo_title": 60, "description": 900, "search_queries": 4},
            "latency_s": 10.0 * attempts,
            "first_latency_s": 10.0,
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "evaluative_phrases": ["надежн"] * final_facts,
        }
    card = {"product": {"name": case}, "meta": {"model": "m"}}
    return {"case": case, "note": "", "metrics": metrics, "card": card}


def test_summary_keeps_denominators():
    records = [
        _record("a", 1),
        _record("b", 2, first_facts=3, final_facts=1, first_ok=False),
        _record("c", 0),
        {"case": "d", "note": "", "error": "таймаут"},
    ]
    s = summarize(records, "card_v1", "m")
    assert s["generated"] == 2
    assert s["first_attempt_with_fact_problems"] == {"k": 1, "n": 2}
    assert s["first_attempt_fact_problems_total"] == 3
    assert s["final_with_fact_problems"] == {"k": 1, "n": 2}
    assert s["first_attempt_lengths_ok"] == {"k": 1, "n": 2}
    assert s["not_enough_data"] == {"k": 1, "n": 3}
    assert s["errors"] == {"k": 1, "n": 4}
    assert s["latency_s_median"] == 15.0
    assert s["with_evaluative_phrases"] == {"k": 1, "n": 2}
    markdown = to_markdown(s, records)
    assert "| Первая попытка с нарушением фактов | 1 из 2 |" in markdown
    assert "ошибка: таймаут" in markdown
    json.dumps(s, ensure_ascii=False)
