"""Sebas's reasoning: Claude when available, a local Ollama model otherwise.

Claude is used when ANTHROPIC_API_KEY is set and the API is reachable. With no
key, or when offline, Sebas runs on the best installed local model, and moves
back to Claude once the connection returns.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from urllib.parse import urlparse

import httpx

from sebas_events import emit

logger = logging.getLogger("sebas")

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
# Best first, from the benchmark of Sebas's own tasks on this laptop (see README).
LOCAL_MODEL_PREFERENCE = ["qwen2.5:latest", "llama3.1:8b", "llama3.2:latest"]
_MAX_HISTORY_MESSAGES = 20
_CLOUD_RETRY_SECONDS = 300
_LOCAL_CONTEXT_TOKENS = "8192"


def anthropic_reachable(timeout: float = 2.5) -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    url = urlparse(os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com")
    try:
        with socket.create_connection(
            (url.hostname, url.port or (443 if url.scheme == "https" else 80)), timeout
        ):
            return True
    except OSError:
        return False


def _ollama_up() -> bool:
    try:
        return httpx.get(f"{OLLAMA_URL}/api/version", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def ensure_ollama() -> None:
    """Start the Ollama server if it is installed but not running."""
    if _ollama_up():
        return
    exe = shutil.which("ollama") or os.path.expandvars(
        r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
    )
    if not os.path.exists(exe):
        raise RuntimeError("Ollama is not installed, so no local model is available.")
    subprocess.Popen(
        [exe, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    for _ in range(30):
        if _ollama_up():
            return
        time.sleep(0.5)
    raise RuntimeError("The Ollama server did not start.")


def _tool_models() -> dict[str, int]:
    """Installed models that support tool calling, with their size in bytes."""
    tags = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=10).json().get("models", [])
    found = {}
    for tag in tags:
        info = httpx.post(f"{OLLAMA_URL}/api/show", json={"model": tag["name"]}, timeout=10).json()
        if "tools" in info.get("capabilities", []):
            found[tag["name"]] = int(tag.get("size", 0))
    return found


def choose_local_model() -> str:
    """SEBAS_LOCAL_MODEL if set, else the best-ranked installed model."""
    if chosen := os.environ.get("SEBAS_LOCAL_MODEL", "").strip():
        return chosen
    ensure_ollama()
    available = _tool_models()
    if not available:
        raise RuntimeError(
            "No installed Ollama model supports tool calling. "
            "Try: ollama pull qwen2.5"
        )
    for name in LOCAL_MODEL_PREFERENCE:
        if name in available:
            return name
    return max(available, key=available.get)  # unranked: the largest is usually best


def is_connection_error(exc: BaseException) -> bool:
    """True when ``exc`` (or its cause) means the cloud API could not be reached."""
    names = {"APIConnectionError", "APITimeoutError", "EngineConnectionError", "ConnectError", "ConnectTimeout"}
    while exc is not None:
        if type(exc).__name__ in names or isinstance(exc, (httpx.TransportError, OSError)):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


class Brain:
    """Sends requests to the orchestrator and remembers the conversation."""

    def __init__(self) -> None:
        import custom_tools  # noqa: F401  (registers Sebas's tools)

        self._history: list = []
        self._systems: dict[str, object] = {}
        self._cloud_retry_at = 0.0
        self._lock = threading.RLock()  # one request at a time, warm-up included
        self.local_model = ""
        if anthropic_reachable():
            self.mode = "cloud"
        else:
            self.mode = "local"
            reason = "no ANTHROPIC_API_KEY" if not os.environ.get("ANTHROPIC_API_KEY") else "Claude is unreachable"
            self._use_local(reason, warm_up=True)

    def _use_local(self, reason: str, warm_up: bool = False) -> None:
        first_time = not self.local_model
        if first_time:
            self.local_model = choose_local_model()
        self.mode = "local"
        self._cloud_retry_at = time.monotonic() + _CLOUD_RETRY_SECONDS
        print(f"[{reason}: using local model {self.local_model}]", flush=True)
        emit("mode", mode="local", model=self.local_model)
        emit("notice", text=f"{reason[0].upper()}{reason[1:]}: thinking with {self.local_model}.")
        if first_time:
            threading.Thread(target=self._keep_local_ready, args=(warm_up,), daemon=True).start()

    def _keep_local_ready(self, warm_up: bool) -> None:
        """Preload the local model and keep it in memory while it is in use.

        On a laptop CPU the first request otherwise takes minutes: the model
        loads from disk and Sebas's long system prompt (persona plus tool
        definitions) is processed from scratch. One throwaway request through
        the same prompt leaves it cached for the first real one, and periodic
        pings stop Ollama unloading the model after its default 5 minutes idle.
        """
        if warm_up:
            try:
                with self._lock:
                    self._system().ask("Reply with one word: ready.", agent="orchestrator")
            except Exception as exc:
                logger.warning("Warming up %s failed: %s", self.local_model, exc)
        while True:
            time.sleep(240)
            if self.mode != "local":
                continue
            try:
                httpx.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={"model": self.local_model, "keep_alive": "10m"},
                    timeout=600,
                )
            except httpx.HTTPError as exc:
                logger.debug("Keep-alive for %s failed: %s", self.local_model, exc)

    @property
    def description(self) -> str:
        if self.mode == "cloud":
            return "Claude"
        return f"local model {self.local_model} via Ollama"

    def _system(self):
        if self.mode not in self._systems:
            from openjarvis.system.builder import SystemBuilder

            # speech(False): voice_pipeline has its own Whisper; OpenJarvis's
            # would load a second copy into memory.
            builder = SystemBuilder().agent("orchestrator").speech(False)
            if self.mode == "cloud":
                builder = builder.engine("cloud")
            else:
                os.environ.setdefault("JARVIS_NUM_CTX", _LOCAL_CONTEXT_TOKENS)
                builder = builder.engine("ollama").model(self.local_model)
            system = builder.build()
            self._forward_tool_events(system)
            self._systems[self.mode] = system
        return self._systems[self.mode]

    @staticmethod
    def _forward_tool_events(system) -> None:
        """Pass the orchestrator's tool calls on to the UI's activity ticker."""
        from openjarvis.core.events import EventType

        def started(event) -> None:
            emit("tool", phase="start", tool=event.data.get("tool", ""))

        def finished(event) -> None:
            emit("tool", phase="end", tool=event.data.get("tool", ""), success=bool(event.data.get("success")))

        system.bus.subscribe(EventType.TOOL_CALL_START, started)
        system.bus.subscribe(EventType.TOOL_CALL_END, finished)

    def _ask_once(self, text: str) -> str:
        # The agent is named explicitly: otherwise OpenJarvis diverts anything
        # containing "good morning" to its separate morning_digest agent.
        result = self._system().ask(text, agent="orchestrator", prior_messages=self._history)
        if result.get("error"):
            raise RuntimeError(result["content"])
        return result["content"]

    def ask(self, text: str) -> str:
        with self._lock:
            return self._ask(text)

    def _ask(self, text: str) -> str:
        from openjarvis.core.types import Message, Role

        # When running locally because Claude was unreachable, check back periodically.
        note = ""
        if (
            self.mode == "local"
            and os.environ.get("ANTHROPIC_API_KEY")
            and time.monotonic() >= self._cloud_retry_at
        ):
            if anthropic_reachable():
                self.mode = "cloud"
                print("[connection restored: using Claude again]", flush=True)
                emit("mode", mode="cloud", model="Claude")
                emit("notice", text="Connection restored: thinking with Claude again.")
            else:
                self._cloud_retry_at = time.monotonic() + _CLOUD_RETRY_SECONDS

        try:
            reply = self._ask_once(text)
        except Exception as exc:
            if self.mode != "cloud" or not is_connection_error(exc):
                raise
            logger.warning("Claude unreachable (%s); switching to the local model", exc)
            self._use_local("Claude is unreachable")
            note = "The connection to Claude has been lost, so I am continuing on the local model. "
            reply = self._ask_once(text)

        if reply:
            self._history += [
                Message(role=Role.USER, content=text),
                Message(role=Role.ASSISTANT, content=reply),
            ]
            del self._history[:-_MAX_HISTORY_MESSAGES]
        return note + reply

    def close(self) -> None:
        for system in self._systems.values():
            system.close()
