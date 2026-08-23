# SlideShow

A full-screen slideshow of the images found in a directory tree (any mix of
.jpg, .jpeg, .png, .gif, .bmp, .webp, .tif, .tiff, at any depth of subdirectories).

The display shows a large title at the top, optionally the image's subdirectory
chain under it, the image scaled to fit, and up to two lines of description
below the image.  Each photo comes with two same-named companion files: a
`.txt` holding the caption and an `.xml` holding photo information from
Piwigo.  The caption shown is the `.txt` content; if there is none, the
image's filename without the extension is used.  A caption too long for its
two lines is shown in a progressively smaller font until it fits.  Below the
caption, in smaller type, the `.xml` file's author and date are shown as
"Photo supplied by …" and "Photo date: …" (each line omitted when that
information is missing).  Dates are shown readably ("June 4, 1942"); a
January 1st date is Piwigo's way of saying only the year is known, so it
shows as just the year.

## Buttons

* **Prev** — move to the previous image shown
* **Pause / Start Slideshow** — one button which toggles with the state: it
  stops the advancing (resuming on its own after *Pause Timeout* seconds
  without user input), or starts it again
* **Next** — move to the next image
* **Add Info** — splits the window in two the narrow way (left/right halves
  on a landscape screen, top/bottom on a portrait one), shoves the photo into
  one half, and shows the Identify Photo panel in the other: the faces found
  in the photo listed left-to-right, each with a box to enter the person's
  name, plus boxes for other comments and corrections, the photo's date, and
  the identifier's name or email address.  Pointing at a row — the face, its
  number, or its name box — rings that face in green on the photo itself, so
  it is clear which person the row is about.  The email address is remembered between saves
  while the user stays active (see *Email Timeout*).  Prev and Next stay live
  while the panel is up: they discard anything not yet saved, move to the next
  photo, and rebuild the panel for it; Pause and Add Info are disabled.  (Face
  detection uses OpenCV's YuNet model, the .onnx file alongside the script.
  Reading the photograph and finding the faces in it happen off the display's
  own thread, so the panel appears at once — saying "Looking for faces…" —
  and the rows arrive when they are ready.  Switching shows works the same
  way: the photo on screen carries on until the new show's photos have been
  found.)

Each Save appends a record to this session's output log, `SlideShow Output
<date and time of the latest save>.json` in the program's directory (a new
file per run, created at the first save so a run with no saves leaves no
file): concatenated pretty-printed JSON objects holding the save
time, the photo's Piwigo id and file name (from its `.xml` companion), the
album path, the editor's name or email, the numbered faces with names and
detection boxes, the comment, and the photo date.  Load with
`json.JSONDecoder().raw_decode` in a loop.  The face rows in the panel are
numbered #1, #2, … so a comment can refer to a face by its number.

A record looks like this:

```json
{
  "saved": "2026-08-20 16:04:55",
  "photo id": 11725,
  "file": "e-l00100.jpg",
  "album": "Fan Photos/LASFS/1941-1943",
  "editor": "mlo@baskerville.org",
  "faces": [
    {"number": 1, "name": "Sam Russell", "box": [412, 88, 60, 74]},
    {"number": 2, "name": "", "box": [502, 95, 58, 70]}
  ],
  "comment": "The rear row, left to right.",
  "photo date": "June 1942"
}
```

**The face boxes.** `box` is `[x, y, w, h]` in **pixels of the original photo**
— not of the photo as displayed, which is scaled to fit the screen.  `x` and
`y` are the top-left corner, measured from the top-left of the photo with `x`
increasing to the right and `y` downwards; `w` and `h` are the box's width and
height.  These are the boxes OpenCV's YuNet detector returns, listed
left-to-right by `x`, and `number` is the row's position in that order.

A consumer wanting to show a face the way SlideShow does should draw a
**circle**, not the box: centred on the box's centre, with a radius of
`0.65 × √(w² + h²)` — 0.65 of the box's diagonal.  That is what the round
thumbnails in the Identify Photo list are cut from, and what the green ring
drawn over the photo follows.

The show opens on the monitor it was on last time (remembered in `SlideShow
state.json`); if that monitor is gone, it opens on the main one instead.
Dragging the top bar moves the window to another monitor.

A top bar across the top of the screen holds the **Select Photo Show** menu at
the left and a **✕** close box in the upper-right corner.

## Photo shows

What the slideshow displays is a *photo show*: a named group of folders taken
from anywhere in the root directory's tree, each folder standing for itself and
everything below it.  The **Select Photo Show** menu offers the built-in **All
Photos** — everything under the root — followed by whatever shows have been
built with **Edit Photo Shows…** at the bottom of the same menu.

The shows you build are kept in `SlideShow shows.json` beside the settings
file, and last from one run to the next:

```json
{"version": 3, "shows": [
   {"name": "Fan Photos, mostly",
    "folders": ["Fan Photos"],
    "except": ["Fan Photos/LASFS/1941-1943"]}]}
