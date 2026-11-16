"""Sending messages on the user's behalf: WhatsApp, email, and his own Discord server.

Every message is risky (it cannot be unsent), so send_message always goes
through the yes-gate: Sebas reads out who it is to and the exact words, and only
the user's yes sends it. Nothing is opened or typed before that yes. One
recipient per message.

    whatsapp  Opens WhatsApp Desktop on the person's chat with the text filled
              in (WhatsApp's own whatsapp://send link), waits until WhatsApp has
              the keyboard, and presses Enter. If WhatsApp does not come to the
              front, Enter is NOT pressed and the draft is left for the user.
    email     Opens a filled-in Gmail compose window in the user's browser. With
              the browser extension connected, presses Send and looks for
              Gmail's "Message sent"; without it, leaves the draft open.
    discord   Posts to a named channel of the user's own server, as the Sebas
              bot (he cannot message the user's friends as the user).

Recipients: a name from [contacts] in laptop.toml, or a phone number or email
address given in full.
"""

from __future__ import annotations

import os
import re
import time
import webbrowser
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult

from custom_tools._base import SebasTool, ToolError
from custom_tools.laptop import _section

_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_MAX_CHARS = {"whatsapp": 1500, "email": 8000, "discord": 1800}
_WHATSAPP_WAIT = 12.0   # seconds for WhatsApp to come to the front
_WHATSAPP_SETTLE = 2.5  # seconds for it to open the chat and fill in the text


# --------------------------------------------------------------------------- who

def _contacts() -> dict[str, dict[str, str]]:
    found = {}
    for name, entry in _section("contacts").items():
        if isinstance(entry, str):  # shorthand: rahul = "+919876543210" or an address
            entry = {"email": entry} if "@" in entry else {"phone": entry}
        found[str(name)] = {k: str(v) for k, v in entry.items()}
    return found


def clean_phone(text: str) -> str:
    """Digits with the country code, no plus: what WhatsApp's link wants."""
    raw = (text or "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 8 or len(digits) > 15 or re.search(r"[A-Za-z@]", raw):
        raise ToolError(f"'{text}' is not a phone number.")
    if raw.startswith("+") or raw.startswith("00"):
        return digits[2:] if raw.startswith("00") else digits
    if len(digits) == 10:  # a local number: add the home country code
        return str(_section("messages").get("country_code", "91")) + digits
    return digits


def resolve(channel: str, to: str) -> tuple[str, str]:
    """(the address to use, how to name the recipient aloud) for a channel."""
    to = " ".join((to or "").split())
    if not to:
        raise ToolError("Who is the message for?")
    if channel == "discord":
        return to.lstrip("#").lower().replace(" ", "-"), f"the #{to.lstrip('#').lower().replace(' ', '-')} channel"
    field = "phone" if channel == "whatsapp" else "email"
    contacts = _contacts()
    exact = next((n for n in contacts if n.lower() == to.lower()), None)
    if exact is None and contacts and not re.search(r"\d{6,}|@", to):
        # A whole word of the name ("Mehta" for "professor mehta") or a near-identical
        # spelling. Nothing looser: a fragment such as "ro" must not reach Rohan.
        said = [w for w in to.lower().split() if len(w) >= 3]
        scored = sorted(((1.0 if said and any(w in n.lower().split() for w in said)
                          else SequenceMatcher(None, to.lower(), n.lower()).ratio(), n) for n in contacts), reverse=True)
        if scored[0][0] >= 0.8 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.1):
            exact = scored[0][1]
        elif scored[0][0] >= 0.8:
            raise ToolError(f"'{to}' could be {scored[0][1]} or {scored[1][1]}; ask the user which.")
    if exact is not None:
        value = contacts[exact].get(field, "")
        if not value:
            raise ToolError(f"{exact} has no {field} in [contacts] of laptop.toml.")
        address = clean_phone(value) if field == "phone" else value.strip()
        if field == "email" and not _EMAIL.match(address):
            raise ToolError(f"The email address for {exact} in laptop.toml does not look right: {address}")
        return address, f"{exact} ({'+' + address if field == 'phone' else address})"
    if field == "email" and _EMAIL.match(to):
        return to, to
    if field == "phone" and re.fullmatch(r"[+\d][\d\s().-]{6,}", to):
        number = clean_phone(to)
        return number, f"+{number}"
    known = ", ".join(sorted(contacts)) or "none yet"
    raise ToolError(f"'{to}' is not in [contacts] of laptop.toml (known: {known}), and is not a full "
                    f"{'phone number' if field == 'phone' else 'email address'}. Ask the user for it.")


# --------------------------------------------------------------------------- how

def _open(link: str) -> None:
    os.startfile(link)  # type: ignore[attr-defined]


def _whatsapp_in_front() -> bool:
    from custom_tools import desk

    hwnd = desk.foreground()
    if not hwnd:
        return False
    title = desk._title(hwnd).lower()
    try:
        import psutil

        app = psutil.Process(desk._pid(hwnd)).name().lower()
    except Exception:
        app = ""
    return "whatsapp" in app or title.strip() == "whatsapp" or title.endswith("whatsapp")


def send_whatsapp(number: str, text: str) -> str:
    from custom_tools import desk

    try:
        _open(f"whatsapp://send?phone={number}&text={quote(text)}")
    except OSError as exc:
        raise ToolError("WhatsApp Desktop does not seem to be installed (the whatsapp: link has no handler).") from exc
    deadline = time.monotonic() + _WHATSAPP_WAIT
    while time.monotonic() < deadline and not _whatsapp_in_front():
        time.sleep(0.3)
    if not _whatsapp_in_front():
        raise ToolError("WhatsApp did not come to the front, so I have NOT pressed send. The message is typed in the "
                        "chat, waiting for the user to press Enter.")
    time.sleep(_WHATSAPP_SETTLE)
    if not _whatsapp_in_front():  # the user clicked elsewhere meanwhile: Enter would land in another program
        raise ToolError("Another window took the keyboard, so I have NOT pressed send. The message is typed in the WhatsApp chat.")
    desk.press(["enter"])
    return ("Pressed send in WhatsApp. (If WhatsApp showed a notice instead, for instance that the number is not "
            "on WhatsApp, the message has not gone; I cannot see that.)")


