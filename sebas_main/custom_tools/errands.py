"""Errands: one request, several steps, carried out in the background.

"Prepare me for the DBMS exam on the 20th" becomes a plan (a title and up to
twelve steps, each one of Sebas's own tools), shown as a checklist on the
interface and worked through on a background thread. Errands add no new powers:
a step can only be a tool Sebas already has, with that tool's own safeguards.

Who thinks about what
    The plan        written by whichever model is holding the conversation, as
                    the arguments of start_errand (no extra request).
    Ordinary steps  run by plain code: no model at all.
    Judgment steps  a step with a ``decide`` note needs its arguments worked out
                    from earlier results ("use the file found in step 1"). That
                    is one short, stand-alone question answered in JSON.
    The report      built by code from the step results.

The quarter rule
    Judgment steps go to Gemini unless the errand would spend more than a quarter
    of what is left of today's Gemini budget (sebas_brain: SEBAS_GEMINI_DAILY_BUDGET,
    default 60), in which case they go to the local Ollama model: slower, but
    free. A local answer that cannot be used is retried once, then that one step
    is put to Gemini. With no local model, everything stays on Gemini. The user
    can force either ("on the local model", "use Gemini for this").

Risk
    A plan containing a risky tool (delete, close, discard) is read out and waits
    for the user's yes before it starts. A risky step whose arguments were only
    decided during the errand pauses and asks again, with the particulars.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

import httpx
from openjarvis.core.registry import ToolRegistry

import sebas_actions
from custom_tools import laptop
from custom_tools._base import SebasTool, ToolError
from custom_tools.household import load, save
from sebas_events import emit

logger = logging.getLogger("sebas.errands")

MAX_STEPS = 12
_FILE = "errands"                 # saved plans
_NOT_STEPS = {"start_errand", "errand", "errand_go"}  # an errand cannot start an errand
_RESULT_CHARS = 1500              # of each earlier result shown to a judgment step
_TOLD_CHARS = 500                 # of a result the user asked to hear, in the spoken report
_LOCAL_TIMEOUT = 600.0           # the first local answer includes loading the model

_lock = threading.Lock()
_errand: dict[str, Any] | None = None   # the running errand, or the last one
_parked: dict[str, Any] | None = None   # a plan with a risky step, waiting for a yes


# --------------------------------------------------------------------------- the plan

def _tool(name: str) -> SebasTool:
    if name in _NOT_STEPS or not ToolRegistry.contains(name):
        raise ToolError(f"'{name}' is not a tool that can be a step.")
    return ToolRegistry.create(name)


def check_plan(title: str, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate a plan and return it in the form the runner uses."""
    title = " ".join((title or "").split())
    if not title:
        raise ToolError("The errand needs a short title.")
    if not isinstance(steps, list) or not steps:
        raise ToolError("The errand needs at least one step.")
    if len(steps) > MAX_STEPS:
        raise ToolError(f"An errand may have at most {MAX_STEPS} steps; this plan has {len(steps)}. Combine or drop some.")
    plan = []
    for n, raw in enumerate(steps, 1):
        if not isinstance(raw, dict):
            raise ToolError(f"Step {n} is not an object.")
        name, decide = str(raw.get("tool", "")).strip(), " ".join(str(raw.get("decide") or "").split())
        tool = _tool(name)
        args = raw.get("args") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError as exc:
                raise ToolError(f"Step {n}: 'args' is not valid JSON ({exc}).") from exc
        if not isinstance(args, dict):
            raise ToolError(f"Step {n}: 'args' must be a JSON object.")
        schema = tool.spec.parameters or {}
        unknown = [k for k in args if k not in schema.get("properties", {})]
        if unknown:
            raise ToolError(f"Step {n}: {name} has no parameter {', '.join(unknown)}.")
        missing = [k for k in schema.get("required", []) if k not in args]
        if missing and not decide:
            raise ToolError(f"Step {n}: {name} needs {', '.join(missing)}. Give it in 'args', or add a 'decide' "
                            "note saying how to work it out from an earlier step.")
        plan.append({"say": " ".join(str(raw.get("say") or name.replace("_", " ")).split())[:80], "tool": name,
                     "args": args, "decide": decide, "tell": bool(raw.get("tell")), "state": "pending", "result": ""})
    return plan


def _risky_steps(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in plan if _tool(s["tool"]).risky]


# --------------------------------------------------------------------------- who thinks

