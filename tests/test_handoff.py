"""Tests for the v0.4 handoff additions: conformance profiles, surface function and quality, route policy,
pacenote sets, position references, override ops, the canonicalizer and the migrator."""

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import canonicalize  # noqa: E402
import migrate  # noqa: E402
import stj_core as core  # noqa: E402
import validate  # noqa: E402

EX = ROOT / "examples"
GP = EX / "test_ring_gp.usda"
STAGE = EX / "coll_de_prova_gravel.usda"


def run(doc):
    with tempfile.NamedTemporaryFile("w", suffix=".stj.json", dir=EX, delete=False, encoding="utf-8") as f:
        json.dump(doc, f)
        name = f.name
    try:
        return validate.validate(name)
    finally:
        Path(name).unlink()


def messages(rep, level):
    return [f"{p}: {m}" for lv, p, m in rep.items if lv == level]


class Base(unittest.TestCase):
    def setUp(self):
        self.gp = core.load_document(GP)
        self.stage = core.load_document(STAGE)

    def errors(self, doc):
        return [m for m in messages(run(doc), "ERROR") if not m.startswith("variants[")]

    def has(self, found, fragment):
        self.assertTrue(any(fragment in m for m in found), f"no {fragment!r} in {found}")


class Conformance(Base):
    def test_examples_meet_their_profiles(self):
        self.gp["_metadata"]["conformance"] = ["core", "race"]
        rep = run(self.gp)
        self.assertEqual([m for m in messages(rep, "ERROR") if not m.startswith("variants[")], [])
        self.has(messages(rep, "NOTE"), "meets: core, race")
        self.stage["_metadata"]["conformance"] = ["core", "rally"]
        self.assertEqual(self.errors(self.stage), [])

    def test_missing_pieces_are_errors(self):
        self.gp["_metadata"]["conformance"] = ["race"]
        del self.gp["race"]["grid"]
        self.has(self.errors(self.gp), "'race' needs race.grid")
        self.stage["_metadata"]["conformance"] = ["core"]
        del self.stage["reference"]
        self.has(self.errors(self.stage), "'core' needs reference.centerline")

    def test_physics_needs_surface_library_and_default(self):
        self.gp["_metadata"]["conformance"] = ["physics"]
        del self.gp["surfaces"]["default"]
        self.has(self.errors(self.gp), "surfaces.default")

    def test_unknown_profile_is_a_schema_error(self):
        self.gp["_metadata"]["conformance"] = ["fast"]
        self.assertTrue(self.errors(self.gp))


class SurfaceFunctionAndQuality(Base):
    def test_function_and_quality(self):
        sid = next(iter(self.gp["surfaces"]["library"]))
        self.gp["surfaces"]["library"][sid]["function"] = "driving"
        self.gp["surfaces"]["library"][sid]["quality"] = {"basis": "measured", "confidence": 0.8, "method": "skid pad"}
        self.assertEqual(self.errors(self.gp), [])

    def test_bad_function(self):
        sid = next(iter(self.gp["surfaces"]["library"]))
        self.gp["surfaces"]["library"][sid]["function"] = "fast"
        self.assertTrue(self.errors(self.gp))

    def test_measured_with_est_warns(self):
        sid = next(iter(self.gp["surfaces"]["library"]))
        surf = self.gp["surfaces"]["library"][sid]
        surf["quality"] = {"basis": "measured"}
        surf["_est"] = "guess"
        self.has(messages(run(self.gp), "WARN"), "measured, but")


class RoutePolicyAndPacenoteSets(Base):
    def test_route_policy(self):
        self.assertTrue(self.stage.get("routes") or True)
        self.stage.setdefault("routes", [{"id": "main", "steps": [{"road": "reference"}]}])
        self.stage["race"]["route_policy"] = {"default": "main", "by_session": {"stage": "main"}}
        self.assertEqual(self.errors(self.stage), [])
        self.stage["race"]["route_policy"]["by_session"]["race"] = "nope"
        self.has(self.errors(self.stage), "unknown route 'nope'")

    def test_pacenote_sets(self):
        notes = copy.deepcopy(self.stage["race"]["pacenotes"]["notes"])
        self.stage["race"]["pacenote_sets"] = [
            {"id": "wrc", "vehicle_class": "rally1", "language": "en", "notes": notes},
            {"id": "wrc", "notes": notes}]
        self.has(self.errors(self.stage), "duplicate id 'wrc'")
        self.stage["race"]["pacenote_sets"][1]["id"] = "club"
        self.assertEqual(self.errors(self.stage), [])
        self.stage["race"]["pacenote_sets"][1]["notes"] = [{"s": 10.0, "kind": "turn"}, {"s": 5.0, "kind": "turn"}]
        self.has(self.errors(self.stage), "race.pacenote_sets[1].notes[1].s")

    def test_racing_line_vehicle_class(self):
        self.gp["race"]["racing_lines"][0]["vehicle_class"] = "gt3"
        self.assertEqual(self.errors(self.gp), [])


