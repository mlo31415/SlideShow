"""
SlideShow.py

Displays a full-screen slideshow of the images found in a directory tree.

The directory to be displayed and the other operating parameters are read from
"SlideShow settings.txt" (name=value lines) in the program's directory:

    Directories:          Starts a list of directory paths, one per line, each the root
                          of a tree of images to display.  The list ends at the first
                          line which is not a valid directory path.  At least one
                          directory is required.
    Order                 "Sequential" or "Random"  (default: Sequential)
    Display Time          Seconds each image is displayed  (default: 10)
    Title                 Title shown at the top  (default: "photos.fanac.org")
    Title Font            Font family for the title; must be installed  (default: Segoe UI)
    Title Font Size       Point size for the title  (default: 32)
    Display Subdirectory  If True, show the subdirectory chain under the title
                          for images not in the top-level directory  (default: True)
    Pause Timeout         Seconds of no user input after which a paused show
                          resumes on its own  (default: 240)

A parameter value whose first non-blank character is '#' is treated as empty,
and the parameter's default is used.

Each photo comes with two same-named companion files: a .txt holding the
caption and an .xml holding photo information from Piwigo.  The caption shown
under the image is the .txt content; if there is none, the image's filename
without the extension is used.  A caption too long for its two lines is shown
in a progressively smaller font until it fits.

Buttons: Prev, Pause/Continue (one button, toggling with the state), Next,
Add Info, Exit.
Keyboard shortcuts: left/right arrows for Prev/Next, Esc for Exit.
Add Info opens the Identify Photo dialog: the faces found in the photo are
listed left-to-right, each with a box to enter the person's name, plus a box
for general comments.  Face detection uses OpenCV's YuNet model (the .onnx
file alongside this script).

The settings file is monitored while the show is running: saving a change to it
applies just the changed parameters on the fly (a changed Directory restarts the
show from the new tree; anything else leaves the current image undisturbed).
Unrecognized parameter names and unusable values are reported in a warning
dialog and ignored; missing parameters revert to their defaults.

Requires: pip install Pillow opencv-python
"""

import os
import sys
import time
import random
from typing import Any
import tkinter as tk
from tkinter import messagebox
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageTk

