"""Load Sebas's secrets and config. Call load_env() before importing openjarvis.

OpenJarvis reads credentials from os.environ and has no .env support of its own,
and it resolves some paths at import time, so the order matters.

Run directly to send one real request through the orchestrator (uses API credit):

    .venv\\Scripts\\python.exe sebas_bootstrap.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


def load_env() -> None:
    """Populate os.environ from .env. Variables already set in the shell win."""
    load_dotenv(ROOT / ".env")
    os.environ.setdefault(
        "OPENJARVIS_CONFIG", str(ROOT / "configs" / "sebas" / "config.toml")
    )


def main() -> int:
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Copy .env.template to .env and fill it in.")
        return 1

    from openjarvis import Jarvis

    with Jarvis() as jarvis:
        result = jarvis.ask_full(
            "What is 2 + 2? Use the calculator tool, then reply in one short sentence.",
            agent="orchestrator",
            tools=["calculator"],
        )
    print(f"engine: {result.get('engine')}  model: {result.get('model')}")
    print(f"reply:  {result['content']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