class PositionRefs(Base):
    def cam(self, ref):
        self.stage["cameras"] = {"sets": [{"id": "tv", "cameras": [
            {"id": "c1", "kind": "static", "look_at": [0, 0, 0], "position_ref": ref}]}]}
        return self.errors(self.stage)

    def test_road_and_world_refs(self):
        self.assertEqual(self.cam({"reference": "road:reference", "s": 10.0, "t": 3.0, "z": 5.0}), [])
        self.assertEqual(self.cam({"reference": "world", "x": 1.0, "y": 2.0, "z": 3.0}), [])

    def test_bad_refs(self):
        self.has(self.cam({"reference": "road:nope", "s": 1.0}), "unknown road")
        self.has(self.cam({"reference": "route:nope", "s": 1.0}), "unknown route")
        self.has(self.cam({"reference": "world", "x": 1.0}), "world needs x and y")
        self.assertTrue(self.cam({"reference": "somewhere", "s": 1.0}))

    def test_resolution(self):
        doc = {"reference": {"centerline": {"points": [[0, 0, 0], [100, 0, 0]]}}}
        x, y, z = core.resolve_position(doc, {"reference": "road:reference", "s": 40.0, "t": 2.0, "z": 1.5})
        self.assertAlmostEqual(x, 40.0)
        self.assertAlmostEqual(y, 2.0)
        self.assertAlmostEqual(z, 1.5)
        self.assertEqual(core.resolve_position(doc, {"reference": "road:nope", "s": 0}), None)

    def test_emitter_with_position_ref(self):
        self.stage["audio"] = {"emitters": [{"id": "crowd1", "kind": "crowd", "max_distance": 80,
                                             "x_game": {"event": "crowd"},
                                             "position_ref": {"reference": "road:reference", "s": 20.0, "t": -6.0}}]}
        self.assertEqual(self.errors(self.stage), [])


class Markings(Base):
    def marks(self, *ms):
        self.stage["markings"] = list(ms)
        return self.errors(self.stage)

    LINE = {"id": "centre", "kind": "centre_line", "s_start": 10.0, "s_end": 90.0, "t": 0.0, "style": "dashed",
            "dash": {"length": 3.0, "gap": 6.0}, "colour": "yellow", "width": 0.12}
    PATCH = {"id": "zebra", "kind": "crosswalk", "s_start": 50.0, "s_end": 53.0, "t_min": -3.5, "t_max": 3.5, "style": "zebra"}

    def test_valid_markings_and_road_fields(self):
        self.assertEqual(self.marks(self.LINE, self.PATCH), [])
        self.stage["roads"][0].update({"road_class": "residential", "speed_limit": 8.3, "lanes": 2, "oneway": False})
        self.assertEqual(self.errors(self.stage), [])

    def test_geometry_rules(self):
        self.has(self.marks({**self.LINE, "t_min": -1.0, "t_max": 1.0}), "not both")
        self.has(self.marks({**self.PATCH, "t_min": 2.0, "t_max": 1.0}), "t_min must be smaller")
        self.has(self.marks({"id": "x", "kind": "centre_line", "s_start": 0.0, "s_end": 5.0}), "")        # schema: no t
        self.has(self.marks(self.LINE, self.LINE), "duplicate marking id")
        self.has(self.marks({**self.LINE, "road": "nope"}), "unknown road")
        self.has(self.marks({**self.LINE, "s_end": 1e6}), "beyond")
        self.has(self.marks({**self.LINE, "surface": "nope"}), "unknown surface")

    def test_kind_warnings(self):
        rep = run({**self.stage, "markings": [{**self.PATCH, "kind": "centre_line"}, {"id": "a", "kind": "arrow", "s_start": 1.0,
                                                                                     "s_end": 3.0, "t_min": -1.0, "t_max": 1.0}]})
        warns = messages(rep, "WARN")
        self.has(warns, "a centre_line is a line")
        self.has(warns, "an arrow needs a direction")

    def test_speed_limit_in_ms(self):
        self.stage["roads"][0]["speed_limit"] = 90.0
        self.has(messages(run(self.stage), "WARN"), "speeds are in m/s")


