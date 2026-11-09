"""The STJ Track add-on: build the extension zip, load it in Blender, run its operators. Needs Blender 5.2 or later
(set STJ_BLENDER to its path)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "tools" / "blender"))
sys.path.insert(0, str(ROOT / "examples"))
from test_blender_profile import find_blender  # noqa: E402


@unittest.skipUnless(find_blender(), "Blender not found (set STJ_BLENDER)")
class Addon(unittest.TestCase):
    def test_the_zip_builds_loads_and_round_trips_a_track(self):
        import build_addon
        import make_examples
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            zip_path = build_addon.build(d / "dist")
            self.assertTrue(zip_path.is_file())
            doc = make_examples.test_ring()
            src = d / "ring.stj.json"
            src.write_text(json.dumps(doc), encoding="utf-8")
            out = d / "out"
            out.mkdir()
            r = subprocess.run([find_blender(), "-b", "--factory-startup", "--python", str(ROOT / "tests" / "blender_addon_check.py"),
                                "--", str(zip_path), str(src), str(out)], capture_output=True, text=True, timeout=600)
            line = next((x for x in r.stdout.splitlines() if x.startswith("RESULT ")), None)
            self.assertTrue(line, r.stdout[-1500:] + r.stderr[-1500:])
            res = json.loads(line[7:])
        self.assertEqual(res["operators"], [True, True, True])
        self.assertTrue(res["panel"])
        self.assertEqual(res["ops"], {"import": ["FINISHED"], "lint": ["FINISHED"], "export": ["FINISHED"]})
        self.assertGreater(res["objects"], 5)
        self.assertGreater(res["panel_lines"], 0)
        self.assertIn("ring.stj.json", res["exported"])
        self.assertIn("ring.usd", res["exported"])
        self.assertTrue(res["same_document"], res)
        self.assertTrue(res["unregistered"])


if __name__ == "__main__":
    unittest.main()
