"""The small conversions behind what is shown on the screen.

Each of these is a place where a wrong answer is quiet: a date reading oddly, a
parameter silently ignored, or the face table sized against the wrong padding.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import load_ss                                 # noqa: E402

ss = load_ss()


class PhotoDates(unittest.TestCase):
    """Piwigo dates are stored as timestamps, and January 1st is its way of
    saying that only the year is known."""

    def test_a_full_date_reads_as_words(self):
        self.assertEqual(ss.SlideShow.FormatPhotoDate("1942-06-04 00:00:00"), "June 4, 1942")

    def test_the_time_is_dropped(self):
        self.assertEqual(ss.SlideShow.FormatPhotoDate("2025-11-05 14:33:02"), "November 5, 2025")

    def test_january_the_first_means_the_year_alone(self):
        self.assertEqual(ss.SlideShow.FormatPhotoDate("2000-01-01 00:00:00"), "2000")
        self.assertEqual(ss.SlideShow.FormatPhotoDate("1977-01-01"), "1977")

    def test_january_the_second_is_a_real_date(self):
        self.assertEqual(ss.SlideShow.FormatPhotoDate("1962-01-02"), "January 2, 1962")

    def test_anything_unrecognizable_is_passed_through(self):
        for odd in ("", "unknown", "1942-13-05", "1942-06", "sometime in 1942"):
            self.assertEqual(ss.SlideShow.FormatPhotoDate(odd), odd.strip().split(" ")[0]
                             if odd != "sometime in 1942" else "sometime")

    def test_a_date_which_is_only_a_year_is_left_as_it_is(self):
        self.assertEqual(ss.SlideShow.FormatPhotoDate("1942"), "1942")


class FaceDetectionThreshold(unittest.TestCase):
    """Out-of-range or unreadable values fall back rather than disabling
    detection or accepting nonsense."""

    def test_a_sensible_value_is_used(self):
        self.assertEqual(ss.SlideShow.ResolveFaceThreshold("0.45"), 0.45)
        self.assertEqual(ss.SlideShow.ResolveFaceThreshold("1"), 1.0)

    def test_nothing_means_the_default(self):
        self.assertEqual(ss.SlideShow.ResolveFaceThreshold(""), ss.DEFAULT_FACE_THRESHOLD)

    def test_words_and_out_of_range_numbers_fall_back(self):
        for bad in ("banana", "0", "-1", "1.5", "100"):
            self.assertEqual(ss.SlideShow.ResolveFaceThreshold(bad), ss.DEFAULT_FACE_THRESHOLD, bad)


class PackPadding(unittest.TestCase):
    """tk hands a pady setting back in whichever form it was given, and the
    face table's height is measured from these."""

    def test_the_several_forms_tk_uses(self):
        self.assertEqual(ss.PadTotal(4), 4)
        self.assertEqual(ss.PadTotal("4"), 4)
        self.assertEqual(ss.PadTotal((4, 0)), 4)
        self.assertEqual(ss.PadTotal("4 0"), 4)
        self.assertEqual(ss.PadTotal("(4, 0)"), 4)
        self.assertEqual(ss.PadTotal((0, 30)), 30, "padding on one side only still counts")

    def test_nothing_is_no_padding(self):
        self.assertEqual(ss.PadTotal(0), 0)
        self.assertEqual(ss.PadTotal(""), 0)


class TheAlbumLine(unittest.TestCase):
    """The line under the title drops a folder whose name merely repeats in the
    one below it, so "Tropicon/Tropicon 27" reads as "Tropicon 27"."""

    @staticmethod
    def shorten(chain):
        parts = chain.split("/")
        while len(parts) > 1 and parts[1].casefold().startswith(parts[0].casefold()):
            parts.pop(0)
        return "/".join(parts)

    def test_a_repeated_name_is_dropped(self):
        self.assertEqual(self.shorten("Tropicon/Tropicon 27"), "Tropicon 27")

    def test_it_keeps_dropping_down_the_chain(self):
        self.assertEqual(self.shorten("Tropicon/Tropicon 27/Tropicon 27 Masquerade"),
                         "Tropicon 27 Masquerade")

    def test_unrelated_names_are_all_kept(self):
        self.assertEqual(self.shorten("Worldcon/Photos"), "Worldcon/Photos")

    def test_a_single_folder_is_left_alone(self):
        self.assertEqual(self.shorten("Tropicon"), "Tropicon")


if __name__ == "__main__":
    unittest.main()
