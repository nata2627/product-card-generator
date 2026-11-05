"""Fail if any tracked or staged file contains a word from the private word list.

The list lives outside git, so on a fresh clone the check is skipped.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORDS_FILE = ROOT / ".git" / "info" / "private-words.txt"
# .gitignore has to name the private files to keep them out of git.
EXEMPT = {".gitignore"}


def load_words() -> list[str]:
    lines = WORDS_FILE.read_text(encoding="utf-8").splitlines()
    return [w.strip() for w in lines if w.strip() and not w.lstrip().startswith("#")]


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line and line not in EXEMPT]


def main() -> int:
    if not WORDS_FILE.exists():
        print("private words: list not found, skipped")
        return 0
    pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(w) for w in load_words()) + r")(?!\w)", re.IGNORECASE
    )
    hits = 0
    for name in tracked_files():
        if pattern.search(name):
            print(f"private word in file name: {name}")
            hits += 1
        path = ROOT / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                # The matched word is not printed so it does not leak into logs.
                print(f"private word: {name}:{lineno}")
                hits += 1
    if hits:
        print(f"private words: {hits} hit(s)")
        return 1
    print("private words: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
