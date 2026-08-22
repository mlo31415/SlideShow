"""Ticking folders in the Edit Photo Shows dialog.

A ticked folder stands for everything below it, which makes unticking one of
its subfolders the interesting case: the rest of that folder has to stay in the
show.  This is the arithmetic behind the check boxes, tested without a window.
"""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import load_ss, build_tree, bare_editor        # noqa: E402

ss = load_ss()


class Ticking(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = build_tree(Path(self.tmp.name), {
            "Fan Photos": [],
            "Fan Photos/Ackermansion": ["a.jpg"],
            "Fan Photos/LASFS": ["b.jpg"],
            "Fan Photos/LASFS/1941-1943": ["c.jpg"],
            "Fan Photos/NESFA": ["d.jpg"],
            "Worldcons": ["e.jpg"]})

    def tearDown(self):
        self.tmp.cleanup()

    def editor(self, selected=()):
        return bare_editor(ss, self.root, selected)

    # ── how a folder shows ───────────────────────────────────────────────────
    def test_a_ticked_folder_is_ticked(self):
        self.assertEqual(self.editor(["Fan Photos"]).State("Fan Photos"), "checked")

    def test_everything_below_a_ticked_folder_is_ticked(self):
        editor = self.editor(["Fan Photos"])
        self.assertEqual(editor.State("Fan Photos/LASFS"), "checked")
        self.assertEqual(editor.State("Fan Photos/LASFS/1941-1943"), "checked")

    def test_a_folder_with_something_ticked_inside_is_partly_ticked(self):
        self.assertEqual(self.editor(["Fan Photos/LASFS"]).State("Fan Photos"), "partial")

    def test_anything_else_is_unticked(self):
        self.assertEqual(self.editor(["Fan Photos"]).State("Worldcons"), "unchecked")

    # ── ticking and unticking ────────────────────────────────────────────────
    def test_ticking_a_folder_adds_it(self):
        editor = self.editor()
        editor.Toggle("Worldcons")
        self.assertEqual(editor.selected, {"Worldcons"})

    def test_ticking_a_folder_absorbs_the_ones_inside_it(self):
        """They would be redundant, and would scan the same photos twice."""
        editor = self.editor(["Fan Photos/LASFS", "Fan Photos/NESFA", "Worldcons"])
        editor.Toggle("Fan Photos")
        self.assertEqual(editor.selected, {"Fan Photos", "Worldcons"})

    def test_unticking_a_folder_which_was_ticked_removes_it(self):
        editor = self.editor(["Fan Photos", "Worldcons"])
        editor.Toggle("Fan Photos")
        self.assertEqual(editor.selected, {"Worldcons"})

    def test_unticking_inside_a_ticked_folder_keeps_the_rest(self):
        """The parent goes, and its other children take its place, so only the
        folder that was unticked leaves the show."""
        editor = self.editor(["Fan Photos"])
        editor.Toggle("Fan Photos/LASFS")
        self.assertEqual(editor.selected, {"Fan Photos/Ackermansion", "Fan Photos/NESFA"})
        self.assertEqual(editor.State("Fan Photos/LASFS"), "unchecked")
        self.assertEqual(editor.State("Fan Photos/NESFA"), "checked")
        self.assertEqual(editor.State("Fan Photos"), "partial")

    def test_unticking_deep_inside_a_ticked_folder_keeps_the_other_branches(self):
        editor = self.editor(["Fan Photos"])
        editor.Toggle("Fan Photos/LASFS/1941-1943")
        self.assertEqual(editor.State("Fan Photos/LASFS/1941-1943"), "unchecked")
        self.assertEqual(editor.State("Fan Photos/Ackermansion"), "checked")
        self.assertEqual(editor.State("Fan Photos/NESFA"), "checked")
        # LASFS held nothing else, so nothing under it is chosen any more
        self.assertEqual(editor.State("Fan Photos/LASFS"), "unchecked")

    def test_ticking_it_again_puts_it_back(self):
        editor = self.editor(["Fan Photos"])
        editor.Toggle("Fan Photos/LASFS")
        editor.Toggle("Fan Photos/LASFS")
        self.assertEqual(editor.State("Fan Photos/LASFS"), "checked")
        self.assertEqual(editor.State("Fan Photos/NESFA"), "checked")

    def test_what_is_stored_never_overlaps(self):
        editor = self.editor(["Fan Photos"])
        editor.Toggle("Fan Photos/LASFS/1941-1943")
        self.assertEqual(sorted(editor.selected), ss.PruneFolders(editor.selected),
                         "a stored folder is never inside another")

    def test_unticking_inside_a_folder_loses_that_folder_s_own_photos(self):
        """KNOWN LIMITATION -- finding SS-19, recorded rather than accepted.

        A show can only say "this folder and everything below it", so unticking
        something inside a ticked folder is done by putting that folder's other
        *folders* in its place.  Photos sitting directly in the folders along
        the way have no folder of their own and so drop out of the show, though
        the visitor only meant to exclude the one folder they unticked.

        This test states what happens today.  When SS-19 is fixed -- most
        likely by recording exclusions instead of rewriting the selection --
        it should fail, and the expectations below are the ones to change.
        """
        build_tree(self.root, {"Fan Photos": ["party.jpg"],
                               "Fan Photos/LASFS": ["clubhouse.jpg"]})
        editor = self.editor(["Fan Photos"])
        before = self.photos(editor.selected)
        editor.Toggle("Fan Photos/LASFS/1941-1943")
        after = self.photos(editor.selected)
        self.assertIn("party.jpg", before)
        self.assertNotIn("party.jpg", after, "the parent folder's own photo goes too")
        self.assertNotIn("clubhouse.jpg", after, "and so does the middle folder's")
        self.assertNotIn("c.jpg", after, "the folder actually unticked, as asked")
        self.assertIn("a.jpg", after, "an untouched branch stays")

    def photos(self, selected):
        """The photos a selection would actually show."""
        folders = [self.root/f.replace("/", "\\") for f in ss.PruneFolders(selected)]
        return sorted(Path(p).name for p in
                      ss.SlideShow.ScanImages([str(f) for f in folders if f.is_dir()]))

    def test_the_folders_offered_are_the_ones_on_disk(self):
        self.assertEqual([Path(f).name for f in self.editor().ChildFolders("Fan Photos")],
                         ["Ackermansion", "LASFS", "NESFA"])
        self.assertEqual(self.editor().ChildFolders("Worldcons"), [],
                         "a folder with no subfolders has nothing to open")


if __name__ == "__main__":
    unittest.main()
