"""The order photographs are shown in, and moving along it.

A show settles its order once, when it is picked, and is then walked round
and round.  Two things follow, and both are the point of doing it that way:
every photograph appears once per pass, and Next and Prev are exact
opposites -- stepping back and forward retraces the same photographs rather
than inventing new ones.
"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import bare_show, load_ss                        # noqa: E402

ss = load_ss()


def show(count, randomOrder=True, seed=20260826):
    """A show of `count` photographs with its order settled, and ShowImage
    stubbed out: what is on screen is a window matter, the order is not."""
    random.seed(seed)
    s = bare_show(ss, images=[f"photo{i}.jpg" for i in range(count)],
                  randomOrder=randomOrder, order=[], orderPos=-1)
    s.ShowImage = lambda: None
    s.SetOrder()
    return s


def walk(s, steps):
    """The photographs a run of Next shows, in order."""
    seen = []
    for _ in range(steps):
        s.NextImage()
        seen.append(s.images[s.order[s.orderPos]])
    return seen


class OrderOfAPass(unittest.TestCase):

    def test_every_photo_appears_once_in_a_pass(self):
        s = show(20)
        self.assertCountEqual(walk(s, 20), s.images)

    def test_the_random_order_is_not_the_folder_order(self):
        s = show(40)
        self.assertNotEqual(walk(s, 40), s.images)

    def test_the_same_order_comes_round_again(self):
        """Circular: the show settled one order and keeps to it."""
        s = show(12)
        self.assertEqual(walk(s, 12), walk(s, 12))

    def test_sequential_order_is_the_folder_order(self):
        s = show(10, randomOrder=False)
        self.assertEqual(walk(s, 10), s.images)

    def test_two_shows_get_different_orders(self):
        self.assertNotEqual(walk(show(40, seed=1), 40), walk(show(40, seed=2), 40))


class NextAndPrevAreOpposites(unittest.TestCase):
    """The reason for settling the order in advance."""

    def test_prev_undoes_next(self):
        s = show(15)
        walk(s, 6)
        here = s.orderPos
        s.NextImage()
        s.PrevImage()
        self.assertEqual(s.orderPos, here)

    def test_stepping_back_retraces_the_same_photos(self):
        s = show(15)
        forwards = walk(s, 9)
        backwards = []
        for _ in range(8):
            s.PrevImage()
            backwards.append(s.images[s.order[s.orderPos]])
        self.assertEqual(backwards, list(reversed(forwards[:-1])))

    def test_prev_from_the_first_photo_wraps_to_the_last(self):
        s = show(7)
        s.NextImage()                               # On the first of the order
        self.assertEqual(s.orderPos, 0)
        s.PrevImage()
        self.assertEqual(s.orderPos, 6, "the show is a circle both ways")

    def test_next_from_the_last_photo_wraps_to_the_first(self):
        s = show(7)
        walk(s, 7)
        self.assertEqual(s.orderPos, 6)
        s.NextImage()
        self.assertEqual(s.orderPos, 0)


class ChangingShow(unittest.TestCase):

    def test_a_new_list_settles_a_new_order(self):
        s = show(10)
        walk(s, 4)
        s.images = [f"other{i}.jpg" for i in range(6)]
        s.SetOrder()
        self.assertEqual(s.orderPos, -1, "the new show starts at the beginning of its order")
        self.assertCountEqual(walk(s, 6), s.images)

    def test_one_photo_shows_shave_a_workable_order(self):
        s = show(1)
        self.assertEqual(walk(s, 3), ["photo0.jpg"]*3)

    def test_an_empty_show_does_not_break_next(self):
        s = show(0)
        s.NextImage()                               # Must not divide by zero
        s.PrevImage()
        self.assertEqual(s.orderPos, -1)


if __name__ == "__main__":
    unittest.main()
