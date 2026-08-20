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
  the identifier's name or email address.  The email address is remembered between saves
  while the user stays active (see *Email Timeout*).  Prev and Next stay live
  while the panel is up: they discard anything not yet saved, move to the next
  photo, and rebuild the panel for it; Pause and Add Info are disabled.  (Face
  detection uses OpenCV's YuNet model, the .onnx file alongside the script.)

Each Save appends a record to this session's output log, `SlideShow Output
<date and time of the latest save>.json` in the program's directory (a new
file per run, created at the first save so a run with no saves leaves no
file): concatenated pretty-printed JSON objects holding the save
time, the photo's Piwigo id and file name (from its `.xml` companion), the
album path, the editor's name or email, the numbered faces with names and
detection boxes, the comment, and the photo date.  Load with
`json.JSONDecoder().raw_decode` in a loop.  The face rows in the panel are
numbered #1, #2, … so a comment can refer to a face by its number.

The show opens on the monitor it was on last time (remembered in `SlideShow
state.json`); if that monitor is gone, it opens on the main one instead.
Dragging the top bar moves the window to another monitor.

A top bar across the top of the screen holds the **Select Photo Show** menu at
the left and a **✕** close box in the upper-right corner.

## Photo shows

What the slideshow displays is a *photo show*: a named group of folders taken
from anywhere in the root directory's tree, each folder standing for itself and
everything below it.  Picking one from the **Select Photo Show** menu switches
to it.  Shows are kept in `SlideShow shows.json` beside the settings file:

```json
{"shows": [
   {"name": "Worldcons", "folders": ["Worldcons", "Fan Photos/LASFS"]},
   {"name": "Fan Photos", "folders": ["Fan Photos"]}]}
```

Folder paths are relative to the root directory and use `/` separators.  A
folder that no longer exists is skipped, and a folder already covered by
another in the same show is ignored, so no photo is ever shown twice.  When
there is no shows file, one show per top-level directory is made up, plus an
"All Photos" show holding them all.

Keyboard shortcuts: **left arrow** = Prev, **right arrow** = Next, **Esc** = exit.

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
