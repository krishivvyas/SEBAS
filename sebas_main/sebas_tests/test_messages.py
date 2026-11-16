"""Sending messages, offline: WhatsApp's link, the keyboard, the browser extension
and the Discord bot are all stand-ins. No message leaves the laptop."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sebas_bootstrap import load_env  # noqa: E402

load_env()

import sebas_actions  # noqa: E402
import sebas_discord  # noqa: E402
from custom_tools import browser, desk, messages  # noqa: E402
from custom_tools._base import ToolError  # noqa: E402

CONTACTS = {"rahul": {"phone": "+91 98765 43210", "email": "rahul@example.com"},
            "rohan": {"phone": "9123456780"}, "professor mehta": "mehta@college.example"}


class _Messages(unittest.TestCase):
    def patch(self, target, name, value):
        p = mock.patch.object(target, name, value)
        p.start()
        self.addCleanup(p.stop)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.patch(sebas_actions, "get_data_dir", lambda: Path(tmp.name))
        self.patch(messages, "_section", lambda name: {"contacts": CONTACTS, "messages": {"country_code": "91"}}.get(name, {}))
        self.opened: list[str] = []
        self.pressed: list[list[str]] = []
        self.front = {"whatsapp": True}
        self.patch(messages, "_open", self.opened.append)
        self.patch(messages, "_whatsapp_in_front", lambda: self.front["whatsapp"])
        self.patch(messages.time, "sleep", lambda s: None)
        self.patch(desk, "press", self.pressed.append)
        sebas_actions.answer("drop anything left over")

    def send(self, **params):
        """Ask as the model would, then answer as the user would."""
        return messages.SendMessageTool().execute(**params)


class Recipients(_Messages):
    def test_names_numbers_and_addresses(self):
        self.assertEqual(messages.resolve("whatsapp", "Rahul"), ("919876543210", "rahul (+919876543210)"))
        self.assertEqual(messages.resolve("whatsapp", "rohan")[0], "919123456780")       # country code added
        self.assertEqual(messages.resolve("whatsapp", "+44 20 7946 0958")[0], "442079460958")
        self.assertEqual(messages.resolve("whatsapp", "98765 43210"), ("919876543210", "+919876543210"))
        self.assertEqual(messages.resolve("email", "Professor Mehta")[0], "mehta@college.example")
        self.assertEqual(messages.resolve("email", "prof mehta")[0], "mehta@college.example")  # close enough
        self.assertEqual(messages.resolve("email", "someone@new.example"), ("someone@new.example", "someone@new.example"))
        self.assertEqual(messages.resolve("discord", "#General Chat"), ("general-chat", "the #general-chat channel"))

    def test_unknown_ambiguous_and_wrong_kind_are_refused(self):
        for channel, to, word in (("whatsapp", "Priya", "not in [contacts]"), ("whatsapp", "ro", "not in [contacts]"),
                                  ("email", "rohan", "no email"), ("email", "not-an-address", "not in [contacts]"),
                                  ("whatsapp", "12345", "not in [contacts]"), ("whatsapp", "", "Who is")):
            with self.assertRaises(ToolError, msg=to) as caught:
                messages.resolve(channel, to)
            self.assertIn(word, str(caught.exception))
        self.patch(messages, "_section", lambda name: {"contacts": {"rahul k": {"phone": "+911111111111"},
                                                                   "rahul m": {"phone": "+912222222222"}}}.get(name, {}))
        with self.assertRaises(ToolError) as caught:
            messages.resolve("whatsapp", "rahul")
        self.assertIn("could be", str(caught.exception))

    def test_an_unknown_recipient_is_said_at_once_not_after_a_yes(self):
        result = self.send(channel="whatsapp", to="Priya", text="hi")
        self.assertFalse(result.success)
        self.assertEqual(sebas_actions.pending_summary(), "")
        self.assertFalse(self.send(channel="whatsapp", to="rahul", text="  ").success)
        self.assertFalse(self.send(channel="sms", to="rahul", text="hi").success)


class WhatsApp(_Messages):
    def test_nothing_happens_until_the_yes(self):
        parked = self.send(channel="whatsapp", to="Rahul", text="Running 10 minutes late, sorry!")
        self.assertIn("NOT DONE YET", parked.content)
        self.assertEqual(sebas_actions.pending_summary(),
                         'Send a WhatsApp message to rahul (+919876543210): "Running 10 minutes late, sorry!"')
        self.assertEqual((self.opened, self.pressed), ([], []))
        said = sebas_actions.answer("yes")
        self.assertIn("Done, sir. To rahul (+919876543210): Pressed send in WhatsApp.", said)
        link = urlparse(self.opened[0])
        self.assertEqual((link.scheme, link.netloc), ("whatsapp", "send"))
        self.assertEqual(parse_qs(link.query), {"phone": ["919876543210"], "text": ["Running 10 minutes late, sorry!"]})
        self.assertEqual(self.pressed, [["enter"]])
        self.assertTrue(any(e["action"] == "send_message" and "Running 10 minutes" in e["detail"] for e in sebas_actions.recent()))

    def test_a_no_sends_nothing(self):
        self.send(channel="whatsapp", to="Rahul", text="hello")
        sebas_actions.answer("no")
        self.assertEqual((self.opened, self.pressed), ([], []))

    def test_enter_is_not_pressed_unless_whatsapp_has_the_keyboard(self):
        self.front["whatsapp"] = False
        clock = {"t": 0.0}
        self.patch(messages.time, "monotonic", lambda: clock.__setitem__("t", clock["t"] + 1) or clock["t"])
        self.send(channel="whatsapp", to="Rahul", text="hello")
        said = sebas_actions.answer("yes")
        self.assertIn("did not succeed", said)
        self.assertIn("NOT pressed send", said)
        self.assertEqual(self.pressed, [])

    def test_and_not_if_the_user_clicks_away_while_it_loads(self):
        looks = iter([True, True, False])  # in front, in front, then gone during the settle
        self.patch(messages, "_whatsapp_in_front", lambda: next(looks, False))
        self.send(channel="whatsapp", to="Rahul", text="hello")
        self.assertIn("Another window took the keyboard", sebas_actions.answer("yes"))
        self.assertEqual(self.pressed, [])

    def test_special_characters_survive_the_link(self):
        text = "50% done & more?\nSee #3 + ₹200"
        self.send(channel="whatsapp", to="Rahul", text=text)
        sebas_actions.answer("yes")
        self.assertEqual(parse_qs(urlparse(self.opened[0]).query)["text"], [text])


class _Gmail:
    """Stands in for the browser extension showing a Gmail compose window."""

    def __init__(self, pages):
        self.pages, self.calls = list(pages), []

    def connected(self):
        return True

    def call(self, cmd, timeout=25.0, **args):
        self.calls.append((cmd, args))
        if cmd == "snapshot":
            return self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]
        return True


COMPOSE = {"url": "https://mail.google.com/mail/u/0/?view=cm", "text": "New Message",
           "elements": [{"n": 7, "kind": "button", "label": "Send ‪(Ctrl-Enter)‬"}, {"n": 8, "kind": "button", "label": "Schedule send"}]}


class Email(_Messages):
    def gmail(self, pages):
        fake = _Gmail(pages)
        self.patch(browser, "BRIDGE", fake)
        self.patch(browser, "_task", None)
        return fake

    def test_sent_and_confirmed(self):
        fake = self.gmail([{"url": "https://mail.google.com/mail/u/0/?view=cm", "text": "", "elements": []}, COMPOSE, COMPOSE,
                           {"url": "https://mail.google.com/", "text": "Message sent Undo View message", "elements": []}])
        parked = self.send(channel="email", to="Professor Mehta", subject="Report", text="I will submit it on Monday.")
        self.assertIn("NOT DONE YET", parked.content)
        self.assertEqual(sebas_actions.pending_summary(),
                         'Send an email to professor mehta (mehta@college.example), subject "Report": "I will submit it on Monday."')
        self.assertEqual(fake.calls, [])
        self.assertIn("Gmail confirmed 'Message sent'", sebas_actions.answer("yes"))
        opened = urlparse(next(a["url"] for c, a in fake.calls if c == "open"))
        self.assertEqual(parse_qs(opened.query), {"view": ["cm"], "fs": ["1"], "to": ["mehta@college.example"],
                                                  "su": ["Report"], "body": ["I will submit it on Monday."]})
        self.assertEqual([a for c, a in fake.calls if c == "click"], [{"n": 7}])  # Send, not "Schedule send"

    def test_without_the_extension_the_draft_is_left_open_and_reported_unsent(self):
        fake = self.gmail([COMPOSE])
        fake.connected = lambda: False
        opened = []
        self.patch(messages.webbrowser, "open", opened.append)
        self.send(channel="email", to="rahul", text="Notes attached.")
        said = sebas_actions.answer("yes")
        self.assertIn("did not succeed", said)
        self.assertIn("NOT sent", said)
        self.assertIn("su=%28no%20subject%29", opened[0])
        self.assertEqual(fake.calls, [])

    def test_a_sign_in_page_or_missing_button_is_reported_unsent(self):
        fake = self.gmail([{"url": "https://accounts.google.com/signin", "text": "Sign in", "elements": []}])
        self.send(channel="email", to="rahul", text="x")
        self.assertIn("asking the user to sign in", sebas_actions.answer("yes"))
        self.assertEqual([c for c, _ in fake.calls if c == "click"], [])
        fake = self.gmail([{"url": "https://mail.google.com/", "text": "Inbox", "elements": []}])
        self.send(channel="email", to="rahul", text="x")
        self.assertIn("could not find the Send button", sebas_actions.answer("yes"))

    def test_send_pressed_but_unconfirmed_says_so(self):
        self.gmail([COMPOSE])
        self.send(channel="email", to="rahul", text="x")
        self.assertIn("did not see its 'Message sent' notice", sebas_actions.answer("yes"))


class Discord(_Messages):
    def test_posts_through_the_running_bot(self):
        posted = []
        bot = mock.Mock(post_to=lambda channel, text: (posted.append((channel, text)), channel)[1])
        self.patch(sebas_discord, "ACTIVE", bot)
        self.send(channel="discord", to="#General", text="Meeting moved to 6.")
        self.assertEqual(sebas_actions.pending_summary(), 'Post in the #general channel: "Meeting moved to 6."')
        self.assertEqual(posted, [])
        self.assertIn("Posted in #general", sebas_actions.answer("yes"))
        self.assertEqual(posted, [("general", "Meeting moved to 6.")])

    def test_no_bot_or_no_such_channel(self):
        self.patch(sebas_discord, "ACTIVE", None)
        self.send(channel="discord", to="general", text="x")
        self.assertIn("bot is not running", sebas_actions.answer("yes"))
        self.patch(sebas_discord, "ACTIVE", mock.Mock(post_to=mock.Mock(side_effect=ValueError("There is no channel #nope."))))
        self.send(channel="discord", to="nope", text="x")
        self.assertIn("no channel #nope", sebas_actions.answer("yes"))


class Gate(_Messages):
    def test_send_message_is_always_behind_the_yes(self):
        self.assertTrue(messages.SendMessageTool.risky)
        from custom_tools import _base
        asked = []
        self.patch(_base, "REMOTE_REQUEST", True)
        self.patch(_base, "confirm_remote", lambda tool, params, desc: asked.append(tool) or "asked on Discord")
        self.assertEqual(self.send(channel="whatsapp", to="rahul", text="hi").content, "asked on Discord")
        self.assertEqual((asked, self.opened), (["send_message"], []))


if __name__ == "__main__":
    unittest.main()
