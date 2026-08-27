"""
SlideShow.py

Displays a full-screen slideshow of the images found in a directory tree.

The directory to be displayed and the other operating parameters are read from
"SlideShow settings.txt" (name=value lines) in the program's directory:

    Directories:          The next line is the path of the root directory holding the
                          photos.  What is displayed is a "photo show": a named group
                          of folders anywhere in that tree, each standing for itself
                          and everything below it, and folders may be left out of
                          those again.  The menu offers the
                          built-in "All Photos" and whatever shows have been built
                          with "Edit Photo Shows..."; those are kept in
                          "SlideShow shows.json" and the one last displayed is
                          remembered in "SlideShow state.json".
    Order                 "Sequential" or "Random"  (default: Sequential)
    Display Time          Seconds each image is displayed  (default: 10)
    Title                 Title shown at the top  (default: "photos.fanac.org")
    Title Font            Font family for the title; must be installed  (default: Segoe UI)
    Title Font Size       Point size for the title  (default: 32)
    Display Subdirectory  If True, show the subdirectory chain under the title
                          for images not in the top-level directory  (default: True)
    Pause Timeout         Seconds of no user input after which a paused show
                          resumes on its own  (default: 240)
    Mode                  "Dark" or "Light" color scheme  (default: Dark)
    Email Timeout         Seconds of no user input after which the remembered
                          email address is forgotten  (default: 60)
    Identify Timeout      Seconds of no typing or touching with the Identify Photo
                          panel open, after which it finishes by itself: saving if
                          anything was written, cancelling if not  (default: 300)
    Face Detection        How sure the detector must be before it calls something a
      Threshold           face, 0 to 1: lower finds more faces, including doubtful
                          ones; higher finds only clear ones  (default: 0.6)
    Maximum               How far a photo smaller than the screen may be enlarged to
      Enlargement         fill it, as a multiple of its own size.  1 leaves such a
                          photo at its own size, as it always used to be; beyond
                          about 2 an old scan starts to look soft  (default: 2)

A parameter value whose first non-blank character is '#' is treated as empty,
and the parameter's default is used.

Each photo comes with two same-named companion files: a .txt holding the
caption and an .xml holding photo information from Piwigo.  The caption shown
under the image is the .txt content; if there is none, the image's filename
without the extension is used.  A caption too long for its two lines first
gets extra lines (up to about a quarter of the display area), then a
progressively smaller font until it fits.  Below the caption, in smaller
type, the .xml file's author and date are shown as "Photo supplied by ..."
and "Photo date: ..." (each line omitted when that information is missing).
Dates are shown readably ("June 4, 1942"); a January 1st date is Piwigo's
way of saying only the year is known, so it shows as just the year.

The show opens on the monitor it was on last time (remembered in "SlideShow
state.json"); if that monitor is gone, it opens on the main one instead.

Buttons: Prev, Pause/Start Slideshow (one button, toggling with the state), Next,
Add Info.  A top bar holds a ✕ close box in the upper-right corner (and has
room for future menu items).
Keyboard shortcuts: left/right arrows for Prev/Next; Esc closes the Identify
Photo panel when it is up, and otherwise exits.
Add Info splits the window in two the narrow way (left/right halves on a
landscape screen, top/bottom on a portrait one), shoves the photo into one
half, and shows the Identify Photo panel in the other: the faces found in the
photo listed left-to-right, each with a box to enter the person's name, plus
a box for other comments and corrections and one for the identifier's email
address (remembered between saves while the user stays active, then forgotten
after Email Timeout seconds of no input).  Pointing at a face rings that face
in green on the photo itself.  Prev and Next stay live while the
panel is up: they discard anything unsaved, move to the next photo, and
rebuild the panel for it; Pause and Add Info are disabled.
Face detection uses OpenCV's YuNet model (the .onnx file alongside this
script).

Each Save appends a record to this session's output log, "SlideShow Output
<date and time of the latest save>.json" in the program's directory (a new
file per run, created at the first save so a run with no saves leaves no
file): concatenated pretty-printed JSON objects holding the save
time, the photo's Piwigo id and file name (from its .xml companion), the
album path, the editor's name or email, the numbered faces with names and
detection boxes, the comment, and the photo date.  Load with
json.JSONDecoder().raw_decode in a loop.  A face's "box" is [x, y, w, h] in
pixels of the *original* photo (top-left origin, y downwards), as YuNet
returns them, listed left-to-right; the round face pictures come from the
circle centred on that box with a radius of 0.65 * its diagonal.  See the
README for a worked example.

The settings file is monitored while the show is running: saving a change to it
applies just the changed parameters on the fly (a changed Directory restarts the
show from the new tree; anything else leaves the current image undisturbed).
Unrecognized parameter names and unusable values are reported in a warning
dialog and ignored; missing parameters revert to their defaults.

Requires: pip install Pillow opencv-python
"""

import os
import re
import sys
import json
import time
import queue
import random
import threading
from typing import Any
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter import simpledialog
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageTk

# How a face is shown -- the circle the round pictures are cut from and the rings are
# drawn on -- is shared with PhotosEditor, so that the two cannot drift apart.  It lives
# in HelpersPackage, either linked into this directory ("mklinks FaceGeometry Only.bat")
# or found as a sibling of it.
# Where the program's own directory is.  PyInstaller unpacks a frozen program into a
# temporary folder and points __file__ at that, so everything the *user* keeps -- the
# settings, the shows, the state, the output logs -- must be looked for beside the
# executable instead, or the program would read a settings file nobody can edit and
# write its logs where they are thrown away.
def ProgramDirectory() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


# Where a file shipped *with* the program is: inside PyInstaller's unpacked folder when
# it was built in, and beside the program when it was not.  Either way it is found.
def BundledFile(name: str) -> str:
    unpacked=getattr(sys, "_MEIPASS", "")
    if len(unpacked) > 0 and os.path.exists(os.path.join(unpacked, name)):
        return os.path.join(unpacked, name)
    return os.path.join(ProgramDirectory(), name)


_HELPERS=os.path.join(os.path.dirname(ProgramDirectory()), "HelpersPackage")
if os.path.isdir(_HELPERS) and _HELPERS not in sys.path:
    sys.path.append(_HELPERS)
try:
    from FaceGeometry import FaceCircleBounds, RoundFaceThumbnail
except ImportError:
    FaceCircleBounds=RoundFaceThumbnail=None       # Reported when a photo is identified