def choose_engine(plan: list[dict[str, Any]], wish: str = "auto") -> tuple[str, str]:
    """("gemini" | "local", a sentence for the user or "") for this errand's judgment steps."""
    from sebas_brain import choose_local_model, gemini_remaining

    judged = sum(1 for s in plan if s["decide"])
    if not judged:
        return "gemini", ""  # nothing to think about: plain code does it all
    wish = (wish or "auto").strip().lower()
    have_key = bool(_gemini_keys())

    def local_ready() -> str:
        try:
            return choose_local_model()
        except Exception as exc:  # Ollama missing, not running, or no suitable model
            logger.info("No local model for the errand: %s", exc)
            return ""

    if wish == "gemini" and have_key:
        return "gemini", ""
    if wish == "local" or not have_key:
        model = local_ready()
        if model:
            return "local", f"As asked, I shall think it through on the local model ({model}); it will be slower."
        if not have_key:
            raise ToolError("This errand needs judgment, and neither a Gemini key nor a local model is available.")
        return "gemini", "No local model is available, so I shall use Gemini."
    remaining = gemini_remaining()
    cost = 1 + judged  # the plan itself, plus one request per judgment step
    if cost * 4 <= remaining:
        return "gemini", ""
    model = local_ready()
    if not model:
        return "gemini", (f"This errand will use about {cost} of the {remaining} Gemini requests left today; "
                          "no local model is available to spare them.")
    return "local", (f"This is a large errand for what is left of today's Gemini quota ({cost} of {remaining} requests), "
                     f"so I shall think it through on the local model ({model}); it will be slower.")


def _gemini_keys() -> list[str]:
    import os

    return [k for k in (os.environ.get("GEMINI_API_KEY", ""), os.environ.get("GEMINI_API_KEY_2", "")) if k.strip()]


def ask_gemini(prompt: str) -> str:
    from custom_tools.assist import gemini_once

    return gemini_once([prompt], need="An errand step", json_mode=True)


def ask_local(prompt: str) -> str:
    from sebas_brain import OLLAMA_URL, choose_local_model

    try:
        reply = httpx.post(f"{OLLAMA_URL}/api/chat", timeout=_LOCAL_TIMEOUT, json={
            "model": choose_local_model(), "stream": False, "format": "json", "keep_alive": "10m",
            "options": {"temperature": 0, "num_ctx": 4096},
            "messages": [{"role": "user", "content": prompt}]})
        reply.raise_for_status()
        return reply.json()["message"]["content"]
    except (httpx.HTTPError, KeyError, RuntimeError) as exc:
        raise ToolError(f"The local model did not answer: {exc}") from exc


