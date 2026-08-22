"""Photo shows: which folders a show stands for, and the shows file.

A show is a list of folders, each standing for itself and everything below it.
Two rules matter to what a visitor sees: a folder already covered by another
must not be scanned twice, and a folder which has been deleted must be passed
over rather than stopping the show.
"""
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import load_ss, build_tree, bare_show          # noqa: E402

ss = load_ss()


class FolderPaths(unittest.TestCase):
    def test_normalize_accepts_either_separator(self):
        self.assertEqual(ss.NormalizeFolder("a\\b"), "a/b")
        self.assertEqual(ss.NormalizeFolder("/a/b/"), "a/b")

    def test_covered_by_is_about_whole_folder_names(self):
        self.assertTrue(ss.IsCoveredBy("A/B", "A"))
        self.assertTrue(ss.IsCoveredBy("A/B/C", "A/B"))
        self.assertTrue(ss.IsCoveredBy("A", "A"), "a folder covers itself")
        self.assertFalse(ss.IsCoveredBy("AB", "A"), "a name is not a folder")
        self.assertFalse(ss.IsCoveredBy("A", "A/B"), "a parent is not covered by its child")

    def test_covered_by_ignores_case(self):
        self.assertTrue(ss.IsCoveredBy("fan photos/LASFS", "Fan Photos"))

    def test_prune_drops_folders_another_already_covers(self):
        self.assertEqual(ss.PruneFolders(["Fan Photos", "Fan Photos/LASFS"]), ["Fan Photos"])

    def test_prune_keeps_folders_which_do_not_overlap(self):
        self.assertEqual(ss.PruneFolders(["A/B", "A/C", "D"]), ["A/B", "A/C", "D"])

    def test_prune_removes_duplicates_and_empties(self):
        self.assertEqual(ss.PruneFolders(["A", "A", "", "/A/"]), ["A"])


