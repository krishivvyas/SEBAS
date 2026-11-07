"""Sebas on Discord: a private bot in your own server.

On first connection he sets the server up himself: a "Sebas" category, visible
only to you and the bot, with five channels:

    #sebas      talk to him (only your account is answered)
    #alerts     deadlines, reminders, system warnings
    #briefings  morning briefing, evening check-in, weekly recap
    #ledger     what changed: tasks, expenses, journal, memory
    #status     one message he keeps updated: battery, mind, agenda, spending

Laptop actions asked for from Discord (opening apps, locking, music, Wi-Fi...)
never run straight away: Sebas asks, and only your "yes" carries them out.

Needs DISCORD_BOT_TOKEN in .env. The master is the server's owner unless
DISCORD_USER_ID (a numeric user ID) says otherwise; DISCORD_GUILD_ID only if the
bot is in more than one server. Runs on its own thread next to the voice
loop or the interface.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Callable

from openjarvis.core.paths import get_data_dir

import custom_tools._base as tool_base
import sebas_events
from sebas_scheduler import idle_seconds

logger = logging.getLogger("sebas.discord")

CATEGORY = "Sebas"
CHANNELS = {
    "sebas": "Speak with Sebas here. Only the master's messages are answered.",
    "alerts": "Deadlines, reminders and system warnings.",
    "briefings": "Morning briefings, evening check-ins and weekly recaps.",
    "ledger": "A record of what changed: tasks, expenses, journal and memory.",
    "status": "A live summary, updated every few minutes.",
    "commands": "Everything you can ask Sebas from Discord, by category (read-only).",
}
LEDGER_TOOLS = {
    "add_task": "Agenda", "complete_task": "Agenda", "log_expense": "Accounts", "undo_expense": "Accounts",
    "journal_add": "Journal", "remember": "Memory", "forget": "Memory", "set_reminder": "Engagement",
}
HELP = (
    "**At your service, sir.** Write to me here as you would speak to me.\n"
    "- Ask anything: *how are my deployments?*, *what's on my agenda?*, *I spent 300 on books*\n"
    "- Laptop actions (opening apps, music, locking, Wi-Fi...) wait for your **yes** before I act.\n"
    "- `!status` for a quick summary, `!help` for this note.\n"
    "Alerts arrive in #alerts, briefings in #briefings, changes in #ledger, and #status stays current."
)
SLEEP_REFUSAL = (
    "I must respectfully decline, sir: sent to sleep from here, I could not be woken again "
    "until you are back at the laptop. Say 'Sebas, sleep' there, should you wish me to retire."
)
# The #commands guide, one Discord message per section (each under 2000 chars).
COMMAND_GUIDE = [
"""# Sebas · Commands
Write to me in **#sebas** in plain words, as you would speak to me; the examples below are suggestions, not fixed phrases. I answer only you.
Anything that acts on the laptop waits for your **yes** before I do it. This channel is updated automatically whenever my abilities change.""",

"""## Quick commands
`!status` · battery, which mind I'm using, today's agenda and spending
`!help` · a short reminder of how to use me
`yes` / `no` · confirm or cancel a laptop action I've asked about (lapses after 5 minutes)""",

"""## Agenda & to-dos
*Add submit the DBMS assignment by Friday at 5 pm* · adds a task with a deadline
*What's on my agenda?* · open tasks, soonest first
*Mark the assignment as done* · completes it
*Cancel the dentist task* · removes it
I warn you an hour before a deadline (in #alerts), and on the morning of date-only deadlines.""",

"""## Money (₹)
*I spent 240 on lunch* · logs an expense (food, transport, shopping, bills, books, games, entertainment, health, other)
*How much did I spend this week?* · today, week, month or year, by category
*Undo that last expense* · removes the most recent entry
Every entry is also noted in #ledger.""",

