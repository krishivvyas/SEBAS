"""One-time Google Calendar sign-in for the morning briefing (read-only access).

Needs GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env, from a "Desktop app"
OAuth client in Google Cloud Console with the Google Calendar API enabled.

    .venv\\Scripts\\python.exe custom_tools\\setup_google_calendar.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sebas_bootstrap import load_env  # noqa: E402

load_env()

from openjarvis.connectors.oauth import run_oauth_flow  # noqa: E402

from custom_tools.morning_briefing import (  # noqa: E402
    _CALENDAR_SCOPE,
    calendar_credentials_path,
    upcoming_events,
)


def main() -> int:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    if not (client_id and client_secret):
        print("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env first.")
        return 1
    path = calendar_credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    print("A browser window will open. Approve read-only calendar access.")
    run_oauth_flow(client_id, client_secret, [_CALENDAR_SCOPE], str(path))
    print(f"Saved to {path}\n")
    print(upcoming_events())
    return 0


if __name__ == "__main__":
    sys.exit(main())