class BuildingParts(Base):
    SQUARE = [[0, 0], [20, 0], [20, 10], [0, 10]]

    def setUp(self):
        super().setUp()
        self.stage["buildings"] = [{"id": "hall", "footprint": self.SQUARE, "height": 8.0,
                                    "address": {"housenumber": "4", "street": "Carrer Major", "city": "Coll", "country": "ES"}}]

    def test_address_and_parts(self):
        self.stage["buildings"][0]["parts"] = [{"id": "tower", "footprint": [[2, 2], [8, 2], [8, 8], [2, 8]], "z": 8.0, "height": 20.0}]
        self.assertEqual(self.errors(self.stage), [])

    def test_floors_and_spaces(self):
        self.stage["race"]["pit_boxes"] = [{"id": "box1", "pose": {"s": 20.0, "t": 5.0}}]
        b = self.stage["buildings"][0]
        b["floors"] = [{"id": "g", "index": 0, "z": 0.0, "height": 4.0, "spaces": [
            {"id": "garage1", "class": "garage", "polygon": [[1, 1], [9, 1], [9, 9], [1, 9]], "vehicle_access": True, "pit_box": "box1"},
            {"id": "tower", "class": "control", "polygon": [[10, 1], [19, 1], [19, 9], [10, 9]]}]}]
        self.assertEqual(self.errors(self.stage), [])
        b["floors"][0]["spaces"][0]["pit_box"] = "nope"
        b["floors"].append({"id": "g2", "index": 0})
        b["floors"][0]["spaces"][1]["id"] = "garage1"
        b["floors"][0]["spaces"][1]["polygon"] = [[10, 1], [40, 1], [40, 9]]
        rep = run(self.stage)
        errs = messages(rep, "ERROR")
        self.has(errs, "unknown pit box 'nope'")
        self.has(errs, "duplicate space id 'garage1'")
        self.has(messages(rep, "WARN"), "two floors with index 0")
        self.has(messages(rep, "WARN"), "reaches outside the building's footprint")

    def test_part_findings(self):
        b = self.stage["buildings"][0]
        b["parts"] = [{"id": "a", "footprint": [[15, 2], [30, 2], [30, 8], [15, 8]], "height": 5.0},
                      {"id": "a", "footprint": [[1, 1], [2, 1], [2, 2]]}]
        rep = run(self.stage)
        self.has(messages(rep, "ERROR"), "duplicate building part id 'a'")
        self.has(messages(rep, "WARN"), "reaches outside the building's footprint")
        self.has(messages(rep, "NOTE"), "no height or levels")


class Portals(Base):
    def setUp(self):
        super().setUp()
        self.st = {"id": "tun", "kind": "tunnel", "s_start": 100.0, "s_end": 160.0, "clearance": 5.0}
        self.stage["structures"] = [self.st]

    def test_portals_and_walls(self):
        self.st["portals"] = {"start": {"style": "arch", "height": 5.5}, "end": {"style": "flat"}}
        self.stage["edges"] = [{"id": "wall1", "side": "left", "s_start": 10.0, "s_end": 50.0, "kind": "barrier",
                                "style": "retaining_wall", "height": 2.0}]
        self.assertEqual(self.errors(self.stage), [])
        self.assertNotIn("is not a barrier style", " ".join(messages(run(self.stage), "WARN")))

    def test_portal_findings(self):
        self.st["kind"] = "bridge"
        self.st["portals"] = {"start": {"style": "arch"}}
        self.has(messages(run(self.stage), "WARN"), "portals belong to a tunnel")
        self.st["kind"] = "tunnel"
        self.st["portals"] = {"end": {"height": 3.0, "mesh": {"mesh_ref": "nope"}}}
        rep = run(self.stage)
        self.has(messages(rep, "WARN"), "lower than the clearance")
        self.has([m for m in messages(rep, "ERROR")], "unknown mesh 'nope'")


