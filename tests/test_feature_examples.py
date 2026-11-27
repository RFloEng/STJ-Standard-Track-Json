"""The small feature examples (examples/features/) give the results written in expected_queries.json.
Run: python -m pytest tests/test_feature_examples.py"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import stj_core as core  # noqa: E402
import stj_query  # noqa: E402
import stj_validate  # noqa: E402

DIR = ROOT / "examples" / "features"
EXPECTED = json.loads((DIR / "expected_queries.json").read_text(encoding="utf-8"))
# the one warning these files are meant to raise
EXPECTED_WARNINGS = {"surface_maps_yup.usda": ("upAxis", "metersPerUnit")}


def load(name):
    doc, chain = core.resolve(DIR / name)
    return doc, chain[0].parent


@unittest.skipUnless(core.have_pxr(), "needs pxr")
class FeatureExamples(unittest.TestCase):
    def test_every_file_validates(self):
        files = sorted(DIR.glob("*.usda")) + sorted(DIR.glob("*.stj.json"))
        self.assertGreaterEqual(len(files), 7)
        for f in files:
            rep = stj_validate.validate(f)
            errors = [f"{p}: {m}" for level, p, m in rep.items if level == "ERROR"]
            warns = [f"{p}: {m}" for level, p, m in rep.items if level == "WARN"
                     and not any(word in m for word in EXPECTED_WARNINGS.get(f.name, ()))]
            self.assertEqual(errors + warns, [], f.name)

    def test_surfaces(self):
        queries = {}
        for case in EXPECTED["surfaces"]:
            with self.subTest(file=case["file"], x=case["x"], y=case["y"]):
                if case["file"] not in queries:
                    queries[case["file"]] = stj_query.SurfaceQuery(*load(case["file"]))
                got = queries[case["file"]].at(case["x"], case["y"])
                self.assertEqual(got["level"], case["level"])
                contact = dict(got["contact"])
                self.assertEqual(set(contact), set(case["contact"]))
                for sid, weight in case["contact"].items():
                    self.assertAlmostEqual(contact[sid], weight, delta=1e-5)
                if "height" in case:
                    if case["height"] is None:
                        self.assertIsNone(got["height"])
                    else:
                        self.assertAlmostEqual(got["height"], case["height"], delta=1e-5)

    def test_grip(self):
        for case in EXPECTED["grip"]:
            with self.subTest(file=case["file"], x=case["x"]):
                doc, base = load(case["file"])
                contact = stj_query.SurfaceQuery(doc, base).at(case["x"], case["y"])["contact"]
                water = doc["environment"]["default_weather"]["water_depth"]
                self.assertAlmostEqual(water, case["water_depth"])
                film = core.FilmQuery(doc, base).depth(contact, case["x"], case["y"], water)
                self.assertAlmostEqual(film, case["film_depth"], delta=1e-7)
                grip = core.contact_grip(doc, contact, film=film)
                for factor, value in case["lambda"].items():
                    self.assertAlmostEqual(grip["lambda"][factor], value, delta=1e-5)

    def test_weather_selection(self):
        case = EXPECTED["weather_selection"]
        doc, base = load(case["file"])
        self.assertEqual(doc["environment"]["default_weather"]["water_depth"], case["base_water_depth"])
        self.assertIn(case["option"], [o.get("variant") for o in doc["environment"]["weather_options"]])
        variant = next(v for v in doc["variants"] if v["id"] == case["option"])
        self.assertEqual(variant["override"], case["override"])
        merged, _base = load(variant["override"])
        self.assertEqual(merged["environment"]["default_weather"]["water_depth"], case["water_depth"])

    def test_opencrg(self):
        for case in EXPECTED["opencrg"]:
            with self.subTest(s=case["s"], t=case["t"]):
                doc, base = load(case["file"])
                entry = next(c for c in doc["geometry"]["crg"] if c["id"] == case["crg"])
                got = stj_query.crg_lookup(entry, stj_query.CrgGrid(base / entry["uri"]), case["s"], case["t"])
                if case["dz"] is None:
                    self.assertIsNone(got)
                    continue
                for key in ("u", "v", "dz"):
                    self.assertAlmostEqual(got[key], case[key], delta=1e-6)

    def test_the_two_up_axes(self):
        self.assertEqual(stj_query.to_stj((100, 200, -300), "Y", 0.01), (1.0, 3.0, 2.0))
        self.assertEqual(stj_query.to_stj((1, 2, 3)), (1.0, 2.0, 3.0))
        with self.assertRaises(ValueError):
            stj_query.to_stj((1, 2, 3), "X")


if __name__ == "__main__":
    unittest.main()
