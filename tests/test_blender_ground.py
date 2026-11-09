"""The layered ground as Blender nodes (tools/blender/stj_ground.py): rendered in Blender and compared, pixel by
pixel, with the reference maths. Needs Blender (set STJ_BLENDER to its path)."""
import json
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


def run_check(patch=None, window=60, size=160):
    with tempfile.TemporaryDirectory() as d:
        args = [find_blender(), "-b", "--factory-startup", "--python", str(CHECK), "--", str(STAGE), str(Path(d) / "r.png"),
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

    def test_the_mask_blend_keeps_the_preview_surface_and_says_so(self):
        res = run_check({"blend": {"method": "mask"}})
        self.assertFalse(res["built"])
        self.assertTrue(any("mask" in n for n in res["notes"]), res)


if __name__ == "__main__":
    unittest.main()
