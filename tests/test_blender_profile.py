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
sys.path.insert(0, str(ROOT / "examples"))
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


def with_places(doc):
    """The stage example with names, tags, a source, a building and an area (spec §7.9)."""
    doc["roads"][0].update({"name": "Carrer Major", "ref": "BV-1", "tags": {"highway": "residential"},
                            "source": {"id": "osm", "osm_id": "way/1"}})
    square = [[0.0, 0.0], [20.0, 0.0], [20.0, 10.0], [0.0, 10.0]]
    doc["buildings"] = [{"id": "hall", "name": "Ajuntament", "class": "public", "footprint": square,
                         "holes": [[[5.0, 3.0], [8.0, 3.0], [8.0, 6.0], [5.0, 6.0]]], "z": 12.5, "height": 12.0,
                         "tags": {"building": "civic", "addr:street": "Carrer Major"},
                         "address": {"street": "Carrer Major", "housenumber": "1"},
                         "floors": [{"id": "g", "index": 0, "spaces": [{"id": "hall1", "class": "other", "polygon": square}]}]}]
    doc["areas"] = [{"id": "square", "class": "park", "name": "Placa", "polygon": square}]
    doc["water"] = {"bodies": [{"id": "pond", "kind": "pond", "outline": [[0.0, 0.0], [5.0, 0.0], [5.0, 5.0]]}]}
    doc["marshals"] = {"posts": [{"id": "p1", "kind": "marshal", "position": [1.0, 2.0, 3.0]}],
                       "sectors": [{"id": "s1", "s_start": 0.0, "s_end": 50.0}]}
    doc["roads"][0].update({"road_class": "residential", "speed_limit": 8.3, "lanes": 2})
    doc["markings"] = [{"id": "centre", "kind": "centre_line", "s_start": 10.0, "s_end": 90.0, "t": 0.0, "style": "dashed",
                        "dash": {"length": 3.0, "gap": 6.0}, "colour": "yellow"},
                       {"id": "zebra", "kind": "crosswalk", "s_start": 50.0, "s_end": 53.0, "t_min": -3.5, "t_max": 3.5,
                        "style": "zebra"}]
    doc["geometry"]["chunks"] = [{"id": "c1", "s_start": 0.0, "s_end": 400.0, "origin": [10.0, 20.0, 0.0], "meshes": []}]
    doc["geometry"]["tiles"] = {"size": 256.0, "origin": [0.0, 0.0, 0.0], "items": [{"index": [0, 0], "meshes": []}]}
    doc["dynamic"] = {"track_temperature": {"tau": 600.0}}
    doc["environment"]["probes"] = [{"id": "pr", "kind": "box", "position": [1.0, 1.0, 1.0]}]
    return doc