SETTINGS_FILE="SlideShow settings.txt"
STATE_FILE="SlideShow state.json"
SHOWS_FILE="SlideShow shows.json"
SHOWS_VERSION=3                 # 2: only the shows built in the editor; 3: they may leave folders out again
ALL_PHOTOS="All Photos"         # The built-in show: everything under the root directory
FACE_MODEL="face_detection_yunet_2023mar.onnx"
IMAGE_EXTENSIONS={".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
DEFAULT_TITLE_FONT="Segoe UI"
DEFAULT_TITLE_FONT_SIZE=32
CAPTION_FONT_SIZE=22            # Normal caption size; long captions shrink from here...
MIN_CAPTION_FONT_SIZE=12        # ...down to this, to fit the two caption lines
CAPTION_LINES=2
CREDIT_FONT_SMALLER=6           # The credit line under the caption is this much smaller than it
MIN_CREDIT_FONT_SIZE=9
MONTHS=["January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"]
BUTTON_PAD_TOP=5                # Space above the button row...
BUTTON_PAD_BOTTOM=15            # ...and below it, on a landscape screen (a portrait one lifts it further)
SUBDIR_FONT_SIZE=28             # Normal album-line size; on a landscape single line it shrinks...
MIN_SUBDIR_FONT_SIZE=14         # ...down to this to fit beside the title, then wraps below it
FACE_DETECT_MAXDIM=1600         # Photos are reduced to this before face detection (bigger finds smaller faces)
DEFAULT_FACE_THRESHOLD=0.6      # Detector confidence needed to call something a face
DEFAULT_MAX_ENLARGEMENT=2.0     # How far a photo smaller than the screen may be blown up to fill it
PANEL_BUTTON_FONT_SIZE=16       # Identify Photo's Save and Cancel (30% up from 12).  They carry no
                                # icon, so their width counts characters: the font is what sizes
                                # them, and growing it grows the button both ways at once.
ENTRY_FONT_SIZE=16              # Identify Photo's name, date and address boxes (30% up from 12)
COMMENTS_FONT_SIZE=14           # ...and its comments box (30% up from 11).  The labels beside
                                # them are left alone: this is about what people type into.
FACE_RING_GREEN="#00FF40"       # Marks a face: on the photo when a row is pointed at, and on
                                # the row's own picture while that row is being typed in
FILLED_BOX_BG="#ffffcc"         # An Identify Photo box with something typed in it...
EMPTY_BOX_BG="white"            # ...and one still empty (what tk gives an Entry or Text here)
KNOWN_PARAMETERS={"directories", "order", "display time", "title", "title font", "title font size", "display subdirectory", "pause timeout", "mode", "email timeout", "face detection threshold", "maximum enlargement", "identify timeout"}

# The color schemes for the Mode parameter (default: dark)
THEMES={
    # scrollThumb is the block showing how much of the face table is on screen, and it is
    # deliberately darker than the trough it slides in: left to tk both are the same pale
    # grey, distinguished only by a 3D edge, and the thumb went unnoticed.
    "dark":  {"bg": "black", "fg": "white", "titleFg": "lightyellow", "subdirFg": "#bbbbbb",
              "barBg": "#202020", "barFg": "white", "barActiveBg": "#3a3a3a", "panelBg": "#101010",
              "separatorBg": "#606060",
              "scrollThumb": "#1c1c1c", "scrollTrough": "#6e6e6e", "scrollActive": "#000000"},
    "light": {"bg": "white", "fg": "black", "titleFg": "darkgoldenrod", "subdirFg": "#555555",
              "barBg": "#e4e4e4", "barFg": "black", "barActiveBg": "#d0d0d0", "panelBg": "#efefef",
              "separatorBg": "#b0b0b0",
              "scrollThumb": "#7a7a7a", "scrollTrough": "#dcdcdc", "scrollActive": "#5a5a5a"},
}


# Read a settings file of name=value lines.  Blank lines and lines starting with '#' are ignored.
# Names are matched case-insensitive.
# A "Directories:" line starts a list of directory paths, one per line, ending at the first
# line which is not a valid directory path; the list is stored under the key "directories".
def ReadSettings(pathname: str) -> dict[str, Any] | None:
    if not os.path.exists(pathname):
        return None
    settings={}
    inDirectories=False
    with open(pathname, "r", encoding="utf-8") as file:
        for line in file:
            line=line.strip()
            if len(line) == 0 or line.startswith("#"):
                continue
            if inDirectories:
                if os.path.isdir(line):
                    settings["directories"].append(line)
                    continue
                inDirectories=False     # Not a valid directory -- the list ends; process the line normally
            if line.casefold() == "directories:":
                inDirectories=True
                settings.setdefault("directories", [])
                continue
            if "=" not in line:
                continue
            name, _, val=line.partition("=")
            val=val.strip()
            if val.startswith("#"):
                continue        # A commented-out value means "use the default"
            settings[name.strip().casefold()]=val
    return settings


# -------------------- Photo shows --------------------
# A "photo show" is a name and a list of folders, each folder standing for itself and
# everything below it.  Folders are stored relative to the root directory, with "/"
# separators, so a shows file remains readable and portable.

# One folder path in the stored form
def NormalizeFolder(folder: str) -> str:
    return folder.replace("\\", "/").strip("/")

# True if folder is ancestor, or lies somewhere below it
def IsCoveredBy(folder: str, ancestor: str) -> bool:
    folder, ancestor=folder.casefold(), ancestor.casefold()
    return folder == ancestor or folder.startswith(ancestor+"/")

# Drop every folder which another folder in the list already covers, so that no photo
# is scanned (and shown) twice
def PruneFolders(folders) -> list[str]:
    kept=[]
    for folder in sorted({NormalizeFolder(f) for f in folders if len(NormalizeFolder(f)) > 0},
                         key=lambda f: (f.count("/"), f.casefold())):
        if not any(IsCoveredBy(folder, k) for k in kept):
            kept.append(folder)
    return sorted(kept, key=str.casefold)


# Is a folder in the show?  A show is a list of chosen folders and a list of folders
# left out again, each standing for itself and everything below it, and the rule is the
# familiar one: of the entries covering this folder, the most specific decides.  So
# "all of Fan Photos except Fan Photos/LASFS" says exactly what it appears to say.
def FolderIsIncluded(folder: str, chosen, excluded) -> bool:
    folder=NormalizeFolder(folder)
    best, included=-1, False
    for entry in chosen:
        entry=NormalizeFolder(entry)
        if IsCoveredBy(folder, entry) and len(entry) > best:
            best, included=len(entry), True
    for entry in excluded:
        entry=NormalizeFolder(entry)
        if IsCoveredBy(folder, entry) and len(entry) >= best:    # a tie goes to leaving it out
            best, included=len(entry), False
    return included


# Drop the entries which make no difference: a chosen folder already covered by another
# with nothing excluded in between, or a folder left out which was never in.  What is
# stored is then just what the user actually said.
def TidyRules(chosen, excluded) -> tuple[list[str], list[str]]:
    chosen={NormalizeFolder(f) for f in chosen if len(NormalizeFolder(f)) > 0}
    excluded={NormalizeFolder(f) for f in excluded if len(NormalizeFolder(f)) > 0}
    dropping=True
    while dropping:
        dropping=False
        for entry in sorted(chosen, key=lambda f: (-f.count("/"), f)):
            if FolderIsIncluded(entry, chosen-{entry}, excluded):
                chosen=chosen-{entry}       # it was in anyway
                dropping=True
                break
        if dropping:
            continue
        for entry in sorted(excluded, key=lambda f: (-f.count("/"), f)):
            if not FolderIsIncluded(entry, chosen, excluded-{entry}):
                excluded=excluded-{entry}   # it was out anyway
                dropping=True
                break
    return sorted(chosen, key=str.casefold), sorted(excluded, key=str.casefold)


# The total padding a pack() pady or padx setting adds, given the several ways tk
# reports one back: 4, "4", (4, 0), "4 0"
def PadTotal(value) -> int:
    if isinstance(value, (list, tuple)):
        return sum(int(v) for v in value)
    parts=str(value).replace("(", " ").replace(")", " ").replace(",", " ").split()
    return sum(int(p) for p in parts if p.lstrip("-").isdigit())


# The screen rectangle (left, top, right, bottom) of the monitor containing a point.
# tk's screen dimensions describe only the primary monitor, so anything which has to
# stay on the monitor the window is actually on must ask Windows.
def MonitorRect(x: int, y: int, widget: tk.Misc) -> tuple[int, int, int, int]:
    try:
        import ctypes
        from ctypes import wintypes
        class MONITORINFO(ctypes.Structure):
            _fields_=[("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                      ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
        hmon=ctypes.windll.user32.MonitorFromPoint(wintypes.POINT(x, y), 2)     # MONITOR_DEFAULTTONEAREST
        mi=MONITORINFO()
        mi.cbSize=ctypes.sizeof(MONITORINFO)
        if ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r=mi.rcMonitor
            return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    return 0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight()


# A small help balloon which appears when the pointer rests on a widget
class ToolTip:
    DELAY=600                   # Milliseconds the pointer must rest before the tip appears

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget=widget
        self.text=text
        self.afterId=None
        self.window=None
        widget.bind("<Enter>", self.OnEnter, add="+")
        widget.bind("<Leave>", self.OnLeave, add="+")
        widget.bind("<ButtonPress>", self.OnLeave, add="+")
        widget.bind("<Destroy>", self.OnLeave, add="+")

    def OnEnter(self, event=None) -> None:
        self.Cancel()
        self.afterId=self.widget.after(self.DELAY, self.Show)

    def OnLeave(self, event=None) -> None:
        self.Cancel()
        self.Hide()

    def Cancel(self) -> None:
        if self.afterId is not None:
            try:
                self.widget.after_cancel(self.afterId)
            except tk.TclError:
                pass
            self.afterId=None

    def Show(self) -> None:
        self.afterId=None
        if self.window is not None or not self.widget.winfo_exists():
            return
        self.window=tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)        # No title bar or border
        tk.Label(self.window, text=self.text, font=("Segoe UI", 10), justify=tk.LEFT, wraplength=380,
                 bg="#ffffe0", fg="black", relief=tk.SOLID, bd=1, padx=6, pady=4).pack()
        self.window.update_idletasks()
        # Centered on the widget and above it, or below when there is no room above,
        # kept within the monitor the widget is on (which need not be the primary one)
        width, height=self.window.winfo_width(), self.window.winfo_height()
        left, top, right, bottom=MonitorRect(self.widget.winfo_rootx()+self.widget.winfo_width()//2,
                                             self.widget.winfo_rooty()+self.widget.winfo_height()//2, self.widget)
        x=self.widget.winfo_rootx()+self.widget.winfo_width()//2-width//2
        x=max(left+2, min(x, right-width-2))
        y=self.widget.winfo_rooty()-height-8
        if y < top+2:
            y=self.widget.winfo_rooty()+self.widget.winfo_height()+8
        if y+height > bottom-2:
            y=max(top+2, bottom-height-2)
        self.window.wm_geometry(f"+{x}+{y}")

    def Hide(self) -> None:
        if self.window is not None:
            self.window.destroy()
            self.window=None


class SlideShow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        # -------------------- Settings --------------------
        settingsPath=os.path.join(ProgramDirectory(), SETTINGS_FILE)
        settings=ReadSettings(settingsPath)
        if settings is None:
            self.Fatal(f"Settings file '{settingsPath}' is missing.")

        def Get(name: str, default: str) -> str:
            return settings.get(name.casefold(), default)

        def IsTrue(name: str, default: str) -> bool:
            return Get(name, default).casefold() in ("true", "yes")

        self.installedFonts=sorted(tkfont.families(self))      # All font families tk knows about

        self.startupProblems=self.ValidateSettings(settings)       # Reported once the show is up

        self.rootDirectories=settings.get("directories", [])
        self.randomOrder=Get("Order", "Sequential").casefold().startswith("random")
        try:
            self.displayTime=float(Get("Display Time", "10"))
        except ValueError:
            self.displayTime=10.0
        if self.displayTime <= 0:
            self.displayTime=10.0
        self.titleText=Get("Title", "photos.fanac.org")
        self.titleFontName, self.titleFontSize=self.ResolveTitleFont(Get("Title Font", ""), Get("Title Font Size", ""))
        self.theme=THEMES.get(Get("Mode", "Dark").casefold(), THEMES["dark"])
        self.displaySubdirectory=IsTrue("Display Subdirectory", "True")
        try:
            self.pauseTimeout=float(Get("Pause Timeout", "240"))
        except ValueError:
            self.pauseTimeout=240.0
        if self.pauseTimeout <= 0:
            self.pauseTimeout=240.0
        try:
            self.emailTimeout=float(Get("Email Timeout", "60"))
        except ValueError:
            self.emailTimeout=60.0
        if self.emailTimeout <= 0:
            self.emailTimeout=60.0
        try:
            self.identifyTimeout=float(Get("Identify Timeout", "300"))
        except ValueError:
            self.identifyTimeout=300.0
        if self.identifyTimeout <= 0:
            self.identifyTimeout=300.0
        self.editorEmail=""             # Remembered between saves while the user stays active
        self.faceThreshold=self.ResolveFaceThreshold(Get("Face Detection Threshold", ""))
        self.maxEnlargement=self.ResolveMaxEnlargement(Get("Maximum Enlargement", ""))

        if len(self.rootDirectories) == 0:
            self.Fatal(f"No directory path is defined in '{settingsPath}'.\n\nThe settings file needs a 'Directories:' line followed by the path of the directory holding the photo shows.")
        self.rootDirectory=self.rootDirectories[0]      # Extra paths are reported by ValidateSettings

        # The settings file is monitored while running: changes to it are applied on the
        # fly, each parameter taking effect only if its value actually changed.
        self.settingsPath=settingsPath
        self.lastSettingsMtime=os.stat(settingsPath).st_mtime
        self.pendingSettings=None       # Newly-read settings awaiting a second identical read (debounce)

        # -------------------- Find the images --------------------
        # The photo shows -- named groups of folders -- are kept in the shows file; the
        # Select Photo Show menu picks one of them.  The show chosen last time is
        # reopened if it is still there and still has photos.
        self.tlds=self.FindTLDs(self.rootDirectory)
        if len(self.tlds) == 0:
            self.Fatal(f"No directories found inside '{self.rootDirectory}' -- there are no photo shows to display.")
        programDirectory=ProgramDirectory()
        self.statePath=os.path.join(programDirectory, STATE_FILE)
        self.showsPath=os.path.join(programDirectory, SHOWS_FILE)
        self.shows=self.LoadShows()
        if self.showsMigrated:
            self.SaveShows()            # Write the tidied-up file back at once
        self.currentShowName=ALL_PHOTOS
        self.savedMonitor=None          # The monitor the show was on last time, if it was recorded
        try:
            with open(self.statePath, "r", encoding="utf-8") as file:
                state=json.load(file)
            saved=state.get("current show", "")
            if any(show["name"] == saved for show in self.AllShows()):
                self.currentShowName=saved
            monitor=state.get("monitor")
            if isinstance(monitor, list) and len(monitor) == 4:
                self.savedMonitor=tuple(monitor)
        except (OSError, json.JSONDecodeError):
            pass
        self.images=self.ImagesForShow(self.currentShowName)
        if len(self.images) == 0:       # That show has lost its photos -- use one which has some
            name, images=self.FirstShowWithPhotos()
            if name is not None:
                self.currentShowName, self.images=name, images
        if len(self.images) == 0:
            self.Fatal(f"No image files found in the photo shows under '{self.rootDirectory}'.")

        # History of images shown (indexes into self.images), so Prev can back up even in random order.
        self.history: list[int]=[]
        self.histpos=-1

        self.paused=False
        self.dialogOpen=False           # True while the Identify Photo panel (or a message) is up
        self.identifyPanel=None         # The Identify Photo panel, when it is up
        self.identifyWasPaused=False    # The pause state to return to when it closes
        self.CloseIdentifyPanel=None    # Closes the panel (set while it is up)
        self.backgroundResults=queue.Queue()    # Answers from the working threads
        self.switchingTo=None           # The show being looked for, while it is being looked for

        # Each run gets its own output log of Identify Photo saves, next to the settings
        # file; its name carries the date and time of the latest save.  It is created
        # only at the first save, so a run with no saves leaves no empty file behind.
        self.outputPath=None
        self.lastInputTime=time.time()
        self.advanceAfterId=None        # Id of the pending after() call which advances to the next image

        # -------------------- The display --------------------
        self.title("SlideShow")
        # Taskbar icon (bundled into the exe via the .spec if frozen); harmless no-op if missing or bad
        try:
            self.iconbitmap(BundledFile("SlideShow.ico"))
        except Exception:
            pass
        self.configure(bg="black")
        self.attributes("-fullscreen", True)

        # Top bar: menu items at the left, with a close box at the right end
        self.topBar=tk.Frame(self, bg="#202020")
        self.topBar.pack(side=tk.TOP, fill=tk.X)
        self.closeButton=tk.Button(self.topBar, text="  ✕  ", command=self.destroy, font=("Segoe UI", 12),
                                   fg="white", bg="#202020", activebackground="#C42B1C", activeforeground="white",
                                   relief=tk.FLAT, bd=0)
        self.closeButton.pack(side=tk.RIGHT)

        # The Select Photo Show menu: one radio-checked entry per listed directory
        self.showMenuButton=tk.Menubutton(self.topBar, text="Select Photo Show", font=("Segoe UI", 11),
                                          fg="white", bg="#202020", activebackground="#3a3a3a", activeforeground="white",
                                          relief=tk.FLAT)
        self.showMenu=tk.Menu(self.showMenuButton, tearoff=False)
        self.showMenuButton.config(menu=self.showMenu)
        self.showMenuButton.pack(side=tk.LEFT, padx=6)
        self.showVar=tk.StringVar(value=self.currentShowName)
        self.RebuildShowMenu()

        # Dragging the top bar moves the window, so it can be dropped on another monitor
        self.dragStart=None
        self.dragging=False
        self.topBar.bind("<ButtonPress-1>", self.OnTopBarPress)
        self.topBar.bind("<B1-Motion>", self.OnTopBarMotion)
        self.topBar.bind("<ButtonRelease-1>", self.OnTopBarRelease)

        # The title and the album line share a header; on a landscape window they sit
        # on a single line to leave more room below, on a portrait one they stack
        self.headerFrame=tk.Frame(self, bg="black")
        self.headerFrame.pack(side=tk.TOP, pady=(10, 0))
        self.titleLabel=tk.Label(self.headerFrame, text=self.titleText, font=(self.titleFontName, self.titleFontSize, "bold"), fg="lightyellow", bg="black")
        self.subdirFont=tkfont.Font(family="Segoe UI", size=SUBDIR_FONT_SIZE)
        self.subdirLabel=tk.Label(self.headerFrame, text="", font=self.subdirFont, fg="#bbbbbb", bg="black")
        self.headerMode=""              # "single" or "stacked", set by ArrangeHeader
        self.ArrangeHeader()

        # The slideshow section: the photo display with the button row at its bottom.
        # The Identify Photo panel splits the window against this frame, so the buttons
        # stay at the bottom of the slideshow half.
        self.showFrame=tk.Frame(self, bg="black")
        self.showFrame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Bottom-up within the slideshow section: buttons at the very bottom,
        # description just above them, image fills the rest.
        buttonFrame=self.buttonFrame=tk.Frame(self.showFrame, bg="black")
        buttonFrame.pack(side=tk.BOTTOM, pady=(BUTTON_PAD_TOP, BUTTON_PAD_BOTTOM))

        # Every button carries an image (a transparent spacer when it has no icon) so
        # that they all size and align identically
        self.buttonIcons=self.MakeButtonIcons()

        # Wide enough for the longest label ("Start Slideshow"), all alike
        def MakeButton(text: str, command, icon: str="blank") -> tk.Button:
            b=tk.Button(buttonFrame, text=" "+text if icon != "blank" else text, image=self.buttonIcons[icon],
                        compound=tk.LEFT, command=command, font=("Segoe UI", 12), width=145)
            b.pack(side=tk.LEFT, padx=8)
            return b

        self.prevButton=MakeButton("Prev", self.OnPrev, "prev")
        self.pauseButton=MakeButton("Pause", self.OnPauseContinue, "pause")     # Toggles with the state
        self.nextButton=MakeButton("Next", self.OnNext, "next")
        self.addInfoButton=MakeButton("Add Info", self.OnAddInfo, "pencil")
        # Bigger and bold, to stand out from its neighbors
        self.addInfoButton.configure(width=191, height=38, font=("Segoe UI", 12, "bold"))
        ToolTip(self.addInfoButton, "If you have anything to tell us about this photo, click here.")

        # The row is re-sized for the shape of whatever monitor the window is on (see
        # FitButtonRow).  Each button's own padding is kept, since they are not all alike:
        # Add Info is deliberately bigger than its neighbors.
        self.buttons=(self.prevButton, self.pauseButton, self.nextButton, self.addInfoButton)
        self.buttonBasePady={b: int(str(b.cget("pady"))) for b in self.buttons}     # cget answers with a Tcl object
        self.buttonNaturalHeight={}     # Measured the first time the row is fitted

        # The image and its caption are stacked in a frame which is centered in the
        # remaining space, so the caption sits directly below the image and moves with it.
        self.centerFrame=tk.Frame(self.showFrame, bg="black")
        self.centerFrame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        innerFrame=self.innerFrame=tk.Frame(self.centerFrame, bg="black")
        innerFrame.pack(expand=True)

        self.imageLabel=tk.Label(innerFrame, bg="black")
        self.imageLabel.pack(side=tk.TOP)
        # Touching or clicking the photo pauses a running show and starts a paused one --
        # on a touch screen the obvious gesture, and the only control a visitor can find
        # without being told.  While the Identify Photo panel is up the same touch means
        # something better: it picks out the face touched.  Both live in OnPhotoClick.
        self.imageLabel.bind("<Button-1>", self.OnPhotoClick)

        self.captionFont=tkfont.Font(family="Segoe UI", size=CAPTION_FONT_SIZE)
        self.descLabel=tk.Label(innerFrame, text="", font=self.captionFont, fg="white", bg="black",
                                justify=tk.CENTER, height=CAPTION_LINES, wraplength=self.winfo_screenwidth()-100)
        self.descLabel.pack(side=tk.TOP)

        # Under the caption, in smaller type: where the photo came from and its date
        self.creditFont=tkfont.Font(family="Segoe UI", size=CAPTION_FONT_SIZE-CREDIT_FONT_SMALLER)
        self.creditLabel=tk.Label(innerFrame, text="", font=self.creditFont, fg="white", bg="black",
                                  justify=tk.CENTER, wraplength=self.winfo_screenwidth()-100)
        self.creditLabel.pack(side=tk.TOP)

        self.ApplyTheme()
        self.UpdateButtonStates()

        # Any user input resets the pause-timeout clock
        self.bind_all("<Key>", self.OnUserInput)
        self.bind_all("<Button>", self.OnUserInput)
        self.bind("<Left>", lambda e: self.OnArrowKey(False))
        self.bind("<Right>", lambda e: self.OnArrowKey(True))
        self.bind("<Escape>", lambda e: self.OnEscape())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        # Let the window get its real size before displaying the first image
        self.after(100, self.Start)


    # Arrange the title and the album line.  On a landscape window they share a single
    # top line, the album font shrinking (to a floor) to fit beside the title; when even
    # the smallest size will not fit, the album wraps onto its own line below the title,
    # which is also the portrait-window arrangement.  Called on every ShowImage, since
    # the album text changes from photo to photo.
    def ArrangeHeader(self) -> None:
        size=SUBDIR_FONT_SIZE
        self.subdirFont.configure(size=size)
        mode="stacked"
        if self.winfo_width() >= self.winfo_height():
            titleFont=tkfont.Font(font=self.titleLabel.cget("font"))
            avail=self.winfo_width()-60-titleFont.measure(self.titleLabel.cget("text"))-30
            while size > MIN_SUBDIR_FONT_SIZE and self.subdirFont.measure(self.subdirLabel.cget("text")) > avail:
                size-=2
                self.subdirFont.configure(size=size)
            if self.subdirFont.measure(self.subdirLabel.cget("text")) <= avail:
                mode="single"
            else:
                self.subdirFont.configure(size=SUBDIR_FONT_SIZE)       # Wrapping -- full size again
        if mode != self.headerMode:
            self.headerMode=mode
            self.titleLabel.pack_forget()
            self.subdirLabel.pack_forget()
            if mode == "single":
                self.titleLabel.pack(side=tk.LEFT, anchor=tk.S)
                self.subdirLabel.pack(side=tk.LEFT, anchor=tk.S, padx=(30, 0), pady=(0, 4))
            else:
                self.titleLabel.pack(side=tk.TOP)
                self.subdirLabel.pack(side=tk.TOP)
            self.update_idletasks()     # So the image scaling that follows sees the new header height

    # Apply the current theme's colors to all the permanent widgets.  (The Identify
    # Photo panel picks up the theme when it is next opened.)
    def ApplyTheme(self) -> None:
        t=self.theme
        self.configure(bg=t["bg"])
        for w in (self.showFrame, self.buttonFrame, self.centerFrame, self.innerFrame, self.imageLabel, self.headerFrame):
            w.configure(bg=t["bg"])
        self.titleLabel.configure(bg=t["bg"], fg=t["titleFg"])
        self.subdirLabel.configure(bg=t["bg"], fg=t["subdirFg"])
        self.descLabel.configure(bg=t["bg"], fg=t["fg"])
        self.creditLabel.configure(bg=t["bg"], fg=t["subdirFg"])
        self.topBar.configure(bg=t["barBg"])
        self.closeButton.configure(bg=t["barBg"], fg=t["barFg"], activebackground="#C42B1C", activeforeground="white")
        self.showMenuButton.configure(bg=t["barBg"], fg=t["barFg"], activebackground=t["barActiveBg"], activeforeground=t["barFg"])


    def Fatal(self, msg: str) -> None:
        self.withdraw()
        messagebox.showerror("SlideShow", msg)
        sys.exit(1)


    def Start(self) -> None:
        self.PollBackground()           # Pick up what the working threads have finished
        # Reappear on the monitor the show was on last time.  If that monitor is gone,
        # MonitorFromPoint answers with a different one, and the main monitor is used.
        if self.savedMonitor is not None:
            rect=self.savedMonitor
            center=((rect[0]+rect[2])//2, (rect[1]+rect[3])//2)
            if MonitorRect(center[0], center[1], self) != rect:
                rect=MonitorRect(0, 0, self)        # The main monitor: it always starts at the origin
            self.PlaceOnMonitor(rect)
        self.FitButtonRow()             # Also when there was no remembered monitor to place it on
        self.NextImage()
        self.ScheduleAdvance()
        self.OnTick()
        if len(self.startupProblems) > 0:
            self.ShowSettingsProblems(self.startupProblems)


    # Return a list of complaints about unrecognized parameter names and unusable values.
    # (The Directory parameter is checked separately, since what is fatal at startup is
    # merely ignorable when the file is edited while running.)
    def ValidateSettings(self, settings: dict[str, str]) -> list[str]:
        problems=[]
        for name in settings.keys():
            if name not in KNOWN_PARAMETERS:
                problems.append(f"Unrecognized parameter '{name}'  (ignoring it)")

        if "order" in settings:
            val=settings["order"].casefold()
            if not val.startswith("seq") and not val.startswith("random"):
                problems.append(f"Order='{settings['order']}' should be Sequential or Random  (ignoring it)")

        for pname, label in (("display time", "Display Time"), ("pause timeout", "Pause Timeout"), ("title font size", "Title Font Size"), ("email timeout", "Email Timeout"), ("identify timeout", "Identify Timeout")):
            if pname in settings:
                try:
                    if float(settings[pname]) <= 0:
                        problems.append(f"{label}='{settings[pname]}' should be greater than zero  (ignoring it)")
                except ValueError:
                    problems.append(f"{label}='{settings[pname]}' should be a number  (ignoring it)")

        if "display subdirectory" in settings and settings["display subdirectory"].casefold() not in ("true", "yes", "false", "no"):
            problems.append(f"Display Subdirectory='{settings['display subdirectory']}' should be True or False  (ignoring it)")

        if "mode" in settings and settings["mode"].casefold() not in THEMES:
            problems.append(f"Mode='{settings['mode']}' should be Dark or Light  (ignoring it)")

        if len(settings.get("directories", [])) > 1:
            problems.append("Directories: lists more than one path  (using the first)")

        if "face detection threshold" in settings:
            value=settings["face detection threshold"]
            try:
                if not 0 < float(value) <= 1:
                    problems.append(f"Face Detection Threshold='{value}' should be greater than 0 and no more than 1  (using {DEFAULT_FACE_THRESHOLD})")
            except ValueError:
                problems.append(f"Face Detection Threshold='{value}' should be a number  (using {DEFAULT_FACE_THRESHOLD})")

        if "maximum enlargement" in settings:
            value=settings["maximum enlargement"]
            try:
                if float(value) < 1:
                    problems.append(f"Maximum Enlargement='{value}' should be 1 or more  (using {DEFAULT_MAX_ENLARGEMENT})")
            except ValueError:
                problems.append(f"Maximum Enlargement='{value}' should be a number  (using {DEFAULT_MAX_ENLARGEMENT})")

        fontName=settings.get("title font", "").strip()
        if len(fontName) > 0 and self.FindFontFamily(fontName) is None:
            problems.append(f"Title Font='{fontName}' is not an installed font  (using {DEFAULT_TITLE_FONT})")

        return problems


    # Show a message dialog.  Like the Add Info panel, the show is held while it is up
    # and returns to its previous pause state afterwards.
    def ShowMessage(self, title: str, message: str, warning: bool=False) -> None:
        wasPaused=self.paused
        self.paused=True
        self.dialogOpen=True
        self.CancelAdvance()
        self.UpdateButtonStates()

        (messagebox.showwarning if warning else messagebox.showinfo)(title, message, parent=self)

        self.dialogOpen=False
        self.lastInputTime=time.time()
        if wasPaused:
            self.UpdateButtonStates()
        else:
            self.Resume()

    # Report settings-file problems in a warning dialog
    def ShowSettingsProblems(self, problems: list[str]) -> None:
        self.ShowMessage("SlideShow settings", "Problems in the settings file:\n\n"+"\n".join(problems), warning=True)


    # Turn the "Maximum Enlargement" parameter value into a usable limit (1 or more),
    # falling back to the default for a missing or unusable value
    @staticmethod
    def ResolveMaxEnlargement(value: str) -> float:
        try:
            limit=float(value)
        except ValueError:
            return DEFAULT_MAX_ENLARGEMENT
        if limit < 1:               # Below its own size is not enlargement; 1 means "leave it alone"
            return DEFAULT_MAX_ENLARGEMENT
        return limit

    # Turn the "Face Detection Threshold" parameter value into a usable confidence
    # (0 < t <= 1), falling back to the default for a missing or unusable value
    @staticmethod
    def ResolveFaceThreshold(value: str) -> float:
        try:
            threshold=float(value)
        except ValueError:
            return DEFAULT_FACE_THRESHOLD
        if threshold <= 0 or threshold > 1:
            return DEFAULT_FACE_THRESHOLD
        return threshold

    # Find an installed font family by name, case-insensitive, first as an exact match and
    # then as a prefix (so "Hobo" will find an installed "Hobo Std").  None if no match.
    def FindFontFamily(self, name: str) -> str | None:
        name=name.strip().casefold()
        if len(name) == 0:
            return None
        matches=[f for f in self.installedFonts if f.casefold() == name]
        if len(matches) == 0:
            matches=[f for f in self.installedFonts if f.casefold().startswith(name)]
        return matches[0] if len(matches) > 0 else None

    # Turn the "Title Font"/"Title Font Size" parameter values into a usable (family, size)
    # pair, falling back to the default for any missing or unusable value.
    def ResolveTitleFont(self, name: str, size: str) -> tuple[str, int]:
        family=self.FindFontFamily(name)
        if family is None:
            family=DEFAULT_TITLE_FONT
        try:
            sz=int(float(size))
        except ValueError:
            sz=DEFAULT_TITLE_FONT_SIZE
        if sz <= 0:
            sz=DEFAULT_TITLE_FONT_SIZE
        return family, sz


    # -------------------- Dragging the window by its top bar --------------------
    # A fullscreen window cannot be dragged directly, so on the first real movement it
    # drops out of fullscreen into a small window that follows the mouse; when the
    # button is released it is expanded to fill whichever monitor it was dropped on.
    # (tk's own -fullscreen always snaps back to the original monitor, so after
    # re-entering fullscreen the window is moved onto the drop monitor by hand with
    # the Windows API.)
    def OnTopBarPress(self, event) -> None:
        self.dragStart=(event.x_root, event.y_root)
        self.dragging=False

    def OnTopBarMotion(self, event) -> None:
        if self.dragStart is None:
            return
        if not self.dragging:
            if abs(event.x_root-self.dragStart[0])+abs(event.y_root-self.dragStart[1]) < 10:
                return                  # Ignore the tiny jiggles of a simple click
            self.dragging=True
            self.attributes("-fullscreen", False)
        self.geometry(f"400x250+{event.x_root-200}+{event.y_root-15}")

    def OnTopBarRelease(self, event) -> None:
        if self.dragging:
            self.attributes("-fullscreen", True)
            self.update_idletasks()
            self.PlaceOnMonitor(MonitorRect(event.x_root, event.y_root, self))
            self.SaveState()            # So the show comes back to this monitor next time
        self.dragStart=None
        self.dragging=False

    # Fill the given monitor.  (tk's -fullscreen always uses the monitor the window
    # started on, so the window is placed on the wanted one with the Windows API.)
    def PlaceOnMonitor(self, rect: tuple[int, int, int, int]) -> None:
        left, top, right, bottom=rect
        try:
            import ctypes
            hwnd=ctypes.windll.user32.GetAncestor(self.winfo_id(), 2)          # GA_ROOT
            ctypes.windll.user32.SetWindowPos(hwnd, 0, left, top, right-left, bottom-top, 0x0014)   # SWP_NOZORDER | SWP_NOACTIVATE
            self.descLabel.config(wraplength=(right-left)-100)                 # This monitor may be a different width
        except Exception:
            pass                        # If the Windows API is unavailable we are at least fullscreen somewhere
        self.update_idletasks()
        self.FitButtonRow()             # This monitor may be portrait where the last was landscape
        if self.identifyPanel is not None:
            # This monitor may be a different shape, so the split has to be redone
            self.FitFaceTable(self.PackIdentifyPanel())
        if len(self.history) > 0:
            self.ShowImage()            # Rescale to this monitor (also refits the header)

    # -------------------- Work done off the screen's thread --------------------
    # Reading a large photograph, looking for faces in it, and walking a big tree of
    # folders all take long enough to stop the display dead if they are done where the
    # screen is drawn.  They are handed to a thread instead -- which must touch no part
    # of tk, since tkinter is not thread-safe: it leaves its answer in a queue, and this
    # poll, which does run on the screen's thread, delivers it.
    def InBackground(self, work, done) -> None:
        def Run() -> None:
            try:
                self.backgroundResults.put((done, work(), None))
            except Exception as e:
                self.backgroundResults.put((done, None, e))
        threading.Thread(target=Run, daemon=True).start()

    def PollBackground(self) -> None:
        try:
            while True:
                done, result, error=self.backgroundResults.get_nowait()
                done(result, error)
        except queue.Empty:
            pass
        self.after(120, self.PollBackground)

    # The monitor the window is on at the moment
    def CurrentMonitor(self) -> tuple[int, int, int, int]:
        return MonitorRect(self.winfo_rootx()+self.winfo_width()//2,
                           self.winfo_rooty()+self.winfo_height()//2, self)


    # The immediate subdirectories of the root directory: the available photo shows
    @staticmethod
    def FindTLDs(rootDirectory: str) -> list[str]:
        try:
            return [os.path.join(rootDirectory, d) for d in sorted(os.listdir(rootDirectory), key=str.casefold)
                    if os.path.isdir(os.path.join(rootDirectory, d))]
        except OSError:
            return []

    # The shows built in the editor, from the shows file.  "All Photos" is built in
    # rather than stored, so it is dropped if an older file still holds it -- as are the
    # shows which older versions made up from the top-level folders.
    def LoadShows(self) -> list[dict]:
        self.showsMigrated=False
        try:
            with open(self.showsPath, "r", encoding="utf-8") as file:
                data=json.load(file)
            shows=[{"name": str(s["name"]),
                    "folders": [NormalizeFolder(f) for f in s["folders"]],
                    "except": [NormalizeFolder(f) for f in s.get("except", [])]}
                   for s in data.get("shows", []) if isinstance(s, dict) and "name" in s and "folders" in s]
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return []
        before=len(shows)
        shows=[show for show in shows if show["name"] != ALL_PHOTOS]
        if data.get("version", 1) < SHOWS_VERSION:
            tldNames={os.path.basename(d).casefold() for d in self.tlds}
            shows=[show for show in shows
                   if not (len(show["folders"]) == 1 and show["folders"][0].casefold() == show["name"].casefold()
                           and show["name"].casefold() in tldNames)]
        self.showsMigrated=len(shows) != before or data.get("version", 1) < SHOWS_VERSION
        return shows

    def SaveShows(self) -> None:
        try:
            # An "except" list is written only when the show has one, so a plain show
            # stays plain in the file
            shows=[{k: v for k, v in show.items() if k != "except" or len(v) > 0} for show in self.shows]
            with open(self.showsPath, "w", encoding="utf-8") as file:
                json.dump({"version": SHOWS_VERSION, "shows": shows}, file, indent=2, ensure_ascii=False)
        except OSError as e:
            self.ShowMessage("SlideShow", f"Could not save the photo shows:\n{e}", warning=True)

    # The shows on offer: the built-in "everything" show, then those built in the editor
    def AllShows(self) -> list[dict]:
        return [{"name": ALL_PHOTOS, "folders": [os.path.basename(d) for d in self.tlds],
                 "except": []}]+self.shows

    # The absolute paths of a show's chosen folders: those which have gone missing are
    # skipped, and one already covered by another is dropped so that no photo is scanned
    # -- and shown -- twice.  (A folder covered by another but with something excluded in
    # between is kept: it is saying something the broader folder does not.)
    def ShowFolders(self, name: str) -> list[str]:
        show=next((show for show in self.AllShows() if show["name"] == name), None)
        if show is None:
            return []
        chosen, excluded=TidyRules(show["folders"], show.get("except", []))
        chosen=[f for f in chosen if not any(IsCoveredBy(f, other) and f != other for other in chosen)]
        paths=[os.path.join(self.rootDirectory, folder.replace("/", os.sep)) for folder in chosen]
        return [path for path in paths if os.path.isdir(path)]

    # The absolute paths a show leaves out again
    def ShowExclusions(self, name: str) -> list[str]:
        show=next((show for show in self.AllShows() if show["name"] == name), None)
        if show is None:
            return []
        _, excluded=TidyRules(show["folders"], show.get("except", []))
        return [os.path.join(self.rootDirectory, folder.replace("/", os.sep)) for folder in excluded]

    # The photos a named show comes to
    def ImagesForShow(self, name: str) -> list[str]:
        return self.ScanImages(self.ShowFolders(name), self.ShowExclusions(name))

    # The first show which actually has photos, and its images: (None, []) if none has
    def FirstShowWithPhotos(self) -> tuple[str | None, list[str]]:
        for show in self.AllShows():
            images=self.ImagesForShow(show["name"])
            if len(images) > 0:
                return show["name"], images
        return None, []

    # Rebuild the Select Photo Show menu: the built-in All Photos, then the shows built
    # in the editor, with the one being displayed marked, and the editor at the bottom.
    # Picking a show is a single click, so the menu closing is the right thing.
    def RebuildShowMenu(self) -> None:
        self.showMenu.delete(0, tk.END)
        for show in self.AllShows():
            self.showMenu.add_radiobutton(label=show["name"], variable=self.showVar,
                                          value=show["name"], command=self.OnSelectShow)
        self.showMenu.add_separator()
        self.showMenu.add_command(label="Edit Photo Shows...", command=self.OnEditShows)

    # Open the editor, holding the show while it is up
    def OnEditShows(self) -> None:
        wasPaused=self.paused
        self.paused=True
        self.dialogOpen=True
        self.CancelAdvance()
        self.UpdateButtonStates()

        self.wait_window(ShowEditor(self))

        self.dialogOpen=False
        self.lastInputTime=time.time()
        if wasPaused:
            self.UpdateButtonStates()
        else:
            self.Resume()

    # Take the shows as edited: save them, rebuild the menu, and put the display on a
    # show which still exists and still has photos
    def ApplyEditedShows(self, shows: list[dict]) -> None:
        self.shows=shows
        self.SaveShows()
        if not any(show["name"] == self.currentShowName for show in self.AllShows()):
            self.currentShowName=ALL_PHOTOS
        images=self.ImagesForShow(self.currentShowName)
        if len(images) == 0:
            name, images=self.FirstShowWithPhotos()
            if name is None:
                self.ShowMessage("Edit Photo Shows", "None of the photo shows has any photos in it, so the display is unchanged.", warning=True)
                self.RebuildShowMenu()
                return
            self.currentShowName=name
        self.showVar.set(self.currentShowName)
        self.RebuildShowMenu()
        self.images=images
        self.history=[]
        self.histpos=-1
        self.NextImage()
        self.ScheduleAdvance()
        self.SaveState()

    # Append one Identify Photo save record to this session's output log -- a
    # pretty-printed JSON object followed by a blank line (concatenated JSON, loadable
    # with json.JSONDecoder().raw_decode in a loop) -- and rename the file so its name
    # carries the date and time of this latest save.
    # quiet is for a save nobody asked for -- the Identify panel timing out with something
    # written in it.  A failure then must not put a dialog on a public screen with nobody
    # in front of it: that would stop the show until somebody came and cleared it, which is
    # worse than the lost record it is reporting.
    def LogSave(self, record: dict, quiet: bool=False) -> None:
        if self.outputPath is None:         # This session's first save creates the file
            self.outputPath=os.path.join(ProgramDirectory(),
                                         f"SlideShow Output {time.strftime('%Y-%m-%d %H.%M.%S')}.json")
        text=json.dumps(record, indent=2, ensure_ascii=False)
        # Compact the four-number face boxes back onto one line for readability
        text=re.sub(r"\[\s+(-?\d+),\s+(-?\d+),\s+(-?\d+),\s+(-?\d+)\s+\]", r"[\1, \2, \3, \4]", text)
        try:
            with open(self.outputPath, "a", encoding="utf-8") as file:
                file.write(text+"\n\n")
        except OSError as e:
            if not quiet:
                messagebox.showwarning("SlideShow", f"This identification could not be saved:\n{e}", parent=self)
            return                      # The record really is lost; worth interrupting for

        # The name carries the time of the latest save, which is a convenience and not
        # the saving itself.  If the rename fails -- another program may have the file
        # open for a moment -- the record is safe under the name it has, so keep that
        # name, say nothing to whoever is at the screen, and let the next save try again.
        newPath=os.path.join(os.path.dirname(self.outputPath),
                             f"SlideShow Output {time.strftime('%Y-%m-%d %H.%M.%S')}.json")
        if newPath != self.outputPath:
            try:
                os.replace(self.outputPath, newPath)
                self.outputPath=newPath
            except OSError:
                pass

    # Remember the show being displayed and the monitor in use between invocations
    def SaveState(self) -> None:
        try:
            with open(self.statePath, "w", encoding="utf-8") as file:
                json.dump({"current show": self.currentShowName,
                           "monitor": list(self.CurrentMonitor())}, file)
        except (OSError, tk.TclError, AttributeError):
            pass

    # Record the monitor on the way out, so a window moved by other means (a Windows
    # shortcut, say) is still remembered
    def destroy(self) -> None:
        self.SaveState()
        super().destroy()

    # A show was picked from the menu: find its photos without stopping the one on
    # screen, and change over when they have been found
    def OnSelectShow(self) -> None:
        name=self.showVar.get()
        if name == self.currentShowName or name == self.switchingTo:
            return
        self.switchingTo=name
        # Say what is happening, but only if it takes long enough to be worth saying
        self.after(400, lambda: self.subdirLabel.config(text=f"Finding the photos in {name}...")
                   if self.switchingTo == name else None)

        def Done(images, error) -> None:
            if self.switchingTo != name:
                return                  # Another show was picked while this one was being found
            self.switchingTo=None
            if error is not None or len(images) == 0:
                self.showVar.set(self.currentShowName)      # Undo the pick
                self.ShowImage()        # Take the "finding..." note off the album line
                self.ShowMessage("Select Photo Show",
                                 f'"{name}" has no photos in it, so the show has not been changed.'
                                 if error is None else f'"{name}" could not be read:\n{error}')
                return
            self.currentShowName=name
            self.images=images
            self.history=[]
            self.histpos=-1
            self.NextImage()
            self.ScheduleAdvance()
            self.SaveState()

        self.InBackground(lambda: self.ImagesForShow(name), Done)

    # Turn a Piwigo date ("1942-06-04 00:00:00") into something readable
    # ("June 4, 1942").  January 1st is Piwigo's way of saying that only the year is
    # known, so such a date is shown as just the year.  Anything unrecognizable is
    # passed through as it stands.
    @staticmethod
    def FormatPhotoDate(value: str) -> str:
        date=value.strip().split(" ")[0]
        parts=date.split("-")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            return date
        year, month, day=(int(part) for part in parts)
        if month == 1 and day == 1:
            return str(year)
        if not 1 <= month <= 12:
            return date
        return f"{MONTHS[month-1]} {day}, {year}"

    # Count the display lines 'text' will occupy in 'font' when word-wrapped to a width
    # of 'width' pixels (mirroring tk's own wrapping).  A caption overflows the display
    # when this exceeds CAPTION_LINES.
    @staticmethod
    def CountWrappedLines(text: str, font: tkfont.Font, width: int) -> int:
        lines=0
        for para in text.split("\n"):
            line=""
            for word in para.split():
                trial=word if len(line) == 0 else line+" "+word
                if font.measure(trial) <= width:
                    line=trial
                else:
                    lines+=1
                    line=word
            lines+=1
        return lines


    # Return the full pathnames of all images in the trees under the listed directories,
    # in sorted order within each directory, directories in the order listed
    @staticmethod
    def ScanImages(rootDirectories: list[str], excluded=()) -> list[str]:
        keepOut={os.path.normcase(os.path.abspath(p)) for p in excluded}
        images=[]
        for rootDirectory in rootDirectories:
            for dirpath, dirnames, filenames in os.walk(rootDirectory):
                dirnames.sort(key=str.casefold)
                # Folders left out of the show are not descended into at all
                dirnames[:]=[d for d in dirnames
                             if os.path.normcase(os.path.abspath(os.path.join(dirpath, d))) not in keepOut]
                for fname in sorted(filenames, key=str.casefold):
                    if os.path.splitext(fname)[1].casefold() in IMAGE_EXTENSIONS:
                        images.append(os.path.join(dirpath, fname))
        return images


    # -------------------- Image selection --------------------
    # Move forward:  through the history if we had backed up with Prev, otherwise to a new image.
    def NextImage(self) -> None:
        if self.histpos < len(self.history)-1:
            self.histpos+=1
        else:
            if self.randomOrder:
                index=random.randrange(len(self.images))
                # Avoid showing the same image twice in a row
                if len(self.history) > 0 and len(self.images) > 1:
                    while index == self.history[-1]:
                        index=random.randrange(len(self.images))
            else:
                index=0 if len(self.history) == 0 else (self.history[-1]+1)%len(self.images)
            self.history.append(index)
            self.histpos=len(self.history)-1
        self.ShowImage()

    def PrevImage(self) -> None:
        if self.histpos > 0:
            self.histpos-=1
            self.ShowImage()

    def ShowImage(self) -> None:
        pathname=self.images[self.history[self.histpos]]

        # The optional subdirectory line: the path below the root directory (including
        # the TLD name, so with several shows checked each photo shows which it is from)
        subdir=os.path.relpath(os.path.dirname(pathname), self.rootDirectory)
        if not self.displaySubdirectory or subdir == ".":
            self.subdirLabel.config(text="")
        else:
            # When a directory's name is a prefix of the directory below it (e.g.,
            # "Tropicon/Tropicon 27"), displaying it adds nothing, so suppress it
            parts=subdir.split(os.sep)
            while len(parts) > 1 and parts[1].casefold().startswith(parts[0].casefold()):
                parts.pop(0)
            self.subdirLabel.config(text="/".join(parts))
        self.ArrangeHeader()            # The album text just changed; refit the header

        # The caption: each photo comes with same-named .txt (caption) and .xml (photo
        # info) files; the caption is the .txt content, or the filename if there is none
        base=os.path.splitext(pathname)[0]
        desc=""
        if os.path.exists(base+".txt"):
            try:
                with open(base+".txt", "r", encoding="utf-8", errors="replace") as file:
                    lines=[ln.strip() for ln in file.readlines() if len(ln.strip()) > 0]
                desc="\n".join(lines[:2])
            except OSError:
                pass
        if len(desc) == 0:
            desc=os.path.splitext(os.path.basename(pathname))[0]
        # Fit the caption to the display area it actually has (which may be a half of
        # the window while the Identify Photo panel is up, or a different monitor).
        # A long caption first gets extra lines, up to about a quarter of the display
        # area; only when that is not enough does the font shrink.
        wraplength=self.centerFrame.winfo_width()-40
        if wraplength < 100:
            wraplength=self.winfo_screenwidth()-100     # Not laid out yet -- fall back to a guess
        self.descLabel.config(wraplength=wraplength)

        def MaxLines() -> int:
            return max(CAPTION_LINES, int(self.centerFrame.winfo_height()*0.28/self.captionFont.metrics("linespace")))

        size=CAPTION_FONT_SIZE
        self.captionFont.configure(size=size)
        lines=self.CountWrappedLines(desc, self.captionFont, wraplength)
        while size > MIN_CAPTION_FONT_SIZE and lines > MaxLines():
            size-=2
            self.captionFont.configure(size=size)
            lines=self.CountWrappedLines(desc, self.captionFont, wraplength)
        self.descLabel.config(text=desc, height=max(CAPTION_LINES, min(lines, MaxLines())))

        # Below the caption, in smaller type, whatever the photo's .xml companion says
        # about where the photo came from and when it was taken
        author, photoDate="", ""
        if os.path.exists(base+".xml"):
            try:
                xmlRoot=ET.parse(base+".xml").getroot()
                author=(xmlRoot.findtext("author") or "").strip()
                photoDate=self.FormatPhotoDate(xmlRoot.findtext("date_creation") or "")
            except (ET.ParseError, OSError):
                pass
        credit=[]
        if len(author) > 0:
            credit.append(f"Photo supplied by {author}")
        if len(photoDate) > 0:
            credit.append(f"Photo date: {photoDate}")
        self.creditFont.configure(size=max(MIN_CREDIT_FONT_SIZE, size-CREDIT_FONT_SMALLER))
        if len(credit) == 0:
            self.creditLabel.pack_forget()          # Nothing to say, so take up no room
        else:
            self.creditLabel.config(text="\n".join(credit), wraplength=wraplength)
            if not self.creditLabel.winfo_ismapped():
                self.creditLabel.pack(side=tk.TOP)

        # The image itself, scaled to fit the space left over after the caption below it
        try:
            img=Image.open(pathname)
            fullWidth=img.width
            width=self.centerFrame.winfo_width()-20
            height=self.centerFrame.winfo_height()-self.descLabel.winfo_reqheight()-10
            if len(credit) > 0:
                height-=self.creditLabel.winfo_reqheight()
            if width < 50 or height < 50:       # Not laid out yet -- fall back to a guess
                width=self.winfo_screenwidth()-40
                height=self.winfo_screenheight()-300
            # Fit it to the space.  A photo bigger than the space is reduced to it; one
            # smaller is enlarged to fill it, but only up to Maximum Enlargement, since
            # past about twice its own size an old scan turns soft and blocky.  (This is
            # deliberately not Image.thumbnail, which only ever reduces -- it left a small
            # scan sitting at its own size in the middle of a large screen.)
            scale=min(width/img.width, height/img.height, self.maxEnlargement)
            if scale != 1.0:
                img=img.resize((max(1, round(img.width*scale)), max(1, round(img.height*scale))), Image.LANCZOS)
            # Kept so that a face can be marked on the photo while it is being identified
            self.displayedImage=img.convert("RGB")
            self.displayScale=img.width/fullWidth if fullWidth > 0 else 1.0
            self.photo=ImageTk.PhotoImage(img)      # Keep a reference or tk will garbage-collect it
            self.imageLabel.config(image=self.photo, text="")
        except Exception as e:
            self.displayedImage=None
            self.imageLabel.config(image="", text=f"Could not display\n{pathname}\n{e}", fg="white", font=("Segoe UI", 14))


    # -------------------- Timing --------------------
    def ScheduleAdvance(self) -> None:
        self.CancelAdvance()
        if not self.paused:
            self.advanceAfterId=self.after(int(self.displayTime*1000), self.OnTimer)

    def CancelAdvance(self) -> None:
        if self.advanceAfterId is not None:
            self.after_cancel(self.advanceAfterId)
            self.advanceAfterId=None

    def OnTimer(self) -> None:
        self.advanceAfterId=None
        self.NextImage()
        self.ScheduleAdvance()

    # Once a second: resume a paused show which has sat without user input for longer
    # than the pause timeout, and check the settings file for changes.
    def OnTick(self) -> None:
        if self.identifyPanel is not None and time.time()-self.lastInputTime >= self.identifyTimeout:
            self.TimeOutIdentifyPanel()
        if self.paused and not self.dialogOpen and time.time()-self.lastInputTime >= self.pauseTimeout:
            self.Resume()
        if len(self.editorEmail) > 0 and time.time()-self.lastInputTime >= self.emailTimeout:
            self.editorEmail=""         # Idle too long -- the next identifier may be someone else
        self.CheckSettingsFile()
        self.after(1000, self.OnTick)


    # -------------------- Live settings reload --------------------
    # If the settings file has changed, re-read it and apply only the parameters whose
    # values actually changed.  To avoid acting on a half-written file, a change is
    # applied only after two consecutive ticks read identical content.
    def CheckSettingsFile(self) -> None:
        try:
            mtime=os.stat(self.settingsPath).st_mtime
        except OSError:
            return                      # File briefly missing (mid-save) -- try again next tick
        if mtime == self.lastSettingsMtime and self.pendingSettings is None:
            return
        settings=ReadSettings(self.settingsPath)
        if settings is None:
            return
        self.lastSettingsMtime=mtime
        if settings != self.pendingSettings:
            self.pendingSettings=settings       # First look at new content -- wait for a stable second read
            return
        self.pendingSettings=None
        problems=self.ValidateSettings(settings)+self.ApplySettings(settings)
        if len(problems) > 0:
            self.ShowSettingsProblems(problems)

    # Apply newly-read settings, each parameter taking effect only if it changed.
    # Invalid values (bad numbers, bad directory) leave the current value in place;
    # missing parameters revert to their defaults.  Returns a list of complaints
    # about a Directory value which could not be used.
    def ApplySettings(self, settings: dict[str, str]) -> list[str]:
        problems=[]
        def Get(name: str, default: str) -> str:
            return settings.get(name.casefold(), default)

        title=Get("Title", "photos.fanac.org")
        if title != self.titleText:
            self.titleText=title
            self.titleLabel.config(text=title)

        fontName, fontSize=self.ResolveTitleFont(Get("Title Font", ""), Get("Title Font Size", ""))
        if fontName != self.titleFontName or fontSize != self.titleFontSize:
            self.titleFontName=fontName
            self.titleFontSize=fontSize
            self.titleLabel.config(font=(fontName, fontSize, "bold"))

        val=Get("Display Subdirectory", "True").casefold()
        if val in ("true", "yes", "false", "no"):        # An unrecognized value keeps the current setting
            displaySubdirectory=val in ("true", "yes")
            if displaySubdirectory != self.displaySubdirectory:
                self.displaySubdirectory=displaySubdirectory
                self.ShowImage()        # Refresh the current image's subdirectory line

        try:
            displayTime=float(Get("Display Time", "10"))
        except ValueError:
            displayTime=self.displayTime
        if displayTime > 0 and displayTime != self.displayTime:
            self.displayTime=displayTime
            self.ScheduleAdvance()      # Restart the clock with the new time (no-op while paused)

        try:
            pauseTimeout=float(Get("Pause Timeout", "240"))
        except ValueError:
            pauseTimeout=self.pauseTimeout
        if pauseTimeout > 0:
            self.pauseTimeout=pauseTimeout

        try:
            emailTimeout=float(Get("Email Timeout", "60"))
        except ValueError:
            emailTimeout=self.emailTimeout
        if emailTimeout > 0:
            self.emailTimeout=emailTimeout

        try:
            identifyTimeout=float(Get("Identify Timeout", "300"))
        except ValueError:
            identifyTimeout=self.identifyTimeout
        if identifyTimeout > 0:
            self.identifyTimeout=identifyTimeout

        self.faceThreshold=self.ResolveFaceThreshold(Get("Face Detection Threshold", ""))
        self.maxEnlargement=self.ResolveMaxEnlargement(Get("Maximum Enlargement", ""))

        mode=Get("Mode", "Dark").casefold()
        if mode in THEMES and THEMES[mode] is not self.theme:
            self.theme=THEMES[mode]
            self.ApplyTheme()

        order=Get("Order", "Sequential").casefold()
        if order.startswith("random"):
            self.randomOrder=True
        elif order.startswith("seq"):
            self.randomOrder=False
        # else: unrecognized value -- keep the current setting

        # A new root directory: rediscover its top-level directories.  The existing shows
        # are kept if any of them still finds photos there; if none does, they described
        # some other collection, so shows for the new root are made up instead.
        # (The path is a valid directory by construction of the parse.)
        newDirectories=settings.get("directories", [])
        if len(newDirectories) == 0:
            problems.append("No directory path is defined  (keeping the current one)")
        elif os.path.normcase(newDirectories[0]) != os.path.normcase(self.rootDirectory):
            tlds=self.FindTLDs(newDirectories[0])
            if len(tlds) == 0:
                problems.append(f"No directories found inside '{newDirectories[0]}'  (keeping the current one)")
                return problems
            oldRoot, oldTlds=self.rootDirectory, self.tlds
            self.rootDirectory, self.tlds=newDirectories[0], tlds
            name, images=self.FirstShowWithPhotos()
            if name is None:
                self.rootDirectory, self.tlds=oldRoot, oldTlds     # Nothing to show there
                problems.append(f"No image files found in the photo shows under '{newDirectories[0]}'  (keeping the current one)")
                return problems
            self.currentShowName=name
            self.showVar.set(name)
            self.images=images
            self.history=[]
            self.histpos=-1
            self.NextImage()
            self.ScheduleAdvance()
            self.RebuildShowMenu()
            self.SaveState()

        return problems


    # -------------------- Buttons --------------------
    def OnUserInput(self, event=None) -> None:
        self.lastInputTime=time.time()

    # Crisp little icons for the buttons, drawn rather than taken from font glyphs so
    # that they are bold, level, and vertically centered on the label text
    @staticmethod
    def MakeButtonIcons() -> dict[str, ImageTk.PhotoImage]:
        def New(width: int=15):
            im=Image.new("RGBA", (width, 15), (0, 0, 0, 0))
            return im, ImageDraw.Draw(im)
        icons={}
        im, d=New()                                             # Left arrow
        d.polygon([(0, 7), (6, 1), (6, 13)], fill="black")
        d.rectangle((6, 5, 14, 9), fill="black")
        icons["prev"]=ImageTk.PhotoImage(im)
        im, d=New()                                             # Right arrow
        d.polygon([(14, 7), (8, 1), (8, 13)], fill="black")
        d.rectangle((0, 5, 8, 9), fill="black")
        icons["next"]=ImageTk.PhotoImage(im)
        im, d=New()                                             # Pause bars
        d.rectangle((2, 1, 5, 13), fill="black")
        d.rectangle((9, 1, 12, 13), fill="black")
        icons["pause"]=ImageTk.PhotoImage(im)
        im, d=New()                                             # Play triangle
        d.polygon([(3, 1), (3, 13), (13, 7)], fill="black")
        icons["play"]=ImageTk.PhotoImage(im)
        im, _=New(1)                                            # Transparent spacer
        icons["blank"]=ImageTk.PhotoImage(im)

        # A writing pencil for Add Info, drawn a little larger to suit that button and
        # supersampled so its diagonal edges come out smooth
        size, ss=19, 4
        big=Image.new("RGBA", (size*ss, size*ss), (0, 0, 0, 0))
        d=ImageDraw.Draw(big)
        def Scale(points):
            return [(x*ss, y*ss) for x, y in points]
        d.polygon(Scale([(2.0, 17.0), (7.0, 15.7), (3.3, 12.0)]), fill="black")                     # Point
        d.polygon(Scale([(4.1, 11.4), (7.6, 14.9), (14.4, 8.1), (10.9, 4.6)]), fill="black")        # Body
        d.polygon(Scale([(11.8, 3.7), (15.3, 7.2), (17.0, 5.5), (13.5, 2.0)]), fill="black")        # Eraser
        icons["pencil"]=ImageTk.PhotoImage(big.resize((size, size), Image.LANCZOS))
        return icons

    # The one Pause/Continue button shows the action it will perform next
    def UpdateButtonStates(self) -> None:
        if self.paused:
            self.pauseButton.config(text=" Start Slideshow", image=self.buttonIcons["play"])
        else:
            self.pauseButton.config(text=" Pause", image=self.buttonIcons["pause"])

    # The button row is sized for the shape of the monitor the window is on.  A portrait
    # screen is the one people walk up to and touch, and it has vertical room to spare, so
    # there the buttons are half again as tall and the row sits half a button clear of the
    # bottom edge instead of hard against it.  Called when the show starts and again
    # whenever the window is dropped on another monitor, which need not be the same shape.
    def FitButtonRow(self) -> None:
        self.update_idletasks()                     # So a button just built reports its real height
        left, top, right, bottom=self.CurrentMonitor()
        portrait=(bottom-top) > (right-left)
        tallest=0
        for b in self.buttons:
            if b not in self.buttonNaturalHeight:
                self.buttonNaturalHeight[b]=b.winfo_reqheight()      # Its height at its own padding
            natural=self.buttonNaturalHeight[b]
            # pady is added at the top and at the bottom, so a quarter of the height at
            # each edge makes the button half again as tall
            extra=natural//4 if portrait else 0
            b.config(pady=self.buttonBasePady[b]+extra)
            tallest=max(tallest, natural+2*extra)   # As it now stands, not as it was built
        lift=tallest//2 if portrait else 0
        self.buttonFrame.pack_configure(pady=(BUTTON_PAD_TOP, BUTTON_PAD_BOTTOM+lift))

    def OnPauseContinue(self) -> None:
        if self.dialogOpen:
            return
        if self.paused:
            self.Resume()
        else:
            self.paused=True
            self.CancelAdvance()
            self.UpdateButtonStates()

    def Resume(self) -> None:
        self.paused=False
        self.UpdateButtonStates()
        self.ScheduleAdvance()

    # Moving to another photo takes the Identify Photo panel with it, and everything typed
    # into it: somebody who has just named four faces and touches Next to see the next
    # picture would lose all four without a word.  So when there is something to lose, ask
    # -- and offer to keep it, since keeping it is almost certainly what was meant.  With
    # nothing typed nothing is asked, so touching through photos is unaffected.
    # True means it is all right to leave.
    # Nobody has typed or touched anything for Identify Timeout seconds, so whoever opened
    # the panel has walked away from it.  Finish as they would have: save if they had
    # written anything, cancel if they had not, and let the show go on.  Without this the
    # panel holds the show on one photograph for the rest of the day -- the ordinary pause
    # timeout is deliberately suppressed while somebody is identifying faces, and there is
    # nothing else to notice that nobody is there any more.
    def TimeOutIdentifyPanel(self) -> None:
        panel=self.identifyPanel
        if panel.HasInput():
            panel.WriteRecord(quiet=True)   # Nobody is at the screen to read a warning
        self.CloseIdentifyPanel()           # As Cancel does: panel away, show running again

    def LeaveIdentifyPanel(self) -> bool:
        panel=self.identifyPanel
        if panel is None or not panel.HasInput():
            return True
        answer=messagebox.askyesnocancel("SlideShow",
                                         "You have not saved what you typed about this photo.\n\n"
                                         "Save it before moving to another photo?", parent=self)
        if answer is None:
            return False            # Thought better of it: stay on this photo, panel intact
        if answer:
            panel.WriteRecord()     # Save, but leave the panel to be closed by the move
        return True

    # Prev and Next work while the Identify Photo panel is up: the photo moves and the
    # panel is rebuilt for it, once anything typed has been saved or given up on.
    def OnNext(self) -> None:
        if self.dialogOpen and self.identifyPanel is None:
            return                  # Some other dialog is up
        if self.identifyPanel is not None:
            if not self.LeaveIdentifyPanel():
                return
            self.CloseIdentifyPanel(restore=False)
            self.NextImage()
            self.OnAddInfo(reopening=True)
            return
        self.NextImage()
        self.ScheduleAdvance()      # Restart the display-time clock

    def OnPrev(self) -> None:
        if self.dialogOpen and self.identifyPanel is None:
            return
        if self.identifyPanel is not None:
            if self.histpos == 0:
                return              # Nothing earlier to go to; leave the panel alone
            if not self.LeaveIdentifyPanel():
                return
            self.CloseIdentifyPanel(restore=False)
            self.PrevImage()
            self.OnAddInfo(reopening=True)
            return
        self.PrevImage()
        self.ScheduleAdvance()

    # Esc closes the Identify Photo panel when it is up -- it must not take the whole
    # show down with somebody's half-finished identification in it -- and otherwise
    # exits the show
    def OnEscape(self) -> None:
        if self.identifyPanel is not None:
            self.CloseIdentifyPanel()   # Just as the panel's own Cancel button does
            return
        if self.dialogOpen:
            return                      # Some other dialog is up; it can deal with the key
        self.destroy()

    # The arrow keys drive Prev/Next, except while a name or comment is being typed,
    # where they belong to the text cursor.  (focus_get() is None when the application
    # is not the active window, so fall back to the toplevel's remembered focus.)
    def OnArrowKey(self, forward: bool) -> None:
        focused=self.focus_get() or self.focus_lastfor()
        if isinstance(focused, (tk.Entry, tk.Text)):
            return
        if forward:
            self.OnNext()
        else:
            self.OnPrev()

    # -------------------- Identify Photo --------------------
    # Detect the faces in a PIL image.  Returns a list of (x, y, w, h) boxes in
    # left-to-right order, [] if there are none, or None if detection is unavailable
    # (OpenCV not installed or the model file missing).
    def DetectFaces(self, img: Image.Image) -> list[tuple[int, int, int, int]] | None:
        try:
            import cv2
            import numpy as np
        except ImportError:
            return None
        try:
            # Silence a harmless OpenCV 5 console warning ("Targets are not supported by the new graph engine")
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except AttributeError:
            pass
        modelPath=BundledFile(FACE_MODEL)
        if not os.path.exists(modelPath):
            return None
        # Detect on a downscaled copy for speed, then scale the boxes back up
        scale=1.0
        det=img
        if max(img.size) > FACE_DETECT_MAXDIM:
            scale=FACE_DETECT_MAXDIM/max(img.size)
            det=img.resize((round(img.width*scale), round(img.height*scale)), Image.LANCZOS)
        arr=cv2.cvtColor(np.array(det), cv2.COLOR_RGB2BGR)
        detector=cv2.FaceDetectorYN.create(modelPath, "", (det.width, det.height), self.faceThreshold)
        _, faces=detector.detect(arr)
        if faces is None:
            return []
        boxes=[(max(int(f[0]/scale), 0), max(int(f[1]/scale), 0), int(f[2]/scale), int(f[3]/scale)) for f in faces]
        boxes.sort(key=lambda b: b[0])
        return boxes

    # Put the Identify Photo panel and its separator on half the window, split the
    # narrow way: left/right on a landscape window, top/bottom on a portrait one.  The
    # window's own size is used, not the primary screen's, and this is re-done when the
    # window is dropped on another monitor.  Returns the panel's usable height.
    def PackIdentifyPanel(self) -> int:
        panel=self.identifyPanel
        width, height=self.winfo_width(), self.winfo_height()
        landscape=width > height
        side=tk.RIGHT if landscape else tk.BOTTOM
        fill=tk.Y if landscape else tk.X
        panel.pack_forget()
        panel.separator.pack_forget()
        panel.configure(width=max(width//2, 200), height=max(height//2, 200))
        panel.pack(side=side, fill=fill, before=self.showFrame)
        panel.separator.configure(width=2, height=2)
        panel.separator.pack(side=side, fill=fill, before=self.showFrame)
        self.update_idletasks()
        return panel.winfo_height()     # Its real height: it starts below the title area

    # Size the face table to the panel, leaving room for the boxes and buttons below it;
    # when there is more table than room, add the scrollbar and mouse-wheel scrolling
    def FitFaceTable(self, panelHeight: int) -> None:
        panel=self.identifyPanel
        self.update_idletasks()
        tableWidth=panel.table.winfo_reqwidth()
        tableHeight=panel.table.winfo_reqheight()
        # How much room the rest of the panel needs is measured rather than guessed, so
        # that a change of font, of DPI, or to the panel's own contents cannot push the
        # boxes and buttons below it off the bottom
        reserve=8                       # A pixel or two in hand
        for child in panel.winfo_children():
            if child.winfo_manager() == "pack":
                reserve+=PadTotal(child.pack_info().get("pady", 0))
            if child is not panel.tableHolder:
                reserve+=child.winfo_reqheight()
        maxTableHeight=max(120, panelHeight-reserve)
        panel.tableCanvas.configure(width=tableWidth, height=min(tableHeight, maxTableHeight),
                                    scrollregion=(0, 0, tableWidth, tableHeight))
        if tableHeight > maxTableHeight:
            if not panel.tableScrollbar.winfo_ismapped():
                panel.tableScrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            # Windows sends the wheel to whatever has the focus rather than to whatever
            # the pointer is over, so the binding has to be a global one which then works
            # out for itself whether the pointer is over the face table
            self.bind_all("<MouseWheel>", self.OnFaceTableWheel)
        else:
            panel.tableScrollbar.pack_forget()
            self.unbind_all("<MouseWheel>")

        # Measuring requested heights gets it very close; this checks the result with
        # everything actually in place and takes off any few pixels still hanging over
        self.update_idletasks()

        # The lowest point anything reaches, looking inside the rows too -- but not
        # inside the table, whose own rows hang below it on purpose, to be scrolled to
        def LowestPoint(widget) -> int:
            lowest=widget.winfo_rooty()+widget.winfo_height()
            for child in widget.winfo_children():
                if child.winfo_ismapped():
                    lowest=max(lowest, LowestPoint(child))
            return lowest

        panelBottom=panel.winfo_rooty()+panel.winfo_height()
        lowest=max((LowestPoint(child) for child in panel.winfo_children()
                    if child.winfo_ismapped() and child is not panel.tableHolder), default=panelBottom)
        if lowest > panelBottom:
            panel.tableCanvas.configure(height=max(60, panel.tableCanvas.winfo_height()-(lowest-panelBottom)))
            self.update_idletasks()

    # Scroll the face table, but only while the pointer is over it: over the comments
    # box, the photo, or anywhere else, the wheel is left to whatever is under it
    def OnFaceTableWheel(self, event) -> None:
        panel=self.identifyPanel
        if panel is None:
            return
        canvas=panel.tableCanvas
        # Is the pointer within the table's own rectangle?  (Its rows are widgets inside
        # the canvas, so asking about the rectangle covers them too.)
        if (canvas.winfo_rootx() <= event.x_root < canvas.winfo_rootx()+canvas.winfo_width()
                and canvas.winfo_rooty() <= event.y_root < canvas.winfo_rooty()+canvas.winfo_height()):
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    # While the mouse is held down on a face in the Identify Photo list, ring that face
    # in green on the photo itself, so it is clear which person the row is about
    def HighlightFace(self, box: tuple[int, int, int, int]) -> None:
        if getattr(self, "displayedImage", None) is None:
            return
        # The circle the row's thumbnail was cut from, scaled to the photo as displayed
        left, top, right, bottom=(v*self.displayScale for v in FaceCircleBounds(box))
        marked=self.displayedImage.copy()
        ImageDraw.Draw(marked).ellipse((left, top, right, bottom), outline=FACE_RING_GREEN,
                                       width=max(2, int((right-left)/24)))
        self.photo=ImageTk.PhotoImage(marked)
        self.imageLabel.config(image=self.photo)

    # Touching a face on the photograph itself is the most direct way of saying who
    # somebody is, and on a touch screen it is the gesture people try first.  It puts the
    # cursor in that face's name box; the focus rules then ring the face on the photo and
    # on its row, and Enter walks on down the rest.  With no panel up the photo is the
    # pause control instead, which is what it has always been.
    def OnPhotoClick(self, event) -> None:
        panel=self.identifyPanel
        if panel is None:
            self.OnPauseContinue()
            return
        # No shared geometry, or a photo which never displayed, means no faces to touch --
        # and the second guard is also what promises displayScale has been worked out
        if FaceCircleBounds is None or getattr(self, "displayedImage", None) is None:
            return
        # The photo sits inside the label's border, so the touch lands a couple of pixels
        # off the image.  Taking the offset from the two actual sizes corrects it whatever
        # border and padding the label happens to have.
        x=event.x-(self.imageLabel.winfo_width()-self.displayedImage.width)//2
        y=event.y-(self.imageLabel.winfo_height()-self.displayedImage.height)//2
        # The circles are in the original photograph's pixels and the photo on screen is
        # displayScale of that.  Of the circles touched, the nearest centre wins, so
        # overlapping faces in a group pick out the one actually aimed at.  Distances are
        # compared squared, which orders them the same and needs no square root.
        best, bestDistance=None, 0.0
        for i, box in enumerate(getattr(panel, "boxes", [])):
            left, top, right, bottom=(v*self.displayScale for v in FaceCircleBounds(box))
            radius=(right-left)/2
            dx, dy=x-(left+right)/2, y-(top+bottom)/2
            distance=dx*dx+dy*dy
            if distance <= radius*radius and (best is None or distance < bestDistance):
                best, bestDistance=i, distance
        if best is not None and best < len(panel.nameEntries):
            panel.nameEntries[best].focus_set()

    def ClearHighlight(self) -> None:
        if getattr(self, "displayedImage", None) is None:
            return
        self.photo=ImageTk.PhotoImage(self.displayedImage)
        self.imageLabel.config(image=self.photo)

    # Open the Identify Photo panel: the main window splits in two the narrow way
    # (left/right halves on a landscape screen, top/bottom halves on a portrait one),
    # the photo display is shoved into one half and the identification panel -- a table
    # with a row for each face found (left-to-right), each with a box for the person's
    # name, then a box for general comments, and Save/Cancel -- takes the other.
    # While the panel is up the show is paused; when it closes, the show returns to
    # whatever pause state it was in before.  Prev and Next stay live: they discard
    # whatever is unsaved, move the photo, and rebuild the panel for it (reopening=True
    # then, so that the pause state to return to is the one from the first opening).
    def OnAddInfo(self, reopening: bool=False) -> None:
        if self.identifyPanel is not None:
            return                      # Already open
        if not reopening:
            self.identifyWasPaused=self.paused
        self.paused=True
        self.dialogOpen=True
        self.CancelAdvance()
        self.UpdateButtonStates()
        # Pause and Add Info make no sense while identifying (Prev/Next stay live)
        for b in (self.pauseButton, self.addInfoButton):
            b.config(state=tk.DISABLED)

        pathname=self.images[self.history[self.histpos]]
        pbg=self.theme["panelBg"]
        pfg=self.theme["fg"]
        pdim=self.theme["subdirFg"]

        panel=tk.Frame(self, bg=pbg)
        panel.pack_propagate(False)             # Hold the half-window size regardless of content
        panel.separator=tk.Frame(self, bg=self.theme["separatorBg"])      # The thin band between the halves
        self.identifyPanel=panel
        panelHeight=self.PackIdentifyPanel()
        self.ShowImage()                # Rescale the photo into its reduced half

        tk.Label(panel, text="Identify Photo", font=("Segoe UI", 18, "bold"), fg=pfg, bg=pbg).pack(pady=(20, 5))

        # The face table lives in a canvas so that it can scroll when there are more
        # faces than fit in the panel
        tableHolder=tk.Frame(panel, bg=pbg)
        tableHolder.pack(pady=(5, 0))
        tableCanvas=tk.Canvas(tableHolder, bg=pbg, highlightthickness=0)
        tableScrollbar=tk.Scrollbar(tableHolder, orient=tk.VERTICAL, command=tableCanvas.yview,
                                    bg=self.theme["scrollThumb"], activebackground=self.theme["scrollActive"],
                                    troughcolor=self.theme["scrollTrough"], bd=0, highlightthickness=0)
        tableCanvas.configure(yscrollcommand=tableScrollbar.set)
        tableCanvas.pack(side=tk.LEFT)
        table=tk.Frame(tableCanvas, bg=pbg)
        tableCanvas.create_window((0, 0), window=table, anchor="nw")
        tk.Label(table, text="", bg=pbg).grid(row=0, column=0)
        tk.Label(table, text="Name", font=("Segoe UI", 12), fg=pfg, bg=pbg).grid(row=0, column=2, sticky="w")
        panel.thumbnails=[]             # Keep references so tk doesn't garbage-collect the images
        nameEntries=[]
        panel.nameEntries=nameEntries   # The same list, so touching a face on the photo can reach the rows
        inputVars=[]                    # Watched, so a box can be tinted as soon as it has something in it
        # Every box on the panel, with the question "is there anything in it?", so that
        # TintBoxes can colour the filled ones without caring what kind of box each is
        tinted=[]
        panel.boxes=[]                  # The faces, once they have been looked for
        panel.focusedBox=None           # The face whose name box has the cursor, if any
        # Reading the photograph and looking for faces in it is the slow part, and the
        # panel must not sit there unbuilt while it happens: it is put up at once,
        # saying so, and the rows are added when the thread comes back.
        working=tk.Label(table, text="Looking for faces...", font=("Segoe UI", 11), fg=pdim, bg=pbg)
        working.grid(row=1, column=0, columnspan=3)

        # Kept so the panel can be re-split when the window moves to another monitor
        panel.table, panel.tableCanvas, panel.tableScrollbar, panel.tableHolder=table, tableCanvas, tableScrollbar, tableHolder
        self.FitFaceTable(panelHeight)

        # In the thread: read the photograph, find the faces, and cut the round pictures
        # (all of it PIL, none of it tk).  Turning those into tk images, and building the
        # rows, happens below on the screen's thread.
        def FindFaces():
            try:
                img=Image.open(pathname).convert("RGB")
            except Exception:
                return None, None, []
            boxes=self.DetectFaces(img)
            if boxes is None or RoundFaceThumbnail is None:
                return img, None, []
            return img, boxes, [RoundFaceThumbnail(img, box, pbg) for box in boxes]

        def AddFaceRows(found, error) -> None:
            if self.identifyPanel is not panel or not table.winfo_exists():
                return                  # The panel has been closed, or moved on to another photo
            img, boxes, pictures=found if error is None else (None, None, [])
            working.destroy()
            # Why there are no faces to show matters: the shared geometry is missing, the
            # photo would not open, face detection is not installed, or the photo simply
            # has nobody in it
            if RoundFaceThumbnail is None:
                message="(FaceGeometry.py, shared with PhotosEditor, was not found)"
            elif error is not None:
                message=f"(This photo could not be read: {error})"
            elif img is None:
                message="(This photo could not be read)"
            elif boxes is None:
                message="(Face detection is unavailable)"
            else:
                message="(No faces detected)"

            if boxes is None or len(boxes) == 0:
                tk.Label(table, text=message, font=("Segoe UI", 11), fg=pdim, bg=pbg).grid(row=1, column=0, columnspan=3)
            else:
                panel.boxes=list(boxes)
                # Each row is numbered so a comment can refer to a face by its number
                for i, (box, picture) in enumerate(zip(boxes, pictures)):
                    thumb=ImageTk.PhotoImage(picture)
                    # The same round picture with a green ring drawn round it, shown while
                    # this row's name box has the cursor.  The face circle is inscribed in
                    # the square picture, so the ring is simply its outline -- the same
                    # green and the same proportional width as the ring on the photo.
                    ringed=picture.copy()
                    ImageDraw.Draw(ringed).ellipse((0, 0, ringed.width-1, ringed.height-1),
                                                   outline=FACE_RING_GREEN, width=max(2, ringed.width//24))
                    ringedThumb=ImageTk.PhotoImage(ringed)
                    panel.thumbnails.append(thumb)
                    panel.thumbnails.append(ringedThumb)        # Both kept, or tk collects them
                    numberLabel=tk.Label(table, text=f"#{i+1}", font=("Segoe UI", 12), fg=pfg, bg=pbg)
                    numberLabel.grid(row=i+1, column=0, padx=(0, 8), sticky="e")
                    faceLabel=tk.Label(table, image=thumb, bg=pbg)
                    faceLabel.grid(row=i+1, column=1, padx=(0, 12), pady=4)
                    var=tk.StringVar()
                    inputVars.append(var)
                    var.trace_add("write", TintBoxes)
                    entry=tk.Entry(table, font=("Segoe UI", ENTRY_FONT_SIZE), width=32, textvariable=var)
                    entry.grid(row=i+1, column=2, sticky="w")
                    nameEntries.append(entry)
                    tinted.append((entry, lambda v=var: len(v.get().strip()) > 0))
                    # Typing in a row rings that row's face both ways -- on the row's own
                    # picture and on the photo -- so it stays clear whose name is being
                    # written once the mouse has left the row to use the keyboard
                    def OnRowFocus(e, lbl=faceLabel, im=ringedThumb, box=box) -> None:
                        lbl.config(image=im)
                        panel.focusedBox=box
                        self.HighlightFace(box)

                    def OnRowUnfocus(e, lbl=faceLabel, im=thumb) -> None:
                        lbl.config(image=im)
                        panel.focusedBox=None
                        self.ClearHighlight()

                    entry.bind("<FocusIn>", OnRowFocus)
                    entry.bind("<FocusOut>", OnRowUnfocus)
                    entry.bind("<Return>", NextBox)         # Down to the next box, and round at the end
                    entry.bind("<KP_Enter>", NextBox)
                    for w in (numberLabel, faceLabel, entry):
                        ToolTip(w, "If you can identify this person, give us a name and, if appropriate, a reason why.  (The latter is not required)  "
                                   "You do not need to fill in any rows except ones you have data for.  "
                                   "Point at the face to see who it is in the photo.")
                    # One rule decides which face is circled on the photo.  If a name box
                    # has the cursor it is that row's face, and nothing else moves it --
                    # so the mark cannot be pulled off the face whose name is being
                    # written.  Only when no name box has the cursor does pointing at a
                    # row decide, and then pointing away clears the photo again.
                    for w in (numberLabel, faceLabel, entry):
                        w.bind("<Enter>", lambda e, box=box: self.HighlightFace(box) if panel.focusedBox is None else None)
                        w.bind("<Leave>", lambda e: self.ClearHighlight() if panel.focusedBox is None else None)
                if len(commentsBox.get("1.0", tk.END).strip()) == 0:
                    nameEntries[0].focus_set()      # Ready to type -- unless a comment is already being written

            self.FitFaceTable(panel.winfo_height())

        tk.Label(panel, text="", bg=pbg).pack()
        commentsLabel=tk.Label(panel, text="Other Comments and Corrections", font=("Segoe UI", 12), fg=pfg, bg=pbg)
        commentsLabel.pack()
        commentsBox=tk.Text(panel, font=("Segoe UI", COMMENTS_FONT_SIZE), width=48, height=4)
        commentsBox.pack(pady=(4, 0))
        tinted.append((commentsBox, lambda: len(commentsBox.get("1.0", tk.END).strip()) > 0))
        for w in (commentsLabel, commentsBox):
            ToolTip(w, "Tell us more: When/where was the photo taken?  Who took it?  Other interesting details.")

        dateRow=tk.Frame(panel, bg=pbg)
        dateRow.pack(pady=(8, 0))
        dateLabel=tk.Label(dateRow, text="Photo Date:", font=("Segoe UI", 12), fg=pfg, bg=pbg)
        dateLabel.pack(side=tk.LEFT, padx=(0, 8))
        dateVar=tk.StringVar()
        inputVars.append(dateVar)
        dateEntry=tk.Entry(dateRow, font=("Segoe UI", ENTRY_FONT_SIZE), width=30, textvariable=dateVar)
        dateEntry.pack(side=tk.LEFT)
        tinted.append((dateEntry, lambda: len(dateVar.get().strip()) > 0))
        for w in (dateLabel, dateEntry):
            ToolTip(w, "If you know when this photo was taken, tell us here.  A year alone is fine.")

        # The email address is remembered between saves as long as the user stays
        # active; OnTick forgets it after Email Timeout seconds without input.  (It is
        # created here but packed below the buttons, further down.)
        emailRow=tk.Frame(panel, bg=pbg)
        emailLabel=tk.Label(emailRow, text="Your name/email address:", font=("Segoe UI", 12), fg=pfg, bg=pbg)
        emailLabel.pack(side=tk.LEFT, padx=(0, 8))
        emailVar=tk.StringVar(value=self.editorEmail)       # Prefilled from the last save, while it is remembered
        prefilledEmail=self.editorEmail                     # What it holds before anybody touches it
        emailEntry=tk.Entry(emailRow, font=("Segoe UI", ENTRY_FONT_SIZE), width=30, textvariable=emailVar)
        emailEntry.pack(side=tk.LEFT)
        tinted.append((emailEntry, lambda: len(emailVar.get().strip()) > 0))

        # Enter steps down to the next box and round from the last back to the first, so a
        # whole photograph can be named from the keyboard without reaching for the mouse.
        # The order is the order down the panel: the faces, then the date, then who is
        # telling us.  The comments box is deliberately not in the ring -- Enter there
        # starts a new line, which is what somebody writing several sentences expects.
        # The list is rebuilt on each press because the face rows do not exist until the
        # thread has finished looking for faces.
        def NextBox(event) -> str:
            boxes=nameEntries+[dateEntry, emailEntry]
            try:
                here=boxes.index(event.widget)
            except ValueError:
                return "break"          # Not one of ours; leave the cursor where it is
            boxes[(here+1) % len(boxes)].focus_set()
            return "break"

        for w in (dateEntry, emailEntry):
            w.bind("<Return>", NextBox)
            w.bind("<KP_Enter>", NextBox)       # The keypad's Enter is the same key to a typist
        for w in (emailLabel, emailEntry):
            ToolTip(w, "Please let us know who is submitting this information, so we can give you credit.")

        def Close(restore: bool=True) -> None:
            self.unbind_all("<MouseWheel>")
            self.ClearHighlight()       # In case the panel is closed with a face still marked
            panel.destroy()
            panel.separator.destroy()
            self.identifyPanel=None
            if not restore:
                return                  # Moving to another photo; the panel is about to be rebuilt
            self.dialogOpen=False
            for b in (self.pauseButton, self.addInfoButton):
                b.config(state=tk.NORMAL)
            self.lastInputTime=time.time()
            if self.identifyWasPaused:
                self.UpdateButtonStates()
            else:
                self.Resume()
            self.update_idletasks()
            self.ShowImage()            # Rescale the photo back to the full display
        self.CloseIdentifyPanel=Close

        # Writing the record is separate from closing the panel, because moving on to the
        # next photo needs to save without the panel being put away and the show restarted
        def WriteRecord(quiet: bool=False) -> None:
            # The photo's Piwigo id and file name come from its .xml companion file
            photoId=None
            photoFile=os.path.basename(pathname)
            xmlPath=os.path.splitext(pathname)[0]+".xml"
            if os.path.exists(xmlPath):
                try:
                    xmlRoot=ET.parse(xmlPath).getroot()
                    idText=(xmlRoot.findtext("id") or "").strip()
                    if idText.isdigit():
                        photoId=int(idText)
                    photoFile=(xmlRoot.findtext("file") or "").strip() or photoFile
                except (ET.ParseError, OSError):
                    pass
            album=os.path.relpath(os.path.dirname(pathname), self.rootDirectory)
            album="" if album == "." else album.replace(os.sep, "/")
            self.editorEmail=emailEntry.get().strip()
            self.LogSave({
                "saved":      time.strftime("%Y-%m-%d %H:%M:%S"),
                "photo id":   photoId,
                "file":       photoFile,
                "album":      album,
                "editor":     self.editorEmail,
                "faces":      [{"number": i+1, "name": e.get().strip(), "box": list(box)} for i, (e, box) in enumerate(zip(nameEntries, panel.boxes))],
                "comment":    commentsBox.get("1.0", tk.END).strip(),
                "photo date": dateEntry.get().strip(),
            }, quiet)

        def OnSave() -> None:
            WriteRecord()
            Close()

        # Is there anything here worth keeping?  The address box does not count while it
        # still holds what was filled in from the last save: otherwise leaving a photo
        # nobody had typed a word about would stop and ask.
        panel.WriteRecord=WriteRecord
        panel.HasInput=lambda: (any(len(v.get().strip()) > 0 for v in inputVars)
                                or len(commentsBox.get("1.0", tk.END).strip()) > 0
                                or emailVar.get().strip() != prefilledEmail)

        buttons=tk.Frame(panel, bg=pbg)
        buttons.pack(pady=15)
        tk.Button(buttons, text="Save", font=("Segoe UI", PANEL_BUTTON_FONT_SIZE), width=9, command=OnSave).pack(side=tk.LEFT, padx=8)
        cancelButton=tk.Button(buttons, text="Cancel", font=("Segoe UI", PANEL_BUTTON_FONT_SIZE), width=9, command=Close)
        cancelButton.pack(side=tk.LEFT, padx=8)

        emailRow.pack(pady=(30, 0))     # Below the buttons, set apart from them

        # A box with anything in it is tinted, so a glance shows what has been filled in
        # and what has not -- worth having when the face table is long enough to scroll,
        # and reassurance to somebody who has just typed a name that it was taken.
        def TintBoxes(*args) -> None:
            for box, hasContent in tinted:
                box.config(bg=FILLED_BOX_BG if hasContent() else EMPTY_BOX_BG)

        for var in inputVars+[emailVar]:
            var.trace_add("write", TintBoxes)
        def OnCommentsModified(event=None) -> None:
            if commentsBox.edit_modified():
                commentsBox.edit_modified(False)        # Rearm, and do not recurse on the reset
                TintBoxes()
        commentsBox.bind("<<Modified>>", OnCommentsModified)
        TintBoxes()                     # The email box may already be filled in from a previous save

        # Ready to type without reaching for the mouse: the first name box, or the
        # comments box when the photo has no faces to name
        commentsBox.focus_set()         # Until the faces arrive, which take the focus then

        self.InBackground(FindFaces, AddFaceRows)


# The Edit Photo Shows dialog: the named shows on the left, and on the right the folder
# tree with a check box on every folder.  A checked folder stands for itself and
# everything below it, so checking a folder unchecks any of its descendants (they would
# be redundant), and unchecking a folder inside a checked one keeps the rest of that
# folder's contents by checking the siblings along the way down.
class ShowEditor(tk.Toplevel):
    PLACEHOLDER="\x01unfilled"      # Suffix of the dummy child which marks "not filled in yet"
                                    # (not \x00: Tcl truncates strings at a NUL)
    MISSING="\x01missing:"          # Prefix of the rows for folders which are no longer there

    def __init__(self, app: "SlideShow") -> None:
        super().__init__(app)
        self.app=app
        self.rootDirectory=app.rootDirectory
        self.shows=[{"name": show["name"], "folders": list(show["folders"]),                            # Working copy
                     "except": list(show.get("except", []))} for show in app.shows]
        self.originalDigest=self.Digest(self.shows)     # To tell later whether anything was changed
        self.selected: set[str]=set()       # Folders chosen
        self.excluded: set[str]=set()       # ...and folders left out of them again
        self.countGeneration=0
        self.counts=queue.Queue()       # Photo counts from the counting threads
        self.pollId=None
        self.icons=self.MakeCheckboxIcons()

        self.title("Edit Photo Shows")
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        tk.Label(self, text="Photo Shows", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", padx=(12, 6), pady=(10, 4))
        self.foldersLabel=tk.Label(self, text="Folders", font=("Segoe UI", 11, "bold"))
        self.foldersLabel.grid(row=0, column=1, sticky="w", padx=6, pady=(10, 4))

        listFrame=tk.Frame(self)
        listFrame.grid(row=1, column=0, sticky="ns", padx=(12, 6))
        self.showList=tk.Listbox(listFrame, font=("Segoe UI", 11), width=26, exportselection=False, activestyle="none")
        self.showList.pack(side=tk.LEFT, fill=tk.Y, expand=True)
        listScroll=tk.Scrollbar(listFrame, orient=tk.VERTICAL, command=self.showList.yview)
        listScroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.showList.configure(yscrollcommand=listScroll.set)
        self.showList.bind("<<ListboxSelect>>", self.OnPickShow)

        treeFrame=tk.Frame(self)
        treeFrame.grid(row=1, column=1, sticky="nsew", padx=6)
        self.tree=ttk.Treeview(treeFrame, show="tree", selectmode="none")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        treeScroll=tk.Scrollbar(treeFrame, orient=tk.VERTICAL, command=self.tree.yview)
        treeScroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=treeScroll.set)
        self.tree.tag_configure("missing", foreground="#909090")
        self.tree.bind("<Button-1>", self.OnTreeClick)
        self.tree.bind("<<TreeviewOpen>>", self.OnTreeOpen)

        showButtons=tk.Frame(self)
        showButtons.grid(row=2, column=0, sticky="w", padx=(12, 6), pady=(6, 0))
        for text, command in (("New", self.OnNew), ("Rename", self.OnRename), ("Delete", self.OnDelete)):
            tk.Button(showButtons, text=text, font=("Segoe UI", 10), width=8, command=command).pack(side=tk.LEFT, padx=(0, 4))

        # Under the tree: the show in words, and what it comes to
        below=tk.Frame(self)
        below.grid(row=2, column=1, sticky="ew", padx=6, pady=(6, 0))
        self.summaryLabel=tk.Label(below, text="", font=("Segoe UI", 10), justify=tk.LEFT,
                                   anchor="w", wraplength=560)
        self.summaryLabel.pack(fill=tk.X)
        self.countLabel=tk.Label(below, text="", font=("Segoe UI", 10), fg="#606060", anchor="w")
        self.countLabel.pack(fill=tk.X)

        dialogButtons=tk.Frame(self)
        dialogButtons.grid(row=3, column=0, columnspan=2, pady=14)
        tk.Button(dialogButtons, text="Save", font=("Segoe UI", 11), width=10, command=self.OnSave).pack(side=tk.LEFT, padx=8)
        tk.Button(dialogButtons, text="Cancel", font=("Segoe UI", 11), width=10, command=self.OnCancel).pack(side=tk.LEFT, padx=8)
        self.protocol("WM_DELETE_WINDOW", self.OnCancel)

        self.FillShowList(app.currentShowName)
        self.FillTree()

        # Centered on the monitor the show is on, at a size which suits a folder tree
        self.update_idletasks()
        left, top, right, bottom=app.CurrentMonitor()
        width, height=min(920, right-left-80), min(640, bottom-top-80)
        self.geometry(f"{width}x{height}+{left+(right-left-width)//2}+{top+(bottom-top-height)//2}")
        self.transient(app)
        self.grab_set()
        self.PollCounts()


    # -------------------- Folders --------------------
    # The relative paths of the subdirectories of a relative folder ("" is the root)
    def ChildFolders(self, folder: str) -> list[str]:
        directory=os.path.join(self.rootDirectory, folder.replace("/", os.sep)) if len(folder) > 0 else self.rootDirectory
        try:
            names=sorted((n for n in os.listdir(directory) if os.path.isdir(os.path.join(directory, n))), key=str.casefold)
        except OSError:
            return []
        return [f"{folder}/{name}" if len(folder) > 0 else name for name in names]

    # Is this folder in the show?  There are only the two answers: the box says whether
    # the folder's photos are shown, and the most specific rule covering it decides.
    def IsIncluded(self, folder: str) -> bool:
        return FolderIsIncluded(folder, self.selected, self.excluded)

    # Ticking a folder takes it and everything below it; unticking leaves out it and
    # everything below it.  Neither touches the folder's parent or its brothers and
    # sisters, and ticking a folder clears whatever was said about its contents, so
    # rules can never pile up out of sight.
    def Toggle(self, folder: str) -> None:
        folder=NormalizeFolder(folder)
        if self.IsIncluded(folder):
            if folder in self.selected:
                self.selected.discard(folder)       # it was chosen in its own right
            else:
                self.excluded.add(folder)           # it comes in with a folder above it
        else:
            self.excluded.discard(folder)
            self.selected.add(folder)
        Below=lambda entry: entry != folder and IsCoveredBy(entry, folder)
        self.selected={f for f in self.selected if not Below(f)}
        self.excluded={f for f in self.excluded if not Below(f)}
        chosen, excluded=TidyRules(self.selected, self.excluded)
        self.selected, self.excluded=set(chosen), set(excluded)

    # What is chosen or left out strictly below a folder, for the note on its row
    def RulesUnder(self, folder: str) -> tuple[int, int]:
        chosen=sum(1 for f in self.selected if f != folder and IsCoveredBy(f, folder))
        excluded=sum(1 for f in self.excluded if f != folder and IsCoveredBy(f, folder))
        return chosen, excluded

    # The show in words, for the line under the tree
    def SummaryText(self) -> str:
        if len(self.selected) == 0:
            return "No folders chosen"
        parts=[]
        for folder in sorted(self.selected, key=str.casefold):
            inside=sorted((e for e in self.excluded if e != folder and IsCoveredBy(e, folder)), key=str.casefold)
            if len(inside) > 0:
                shortened=[e[len(folder)+1:] for e in inside]
                parts.append(f"all of {folder} except "+", ".join(shortened))
            else:
                parts.append(folder)
        return "; ".join(parts)


    # -------------------- The tree --------------------
    @staticmethod
    def MakeCheckboxIcons() -> dict[str, ImageTk.PhotoImage]:
        icons={}
        size, ss=14, 4
        for name in ("unchecked", "checked"):
            image=Image.new("RGBA", (size*ss, size*ss), (0, 0, 0, 0))
            draw=ImageDraw.Draw(image)
            draw.rectangle((ss, ss, (size-2)*ss, (size-2)*ss), fill="white", outline="#606060", width=ss)
            if name == "checked":
                draw.line([(4*ss, 7*ss), (6*ss, 9*ss), (9*ss, 4*ss)], fill="#202020", width=2*ss)
            icons[name]=ImageTk.PhotoImage(image.resize((size, size), Image.LANCZOS))
        return icons

    def FillTree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for folder in self.ChildFolders(""):
            self.InsertFolder("", folder)
        # Selected folders which are no longer on disk, so they can be cleaned up
        for folder in sorted(self.selected, key=str.casefold):
            if not os.path.isdir(os.path.join(self.rootDirectory, folder.replace("/", os.sep))):
                self.tree.insert("", tk.END, iid=self.MISSING+folder, text=f"  {folder}   (folder no longer exists)",
                                 image=self.icons["checked"], tags=("missing",))
        self.RevealRules()
        self.RefreshImages()
        self.UpdateCount()

    # Open every branch which has something chosen or left out inside it, so that a
    # show's shape is visible on opening rather than hidden under a closed folder
    def RevealRules(self) -> None:
        for rule in sorted(self.selected|self.excluded, key=str.casefold):
            parts=rule.split("/")
            for depth in range(1, len(parts)):
                parent="/".join(parts[:depth])
                if not self.tree.exists(parent):
                    break
                self.FillFolder(parent)
                self.tree.item(parent, open=True)

    # Replace a folder's "not filled in yet" marker with its real children
    def FillFolder(self, folder: str) -> None:
        placeholder=folder+self.PLACEHOLDER
        if self.tree.exists(placeholder):
            self.tree.delete(placeholder)
            for child in self.ChildFolders(folder):
                self.InsertFolder(folder, child)

    def InsertFolder(self, parent: str, folder: str) -> None:
        self.tree.insert(parent, tk.END, iid=folder, text="  "+os.path.basename(folder), image=self.icons["unchecked"])
        if len(self.ChildFolders(folder)) > 0:
            self.tree.insert(folder, tk.END, iid=folder+self.PLACEHOLDER, text="")

    # Fill in the children of a folder which has just been opened.  The item's "open"
    # flag is not set until after <<TreeviewOpen>> has been dealt with, so the folder
    # in hand is filled in now and the rest are swept up once the event is over.
    def OnTreeOpen(self, event=None) -> None:
        self.FillOpenedFolders()
        self.after(0, self.FillOpenedFolders)

    def FillOpenedFolders(self) -> None:
        if not self.tree.winfo_exists():
            return                      # The dialog has been closed
        justOpened=self.tree.focus()
        for iid in self.AllItems():
            if iid.endswith(self.PLACEHOLDER):
                parent=iid[:-len(self.PLACEHOLDER)]
                if self.tree.item(parent, "open") or parent == justOpened:
                    self.FillFolder(parent)
        self.RefreshImages()

    def AllItems(self, parent: str="") -> list[str]:
        items=[]
        for iid in self.tree.get_children(parent):
            items.append(iid)
            items.extend(self.AllItems(iid))
        return items

    # Each row shows whether its folder is in the show, and -- since a collapsed
    # folder would otherwise hide it -- a note of anything chosen or left out below it
    def RefreshImages(self) -> None:
        for iid in self.AllItems():
            if iid.endswith(self.PLACEHOLDER) or iid.startswith(self.MISSING):
                continue
            chosen, excluded=self.RulesUnder(iid)
            notes=[]
            if excluded > 0:
                notes.append(f"{excluded} folder{'' if excluded == 1 else 's'} left out")
            if chosen > 0 and not self.IsIncluded(iid):
                notes.append(f"{chosen} folder{'' if chosen == 1 else 's'} chosen inside")
            note="   ("+", ".join(notes)+")" if len(notes) > 0 else ""
            self.tree.item(iid, image=self.icons["checked" if self.IsIncluded(iid) else "unchecked"],
                           text="  "+os.path.basename(iid)+note)

    def OnTreeClick(self, event) -> None:
        iid=self.tree.identify_row(event.y)
        if len(iid) == 0 or iid.endswith(self.PLACEHOLDER):
            return
        if "indicator" in self.tree.identify_element(event.x, event.y):
            return                      # The expand/collapse arrow does its own job
        if iid.startswith(self.MISSING):
            gone=iid[len(self.MISSING):]                        # Cleaning up a folder which has gone
            self.selected.discard(gone)
            self.excluded.discard(gone)
            self.tree.delete(iid)
        else:
            self.Toggle(iid)
            self.RefreshImages()
        self.UpdateCount()

    # Count the photos of the current selection without holding up the dialog.  The
    # counting thread must not touch tk at all (tkinter is not thread-safe), so it drops
    # its answer in a queue which the dialog itself picks up.
    def UpdateCount(self) -> None:
        self.countGeneration+=1
        generation=self.countGeneration
        self.summaryLabel.config(text=self.SummaryText())
        folders, excluded=TidyRules(self.selected, self.excluded)
        if len(folders) == 0:
            self.countLabel.config(text="No folders chosen")
            return
        self.countLabel.config(text=f"{len(folders)} folder{'' if len(folders) == 1 else 's'}, counting photos...")
        paths=[os.path.join(self.rootDirectory, folder.replace("/", os.sep)) for folder in folders]
        keepOut=[os.path.join(self.rootDirectory, folder.replace("/", os.sep)) for folder in excluded]
        def Count() -> None:
            found=len(SlideShow.ScanImages([p for p in paths if os.path.isdir(p)], keepOut))
            self.counts.put((generation, len(folders), found))
        threading.Thread(target=Count, daemon=True).start()

    def PollCounts(self) -> None:
        try:
            while True:
                generation, folders, photos=self.counts.get_nowait()
                if generation == self.countGeneration:
                    self.countLabel.config(text=f"{folders} folder{'' if folders == 1 else 's'}, {photos:,} photo{'' if photos == 1 else 's'}")
        except queue.Empty:
            pass
        self.pollId=self.after(150, self.PollCounts)

    def destroy(self) -> None:
        if getattr(self, "pollId", None) is not None:
            self.after_cancel(self.pollId)
            self.pollId=None
        super().destroy()


    # -------------------- The list of shows --------------------
    def FillShowList(self, select: str="") -> None:
        self.showList.delete(0, tk.END)
        for show in self.shows:
            self.showList.insert(tk.END, show["name"])
        if len(self.shows) == 0:        # Nothing built yet: All Photos is built in and not listed here
            self.loadedIndex=-1
            self.selected, self.excluded=set(), set()
            self.foldersLabel.config(text='Press "New" to make a photo show')
            if hasattr(self, "tree"):
                self.FillTree()
            return
        index=next((i for i, show in enumerate(self.shows) if show["name"] == select), 0)
        self.showList.selection_clear(0, tk.END)
        self.showList.selection_set(index)
        self.LoadShow(index)

    def CurrentIndex(self) -> int:
        selection=self.showList.curselection()
        return selection[0] if len(selection) > 0 else -1

    def LoadShow(self, index: int) -> None:
        self.loadedIndex=index
        chosen, excluded=TidyRules(self.shows[index]["folders"], self.shows[index].get("except", []))
        self.selected, self.excluded=set(chosen), set(excluded)
        self.foldersLabel.config(text=f'Folders in "{self.shows[index]["name"]}"')
        if hasattr(self, "tree"):
            self.FillTree()

    # Keep whatever has been ticked for the show being left
    def StoreShow(self) -> None:
        if 0 <= getattr(self, "loadedIndex", -1) < len(self.shows):
            chosen, excluded=TidyRules(self.selected, self.excluded)
            self.shows[self.loadedIndex]["folders"]=chosen
            self.shows[self.loadedIndex]["except"]=excluded

    def OnPickShow(self, event=None) -> None:
        index=self.CurrentIndex()
        if index < 0 or index == getattr(self, "loadedIndex", -1):
            return
        self.StoreShow()
        self.LoadShow(index)

    def AskName(self, title: str, initial: str="") -> str | None:
        name=simpledialog.askstring(title, "Name of the photo show:", initialvalue=initial, parent=self)
        if name is None:
            return None
        name=name.strip()
        if len(name) == 0:
            return None
        if any(show["name"] == name for show in self.shows if show["name"] != initial):
            messagebox.showwarning("Edit Photo Shows", f'There is already a photo show named "{name}".', parent=self)
            return None
        return name

    def OnNew(self) -> None:
        name=self.AskName("New Photo Show")
        if name is None:
            return
        self.StoreShow()
        self.shows.append({"name": name, "folders": [], "except": []})
        self.FillShowList(name)

    def OnRename(self) -> None:
        index=self.CurrentIndex()
        if index < 0:
            return
        name=self.AskName("Rename Photo Show", self.shows[index]["name"])
        if name is None:
            return
        self.StoreShow()
        self.shows[index]["name"]=name
        self.FillShowList(name)

    def OnDelete(self) -> None:
        index=self.CurrentIndex()
        if index < 0:
            return
        if not messagebox.askyesno("Edit Photo Shows", f'Delete the photo show "{self.shows[index]["name"]}"?', parent=self):
            return
        del self.shows[index]
        self.loadedIndex=-1
        self.FillShowList()

    # What the shows amount to, for telling whether anything has actually been changed
    # (the same folders in a different order, or a redundant one, is no change)
    @staticmethod
    def Digest(shows: list[dict]) -> list:
        digest=[]
        for show in shows:
            chosen, excluded=TidyRules(show["folders"], show.get("except", []))
            digest.append((show["name"], tuple(chosen), tuple(excluded)))
        return digest

    # Cancel throws away everything done since the dialog was opened, so ask first
    def OnCancel(self) -> None:
        self.StoreShow()
        if self.Digest(self.shows) != self.originalDigest and not messagebox.askyesno(
                "Edit Photo Shows",
                "The photo shows have been changed.\n\nClose the editor and throw those changes away?",
                icon="warning", parent=self):
            return
        self.destroy()

    def OnSave(self) -> None:
        self.StoreShow()
        empty=[show["name"] for show in self.shows if len(show["folders"]) == 0]
        if len(empty) > 0 and not messagebox.askyesno(
                "Edit Photo Shows",
                "These photo shows have no folders in them and will show nothing:\n\n  "+"\n  ".join(empty)+"\n\nSave anyway?",
                parent=self):
            return
        self.app.ApplyEditedShows(self.shows)
        self.destroy()


def main() -> None:
    SlideShow().mainloop()


if __name__ == "__main__":
    main()
