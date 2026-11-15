"""The coding delegate: "Sebas, have Claude fix the failing test in the sebas project".

Sebas does not write code himself. He prepares the ground, hands the task to a
coding agent, and reports back:

1. The project must be listed under [projects] in laptop.toml, be a git
   repository, and have no uncommitted changes (so the agent's work never mixes
   with the user's own).
2. He creates the branch ``sebas/<task>`` and starts Claude Code headless there,
   in the background. Claude may edit files and run only the test, lint and build
   commands listed under [coding] in laptop.toml, plus read-only git. Committing
   and pushing are refused. One job at a time, with a time limit.
3. When Claude finishes he says so (and Discord's #alerts hears it too), with a
   two-sentence summary and the number of files changed. The full report is
   saved in ~/.openjarvis/sebas/coding/. Nothing is committed: the user reviews
   the branch.

If Claude Code cannot be used (not installed, not signed in, out of usage, or it
fails before changing any file), the task goes to Antigravity's agent instead,
through ``antigravity-ide chat --mode agent``. That agent works inside the IDE
window under its own approval settings: Sebas cannot restrict its commands, and
it gives no signal when it is done, so he reports once the project's files have
been still for three minutes.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil
from openjarvis.core.paths import get_data_dir
from openjarvis.core.registry import ToolRegistry

import sebas_actions
from custom_tools import laptop
from custom_tools._base import SebasTool, ToolError
from custom_tools.laptop import _choice_param, _lookup, _section

logger = logging.getLogger("sebas.coding")

DEFAULT_COMMANDS = [
    "pytest", "python -m pytest", "python -m unittest", "npm test", "npm run test", "npm run build",
    "npm run lint", "npx tsc", "cargo test", "cargo build", "cargo check", "go test", "go build", "go vet",
]
_READ_ONLY_GIT = ["git status", "git diff", "git log", "git show"]
_REFUSED = ["git commit", "git push", "git switch", "git checkout", "git reset", "git merge", "git rebase", "git stash"]
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_QUIET_SECONDS = 180        # Antigravity: files unchanged this long means "finished"
_POLL_SECONDS = 20
_IDLE_START_SECONDS = 600   # Antigravity: no file touched in this long means it is waiting in the IDE

_lock = threading.Lock()
_job: dict[str, Any] | None = None  # the running job, or the last one


# --------------------------------------------------------------------------- settings and git

def _minutes() -> float:
    return float(_section("coding").get("minutes", 20))


def _allowed_commands() -> list[str]:
    return [str(c) for c in _section("coding").get("allowed_commands", DEFAULT_COMMANDS)]


def _git(folder: Path, *args: str, check: bool = True) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60, creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolError(f"git could not run in {folder}: {exc}") from exc
    if check and done.returncode != 0:
        raise ToolError(f"git {' '.join(args)} failed: {(done.stderr or done.stdout).strip()[:300]}")
    return done.stdout.rstrip()  # not strip(): the first line of `git status --porcelain` may begin with a space


def _changes(folder: Path) -> list[str]:
    """Files that differ from the last commit, tracked or new."""
    return [line[3:].strip().strip('"') for line in _git(folder, "status", "--porcelain").splitlines() if line.strip()]


def _slug(task: str) -> str:
    words = re.findall(r"[a-z0-9]+", task.lower())
    skip = {"the", "a", "an", "in", "on", "of", "to", "my", "please", "and", "for", "project"}
    return "-".join([w for w in words if w not in skip][:5])[:40].strip("-") or "task"


def _new_branch(folder: Path, task: str) -> str:
    existing = set(_git(folder, "branch", "--format=%(refname:short)").split())
    name = base = f"sebas/{_slug(task)}"
    n = 2
    while name in existing:
        name, n = f"{base}-{n}", n + 1
    return name


def prepare(project: str) -> tuple[Path, str]:
    """Check the project is fit for unattended work. Returns its folder and current branch."""
    folder = Path(str(_lookup("projects", project))).expanduser()
    if not folder.is_dir():
        raise ToolError(f"The folder for {project} does not exist: {folder}")
    if _git(folder, "rev-parse", "--is-inside-work-tree", check=False) != "true":
        raise ToolError(f"{project} is not a git repository, so the work could not be kept apart on a branch.")
    base = _git(folder, "branch", "--show-current")
    if not base:
        raise ToolError(f"{project} is not on a branch at the moment (detached HEAD); switch to one first.")
    dirty = _changes(folder)
    if dirty:
        raise ToolError(
            f"{project} has {len(dirty)} uncommitted changes ({', '.join(dirty[:3])}). Commit or stash them first, "
            "so the agent's work stays separate from the user's own.")
    return folder, base


# --------------------------------------------------------------------------- the agents

def _brief(task: str, branch: str) -> str:
    return (
        "You are working unattended, on behalf of the user, at the request of their voice assistant. "
        "Nobody can answer questions or approve anything: do not ask, make the most reasonable choice and note it.\n\n"
        f"Task: {task}\n\n"
        f"Rules: you are on the git branch {branch}, created for this task. Do not commit, push, switch branches, "
        "or touch anything outside this folder; leave your changes uncommitted for review. You may run the "
        "project's test, lint and build commands; if a command is refused, carry on without it and say so.\n\n"
        "When you have finished, end your reply with a line beginning 'SPOKEN:' followed by two short, plain "
        "sentences (no markdown, no file paths) saying what you did and whether the tests pass. It will be read aloud."
    )


def claude_command() -> list[str] | None:
    """The headless Claude Code command, or None if it is not installed."""
    exe = shutil.which("claude")
    if not exe:
        return None
    allowed = ["Read", "Edit", "Write", "Glob", "Grep"] + [f"Bash({c} *)" for c in _allowed_commands() + _READ_ONLY_GIT]
    allowed += [f"Bash({c})" for c in _allowed_commands() + _READ_ONLY_GIT]  # the bare command, with no arguments
    # The user's own Claude Code settings may allow every command (they are for
    # attended work). An unattended job must not inherit that: load no settings
    # files, offer only these tools (so no PowerShell, web or sub-agents), and
    # let nothing that would need approval through.
    return [exe, "-p", "--permission-mode", "acceptEdits", "--output-format", "json",
            "--setting-sources", "", "--strict-mcp-config", "--tools", "Read,Edit,Write,Glob,Grep,Bash",
            "--allowedTools", ",".join(allowed),
            "--disallowedTools", ",".join(f"Bash({c} *)" for c in _REFUSED)]


def antigravity_command(prompt: str) -> list[str] | None:
    """Antigravity's own launcher script sets ELECTRON_RUN_AS_NODE and runs cli.js;
    doing the same directly keeps the prompt out of cmd.exe's quoting rules."""
    editor = Path(str(_section("coding").get("antigravity") or _section("workspace").get("editor", "")))
    cli = editor.parent / "resources" / "app" / "out" / "cli.js"
    if not editor.is_file() or not cli.is_file():
        return None
    return [str(editor), str(cli), "chat", "--mode", "agent", prompt]