class KeepExamples:
    """make_examples writes the example PNGs when a document is built; put the files back as they were."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._saved = {p: p.read_bytes() for p in (ROOT / "examples").rglob("*.png")}

    @classmethod
    def tearDownClass(cls):
        for p, data in cls._saved.items():
            if p.read_bytes() != data:
                p.write_bytes(data)
        super().tearDownClass()


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


class DocumentToScene(KeepExamples, unittest.TestCase):
    """Import: a document becomes a scene description, and the scene gives the document back."""

    def doc(self):
        import make_examples
        return make_examples.test_ring()

    def test_round_trip_of_the_test_ring_is_exact(self):
        doc = self.doc()
        back = profile.apply_scene(profile.scene_from_document(doc))
        for key in ("reference", "timing", "race", "surfaces", "environment"):
            self.assertEqual(back[key], doc[key], key)
        self.assertEqual(back, doc)

    def test_a_moved_object_overrides_the_stored_pose_and_gate(self):
        desc = profile.scene_from_document(self.doc())
        grid1 = next(o for o in desc["objects"] if o["name"] == "STJ::grid::1")
        grid1["location"][0] += 3.0
        gate = next(o for o in desc["objects"] if o["name"] == "STJ::timing::start_finish")
        gate["location"][0] += 3.0
        back = profile.apply_scene(desc)
        self.assertIn("position", back["race"]["grid"][0]["pose"])          # a world pose now
        self.assertNotEqual(back["timing"]["start_finish"]["s"], 150.0)

    def test_every_example_document_round_trips_exactly(self):
        import make_examples
        for name in ("test_ring", "test_ring_gp", "coll_de_prova"):
            doc = getattr(make_examples, name)()
            self.assertEqual(profile.apply_scene(profile.scene_from_document(doc)), doc, name)

    def test_terrain_becomes_a_grid_and_back(self):
        import make_examples
        doc = make_examples.coll_de_prova()
        desc = profile.scene_from_document(doc, ROOT / "examples")
        terr = next(o for o in desc["objects"] if o["name"].startswith("STJ::terrain::"))
        nx, ny = doc["geometry"]["terrain"]["heightmap"]["size"]
        self.assertEqual(len(terr["points"]), nx * ny)
        self.assertNotIn("terrain", json.loads(desc["texts"]["track.stj.json"]).get("geometry", {}))
        self.assertEqual(profile.apply_scene(desc), doc)                       # untouched: the entry as it was
        self.assertEqual(profile.terrain_files(desc), [])
        terr["points"][5][2] += 2.0                                             # sculpt one vertex
        back = profile.apply_scene(desc)
        hm = back["geometry"]["terrain"]["heightmap"]
        self.assertNotIn("nodata", hm)
        self.assertEqual(back["geometry"]["terrain"]["layers"], doc["geometry"]["terrain"]["layers"])
        (uri, data), = profile.terrain_files(desc)
        self.assertEqual(uri, doc["geometry"]["terrain"]["heightmap"]["uri"])
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(ROOT / "examples" / "terrain", Path(d) / "terrain")
            (Path(d) / uri).write_bytes(data)
            t = core.Terrain(back["geometry"]["terrain"], d)
            x, y, z = terr["points"][5]
            self.assertAlmostEqual(t.height(x, y), z, delta=(hm["height_max"] - hm["height_min"]) / 65535 + 1e-6)

    def test_ground_sky_and_screens(self):
        import make_examples
        doc = make_examples.coll_de_prova()
        desc = profile.scene_from_document(doc)
        names = {o["name"] for o in desc["objects"]}
        for want in ("STJ::ground_layer::stage_gravel", "STJ::ground_material::stage_ground_0", "STJ::sky::sky"):
            self.assertIn(want, names)
        self.assertNotIn("sky", json.loads(desc["texts"]["track.stj.json"]).get("environment", {}))
        sky = next(o for o in desc["objects"] if o["name"] == "STJ::sky::sky")
        sky["props"]["stj"]["turbidity"] = 4.0                                  # an edit in the property
        self.assertEqual(profile.apply_scene(desc)["environment"]["sky"]["turbidity"], 4.0)
        gp = profile.scene_from_document(make_examples.test_ring_gp())
        self.assertIn("STJ::screen::main_screen", {o["name"] for o in gp["objects"]})

    def test_racing_lines_and_ford_paths(self):
        import make_examples
        doc = make_examples.coll_de_prova()
        desc = profile.scene_from_document(doc)
        line = next(o for o in desc["objects"] if o["name"] == "STJ::line::race")
        ford = next(o for o in desc["objects"] if o["name"] == "STJ::water::ford_ss1")
        self.assertEqual((line["type"], ford["type"]), ("CURVE", "CURVE"))
        line["points"][3][1] += 1.0                                              # nudge the racing line
        back = profile.apply_scene(desc)["race"]["racing_lines"][0]["points"]
        self.assertAlmostEqual(back[3][1], doc["race"]["racing_lines"][0]["points"][3][1] + 1.0, places=3)
        ford["points"][0][2] += 0.1
        path = profile.apply_scene(desc)["water"]["bodies"][0]["path"]
        self.assertEqual(path[0][3:], doc["water"]["bodies"][0]["path"][0][3:])      # width and depth stay
        line["props"]["stj"]["speed"] = [10.0]
        self.assertTrue(any(l == "WARN" and "speed has 1 values" in m for l, _p, m in profile.lint_scene(desc)))

    def test_pit_lane_path_is_a_curve(self):
        import make_examples
        doc = make_examples.test_ring_gp()
        desc = profile.scene_from_document(doc)
        lane = next(o for o in desc["objects"] if o["name"] == "STJ::pit_lane::pit_lane")
        self.assertEqual(lane["type"], "CURVE")
        self.assertEqual(profile.apply_scene(desc), doc)
        lane["points"][2][1] += 1.5
        out = profile.apply_scene(desc)["timing"]["pit_lane"]
        self.assertEqual(out["path"][2][1], doc["timing"]["pit_lane"]["path"][2][1] + 1.5)
        self.assertEqual(out["limit_start"], doc["timing"]["pit_lane"]["limit_start"])

    def test_prototype_body_changes_only_what_moved(self):
        import make_examples
        doc = make_examples.coll_de_prova()
        desc = profile.scene_from_document(doc)
        body = next(o for o in desc["objects"] if o["name"] == "STJ::prototype::hay_bale::body")
        self.assertEqual(body["rigid_body"]["type"], "ACTIVE")
        self.assertEqual(body["dimensions"], [1.5, 1.5, 1.2])
        self.assertEqual(profile.apply_scene(desc), doc)
        body["rigid_body"]["mass"] = 300.0
        phys = profile.apply_scene(desc)["scenery"]["prototypes"]["hay_bale"]["physics"]
        self.assertEqual((phys["mass"], phys["mode"]), (300.0, "movable"))
        body["rigid_body"]["type"] = "PASSIVE"                                   # a passive body is static
        phys = profile.apply_scene(desc)["scenery"]["prototypes"]["hay_bale"]["physics"]
        self.assertEqual(phys["mode"], "static")
        self.assertEqual(phys["shape"], doc["scenery"]["prototypes"]["hay_bale"]["physics"]["shape"])
        body["dimensions"][2] = 2.0
        self.assertEqual(profile.apply_scene(desc)["scenery"]["prototypes"]["hay_bale"]["physics"]["shape"]["height"], 2.0)
        desc["objects"].append({"name": "STJ::prototype::hay_bale::oops", "type": "EMPTY", "location": [0, 0, 0],
                                "heading": 0, "collections": ["STJ"], "props": {}})
        self.assertTrue(any(l == "ERROR" and "unknown part" in m for l, _p, m in profile.lint_scene(desc)))

    def test_surfaces_in_materials_and_the_last_records(self):
        import make_examples
        doc = make_examples.coll_de_prova()
        desc = profile.scene_from_document(doc)
        mat = next(m for m in desc["materials"] if m["name"] == "STJ::surface::gravel_loose")
        self.assertEqual(mat["props"]["stj"], doc["surfaces"]["library"]["gravel_loose"])
        self.assertNotIn("gravel_loose", json.loads(desc["texts"]["track.stj.json"]).get("surfaces", {}).get("library", {}))
        mat["props"]["stj"]["rolling_resistance"] = 0.07                          # edited on the material
        back = profile.apply_scene(desc)
        self.assertEqual(back["surfaces"]["library"]["gravel_loose"]["rolling_resistance"], 0.07)
        self.assertEqual(back["surfaces"]["default"], doc["surfaces"]["default"])
        names = {o["name"] for o in desc["objects"]}
        for want in ("STJ::track_info::track_info", "STJ::layout::ss1_reverse", "STJ::variant::wet"):
            self.assertIn(want, names)
        doc2 = make_examples.coll_de_prova()
        doc2["audio"]["emitters"].append({"id": "river", "kind": "water", "path": [[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]],
                                          "x_game": {"event": "river"}})
        desc2 = profile.scene_from_document(doc2)
        river = next(o for o in desc2["objects"] if o["name"] == "STJ::emitter::river")
        self.assertEqual(river["type"], "CURVE")
        self.assertEqual(profile.apply_scene(desc2), doc2)

    def test_terrain_lint(self):
        import make_examples
        desc = profile.scene_from_document(make_examples.coll_de_prova(), ROOT / "examples")
        terr = next(o for o in desc["objects"] if o["name"].startswith("STJ::terrain::"))
        terr["points"].pop()
        self.assertTrue(any(l == "ERROR" and "vertices" in m for l, _p, m in profile.lint_scene(desc)))

    def test_records_instances_and_emitters(self):
        import make_examples
        doc = make_examples.coll_de_prova()
        desc = profile.scene_from_document(doc)
        names = {o["name"] for o in desc["objects"]}
        self.assertIn("STJ::structure::" + doc["structures"][0]["id"], names)
        self.assertIn("STJ::prototype::scots_pine", names)
        inst = next(o for o in desc["objects"] if o["name"].startswith("STJ::instance::scots_pine"))
        self.assertEqual(len(inst["points"]), len(doc["scenery"]["instances"][0]["transforms"]))
        inst["points"][0][0] += 1.0                                             # move one tree
        back = profile.apply_scene(desc)
        first = back["scenery"]["instances"][0]["transforms"][0]
        self.assertAlmostEqual(first[0], doc["scenery"]["instances"][0]["transforms"][0][0] + 1.0, places=3)
        self.assertEqual(len(first), len(doc["scenery"]["instances"][0]["transforms"][0]))      # scale kept or left out as given

    def test_a_moved_emitter_writes_its_new_position(self):
        import make_examples
        doc = make_examples.test_ring_gp()
        desc = profile.scene_from_document(doc)
        em = next(o for o in desc["objects"] if o["name"].startswith("STJ::emitter::"))
        em["location"][2] += 3.0
        want = doc["audio"]["emitters"][0]["position"][2] + 3.0
        self.assertAlmostEqual(profile.apply_scene(desc)["audio"]["emitters"][0]["position"][2], want, places=3)

    def test_names_tags_buildings_and_areas_round_trip(self):
        import make_examples
        doc = with_places(make_examples.coll_de_prova())
        desc = profile.scene_from_document(doc)
        names = {o["name"] for o in desc["objects"]}
        self.assertIn("STJ::building::hall", names)
        self.assertIn("STJ::area::square", names)
        self.assertEqual(profile.apply_scene(desc), doc)
        names = {o["name"] for o in desc["objects"]}
        for want in ("STJ::water::pond", "STJ::post::p1", "STJ::sector::s1", "STJ::probe::pr", "STJ::scatter::forest_fill"):
            self.assertIn(want, names)
        centre = next(o for o in desc["objects"] if o["name"] == "STJ::marking::centre")
        zebra = next(o for o in desc["objects"] if o["name"] == "STJ::marking::zebra")
        self.assertFalse(centre["cyclic"])
        self.assertEqual((zebra["cyclic"], len(zebra["points"])), (True, 4))
        for p in centre["points"]:
            p[1] += 1.5                                                         # slide the line sideways
        moved = profile.apply_scene(desc)["markings"][0]
        self.assertAlmostEqual(moved["t"], doc["markings"][0]["t"] + 1.5, delta=0.2)
        for p in centre["points"]:
            p[1] -= 1.5
        chunk = next(o for o in desc["objects"] if o["name"] == "STJ::chunk::c1")
        self.assertEqual(chunk["location"], [10.0, 20.0, 0.0])
        chunk["location"][0] += 5.0                                             # a moved chunk writes its origin
        self.assertEqual(profile.apply_scene(desc)["geometry"]["chunks"][0]["origin"][0], 15.0)
        chunk["location"][0] -= 5.0
        self.assertIn("STJ::tiles::tiles", names)
        self.assertIn("STJ::dynamic::dynamic", names)
        pond = next(o for o in desc["objects"] if o["name"] == "STJ::water::pond")
        svc = next(o for o in desc["objects"] if o["name"] == "STJ::service::service_park")
        self.assertEqual((pond["type"], svc["type"]), ("CURVE", "CURVE"))
        pond["points"][1][0] += 2.0                                             # pull a corner of the pond
        self.assertEqual(profile.apply_scene(desc)["water"]["bodies"][0]["outline"][1], [7.0, 0.0])
        pond["points"][1][0] -= 2.0
        probe = next(o for o in desc["objects"] if o["name"] == "STJ::probe::pr")
        probe["location"][0] += 4.0                                             # a moved probe writes its position
        self.assertEqual(profile.apply_scene(desc)["environment"]["probes"][0]["position"][0], 5.0)
        probe["location"][0] -= 4.0
        hall = next(o for o in desc["objects"] if o["name"] == "STJ::building::hall")
        hall["points"][2][0] += 5.0                                         # pull a corner out
        self.assertEqual(profile.apply_scene(desc)["buildings"][0]["footprint"][2], [25.0, 10.0])
        self.assertEqual(profile.apply_scene(desc)["buildings"][0]["holes"], doc["buildings"][0]["holes"])

    def test_moving_a_camera_a_road_and_an_edge(self):
        import make_examples
        doc = make_examples.test_ring_gp()
        desc = profile.scene_from_document(doc)
        cam = next(o for o in desc["objects"] if o["name"].startswith("STJ::camera::"))
        cam["location"][2] += 2.0
        edge = next(o for o in desc["objects"] if o["name"].startswith("STJ::edge::"))
        edge["points"] = [[x, y + 1.0, z] for x, y, z in edge["points"]]
        back = profile.apply_scene(desc)
        first = doc["cameras"]["sets"][0]["cameras"][0]
        self.assertAlmostEqual(back["cameras"]["sets"][0]["cameras"][0]["position"][2], first["position"][2] + 2.0, places=3)
        old = next(e for e in doc["edges"] if f"STJ::edge::{e['id']}" == edge["name"])
        new = next(e for e in back["edges"] if e["id"] == old["id"])
        self.assertNotEqual(new.get("t"), old.get("t"))               # the curve moved sideways: the offset follows it

    def test_the_scene_has_the_profile_names_and_no_errors(self):
        desc = profile.scene_from_document(self.doc())
        names = {o["name"] for o in desc["objects"]}
        self.assertIn("STJ::reference::centerline", names)
        self.assertIn("STJ::timing::start_finish", names)
        self.assertIn("STJ::grid::1", names)
        self.assertEqual({m["name"] for m in desc["materials"]}, {"STJ::surface::asphalt", "STJ::surface::kerb", "STJ::surface::grass"})
        self.assertEqual(levels(profile.lint_scene(desc), "ERROR"), [])
        base = json.loads(desc["texts"][profile.BASE_TEXT])
        self.assertNotIn("points", base["reference"]["centerline"])
        self.assertNotIn("grid", base.get("race", {}))

    def test_what_a_scene_cannot_hold_stays_in_the_text_block(self):
        doc = self.doc()
        doc["timing"]["split_points"] = [{"id": "a", "name": "Named split", "s": 300.0}]
        doc["race"]["spawns"] = [{"id": "free", "pose": {"s": 10.0, "t": 0.0, "x_note": 1}}]
        desc = profile.scene_from_document(doc)
        base = json.loads(desc["texts"][profile.BASE_TEXT])
        self.assertEqual(base["timing"]["split_points"], doc["timing"]["split_points"])
        self.assertEqual(base["race"]["spawns"], doc["race"]["spawns"])
        self.assertEqual(profile.apply_scene(desc)["timing"]["split_points"], doc["timing"]["split_points"])

    def test_tangents_are_kept_for_a_bezier_curve(self):
        doc = self.doc()
        cl = doc["reference"]["centerline"]
        cl["tangents"] = [[10.0, 0.0, 0.0]] * len(cl["points"])
        desc = profile.scene_from_document(doc)
        self.assertEqual(len(desc["objects"][0]["tangents_out"]), len(cl["points"]))
        back = profile.apply_scene(desc)["reference"]["centerline"]
        self.assertEqual(back["tangents"], cl["tangents"])                # given as one per point, written as given
        self.assertNotIn("tangents_out", back)


class PlaceAndSun(KeepExamples, unittest.TestCase):
    """The geo origin (coordinates, height, time, north) and the sun light (spec/STJ_Blender_Profile.md §4)."""

    ENV = {"geo_reference": {"latitude": 41.0, "longitude": 0.0, "altitude": 312.5, "vertical_datum": "EGM2008"},
           "north_heading": 1.2, "timezone": "UTC", "default_time": {"date": "2026-12-21", "local_time": "12:00"}}

    def doc(self):
        d = json.loads(json.dumps(BASE))
        d["environment"] = json.loads(json.dumps(self.ENV))
        return d

    def test_sun_position_from_place_and_time(self):
        e, n, u = core.sun_enu(0.0, 0.0, __import__("datetime").datetime(2026, 3, 20, 12, 0))
        self.assertGreater(u, 0.998)                                    # equinox noon on the equator: overhead
        e, n, u = core.sun_enu(41.0, 0.0, __import__("datetime").datetime(2026, 12, 21, 12, 0))
        self.assertAlmostEqual(math.degrees(math.asin(u)), 25.6, delta=0.3)      # 90 - 41 - 23.4
        self.assertLess(n, -0.85)                                       # in the south

    def test_sun_direction_follows_north_heading(self):
        d = self.doc()
        x, y, z = core.sun_direction(d)
        self.assertAlmostEqual(x * math.cos(1.2) + y * math.sin(1.2), -0.9, delta=0.02)   # south
        d["environment"]["lighting"] = {"sun": {"direction": [0, 0, 1]}}
        self.assertEqual(core.sun_direction(d), (0.0, 0.0, 1.0))                     # a fixed sun wins
        del d["environment"]["lighting"], d["environment"]["default_time"]
        self.assertIsNone(core.sun_direction(d))

    def test_import_makes_a_geo_origin_and_a_sun(self):
        desc = profile.scene_from_document(self.doc())
        by = {o["name"]: o for o in desc["objects"]}
        geo = by["STJ::geo::origin"]
        self.assertEqual(geo["heading"], 1.2)
        self.assertEqual(geo["props"]["stj"]["altitude"], 312.5)
        self.assertEqual(geo["props"]["stj"]["local_time"], "12:00")
        sun = by["STJ::sun::main"]
        self.assertEqual(sun["type"], "LIGHT")
        self.assertAlmostEqual(math.sqrt(sum(c * c for c in sun["direction"])), 1.0)
        base = json.loads(desc["texts"][profile.BASE_TEXT])
        self.assertNotIn("environment", base)                              # the heading is on the geo origin

    def test_import_then_apply_gives_the_environment_back(self):
        doc = self.doc()
        back = profile.apply_scene(profile.scene_from_document(doc))
        self.assertEqual(back["environment"], doc["environment"])            # the sun follows the time: no direction written
        self.assertEqual(levels(profile.lint_scene(profile.scene_from_document(doc)), "ERROR"), [])

    def test_a_moved_sun_becomes_a_fixed_direction(self):
        desc = profile.scene_from_document(self.doc())
        sun = next(o for o in desc["objects"] if o["name"] == "STJ::sun::main")
        sun["direction"] = [0.0, 0.0, 1.0]
        doc = profile.apply_scene(desc)
        self.assertEqual(doc["environment"]["lighting"]["sun"]["direction"], [0.0, 0.0, 1.0])
        self.assertTrue(any("will not follow date and time" in m for m in levels(profile.lint_scene(desc), "NOTE")))

    def test_the_geo_origin_in_blender_overrides_the_text_block(self):
        s = scene()
        s["objects"].append({"name": "STJ::geo::origin", "type": "EMPTY", "location": [0, 0, 0], "heading": math.pi / 2,
                             "collections": [], "props": {"stj": {"latitude": 10.0, "longitude": 20.0, "altitude": 5.0}}})
        env = profile.apply_scene(s)["environment"]
        self.assertEqual(env["geo_reference"], {"latitude": 10.0, "longitude": 20.0, "altitude": 5.0})
        self.assertNotIn("north_heading", env)                                # +Y north is the default

    def test_bad_geo_and_sun_objects(self):
        s = scene()
        s["objects"] += [{"name": "STJ::geo::origin", "type": "EMPTY", "location": [0, 0, 0], "heading": 0.0,
                          "collections": [], "props": {"stj": {"latitude": 95.0}}},
                         {"name": "STJ::sun::a", "type": "LIGHT", "light_type": "POINT", "location": [0, 0, 5], "heading": 0.0,
                          "collections": [], "props": {}, "direction": [0, 0, 1]},
                         {"name": "STJ::sun::b", "type": "LIGHT", "light_type": "SUN", "location": [0, 0, 5], "heading": 0.0,
                          "collections": [], "props": {}, "direction": [0, 0, 1]}]
        found = " | ".join(levels(profile.lint_scene(s), "ERROR"))
        self.assertIn("latitude must be", found)
        self.assertIn("a sun must be a Sun light", found)
        self.assertIn("more than one sun", found)


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


class RealDocuments(unittest.TestCase):
    """Three things real converted tracks showed, and the converters' own output when it is next to this repository."""

    def test_a_null_a_negative_scale_and_a_gate_off_the_arc_length_survive(self):
        import make_examples
        doc = make_examples.coll_de_prova()
        doc["ground"]["layers"][next(iter(doc["ground"]["layers"]))]["x_test"] = {"tilling": None, "n": 1}
        inst = doc["scenery"]["instances"][0]["transforms"]
        inst[0] = [inst[0][0], inst[0][1], inst[0][2], 1.5, -0.3333]            # a mirrored instance
        desc = profile.scene_from_document(doc)
        self.assertEqual(profile.apply_scene(desc), doc)

    def test_tilted_instances_round_trip(self):
        import make_examples
        doc = make_examples.coll_de_prova()
        rows = doc["scenery"]["instances"][0]["transforms"]
        rows[0] = [rows[0][0], rows[0][1], rows[0][2], 0.5, 1.0, 0.25]                  # pitch only
        rows[1] = [rows[1][0], rows[1][1], rows[1][2], 0.5, 0.8, -0.1, 1.5]             # pitch and roll
        rows[2] = [rows[2][0], rows[2][1], rows[2][2], 0.5, 1.0, 0.0, 3.1416]           # a roll only (upside down)
        desc = profile.scene_from_document(doc)
        inst = next(o for o in desc["objects"] if o["name"].startswith("STJ::instance::scots_pine"))
        self.assertEqual(inst["pitches"][:3], [0.25, -0.1, 0.0])
        self.assertEqual(inst["rolls"][:3], [0.0, 1.5, 3.1416])
        self.assertEqual(profile.apply_scene(desc), doc)

    def test_a_gate_whose_s_is_not_the_arc_length_stays_put(self):
        import make_examples
        doc = make_examples.test_ring()
        doc["reference"]["centerline"]["chainage"] = [k * 1.01 for k in range(len(doc["reference"]["centerline"]["points"]))]
        doc["timing"]["start_finish"]["s"] = 100.0
        back = profile.apply_scene(profile.scene_from_document(doc))
        self.assertEqual(back["timing"]["start_finish"]["s"], 100.0)

    def test_converter_output_round_trips(self):
        root = ROOT.parent
        files = [p for p in root.glob("*/out*/**/*.stj.json") if "STJ repo" not in str(p)][:60]
        if not files:
            self.skipTest("no converter output next to the repository")
        for f in files:
            doc = json.loads(f.read_text(encoding="utf-8"))
            desc = profile.scene_from_document(doc)
            self.assertEqual(levels(profile.lint_scene(desc), "ERROR"), [], f)
            self.assertEqual(profile.apply_scene(desc), doc, str(f))


