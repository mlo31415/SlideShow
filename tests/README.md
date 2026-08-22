# SlideShow tests

Run them from the `SlideShow` folder:

```
python -m unittest discover -s tests
```

No pytest, no plugins, no configuration: the standard library only, so the
suite runs anywhere the app does. It needs no photo collection, opens no
window, and takes about a third of a second.

## What is covered

These are the pure parts — the ones where a mistake is silent, and where a
wrong answer shows a visitor the wrong photographs.

| File | Covers |
|------|--------|
| `test_settings.py` | Reading the settings file: the `Directories:` block, commented-out values, names matched without regard to case |
| `test_photo_shows.py` | What a show stands for (overlapping and missing folders), the shows file and its v1→v2 tidying, finding the photos |
| `test_folder_picking.py` | The check boxes in Edit Photo Shows: which folders a show comes to, ticking, unticking, and unticking *inside* a ticked folder |
| `test_display_values.py` | Photo dates, the face-detection threshold, pack padding, the album line |

Where the code under test is a method rather than a plain function, the tests
build a bare object with `object.__new__` and give it only the attributes that
method uses — see `_support.py`. That is what keeps the suite free of Tk.

Careful with `SlideShow`: it inherits from `tk.Tk`, whose `__getattr__`
forwards anything it does not recognise to the Tcl interpreter. A missing
attribute on a bare object therefore ends in a `RecursionError` rather than an
`AttributeError`. If a test dies that way, an attribute is missing from the
`bare_show(...)` call, not from the app.

## What is not covered, and why

- **Anything drawn.** Layout, scaling, the split screen, the tooltips and the
  green face ring were checked against a real window, by measuring the widgets
  after the event loop had settled. Worth automating one day; those tests are
  slow, need a desktop session, and several of them are only meaningful on a
  second monitor.
- **Face detection itself.** That is OpenCV's YuNet model doing the work. What
  is worth checking here is what SlideShow does with the boxes, which the
  README's face-box section pins down.
- **The output log.** PhotosEditor's own suite covers reading, rewriting and
  marking those files, and does it in more detail than SlideShow could: PE is
  the program that writes to them.

When adding a test, prefer one that needs none of the three. If a bug turns up
in code that does need them, that is usually a sign the logic wants pulling out
into a function that does not.

## A note on the folder-picking tests

`test_folder_picking.py` grew out of a real defect (**SS-19**, fixed): a show
used to be able to say only "this folder and everything below it", so unticking
something inside a ticked folder dropped the photos sitting loose in the folders
along the way. A show can now leave folders out again, and those tests pin the
rule down — including the cases that made the old arrangement wrong.