def _child_env(**extra: str) -> dict[str, str]:
    # Sebas may himself have been started from a Claude Code terminal; a child
    # must not think it is part of that session.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CLAUDE_", "CLAUDECODE"))}
    env.update(extra)
    return env


def _kill(proc: subprocess.Popen) -> None:
    try:
        parent = psutil.Process(proc.pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
    except psutil.Error:
        pass


def _read_result(stdout: str) -> tuple[bool, str]:
    """(succeeded, the agent's final reply) from Claude Code's JSON output."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return bool(stdout.strip()), stdout.strip()
    if isinstance(data, list):  # some versions print the whole event list
        data = next((d for d in reversed(data) if isinstance(d, dict) and d.get("type") == "result"), {})
    return not data.get("is_error", False), str(data.get("result") or "").strip()


def _spoken(reply: str) -> str:
    found = re.search(r"SPOKEN:\s*(.+)", reply, re.DOTALL)
    text = " ".join((found.group(1) if found else reply).split())
    return re.sub(r"[*_`#]", "", text)[:400]


# --------------------------------------------------------------------------- running a job

def _tell(text: str) -> None:
    import sebas_calls  # mid-call it would be spoken into the call: it waits

    sebas_calls.DESK.hold_or_say(laptop._announce, text)


def _files_phrase(n: int) -> str:
    return "No files were changed" if n == 0 else f"{n} file{'s' if n != 1 else ''} changed"


def _save_report(job: dict[str, Any], reply: str) -> None:
    folder = get_data_dir() / "sebas" / "coding"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{datetime.now():%Y-%m-%d-%H%M}-{job['branch'].split('/')[-1]}.md"
        stat = _git(job["folder"], "status", "--short", check=False)
        path.write_text(
            f"# {job['task']}\n\nProject: {job['project']} ({job['folder']})\nBranch: {job['branch']} (from {job['base']})\n"
            f"Agent: {job['agent']}\nOutcome: {job['state']}\n\n## Changed files\n\n{stat or '(none)'}\n\n## The agent's report\n\n{reply}\n",
            "utf-8")
        job["report"] = str(path)
    except (OSError, ToolError):
        logger.exception("Could not save the coding report")


def _finish(job: dict[str, Any], state: str, sentence: str, reply: str = "") -> None:
    job["state"], job["summary"], job["ended"] = state, sentence, time.time()
    _save_report(job, reply)
    sebas_actions.log("delegate_coding", f"{job['agent']} on {job['project']} ({job['branch']}): {state}. {sentence}",
                      ok=state == "done")
    _tell(sentence)


def _run_claude(job: dict[str, Any], command: list[str]) -> None:
    brief = _brief(job["task"], job["branch"])
    try:
        proc = subprocess.Popen(command, cwd=job["folder"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                env=_child_env(), creationflags=_NO_WINDOW)
    except OSError as exc:
        return _fall_back(job, f"Claude Code could not start ({exc})")
    job["proc"] = proc
    try:
        stdout, stderr = proc.communicate(brief, timeout=_minutes() * 60)
    except subprocess.TimeoutExpired:
        _kill(proc)
        n = len(_changes(job["folder"]))
        return _finish(job, "timeout", f"Sir, Claude ran out of time on {job['project']} after {_minutes():.0f} minutes and "
                       f"was stopped. {_files_phrase(n)} so far, on the branch {job['branch']}.")
    if job["state"] == "stopped":  # "stop Claude": already reported
        return
    ok, reply = _read_result(stdout)
    changed = len(_changes(job["folder"]))
    if proc.returncode != 0 or not ok:
        reason = " ".join((reply or stderr or "no explanation").split())[:200]
        if changed == 0:
            return _fall_back(job, f"Claude Code could not do it ({reason})")
        return _finish(job, "failed", f"Sir, Claude stopped with an error part-way through {job['project']}: {reason} "
                       f"{_files_phrase(changed)} on the branch {job['branch']}.", reply or stderr)
    _finish(job, "done", f"Sir, Claude has finished in {job['project']}. {_spoken(reply)} "
            f"{_files_phrase(changed)} on the branch {job['branch']}, left uncommitted for your review.", reply)


def _fall_back(job: dict[str, Any], why: str) -> None:
    """Claude Code is unavailable: hand the task to Antigravity's agent in the IDE."""
    command = antigravity_command(_brief(job["task"], job["branch"]))
    if command is None:
        return _finish(job, "failed", f"Sir, {why}, and Antigravity was not found to take over. Nothing was changed; "
                       f"the empty branch {job['branch']} remains.")
    job["agent"] = "Antigravity"
    try:
        subprocess.Popen(command, cwd=job["folder"], env=_child_env(ELECTRON_RUN_AS_NODE="1"), creationflags=_NO_WINDOW,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        return _finish(job, "failed", f"Sir, {why}, and Antigravity could not start either ({exc}). Nothing was changed.")
    _tell(f"Sir, {why}, so I have passed the task to Antigravity's agent instead. It works in the editor window "
          "under its own approval settings; I shall tell you when the files have settled.")
    _watch_until_quiet(job)


def _signature(folder: Path) -> tuple[str, ...]:
    """Which files differ from the last commit, and when each was last written."""
    marks = []
    for name in _changes(folder):
        try:
            marks.append(f"{name}@{(folder / name).stat().st_mtime_ns}")
        except OSError:
            marks.append(f"{name}@gone")
    return tuple(marks)


def _watch_until_quiet(job: dict[str, Any]) -> None:
    started = last_change = time.monotonic()
    seen: tuple[str, ...] = ()
    while job["state"] == "running":
        time.sleep(_POLL_SECONDS)
        now = time.monotonic()
        try:
            current = _signature(job["folder"])
        except ToolError:
            continue
        if current != seen:
            seen, last_change = current, now
        elif seen and now - last_change >= _QUIET_SECONDS:
            return _finish(job, "done", f"Sir, Antigravity's agent appears to have finished in {job['project']}: "
                           f"{_files_phrase(len(seen)).lower()} on the branch {job['branch']}, and nothing has moved for "
                           "three minutes. Do look it over in the editor.")
        elif not seen and now - started >= _IDLE_START_SECONDS:
            return _finish(job, "failed", f"Sir, Antigravity's agent has not changed any file in {job['project']} in ten "
                           "minutes. It may be waiting for you in the editor window.")
        elif now - started >= _minutes() * 60:
            return _finish(job, "timeout", f"Sir, Antigravity's agent is still at work in {job['project']} after "
                           f"{_minutes():.0f} minutes, so I have stopped watching. {_files_phrase(len(seen))} so far.")


def running() -> bool:
    return _job is not None and _job["state"] == "running"


def start(project: str, task: str) -> dict[str, Any]:
    """Create the branch and start the agent in the background."""
    global _job
    task = " ".join((task or "").split())
    if len(task) < 8:
        raise ToolError("The task is too brief to hand to a coding agent; ask the user what exactly should be done.")
    with _lock:
        if running():
            raise ToolError(f"{_job['agent']} is still working on '{_job['task']}' in {_job['project']}. One job at a time.")
        folder, base = prepare(project)
        branch = _new_branch(folder, task)
        _git(folder, "switch", "-c", branch)
        command = claude_command()
        _job = job = {"project": project, "folder": folder, "task": task, "branch": branch, "base": base,
                      "agent": "Claude", "claude": command is not None, "state": "running",
                      "started": time.time(), "summary": ""}
    if command is None:
        target, args = _fall_back, (job, "Claude Code is not installed")
    else:
        target, args = _run_claude, (job, command)
    job["thread"] = threading.Thread(target=_guarded, args=(target, job, *args[1:]), name="sebas-coding", daemon=True)
    job["thread"].start()
    return job


def _guarded(target, job: dict[str, Any], *args: Any) -> None:
    try:
        target(job, *args)
    except Exception as exc:  # the user must hear about it either way
        logger.exception("The coding job failed")
        if job["state"] == "running":
            _finish(job, "failed", f"Sir, the coding job in {job['project']} failed unexpectedly: {type(exc).__name__}. "
                    f"The branch {job['branch']} remains.")


def snapshot() -> dict[str, str] | None:
    """For the interface: the running job as a row."""
    job = _job
    if job is None or job["state"] != "running":
        return None
    minutes = int((time.time() - job["started"]) / 60)
    return {"label": f"{job['agent']} · {job['task'][:60]}", "detail": f"working · {minutes} min"}


# --------------------------------------------------------------------------- tools

@ToolRegistry.register("delegate_coding")
class DelegateCodingTool(SebasTool):
    name = "delegate_coding"
    acts_on_laptop = True
    timeout_seconds = 90.0
    description = (
        "Hand a coding task in one of the user's projects to a coding agent (Claude Code; Antigravity if "
        "Claude is unavailable): 'have Claude fix the failing test in sebas'. It works in the background on a "
        "new branch and never commits; the user is told when it finishes. Returns at once. If the user did "
        "not say which project, ask before calling this."
    )

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project": _choice_param("projects", "Which project."),
                "task": {"type": "string", "description": "The task in full, with every detail the user gave."},
            },
            "required": ["project", "task"],
        }

    def run(self, project: str, task: str) -> str:
        job = start(project, task)
        agent = "Claude Code is" if job["claude"] else \
            "Claude Code is not installed, so Antigravity's agent is"
        return (f"Started. {agent} working on it in {project}, on the new branch {job['branch']} "
                f"(the user was on {job['base']}). It may take up to {_minutes():.0f} minutes and the user will be "
                "told when it finishes; nothing will be committed.")


