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


if __name__ == "__main__":
    unittest.main()
