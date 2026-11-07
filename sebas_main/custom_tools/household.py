"""Daily life: the agenda (to-dos with deadlines), an expense log in rupees, and a journal.

Everything is kept as small JSON files under ~/.openjarvis/sebas/ (or
$OPENJARVIS_HOME/sebas/), readable and editable by hand.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from openjarvis.core.paths import get_data_dir
from openjarvis.core.registry import ToolRegistry

from custom_tools._base import SebasTool, ToolError

_lock = threading.Lock()


def _path(name: str) -> Path:
    return get_data_dir() / "sebas" / f"{name}.json"


def load(name: str) -> list[dict[str, Any]]:
    path = _path(name)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolError(f"{path.name} is damaged ({exc}); fix or delete it.") from exc


def save(name: str, items: list[dict[str, Any]]) -> None:
    path = _path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=1, ensure_ascii=False), "utf-8")
    tmp.replace(path)


def parse_when(value: str | None) -> datetime | None:
    """Accept 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' (also with a 'T')."""
    if not value:
        return None
    value = value.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[: len(datetime.now().strftime(fmt))], fmt)
        except ValueError:
            continue
    raise ToolError(f"Could not read the date '{value}'. Use YYYY-MM-DD or YYYY-MM-DD HH:MM.")


def _best_match(items: list[dict], text: str, field: str) -> dict:
    target = text.strip().lower()
    scored = sorted(
        ((SequenceMatcher(None, target, i[field].lower()).ratio() + (0.3 if target in i[field].lower() else 0), n)
         for n, i in enumerate(items)),
        reverse=True,
    )
    if not scored or scored[0][0] < 0.5:
        raise ToolError(f"Nothing matches '{text}'.")
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.05:
        raise ToolError(f"More than one item matches '{text}': {items[scored[0][1]][field]}; {items[scored[1][1]][field]}.")
    return items[scored[0][1]]


def describe_due(due: str | None, now: datetime | None = None) -> str:
    if not due:
        return "no deadline"
    when, now = datetime.fromisoformat(due), now or datetime.now()
    day = when.date()
    label = "today" if day == now.date() else "tomorrow" if day == now.date() + timedelta(days=1) else when.strftime("%a %d %b")
    has_time = when.time() != datetime.min.time()
    overdue = " (overdue)" if (when if has_time else datetime.combine(day, datetime.max.time())) < now else ""
    return label + (when.strftime(" %I:%M %p") if has_time else "") + overdue


# --------------------------------------------------------------------------- agenda

def open_tasks() -> list[dict]:
    tasks = [t for t in load("agenda") if not t.get("done")]
    return sorted(tasks, key=lambda t: t.get("due") or "9999")


@ToolRegistry.register("add_task")
class AddTaskTool(SebasTool):
    name = "add_task"
    description = (
        "Add a to-do to the user's agenda, optionally with a deadline. Convert phrases "
        "like 'by Friday' or 'tomorrow at 5' into an absolute date using the current "
        "date given in the conversation."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "What needs doing."},
            "due": {"type": "string", "description": "Deadline as YYYY-MM-DD or YYYY-MM-DD HH:MM (24h). Omit if none."},
        },
        "required": ["task"],
    }

    def run(self, task: str, due: str = "") -> str:
        task = " ".join((task or "").split())
        if not task:
            raise ToolError("There was no task to add.")
        when = parse_when(due)
        with _lock:
            items = load("agenda")
            items.append({"id": uuid.uuid4().hex[:8], "task": task, "due": when.isoformat() if when else None,
                          "added": datetime.now().isoformat(timespec="minutes"), "done": False})
            save("agenda", items)
        return f"Added: {task} ({describe_due(when.isoformat() if when else None)})."


@ToolRegistry.register("list_tasks")
class ListTasksTool(SebasTool):
    name = "list_tasks"
    description = "List the open to-dos on the user's agenda, soonest deadline first."

    def run(self) -> str:
        tasks = open_tasks()
        if not tasks:
            return "The agenda is clear."
        return "\n".join(f"- {t['task']} ({describe_due(t.get('due'))})" for t in tasks)


@ToolRegistry.register("complete_task")
class CompleteTaskTool(SebasTool):
    name = "complete_task"
    description = "Mark a to-do as done (or remove it if the user cancels it)."
    parameters = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "The to-do, as the user describes it."},
            "cancel": {"type": "boolean", "description": "true to delete instead of marking done."},
        },
        "required": ["task"],
    }

    def run(self, task: str, cancel: bool = False) -> str:
        with _lock:
            items = load("agenda")
            match = _best_match([i for i in items if not i.get("done")], task, "task")
            if cancel:
                items = [i for i in items if i["id"] != match["id"]]
            else:
                match["done"] = datetime.now().isoformat(timespec="minutes")
            save("agenda", items)
        return f"{'Removed' if cancel else 'Done'}: {match['task']}."


