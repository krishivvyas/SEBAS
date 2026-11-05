"""Morning briefing: local time, weather and the next day of Google Calendar events."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from openjarvis.core.paths import get_config_dir
from openjarvis.core.registry import ToolRegistry

from custom_tools._base import SebasTool

_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


def calendar_credentials_path() -> Path:
    """Same file OpenJarvis's own Google Calendar connector uses."""
    return get_config_dir() / "connectors" / "gcalendar.json"


def _events_api(token: str, time_min: str, time_max: str) -> dict:
    response = httpx.get(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "singleEvents": "true",
            "orderBy": "startTime",
            "timeMin": time_min,
            "timeMax": time_max,
            "maxResults": 20,
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def upcoming_events(hours: int = 24) -> str:
    path = calendar_credentials_path()
    if not path.exists():
        return (
            "Calendar: not connected. Run custom_tools/setup_google_calendar.py "
            "once to connect Google Calendar."
        )
    from openjarvis.connectors.google_auth import call_with_refresh

    now = datetime.now(timezone.utc)
    try:
        data = call_with_refresh(
            _events_api,
            str(path),
            now.isoformat(),
            (now + timedelta(hours=hours)).isoformat(),
        )
    except Exception as exc:
        return f"Calendar: could not be read ({type(exc).__name__}: {exc})."
    lines = []
    for event in data.get("items", []):
        start = event.get("start", {})
        if "dateTime" in start:
            when = datetime.fromisoformat(start["dateTime"]).astimezone().strftime("%a %I:%M %p")
        else:
            when = f"{start.get('date', '?')} (all day)"
        lines.append(f"- {when}: {event.get('summary', '(no title)')}")
    if not lines:
        return f"Calendar: nothing scheduled in the next {hours} hours."
    return f"Calendar, next {hours} hours:\n" + "\n".join(lines)


def weather_summary() -> str:
    location = os.environ.get("SEBAS_HOME_LOCATION", "").strip()
    if not location:
        return "Weather: SEBAS_HOME_LOCATION is not set in .env."
    from openjarvis.tools.weather import WeatherTool

    result = WeatherTool().execute(location=location)
    return f"Weather for {location}: {result.content}"


@ToolRegistry.register("morning_briefing")
class MorningBriefingTool(SebasTool):
    name = "morning_briefing"
    description = (
        "Gather the morning briefing: current local date and time, today's "
        "weather at home, and Google Calendar events for the next 24 hours. "
        "Use it when the user asks for their briefing or how their day looks."
    )
    timeout_seconds = 60.0

    def run(self) -> str:
        now = datetime.now().astimezone()
        return "\n\n".join(
            [
                f"Local time: {now.strftime('%A %d %B %Y, %I:%M %p')} ({now.tzname()})",
                weather_summary(),
                upcoming_events(),
            ]
        )
