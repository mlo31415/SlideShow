"""Ticking folders in the Edit Photo Shows dialog.

A show says which folders are in it and which are left out again, each standing
for itself and everything below it, and the most specific of those decides.
Ticking a folder takes it and everything below; unticking leaves out it and
everything below; neither touches the folder's parent or its brothers and
sisters.  This is that arithmetic, tested without a window.
"""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import load_ss, build_tree, bare_editor        # noqa: E402

ss = load_ss()


class TheRule(unittest.TestCase):
    """Of the entries covering a folder, the most specific one decides."""

    def test_a_chosen_folder_is_in(self):
        self.assertTrue(ss.FolderIsIncluded("A", ["A"], []))

    def test_everything_below_a_chosen_folder_is_in(self):
        self.assertTrue(ss.FolderIsIncluded("A/B/C", ["A"], []))

    def test_a_folder_nobody_mentioned_is_out(self):
        self.assertFalse(ss.FolderIsIncluded("B", ["A"], []))

    def test_a_folder_left_out_is_out(self):
        self.assertFalse(ss.FolderIsIncluded("A/B", ["A"], ["A/B"]))

    def test_everything_below_one_left_out_is_out(self):
        self.assertFalse(ss.FolderIsIncluded("A/B/C", ["A"], ["A/B"]))

    def test_the_rest_of_the_chosen_folder_is_still_in(self):
        self.assertTrue(ss.FolderIsIncluded("A/D", ["A"], ["A/B"]))
        self.assertTrue(ss.FolderIsIncluded("A", ["A"], ["A/B"]), "including the folder itself")

    def test_something_chosen_again_below_what_was_left_out(self):
        self.assertTrue(ss.FolderIsIncluded("A/B/C", ["A", "A/B/C"], ["A/B"]))
        self.assertFalse(ss.FolderIsIncluded("A/B/D", ["A", "A/B/C"], ["A/B"]))


class TidyingTheRules(unittest.TestCase):
    """What is stored is what the user actually said, and no more."""

    def test_a_folder_inside_a_chosen_one_is_dropped(self):
        self.assertEqual(ss.TidyRules(["A", "A/B"], []), (["A"], []))

    def test_unless_something_is_left_out_in_between(self):
        chosen, excluded = ss.TidyRules(["A", "A/B/C"], ["A/B"])
        self.assertEqual((chosen, excluded), (["A", "A/B/C"], ["A/B"]))

    def test_leaving_out_what_was_never_in_says_nothing(self):
        self.assertEqual(ss.TidyRules(["A"], ["B/C"]), (["A"], []))

    def test_leaving_out_the_same_thing_twice_over_says_nothing(self):
        self.assertEqual(ss.TidyRules(["A"], ["A/B", "A/B/C"]), (["A"], ["A/B"]))


