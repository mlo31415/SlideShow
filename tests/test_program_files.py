"""Where the program looks for its files, built or unbuilt.

PyInstaller unpacks a frozen program into a temporary folder and points
__file__ at it.  Anything the *user* keeps -- the settings, the shows, the
state, the output logs -- must therefore be looked for beside the executable,
not beside __file__, or a built SlideShow reads a settings file nobody can
edit and writes its logs where they are thrown away.  That is exactly what
went wrong the first time SlideShow.exe was built.
"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import load_ss                                 # noqa: E402

ss = load_ss()


class Frozen(unittest.TestCase):
    """Pretend PyInstaller built it: sys.frozen is set, sys.executable is the
    .exe, and sys._MEIPASS is the temporary unpacking folder."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.beside = Path(self.tmp.name)/"beside the exe"
        self.unpacked = Path(self.tmp.name)/"_MEI000050d82"
        self.beside.mkdir()
        self.unpacked.mkdir()
        self.saved = (getattr(sys, "frozen", None), sys.executable, getattr(sys, "_MEIPASS", None))
        sys.frozen = True
        sys.executable = str(self.beside/"SlideShow.exe")
        sys._MEIPASS = str(self.unpacked)

    def tearDown(self):
        frozen, executable, meipass = self.saved
        if frozen is None:
            del sys.frozen
        else:
            sys.frozen = frozen
        sys.executable = executable
        if meipass is None:
            del sys._MEIPASS
        else:
            sys._MEIPASS = meipass
        self.tmp.cleanup()

    def test_the_users_files_are_beside_the_executable(self):
        self.assertEqual(ss.ProgramDirectory(), str(self.beside))

    def test_not_in_the_unpacking_folder(self):
        """The bug: the settings file was looked for inside _MEI000050d82."""
        self.assertNotIn("_MEI", ss.ProgramDirectory())

    def test_a_file_built_into_the_program_comes_from_the_unpacking_folder(self):
        (self.unpacked/"face_detection_yunet_2023mar.onnx").write_text("", encoding="utf-8")
        self.assertEqual(ss.BundledFile("face_detection_yunet_2023mar.onnx"),
                         str(self.unpacked/"face_detection_yunet_2023mar.onnx"))

    def test_one_which_was_not_built_in_is_looked_for_beside_the_executable(self):
        """So a model or icon left sitting next to the .exe is still found."""
        (self.beside/"SlideShow.ico").write_text("", encoding="utf-8")
        self.assertEqual(ss.BundledFile("SlideShow.ico"), str(self.beside/"SlideShow.ico"))

    def test_a_file_which_is_nowhere_names_the_place_it_should_be(self):
        self.assertEqual(ss.BundledFile("missing.onnx"), str(self.beside/"missing.onnx"))


class NotFrozen(unittest.TestCase):
    """Run from the source, everything sits beside SlideShow.py as before."""

    def test_the_program_directory_is_the_source_directory(self):
        self.assertEqual(ss.ProgramDirectory(), str(Path(ss.__file__).resolve().parent))

    def test_a_bundled_file_is_looked_for_there_too(self):
        self.assertEqual(ss.BundledFile("SlideShow.ico"),
                         os.path.join(str(Path(ss.__file__).resolve().parent), "SlideShow.ico"))


if __name__ == "__main__":
    unittest.main()