"""## Journal & memory
*Write in my journal: finished the UI today, quite pleased* · saves a journal entry
*What did I write this week?* · reads recent entries
*Remember that I prefer chai over coffee* · a fact I keep for every future conversation
*Forget that I prefer chai* · removes it
Each evening at 21:30 I ask how your day went; answer here and I'll save it. On Sundays I recap your week.""",

"""## Reminders
*Remind me in 20 minutes to stretch* · I announce it at the laptop and post it in #alerts
*What reminders are pending?* · lists them
(Reminders live while I'm running; they don't survive a restart.)""",

"""## Information
*What's the weather?* · Gandhinagar, or ask about any city
*Give me my morning briefing* · time, weather, agenda (calendar after December)
*Anything new on GitHub?* · your open PRs, review requests and notifications
*How is my laptop doing?* · battery, CPU, memory, disk, uptime
*Any sales on my Steam wishlist?* · *Any new light novels on Bookswagon?*
*How are my Vercel deployments?* · *How are my AWS servers?* (once those keys are added)""",

"""## Laptop control (each asks for your **yes**)
**Music:** *pause the music* · *next song* · *previous song* · *what's playing?* · *resume Spotify* · *search Spotify for lo-fi beats*
**Apps & sites:** *open YouTube* · *open notepad* · *open my workspace* (editor, Claude, Gemini and your music) · *run my inbox routine*
**Settings:** *set the volume to 30* · *mute* · *turn Wi-Fi off* · *turn Bluetooth on* · *brightness 60* · *switch to light mode* · *lock the screen*
Only apps, sites and folders listed in `laptop.toml` can be opened. Turning Wi-Fi off from here would cut me off from Discord.""",

"""## Screen, clipboard & files (each asks for your **yes**)
*What's this error on my screen?* · a screenshot, read by Gemini (only when you ask)
*Summarise what I copied* · *translate my clipboard into Hindi* · *explain the code I copied*
*Put that on my clipboard* · copies my answer so you can paste it
*Tidy my Downloads* · I show the plan first and move nothing until you agree · *undo the tidy*""",

"""## Reading & notes (at the laptop)
*Read this article aloud: <link>* · *read my clipboard aloud* · *read the PDF at C:/Users/krish/Downloads/notes.pdf* · *stop reading*
*Start recording the DBMS lecture* · *stop recording* · I transcribe it on the laptop and save a summary, key points and action items to Documents › Sebas Notes, then tell you it's ready""",

"""## Anime, manga & light novels (AniList)
*What anime airs today?* · from your watching and planning list, in Indian time · *what's popular this week?*
*What am I watching?* · *what's on my plan-to-watch?* · *which light novels am I reading?*
*I finished episode 7 of Frieren* · *rate it 9* · *mark Dandadan as completed* · updates AniList
*Anything new on my list?* · new episodes, chapters and volumes since the last check (I also check every 30 minutes and post news in #alerts)
*Suggest something short and funny for tonight* · recommendations from what you've rated highly""",

"""## Channels
**#sebas** · talk to me
**#alerts** · deadlines, reminders, battery, memory and disk warnings
**#briefings** · morning briefings, evening check-ins, weekly recaps
**#ledger** · every task, expense, journal entry and memory I record
**#status** · a live summary, refreshed every 5 minutes
**#commands** · this guide

## Not from Discord
Sending me to sleep (*Sebas, sleep*) and voice commands work only at the laptop.""",
]

_STATUS_SECONDS = 300
_CONFIRM_SECONDS = 300
_AWAY_SECONDS = 600


def discord_configured() -> bool:
    return bool(os.environ.get("DISCORD_BOT_TOKEN", "").strip())


def _configured_owner() -> int | None:
    value = os.environ.get("DISCORD_USER_ID", "").strip()
    return int(value) if value.isdigit() else None  # a username is not an ID


def _split(text: str, limit: int = 1900) -> list[str]:
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        cut = cut if cut > limit // 2 else limit
        parts.append(text[:cut]); text = text[cut:].lstrip()
    return parts + ([text] if text else [])


