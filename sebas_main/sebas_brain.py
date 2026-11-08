"""Sebas's reasoning: Gemini key 1 -> Gemini key 2 -> a local Ollama model.

Each Gemini key is tried in order. A key that runs out of quota is rested
(about a minute for a per-minute limit, until midnight Pacific for a spent
daily quota) and the next one takes over; with no usable key, or offline,
Sebas runs on the best installed local model. Higher-priority providers are
tried again automatically once they have rested.

Note: Gemini quotas belong to the Google Cloud *project*, so the two keys only
help if they come from different projects or accounts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from sebas_events import emit

logger = logging.getLogger("sebas")

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
# Best first, from the benchmark of Sebas's own tasks on this laptop (see README).
LOCAL_MODEL_PREFERENCE = ["qwen2.5:latest", "llama3.1:8b", "llama3.2:latest"]
# Used when the model list cannot be fetched; confirmed GA in the Gemini changelog.
FALLBACK_GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_HOST = "generativelanguage.googleapis.com"
_MAX_HISTORY_MESSAGES = 20
_OFFLINE_RETRY_SECONDS = 300
_RATE_LIMIT_REST_SECONDS = 65
_BAD_KEY_REST_SECONDS = 3600
_LOCAL_CONTEXT_TOKENS = "8192"
_GEMINI_TIMEOUT_MS = 30_000
_LITE_LADDER_SIZE = 3
_MODEL_LADDER_SIZE = 5  # each model has its own free-tier daily quota
_BUSY_REST_SECONDS = 15 * 60  # doubles on each repeat, up to _BUSY_REST_MAX
_BUSY_REST_MAX = 2 * 3600


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def gemini_reachable(timeout: float = 2.5) -> bool:
    try:
        with socket.create_connection((GEMINI_HOST, 443), timeout):
            return True
    except OSError:
        return False


def _version(name: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", name.split("flash")[0])) or (0,)


def choose_gemini_models(api_key: str) -> list[str]:
    """The models to try on a key, best first.

    The newest stable Flash models the key can use, newest first: when the
    newest is overloaded (common for a week or two after a release), the next
    one down usually answers in seconds. SEBAS_GEMINI_MODEL, if set, goes first.
    """
    pinned = os.environ.get("SEBAS_GEMINI_MODEL", "").strip()
    ladder = _stable_flash_models(api_key)[:_MODEL_LADDER_SIZE] or [FALLBACK_GEMINI_MODEL]
    return [pinned] + [m for m in ladder if m != pinned] if pinned else ladder


def choose_lite_models(api_key: str) -> list[str]:
    """Flash-Lite models, newest first: lighter, but with much higher free daily
    limits, so they keep Sebas on Gemini after the Flash quotas are spent."""
    return _stable_flash_models(api_key, lite=True)[:_LITE_LADDER_SIZE]


def _stable_flash_models(api_key: str, lite: bool = False) -> list[str]:
    try:
        from google import genai

        names = []
        # kept alive while the pager is read
        client = genai.Client(api_key=api_key, http_options={"timeout": 15_000})
        for model in client.models.list():
            name = model.name.removeprefix("models/")
            actions = getattr(model, "supported_actions", None) or []
            if "flash" not in name or (actions and "generateContent" not in actions):
                continue
            if ("flash-lite" in name) != lite:
                continue
            if re.search(r"image|tts|live|audio|embed|thinking|exp|preview|latest|\d{3,}$", name):
                continue
            names.append(name)
        return sorted(set(names), key=_version, reverse=True)
    except Exception as exc:
        logger.warning("Could not list Gemini models (%s); using %s", exc, FALLBACK_GEMINI_MODEL)
        return []


def _api_error(exc: BaseException):
    """The google-genai APIError inside ``exc``'s cause chain, if any."""
    while exc is not None:
        if hasattr(exc, "code") and hasattr(exc, "status") and type(exc).__module__.startswith("google"):
            return exc
        exc = exc.__cause__ or exc.__context__
    return None