@ToolRegistry.register("coding_status")
class CodingStatusTool(SebasTool):
    name = "coding_status"
    description = "How the coding agent's job is going, or what the last one changed."

    def run(self) -> str:
        job = _job
        if job is None:
            return "No coding job has been started since Sebas was last opened."
        files = _changes(job["folder"]) if job["folder"].is_dir() else []
        listed = ", ".join(files[:8]) + ("..." if len(files) > 8 else "") if files else "none"
        if job["state"] == "running":
            minutes = (time.time() - job["started"]) / 60
            return (f"{job['agent']} has been working on '{job['task']}' in {job['project']} for {minutes:.0f} minutes, "
                    f"on the branch {job['branch']}. Files changed so far: {listed}.")
        return (f"The last job, '{job['task']}' in {job['project']} by {job['agent']}, ended as: {job['state']}. "
                f"{job['summary']} Files differing from the last commit now: {listed}. "
                f"Full report: {job.get('report', 'not saved')}.")


@ToolRegistry.register("stop_coding")
class StopCodingTool(SebasTool):
    name = "stop_coding"
    description = "Stop the coding agent's running job. What it has changed so far stays on its branch."

    def run(self) -> str:
        job = _job
        if job is None or job["state"] != "running":
            raise ToolError("No coding job is running.")
        job["state"] = "stopped"
        if job["agent"] == "Claude" and job.get("proc") is not None:
            _kill(job["proc"])
            note = "Claude has been stopped."
        else:
            note = ("I have stopped watching; Antigravity's agent runs inside the editor and must be "
                    "stopped there.")
        n = len(_changes(job["folder"]))
        job["summary"] = f"Stopped at the user's request. {_files_phrase(n)} on the branch {job['branch']}."
        _save_report(job, "")
        sebas_actions.log("stop_coding", f"{job['project']} ({job['branch']})")
        return f"{note} {_files_phrase(n)} so far, on the branch {job['branch']}."


@ToolRegistry.register("discard_coding")
class DiscardCodingTool(SebasTool):
    name = "discard_coding"
    risky = True
    description = (
        "Throw away what the coding agent did in its last job: return the project to the branch the user "
        "was on and delete the agent's branch. Cannot be undone."
    )

    def confirm_summary(self, **params: Any) -> str:
        job = _job
        if job is None:
            return "Discard the coding agent's last job."
        return (f"Discard everything on the branch {job['branch']} in {job['project']}, return to {job['base']}, "
                "and delete that branch. It cannot be undone.")

    def run(self) -> str:
        job = _job
        if job is None:
            raise ToolError("There is no coding job to discard.")
        if job["state"] == "running":
            raise ToolError("The job is still running; stop it first.")
        folder = job["folder"]
        if _git(folder, "branch", "--show-current") != job["branch"]:
            raise ToolError(f"{job['project']} is no longer on {job['branch']}, so I have left it alone.")
        _git(folder, "reset", "--hard")
        _git(folder, "clean", "-fd")
        _git(folder, "switch", job["base"])
        _git(folder, "branch", "-D", job["branch"])
        job["state"] = "discarded"
        return f"Discarded. {job['project']} is back on {job['base']}, and the branch {job['branch']} is gone."
