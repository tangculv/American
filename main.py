from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.cli import main  # noqa: E402


if __name__ == "__main__":
    argv = sys.argv[1:]
    known_commands = {"run", "run-and-notify", "notify-latest", "list-strategies", "-h", "--help"}
    if not argv:
        argv = ["run"]
    elif argv[0] not in known_commands:
        argv = ["run", *argv]
    raise SystemExit(main(argv))
