"""
SlideShow.py

Displays a full-screen slideshow of the images found in a directory tree.

The directory to be displayed and the other operating parameters are read from
"SlideShow settings.txt" (name=value lines) in the program's directory:

    Directory             Path of the directory tree holding the images
    Order                 "Sequential" or "Random"  (default: Sequential)
    Display Time          Seconds each image is displayed  (default: 10)
    Title                 Title shown at the top  (default: "photos.fanac.org")
    Display Subdirectory  If True, show the subdirectory chain under the title
                          for images not in the top-level directory  (default: True)
    Pause Timeout         Seconds of no user input after which a paused show
                          resumes on its own  (default: 240)

An image's description is taken from a .txt file with the same name in the
same directory (e.g., "xyz.jpg" described by "xyz.txt").  If there is none,
the image's filename without the extension is used.

Buttons: Prev, Pause, Continue, Next, Add Info, Exit.
Keyboard shortcuts: left/right arrows for Prev/Next, Esc for Exit.

Requires: pip install Pillow
"""

import os
import sys
import time
import random
import tkinter as tk
from tkinter import messagebox

from PIL import Image, ImageTk

SETTINGS_FILE="SlideShow settings.txt"
IMAGE_EXTENSIONS={".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}


# Read a settings file of name=value lines.  Blank lines and lines starting with '#' are ignored.
# Names are matched case-insensitive.
def ReadSettings(pathname: str) -> dict[str, str] | None:
    if not os.path.exists(pathname):
        return None
    settings={}
    with open(pathname, "r", encoding="utf-8") as file:
        for line in file:
            line=line.strip()
            if len(line) == 0 or line.startswith("#") or "=" not in line:
                continue
            name, _, val=line.partition("=")
            settings[name.strip().casefold()]=val.strip()
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

        self.rootDirectory=Get("Directory", "")
        self.randomOrder=Get("Order", "Sequential").casefold().startswith("random")
        self.displayTime=float(Get("Display Time", "10"))
        self.titleText=Get("Title", "photos.fanac.org")
        self.displaySubdirectory=IsTrue("Display Subdirectory", "True")
        self.pauseTimeout=float(Get("Pause Timeout", "240"))

        if len(self.rootDirectory) == 0 or not os.path.isdir(self.rootDirectory):
            self.Fatal(f"The Directory setting ('{self.rootDirectory}') is missing or is not a directory.\n\nEdit '{settingsPath}' to point to a directory of images.")

        # -------------------- Find the images --------------------
        self.images: list[str]=[]       # Full pathnames of all images found, in sorted order
        for dirpath, dirnames, filenames in os.walk(self.rootDirectory):
            dirnames.sort(key=str.casefold)
            for fname in sorted(filenames, key=str.casefold):
                if os.path.splitext(fname)[1].casefold() in IMAGE_EXTENSIONS:
                    self.images.append(os.path.join(dirpath, fname))
        if len(self.images) == 0:
            self.Fatal(f"No image files found under '{self.rootDirectory}'.")

        # History of images shown (indexes into self.images), so Prev can back up even in random order.
        self.history: list[int]=[]
        self.histpos=-1

        self.paused=False
        self.dialogOpen=False           # True while the Add Info dialog is up
        self.lastInputTime=time.time()
        self.advanceAfterId=None        # Id of the pending after() call which advances to the next image

        # -------------------- The display --------------------
        self.title("SlideShow")
        self.configure(bg="black")
        self.attributes("-fullscreen", True)

        self.titleLabel=tk.Label(self, text=self.titleText, font=("Segoe UI", 32, "bold"), fg="lightyellow", bg="black")
        self.titleLabel.pack(side=tk.TOP, pady=(10, 0))

        self.subdirLabel=tk.Label(self, text="", font=("Segoe UI", 28), fg="#bbbbbb", bg="black")
        self.subdirLabel.pack(side=tk.TOP)

        # Bottom-up: buttons at the very bottom, description just above them, image fills the rest.
        buttonFrame=tk.Frame(self, bg="black")
        buttonFrame.pack(side=tk.BOTTOM, pady=(5, 15))

        def MakeButton(text: str, command) -> tk.Button:
            b=tk.Button(buttonFrame, text=text, command=command, font=("Segoe UI", 12), width=9)
            b.pack(side=tk.LEFT, padx=8)
            return b

        self.prevButton=MakeButton("Prev", self.OnPrev)
        self.pauseButton=MakeButton("Pause", self.OnPause)
        self.continueButton=MakeButton("Continue", self.OnContinue)
        self.nextButton=MakeButton("Next", self.OnNext)
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

        self.descLabel=tk.Label(innerFrame, text="", font=("Segoe UI", 22), fg="white", bg="black",
                                justify=tk.CENTER, height=2, wraplength=self.winfo_screenwidth()-100)
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
        self.CheckPauseTimeout()


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

        # The optional subdirectory line: the path below the root directory, so photos in
        # the root itself show nothing, and deeper ones show e.g. "A" or "A/B"
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

        # The description: from a matching .txt file if there is one, else the filename
        descPath=os.path.splitext(pathname)[0]+".txt"
        desc=""
        if os.path.exists(descPath):
            try:
                with open(descPath, "r", encoding="utf-8", errors="replace") as file:
                    lines=[ln.strip() for ln in file.readlines() if len(ln.strip()) > 0]
                desc="\n".join(lines[:2])
            except OSError:
                pass
        if len(desc) == 0:
            desc=os.path.splitext(os.path.basename(pathname))[0]
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

    # Once a second, check whether a paused show has sat without user input for longer
    # than the pause timeout.  If so, resume it.
    def CheckPauseTimeout(self) -> None:
        if self.paused and not self.dialogOpen and time.time()-self.lastInputTime >= self.pauseTimeout:
            self.Resume()
        self.after(1000, self.CheckPauseTimeout)


    # -------------------- Buttons --------------------
    def OnUserInput(self, event=None) -> None:
        self.lastInputTime=time.time()

    def UpdateButtonStates(self) -> None:
        self.pauseButton.config(state=tk.DISABLED if self.paused else tk.NORMAL)
        self.continueButton.config(state=tk.NORMAL if self.paused else tk.DISABLED)

    def OnPause(self) -> None:
        self.paused=True
        self.CancelAdvance()
        self.UpdateButtonStates()

    def Resume(self) -> None:
        self.paused=False
        self.UpdateButtonStates()
        self.ScheduleAdvance()

    def OnContinue(self) -> None:
        self.Resume()

    def OnNext(self) -> None:
        self.NextImage()
        self.ScheduleAdvance()      # Restart the display-time clock

    def OnPrev(self) -> None:
        self.PrevImage()
        self.ScheduleAdvance()

    # Open the (for now, placeholder) Add Info dialog.  While it is up the show is paused;
    # when it closes, the show returns to whatever pause state it was in before.
    def OnAddInfo(self) -> None:
        wasPaused=self.paused
        self.paused=True
        self.dialogOpen=True
        self.CancelAdvance()
        self.UpdateButtonStates()

        dlg=tk.Toplevel(self)
        dlg.title("Add Info")
        dlg.configure(bg="black")
        tk.Label(dlg, text="Something Needed Here!", font=("Segoe UI", 16), fg="white", bg="black").pack(padx=40, pady=(30, 20))
        tk.Button(dlg, text="Cancel", font=("Segoe UI", 12), width=9, command=dlg.destroy).pack(pady=(0, 20))
        dlg.transient(self)
        dlg.grab_set()
        # Center the dialog on the screen
        dlg.update_idletasks()
        dlg.geometry(f"+{(self.winfo_screenwidth()-dlg.winfo_width())//2}+{(self.winfo_screenheight()-dlg.winfo_height())//2}")
        self.wait_window(dlg)

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