class Ticking(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = build_tree(Path(self.tmp.name), {
            "Fan Photos": ["party.jpg"],                    # a photo loose in the parent
            "Fan Photos/Ackermansion": ["a.jpg"],
            "Fan Photos/LASFS": ["clubhouse.jpg"],          # and one in the middle folder
            "Fan Photos/LASFS/1941-1943": ["c.jpg"],
            "Fan Photos/NESFA": ["d.jpg"],
            "Worldcons": ["e.jpg"]})

    def tearDown(self):
        self.tmp.cleanup()

    def editor(self, selected=(), excluded=()):
        return bare_editor(ss, self.root, selected, excluded)

    def photos(self, editor):
        """The photos this selection would actually show."""
        chosen, excluded = ss.TidyRules(editor.selected, editor.excluded)
        roots = [self.root/f.replace("/", "\\") for f in chosen]
        keepOut = [str(self.root/f.replace("/", "\\")) for f in excluded]
        return sorted(Path(p).name for p in
                      ss.SlideShow.ScanImages([str(r) for r in roots if r.is_dir()], keepOut))

    # ── how a folder shows ───────────────────────────────────────────────────
    def test_a_ticked_folder_and_everything_below_it_is_ticked(self):
        editor = self.editor(["Fan Photos"])
        self.assertTrue(editor.IsIncluded("Fan Photos"))
        self.assertTrue(editor.IsIncluded("Fan Photos/LASFS/1941-1943"))

    def test_a_folder_left_out_is_not_ticked_but_its_parent_still_is(self):
        editor = self.editor(["Fan Photos"], ["Fan Photos/LASFS"])
        self.assertFalse(editor.IsIncluded("Fan Photos/LASFS"))
        self.assertTrue(editor.IsIncluded("Fan Photos"))
        self.assertTrue(editor.IsIncluded("Fan Photos/NESFA"))

    # ── ticking and unticking ────────────────────────────────────────────────
    def test_ticking_takes_the_folder_and_everything_below(self):
        editor = self.editor()
        editor.Toggle("Fan Photos")
        self.assertEqual(self.photos(editor),
                         ["a.jpg", "c.jpg", "clubhouse.jpg", "d.jpg", "party.jpg"])

    def test_unticking_a_folder_of_its_own_removes_it(self):
        editor = self.editor(["Fan Photos", "Worldcons"])
        editor.Toggle("Fan Photos")
        self.assertEqual(self.photos(editor), ["e.jpg"])

    def test_unticking_inside_a_ticked_folder_leaves_only_that_folder_out(self):
        """SS-19: the photos loose in the folders above it must stay in the show."""
        editor = self.editor(["Fan Photos"])
        editor.Toggle("Fan Photos/LASFS/1941-1943")
        self.assertEqual(self.photos(editor), ["a.jpg", "clubhouse.jpg", "d.jpg", "party.jpg"])
        self.assertNotIn("c.jpg", self.photos(editor), "the folder unticked, as asked")

    def test_unticking_a_whole_branch_leaves_out_what_is_below_it(self):
        editor = self.editor(["Fan Photos"])
        editor.Toggle("Fan Photos/LASFS")
        self.assertEqual(self.photos(editor), ["a.jpg", "d.jpg", "party.jpg"])

    def test_ticking_the_parent_again_brings_everything_back(self):
        """Unticking then ticking a folder clears whatever was said inside it, so
        rules can never pile up out of sight."""
        editor = self.editor(["Fan Photos"])
        editor.Toggle("Fan Photos/LASFS")
        editor.Toggle("Fan Photos")                          # untick the parent
        editor.Toggle("Fan Photos")                          # and tick it again
        self.assertEqual(self.photos(editor),
                         ["a.jpg", "c.jpg", "clubhouse.jpg", "d.jpg", "party.jpg"])
        self.assertEqual(editor.excluded, set(), "nothing left over from before")

    def test_ticking_a_folder_which_was_left_out_puts_it_back(self):
        editor = self.editor(["Fan Photos"], ["Fan Photos/LASFS"])
        editor.Toggle("Fan Photos/LASFS")
        self.assertTrue(editor.IsIncluded("Fan Photos/LASFS"))
        self.assertEqual(editor.excluded, set())

    def test_neither_parents_nor_brothers_and_sisters_are_touched(self):
        editor = self.editor(["Fan Photos"])
        editor.Toggle("Fan Photos/LASFS")
        self.assertTrue(editor.IsIncluded("Fan Photos"), "the parent stays in")
        self.assertTrue(editor.IsIncluded("Fan Photos/NESFA"), "and so do its brothers")
        self.assertFalse(editor.IsIncluded("Worldcons"), "an unrelated folder is unaffected")

    def test_ticking_a_folder_inside_one_left_out(self):
        editor = self.editor(["Fan Photos"], ["Fan Photos/LASFS"])
        editor.Toggle("Fan Photos/LASFS/1941-1943")
        self.assertEqual(self.photos(editor), ["a.jpg", "c.jpg", "d.jpg", "party.jpg"])
        self.assertNotIn("clubhouse.jpg", self.photos(editor), "LASFS itself is still out")

    # ── what the user is shown about it ──────────────────────────────────────
    def test_the_rows_note_what_is_hidden_below_them(self):
        editor = self.editor(["Fan Photos"], ["Fan Photos/LASFS"])
        self.assertEqual(editor.RulesUnder("Fan Photos"), (0, 1))
        self.assertEqual(editor.RulesUnder("Worldcons"), (0, 0))

    def test_the_show_reads_as_a_sentence(self):
        self.assertEqual(self.editor(["Worldcons"]).SummaryText(), "Worldcons")
        self.assertEqual(self.editor(["Fan Photos"], ["Fan Photos/LASFS"]).SummaryText(),
                         "all of Fan Photos except LASFS")
        self.assertEqual(self.editor().SummaryText(), "No folders chosen")

    def test_the_folders_offered_are_the_ones_on_disk(self):
        self.assertEqual([Path(f).name for f in self.editor().ChildFolders("Fan Photos")],
                         ["Ackermansion", "LASFS", "NESFA"])
        self.assertEqual(self.editor().ChildFolders("Worldcons"), [],
                         "a folder with no subfolders has nothing to open")


if __name__ == "__main__":
    unittest.main()