# --------------------------------------------------------------------------- expenses

@ToolRegistry.register("log_expense")
class LogExpenseTool(SebasTool):
    name = "log_expense"
    description = "Record money the user spent, in Indian rupees."
    parameters = {
        "type": "object",
        "properties": {
            "amount": {"type": "number", "description": "Amount in rupees."},
            "category": {"type": "string", "description": "One word: food, transport, shopping, bills, entertainment, books, games, health, other."},
            "note": {"type": "string", "description": "What it was for, briefly."},
            "date": {"type": "string", "description": "YYYY-MM-DD if not today."},
        },
        "required": ["amount", "category"],
    }

    def run(self, amount: float, category: str, note: str = "", date: str = "") -> str:
        amount = round(float(amount), 2)
        if amount <= 0:
            raise ToolError("The amount must be above zero.")
        day = (parse_when(date) or datetime.now()).date().isoformat()
        category = (category or "other").strip().lower()
        with _lock:
            items = load("expenses")
            items.append({"date": day, "amount": amount, "category": category, "note": note.strip()})
            save("expenses", items)
            month = sum(i["amount"] for i in items if i["date"][:7] == day[:7])
        return f"Logged ₹{amount:,.0f} on {category}. This month so far: ₹{month:,.0f}."


def expense_totals(period: str, today: date | None = None) -> tuple[float, dict[str, float], int]:
    today = today or date.today()
    start = {"today": today, "week": today - timedelta(days=today.weekday()),
             "month": today.replace(day=1), "year": today.replace(month=1, day=1)}[period]
    total, by_cat, count = 0.0, {}, 0
    for i in load("expenses"):
        if start.isoformat() <= i["date"] <= today.isoformat():
            total += i["amount"]; count += 1
            by_cat[i["category"]] = by_cat.get(i["category"], 0) + i["amount"]
    return total, dict(sorted(by_cat.items(), key=lambda kv: -kv[1])), count


@ToolRegistry.register("expense_summary")
class ExpenseSummaryTool(SebasTool):
    name = "expense_summary"
    description = "Summarise the user's spending for today, this week, this month or this year, by category."
    parameters = {
        "type": "object",
        "properties": {"period": {"type": "string", "enum": ["today", "week", "month", "year"]}},
        "required": ["period"],
    }

    def run(self, period: str = "month") -> str:
        if period not in ("today", "week", "month", "year"):
            raise ToolError("Period must be today, week, month or year.")
        total, by_cat, count = expense_totals(period)
        if not count:
            return f"Nothing spent {'today' if period == 'today' else 'this ' + period}."
        parts = ", ".join(f"{c} ₹{v:,.0f}" for c, v in by_cat.items())
        return f"{count} expenses, ₹{total:,.0f} in total: {parts}."


@ToolRegistry.register("undo_expense")
class UndoExpenseTool(SebasTool):
    name = "undo_expense"
    description = "Remove the most recently logged expense, when the user says it was a mistake."

    def run(self) -> str:
        with _lock:
            items = load("expenses")
            if not items:
                raise ToolError("There are no expenses to remove.")
            last = items.pop()
            save("expenses", items)
        return f"Removed ₹{last['amount']:,.0f} on {last['category']} ({last['date']})."


# --------------------------------------------------------------------------- journal

@ToolRegistry.register("journal_add")
class JournalAddTool(SebasTool):
    name = "journal_add"
    description = (
        "Save the user's account of their day to their private journal. Record it "
        "faithfully in the first person, lightly tidied; do not add your own opinions."
    )
    parameters = {
        "type": "object",
        "properties": {
            "entry": {"type": "string", "description": "The journal entry."},
            "mood": {"type": "string", "description": "One word for the mood, if it is clear."},
        },
        "required": ["entry"],
    }

    def run(self, entry: str, mood: str = "") -> str:
        entry = (entry or "").strip()
        if not entry:
            raise ToolError("There was nothing to write in the journal.")
        with _lock:
            items = load("journal")
            items.append({"date": date.today().isoformat(), "time": datetime.now().strftime("%H:%M"),
                          "entry": entry, "mood": mood.strip().lower()})
            save("journal", items)
        return "The journal entry has been saved."


@ToolRegistry.register("journal_read")
class JournalReadTool(SebasTool):
    name = "journal_read"
    description = "Read the user's journal entries from the last few days, e.g. for a weekly recap."
    parameters = {
        "type": "object",
        "properties": {"days": {"type": "integer", "description": "How many days back (default 7)."}},
    }

    def run(self, days: int = 7) -> str:
        since = (date.today() - timedelta(days=max(1, int(days or 7)) - 1)).isoformat()
        entries = [e for e in load("journal") if e["date"] >= since]
        if not entries:
            return "No journal entries in that period."
        return "\n".join(f"{e['date']}{' (' + e['mood'] + ')' if e.get('mood') else ''}: {e['entry']}" for e in entries)