class OverrideOps(unittest.TestCase):
    DOC = {"edges": [{"id": "a", "kind": "kerb"}, {"id": "b", "kind": "wall"}], "race": {"grid": [{"position": 1}]}}

    def test_each_op(self):
        out = core.apply_ops(self.DOC, [
            {"op": "update", "target": "edges[id=a]", "value": {"kind": "rumble"}},
            {"op": "replace", "target": "edges[id=b]", "value": {"id": "b", "kind": "fence"}},
            {"op": "add", "target": "edges", "value": {"id": "c", "kind": "wall"}},
            {"op": "remove", "target": "race.grid[position=1]"}])
        self.assertEqual(out["edges"], [{"id": "a", "kind": "rumble"}, {"id": "b", "kind": "fence"}, {"id": "c", "kind": "wall"}])
        self.assertEqual(out["race"]["grid"], [])
        self.assertEqual(self.DOC["edges"][0]["kind"], "kerb")        # the input is untouched

    def test_bad_targets(self):
        for op in ({"op": "remove", "target": "edges[id=zz]"}, {"op": "remove", "target": "edges"},
                   {"op": "update", "target": "nothing[id=a]", "value": {}}, {"op": "add", "target": "edges[id=a]"},
                   {"op": "remove", "target": "bad target"}):
            with self.assertRaises(core.StjLoadError, msg=op):
                core.apply_ops(self.DOC, [op])

    def test_override_file_uses_ops(self):
        base = core.load_document(STAGE)
        base["edges"] = [{"id": "kerb_t1", "side": "left", "s_start": 10, "s_end": 20, "kind": "kerb"}]
        with tempfile.TemporaryDirectory(dir=EX) as d:
            d = Path(d)
            (d / "base.stj.json").write_text(json.dumps(base), encoding="utf-8")
            (d / "wet.stj-override.json").write_text(json.dumps({
                "_metadata": {"specification": "STJ-OVERRIDE", "version": "0.3", "base": "base.stj.json"},
                "patch": {},
                "ops": [{"op": "update", "target": "edges[id=kerb_t1]", "value": {"kind": "wall"}}]}), encoding="utf-8")
            doc, chain = core.resolve(d / "wet.stj-override.json")
            self.assertEqual(doc["edges"][0]["kind"], "wall")
            self.assertEqual(len(chain), 2)


