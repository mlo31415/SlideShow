"""Random order deals the photographs out rather than drawing them at random.

Each photograph is shown once before any is shown twice.  Drawing
independently instead -- which is what SlideShow used to do -- shows some
three times before others appear at all, which over a convention day means a
visitor can miss the very photograph they could have identified.
"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import bare_show, load_ss                        # noqa: E402

ss = load_ss()


def show(images, history=()):
    return bare_show(ss, images=list(images), history=list(history),
                     unshown=[], unshownFrom=None)


def deal(s, count):
    """The next `count` photographs, recording each in the history as
    NextImage does, so the no-repeat rule sees what it would really see."""
    drawn = []
    for _ in range(count):
        index = s.NextRandomIndex()
        s.history.append(index)
        drawn.append(index)
    return drawn


class OnePassThroughThePack(unittest.TestCase):

    def setUp(self):
        random.seed(20260826)

    def test_every_photo_appears_once_before_any_appears_twice(self):
        s = show(range(20))
        self.assertCountEqual(deal(s, 20), range(20))

    def test_and_the_pack_is_dealt_again_after_that(self):
        s = show(range(8))
        first, second = deal(s, 8), deal(s, 8)
        self.assertCountEqual(first, range(8))
        self.assertCountEqual(second, range(8))

    def test_the_order_is_not_the_order_of_the_folder(self):
        s = show(range(40))
        self.assertNotEqual(deal(s, 40), list(range(40)), "dealt in file order is not random")

    def test_two_passes_differ(self):
        s = show(range(40))
        self.assertNotEqual(deal(s, 40), deal(s, 40))


class NoImmediateRepeat(unittest.TestCase):
    """The join between one pass and the next is the only place a photograph
    could follow itself, since within a pass it has been taken out of the pack."""

    def test_no_photo_follows_itself_across_many_passes(self):
        random.seed(7)
        s = show(range(5))
        drawn = deal(s, 500)
        repeats = [i for i in range(1, len(drawn)) if drawn[i] == drawn[i-1]]
        self.assertEqual(repeats, [], "a photograph was shown twice running")

    def test_a_single_photo_show_still_works(self):
        """With one photograph there is nothing else to move to, so it repeats."""
        random.seed(1)
        s = show([0])
        self.assertEqual(deal(s, 3), [0, 0, 0])


class ChangingShow(unittest.TestCase):

    def test_a_new_list_deals_a_fresh_pack(self):
        random.seed(3)
        s = show(range(10))
        deal(s, 4)
        s.images = list(range(100, 106))         # Another show was picked
        self.assertCountEqual(deal(s, 6), range(6), "the pack must be dealt from the new list")

    def test_the_same_list_keeps_dealing_where_it_left_off(self):
        random.seed(3)
        s = show(range(10))
        first = deal(s, 4)
        rest = deal(s, 6)
        self.assertCountEqual(first+rest, range(10), "the pack was re-dealt when it should not have been")


if __name__ == "__main__":
    unittest.main()
