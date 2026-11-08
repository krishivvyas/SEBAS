"""Wellbeing nudges, with a fake clock and fake keyboard activity: no waiting, no Windows calls."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sebas_bootstrap import load_env  # noqa: E402

load_env()

from custom_tools import household, wellbeing  # noqa: E402

CONF = {**wellbeing.DEFAULTS}
MIN = 60.0


class Desk:
    """Simulates someone at the laptop: ``idle`` seconds since the last input."""

    def __init__(self):
        self.idle, self.busy = 0.0, False

    def run(self, w, start, minutes, step=0.5):
        """Tick every ``step`` minutes (the scheduler ticks every 30 s); collect nudges."""
        out, t = [], start
        while t < start + minutes * MIN:
            out += [(round((t - start) / MIN), n.kind) for n in w.tick(t, CONF)]
            t += step * MIN
        return out, t


class Nudges(unittest.TestCase):
    def setUp(self):
        self.desk = Desk()
        self.w = wellbeing.Wellbeing(lambda: self.desk.idle, lambda: self.desk.busy)
        self.w.last_water = -1e9  # no glass logged yet

    def kinds(self, nudges, kind):
        return [m for m, k in nudges if k == kind]

    def test_an_hour_of_work(self):
        nudges, _ = self.desk.run(self.w, 1000.0, 121)
        self.assertEqual(self.kinds(nudges, "break"), [60, 90, 120])        # then every 30 min if ignored
        self.assertEqual(self.kinds(nudges, "water"), [45])                 # half an interval in, then every 90
        self.assertEqual(self.kinds(nudges, "eye"), [20, 40, 80, 100])      # 60 and 120 gave way to the break
        self.assertTrue(all(n.spoken for n in self.w.tick(5000.0 + 200 * MIN, CONF) if n.kind != "eye"))

    def test_stepping_away_is_a_break(self):
        _, t = self.desk.run(self.w, 0.0, 50)
        self.desk.idle = 6 * MIN                 # away for six minutes
        self.assertEqual(self.w.tick(t, CONF), [])
        self.desk.idle = 0.0
        nudges, _ = self.desk.run(self.w, t, 50)
        self.assertEqual(self.kinds(nudges, "break"), [])   # the clock started again

    def test_nothing_while_busy_or_paused_or_away(self):
        self.desk.busy = True                    # focus block, game, or full-screen film
        nudges, t = self.desk.run(self.w, 0.0, 130)
        self.assertEqual(nudges, [])
        self.desk.busy = False
        self.w.paused_until = t + 30 * MIN
        self.assertEqual(self.desk.run(self.w, t, 29)[0], [])
        self.desk.idle = 3 * MIN                 # not touching the laptop, but not long enough to be a break
        self.assertEqual(self.w.tick(t + 40 * MIN, CONF), [])

    def test_eye_cues_are_never_spoken(self):
        nudges = [n for n in self.w.tick(0.0, CONF)] + [n for n in self.w.tick(21 * MIN, CONF)]
        self.assertEqual([(n.kind, n.spoken) for n in nudges], [("eye", False)])


class Storage(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = mock.patch.object(household, "get_data_dir", return_value=Path(tmp.name))
        p.start()
        self.addCleanup(p.stop)

    def test_water_and_settings(self):
        self.assertEqual(wellbeing.water_today(), 0)
        wellbeing.log_water()
        self.assertEqual(wellbeing.log_water(2), 3)
        r = wellbeing.WellbeingSettingsTool().run(kind="eye", enabled=False)
        self.assertIn("eye reminder off", r)
        self.assertFalse(wellbeing.settings()["eye"])
        wellbeing.WellbeingSettingsTool().run(kind="break", every_minutes=45)
        self.assertEqual(wellbeing.settings()["break_minutes"], 45)
        self.assertEqual(wellbeing.water_today(), 3)  # settings and water share a file safely


if __name__ == "__main__":
    unittest.main()