```

A show names the folders it takes and, if you like, folders to leave out of
them again — each standing for itself and everything below it, with the most
specific entry deciding.  So the show above means *all of Fan Photos except
that one folder*.  Paths are relative to the root directory and use `/`
separators; a folder that no longer exists is skipped, and an entry that
changes nothing is dropped, so the file holds just what you actually said.

The **Edit Photo Shows** dialog lists the shows on the left (New / Rename /
Delete) and the whole folder tree on the right, with a check box on every
folder at any level:

* **Ticking** a folder takes it and everything below it.
* **Unticking** a folder leaves out it and everything below it.
* Neither touches the folder's parent or the folders alongside it, so
  unticking one folder inside a ticked one leaves the rest of that folder —
  including any photos sitting loose in it — in the show.
* Ticking a folder again clears whatever was said about its contents, so
  rules can never pile up out of sight.

A box therefore says one thing only: whether that folder's photos are in the
show.  Because a closed folder could still hide something, a row says so —
*"Fan Photos   (1 folder left out)"* — and any branch with something chosen or
left out inside it is opened for you when the show is loaded.  Under the tree,
the show is written out in words (*"all of Fan Photos except LASFS/1941-1943"*)
along with a running count of the folders and photos it comes to.  Folders
which have since been deleted appear in gray so they can be cleared out.
**Save** keeps the changes; **Cancel** throws them away, asking first if
anything was changed.

Keyboard shortcuts: **left arrow** = Prev, **right arrow** = Next, **Esc**
closes the Identify Photo panel when it is up, and otherwise exits.

## Settings

Operating parameters are read from `SlideShow settings.txt` (name=value lines)
in the program's directory:

| Name | Meaning | Default |
|------|---------|---------|
| Directories: | The next line is the path of the root directory holding the photos.  See **Photo shows** below | *(required)* |
| Order | `Sequential` or `Random` | Sequential |
| Display Time | Seconds each image is shown | 10 |
| Title | Title shown at the top | photos.fanac.org |
| Title Font | Font family for the title (must be an installed font; matched case-insensitive, prefixes allowed, so "Hobo" finds "Hobo Std") | Segoe UI |
| Title Font Size | Point size for the title | 32 |
| Display Subdirectory | Show the subdirectory chain for images below the top level | True |
| Pause Timeout | Seconds of no user input after which a paused show resumes | 240 |
| Mode | `Dark` or `Light` color scheme | Dark |
| Email Timeout | Seconds of no user input after which the remembered email address is forgotten | 60 |
| Face Detection Threshold | How sure the detector must be before it calls something a face, 0 to 1.  Lower finds more faces, including doubtful ones; higher finds only clear ones | 0.6 |

A parameter value whose first non-blank character is `#` is treated as empty,
and the parameter's default is used.

The settings file is monitored while the show is running: saving a change to it
applies just the changed parameters on the fly.  A changed Directory restarts
the show from the new tree; any other change leaves the current image
undisturbed.  Unrecognized parameter names and unusable values (bad numbers,
uninstalled fonts, a nonexistent directory) are reported in a warning dialog
and otherwise ignored; missing parameters revert to their defaults.

## Requirements

Python 3.10+, Pillow, and OpenCV:

```
pip install Pillow opencv-python
```
