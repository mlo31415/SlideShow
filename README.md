# SlideShow

A full-screen slideshow of the images found in a directory tree (any mix of
.jpg, .jpeg, .png, .gif, .bmp, .webp, .tif, .tiff, at any depth of subdirectories).

The display shows a large title at the top, optionally the image's subdirectory
chain under it, the image scaled to fit, and up to two lines of description
below the image.  Each photo comes with two same-named companion files: a
`.txt` holding the caption and an `.xml` holding photo information from
Piwigo.  The caption shown is the `.txt` content; if there is none, the
image's filename without the extension is used.  A caption too long for its
two lines is shown in a progressively smaller font until it fits.

## Buttons

* **Prev** — move to the previous image shown
* **Pause** — stop advancing (resumes on its own after *Pause Timeout* seconds without user input)
* **Continue** — resume advancing
* **Next** — move to the next image
* **Add Info** — opens the Identify Photo dialog: the faces found in the
  photo are listed left-to-right, each with a box to enter the person's name,
  plus a box for general comments about the photo.  (Face detection uses
  OpenCV's YuNet model, the .onnx file alongside the script.  Where the
  entered information gets saved is still to be decided.)
* **Exit** — exits the program

Keyboard shortcuts: **left arrow** = Prev, **right arrow** = Next, **Esc** = Exit.

## Settings

Operating parameters are read from `SlideShow settings.txt` (name=value lines)
in the program's directory:

| Name | Meaning | Default |
|------|---------|---------|
| Directories: | Starts a list of directory paths, one per line, each the root of a tree of images to display; the list ends at the first line which is not a valid directory path | *(at least one required)* |
| Order | `Sequential` or `Random` | Sequential |
| Display Time | Seconds each image is shown | 10 |
| Title | Title shown at the top | photos.fanac.org |
| Title Font | Font family for the title (must be an installed font; matched case-insensitive, prefixes allowed, so "Hobo" finds "Hobo Std") | Segoe UI |
| Title Font Size | Point size for the title | 32 |
| Display Subdirectory | Show the subdirectory chain for images below the top level | True |
| Pause Timeout | Seconds of no user input after which a paused show resumes | 240 |

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