SETTINGS_FILE="SlideShow settings.txt"
FACE_MODEL="face_detection_yunet_2023mar.onnx"
IMAGE_EXTENSIONS={".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
DEFAULT_TITLE_FONT="Segoe UI"
DEFAULT_TITLE_FONT_SIZE=32
CAPTION_FONT_SIZE=22            # Normal caption size; long captions shrink from here...
MIN_CAPTION_FONT_SIZE=12        # ...down to this, to fit the two caption lines
CAPTION_LINES=2
KNOWN_PARAMETERS={"directories", "order", "display time", "title", "title font", "title font size", "display subdirectory", "pause timeout"}


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
        self.displaySubdirectory=IsTrue("Display Subdirectory", "True")
        try:
            self.pauseTimeout=float(Get("Pause Timeout", "240"))
        except ValueError:
            self.pauseTimeout=240.0
        if self.pauseTimeout <= 0:
            self.pauseTimeout=240.0

        if len(self.rootDirectories) == 0:
            self.Fatal(f"No directory paths are defined in '{settingsPath}'.\n\nThe settings file needs a 'Directories:' line followed by at least one existing directory path.")

        # The settings file is monitored while running: changes to it are applied on the
        # fly, each parameter taking effect only if its value actually changed.
        self.settingsPath=settingsPath
        self.lastSettingsMtime=os.stat(settingsPath).st_mtime
        self.pendingSettings=None       # Newly-read settings awaiting a second identical read (debounce)

        # -------------------- Find the images --------------------
        self.images=self.ScanImages(self.rootDirectories)
        if len(self.images) == 0:
            self.Fatal(f"No image files found under {', '.join(self.rootDirectories)}.")

        # History of images shown (indexes into self.images), so Prev can back up even in random order.
        self.history: list[int]=[]
        self.histpos=-1

        self.paused=False
        self.dialogOpen=False           # True while the Identify Photo dialog is up
        self.photoInfo={}               # Names/comments entered via Add Info, keyed by image pathname (persistence TBD)
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

        self.titleLabel=tk.Label(self, text=self.titleText, font=(self.titleFontName, self.titleFontSize, "bold"), fg="lightyellow", bg="black")
        self.titleLabel.pack(side=tk.TOP, pady=(10, 0))

        self.subdirLabel=tk.Label(self, text="", font=("Segoe UI", 28), fg="#bbbbbb", bg="black")
        self.subdirLabel.pack(side=tk.TOP)

        # Bottom-up: buttons at the very bottom, description just above them, image fills the rest.
        buttonFrame=tk.Frame(self, bg="black")
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
        self.addInfoButton=MakeButton("Add Info", self.OnAddInfo)
        self.exitButton=MakeButton("Exit", self.destroy)

        # The image and its caption are stacked in a frame which is centered in the
        # remaining space, so the caption sits directly below the image and moves with it.
        self.centerFrame=tk.Frame(self, bg="black")
        self.centerFrame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        innerFrame=tk.Frame(self.centerFrame, bg="black")
        innerFrame.pack(expand=True)

        self.imageLabel=tk.Label(innerFrame, bg="black")
        self.imageLabel.pack(side=tk.TOP)

        self.captionFont=tkfont.Font(family="Segoe UI", size=CAPTION_FONT_SIZE)
        self.descLabel=tk.Label(innerFrame, text="", font=self.captionFont, fg="white", bg="black",
                                justify=tk.CENTER, height=CAPTION_LINES, wraplength=self.winfo_screenwidth()-100)
        self.descLabel.pack(side=tk.TOP)

        self.UpdateButtonStates()

        # Any user input resets the pause-timeout clock
        self.bind_all("<Key>", self.OnUserInput)
        self.bind_all("<Button>", self.OnUserInput)
        self.bind("<Left>", lambda e: self.OnPrev())
        self.bind("<Right>", lambda e: self.OnNext())
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        # Let the window get its real size before displaying the first image
        self.after(100, self.Start)


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

        for pname, label in (("display time", "Display Time"), ("pause timeout", "Pause Timeout"), ("title font size", "Title Font Size")):
            if pname in settings:
                try:
                    if float(settings[pname]) <= 0:
                        problems.append(f"{label}='{settings[pname]}' should be greater than zero  (ignoring it)")
                except ValueError:
                    problems.append(f"{label}='{settings[pname]}' should be a number  (ignoring it)")

        if "display subdirectory" in settings and settings["display subdirectory"].casefold() not in ("true", "yes", "false", "no"):
            problems.append(f"Display Subdirectory='{settings['display subdirectory']}' should be True or False  (ignoring it)")

        fontName=settings.get("title font", "").strip()
        if len(fontName) > 0 and self.FindFontFamily(fontName) is None:
            problems.append(f"Title Font='{fontName}' is not an installed font  (using {DEFAULT_TITLE_FONT})")

        return problems


    # Report settings-file problems in a warning dialog.  Like the Add Info dialog, the
    # show is held while it is up and returns to its previous pause state afterwards.
    def ShowSettingsProblems(self, problems: list[str]) -> None:
        wasPaused=self.paused
        self.paused=True
        self.dialogOpen=True
        self.CancelAdvance()
        self.UpdateButtonStates()

        messagebox.showwarning("SlideShow settings", "Problems in the settings file:\n\n"+"\n".join(problems), parent=self)

        self.dialogOpen=False
        self.lastInputTime=time.time()
        if wasPaused:
            self.UpdateButtonStates()
        else:
            self.Resume()


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

        # The optional subdirectory line: the path below the listed directory the image
        # came from, so photos in that directory itself show nothing, and deeper ones
        # show e.g. "A" or "A/B"
        subdir="."
        for root in self.rootDirectories:
            rel=os.path.relpath(os.path.dirname(pathname), root)
            if not rel.startswith(".."):
                subdir=rel
                break
        if not self.displaySubdirectory or subdir == ".":
            self.subdirLabel.config(text="")
        else:
            # When a directory's name is a prefix of the directory below it (e.g.,
            # "Tropicon/Tropicon 27"), displaying it adds nothing, so suppress it
            parts=subdir.split(os.sep)
            while len(parts) > 1 and parts[1].casefold().startswith(parts[0].casefold()):
                parts.pop(0)
            self.subdirLabel.config(text="/".join(parts))

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
        # A caption too long for its two lines at normal size gets a progressively
        # smaller font until it fits (or the minimum size is reached)
        wraplength=self.descLabel.cget("wraplength")
        size=CAPTION_FONT_SIZE
        self.captionFont.configure(size=size)
        while size > MIN_CAPTION_FONT_SIZE and self.CountWrappedLines(desc, self.captionFont, wraplength) > CAPTION_LINES:
            size-=2
            self.captionFont.configure(size=size)
        self.descLabel.config(text=desc)

        # The image itself, scaled to fit the space left over after the caption below it
        try:
            img=Image.open(pathname)
            width=self.centerFrame.winfo_width()-20
            height=self.centerFrame.winfo_height()-self.descLabel.winfo_reqheight()-10
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

        order=Get("Order", "Sequential").casefold()
        if order.startswith("random"):
            self.randomOrder=True
        elif order.startswith("seq"):
            self.randomOrder=False
        # else: unrecognized value -- keep the current setting

        # A new directory list: rescan, and only if the new trees have images, switch to
        # them.  (Paths in the list are valid directories by construction of the parse.)
        newDirectories=settings.get("directories", [])
        if len(newDirectories) == 0:
            problems.append("No directory paths are defined  (keeping the current list)")
        elif [os.path.normcase(d) for d in newDirectories] != [os.path.normcase(d) for d in self.rootDirectories]:
            images=self.ScanImages(newDirectories)
            if len(images) == 0:
                problems.append(f"No image files found under {', '.join(newDirectories)}  (keeping the current list)")
            else:
                self.rootDirectories=newDirectories
                self.images=images
                self.history=[]
                self.histpos=-1
                self.NextImage()
                self.ScheduleAdvance()

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
        return icons

    # The one Pause/Continue button shows the action it will perform next
    def UpdateButtonStates(self) -> None:
        if self.paused:
            self.pauseButton.config(text=" Continue", image=self.buttonIcons["play"])
        else:
            self.pauseButton.config(text=" Pause", image=self.buttonIcons["pause"])

    def OnPauseContinue(self) -> None:
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

    def OnNext(self) -> None:
        self.NextImage()
        self.ScheduleAdvance()      # Restart the display-time clock

    def OnPrev(self) -> None:
        self.PrevImage()
        self.ScheduleAdvance()

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
        if max(img.size) > 1024:
            scale=1024/max(img.size)
            det=img.resize((round(img.width*scale), round(img.height*scale)), Image.LANCZOS)
        arr=cv2.cvtColor(np.array(det), cv2.COLOR_RGB2BGR)
        detector=cv2.FaceDetectorYN.create(modelPath, "", (det.width, det.height), 0.6)
        _, faces=detector.detect(arr)
        if faces is None:
            return []
        boxes=[(max(int(f[0]/scale), 0), max(int(f[1]/scale), 0), int(f[2]/scale), int(f[3]/scale)) for f in faces]
        boxes.sort(key=lambda b: b[0])
        return boxes

    # A round thumbnail of the face at box, for the Identify Photo table
    @staticmethod
    def MakeFaceThumbnail(img: Image.Image, box: tuple[int, int, int, int], size: int=72) -> ImageTk.PhotoImage:
        x, y, w, h=box
        cx, cy=x+w/2, y+h/2
        r=0.65*(w*w+h*h)**0.5
        square=img.crop((max(int(cx-r), 0), max(int(cy-r), 0), min(int(cx+r), img.width), min(int(cy+r), img.height))).resize((size, size), Image.LANCZOS)
        mask=Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size-1, size-1), fill=255)
        thumb=Image.new("RGB", (size, size), "black")
        thumb.paste(square, (0, 0), mask)
        return ImageTk.PhotoImage(thumb)

    # Open the Identify Photo dialog: a table with a row for each face found in the
    # current photo (left-to-right), each with a box for the person's name, then a box
    # for general comments, and Save/Cancel.  While the dialog is up the show is paused;
    # when it closes, the show returns to whatever pause state it was in before.
    def OnAddInfo(self) -> None:
        wasPaused=self.paused
        self.paused=True
        self.dialogOpen=True
        self.CancelAdvance()
        self.UpdateButtonStates()

        pathname=self.images[self.history[self.histpos]]
        try:
            img=Image.open(pathname).convert("RGB")
        except Exception:
            img=None
        boxes=self.DetectFaces(img) if img is not None else None

        dlg=tk.Toplevel(self)
        dlg.title("Identify Photo")
        dlg.configure(bg="black")

        # The face table lives in a canvas so that it can scroll when there are more
        # faces than fit on the screen
        tableHolder=tk.Frame(dlg, bg="black")
        tableHolder.pack(padx=30, pady=(20, 0))
        tableCanvas=tk.Canvas(tableHolder, bg="black", highlightthickness=0)
        tableScrollbar=tk.Scrollbar(tableHolder, orient=tk.VERTICAL, command=tableCanvas.yview)
        tableCanvas.configure(yscrollcommand=tableScrollbar.set)
        tableCanvas.pack(side=tk.LEFT)
        table=tk.Frame(tableCanvas, bg="black")
        tableCanvas.create_window((0, 0), window=table, anchor="nw")
        tk.Label(table, text="", bg="black").grid(row=0, column=0)
        tk.Label(table, text="Name", font=("Segoe UI", 12), fg="white", bg="black").grid(row=0, column=1, sticky="w")
        dlg.thumbnails=[]               # Keep references so tk doesn't garbage-collect the images
        nameEntries=[]
        if boxes is None:
            tk.Label(table, text="(Face detection is unavailable)", font=("Segoe UI", 11), fg="#bbbbbb", bg="black").grid(row=1, column=0, columnspan=2)
        elif len(boxes) == 0:
            tk.Label(table, text="(No faces detected)", font=("Segoe UI", 11), fg="#bbbbbb", bg="black").grid(row=1, column=0, columnspan=2)
        else:
            for i, box in enumerate(boxes):
                thumb=self.MakeFaceThumbnail(img, box)
                dlg.thumbnails.append(thumb)
                tk.Label(table, image=thumb, bg="black").grid(row=i+1, column=0, padx=(0, 12), pady=4)
                entry=tk.Entry(table, font=("Segoe UI", 12), width=32)
                entry.grid(row=i+1, column=1, sticky="w")
                nameEntries.append(entry)

        # Size the canvas to the table, capped at about half the screen; when capped,
        # add the scrollbar and mouse-wheel scrolling
        dlg.update_idletasks()
        tableWidth=table.winfo_reqwidth()
        tableHeight=table.winfo_reqheight()
        maxTableHeight=int(self.winfo_screenheight()*0.55)
        tableCanvas.configure(width=tableWidth, height=min(tableHeight, maxTableHeight),
                              scrollregion=(0, 0, tableWidth, tableHeight))
        if tableHeight > maxTableHeight:
            tableScrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            tableCanvas.bind_all("<MouseWheel>", lambda e: tableCanvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))

        tk.Label(dlg, text="", bg="black").pack()
        tk.Label(dlg, text="General comments about the photo", font=("Segoe UI", 12), fg="white", bg="black").pack()
        commentsBox=tk.Text(dlg, font=("Segoe UI", 11), width=48, height=3)
        commentsBox.pack(padx=30, pady=(4, 0))

        def OnSave() -> None:
            # TODO: Where this should be persisted is still to be decided; for now it is kept in memory
            self.photoInfo[pathname]={"names": [e.get().strip() for e in nameEntries], "comments": commentsBox.get("1.0", tk.END).strip()}
            dlg.destroy()

        buttons=tk.Frame(dlg, bg="black")
        buttons.pack(pady=15)
        tk.Button(buttons, text="Save", font=("Segoe UI", 12), width=9, command=OnSave).pack(side=tk.LEFT, padx=8)
        tk.Button(buttons, text="Cancel", font=("Segoe UI", 12), width=9, command=dlg.destroy).pack(side=tk.LEFT, padx=8)

        dlg.transient(self)
        dlg.grab_set()
        # Center the dialog on the screen
        dlg.update_idletasks()
        dlg.geometry(f"+{(self.winfo_screenwidth()-dlg.winfo_width())//2}+{(self.winfo_screenheight()-dlg.winfo_height())//2}")
        self.wait_window(dlg)

        self.unbind_all("<MouseWheel>")
        self.dialogOpen=False
        self.lastInputTime=time.time()
        if wasPaused:
            self.UpdateButtonStates()
        else:
            self.Resume()


def main() -> None:
    SlideShow().mainloop()


if __name__ == "__main__":
    main()
