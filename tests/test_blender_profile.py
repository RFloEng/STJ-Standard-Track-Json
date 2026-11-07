"""The STJ Blender profile (spec/STJ_Blender_Profile.md): names, scene to document, checker.

The tests use a hand-made scene description, so they run without Blender. One test runs Blender itself
when it can be found (set STJ_BLENDER to its path): it builds the reference .blend, lints it and exports it.
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "blender"))
import stj_core as core  # noqa: E402
import stj_profile as profile  # noqa: E402
import validate  # noqa: E402

# a straight 1 km road along +X, 12 m wide
BASE = {
    "_metadata": {"specification": "STJ", "version": "0.3", "coordinate_system": "OpenDRIVE", "units": "SI"},
    "track_info": {"name": "Profile test", "type": "point_to_point"},
    "reference": {"centerline": {"width": {"left": 6.0, "right": 6.0}}},
    "surfaces": {"default": "asphalt", "library": {"asphalt": {"class": "asphalt"}}},
}


def empty(name, x, y, heading=0.0):
    return {"name": name, "type": "EMPTY", "location": [x, y, 0.0], "heading": heading, "collections": [], "props": {}}


def scene(**over):
    s = {"blender": "5.2.2", "profile": profile.PROFILE_VERSION,
         "objects": [{"name": "STJ::reference::centerline", "type": "CURVE", "location": [0, 0, 0], "heading": 0.0,
                      "collections": [], "props": {}, "cyclic": False,
                      "points": [[0, 0, 0], [500, 0, 0], [1000, 0, 0]]}],
         "materials": [{"name": "STJ::surface::asphalt", "props": {}}],
         "texts": {profile.BASE_TEXT: json.dumps(BASE)}, "scene_props": {}}
    s.update(over)
    return s


def levels(findings, level):
    return [f"{where}: {msg}" for lvl, where, msg in findings if lvl == level]


class Names(unittest.TestCase):
    def test_both_spellings_and_the_duplicate_suffix(self):
        self.assertEqual(profile.parse_name("STJ::timing::start"), ("timing", "start", None))
        self.assertEqual(profile.parse_name("STJ__timing__start"), ("timing", "start", None))
        self.assertEqual(profile.parse_name("STJ::timing::start.001"), ("timing", "start", None))
        self.assertEqual(profile.parse_name("STJ::pit::box1::garage"), ("pit", "box1", "garage"))

    def test_other_names_are_not_stj(self):
        self.assertIsNone(profile.parse_name("Cube"))
        self.assertIsNone(profile.parse_name("STJ_Collision"))


class SceneToDocument(unittest.TestCase):
    def test_the_reference_curve_becomes_the_centerline(self):
        doc = profile.apply_scene(scene())
        cl = doc["reference"]["centerline"]
        self.assertEqual(cl["points"], [[0, 0, 0], [500, 0, 0], [1000, 0, 0]])
        self.assertEqual(cl["width"], {"left": 6.0, "right": 6.0})        # kept from the text block
        self.assertNotIn("closed", cl)

    def test_a_cyclic_curve_is_closed_and_a_bezier_curve_has_tangents(self):
        s = scene()
        ref = s["objects"][0]
        ref["cyclic"] = True
        ref["points"] = [[0, 0, 0], [100, 0, 0], [100, 100, 0]]
        ref["tangents_out"] = [[10, 0, 0]] * 3
        ref["tangents_in"] = [[10, 0, 0]] * 3
        cl = profile.apply_scene(s)["reference"]["centerline"]
        self.assertTrue(cl["closed"])
        self.assertEqual(len(cl["tangents_out"]), 3)

    def test_gates_are_projected_onto_the_reference_line(self):
        s = scene()
        s["objects"] += [empty("STJ::timing::start", 100, 2), empty("STJ::timing::finish", 900, -1),
                         empty("STJ::timing::split_2", 600, 0), empty("STJ::timing::split_1", 300, 0)]
        t = profile.apply_scene(s)["timing"]
        self.assertAlmostEqual(t["start"]["s"], 100.0, places=1)
        self.assertAlmostEqual(t["finish"]["s"], 900.0, places=1)
        self.assertEqual([p["id"] for p in t["split_points"]], ["split_1", "split_2"])   # in race order

    def test_grid_pit_boxes_and_spawns_are_poses(self):
        s = scene()
        s["objects"] += [empty("STJ::grid::2", 10, -2, 0.5), empty("STJ::grid::1", 20, 2, 0.5),
                         empty("STJ::pit::box1", 50, -9), empty("STJ::pit::box1::garage", 50, -14),
                         empty("STJ::spawn::hotlap", 5, 0)]
        race = profile.apply_scene(s)["race"]
        self.assertEqual([g["position"] for g in race["grid"]], [1, 2])
        self.assertEqual(race["grid"][0]["pose"], {"position": [20, 2, 0], "heading": 0.5})
        self.assertEqual(race["pit_boxes"][0]["garage_pose"]["position"], [50, -14, 0])
        self.assertEqual(race["spawns"][0]["id"], "hotlap")

    def test_the_text_block_is_the_base_and_the_objects_win(self):
        base = dict(BASE, timing={"start": {"s": 5.0}, "sectors": [{"id": "s1", "s_start": 0, "s_end": 900}]})
        s = scene(texts={profile.BASE_TEXT: json.dumps(base)})
        s["objects"].append(empty("STJ::timing::start", 100, 0))
        doc = profile.apply_scene(s)
        self.assertAlmostEqual(doc["timing"]["start"]["s"], 100.0, places=1)
        self.assertEqual(doc["timing"]["sectors"][0]["id"], "s1")
        self.assertTrue(any("timing.start.s" in m and "objects win" in m for m in levels(profile.lint_scene(s), "NOTE")))

    def test_the_stj_property_is_merged_into_the_curve(self):
        s = scene()
        s["objects"][0]["props"] = {"stj": {"width": {"left": 8.0, "right": 8.0}}}
        self.assertEqual(profile.apply_scene(s)["reference"]["centerline"]["width"]["left"], 8.0)

    def test_the_result_is_a_valid_document(self):
        s = scene()
        s["objects"] += [empty("STJ::timing::start", 100, 0), empty("STJ::timing::finish", 900, 0),
                         empty("STJ::grid::1", 90, 2), empty("STJ::pit::box1", 50, -9)]
        doc = profile.apply_scene(s)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "track.stj.json"
            p.write_text(json.dumps(doc), encoding="utf-8")
            rep = validate.validate(str(p))
        self.assertEqual([f"{w}: {m}" for lv, w, m in rep.items if lv == "ERROR"], [])


class Checker(unittest.TestCase):
    def test_a_clean_scene_has_no_errors(self):
        self.assertEqual(levels(profile.lint_scene(scene()), "ERROR"), [])

    def test_profile_version(self):
        self.assertTrue(any("profile version is unknown" in m for m in levels(profile.lint_scene(scene(profile=None)), "WARN")))
        self.assertTrue(any("newer than this checker" in m for m in levels(profile.lint_scene(scene(profile="9.0")), "ERROR")))

    def test_an_untested_blender_version_is_a_warning(self):
        self.assertTrue(any("Blender 4.2.1" in m for m in levels(profile.lint_scene(scene(blender="4.2.1")), "WARN")))

    def test_no_base_document_and_no_reference(self):
        s = scene(texts={})
        s["objects"] = []
        found = levels(profile.lint_scene(s), "ERROR")
        self.assertTrue(any("no base document" in m for m in found))
        self.assertTrue(any("no reference curve" in m for m in found))

    def test_two_reference_curves(self):
        s = scene()
        s["objects"].append(dict(s["objects"][0], name="STJ::reference::second"))
        self.assertTrue(any("2 reference curves" in m for m in levels(profile.lint_scene(s), "ERROR")))

    def test_bad_names_and_kinds(self):
        s = scene()
        s["objects"] += [empty("STJ_oops", 0, 0), empty("STJ::timing::Start", 0, 0), empty("STJ::grid::first", 0, 0),
                         empty("STJ::pit::box1::roof", 0, 0), empty("STJ::reference::x", 0, 0)]
        found = " | ".join(levels(profile.lint_scene(s), "ERROR"))
        self.assertIn("starts with STJ but is not", found)
        self.assertIn("lowercase letters", found)
        self.assertIn("named by its position", found)
        self.assertIn("unknown part 'roof'", found)
        self.assertIn("is for CURVE, this is EMPTY", found)

    def test_unknown_category_is_a_warning(self):
        s = scene()
        s["objects"].append(empty("STJ::banner::start", 0, 0))
        self.assertTrue(any("unknown category 'banner'" in m for m in levels(profile.lint_scene(s), "WARN")))

    def test_the_same_name_twice(self):
        s = scene()
        s["objects"] += [empty("STJ::timing::start", 0, 0), empty("STJ::timing::start.001", 5, 0)]
        self.assertTrue(any("same STJ name" in m for m in levels(profile.lint_scene(s), "ERROR")))

    def test_a_gate_far_from_the_track(self):
        s = scene()
        s["objects"].append(empty("STJ::timing::start", 100, 200))
        self.assertTrue(any("belongs on the track" in m for m in levels(profile.lint_scene(s), "WARN")))

    def test_a_surface_material_that_the_document_does_not_know(self):
        s = scene()
        s["materials"].append({"name": "STJ::surface::mud", "props": {}})
        self.assertTrue(any("'mud' is not in surfaces.library" in m for m in levels(profile.lint_scene(s), "WARN")))


def find_blender():
    for cand in (os.environ.get("STJ_BLENDER"), shutil.which("blender"),
                 r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"):
        if cand and Path(cand).is_file():
            return cand
    return None


@unittest.skipUnless(find_blender(), "Blender not found (set STJ_BLENDER)")
class InBlender(unittest.TestCase):
    """Builds the reference .blend, lints it, exports it and checks the result."""

    def run_blender(self, *args):
        return subprocess.run([find_blender(), "-b", "--factory-startup", *args], capture_output=True, text=True, timeout=300)

    def test_reference_blend_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_blender("--python", str(ROOT / "examples" / "make_blender_reference.py"), "--", d)
            blend = Path(d) / "test_ring_profile.blend"
            self.assertTrue(blend.is_file(), r.stdout[-800:] + r.stderr[-800:])
            r = subprocess.run([find_blender(), "-b", str(blend), "--python", str(ROOT / "tools" / "blender" / "stj_blender.py"),
                                "--", "lint"], capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stdout[-800:])
            self.assertIn("0 error(s)", r.stdout)
            r = subprocess.run([find_blender(), "-b", str(blend), "--python", str(ROOT / "tools" / "blender" / "stj_blender.py"),
                                "--", "export", str(Path(d) / "out"), "ring"], capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stdout[-800:])
            doc = json.loads((Path(d) / "out" / "ring.stj.json").read_text(encoding="utf-8"))
            self.assertEqual(len(doc["reference"]["centerline"]["points"]), 36)
            self.assertTrue(doc["reference"]["centerline"]["closed"])
            self.assertAlmostEqual(doc["timing"]["start_finish"]["s"], 150.0, delta=0.5)
            self.assertEqual([g["position"] for g in doc["race"]["grid"]], [1, 2, 3, 4])
            if core.have_pxr():
                self.assertEqual(core.load_document(Path(d) / "out" / "ring.usd"), doc)        # the document is in the USD


if __name__ == "__main__":
    unittest.main()
