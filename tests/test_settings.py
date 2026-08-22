"""Reading the settings file.

The settings file is the one thing a user edits by hand while the show is
running, so its grammar has to hold: a Directories: block which ends at the
first line that is not a directory, values which may be commented out to mean
"use the default", and names matched without regard to case.
"""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import load_ss                                 # noqa: E402

ss = load_ss()


class NameValueLines(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name)/"settings.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, text):
        self.path.write_text(text, encoding="utf-8")
        return ss.ReadSettings(str(self.path))

    def test_names_are_lowercased_and_values_kept(self):
        self.assertEqual(self.read("Display Time=7\n")["display time"], "7")
        self.assertEqual(self.read("DISPLAY TIME=7\n")["display time"], "7")

    def test_surrounding_space_is_ignored(self):
        self.assertEqual(self.read("  Title  =  photos.fanac.org  \n")["title"],
                         "photos.fanac.org")

    def test_blank_and_comment_lines_are_skipped(self):
        settings = self.read("# a comment\n\nTitle=Something\n\n# another\n")
        self.assertEqual(settings, {"title": "Something"})

    def test_a_commented_out_value_means_the_default(self):
        """The parameter must be absent, not present-and-empty: absent is what
        makes Get() fall back to the default."""
        self.assertNotIn("title font", self.read("Title Font=#Chicle\n"))
        self.assertNotIn("title font", self.read("Title Font=   # Chicle\n"))

    def test_a_value_may_contain_a_hash_elsewhere(self):
        self.assertEqual(self.read("Title=No. #1 in the series\n")["title"],
                         "No. #1 in the series")

    def test_a_line_without_an_equals_is_ignored(self):
        self.assertEqual(self.read("this line means nothing\nTitle=x\n"), {"title": "x"})

    def test_a_missing_file_reads_as_None(self):
        self.assertIsNone(ss.ReadSettings(str(self.path.parent/"not there.txt")))


class DirectoriesBlock(unittest.TestCase):
    """The Directories: line is followed by paths, one per line, and the list
    ends at the first line which is not a directory -- that line still being
    read as an ordinary parameter."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/"Photos").mkdir()
        (self.root/"More Photos").mkdir()
        self.path = self.root/"settings.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, text):
        self.path.write_text(text, encoding="utf-8")
        return ss.ReadSettings(str(self.path))

    def test_one_directory(self):
        settings = self.read(f"Directories:\n{self.root/'Photos'}\n")
        self.assertEqual(settings["directories"], [str(self.root/"Photos")])

    def test_several_directories(self):
        settings = self.read(f"Directories:\n{self.root/'Photos'}\n{self.root/'More Photos'}\n")
        self.assertEqual(len(settings["directories"]), 2)

    def test_the_list_ends_at_the_first_line_which_is_not_a_directory(self):
        settings = self.read(f"Directories:\n{self.root/'Photos'}\n"
                             f"{self.root/'Does Not Exist'}\n{self.root/'More Photos'}\n")
        self.assertEqual(settings["directories"], [str(self.root/"Photos")])

    def test_a_parameter_after_the_list_is_still_read(self):
        settings = self.read(f"Directories:\n{self.root/'Photos'}\nOrder=Random\n")
        self.assertEqual(settings["order"], "Random")
        self.assertEqual(len(settings["directories"]), 1)

    def test_blank_and_comment_lines_do_not_end_the_list(self):
        settings = self.read(f"Directories:\n\n# still going\n{self.root/'Photos'}\n")
        self.assertEqual(settings["directories"], [str(self.root/"Photos")])

    def test_the_header_alone_leaves_an_empty_list(self):
        """Which is what makes the startup check say so, rather than crashing."""
        self.assertEqual(self.read("Directories:\nOrder=Random\n")["directories"], [])

    def test_no_header_means_no_key_at_all(self):
        self.assertNotIn("directories", self.read("Order=Random\n"))


if __name__ == "__main__":
    unittest.main()