class Canonical(unittest.TestCase):
    def test_stable_and_equal(self):
        doc = {"x_a": 1, "zeta": [1.0, 2.5, -0.0], "_note": "n", "name": "n", "id": "i",
               "_metadata": {"version": "0.3"}, "alpha": {"points": [[0.0, 1.0, 2.0], [3, 4, 5]]}}
        text = canonicalize.canonical_text(doc)
        self.assertEqual(list(json.loads(text)), ["_metadata", "id", "name", "alpha", "zeta", "_note", "x_a"])
        self.assertEqual(json.loads(text)["zeta"], [1, 2.5, 0])
        self.assertEqual(canonicalize.canonical_text(json.loads(text)), text)
        self.assertTrue(text.endswith("}\n"))
        self.assertIn("[0, 1, 2]", text)

    def test_keeps_the_data(self):
        for path in (GP, STAGE):
            doc = core.load_document(path)
            self.assertEqual(json.loads(canonicalize.canonical_text(doc)), doc)

    def test_check_flag(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "a.stj.json"
            f.write_text('{"b": 1, "a": 2}', encoding="utf-8")
            self.assertEqual(canonicalize.main(["--check", str(f)]), 1)
            canonicalize.main(["--write", str(f)])
            self.assertEqual(canonicalize.main(["--check", str(f)]), 0)


class Migrate(unittest.TestCase):
    def test_version_steps(self):
        doc = {"_metadata": {"specification": "STJ", "version": "0.1"}}
        out, notes = migrate.migrate(doc)
        self.assertEqual(out["_metadata"]["version"], "0.3")
        self.assertEqual(doc["_metadata"]["version"], "0.1")
        self.assertEqual(len(notes), 2)
        self.assertEqual(migrate.migrate(doc, "0.2")[0]["_metadata"]["version"], "0.2")

    def test_bad_requests(self):
        with self.assertRaises(ValueError):
            migrate.migrate({"_metadata": {"version": "0.3"}}, "0.1")
        with self.assertRaises(ValueError):
            migrate.migrate({"_metadata": {"version": "9.9"}})

    def test_dry_run_writes_nothing_and_shows_the_change(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "a.stj.json"
            f.write_text(json.dumps({"_metadata": {"specification": "STJ", "version": "0.2"}}), encoding="utf-8")
            before = f.read_text(encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(migrate.main([str(f), "--dry-run"]), 0)
            self.assertEqual(f.read_text(encoding="utf-8"), before)
            self.assertIn("would become 0.3", buf.getvalue())
            self.assertIn('"version": "0.3"', buf.getvalue())


class DiagnosticsJson(unittest.TestCase):
    def test_json_pointer_from_a_dotted_path(self):
        self.assertEqual(validate.json_pointer("roads[0].centerline"), "/roads/0/centerline")
        self.assertEqual(validate.json_pointer("timing.sectors"), "/timing/sectors")
        self.assertEqual(validate.json_pointer("race.grid[2] (p3).pose"), "/race/grid/2/pose")
        self.assertEqual(validate.json_pointer("(override)"), "")
        self.assertEqual(validate.json_pointer("a.b with spaces.c"), "/a")

    def test_the_json_output_has_severity_path_pointer_and_message(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "bad.stj.json"
            f.write_text(json.dumps({"_metadata": {"specification": "STJ", "version": "0.3", "coordinate_system": "OpenDRIVE", "units": "SI"},
                                     "layouts": [{"id": "bad", "route": "nope", "direction": "reverse"}]}), encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = validate.main([str(f), "--json"])
            out = json.loads(buf.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(out["result"], "FAIL")
        self.assertEqual(out["errors"], sum(1 for x in out["diagnostics"] if x["severity"] == "ERROR"))
        for x in out["diagnostics"]:
            self.assertEqual(set(x), {"severity", "path", "pointer", "message"})
            self.assertTrue(x["pointer"] == "" or x["pointer"].startswith("/"))
        routes = [x for x in out["diagnostics"] if "route" in x["path"] and x["severity"] == "ERROR"]
        self.assertTrue(routes and routes[0]["pointer"].startswith("/layouts/0"))     # the invalid layout of spec §2.1

    def test_a_clean_file_gives_an_empty_list(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(validate.main([str(GP), "--json", "--strict"]), 0)
        self.assertEqual(json.loads(buf.getvalue())["diagnostics"], [])


class ConversionReport(unittest.TestCase):
    def test_entries_counts_and_lost(self):
        r = core.ConversionReport("dr2_to_stj", "stage.xml", "stage.stj.json", "1.0")
        r.add("mapped", "/roads/0", "carried over").add("dropped", "/scenery/trees/3", "species 'palm' has no equivalent")
        r.add("baked", "", "two layers baked to one map")
        self.assertEqual(r.counts()["dropped"], 1)
        self.assertEqual(r.lost(), ["/scenery/trees/3: species 'palm' has no equivalent", "two layers baked to one map"])
        d = r.to_dict()
        self.assertEqual((d["tool"], d["tool_version"], len(d["entries"])), ("dr2_to_stj", "1.0", 3))
        json.dumps(d)
        with self.assertRaises(ValueError):
            r.add("lost", "", "x")

    def test_lost_fits_provenance(self):
        lost = core.ConversionReport("t").add("dropped", "/x", "y").lost()
        doc = {"_metadata": {"specification": "STJ", "version": "0.3", "provenance": {"conversion": {"lost": lost}}}}
        self.assertTrue(all(isinstance(m, str) for m in doc["_metadata"]["provenance"]["conversion"]["lost"]))



class SectionReferences(unittest.TestCase):
    def test_every_section_reference_outside_the_spec_resolves(self):
        import re
        spec = (ROOT / "spec" / "STJ_Spec.md").read_text(encoding="utf-8")
        heads = set(re.findall(r"^#{2,3} (\d+(?:\.\d+)?)[. ]", spec, re.M))
        files = [ROOT / "README.md", ROOT / "CHANGELOG.md", ROOT / "docs" / "consistency_audit.md", ROOT / "docs" / "interoperability.md",
                 ROOT / "docs" / "best_practices.md", ROOT / "tools" / "validate.py", ROOT / "tools" / "stj_core.py", ROOT / "tools" / "migrate.py"]
        for f in files:
            for ref in re.findall(r"(?<!SVJ )(?<!SVJ_Spec )(?<!profile )§(\d+(?:\.\d+)?)", f.read_text(encoding="utf-8")):
                self.assertIn(ref, heads, f"{f.name}: §{ref}")


if __name__ == "__main__":
    unittest.main()
