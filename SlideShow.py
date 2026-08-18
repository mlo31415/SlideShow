"""
SlideShow.py

Displays a full-screen slideshow of the images found in a directory tree.

The directory to be displayed and the other operating parameters are read from
"SlideShow settings.txt" (name=value lines) in the program's directory:

    Directories:          The next line is the path of the directory holding the photo
                          shows: each of its immediate subdirectories (the TLDs) is an
                          available show, listed with a check box in the Select Photo
                          Show menu.  Every checked show's whole tree is in the
                          slideshow.  The checked set is remembered between runs (in
                          "SlideShow state.json"); TLDs that have vanished are dropped,
                          and if none survive, all are checked.
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
    Face Detection        How sure the detector must be before it calls something a
      Threshold           face, 0 to 1: lower finds more faces, including doubtful
                          ones; higher finds only clear ones  (default: 0.6)

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

Buttons: Prev, Pause/Continue (one button, toggling with the state), Next,
Add Info.  A top bar holds a ✕ close box in the upper-right corner (and has
room for future menu items).
Keyboard shortcuts: left/right arrows for Prev/Next, Esc to exit.
Add Info splits the window in two the narrow way (left/right halves on a
landscape screen, top/bottom on a portrait one), shoves the photo into one
half, and shows the Identify Photo panel in the other: the faces found in the
photo listed left-to-right, each with a box to enter the person's name, plus
a box for other comments and corrections and one for the identifier's email
address (remembered between saves while the user stays active, then forgotten
after Email Timeout seconds of no input).  Prev and Next stay live while the
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
json.JSONDecoder().raw_decode in a loop.

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
import random
from typing import Any
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import messagebox
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageTk

SETTINGS_FILE="SlideShow settings.txt"
STATE_FILE="SlideShow state.json"
FACE_MODEL="face_detection_yunet_2023mar.onnx"
IMAGE_EXTENSIONS={".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
DEFAULT_TITLE_FONT="Segoe UI"
DEFAULT_TITLE_FONT_SIZE=32
CAPTION_FONT_SIZE=22            # Normal caption size; long captions shrink from here...
MIN_CAPTION_FONT_SIZE=12        # ...down to this, to fit the two caption lines
CAPTION_LINES=2
CREDIT_FONT_SMALLER=6           # The credit line under the caption is this much smaller than it
MIN_CREDIT_FONT_SIZE=9
SUBDIR_FONT_SIZE=28             # Normal album-line size; on a landscape single line it shrinks...
MIN_SUBDIR_FONT_SIZE=14         # ...down to this to fit beside the title, then wraps below it
FACE_DETECT_MAXDIM=1600         # Photos are reduced to this before face detection (bigger finds smaller faces)
DEFAULT_FACE_THRESHOLD=0.6      # Detector confidence needed to call something a face
KNOWN_PARAMETERS={"directories", "order", "display time", "title", "title font", "title font size", "display subdirectory", "pause timeout", "mode", "email timeout", "face detection threshold"}

# The color schemes for the Mode parameter (default: dark)
THEMES={
    "dark":  {"bg": "black", "fg": "white", "titleFg": "lightyellow", "subdirFg": "#bbbbbb",
              "barBg": "#202020", "barFg": "white", "barActiveBg": "#3a3a3a", "panelBg": "#101010",
              "separatorBg": "#606060"},
    "light": {"bg": "white", "fg": "black", "titleFg": "darkgoldenrod", "subdirFg": "#555555",
              "barBg": "#e4e4e4", "barFg": "black", "barActiveBg": "#d0d0d0", "panelBg": "#efefef",
              "separatorBg": "#b0b0b0"},
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
        settingsPath=os.path.join(os.path.dirname(os.path.abspath(__file__)), SETTINGS_FILE)
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
        self.editorEmail=""             # Remembered between saves while the user stays active
        self.faceThreshold=self.ResolveFaceThreshold(Get("Face Detection Threshold", ""))

        if len(self.rootDirectories) == 0:
            self.Fatal(f"No directory path is defined in '{settingsPath}'.\n\nThe settings file needs a 'Directories:' line followed by the path of the directory holding the photo shows.")
        self.rootDirectory=self.rootDirectories[0]      # Extra paths are reported by ValidateSettings

        # The settings file is monitored while running: changes to it are applied on the
        # fly, each parameter taking effect only if its value actually changed.
        self.settingsPath=settingsPath
        self.lastSettingsMtime=os.stat(settingsPath).st_mtime
        self.pendingSettings=None       # Newly-read settings awaiting a second identical read (debounce)

        # -------------------- Find the images --------------------
        # The immediate subdirectories of the root directory (the TLDs) are the available
        # photo shows, each toggled by a check box in the Select Photo Show menu; every
        # checked show's whole tree is in the slideshow.  The set checked last time is
        # restored at startup (dropping TLDs that no longer exist); when none survive,
        # all are checked.
        self.tlds=self.FindTLDs(self.rootDirectory)
        if len(self.tlds) == 0:
            self.Fatal(f"No directories found inside '{self.rootDirectory}' -- there are no photo shows to display.")
        self.statePath=os.path.join(os.path.dirname(os.path.abspath(__file__)), STATE_FILE)
        self.checkedTlds={os.path.normcase(d) for d in self.tlds}
        try:
            with open(self.statePath, "r", encoding="utf-8") as file:
                saved={os.path.normcase(d) for d in json.load(file).get("checked directories", [])}
            if len(saved & self.checkedTlds) > 0:
                self.checkedTlds&=saved
        except (OSError, json.JSONDecodeError):
            pass
        self.images=self.ScanImages(self.CheckedTldList())
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
            self.iconbitmap(os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "SlideShow.ico"))
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
        buttonFrame.pack(side=tk.BOTTOM, pady=(5, 15))

        # Every button carries an image (a transparent spacer when it has no icon) so
        # that they all size and align identically
        self.buttonIcons=self.MakeButtonIcons()

        def MakeButton(text: str, command, icon: str="blank") -> tk.Button:
            b=tk.Button(buttonFrame, text=" "+text if icon != "blank" else text, image=self.buttonIcons[icon],
                        compound=tk.LEFT, command=command, font=("Segoe UI", 12), width=110)
            b.pack(side=tk.LEFT, padx=8)
            return b

        self.prevButton=MakeButton("Prev", self.OnPrev, "prev")
        self.pauseButton=MakeButton("Pause", self.OnPauseContinue, "pause")     # Toggles between Pause and Continue
        self.nextButton=MakeButton("Next", self.OnNext, "next")
        self.addInfoButton=MakeButton("Add Info", self.OnAddInfo, "pencil")
        # Bigger and bold, to stand out from its neighbors
        self.addInfoButton.configure(width=143, height=38, font=("Segoe UI", 12, "bold"))
        ToolTip(self.addInfoButton, "If you have anything to tell us about this photo, click here.")

        # The image and its caption are stacked in a frame which is centered in the
        # remaining space, so the caption sits directly below the image and moves with it.
        self.centerFrame=tk.Frame(self.showFrame, bg="black")
        self.centerFrame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        innerFrame=self.innerFrame=tk.Frame(self.centerFrame, bg="black")
        innerFrame.pack(expand=True)

        self.imageLabel=tk.Label(innerFrame, bg="black")
        self.imageLabel.pack(side=tk.TOP)

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
        self.bind("<Escape>", lambda e: self.destroy())
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

        for pname, label in (("display time", "Display Time"), ("pause timeout", "Pause Timeout"), ("title font size", "Title Font Size"), ("email timeout", "Email Timeout")):
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
            try:
                import ctypes
                left, top, right, bottom=MonitorRect(event.x_root, event.y_root, self)
                hwnd=ctypes.windll.user32.GetAncestor(self.winfo_id(), 2)       # GA_ROOT
                ctypes.windll.user32.SetWindowPos(hwnd, 0, left, top, right-left, bottom-top, 0x0014)   # SWP_NOZORDER | SWP_NOACTIVATE
                self.descLabel.config(wraplength=(right-left)-100)              # The new monitor may be a different width
            except Exception:
                pass                    # If the Windows API is unavailable we are at least fullscreen somewhere
            self.update_idletasks()
            self.ShowImage()            # Rescale to the new monitor (also refits the header)
        self.dragStart=None
        self.dragging=False


    # The immediate subdirectories of the root directory: the available photo shows
    @staticmethod
    def FindTLDs(rootDirectory: str) -> list[str]:
        try:
            return [os.path.join(rootDirectory, d) for d in sorted(os.listdir(rootDirectory), key=str.casefold)
                    if os.path.isdir(os.path.join(rootDirectory, d))]
        except OSError:
            return []

    # The checked TLDs, in TLD (sorted) order
    def CheckedTldList(self) -> list[str]:
        return [d for d in self.tlds if os.path.normcase(d) in self.checkedTlds]

    # Rebuild the Select Photo Show menu: one check box per TLD, showing just the
    # directory names, with the checked ones making up the slideshow
    def RebuildShowMenu(self) -> None:
        self.showMenu.delete(0, tk.END)
        self.showVars=[]
        for i, d in enumerate(self.tlds):
            var=tk.BooleanVar(value=os.path.normcase(d) in self.checkedTlds)
            self.showVars.append(var)
            self.showMenu.add_checkbutton(label=os.path.basename(d), variable=var,
                                          command=lambda i=i: self.OnToggleShow(i))

    # Append one Identify Photo save record to this session's output log -- a
    # pretty-printed JSON object followed by a blank line (concatenated JSON, loadable
    # with json.JSONDecoder().raw_decode in a loop) -- and rename the file so its name
    # carries the date and time of this latest save.
    def LogSave(self, record: dict) -> None:
        try:
            if self.outputPath is None:     # This session's first save creates the file
                self.outputPath=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             f"SlideShow Output {time.strftime('%Y-%m-%d %H.%M.%S')}.json")
            text=json.dumps(record, indent=2, ensure_ascii=False)
            # Compact the four-number face boxes back onto one line for readability
            text=re.sub(r"\[\s+(-?\d+),\s+(-?\d+),\s+(-?\d+),\s+(-?\d+)\s+\]", r"[\1, \2, \3, \4]", text)
            with open(self.outputPath, "a", encoding="utf-8") as file:
                file.write(text+"\n\n")
            newPath=os.path.join(os.path.dirname(self.outputPath),
                                 f"SlideShow Output {time.strftime('%Y-%m-%d %H.%M.%S')}.json")
            if newPath != self.outputPath:
                os.replace(self.outputPath, newPath)
                self.outputPath=newPath
        except OSError as e:
            messagebox.showwarning("SlideShow", f"Could not write the output log:\n{e}", parent=self)

    # Remember the checked shows between invocations
    def SaveState(self) -> None:
        try:
            with open(self.statePath, "w", encoding="utf-8") as file:
                json.dump({"checked directories": self.CheckedTldList()}, file)
        except OSError:
            pass

    # A show was checked or unchecked in the menu: recompute the slideshow from the
    # union of the checked shows' trees
    def OnToggleShow(self, index: int) -> None:
        newChecked=[d for i, d in enumerate(self.tlds) if self.showVars[i].get()]
        if len(newChecked) == 0:
            self.showVars[index].set(True)      # Undo the toggle
            self.ShowMessage("Select Photo Show",
                             f'The slideshow needs at least one photo show, so "{os.path.basename(self.tlds[index])}" stays checked.\n\n'
                             "To switch to a different show, check it first and then uncheck the others.")
            return
        images=self.ScanImages(newChecked)
        if len(images) == 0:
            self.showVars[index].set(not self.showVars[index].get())
            self.ShowMessage("Select Photo Show",
                             "That change would have left no photos to display, so it has been undone.", warning=True)
            return
        self.checkedTlds={os.path.normcase(d) for d in newChecked}
        self.images=images
        self.history=[]
        self.histpos=-1
        self.NextImage()
        self.ScheduleAdvance()
        self.SaveState()

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
    def ScanImages(rootDirectories: list[str]) -> list[str]:
        images=[]
        for rootDirectory in rootDirectories:
            for dirpath, dirnames, filenames in os.walk(rootDirectory):
                dirnames.sort(key=str.casefold)
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
                photoDate=(xmlRoot.findtext("date_creation") or "").strip().split(" ")[0]
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
            width=self.centerFrame.winfo_width()-20
            height=self.centerFrame.winfo_height()-self.descLabel.winfo_reqheight()-10
            if len(credit) > 0:
                height-=self.creditLabel.winfo_reqheight()
            if width < 50 or height < 50:       # Not laid out yet -- fall back to a guess
                width=self.winfo_screenwidth()-40
                height=self.winfo_screenheight()-300
            img.thumbnail((width, height), Image.LANCZOS)
            self.photo=ImageTk.PhotoImage(img)      # Keep a reference or tk will garbage-collect it
            self.imageLabel.config(image=self.photo, text="")
        except Exception as e:
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

        self.faceThreshold=self.ResolveFaceThreshold(Get("Face Detection Threshold", ""))

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

        # A new root directory: rediscover its TLDs and restart with all of them
        # checked.  (The path is a valid directory by construction of the parse.)
        newDirectories=settings.get("directories", [])
        if len(newDirectories) == 0:
            problems.append("No directory path is defined  (keeping the current one)")
        elif os.path.normcase(newDirectories[0]) != os.path.normcase(self.rootDirectory):
            tlds=self.FindTLDs(newDirectories[0])
            if len(tlds) == 0:
                problems.append(f"No directories found inside '{newDirectories[0]}'  (keeping the current one)")
                return problems
            images=self.ScanImages(tlds)
            if len(images) == 0:
                problems.append(f"No image files found in the photo shows under '{newDirectories[0]}'  (keeping the current one)")
                return problems
            self.rootDirectory=newDirectories[0]
            self.tlds=tlds
            self.checkedTlds={os.path.normcase(d) for d in tlds}
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
            self.pauseButton.config(text=" Continue", image=self.buttonIcons["play"])
        else:
            self.pauseButton.config(text=" Pause", image=self.buttonIcons["pause"])

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

    # Prev and Next work while the Identify Photo panel is up: anything typed there and
    # not yet saved is discarded, the photo moves, and the panel is rebuilt for it.
    def OnNext(self) -> None:
        if self.dialogOpen and self.identifyPanel is None:
            return                  # Some other dialog is up
        if self.identifyPanel is not None:
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
            self.CloseIdentifyPanel(restore=False)
            self.PrevImage()
            self.OnAddInfo(reopening=True)
            return
        self.PrevImage()
        self.ScheduleAdvance()

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
        modelPath=os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), FACE_MODEL)
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

    # A round thumbnail of the face at box, for the Identify Photo table
    @staticmethod
    def MakeFaceThumbnail(img: Image.Image, box: tuple[int, int, int, int], bg: str, size: int=72) -> ImageTk.PhotoImage:
        x, y, w, h=box
        cx, cy=x+w/2, y+h/2
        r=0.65*(w*w+h*h)**0.5
        square=img.crop((max(int(cx-r), 0), max(int(cy-r), 0), min(int(cx+r), img.width), min(int(cy+r), img.height))).resize((size, size), Image.LANCZOS)
        mask=Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size-1, size-1), fill=255)
        thumb=Image.new("RGB", (size, size), bg)
        thumb.paste(square, (0, 0), mask)
        return ImageTk.PhotoImage(thumb)

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
        try:
            img=Image.open(pathname).convert("RGB")
        except Exception:
            img=None
        boxes=self.DetectFaces(img) if img is not None else None

        pbg=self.theme["panelBg"]
        pfg=self.theme["fg"]
        pdim=self.theme["subdirFg"]

        # Split using the window's own dimensions (not the primary screen's -- the
        # window may have been dragged to a different-sized or rotated monitor)
        panel=tk.Frame(self, bg=pbg)
        self.identifyPanel=panel
        windowWidth=self.winfo_width()
        windowHeight=self.winfo_height()
        landscape=windowWidth > windowHeight
        # A thin gray band separates the two halves
        separator=tk.Frame(self, bg=self.theme["separatorBg"])
        if landscape:
            panel.configure(width=windowWidth//2)
            panel.pack_propagate(False)         # Hold the half-window size regardless of content
            panel.pack(side=tk.RIGHT, fill=tk.Y, before=self.showFrame)
            separator.configure(width=2)
            separator.pack(side=tk.RIGHT, fill=tk.Y, before=self.showFrame)
        else:
            panel.configure(height=windowHeight//2)
            panel.pack_propagate(False)
            panel.pack(side=tk.BOTTOM, fill=tk.X, before=self.showFrame)
            separator.configure(height=2)
            separator.pack(side=tk.BOTTOM, fill=tk.X, before=self.showFrame)
        self.update_idletasks()
        panelHeight=panel.winfo_height()        # The panel's real height (it starts below the title area)
        self.ShowImage()                # Rescale the photo into its reduced half

        tk.Label(panel, text="Identify Photo", font=("Segoe UI", 18, "bold"), fg=pfg, bg=pbg).pack(pady=(20, 5))

        # The face table lives in a canvas so that it can scroll when there are more
        # faces than fit in the panel
        tableHolder=tk.Frame(panel, bg=pbg)
        tableHolder.pack(pady=(5, 0))
        tableCanvas=tk.Canvas(tableHolder, bg=pbg, highlightthickness=0)
        tableScrollbar=tk.Scrollbar(tableHolder, orient=tk.VERTICAL, command=tableCanvas.yview)
        tableCanvas.configure(yscrollcommand=tableScrollbar.set)
        tableCanvas.pack(side=tk.LEFT)
        table=tk.Frame(tableCanvas, bg=pbg)
        tableCanvas.create_window((0, 0), window=table, anchor="nw")
        tk.Label(table, text="", bg=pbg).grid(row=0, column=0)
        tk.Label(table, text="Name", font=("Segoe UI", 12), fg=pfg, bg=pbg).grid(row=0, column=2, sticky="w")
        panel.thumbnails=[]             # Keep references so tk doesn't garbage-collect the images
        nameEntries=[]
        inputVars=[]                    # Watched so the Cancel button can tell whether anything was entered
        if boxes is None:
            tk.Label(table, text="(Face detection is unavailable)", font=("Segoe UI", 11), fg=pdim, bg=pbg).grid(row=1, column=0, columnspan=3)
        elif len(boxes) == 0:
            tk.Label(table, text="(No faces detected)", font=("Segoe UI", 11), fg=pdim, bg=pbg).grid(row=1, column=0, columnspan=3)
        else:
            # Each row is numbered so a comment can refer to a face by its number
            for i, box in enumerate(boxes):
                thumb=self.MakeFaceThumbnail(img, box, pbg)
                panel.thumbnails.append(thumb)
                numberLabel=tk.Label(table, text=f"#{i+1}", font=("Segoe UI", 12), fg=pfg, bg=pbg)
                numberLabel.grid(row=i+1, column=0, padx=(0, 8), sticky="e")
                faceLabel=tk.Label(table, image=thumb, bg=pbg)
                faceLabel.grid(row=i+1, column=1, padx=(0, 12), pady=4)
                var=tk.StringVar()
                inputVars.append(var)
                entry=tk.Entry(table, font=("Segoe UI", 12), width=32, textvariable=var)
                entry.grid(row=i+1, column=2, sticky="w")
                nameEntries.append(entry)
                for w in (numberLabel, faceLabel, entry):
                    ToolTip(w, "If you can identify this person, give us a name and, if appropriate, a reason why.  (The latter is not required)  "
                               "You do not need to fill in any rows except ones you have data for.")

        # Size the canvas to the table, capped to leave room for the comments box and
        # buttons below; when capped, add the scrollbar and mouse-wheel scrolling
        self.update_idletasks()
        tableWidth=table.winfo_reqwidth()
        tableHeight=table.winfo_reqheight()
        maxTableHeight=max(150, panelHeight-430)
        tableCanvas.configure(width=tableWidth, height=min(tableHeight, maxTableHeight),
                              scrollregion=(0, 0, tableWidth, tableHeight))
        if tableHeight > maxTableHeight:
            tableScrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            tableCanvas.bind_all("<MouseWheel>", lambda e: tableCanvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))

        tk.Label(panel, text="", bg=pbg).pack()
        commentsLabel=tk.Label(panel, text="Other Comments and Corrections", font=("Segoe UI", 12), fg=pfg, bg=pbg)
        commentsLabel.pack()
        commentsBox=tk.Text(panel, font=("Segoe UI", 11), width=48, height=4)
        commentsBox.pack(pady=(4, 0))
        for w in (commentsLabel, commentsBox):
            ToolTip(w, "Tell us more: When/where was the photo taken?  Who took it?  Other interesting details.")

        dateRow=tk.Frame(panel, bg=pbg)
        dateRow.pack(pady=(8, 0))
        dateLabel=tk.Label(dateRow, text="Photo Date:", font=("Segoe UI", 12), fg=pfg, bg=pbg)
        dateLabel.pack(side=tk.LEFT, padx=(0, 8))
        dateVar=tk.StringVar()
        inputVars.append(dateVar)
        dateEntry=tk.Entry(dateRow, font=("Segoe UI", 12), width=30, textvariable=dateVar)
        dateEntry.pack(side=tk.LEFT)
        for w in (dateLabel, dateEntry):
            ToolTip(w, "If you know when this photo was taken, tell us here.  A year alone is fine.")

        # The email address is remembered between saves as long as the user stays
        # active; OnTick forgets it after Email Timeout seconds without input
        emailRow=tk.Frame(panel, bg=pbg)
        emailRow.pack(pady=(8, 0))
        emailLabel=tk.Label(emailRow, text="Your name/email address:", font=("Segoe UI", 12), fg=pfg, bg=pbg)
        emailLabel.pack(side=tk.LEFT, padx=(0, 8))
        emailVar=tk.StringVar(value=self.editorEmail)       # Prefilled, so it only counts as input once changed
        prefilledEmail=self.editorEmail
        emailEntry=tk.Entry(emailRow, font=("Segoe UI", 12), width=30, textvariable=emailVar)
        emailEntry.pack(side=tk.LEFT)
        for w in (emailLabel, emailEntry):
            ToolTip(w, "Please let us know who is submitting this information, so we can give you credit.")

        def Close(restore: bool=True) -> None:
            self.unbind_all("<MouseWheel>")
            panel.destroy()
            separator.destroy()
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

        def OnSave() -> None:
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
                "faces":      [{"number": i+1, "name": e.get().strip(), "box": list(box)} for i, (e, box) in enumerate(zip(nameEntries, boxes or []))],
                "comment":    commentsBox.get("1.0", tk.END).strip(),
                "photo date": dateEntry.get().strip(),
            })
            Close()

        buttons=tk.Frame(panel, bg=pbg)
        buttons.pack(pady=15)
        tk.Button(buttons, text="Save", font=("Segoe UI", 12), width=9, command=OnSave).pack(side=tk.LEFT, padx=8)
        cancelButton=tk.Button(buttons, text="Close", font=("Segoe UI", 12), width=9, command=Close)
        cancelButton.pack(side=tk.LEFT, padx=8)

        # That button discards whatever has been entered, so it says "Cancel" once
        # there is something to discard and "Close" while every box is still empty
        def UpdateCancelLabel(*args) -> None:
            entered=(any(len(v.get().strip()) > 0 for v in inputVars)
                     or len(commentsBox.get("1.0", tk.END).strip()) > 0
                     or emailVar.get().strip() != prefilledEmail)
            cancelButton.config(text="Cancel" if entered else "Close")

        for var in inputVars+[emailVar]:
            var.trace_add("write", UpdateCancelLabel)
        def OnCommentsModified(event=None) -> None:
            if commentsBox.edit_modified():
                commentsBox.edit_modified(False)        # Rearm, and do not recurse on the reset
                UpdateCancelLabel()
        commentsBox.bind("<<Modified>>", OnCommentsModified)
        UpdateCancelLabel()


def main() -> None:
    SlideShow().mainloop()


if __name__ == "__main__":
    main()
