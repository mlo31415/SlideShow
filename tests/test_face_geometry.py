"""How a face is shown: the circle SlideShow cuts its round pictures from.

The same geometry decides what PhotosEditor draws while reviewing, so both
programs are held to one set of recorded numbers -- FaceGeometryGolden.json,
beside the shared module in HelpersPackage.  If this file and PhotosEditor's
`test_face_geometry.py` disagree, the two programs have drifted apart, which is
the thing the shared module exists to prevent.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import load_ss                                 # noqa: E402

ss = load_ss()

_GOLDEN = (Path(__file__).resolve().parent.parent.parent
           / "HelpersPackage" / "FaceGeometryGolden.json")


@unittest.skipUnless(_GOLDEN.is_file(), f"the shared HelpersPackage is not beside SlideShow ({_GOLDEN})")
class TheRecordedCircles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))
        sys.path.insert(0, str(_GOLDEN.parent))

    def test_the_ratio_is_the_recorded_one(self):
        from FaceGeometry import FACE_CIRCLE_RATIO
        self.assertEqual(FACE_CIRCLE_RATIO, self.golden["ratio"])

    def test_every_recorded_face_gives_its_recorded_circle(self):
        from FaceGeometry import FaceCircle, FaceCircleBounds
        for case in self.golden["cases"]:
            with self.subTest(case["what"]):
                self.assertEqual([round(v, 6) for v in FaceCircle(case["box"])], case["circle"])
                self.assertEqual([round(v, 6) for v in FaceCircleBounds(case["box"])], case["bounds"])

    def test_a_face_on_a_scaled_photo_lands_where_it_should(self):
        from FaceGeometry import FaceCircleOnDisplay
        case = self.golden["on display"]
        drawn = FaceCircleOnDisplay(case["box"], case["original size"], case["display rect"])
        self.assertEqual([round(v, 6) for v in drawn], case["circle"])

    def test_a_face_which_cannot_belong_to_the_photo_is_refused(self):
        """Rather than drawing a ring somewhere wrong."""
        from FaceGeometry import FaceCircleOnDisplay
        for case in self.golden["refused"]:
            with self.subTest(case["what"]):
                self.assertIsNone(FaceCircleOnDisplay(case["box"], case["original size"],
                                                      case["display rect"]))


@unittest.skipUnless(_GOLDEN.is_file(), "the shared HelpersPackage is not beside SlideShow")
class TheRoundPicture(unittest.TestCase):
    """SS-2: a face at the edge of a photo keeps its shape.  The crop is padded
    out to the circle rather than clamped to the photo, which used to squash an
    edge face sideways when the square was resized."""

    @staticmethod
    def photo(centreX, centreY):
        """A photo with a black square centred where the face is.  If the
        thumbnail stretches, the square stops being square -- which is exactly
        what clamping the crop to the photo used to do to an edge face."""
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (200, 200), "white")
        ImageDraw.Draw(image).rectangle((centreX-10, centreY-10, centreX+10, centreY+10), fill="black")
        return image

    @staticmethod
    def markerAspect(thumb):
        dark = [(x, y) for y in range(thumb.height) for x in range(thumb.width)
                if sum(thumb.getpixel((x, y))) < 200]
        xs, ys = [p[0] for p in dark], [p[1] for p in dark]
        return (max(xs)-min(xs)+1)/(max(ys)-min(ys)+1)

    def test_a_face_at_the_edge_is_shaped_like_one_in_the_middle(self):
        from FaceGeometry import RoundFaceThumbnail, FaceCircleBounds
        edgeBox = [0, 80, 40, 40]                            # hard against the left edge
        self.assertLess(FaceCircleBounds(edgeBox)[0], 0, "the circle really does hang off the photo")
        middle = RoundFaceThumbnail(self.photo(100, 100), [80, 80, 40, 40], "white", 72)
        edge = RoundFaceThumbnail(self.photo(20, 100), edgeBox, "white", 72)
        self.assertAlmostEqual(self.markerAspect(edge), self.markerAspect(middle), delta=0.05,
                               msg="an edge face is being stretched (SS-2)")

    def test_what_lies_beyond_the_photo_is_the_background(self):
        """Not black -- PIL's own padding would ignore the colour asked for, and
        show a black wedge on a light background."""
        from FaceGeometry import RoundFaceThumbnail
        thumb = RoundFaceThumbnail(self.photo(20, 100), [0, 80, 40, 40], "red", 72)
        self.assertEqual(thumb.getpixel((3, 36)), (255, 0, 0))

    def test_the_thumbnail_is_the_size_asked_for_and_round(self):
        from FaceGeometry import RoundFaceThumbnail
        thumb = RoundFaceThumbnail(self.photo(100, 100), [80, 80, 40, 40], "red", 72)
        self.assertEqual(thumb.size, (72, 72))
        self.assertEqual(thumb.getpixel((0, 0)), (255, 0, 0), "the corners are outside the circle")

    def test_a_box_with_no_size_gives_a_plain_picture_rather_than_failing(self):
        from FaceGeometry import RoundFaceThumbnail
        thumb = RoundFaceThumbnail(self.photo(100, 100), [10, 10, 0, 0], "red", 72)
        self.assertEqual(thumb.size, (72, 72))


@unittest.skipUnless(_GOLDEN.is_file(), "the shared HelpersPackage is not beside SlideShow")
class TheFacesTooSmallToBother(unittest.TestCase):
    """A detector finds faces far back in a crowd that nobody could name.  They
    are measured against the third-largest face in the same photo, so that one
    head close to the camera cannot set the bar for everybody behind it."""

    @staticmethod
    def square(size, x=0):
        return (x, 0, size, size)

    def drop(self, boxes, ratio=None):
        from FaceGeometry import DropTinyFaces, SMALL_FACE_RATIO
        return DropTinyFaces(boxes, SMALL_FACE_RATIO if ratio is None else ratio)

    def test_the_ratio_is_a_fifth(self):
        from FaceGeometry import SMALL_FACE_RATIO
        self.assertEqual(SMALL_FACE_RATIO, 0.20)

    def test_it_is_measured_across_the_face_not_by_area(self):
        """A face a fifth as wide is a speck; a face a fifth the *area* is
        nearly half as wide, which is a person merely standing further back."""
        from FaceGeometry import FaceSize
        self.assertAlmostEqual(FaceSize((0, 0, 30, 40)), 50.0)

    def test_a_speck_behind_a_crowd_goes(self):
        boxes = [self.square(100), self.square(90, 200), self.square(80, 400),
                 self.square(10, 600)]
        self.assertEqual(len(self.drop(boxes)), 3)

    def test_the_measure_is_the_third_largest_not_the_largest(self):
        """One big foreground head must not carry away the faces behind it.
        Third largest is 80, so the bar is 16: the 20 stays."""
        boxes = [self.square(400), self.square(90, 500), self.square(80, 700),
                 self.square(20, 900)]
        self.assertEqual([b[2] for b in self.drop(boxes)], [400, 90, 80, 20])

    def test_a_face_exactly_on_the_bar_stays(self):
        boxes = [self.square(100), self.square(100, 200), self.square(100, 400),
                 self.square(20, 600)]
        self.assertEqual(len(self.drop(boxes)), 4)

    def test_whichever_face_sets_the_bar_always_clears_it(self):
        for sizes in ([50, 40, 30], [90, 12, 11, 10], [7, 7, 7, 7], [400, 9]):
            with self.subTest(sizes=sizes):
                boxes = [self.square(s, i*1000) for i, s in enumerate(sizes)]
                kept = [b[2] for b in self.drop(boxes)]
                ordered = sorted(sizes, reverse=True)
                self.assertIn(ordered[2] if len(sizes) >= 3 else ordered[0], kept)

    def test_two_faces_are_measured_against_the_larger(self):
        """No crowd here for the third-largest to protect, so the larger face
        is the only reference there is."""
        self.assertEqual([b[2] for b in self.drop([self.square(100),
                                                   self.square(3, 200)])], [100])
        self.assertEqual(len(self.drop([self.square(100), self.square(90, 200)])), 2)
        self.assertEqual(len(self.drop([self.square(100), self.square(20, 200)])), 2,
                         "exactly on the bar, so it stays")

    def test_a_single_face_is_never_dropped(self):
        """Nothing to compare it against, and it is the whole photograph."""
        self.assertEqual(len(self.drop([self.square(3)])), 1)
        self.assertEqual(self.drop([]), [])

    def test_a_photo_of_evenly_sized_faces_loses_none(self):
        boxes = [self.square(50, i*100) for i in range(8)]
        self.assertEqual(len(self.drop(boxes)), 8)

    def test_a_crowd_keeps_everyone_worth_naming(self):
        """Six faces receding into the distance and two specks."""
        boxes = [self.square(s, i*1000) for i, s in
                 enumerate([120, 110, 100, 60, 40, 21, 19, 5])]
        self.assertEqual([b[2] for b in self.drop(boxes)],
                         [120, 110, 100, 60, 40, 21])

    def test_the_boxes_come_back_unchanged(self):
        boxes = [(5, 6, 100, 100), (7, 8, 90, 90), (9, 10, 80, 80)]
        self.assertEqual(self.drop(boxes), boxes)

    def test_degenerate_boxes_do_not_raise(self):
        self.assertEqual(len(self.drop([self.square(0), self.square(0, 1),
                                        self.square(0, 2)])), 3)


@unittest.skipUnless(_GOLDEN.is_file(), "the shared HelpersPackage is not beside SlideShow")
class DetectionUsesIt(unittest.TestCase):
    def test_detect_faces_puts_its_boxes_through_the_filter(self):
        """Without this the rule would live in the shared module unused."""
        import inspect
        source = inspect.getsource(ss.SlideShow.DetectFaces)
        self.assertIn("DropTinyFaces(boxes)", source)


if __name__ == "__main__":
    unittest.main()