def _until_pacific_midnight() -> float:
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    return (midnight - now).total_seconds()


def classify_failure(exc: BaseException) -> tuple[str, float] | None:
    """Why a cloud request failed, and how long to rest it.

    Returns ("quota-day" | "quota-minute" | "bad-key" | "busy" | "offline",
    seconds), or None for errors that switching providers would not fix.
    Quota and "busy" apply to one model: free-tier quotas are counted per
    model per project (20 requests a day each, at the time of writing).
    """
    chain = exc
    while chain is not None:  # a slow reply means a busy model, not no internet
        if isinstance(chain, (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
            return "busy", _BUSY_REST_SECONDS
        chain = chain.__cause__ or chain.__context__
    api = _api_error(exc)
    if api is not None:
        text = f"{getattr(api, 'status', '')} {getattr(api, 'message', '')} {getattr(api, 'details', '')}"
        if api.code == 429 or "RESOURCE_EXHAUSTED" in text:
            # Google states when the quota frees up; trust that over our guess.
            delay = re.search(r"retryDelay'?\"?:\s*'?\"?(\d+(?:\.\d+)?)s", text)
            if delay:
                # Trust Google's own retry delay: a per-minute error can also list the
                # daily quota among its details, which once rested models for a day.
                seconds = float(delay.group(1))
                return ("quota-day", seconds) if seconds > 3600 else ("quota-minute", seconds + 2)
            if re.search(r"PerDay|per day", text, re.IGNORECASE) and not re.search(r"PerMinute|per minute", text, re.IGNORECASE):
                return "quota-day", _until_pacific_midnight()
            return "quota-minute", _RATE_LIMIT_REST_SECONDS
        if api.code in (401, 403) or re.search(r"API key|PERMISSION_DENIED|UNAUTHENTICATED", text):
            return "bad-key", _BAD_KEY_REST_SECONDS
        if api.code >= 500:  # 503 high demand, 504 deadline exceeded
            return "busy", _BUSY_REST_SECONDS
        return None
    names = {"ConnectError", "ConnectTimeout", "EngineConnectionError"}
    while exc is not None:
        if type(exc).__name__ in names or isinstance(exc, (httpx.TransportError, socket.gaierror, ConnectionError)):
            return "offline", _OFFLINE_RETRY_SECONDS
        exc = exc.__cause__ or exc.__context__
    return None


# ---------------------------------------------------------------------------
# Local (Ollama)
# ---------------------------------------------------------------------------

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


def choose_local_models() -> list[str]:
    """Installed tool-capable models, best first: the benchmark's ranking, then the
    rest by size. SEBAS_LOCAL_MODEL, if set, goes first."""
    ensure_ollama()
    available = _tool_models()
    pinned = os.environ.get("SEBAS_LOCAL_MODEL", "").strip()
    if not available and not pinned:
        raise RuntimeError(
            "No installed Ollama model supports tool calling. Try: ollama pull qwen2.5"
        )
    ranked = [m for m in LOCAL_MODEL_PREFERENCE if m in available]
    ranked += sorted((m for m in available if m not in ranked), key=available.get, reverse=True)
    return [pinned] + [m for m in ranked if m != pinned] if pinned else ranked


def choose_local_model() -> str:
    return choose_local_models()[0]


def local_model_failed(exc: BaseException) -> bool:
    """True when Ollama could not run the model (often too little free memory)."""
    text = str(exc).lower()
    return any(s in text for s in ("model runner", "resource", "out of memory", "memory", "500"))


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------

@dataclass
class Provider:
    label: str              # shown to the user: "Gemini key 1", "Gemini key 1 (lite)", "local"
    api_key: str = ""       # empty for the local model
    key_number: int = 0
    lite: bool = False      # the Flash-Lite tier of a key
    models: list[str] = field(default_factory=list)  # Gemini ladder, best first; or [local model]
    rested_until: float = 0.0
    busy_until: dict[str, float] = field(default_factory=dict)
    busy_strikes: dict[str, int] = field(default_factory=dict)

    @property
    def is_local(self) -> bool:
        return not self.api_key

    @property
    def model(self) -> str:
        """The best model on this provider that is not resting as overloaded."""
        now = time.monotonic()
        return next((m for m in self.models if self.busy_until.get(m, 0) <= now), "")

    def available(self) -> bool:
        return time.monotonic() >= self.rested_until and (not self.models or bool(self.model))

    def mark_busy(self, model: str) -> None:
        strikes = self.busy_strikes.get(model, 0)
        self.busy_strikes[model] = strikes + 1
        self.busy_until[model] = time.monotonic() + min(_BUSY_REST_SECONDS * 2 ** strikes, _BUSY_REST_MAX)


_REASONS = {
    "quota-day": "has used today's quota",
    "quota-minute": "is being rate-limited",
    "bad-key": "was rejected; please check that key",
    "busy": "has every model overloaded at the moment",
    "offline": "cannot be reached",
}
_MODEL_REASONS = {
    "busy": "is overloaded",
    "quota-day": "has used today's quota",
    "quota-minute": "is rate-limited",
}


class Brain:
    """Sends requests to the orchestrator, remembers the conversation, and
    moves down the provider chain when a provider runs dry."""

    def __init__(self) -> None:
        import custom_tools  # noqa: F401  (registers Sebas's tools)

        self._history: list = []
        self._systems: dict[str, object] = {}
        self._lock = threading.RLock()  # one request at a time, warm-up included
        self._local_ready_started = False
        self._shown: tuple[str, str] | None = None  # (provider, model) last announced

        keys = [os.environ.get("GEMINI_API_KEY", "").strip(), os.environ.get("GEMINI_API_KEY_2", "").strip()]
        # Full Flash on each key first, then each key's Flash-Lite tier (much higher
        # free limits), then the local model.
        numbered = [(i, k) for i, k in enumerate(keys, 1) if k]
        self.providers = [Provider(f"Gemini key {i}", k, key_number=i) for i, k in numbered]
        self.providers += [Provider(f"Gemini key {i} (lite)", k, key_number=i, lite=True) for i, k in numbered]
        self.providers.append(Provider("local"))
        self._restore_spent_models()
        self.current: Provider | None = None

        online = bool(self.providers[:-1]) and gemini_reachable()
        if self.providers[:-1] and not online:
            for p in self.providers[:-1]:
                p.rested_until = time.monotonic() + _OFFLINE_RETRY_SECONDS
        self._select(reason=None if online else ("No Gemini key in .env" if len(self.providers) == 1 else "Offline"))

    # --- daily quotas survive restarts ---------------------------------------
    # A model whose daily quota is spent stays spent until Google's reset, even
    # if Sebas restarts; without this, each restart re-tries it (and fails).
    @staticmethod
    def _spent_path():
        from openjarvis.core.paths import get_data_dir

        return get_data_dir() / "sebas" / "spent_models.json"

    @staticmethod
    def _key_id(api_key: str) -> str:
        return hashlib.sha256(api_key.encode()).hexdigest()[:12]  # never store the key itself

    def _restore_spent_models(self) -> None:
        try:
            spent = json.loads(self._spent_path().read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        now_wall, now_mono = time.time(), time.monotonic()
        for p in self.providers:
            for model, until in spent.get(self._key_id(p.api_key), {}).items() if p.api_key else ():
                if until > now_wall:
                    p.busy_until[model] = now_mono + (until - now_wall)

    def _remember_spent_model(self, provider: Provider, model: str, rest: float) -> None:
        path = self._spent_path()
        try:
            spent = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            spent = {}
        now = time.time()
        spent = {k: {m: u for m, u in v.items() if u > now} for k, v in spent.items()}  # drop expired
        spent.setdefault(self._key_id(provider.api_key), {})[model] = now + rest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(spent, indent=1), "utf-8")

    # --- provider selection ------------------------------------------------
    def _select(self, reason: str | None = None) -> None:
        """Use the highest-priority provider that is not resting."""
        for p in self.providers:
            # Load a key's model list before judging it: with every model on it
            # resting (e.g. yesterday's spent quotas, remembered), it is not usable.
            if not p.is_local and not p.models and time.monotonic() >= p.rested_until:
                p.models = choose_lite_models(p.api_key) if p.lite else choose_gemini_models(p.api_key)
        chosen = next(p for p in self.providers if p.available() or p.is_local)
        if chosen.is_local:
            if not chosen.models:
                chosen.models = choose_local_models()
            self._start_local_keepalive(chosen, warm_up=reason is not None and self.current is None)
        if (chosen.label, chosen.model) == self._shown:
            return
        self._shown = (chosen.label, chosen.model)
        previous, self.current = self.current, chosen
        text = f"{reason}; now thinking with {self.description}." if reason else f"Thinking with {self.description}."
        print(f"[{text}]", flush=True)
        emit("mode", mode="local" if chosen.is_local else "cloud", model=self.short_description)
        if previous is not None or reason:
            emit("notice", text=text)

    @property
    def mode(self) -> str:
        return "local" if self.current.is_local else "cloud"

    @property
    def local_model(self) -> str:
        return self.current.model if self.current.is_local else ""

    @property
    def description(self) -> str:
        p = self.current
        return f"local model {p.model} via Ollama" if p.is_local else f"{p.model} ({p.label})"

    @property
    def short_description(self) -> str:
        p = self.current
        return p.model if p.is_local else f"{p.model} · key {p.key_number}"

    # --- building the orchestrator per provider ------------------------------
    def _system(self, provider: Provider):
        cache_key = f"{provider.label}|{provider.model}"
        if cache_key not in self._systems:
            from openjarvis.system.builder import SystemBuilder

            # speech(False): voice_pipeline has its own Whisper; OpenJarvis's
            # would load a second copy into memory.
            builder = SystemBuilder().agent("orchestrator").speech(False)
            if provider.is_local:
                os.environ.setdefault("JARVIS_NUM_CTX", _LOCAL_CONTEXT_TOKENS)
                builder = builder.engine("ollama").model(provider.model)
            else:
                from google import genai
                from openjarvis.engine.cloud import CloudEngine

                engine = CloudEngine()
                # Each key gets its own client; CloudEngine would otherwise read
                # only GEMINI_API_KEY from the environment. The timeout matters:
                # google-genai has none by default, so a stalled response would
                # hang Sebas forever instead of falling back down the chain.
                engine._google_client = genai.Client(
                    api_key=provider.api_key,
                    http_options={"timeout": _GEMINI_TIMEOUT_MS},
                )
                builder = builder.engine_instance(engine, key="cloud").model(provider.model)
            system = builder.build()
            self._forward_tool_events(system)
            self._systems[cache_key] = system
        return self._systems[cache_key]

    _forwarded_buses: set[int] = set()

    @classmethod
    def _forward_tool_events(cls, system) -> None:
        """Pass the orchestrator's tool calls on to the UI's activity ticker.

        Systems built for different models can share one event bus; subscribing
        it again would repeat every event (and every #ledger post).
        """
        from openjarvis.core.events import EventType

        if id(system.bus) in cls._forwarded_buses:
            return
        cls._forwarded_buses.add(id(system.bus))

        def started(event) -> None:
            emit("tool", phase="start", tool=event.data.get("tool", ""))

        def finished(event) -> None:
            emit("tool", phase="end", tool=event.data.get("tool", ""), success=bool(event.data.get("success")),
                 result=str(event.data.get("result", ""))[:500])

        system.bus.subscribe(EventType.TOOL_CALL_START, started)
        system.bus.subscribe(EventType.TOOL_CALL_END, finished)

    # --- local model upkeep --------------------------------------------------
    def _start_local_keepalive(self, provider: Provider, warm_up: bool) -> None:
        if self._local_ready_started:
            return
        self._local_ready_started = True
        threading.Thread(target=self._keep_local_ready, args=(provider, warm_up), daemon=True).start()

    def _keep_local_ready(self, provider: Provider, warm_up: bool) -> None:
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
                    self._system(provider).ask("Reply with one word: ready.", agent="orchestrator")
            except Exception as exc:
                logger.warning("Warming up %s failed: %s", provider.model, exc)
        while True:
            time.sleep(240)
            if self.current is not provider:
                continue
            try:
                httpx.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={"model": provider.model, "keep_alive": "10m"},
                    timeout=600,
                )
            except httpx.HTTPError as exc:
                logger.debug("Keep-alive for %s failed: %s", provider.model, exc)

    # --- asking -------------------------------------------------------------
    def _ask_once(self, provider: Provider, text: str) -> str:
        # The agent is named explicitly: otherwise OpenJarvis diverts anything
        # containing "good morning" to its separate morning_digest agent.
        # The model has no clock: give it one, so "by Friday" becomes a date.
        stamped = f"[Now: {datetime.now().strftime('%A %d %B %Y, %I:%M %p')}] {text}"
        result = self._system(provider).ask(stamped, agent="orchestrator", prior_messages=self._history)
        if result.get("error"):
            raise RuntimeError(result["content"])
        return result["content"]

    def ask(self, text: str) -> str:
        with self._lock:
            return self._ask(text)

    def _ask(self, text: str) -> str:
        from openjarvis.core.types import Message, Role

        self._select()  # a rested higher-priority provider takes back over
        started_on = self.current
        notes = []
        while True:
            provider = self.current
            model = provider.model
            try:
                reply = self._ask_once(provider, text)
                provider.busy_strikes.pop(model, None)
                break
            except Exception as exc:
                if provider.is_local:
                    # Ollama could not run this model, usually for want of memory: try a smaller one
                    if local_model_failed(exc) and len([m for m in provider.models if provider.busy_until.get(m, 0) <= time.monotonic()]) > 1:
                        logger.warning("Local model %s failed (%s); trying a smaller one", model, str(exc)[:120])
                        provider.busy_until[model] = time.monotonic() + 600
                        self._select(reason=f"{model} could not run (low memory?)")
                        notes.append(f"The local model {model} could not run, so I am using a lighter one.")
                        continue
                    raise
                failure = classify_failure(exc)
                if failure is None:
                    raise
                kind, rest = failure
                logger.warning("%s / %s failed (%s): %s", provider.label, model, kind, str(exc)[:200])
                if kind in ("busy", "quota-day", "quota-minute"):  # this model only
                    if kind == "busy":
                        provider.mark_busy(model)
                    else:
                        provider.busy_until[model] = time.monotonic() + rest
                        if kind == "quota-day":
                            self._remember_spent_model(provider, model, rest)
                    if provider.model:  # another model on the same key: no need to tell the user
                        self._select(reason=f"{model} {_MODEL_REASONS[kind]}")
                        continue
                    rest = min(provider.busy_until.values()) - time.monotonic()
                provider.rested_until = time.monotonic() + rest
                if kind == "offline":  # every cloud key shares the connection
                    for p in self.providers:
                        if not p.is_local:
                            p.rested_until = max(p.rested_until, provider.rested_until)
                self._select(reason=f"{provider.label} {_REASONS[kind]}")


        if reply:
            self._history += [
                Message(role=Role.USER, content=text),
                Message(role=Role.ASSISTANT, content=reply),
            ]
            del self._history[:-_MAX_HISTORY_MESSAGES]
        # One short spoken sentence, and only when Sebas dropped a tier (switching
        # keys is silent; the console and interface still show every switch).
        if self.current is not started_on and not notes:
            if self.current.is_local:
                notes.append("Gemini is unavailable just now, sir, so I am answering with the local model.")
            elif self.current.lite and not started_on.lite:
                notes.append("Today's Gemini quota is spent, sir, so I am using a lighter model.")
        return (" ".join(notes) + " " + reply).strip() if notes else reply

    def close(self) -> None:
        for system in self._systems.values():
            system.close()
