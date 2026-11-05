"""Check that every measured number in README.md matches the files in results/ and examples/.

python -m scripts.verify_numbers          # exit 1 and list the lines README is missing
python -m scripts.verify_numbers --print  # print the lines to paste into README

The lines are rendered from the result files, so README carries no hand-typed metric.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
PROMPTS = ("card_v1", "card_v2")


def _summary(prompt: str) -> dict:
    data = json.loads((ROOT / "results" / prompt / "eval.json").read_text(encoding="utf-8"))
    return data["summary"]


def _share(value: dict) -> str:
    return f"{value['k']} из {value['n']}"


def _decimal(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _value(summary: dict, key: str) -> str:
    value = summary[key]
    return _share(value) if isinstance(value, dict) else str(value)


# Row label in README and the summary key it shows.
EVAL_ROWS = [
    ("Первая попытка не по формату JSON", "first_attempt_format_errors"),
    ("Первая попытка с нарушением фактов", "first_attempt_with_fact_problems"),
    ("Нарушений фактов на первой попытке, всего", "first_attempt_fact_problems_total"),
    ("Нарушения фактов остались после повтора", "final_with_fact_problems"),
    ("Нарушений фактов после повтора, всего", "final_fact_problems_total"),
    ("Карточка помечена «требует проверки»", "needs_review"),
    ("Длины в норме с первой попытки", "first_attempt_lengths_ok"),
    ("Длины в норме в итоге", "final_lengths_ok"),
    ("Оценочные фразы без данных, всего", "evaluative_phrases_total"),
    ("Отказ «недостаточно данных»", "not_enough_data"),
    ("Ошибки API", "errors"),
]


def expected_lines() -> list[str]:
    summaries = [_summary(p) for p in PROMPTS]
    rows = [("Карточек с текстом", [f"{s['generated']} из {s['cases']}" for s in summaries])]
    rows += [(label, [_value(s, key) for s in summaries]) for label, key in EVAL_ROWS]
    rows.append(
        (
            "Время карточки, медиана и максимум, с",
            [
                f"{_decimal(s['latency_s_median'])}; {_decimal(s['latency_s_max'])}"
                for s in summaries
            ],
        )
    )
    rows.append(
        (
            "Токены, вход и выход, всего",
            [f"{s['prompt_tokens_total']}; {s['completion_tokens_total']}" for s in summaries],
        )
    )
    lines = [f"| {label} | {' | '.join(values)} |" for label, values in rows]
    lines.append(f"Модель {summaries[-1]['model']}")

    for path in sorted((ROOT / "examples" / "outputs").glob("*.json")):
        card = json.loads(path.read_text(encoding="utf-8"))
        lengths = card["lengths"]
        lines.append(
            f"| `{path.stem}` | {card['product']['name']} | {card['status']} | "
            f"{lengths['seo_title']} | {lengths['description']} | "
            f"{len([r for r in card['key_specs'] if r['status'] == 'missing'])} |"
        )

    inputs = [
        json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "eval" / "inputs").glob("*.json")
    ]
    examples = len(list((ROOT / "examples" / "inputs").glob("*.json")))
    lines.append(f"прогоняет {len(inputs)} товаров из фида")
    lines.append(f"из них {sum(d.get('manufacturer') != 'ОВЕН' for d in inputs)} не ОВЕН")
    lines.append(f"на {len(inputs) + examples} реальных входах")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", help="print the expected lines")
    args = parser.parse_args()

    lines = expected_lines()
    if args.print:
        print("\n".join(lines))
        return 0
    readme = README.read_text(encoding="utf-8")
    missing = [line for line in lines if line not in readme]
    for line in missing:
        print(f"README: нет строки «{line}»", file=sys.stderr)
    print(f"numbers: {len(lines) - len(missing)} of {len(lines)} lines match results")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