@unittest.skipUnless(find_blender(), "Blender not found (set STJ_BLENDER)")
class InBlender(KeepExamples, unittest.TestCase):
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

    def test_names_of_meshes_and_the_placeholders(self):
        """Mesh objects keep the names of the USD prims (a repeated name gets its parent in front, not a .001) and a document
        without sky or sun gets placeholders that are never exported."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            r = self.run_blender("--python", str(ROOT / "tests" / "blender_names_check.py"), "--", str(ROOT / "examples" / "test_ring_gp.usda"), str(d / "out"))
            line = next((x for x in r.stdout.splitlines() if x.startswith("RESULT ")), None)
            self.assertTrue(line, r.stdout[-1500:] + r.stderr[-1500:])
            res = json.loads(line[7:])
        self.assertFalse([n for n in res["mesh_objects"] if n[-4:-3] == "." and n[-3:].isdigit()], res["mesh_objects"])
        self.assertIn("Marshal_Flag_T1/shape", res["mesh_objects"])
        self.assertEqual(res["placeholders"], {"Placeholder sun": ["STJ Placeholders"]})
        self.assertEqual(res["worlds"], {"Placeholder sky": True})
        self.assertEqual(res["export"], 0)
        self.assertFalse(res["placeholder_in_export"])
        self.assertEqual(res["layout_notes"], [])
        self.assertEqual(res["findings"], [])

    def test_a_usd_instance_set_is_visible_and_survives_the_export(self):
        """A PointInstancer in a mesh file is instances in Blender (Blender's importer makes them), with orientation and 3-axis
        scale, and the export puts the instancer back at its prim path instead of one object per instance."""
        if not core.have_pxr():
            self.skipTest("pxr not installed")
        from pxr import Gf, Usd, UsdGeom, Vt
        import make_examples
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            st = Usd.Stage.CreateNew(str(d / "scenery.usda"))
            UsdGeom.SetStageUpAxis(st, "Z")
            UsdGeom.SetStageMetersPerUnit(st, 1.0)
            UsdGeom.Xform.Define(st, "/track")
            inst = UsdGeom.PointInstancer.Define(st, "/track/logs")
            UsdGeom.Xform.Define(st, "/track/logs/protos")
            UsdGeom.Cube.Define(st, "/track/logs/protos/log").GetSizeAttr().Set(1.0)
            inst.CreatePrototypesRel().AddTarget("/track/logs/protos/log")
            inst.CreatePositionsAttr(Vt.Vec3fArray([Gf.Vec3f(0, 0, 1), Gf.Vec3f(5, 0, 1), Gf.Vec3f(10, 0, 1)]))
            inst.CreateProtoIndicesAttr(Vt.IntArray([0, 0, 0]))
            inst.CreateOrientationsAttr(Vt.QuathArray([Gf.Quath(1, 0, 0, 0), Gf.Quath(0.7071, 0, 0.7071, 0), Gf.Quath(0, 1, 0, 0)]))
            inst.CreateScalesAttr(Vt.Vec3fArray([Gf.Vec3f(1, 1, 1), Gf.Vec3f(2, 1, 1), Gf.Vec3f(1, 3, 1)]))
            st.GetRootLayer().Save()
            doc = make_examples.test_ring()
            doc.setdefault("geometry", {}).setdefault("meshes", []).append({"id": "scenery", "uri": "scenery.usda", "roles": ["visual"]})
            doc["scenery"] = {"prototypes": {"log": {"class": "rock"}},
                              "instances": [{"prototype": "log", "usd": {"mesh_ref": "scenery", "prim": "/track/logs"}}]}
            (d / "track.stj.json").write_text(json.dumps(doc), encoding="utf-8")
            r = self.run_blender("--python", str(ROOT / "tests" / "blender_instancer_check.py"), "--", str(d / "track.stj.json"), str(d / "out"))
            line = next((x for x in r.stdout.splitlines() if x.startswith("RESULT ")), None)
            self.assertTrue(line, r.stdout[-1500:] + r.stderr[-1500:])
            res = json.loads(line[7:])
        self.assertEqual(res["instances"], 3)
        self.assertEqual(res["scales"], [[1.0, 1.0, 1.0], [2.0, 1.0, 1.0], [1.0, 3.0, 1.0]])
        self.assertEqual(res["pointclouds"], [["logs", ["STJ::mesh::scenery"]]])
        self.assertEqual(res["findings"], [])
        self.assertTrue(res["same_document"], res)
        self.assertEqual(res["exported_instancers"], ["/track/logs"])
        self.assertEqual(res["exported_count"], 3)

    def test_import_then_export_gives_the_document_back(self):
        import make_examples
        doc = make_examples.test_ring()
        script = str(ROOT / "tools" / "blender" / "stj_blender.py")
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "ring.stj.json"
            src.write_text(json.dumps(doc), encoding="utf-8")
            blend = Path(d) / "ring.blend"
            r = self.run_blender("--python", script, "--", "import", str(src), str(blend))
            self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-800:])
            self.assertTrue(blend.is_file())
            r = subprocess.run([find_blender(), "-b", str(blend), "--python", script, "--", "export", str(Path(d) / "out"), "ring"],
                               capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stdout[-800:])
            back = json.loads((Path(d) / "out" / "ring.stj.json").read_text(encoding="utf-8"))
            self.assertEqual(back["reference"]["centerline"]["points"], doc["reference"]["centerline"]["points"])
            self.assertAlmostEqual(back["timing"]["start_finish"]["s"], 150.0, delta=0.01)
            self.assertEqual(back["timing"]["sectors"], doc["timing"]["sectors"])
            self.assertEqual(len(back["race"]["grid"]), 4)

    def test_objects_are_sorted_into_collections_by_kind(self):
        import make_examples
        doc = make_examples.coll_de_prova()
        script = str(ROOT / "tools" / "blender" / "stj_blender.py")
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "stage.stj.json"
            src.write_text(json.dumps(doc), encoding="utf-8")
            blend = Path(d) / "stage.blend"
            r = self.run_blender("--python", script, "--", "import", str(src), str(blend))
            self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-800:])
            probe = ("import bpy,json;print('COLL',json.dumps({c.name:sorted(o.name for o in c.objects) for c in bpy.data.collections},"
                     "default=str))")
            r = subprocess.run([find_blender(), "-b", str(blend), "--python-expr", probe], capture_output=True, text=True, timeout=300)
            line = next(x for x in r.stdout.splitlines() if x.startswith("COLL "))
            colls = json.loads(line[5:])
            self.assertTrue(any(n.startswith("STJ::reference::") for n in colls["STJ Track"]))
            self.assertTrue(any(n.startswith("STJ::instance::") for n in colls["STJ Scenery"]))
            self.assertTrue(any(n.startswith("STJ::ground_layer::") for n in colls["STJ Ground"]))
            self.assertTrue(any(n.startswith("STJ::spawn::") for n in colls["STJ Race"]))
            self.assertTrue(any(n.startswith("STJ::road::") for n in colls["STJ Roads"]))
            self.assertTrue(any(n.startswith("STJ::emitter::") for n in colls["STJ Cameras and audio"]))
            self.assertEqual(colls["STJ"], [])                         # nothing is left loose in the root
            r = subprocess.run([find_blender(), "-b", str(blend), "--python", script, "--", "export", str(Path(d) / "out"), "stage"],
                               capture_output=True, text=True, timeout=300)
            back = json.loads((Path(d) / "out" / "stage.stj.json").read_text(encoding="utf-8"))
            self.assertEqual(back["reference"], doc["reference"])      # which collection an object is in changes nothing

    def test_the_layout_note_names_objects_outside_their_collection(self):
        import make_examples
        desc = profile.scene_from_document(make_examples.coll_de_prova())
        self.assertEqual([x for x in profile.lint_scene(desc) if x[1] == "layout"], [])            # an import follows the layout
        road = next(o for o in desc["objects"] if o["name"].startswith("STJ::road::"))
        road["collections"] = ["STJ"]
        notes = [x for x in profile.lint_scene(desc) if x[1] == "layout"]
        self.assertEqual([n[0] for n in notes], ["NOTE"])
        self.assertIn("STJ Roads", notes[0][2])

    def test_emitters_are_speakers_and_the_sky_is_a_world(self):
        import make_examples
        doc = make_examples.coll_de_prova()
        script = str(ROOT / "tools" / "blender" / "stj_blender.py")
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "stage.stj.json"
            src.write_text(json.dumps(doc), encoding="utf-8")
            blend = Path(d) / "stage.blend"
            r = self.run_blender("--python", script, "--", "import", str(src), str(blend))
            self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-800:])
            probe = ("import bpy;print('SPK',sorted(o.name for o in bpy.data.objects if o.type=='SPEAKER'));"
                     "print('WORLD',bpy.context.scene.world.name if bpy.context.scene.world else None)")
            r = subprocess.run([find_blender(), "-b", str(blend), "--python-expr", probe], capture_output=True, text=True, timeout=300)
            positional = sorted("STJ::emitter::" + e["id"] for e in doc["audio"]["emitters"] if "position" in e)
            self.assertIn("SPK " + str(positional), r.stdout)
            self.assertIn("WORLD STJ::sky", r.stdout)
            r = subprocess.run([find_blender(), "-b", str(blend), "--python", script, "--", "export", str(Path(d) / "out"), "stage"],
                               capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stdout[-800:])
            back = json.loads((Path(d) / "out" / "stage.stj.json").read_text(encoding="utf-8"))
            self.assertEqual(back["audio"]["emitters"], doc["audio"]["emitters"])
            self.assertEqual(back["environment"]["sky"], doc["environment"]["sky"])

    def test_coordinates_height_and_sun_survive_the_round_trip(self):
        doc = json.loads(json.dumps(PlaceAndSun.ENV))
        import make_examples
        full = make_examples.test_ring()
        full["environment"].update(doc)
        script = str(ROOT / "tools" / "blender" / "stj_blender.py")
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "ring.stj.json"
            src.write_text(json.dumps(full), encoding="utf-8")
            blend = Path(d) / "ring.blend"
            r = self.run_blender("--python", script, "--", "import", str(src), str(blend))
            self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-800:])
            r = subprocess.run([find_blender(), "-b", str(blend), "--python", script, "--", "export", str(Path(d) / "out"), "ring"],
                               capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stdout[-800:])
            back = json.loads((Path(d) / "out" / "ring.stj.json").read_text(encoding="utf-8"))
            env = back["environment"]
            self.assertEqual(env["geo_reference"], full["environment"]["geo_reference"])
            self.assertAlmostEqual(env["north_heading"], 1.2, places=5)
            self.assertEqual(env["default_time"], full["environment"]["default_time"])
            self.assertNotIn("lighting", env)        # the sun was not moved, so it still follows date and time

    def test_meshes_round_trip_through_collections(self):
        from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade
        import make_examples
        doc = make_examples.test_ring()
        script = str(ROOT / "tools" / "blender" / "stj_blender.py")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            stage = Usd.Stage.CreateNew(str(d / "road.usda"))
            UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
            UsdGeom.SetStageMetersPerUnit(stage, 1.0)
            mesh = UsdGeom.Mesh.Define(stage, "/road/STJ__collision__road")
            mesh.CreatePointsAttr([Gf.Vec3f(0, 0, 0), Gf.Vec3f(10, 0, 0), Gf.Vec3f(10, 10, 0), Gf.Vec3f(0, 10, 0)])
            mesh.CreateFaceVertexCountsAttr([4])
            mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
            mat = UsdShade.Material.Define(stage, "/road/Looks/STJ__surface__asphalt")
            sh = UsdShade.Shader.Define(stage, "/road/Looks/STJ__surface__asphalt/Preview")
            sh.CreateIdAttr("UsdPreviewSurface")
            sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.3, 0.3, 0.3))
            mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
            UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(mat)
            stage.GetRootLayer().Save()
            doc["geometry"] = {"meshes": [{"id": "road", "uri": "road.usda", "roles": ["collision", "visual"]}]}
            (d / "ring.stj.json").write_text(json.dumps(doc), encoding="utf-8")
            blend = d / "ring.blend"
            r = self.run_blender("--python", script, "--", "import", str(d / "ring.stj.json"), str(blend))
            self.assertEqual(r.returncode, 0, r.stdout[-1500:] + r.stderr[-800:])
            r = subprocess.run([find_blender(), "-b", str(blend), "--python", script, "--", "export", str(d / "out"), "ring"],
                               capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stdout[-1500:])
            back = json.loads((d / "out" / "ring.stj.json").read_text(encoding="utf-8"))
            self.assertEqual(back["geometry"]["meshes"], doc["geometry"]["meshes"])
            out_stage = Usd.Stage.Open(str(d / "out" / "road.usda"))
            meshes = [p for p in out_stage.Traverse() if p.IsA(UsdGeom.Mesh)]
            self.assertEqual(len(meshes), 1)
            self.assertEqual(len(UsdGeom.Mesh(meshes[0]).GetPointsAttr().Get()), 4)
            self.assertTrue(any(p.GetName() == "STJ__surface__asphalt" for p in out_stage.Traverse()))
            rep = validate.validate(str(d / "out" / "ring.stj.json"))
            self.assertEqual([f"{w}: {m}" for lv, w, m in rep.items if lv == "ERROR"], [])

    def test_full_documents_survive_blender(self):
        import make_examples
        script = str(ROOT / "tools" / "blender" / "stj_blender.py")
        for name in ("test_ring_gp", "coll_de_prova", "with_places"):
            doc = with_places(make_examples.coll_de_prova()) if name == "with_places" else getattr(make_examples, name)()
            with tempfile.TemporaryDirectory() as d:
                d = Path(d)
                (d / "t.stj.json").write_text(json.dumps(doc), encoding="utf-8")
                r = self.run_blender("--python", script, "--", "import", str(d / "t.stj.json"), str(d / "t.blend"))
                self.assertEqual(r.returncode, 0, name + r.stdout[-1500:] + r.stderr[-500:])
                r = subprocess.run([find_blender(), "-b", str(d / "t.blend"), "--python", script, "--", "export", str(d / "out"), "t"],
                                   capture_output=True, text=True, timeout=300)
                self.assertEqual(r.returncode, 0, name + r.stdout[-1500:])
                back = json.loads((d / "out" / "t.stj.json").read_text(encoding="utf-8"))
                for key in sorted(set(doc) | set(back)):
                    self.assertEqual(back.get(key), doc.get(key), f"{name}: {key}")

    def test_terrain_survives_blender(self):
        import shutil
        import make_examples
        script = str(ROOT / "tools" / "blender" / "stj_blender.py")
        doc = make_examples.coll_de_prova()
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            shutil.copytree(ROOT / "examples" / "terrain", d / "terrain")
            (d / "t.stj.json").write_text(json.dumps(doc), encoding="utf-8")
            r = self.run_blender("--python", script, "--", "import", str(d / "t.stj.json"), str(d / "t.blend"))
            self.assertEqual(r.returncode, 0, r.stdout[-1500:] + r.stderr[-500:])
            r = subprocess.run([find_blender(), "-b", str(d / "t.blend"), "--python", script, "--", "export", str(d / "out"), "t"],
                               capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stdout[-1500:])
            back = json.loads((d / "out" / "t.stj.json").read_text(encoding="utf-8"))
            self.assertEqual(back["geometry"]["terrain"], doc["geometry"]["terrain"])
            self.assertFalse((d / "out" / "terrain").exists())                 # untouched: nothing rewritten

    def test_rigid_body_edits_reach_the_document(self):
        import make_examples
        script = str(ROOT / "tools" / "blender" / "stj_blender.py")
        doc = make_examples.coll_de_prova()
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "t.stj.json").write_text(json.dumps(doc), encoding="utf-8")
            r = self.run_blender("--python", script, "--", "import", str(d / "t.stj.json"), str(d / "t.blend"))
            self.assertEqual(r.returncode, 0, r.stdout[-1500:] + r.stderr[-500:])
            edit = d / "edit.py"
            edit.write_text(chr(10).join([
                "import bpy",
                "o = bpy.data.objects['STJ::prototype::hay_bale::body']",
                "assert o.rigid_body.mass == 250.0 and o.rigid_body.collision_shape == 'CYLINDER'",
                "o.rigid_body.mass = 400.0",
                "o.scale.z = 2.0",
                "bpy.ops.wm.save_mainfile()"]), encoding="utf-8")
            r = subprocess.run([find_blender(), "-b", str(d / "t.blend"), "--python", str(edit)],
                               capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stdout[-1500:])
            r = subprocess.run([find_blender(), "-b", str(d / "t.blend"), "--python", script, "--", "export", str(d / "out"), "t"],
                               capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stdout[-1500:])
            back = json.loads((d / "out" / "t.stj.json").read_text(encoding="utf-8"))
            phys = back["scenery"]["prototypes"]["hay_bale"]["physics"]
            self.assertEqual(phys["mass"], 400.0)
            self.assertAlmostEqual(phys["shape"]["height"], 2.4, places=3)
            self.assertEqual(phys["shape"]["radius"], 0.75)
            self.assertEqual(phys["friction"], 0.6)                              # untouched values stay as written
            self.assertEqual(back["scenery"]["prototypes"]["birch_sapling"], doc["scenery"]["prototypes"]["birch_sapling"])

    def test_blend_to_document_to_blend_keeps_the_scene(self):
        script = str(ROOT / "tools" / "blender" / "stj_blender.py")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.run_blender("--python", str(ROOT / "examples" / "make_blender_reference.py"), "--", str(d))
            ref = d / "test_ring_profile.blend"

            def run(*args, blend=None):
                cmd = [find_blender(), "-b"] + ([str(blend)] if blend else ["--factory-startup"]) + ["--python", script, "--", *args]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                self.assertEqual(r.returncode, 0, r.stdout[-1500:])
            run("dump", str(d / "a.json"), blend=ref)
            run("export", str(d / "out"), "r", blend=ref)
            run("import", str(d / "out" / "r.stj.json"), str(d / "b.blend"))
            run("dump", str(d / "b.json"), blend=d / "b.blend")
            a, b = (json.loads((d / f"{x}.json").read_text(encoding="utf-8")) for x in "ab")
            A, B = ({o["name"]: o for o in sc["objects"]} for sc in (a, b))
            self.assertEqual(sorted(A), sorted(B))
            for name in A:
                self.assertEqual(A[name]["type"], B[name]["type"], name)
                for i in range(3):
                    self.assertAlmostEqual(A[name]["location"][i], B[name]["location"][i], delta=0.01, msg=name)
                self.assertAlmostEqual(A[name]["heading"], B[name]["heading"], delta=0.001, msg=name)
                if "points" in A[name]:
                    self.assertEqual(len(A[name]["points"]), len(B[name]["points"]))
                    for p, q in zip(A[name]["points"], B[name]["points"]):
                        self.assertAlmostEqual(p[0], q[0], delta=0.001)
            self.assertEqual([m["name"] for m in a["materials"]], [m["name"] for m in b["materials"]])


if __name__ == "__main__":
    unittest.main()
