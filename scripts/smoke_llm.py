"""One live GigaChat call through the project client; prints the answer and usage only."""

import json
from dataclasses import asdict
from pathlib import Path

from card_generator.llm import GigaChatClient

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    client = GigaChatClient.from_env()
    result = client.complete([{"role": "user", "content": "Ответь одним словом: столица России?"}])
    out = ROOT / "logs" / "smoke_llm.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(asdict(result), ensure_ascii=False))


if __name__ == "__main__":
    main()