def _read_judgment(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    """The model's JSON -> {"args": {...}} or {"skip": "why"}; raises ToolError if unusable."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ToolError(f"not JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise ToolError("not a JSON object")
    if data.get("skip"):
        return {"skip": str(data["skip"])[:200]}
    args = data.get("args")
    if not isinstance(args, dict):
        raise ToolError("no 'args' object")
    known = schema.get("properties", {})
    args = {k: v for k, v in args.items() if k in known and v is not None}
    missing = [k for k in schema.get("required", []) if k not in args]
    if missing:
        raise ToolError(f"missing {', '.join(missing)}")
    return {"args": args}


def judge(errand: dict[str, Any], index: int) -> dict[str, Any]:
    """Work out one step's arguments from the earlier results."""
    step = errand["steps"][index]
    tool = _tool(step["tool"])
    schema = tool.spec.parameters or {}
    earlier = "\n".join(f"{n}. {s['say']} [{s['state']}]: {s['result'][:_RESULT_CHARS] or '(no output)'}"
                        for n, s in enumerate(errand["steps"][:index], 1)) or "(this is the first step)"
    prompt = (
        "You are filling in the arguments for one step of a multi-step errand being carried out for a user. "
        "Reply with a single JSON object and nothing else.\n\n"
        f"Today: {datetime.now():%A %d %B %Y, %H:%M}\nErrand: {errand['title']}\n\nResults of the earlier steps:\n{earlier}\n\n"
        f"This step: {step['say']}\nTool: {step['tool']}: {tool.spec.description}\n"
        f"Parameters (JSON schema): {json.dumps(schema)}\nArguments given so far: {json.dumps(step['args'])}\n"
        f"How to decide: {step['decide']}\n\n"
        'Reply {"args": {...the complete arguments...}}. If the earlier results show that this step cannot or '
        'should not be done, reply {"skip": "the reason in a few words"}. Use only values that appear in the '
        "results or the instructions; never invent a file, a name or a date."
    )
    order = [ask_local, ask_local, ask_gemini] if errand["engine"] == "local" else [ask_gemini, ask_local]
    problems = []
    for ask in order:
        if ask is ask_gemini and not _gemini_keys():
            continue
        try:
            found = _read_judgment(ask(prompt), schema)
        except ToolError as exc:
            problems.append(f"{'Gemini' if ask is ask_gemini else 'local'}: {exc}")
            continue
        if ask is ask_gemini and errand["engine"] == "local":
            errand["gemini_rescues"] = errand.get("gemini_rescues", 0) + 1
        return found
    raise ToolError("No model could decide this step (" + "; ".join(problems)[:300] + ").")


# --------------------------------------------------------------------------- running

def _tell(text: str) -> None:
    import sebas_calls  # mid-call it would be spoken into the call: it waits

    sebas_calls.DESK.hold_or_say(laptop._announce, text)


def snapshot() -> dict[str, Any] | None:
    """For the interface: the errand as a checklist."""
    e = _errand
    if e is None or (e["state"] != "running" and time.time() - e.get("ended", 0) > 600):
        return None
    return {"title": e["title"], "state": e["state"], "engine": e["engine"],
            "steps": [{"say": s["say"], "state": s["state"]} for s in e["steps"]]}


def _show() -> None:
    emit("errand", errand=snapshot())


def _set(step: dict[str, Any], state: str, result: str = "") -> None:
    step["state"], step["result"] = state, (result or step["result"])
    _show()


def _confirm_step(errand: dict[str, Any], step: dict[str, Any], tool: SebasTool, args: dict[str, Any]) -> None:
    """A risky step decided mid-errand: ask, and wait for the user's answer."""
    settled = threading.Event()
    outcome: dict[str, Any] = {}

    def on_settled(result: str, text: str, ok: bool) -> None:
        outcome.update(result=result, text=text, ok=ok)
        settled.set()

    summary = tool.confirm_summary(**args)
    sebas_actions.request(step["tool"], args, summary, on_settled)
    _set(step, "waiting")
    _tell(f"Sir, the errand '{errand['title']}' needs your word before its next step. {summary} "
          "Say 'Sebas, yes' to proceed, or 'Sebas, no' to skip it.")
    if not settled.wait(sebas_actions.CONFIRM_SECONDS + 30):
        sebas_actions.answer("")  # drop it: nobody answered
        outcome.setdefault("result", "lapsed")
    if outcome.get("result") == "yes":
        _set(step, "done" if outcome["ok"] else "failed", outcome["text"])
    else:
        _set(step, "skipped", "declined by the user" if outcome.get("result") == "no" else "no answer was given")


def _run(errand: dict[str, Any]) -> None:
    for index, step in enumerate(errand["steps"]):
        if errand["state"] != "running":  # stopped
            break
        _set(step, "running")
        try:
            tool, args, judged = _tool(step["tool"]), dict(step["args"]), False
            if step["decide"]:
                found = judge(errand, index)
                if "skip" in found:
                    _set(step, "skipped", found["skip"])
                    continue
                args, judged = {**args, **found["args"]}, True
            if tool.risky and judged:  # the user approved the plan, not these particulars
                _confirm_step(errand, step, tool, args)
                continue
            result = tool.run_now(**args)  # a risky step with fixed arguments was approved with the plan
            _set(step, "done" if result.success else "failed", str(result.content))
        except ToolError as exc:
            _set(step, "failed", str(exc))
        except Exception as exc:
            logger.exception("Errand step failed")
            _set(step, "failed", f"{type(exc).__name__}: {exc}")
    _finish(errand)


def _finish(errand: dict[str, Any]) -> None:
    steps = errand["steps"]
    done = sum(s["state"] == "done" for s in steps)
    stopped = errand["state"] == "stopped"
    errand["state"], errand["ended"] = ("stopped" if stopped else "done"), time.time()
    for s in steps:
        if s["state"] in ("pending", "running"):
            s["state"] = "skipped"
            s["result"] = s["result"] or "the errand was stopped"
    troubles = [f"step {n} ({s['say']}) {'failed' if s['state'] == 'failed' else 'was skipped'}: "
                f"{' '.join(s['result'].split())[:120]}" for n, s in enumerate(steps, 1) if s["state"] in ("failed", "skipped")]
    report = (f"Sir, the errand '{errand['title']}' {'was stopped' if stopped else 'is complete'}: "
              f"{done} of {len(steps)} steps done.")
    if troubles:
        report += " " + "; ".join(troubles[:3]) + ("; and more." if len(troubles) > 3 else ".")
    for s in steps:  # what the user asked to be told ("...then read me my agenda")
        if s["tell"] and s["state"] == "done" and s["result"].strip():
            report += f" {s['say']}: {' '.join(s['result'].split())[:_TOLD_CHARS]}"
    if errand.get("gemini_rescues"):
        report += f" The local model needed Gemini's help on {errand['gemini_rescues']} step(s)."
    errand["report"] = report
    sebas_actions.log("errand", report, ok=not troubles)
    _show()
    if not stopped:  # the user who stopped it has already been answered
        _tell(report)


def running() -> bool:
    return _errand is not None and _errand["state"] == "running"


def begin(title: str, plan: list[dict[str, Any]], engine: str, source: list[dict[str, Any]]) -> dict[str, Any]:
    """Start the runner thread. ``source`` is the plan as given, kept so it can be saved by name."""
    global _errand
    with _lock:
        if running():
            raise ToolError(f"The errand '{_errand['title']}' is still under way. One errand at a time.")
        _errand = errand = {"title": title, "steps": plan, "engine": engine, "state": "running",
                            "started": time.time(), "source": source}
    _show()
    errand["thread"] = threading.Thread(target=_run, args=(errand,), name="sebas-errand", daemon=True)
    errand["thread"].start()
    return errand


def launch(title: str, steps: list[dict[str, Any]], engine_wish: str = "auto") -> str:
    """Validate, choose who thinks, and either start or (for a risky plan) ask first."""
    global _parked
    if running():
        raise ToolError(f"The errand '{_errand['title']}' is still under way. One errand at a time.")
    plan = check_plan(title, steps)
    title = " ".join(title.split())
    engine, note = choose_engine(plan, engine_wish)
    risky = _risky_steps(plan)
    if risky:
        _parked = {"title": title, "plan": plan, "engine": engine, "source": steps}
        listing = "; ".join(f"{n}. {s['say']}" for n, s in enumerate(plan, 1))
        summary = (f"Carry out the errand '{title}' ({len(plan)} steps: {listing}). It includes "
                   f"{', '.join(s['say'] for s in risky)}, which cannot easily be undone.")
        def settled(outcome: str, _text: str, _ok: bool) -> None:
            global _parked
            if outcome != "yes":  # declined, lapsed, or he spoke of something else: the plan is dropped
                _parked = None

        return sebas_actions.request("errand_go", {}, summary, settled) + (f" Also tell him: {note}" if note else "")
    begin(title, plan, engine, steps)
    return (f"The errand '{title}' has begun: {len(plan)} steps, running in the background, shown as a checklist on "
            f"the interface. The user will be told when it finishes. {note}").strip()


@ToolRegistry.register("errand_go")
class ErrandGoTool(SebasTool):
    """Internal: releases a parked plan once the user has said yes. Not offered to the model."""

    name = "errand_go"
    description = "Start the errand the user has just approved."

    def run(self) -> str:
        global _parked
        parked, _parked = _parked, None
        if parked is None:
            raise ToolError("There is no errand waiting to start.")
        begin(parked["title"], parked["plan"], parked["engine"], parked["source"])
        return f"The errand '{parked['title']}' has begun; I shall report when it is finished."


# --------------------------------------------------------------------------- tools

@ToolRegistry.register("start_errand")
class StartErrandTool(SebasTool):
    name = "start_errand"
    acts_on_laptop = True
    timeout_seconds = 60.0
    description = (
        "Carry out a request that needs several of your tools, in the background, as one errand with a visible "
        "checklist ('prepare me for the DBMS exam on the 20th', 'wrap up for the day'). Give the whole plan at "
        f"once: up to {MAX_STEPS} steps, in order, each naming one of your other tools and its arguments. When a "
        "step's arguments depend on an earlier step's result (such as a file found by a search), leave them out "
        "and put how to work them out in 'decide'. Use this whenever the request has three or more actions, or the "
        "actions must happen in order ('..., then read me my agenda'): tools you call together in one turn run at "
        "the same moment, in no fixed order, so a later one cannot see an earlier one's effect. For one or two "
        "independent actions, just call the tools. Returns at once."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "A short name for the errand, three to six words."},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "say": {"type": "string", "description": "What this step does, in a few words, for the checklist."},
                        "tool": {"type": "string", "description": "The name of one of your tools."},
                        "args": {"type": "string", "description": "The tool's arguments as a JSON object in a string, e.g. {\"task\": \"Revise joins\", \"due\": \"2026-11-18\"}."},
                        "decide": {"type": "string", "description": "Only if arguments depend on earlier results: how to work them out, e.g. 'path = the DBMS notes file found in step 1'."},
                        "tell": {"type": "boolean", "description": "true if the user asked to be told this step's result ('...then read me my agenda'); it is read out in the final report."},
                    },
                    "required": ["say", "tool"],
                },
            },
            "engine": {"type": "string", "enum": ["auto", "local", "gemini"],
                       "description": "Leave as auto unless the user asks for the local model or for Gemini."},
        },
        "required": ["title", "steps"],
    }

    def run(self, title: str, steps: list[dict[str, Any]], engine: str = "auto") -> str:
        return launch(title, steps, engine)