def gmail_link(address: str, subject: str, body: str) -> str:
    return f"https://mail.google.com/mail/?view=cm&fs=1&to={quote(address)}&su={quote(subject)}&body={quote(body)}"


def send_email(address: str, subject: str, body: str) -> str:
    from custom_tools import browser

    link = gmail_link(address, subject, body)
    bridge = browser.BRIDGE
    if not bridge.connected() or browser.running():
        webbrowser.open(link)
        why = "the browser is busy with another task" if browser.running() else "the browser extension is not connected"
        raise ToolError(f"The email is written and open in Gmail, but NOT sent: {why}, so the user must press Send.")
    try:
        bridge.call("open", url=link, timeout=30)
        send = None
        for _ in range(8):  # Gmail draws its compose window a moment after the page loads
            page = bridge.call("snapshot", maxText=1500, maxElements=120)
            if (page.get("url") or "").startswith("https://accounts.google.com"):
                raise ToolError("Gmail is asking the user to sign in, so the email is NOT sent. The tab is open for him.")
            send = next((e for e in page.get("elements", []) if e.get("kind") == "button"
                         and re.match(r"send\b", e.get("label", "").strip(), re.I) and "schedule" not in e.get("label", "").lower()), None)
            if send:
                break
            time.sleep(1.0)
        if send is None:
            raise ToolError("The email is written and open in Gmail, but I could not find the Send button, so it is NOT sent.")
        bridge.call("click", n=send["n"])
        for _ in range(6):
            time.sleep(0.8)
            if "message sent" in (bridge.call("snapshot", maxText=3000, maxElements=5).get("text") or "").lower():
                bridge.call("close")
                return "Sent; Gmail confirmed 'Message sent'."
        return "Pressed Send in Gmail, but did not see its 'Message sent' notice; the tab is open for the user to check."
    except browser.BrowserError as exc:
        raise ToolError(f"The browser gave trouble ({exc}), so the email may NOT be sent; the user should check the Gmail tab.") from exc


def send_discord(channel: str, text: str) -> str:
    import sebas_discord

    bridge = sebas_discord.ACTIVE
    if bridge is None:
        raise ToolError("The Discord bot is not running (no DISCORD_BOT_TOKEN in .env).")
    try:
        return f"Posted in #{bridge.post_to(channel, text)}."
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


# --------------------------------------------------------------------------- the tool

@ToolRegistry.register("send_message")
class SendMessageTool(SebasTool):
    name = "send_message"
    risky = True
    timeout_seconds = 90.0
    description = (
        "Send one message for the user: channel 'whatsapp' (to a contact's name or a full phone number), 'email' "
        "(to a contact's name or a full address, through Gmail; give a subject), or 'discord' (to a channel of his "
        "own server, by name, posted as you). Write the text exactly as it should be sent, in the user's voice "
        "unless he asks otherwise. It always waits for his yes, after you read him the recipient and the words; "
        "never claim it is sent before then. One recipient per call."
    )
    parameters = {
        "type": "object",
        "properties": {
            "channel": {"type": "string", "enum": ["whatsapp", "email", "discord"]},
            "to": {"type": "string", "description": "A contact's name, a full phone number or email address, or a Discord channel name."},
            "text": {"type": "string", "description": "The message, exactly as it should be sent."},
            "subject": {"type": "string", "description": "Email only: the subject line."},
        },
        "required": ["channel", "to", "text"],
    }

    def _check(self, channel: str = "", to: str = "", text: str = "", subject: str = "", **_: Any) -> tuple[str, str, str]:
        if channel not in _MAX_CHARS:
            raise ToolError("Channel must be whatsapp, email or discord.")
        text = (text or "").strip()
        if not text:
            raise ToolError("There is no message to send.")
        if len(text) > _MAX_CHARS[channel]:
            raise ToolError(f"That is {len(text):,} characters; a {channel} message may be at most {_MAX_CHARS[channel]:,}.")
        address, spoken = resolve(channel, to)
        return address, spoken, text

    def execute(self, **params: Any) -> ToolResult:
        try:  # an unknown recipient is said at once, not after the user has been asked for a yes
            self._check(**params)
        except ToolError as exc:
            return ToolResult(tool_name=self.name, success=False, content=(
                f"NOT SENT, and nothing is waiting for a yes: {exc} Tell the user this plainly; do not ask "
                "whether to send it."))
        return super().execute(**params)

    def confirm_summary(self, **params: Any) -> str:
        _, spoken, text = self._check(**params)
        how = {"whatsapp": "Send a WhatsApp message to", "email": "Send an email to", "discord": "Post in"}[params["channel"]]
        subject = f", subject \"{params.get('subject', '').strip()}\"" if params["channel"] == "email" and params.get("subject") else ""
        return f"{how} {spoken}{subject}: \"{text}\""

    def run(self, channel: str, to: str, text: str, subject: str = "") -> str:
        address, spoken, text = self._check(channel=channel, to=to, text=text)
        if channel == "whatsapp":
            outcome = send_whatsapp(address, text)
        elif channel == "email":
            outcome = send_email(address, (subject or "").strip() or "(no subject)", text)
        else:
            outcome = send_discord(address, text)
        return f"To {spoken}: {outcome}"
