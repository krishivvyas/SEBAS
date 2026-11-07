"""Load Sebas's secrets and config. Call load_env() before importing openjarvis.

OpenJarvis reads credentials from os.environ and has no .env support of its own,
and it resolves some paths at import time, so the order matters.

Run directly to send one real request through the provider chain (uses API quota):

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
    from sebas_brain import Brain

    brain = Brain()
    try:
        reply = brain.ask("How is my laptop doing? Use the system_status tool, then answer in one sentence.")
        print(f"answered by: {brain.description}")
        print(f"reply:       {reply}")
    finally:
        brain.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