class WhatAShowStandsFor(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = build_tree(Path(self.tmp.name), {
            "Fan Photos": ["a.jpg"],
            "Fan Photos/LASFS": ["b.jpg"],
            "Worldcons": ["c.jpg"]})

    def tearDown(self):
        self.tmp.cleanup()

    def folders(self, show):
        show_obj = bare_show(ss, rootDirectory=str(self.root), tlds=[], shows=[show])
        return [Path(p).relative_to(self.root).as_posix() for p in show_obj.ShowFolders(show["name"])]

    def test_a_folder_stands_for_itself(self):
        self.assertEqual(self.folders({"name": "S", "folders": ["Worldcons"]}), ["Worldcons"])

    def test_a_folder_inside_a_chosen_one_is_dropped(self):
        """Otherwise its photos would be shown twice."""
        self.assertEqual(self.folders({"name": "S", "folders": ["Fan Photos", "Fan Photos/LASFS"]}),
                         ["Fan Photos"])

    def test_a_folder_which_no_longer_exists_is_passed_over(self):
        self.assertEqual(self.folders({"name": "S", "folders": ["Worldcons", "Gone/Missing"]}),
                         ["Worldcons"])

    def test_a_show_of_nothing_but_missing_folders_is_empty(self):
        self.assertEqual(self.folders({"name": "S", "folders": ["Gone", "Also/Gone"]}), [])


class TheShowsFile(unittest.TestCase):
    """The file holds only the shows built in the editor.  All Photos is built
    in, and the shows older versions made up from the top-level folders are
    cleared out the first time such a file is read."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = build_tree(Path(self.tmp.name)/"photos", {
            "Fan Photos": ["a.jpg"], "Worldcons": ["b.jpg"]})
        self.showsPath = Path(self.tmp.name)/"shows.json"
        self.show = bare_show(
            ss, rootDirectory=str(self.root), showsPath=str(self.showsPath), shows=[],
            tlds=[str(self.root/"Fan Photos"), str(self.root/"Worldcons")])

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data):
        self.showsPath.write_text(json.dumps(data), encoding="utf-8")

    def test_no_file_means_no_shows_of_your_own(self):
        self.assertEqual(self.show.LoadShows(), [])

    def test_all_photos_is_built_in_and_offered_first(self):
        self.show.shows = []
        offered = self.show.AllShows()
        self.assertEqual(offered[0]["name"], ss.ALL_PHOTOS)
        self.assertEqual(offered[0]["folders"], ["Fan Photos", "Worldcons"])

    def test_all_photos_follows_the_root_rather_than_being_stored(self):
        """A top-level folder added later must appear in it without an edit."""
        (self.root/"New Album").mkdir()
        self.show.tlds.append(str(self.root/"New Album"))
        self.assertIn("New Album", self.show.AllShows()[0]["folders"])

    def test_your_own_shows_are_read_back(self):
        self.write({"version": ss.SHOWS_VERSION,
                    "shows": [{"name": "Mine", "folders": ["Worldcons"], "except": ["Worldcons/LAcon"]}]})
        self.assertEqual(self.show.LoadShows(),
                         [{"name": "Mine", "folders": ["Worldcons"], "except": ["Worldcons/LAcon"]}])

    def test_a_show_with_nothing_left_out_reads_back_with_an_empty_list(self):
        """So the rest of the code never has to ask whether the key is there."""
        self.write({"version": ss.SHOWS_VERSION, "shows": [{"name": "Mine", "folders": ["Worldcons"]}]})
        self.assertEqual(self.show.LoadShows(), [{"name": "Mine", "folders": ["Worldcons"], "except": []}])

    def test_an_old_file_loses_its_made_up_shows(self):
        """Version 1 stored All Photos and one show per top-level folder; only
        what the user built themselves survives."""
        self.write({"shows": [
            {"name": "All Photos", "folders": ["Fan Photos", "Worldcons"]},
            {"name": "Fan Photos", "folders": ["Fan Photos"]},
            {"name": "Worldcons", "folders": ["Worldcons"]},
            {"name": "Mine", "folders": ["Fan Photos/LASFS"]}]})
        self.assertEqual([s["name"] for s in self.show.LoadShows()], ["Mine"])
        self.assertTrue(self.show.showsMigrated, "the tidied file wants writing back")

    def test_a_current_file_is_left_alone(self):
        """The same shapes are legitimate once the user has made them."""
        self.write({"version": ss.SHOWS_VERSION, "shows": [{"name": "Worldcons", "folders": ["Worldcons"]}]})
        self.assertEqual([s["name"] for s in self.show.LoadShows()], ["Worldcons"])
        self.assertFalse(self.show.showsMigrated)

    def test_a_version_2_file_keeps_its_shows_and_is_restamped(self):
        """Version 2 had no way to leave a folder out again; nothing else changed."""
        self.write({"version": 2, "shows": [{"name": "Mine", "folders": ["Worldcons"]}]})
        self.assertEqual([s["name"] for s in self.show.LoadShows()], ["Mine"])
        self.assertTrue(self.show.showsMigrated, "so the version stamp is brought up to date")

    def test_rubbish_in_the_file_is_survivable(self):
        self.showsPath.write_text("{ this is not json", encoding="utf-8")
        self.assertEqual(self.show.LoadShows(), [])

    def test_saving_stamps_the_version(self):
        self.show.shows = [{"name": "Mine", "folders": ["Worldcons"], "except": []}]
        self.show.SaveShows()
        written = json.loads(self.showsPath.read_text(encoding="utf-8"))
        self.assertEqual(written["version"], ss.SHOWS_VERSION)

    def test_a_show_with_nothing_left_out_is_written_plainly(self):
        """An empty except list is left out of the file, so a plain show stays plain."""
        self.show.shows = [{"name": "Mine", "folders": ["Worldcons"], "except": []}]
        self.show.SaveShows()
        written = json.loads(self.showsPath.read_text(encoding="utf-8"))
        self.assertEqual(written["shows"], [{"name": "Mine", "folders": ["Worldcons"]}])

    def test_what_is_left_out_is_written_down(self):
        self.show.shows = [{"name": "Mine", "folders": ["Fan Photos"], "except": ["Fan Photos/LASFS"]}]
        self.show.SaveShows()
        written = json.loads(self.showsPath.read_text(encoding="utf-8"))
        self.assertEqual(written["shows"][0]["except"], ["Fan Photos/LASFS"])


class FindingThePhotos(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = build_tree(Path(self.tmp.name), {
            "Album": ["b.jpg", "a.JPG", "notes.txt", "c.png", "d.tiff", "e.doc"],
            "Album/Sub": ["f.jpeg"]})

    def tearDown(self):
        self.tmp.cleanup()

    def test_pictures_are_found_at_any_depth_and_sorted(self):
        found = [Path(p).name for p in ss.SlideShow.ScanImages([str(self.root/"Album")])]
        self.assertEqual(found, ["a.JPG", "b.jpg", "c.png", "d.tiff", "f.jpeg"])

    def test_files_which_are_not_pictures_are_left_out(self):
        found = [Path(p).name for p in ss.SlideShow.ScanImages([str(self.root)])]
        self.assertNotIn("notes.txt", found)
        self.assertNotIn("e.doc", found)

    def test_the_top_level_directories_are_the_available_shows(self):
        (self.root/"Album"/"Sub"/"Deeper").mkdir()
        tlds = [Path(p).name for p in ss.SlideShow.FindTLDs(str(self.root))]
        self.assertEqual(tlds, ["Album"], "only the immediate subdirectories")


if __name__ == "__main__":
    unittest.main()
