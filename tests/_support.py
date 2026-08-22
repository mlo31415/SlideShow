"""Load SlideShow.py for testing without starting the application.

Importing the module is safe: it defines its constants, helpers and classes,
but opens no window and reads no file until SlideShow() is instantiated.  That
is what lets the pure parts be tested with no display and no photo collection.

Where the code worth testing is a method rather than a plain function, the
tests build a *bare* object with object.__new__ and give it only the attributes
that method uses.  No Tk root is ever created, so the suite opens no windows.
"""
import importlib.util
import sys
from pathlib import Path

_HERE    = Path(__file__).resolve().parent
_APP_DIR = _HERE.parent

if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

_MODULE_NAME = "slideshow_under_test"


def load_ss():
    """The SlideShow module, imported once per test run."""
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    spec = importlib.util.spec_from_file_location(
        _MODULE_NAME, _APP_DIR / "SlideShow.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = mod        # before exec, so self-imports resolve
    spec.loader.exec_module(mod)
    return mod


def build_tree(root: Path, spec: dict) -> Path:
    """Make a photo tree.  spec maps a folder path relative to root (use "/"
    separators; "" for the root itself) to the file names to put in it.  The
    files are empty: nothing under test reads them, and empty files keep the
    suite quick."""
    for folder, names in spec.items():
        directory = root / folder if folder else root
        directory.mkdir(parents=True, exist_ok=True)
        for name in names:
            (directory / name).write_text("", encoding="utf-8")
    return root


def write_settings(path: Path, directories=(), **parameters) -> Path:
    """A settings file in the current format: a Directories: block followed by
    name=value lines."""
    lines = []
    if directories:
        lines.append("Directories:")
        lines.extend(str(d) for d in directories)
    lines.extend(f"{name.replace('_', ' ')}={value}" for name, value in parameters.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def bare_show(ss, **attributes):
    """A SlideShow object which was never constructed: no window, no photos,
    just the attributes a test gives it."""
    show = object.__new__(ss.SlideShow)
    for name, value in attributes.items():
        setattr(show, name, value)
    return show


def bare_editor(ss, rootDirectory, selected=(), excluded=()):
    """A ShowEditor object which was never constructed, holding just the folders
    chosen and left out again that its picking logic works on."""
    editor = object.__new__(ss.ShowEditor)
    editor.rootDirectory = str(rootDirectory)
    editor.selected = set(selected)
    editor.excluded = set(excluded)
    return editor