@ToolRegistry.register("errand")
class ErrandTool(SebasTool):
    name = "errand"

    def execute(self, **params: Any):
        # From Discord, only carrying an errand out needs the yes; asking after one does not.
        self.acts_on_laptop = params.get("action") == "run"
        return super().execute(**params)

    description = (
        "Errands, other than starting a new one. action 'status': how the current or last errand went, with each "
        "step's result. 'stop': stop the running errand. 'save': keep the last errand's plan under a name ('save "
        "that as my evening wrap-up'). 'run': carry out a saved errand by name. 'list': the saved errands. "
        "'forget': delete a saved errand."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "stop", "save", "run", "list", "forget"]},
            "name": {"type": "string", "description": "The saved errand's name (save, run, forget)."},
            "engine": {"type": "string", "enum": ["auto", "local", "gemini"], "description": "For run; normally auto."},
        },
        "required": ["action"],
    }

    def run(self, action: str, name: str = "", engine: str = "auto") -> str:
        if action == "status":
            return _status()
        if action == "stop":
            e = _errand
            if not running():
                raise ToolError("No errand is running.")
            e["state"] = "stopped"
            return (f"The errand '{e['title']}' will stop once its current step ends; "
                    f"{sum(s['state'] == 'done' for s in e['steps'])} of {len(e['steps'])} steps are done.")
        if action == "list":
            saved = load(_FILE)
            if not saved:
                return "No errands have been saved."
            return "\n".join(f"- {s['name']}: {len(s['steps'])} steps ({'; '.join(x.get('say', x['tool']) for x in s['steps'][:4])}...)"
                             for s in saved)
        name = " ".join((name or "").split())
        if not name:
            raise ToolError("Which saved errand? Give its name.")
        if action == "save":
            if _errand is None:
                raise ToolError("There is no errand to save yet; carry one out first.")
            saved = [s for s in load(_FILE) if s["name"].lower() != name.lower()]
            saved.append({"name": name, "title": _errand["title"], "steps": _errand["source"],
                          "saved": datetime.now().isoformat(timespec="minutes")})
            save(_FILE, saved)
            return f"Saved as '{name}': {len(_errand['source'])} steps. Say 'run my {name}' to carry it out again."
        saved = load(_FILE)
        if not saved:
            raise ToolError("No errands have been saved.")
        best = max(saved, key=lambda s: SequenceMatcher(None, name.lower(), s["name"].lower()).ratio()
                   + (0.4 if name.lower() in s["name"].lower() else 0))
        if SequenceMatcher(None, name.lower(), best["name"].lower()).ratio() < 0.5 and name.lower() not in best["name"].lower():
            raise ToolError(f"No saved errand matches '{name}'. Saved: {', '.join(s['name'] for s in saved)}.")
        if action == "forget":
            save(_FILE, [s for s in saved if s is not best])
            return f"Forgotten: '{best['name']}'."
        if action == "run":
            return launch(best["title"], best["steps"], engine)
        raise ToolError("Action must be status, stop, save, run, list or forget.")


def _status() -> str:
    e = _errand
    if e is None:
        return "No errand has been carried out since Sebas was last opened." + (
            " One is waiting for the user's yes." if _parked else "")
    lines = [f"Errand '{e['title']}': {e['state']}" + (f", thinking on the {e['engine']} model" if any(s['decide'] for s in e['steps']) else "") + "."]
    for n, s in enumerate(e["steps"], 1):
        lines.append(f"{n}. {s['say']} [{s['state']}]" + (f": {' '.join(s['result'].split())[:400]}" if s["result"] else ""))
    return "\n".join(lines)
