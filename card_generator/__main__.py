"""CLI: python -m card_generator input.json [-o out/]"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from card_generator.llm import ROOT, GigaChatClient, LazyClient, LLMError
from card_generator.pipeline import make_card
from card_generator.prompting import DEFAULT_PROMPT, load_prompt
from card_generator.render import to_dict, to_markdown
from card_generator.schema import InputError

CALL_LOG = ROOT / "logs" / "calls.jsonl"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m card_generator", description="Черновик карточки товара КИП."
    )
    parser.add_argument("input", help="JSON-файл с данными товара или - для stdin")
    parser.add_argument("-o", "--out", type=Path, default=Path("out"), help="папка для .json и .md")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="версия промпта из prompts/")
    parser.add_argument(
        "--draft-anyway",
        action="store_true",
        help="генерировать текст, даже если данных меньше порога",
    )
    args = parser.parse_args(argv)

    try:
        if args.input == "-":
            raw, stem = sys.stdin.buffer.read(), "card"
        else:
            path = Path(args.input)
            if not path.is_file():
                raise InputError([f"Файл не найден: {path}"])
            raw, stem = path.read_bytes(), path.stem
        card = make_card(
            raw, LazyClient(GigaChatClient.from_env), load_prompt(args.prompt), args.draft_anyway
        )
    except InputError as exc:
        print("Ошибка во входных данных:", *exc.messages, sep="\n- ", file=sys.stderr)
        return 2
    except LLMError as exc:
        print(f"Ошибка модели: {exc}", file=sys.stderr)
        return 1

    data = to_dict(card)
    markdown = to_markdown(card)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{stem}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.out / f"{stem}.md").write_text(markdown, encoding="utf-8")
    _log_call(stem, data)
    print(markdown)
    print(f"Сохранено: {args.out / stem}.json, {args.out / stem}.md", file=sys.stderr)
    return 0


def _log_call(stem: str, data: dict) -> None:
    CALL_LOG.parent.mkdir(exist_ok=True)
    record = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "input": stem,
        "status": data["status"],
        "lengths": data["lengths"],
        "needs_review": len(data["needs_review"]),
        **data["meta"],
    }
    with CALL_LOG.open("a", encoding="utf-8") as log:
        log.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    sys.exit(main())
