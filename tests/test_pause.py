"""Pausing and starting the show.

Touching the photo is bound straight to OnPauseContinue, so the photo and the
Pause/Start Slideshow button are one action with one set of rules.  What matters
is the guard: while the Identify Photo panel is up the show is deliberately held
paused, and a stray touch on the photo -- easily done on a touch screen while
somebody is typing a name -- must not start it running under them.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import bare_show, load_ss                        # noqa: E402

ss = load_ss()


def show(paused, dialogOpen=False):
    """A show which records what the pause machinery asked the display to do."""
    s = bare_show(ss, paused=paused, dialogOpen=dialogOpen, advance=[])
    s.CancelAdvance = lambda: s.advance.append("cancelled")
    s.ScheduleAdvance = lambda: s.advance.append("scheduled")
    s.UpdateButtonStates = lambda: None
    return s


class TouchingThePhoto(unittest.TestCase):

    def test_a_running_show_stops(self):
        s = show(paused=False)
        s.OnPauseContinue()
        self.assertTrue(s.paused)
        self.assertEqual(s.advance, ["cancelled"])

    def test_a_paused_show_starts(self):
        s = show(paused=True)
        s.OnPauseContinue()
        self.assertFalse(s.paused)
        self.assertEqual(s.advance, ["scheduled"])

    def test_it_is_a_toggle(self):
        s = show(paused=False)
        s.OnPauseContinue()
        s.OnPauseContinue()
        self.assertFalse(s.paused)
        self.assertEqual(s.advance, ["cancelled", "scheduled"])


class WhileIdentifying(unittest.TestCase):
    """dialogOpen is set for the whole time the Identify Photo panel is up."""

    def test_touching_the_photo_does_not_start_the_show(self):
        s = show(paused=True, dialogOpen=True)
        s.OnPauseContinue()
        self.assertTrue(s.paused, "the show must stay paused while faces are being identified")
        self.assertEqual(s.advance, [])

    def test_and_does_not_stop_one_either(self):
        s = show(paused=False, dialogOpen=True)
        s.OnPauseContinue()
        self.assertFalse(s.paused)
        self.assertEqual(s.advance, [])


if __name__ == "__main__":
    unittest.main()