def status_text(brain) -> str:
    import psutil

    from custom_tools.household import describe_due, expense_totals, open_tasks

    battery = psutil.sensors_battery()
    tasks = open_tasks()
    lines = [
        f"**Status** · updated {datetime.now().strftime('%I:%M %p')}",
        f"Mind: {brain.short_description if brain and brain.current else 'starting'}",
        f"Battery: {battery.percent:.0f}% ({'charging' if battery.power_plugged else 'on battery'})" if battery else "Battery: mains",
        f"CPU {psutil.cpu_percent(interval=None):.0f}% · memory {psutil.virtual_memory().percent:.0f}%",
        f"At the laptop: {'yes' if idle_seconds() < _AWAY_SECONDS else 'away'}",
        f"Spent today ₹{expense_totals('today')[0]:,.0f} · this month ₹{expense_totals('month')[0]:,.0f}",
        f"Agenda: {len(tasks)} open" + (f" · next: {tasks[0]['task']} ({describe_due(tasks[0].get('due'))})" if tasks else ""),
    ]
    return "\n".join(lines)


class DiscordBridge:
    """Connects one brain to one private Discord server."""

    def __init__(self, brain, is_sleep: Callable[[str], bool]) -> None:
        self.brain = brain
        self._is_sleep = is_sleep
        self.loop: asyncio.AbstractEventLoop | None = None
        self.client = None
        self.channels: dict[str, Any] = {}
        self.ready = threading.Event()
        self.owner_id: int | None = _configured_owner()  # else the server owner, once connected
        self._pending: dict[str, Any] | None = None  # action awaiting the master's yes
        self._state_path = get_data_dir() / "sebas" / "discord.json"

    # --- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        threading.Thread(target=self._run, name="sebas-discord", daemon=True).start()
        tool_base.confirm_remote = self._request_confirmation
        sebas_events.add_listener(self._on_event)
        # Reminders: always post to #alerts; speak them only if someone is at the laptop.
        from custom_tools import laptop

        speak = laptop._announce

        def announce(text: str) -> None:
            if not (self.alert(text) and self.user_away()):
                speak(text)

        laptop.set_announcer(announce)

    def _run(self) -> None:
        import discord

        intents = discord.Intents.default()
        intents.message_content = True  # also switch this on in the Developer Portal
        self.client = client = discord.Client(intents=intents)
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        @client.event
        async def on_ready() -> None:
            try:
                await self._prepare_server()
                self.ready.set()
                logger.info("Discord ready in %s", self.channels["sebas"].guild.name)
                self.loop.create_task(self._status_loop())
            except Exception:
                logger.exception("Could not prepare the Discord server")

        @client.event
        async def on_message(message) -> None:
            await self._on_message(message)

        try:
            self.loop.run_until_complete(client.start(os.environ["DISCORD_BOT_TOKEN"].strip()))
        except Exception as exc:
            logger.error("Discord stopped: %s", exc)
            sebas_events.emit("notice", text=f"Discord is unavailable: {exc}")

    # --- server setup --------------------------------------------------------
    async def _prepare_server(self) -> None:
        import discord

        client = self.client
        wanted = os.environ.get("DISCORD_GUILD_ID", "").strip()
        guilds = [g for g in client.guilds if not wanted or str(g.id) == wanted]
        if len(guilds) != 1:
            raise RuntimeError(
                f"The bot is in {len(client.guilds)} servers; invite it to exactly one, or set DISCORD_GUILD_ID."
            )
        guild = guilds[0]
        if self.owner_id is None:
            self.owner_id = guild.owner_id  # the person who created the server
        owner = await guild.fetch_member(self.owner_id)
        logger.info("Serving %s (%s) in %s", owner.name, self.owner_id, guild.name)
        state = self._load_state()
        private = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            # Only permissions the bot itself holds: Discord refuses to let it
            # grant any it lacks (403 Missing Permissions).
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                                  embed_links=True, pin_messages=True),
            discord.Object(id=self.owner_id, type=discord.Member): discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True),
        }
        category = guild.get_channel(state.get("category", 0)) or discord.utils.get(guild.categories, name=CATEGORY)
        if category is None:
            category = await guild.create_category(CATEGORY, overwrites=private, reason="Sebas setting up his quarters")
        for name, topic in CHANNELS.items():
            channel = (guild.get_channel(state.get(name, 0)) or discord.utils.get(category.text_channels, name=name)
                       or discord.utils.get(guild.text_channels, name=name))
            access = private
            if name == "commands":  # read-only for the master: the guide is Sebas's to keep
                access = {**private, discord.Object(id=self.owner_id, type=discord.Member): discord.PermissionOverwrite(
                    view_channel=True, send_messages=False, read_message_history=True)}
            if channel is not None and channel.category_id != category.id:
                # a channel the user made already (e.g. #sebas): adopt it, made private
                await channel.edit(category=category, overwrites=access, topic=topic, reason="Sebas setting up his quarters")
            if channel is None:
                channel = await guild.create_text_channel(name, category=category, topic=topic, overwrites=access,
                                                          reason="Sebas setting up his quarters")
            self.channels[name] = channel
        if not state.get("help_pinned"):
            note = await self.channels["sebas"].send(HELP)
            try:
                await note.pin()
            except discord.HTTPException:
                logger.warning("Could not pin the help note (Pin Messages permission)")
            state["help_pinned"] = note.id
        await self._publish_guide(state)
        state.update({"guild": guild.id, "category": category.id, **{k: c.id for k, c in self.channels.items()}})
        self._save_state(state)

    async def _publish_guide(self, state: dict) -> None:
        """Post the #commands guide; replace it whenever its text changes."""
        import hashlib

        import discord

        digest = hashlib.sha256("|".join(COMMAND_GUIDE).encode()).hexdigest()[:16]
        if state.get("guide_hash") == digest:
            return
        channel = self.channels["commands"]
        for message_id in state.get("guide_messages", []):
            try:
                await (await channel.fetch_message(message_id)).delete()
            except discord.HTTPException:
                pass
        ids = [(await channel.send(section)).id for section in COMMAND_GUIDE]
        state.update(guide_hash=digest, guide_messages=ids)

    def _load_state(self) -> dict:
        try:
            return json.loads(self._state_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self, state: dict) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(state, indent=1), "utf-8")

    # --- messages from the master ----------------------------------------------
    async def _on_message(self, message) -> None:
        if message.author.bot or self.owner_id is None or message.author.id != self.owner_id:
            return
        if self.channels.get("sebas") is None or message.channel.id != self.channels["sebas"].id:
            return
        text = message.content.strip()
        if not text:
            return
        low = text.lower().rstrip(".!")
        if low in ("!help", "help"):
            await message.reply(HELP, mention_author=False)
            return
        if low == "!status":
            await message.reply(await self._in_thread(status_text, self.brain), mention_author=False)
            return
        if self._pending and low in ("yes", "y", "yes please", "confirm", "do it", "go ahead", "no", "n", "cancel", "never mind"):
            await self._answer_confirmation(message, low)
            return
        if self._is_sleep(text):
            await message.reply(SLEEP_REFUSAL, mention_author=False)
            return
        import sebas_eggs

        egg = sebas_eggs.check(text)
        if egg is not None:  # the line only; the visual effect shows on the laptop's interface
            sebas_eggs.trigger(egg)
            await message.reply(f"*{egg.line}*", mention_author=False)
            return
        async with message.channel.typing():
            reply = await self._in_thread(self._ask_remote, text)
        for i, part in enumerate(_split(reply or "…")):
            await (message.reply(part, mention_author=False) if i == 0 else message.channel.send(part))

    def _ask_remote(self, text: str) -> str:
        """Ask the brain with the laptop-action gate closed."""
        with self.brain._lock:
            tool_base.REMOTE_REQUEST = True
            try:
                return self.brain.ask(f"(Written to you on Discord, away from the laptop.) {text}")
            except Exception:
                logger.exception("Discord request failed")
                return "I regret that the request could not be completed, sir. The details are in the laptop's console."
            finally:
                tool_base.REMOTE_REQUEST = False

    async def _in_thread(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)

    # --- confirmations -------------------------------------------------------
    def _request_confirmation(self, tool: str, params: dict[str, Any], description: str) -> str:
        """Called by a laptop-acting tool during a Discord request (tool thread)."""
        action = tool.replace("_", " ")
        detail = ", ".join(f"{k} {v}" for k, v in params.items()) or "no details"
        self._pending = {"tool": tool, "params": params, "asked": time.monotonic()}
        self.send("sebas", f"Shall I **{action}** ({detail}) on the laptop, sir? Reply **yes** to proceed or **no** to cancel.")
        return (
            "This action needs the master's confirmation because it was requested remotely. "
            "A confirmation question has been posted; tell him briefly that you await his yes. Do not claim it is done."
        )

    async def _answer_confirmation(self, message, answer: str) -> None:
        pending, self._pending = self._pending, None
        if time.monotonic() - pending["asked"] > _CONFIRM_SECONDS:
            await message.reply("That request has lapsed, sir; please ask again.", mention_author=False)
            return
        if answer.startswith("n") or answer in ("cancel", "never mind"):
            await message.reply("Very good, sir. I have left it be.", mention_author=False)
            return
        from openjarvis.core.registry import ToolRegistry

        result = await self._in_thread(lambda: ToolRegistry.create(pending["tool"]).run_now(**pending["params"]))
        prefix = "Done, sir." if result.success else "I regret that it could not be done, sir:"
        await message.reply(f"{prefix} {result.content}", mention_author=False)

    # --- sending from other threads ------------------------------------------
    def send(self, channel: str, text: str) -> bool:
        if not self.ready.is_set() or channel not in self.channels:
            return False

        async def post() -> None:
            for part in _split(text):
                await self.channels[channel].send(part)

        asyncio.run_coroutine_threadsafe(post(), self.loop)
        return True

    def converse_remote(self, prompt: str, title: str) -> None:
        """A scheduled prompt held on Discord while the user is away."""
        reply = self.brain.ask(prompt)
        self.briefing(title, reply)
        self.send("sebas", reply)  # so the answer can be given right here

    def alert(self, text: str) -> bool:
        return self.send("alerts", text)

    def briefing(self, title: str, text: str) -> bool:
        return self.send("briefings", f"**{title}** · {datetime.now().strftime('%a %d %b, %I:%M %p')}\n{text}")

    @staticmethod
    def user_away() -> bool:
        return idle_seconds() >= _AWAY_SECONDS

    # --- the ledger and the live status --------------------------------------
    def _on_event(self, kind: str, data: dict[str, Any]) -> None:
        if kind == "tool" and data.get("phase") == "end" and data.get("success") and data.get("tool") in LEDGER_TOOLS:
            result = (data.get("result") or "").strip()
            if result and "confirmation" not in result:
                self.send("ledger", f"**{LEDGER_TOOLS[data['tool']]}** · {result}")

    async def _status_loop(self) -> None:
        import discord

        state = self._load_state()
        message = None
        if state.get("status_message"):
            try:
                message = await self.channels["status"].fetch_message(state["status_message"])
            except discord.HTTPException:
                message = None
        while not self.client.is_closed():
            try:
                text = await self._in_thread(status_text, self.brain)
                if message is None:
                    message = await self.channels["status"].send(text)
                    state = self._load_state(); state["status_message"] = message.id; self._save_state(state)
                else:
                    await message.edit(content=text)
            except Exception:
                logger.exception("Status update failed")
            await asyncio.sleep(_STATUS_SECONDS)
