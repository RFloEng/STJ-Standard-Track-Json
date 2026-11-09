"""The layered ground as Blender nodes (tools/blender/stj_ground.py): rendered in Blender and compared, pixel by
pixel, with the reference maths. Needs Blender (set STJ_BLENDER to its path)."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_blender_profile import find_blender  # noqa: E402

CHECK = ROOT / "tests" / "blender_ground_check.py"
STAGE = ROOT / "examples" / "coll_de_prova_gravel.usda"


def run_check(patch=None, window=60, size=160, stage=STAGE):
    with tempfile.TemporaryDirectory() as d:
        args = [find_blender(), "-b", "--factory-startup", "--python", str(CHECK), "--", str(stage), str(Path(d) / "r.png"),
                str(window), str(size)] + ([json.dumps(patch)] if patch else [])
        r = subprocess.run(args, capture_output=True, text=True, timeout=600)
    line = next((x for x in r.stdout.splitlines() if x.startswith("RESULT ")), None)
    assert line, r.stdout[-1500:] + r.stderr[-1500:]
    return json.loads(line[7:])


@unittest.skipUnless(find_blender(), "Blender not found (set STJ_BLENDER)")
class GroundNodes(unittest.TestCase):
    def assert_matches(self, res):
        self.assertTrue(res["built"], res)
        self.assertGreater(res["samples"], 100)
        self.assertGreaterEqual(res["within_0_02"], 0.99, res)

    def test_the_height_blend_with_a_tint_map(self):
        self.assert_matches(run_check())

    def test_the_linear_blend(self):
        self.assert_matches(run_check({"blend": {"method": "linear"}}))

    def test_the_colour_and_multiply_macro_encodings(self):
        for enc in ({"encoding": "colour", "strength": 0.8}, {"encoding": "multiply"}):
            macro = {"kind": "tint", "uri": "ground/sec01_tint.png", "texcoord": "st", **enc}
            self.assert_matches(run_check({"macro": [macro]}))

    def test_the_mask_blend(self):
        import random
        sys.path.insert(0, str(ROOT / "tools"))
        import stj_core as core
        with tempfile.TemporaryDirectory() as d:
            copy = Path(d) / "examples"
            shutil.copytree(ROOT / "examples", copy)
            rnd = random.Random(5)
            core.write_png(copy / "ground" / "mask_a.png", 16, 16, [rnd.randrange(256) for _ in range(256)], channels=1)
            core.write_png(copy / "ground" / "mask_b.png", 16, 16, [rnd.randrange(256) for _ in range(256 * 4)], channels=4)
            core.write_png(copy / "ground" / "mask_c.png", 16, 16, [rnd.randrange(256) for _ in range(256 * 3)], channels=3)
            masks = [{"uri": "ground/mask_a.png", "tile": 7.0},
                     {"uri": "ground/mask_b.png", "channel": "a", "tile": 5.0, "projection": "road"},
                     {"uri": "ground/mask_c.png", "channel": "g", "tile": 9.0}]
            self.assert_matches(run_check({"blend": {"method": "mask", "mask": masks, "softness": 0.2}},
                                          stage=copy / STAGE.name))

    def test_a_mask_blend_without_its_masks_keeps_the_preview_surface_and_says_so(self):
        res = run_check({"blend": {"method": "mask"}})
        self.assertFalse(res["built"])
        self.assertTrue(any("mask" in n for n in res["notes"]), res)


if __name__ == "__main__":
    unittest.main()
