"""Tests for tools/validate.py and tools/stj_core.py. Run: python -m unittest discover tests"""

import contextlib
import copy
import io
import json
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import stj_core as core  # noqa: E402
import validate  # noqa: E402

EX = ROOT / "examples"
RING = EX / "test_ring_minimal.usda"
GP = EX / "test_ring_gp.usda"
STAGE = EX / "coll_de_prova_gravel.usda"
WET = EX / "coll_de_prova_gravel_wet.usda"
BLEND = EX / "test_ring_blend.usda"


def run(doc, where=EX):
    """Validate a document written next to the examples (so relative URIs resolve)."""
    with tempfile.NamedTemporaryFile("w", suffix=".stj.json", dir=where, delete=False, encoding="utf-8") as f:
        json.dump(doc, f)
        name = f.name
    try:
        return validate.validate(name)
    finally:
        Path(name).unlink()


def messages(rep, level):
    return [f"{p}: {m}" for lv, p, m in rep.items if lv == level]


class Examples(unittest.TestCase):
    def test_examples_pass_strict(self):
        files = sorted(EX.glob("*.usda")) + sorted(EX.glob("*.usdz"))
        self.assertGreaterEqual(len(files), 10)
        for f in files:
            rep = validate.validate(f)
            self.assertEqual(messages(rep, "ERROR") + messages(rep, "WARN"), [], f.name)

    def test_minimal_file(self):
        doc = {"_metadata": {"specification": "STJ", "version": "0.1", "coordinate_system": "OpenDRIVE", "units": "SI"},
               "reference": {"centerline": {"points": [[0, 0, 0], [100, 0, 0]]}},
               "surfaces": {"default": "a", "library": {"a": {"class": "asphalt"}}}}
        self.assertEqual(messages(run(doc), "ERROR"), [])


class CrossReferences(unittest.TestCase):
    def setUp(self):
        self.ring = core.load_document(RING)
        self.stage = core.load_document(STAGE)

    def assertError(self, doc, fragment):
        errs = messages(run(doc), "ERROR")
        self.assertTrue(any(fragment in e for e in errs), f"no error containing {fragment!r} in {errs}")

    def assertWarn(self, doc, fragment):
        warns = messages(run(doc), "WARN")
        self.assertTrue(any(fragment in w for w in warns), f"no warning containing {fragment!r} in {warns}")

    def test_schema_rejects_typo(self):
        self.ring["timing"]["start_finsh"] = {"s": 1}
        self.assertError(self.ring, "start_finsh")

    def test_unknown_surface_in_band(self):
        self.ring["surfaces"]["bands"][0]["surface"] = "tarmac"
        self.assertError(self.ring, "unknown surface 'tarmac'")

    def test_unknown_base_surface(self):
        self.stage["surfaces"]["library"]["gravel_loose"]["deformable"]["effective"]["base_surface"] = "rock"
        self.assertError(self.stage, "unknown surface 'rock'")

    def test_binding_to_missing_material(self):
        self.stage["surfaces"]["bindings"][0]["material"] = "GravelCoarse"
        self.assertError(self.stage, "material 'GravelCoarse' not in")

    def test_binding_to_unknown_mesh(self):
        self.stage["surfaces"]["bindings"][0]["mesh_ref"] = "terrain"
        self.assertError(self.stage, "unknown mesh 'terrain'")

    def test_sector_gap(self):
        self.ring["timing"]["sectors"][1]["s_start"] = 430.0
        self.assertError(self.ring, "not at the end of sector 's1'")

    def test_sectors_do_not_close_the_lap(self):
        self.ring["timing"]["sectors"].pop()
        self.assertError(self.ring, "sectors end")

    def test_sectors_wrap_on_closed_track(self):
        # s3 runs from 720 through s = 0 to 150: valid only because the line is closed
        self.assertEqual(messages(run(self.ring), "ERROR"), [])

    def test_splits_out_of_order(self):
        sp = self.stage["timing"]["split_points"]
        sp[0]["s"], sp[1]["s"] = sp[1]["s"], sp[0]["s"]
        self.assertError(self.stage, "is not after the previous timing point")

    def test_finish_before_start(self):
        self.stage["timing"]["finish"]["s"] = 10.0
        self.assertError(self.stage, "must come after start")

    def test_s_beyond_line(self):
        self.stage["timing"]["stop"]["s"] = 99999.0
        self.assertError(self.stage, "beyond the reference line")

    def test_pacenotes_out_of_order(self):
        notes = self.stage["race"]["pacenotes"]["notes"]
        notes[2], notes[3] = notes[3], notes[2]
        self.assertError(self.stage, "comes before the previous note")

    def test_s_without_reference(self):
        del self.ring["reference"]
        del self.ring["surfaces"]["bands"]
        self.assertError(self.ring, "needs a reference line")

    def test_grid_gap(self):
        self.ring["race"]["grid"][3]["position"] = 6
        self.assertError(self.ring, "positions must be 1..4")

    def test_grid_order(self):
        g = self.ring["race"]["grid"]
        g[0]["pose"], g[1]["pose"] = g[1]["pose"], g[0]["pose"]
        self.assertWarn(self.ring, "is ahead of position")

    def test_degrees_instead_of_radians(self):
        self.ring["environment"]["north_heading"] = 90
        self.assertWarn(self.ring, "angles are in radians")

    def test_kmh_instead_of_ms(self):
        self.ring["timing"]["pit_lane"] = {"entry_s": 900.0, "exit_s": 200.0, "speed_limit": 60}
        self.assertWarn(self.ring, "speeds are in m/s")

    def test_geographic_projection_rejected(self):
        self.stage["environment"]["geo_reference"]["proj"] = "EPSG:4326"
        self.assertError(self.stage, "projected metres")

    def test_unknown_prototype(self):
        self.stage["scenery"]["scatter"][1]["prototypes"][0]["prototype"] = "oak"
        self.assertError(self.stage, "unknown prototype 'oak'")

    def test_scatter_on_unknown_surface(self):
        self.stage["scenery"]["scatter"][0]["area"]["surfaces"] = ["meadow"]
        self.assertError(self.stage, "unknown surface 'meadow'")

    def test_newer_key_in_older_file_warns(self):
        self.ring["dynamic"] = {}
        self.assertWarn(self.ring, "declares 0.1 but uses v0.3 features")

    def test_track_type_mismatch(self):
        self.ring["track_info"]["type"] = "point_to_point"
        self.assertWarn(self.ring, "centerline is closed")

    def test_wet_response_order(self):
        self.ring["surfaces"]["library"]["asphalt"]["wet_response"] = [[0.0, 1.0], [0.002, 0.7], [0.001, 0.8]]
        self.assertError(self.ring, "x values must increase")


class Tier1(unittest.TestCase):
    """Layouts, variants, edges, cameras, AI, race control."""

    def setUp(self):
        self.gp = core.load_document(GP)
        self.stage = core.load_document(STAGE)

    def assertFinding(self, doc, level, fragment):
        found = messages(run(doc), level)
        self.assertTrue(any(fragment in m for m in found), f"no {level} containing {fragment!r} in {found}")

    def test_reverse_layout_sectors_checked_on_reversed_line(self):
        self.gp["layouts"][0]["timing"]["sectors"][1]["s_start"] += 5
        self.assertFinding(self.gp, "ERROR", "layouts[0](gp_reverse).timing.sectors[1].s_start")

    def test_reverse_layout_pacenotes_order(self):
        notes = self.stage["layouts"][0]["race"]["pacenotes"]["notes"]
        notes[1], notes[2] = notes[2], notes[1]
        self.assertFinding(self.stage, "ERROR", "layouts[0](ss1_reverse).race.pacenotes")

    def test_layout_unknown_mesh(self):
        self.stage["layouts"][0]["include_meshes"] = ["stage_visual"]
        self.assertFinding(self.stage, "ERROR", "unknown mesh 'stage_visual'")

    def test_variant_with_foreign_base(self):
        self.gp["variants"][0]["override"] = "coll_de_prova_gravel_wet.usda"
        self.assertFinding(self.gp, "ERROR", "not this file")

    def test_variant_findings_are_prefixed(self):
        with tempfile.TemporaryDirectory(dir=EX) as d:
            base = Path(d, "base.stj.json")
            ring = core.load_document(RING)
            ring["variants"] = [{"id": "flood", "kind": "weather", "override": "flood.stj-override.json"}]
            base.write_text(json.dumps(ring))
            Path(d, "flood.stj-override.json").write_text(json.dumps({
                "_metadata": {"specification": "STJ-OVERRIDE", "version": "0.1", "base": "base.stj.json"},
                "patch": {"environment": {"default_weather": {"water_depth": 0.5}}}}))
            warns = messages(validate.validate(base), "WARN")
        self.assertTrue(any(w.startswith("variants[0](flood).environment.default_weather.water_depth") for w in warns), warns)

    def test_drs_order(self):
        z = self.gp["timing"]["drs_zones"][0]
        z["activation_s"], z["deactivation_s"] = z["deactivation_s"], z["activation_s"]
        self.assertFinding(self.gp, "ERROR", "detection, activation, deactivation")

    def test_edge_checks(self):
        self.gp["edges"][0]["surface"] = "astroturf"
        self.gp["edges"][3]["t"] = 25.0                     # right-side barrier with a left offset
        self.gp["edges"][4]["style"] = "rumble"             # a kerb style on a barrier
        doc = run(self.gp)
        self.assertTrue(any("unknown surface 'astroturf'" in e for e in messages(doc, "ERROR")))
        warns = messages(doc, "WARN")
        self.assertTrue(any("edges[3].t" in w for w in warns), warns)
        self.assertTrue(any("is not a barrier style" in w for w in warns), warns)

    def test_camera_checks(self):
        cams = self.gp["cameras"]["sets"][0]["cameras"]
        cams[1]["fov"] = [10, 40]
        del cams[0]["look_at"]
        doc = run(self.gp)
        warns = messages(doc, "WARN")
        self.assertTrue(any("field of view is in radians" in w for w in warns), warns)
        self.assertTrue(any("needs look_at" in w for w in warns), warns)

    def test_ai_checks(self):
        ai = self.gp["race"]["ai"]
        ai["corridor"][3][0] = ai["corridor"][2][0]
        ai["hints"][0]["value"] = 100 * 3.6
        doc = run(self.gp)
        self.assertTrue(any("corridor[3]: s must increase" in e for e in messages(doc, "ERROR")))
        self.assertTrue(any("speeds are in m/s" in w for w in messages(doc, "WARN")))

    def test_start_procedure_checks(self):
        self.stage["race"]["start_procedure"] = {"type": "rolling", "rolling_start_speed": 80}
        doc = run(self.stage)
        warns = messages(doc, "WARN")
        self.assertTrue(any("start on an open track" in w for w in warns), warns)
        self.assertTrue(any("speeds are in m/s" in w for w in warns), warns)

    def test_weather_schedule_order(self):
        self.gp["environment"]["weather_schedule"][2]["time"] = 600.0
        self.assertFinding(self.gp, "ERROR", "must not decrease")

    def test_rally_controls_and_side_roads(self):
        self.stage["timing"]["controls"][1]["id"] = "tc1"
        self.stage["timing"]["side_roads"][0]["s"] = 99999.0
        doc = run(self.stage)
        errs = messages(doc, "ERROR")
        self.assertTrue(any("duplicate control id 'tc1'" in e for e in errs), errs)
        self.assertTrue(any("side_roads[0].s" in e for e in errs), errs)

    def test_reverse_reference_geometry(self):
        doc = core.load_document(GP)
        fwd = core.reference_line(doc)
        rev = core.reference_line(core.layout_document(doc, "gp_reverse"))
        self.assertAlmostEqual(fwd.length, rev.length)
        for s in (0.0, 123.4, 500.0, 900.0):                         # the line itself: s' = L - s
            a = fwd.point(s)
            b = rev.point((fwd.length - s) % fwd.length)
            self.assertAlmostEqual(math.dist(a, b), 0.0, places=6)
        for i in (0, 7, 20):                                         # offsets, away from vertices: left becomes right
            s = 0.5 * (fwd.s[i] + fwd.s[i + 1])
            a = fwd.point(s, 2.0)
            b = rev.point(fwd.length - s, -2.0)
            self.assertAlmostEqual(math.dist(a, b), 0.0, places=6)

    def test_layout_document_replaces_race_data(self):
        doc = core.layout_document(core.load_document(STAGE), "ss1_reverse")
        self.assertEqual(doc["track_info"]["layout"], "SS1 reverse")
        self.assertNotIn("edges", doc)                 # base edges sit on the forward line
        self.assertNotIn("layouts", doc)
        self.assertEqual(doc["race"]["pacenotes"]["notes"][-1]["kind"], "finish")


class Core(unittest.TestCase):
    def test_merge_patch_rfc7396(self):
        # examples from RFC 7396 appendix A
        self.assertEqual(core.merge_patch({"a": "b"}, {"a": "c"}), {"a": "c"})
        self.assertEqual(core.merge_patch({"a": "b"}, {"a": None}), {})
        self.assertEqual(core.merge_patch({"a": [{"b": "c"}]}, {"a": [1]}), {"a": [1]})
        self.assertEqual(core.merge_patch({"a": {"b": "c"}}, {"a": {"b": "d", "c": None}}), {"a": {"b": "d"}})
        self.assertEqual(core.merge_patch({"e": None}, {"a": 1}), {"e": None, "a": 1})

    def test_override_applies(self):
        doc, chain = core.resolve(WET)
        self.assertEqual(doc["environment"]["default_weather"]["condition"], "rain")
        self.assertEqual(doc["surfaces"]["library"]["verge_grass"]["deformable"]["effective"]["sinkage"], 0.04)
        self.assertEqual(doc["surfaces"]["library"]["verge_grass"]["deformable"]["effective"]["drag_coefficient"], 0.004)
        self.assertEqual([p.name for p in chain], [STAGE.name, WET.name])

    def test_circular_ref(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "a.json").write_text('{"x": {"$ref": "b.json"}}')
            Path(d, "b.json").write_text('{"y": {"$ref": "a.json"}}')
            with self.assertRaises(core.StjLoadError):
                core.resolve(Path(d, "a.json"))

    def test_reference_line(self):
        line = core.ReferenceLine([[0, 0, 0], [100, 0, 10], [100, 100, 10]])
        self.assertAlmostEqual(line.length, 200.0)          # x/y-plane length, z ignored (OpenDRIVE s)
        x, y, z = line.point(50, 2.0)                       # t positive to the left of +X is +Y
        self.assertAlmostEqual((x, y, z), (50.0, 2.0, 5.0))
        closed = core.ReferenceLine([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]], closed=True)
        self.assertAlmostEqual(closed.length, 40.0)
        self.assertAlmostEqual(closed.lap_distance(5, 35), 10.0)


class Tier2(unittest.TestCase):
    """v0.2: signals, terrain, water, substitutions, line states, props, animation, audio."""

    def setUp(self):
        self.gp = core.load_document(GP)
        self.stage = core.load_document(STAGE)

    def assertFinding(self, doc, level, fragment):
        found = messages(run(doc), level)
        self.assertTrue(any(fragment in m for m in found), f"no {level} containing {fragment!r} in {found}")

    def light(self, i=0):
        return self.gp["environment"]["lighting"]["lights"][i]

    # signals
    def test_unknown_signal_is_a_schema_error(self):
        self.light()["when"] = {"signal": "sun_angle", "op": "lt", "value": 0.0}
        self.assertFinding(self.gp, "ERROR", "sun_angle")

    def test_enum_signal_needs_eq_ne_in(self):
        self.light()["when"] = {"signal": "session", "op": "lt", "value": "race"}
        self.assertFinding(self.gp, "ERROR", "is an enum signal")

    def test_enum_signal_value(self):
        self.light()["when"] = {"signal": "flag", "op": "in", "value": ["yellow", "purple"]}
        self.assertFinding(self.gp, "ERROR", "'purple' is not a value of 'flag'")

    def test_sun_elevation_in_degrees(self):
        self.light()["when"] = {"signal": "sun_elevation", "op": "lt", "value": 3}
        self.assertFinding(self.gp, "WARN", "check the unit")

    def test_map_on_numeric_signal(self):
        self.light()["intensity_by"] = {"signal": "wind_speed", "map": {"calm": 1.0}}
        self.assertFinding(self.gp, "ERROR", "use curve, not map")

    def test_more_start_lights_than_the_gantry_has(self):
        self.light(6)["when"]["value"] = 7
        self.assertFinding(self.gp, "WARN", "start_procedure.lights.count is 5")

    # terrain
    def test_terrain_above_road(self):
        hm = self.stage["geometry"]["terrain"]["heightmap"]
        hm["height_min"] += 3.0
        hm["height_max"] += 3.0
        self.assertFinding(self.stage, "WARN", "terrain rises above the road")

    def test_terrain_size_mismatch(self):
        self.stage["geometry"]["terrain"]["heightmap"]["size"] = [65, 129]
        self.assertFinding(self.stage, "ERROR", "heightmap.size says 65 x 129")

    def test_terrain_non_square_cells(self):
        ext = self.stage["geometry"]["terrain"]["heightmap"]["extent"]
        ext[3] += 100.0
        self.assertFinding(self.stage, "WARN", "square cells")

    def test_terrain_layer_surface(self):
        self.stage["geometry"]["terrain"]["layers"][1]["surface"] = "moss"
        self.assertFinding(self.stage, "ERROR", "unknown surface 'moss'")

    def test_terrain_raw_f32_size(self):
        with tempfile.TemporaryDirectory(dir=EX) as d:
            Path(d, "h.raw").write_bytes(bytes(100))
            ter = self.stage["geometry"]["terrain"]
            ter["heightmap"].update({"uri": Path(d).name + "/h.raw", "format": "raw_f32"})
            self.assertFinding(self.stage, "ERROR", "expected")

    # surfaces
    def test_substitution_chain(self):
        winter = core.resolve(EX / "coll_de_prova_gravel_winter.usda")[0]
        winter["surfaces"]["substitutions"]["snow_packed"] = "snow_soft"
        self.assertFinding(winter, "ERROR", "no chains")

    def test_substitution_unknown_target(self):
        self.stage["surfaces"]["substitutions"] = {"gravel_loose": "ice_sheet"}
        self.assertFinding(self.stage, "ERROR", "unknown surface 'ice_sheet'")

    def test_line_state_needs_a_racing_line(self):
        self.gp["surfaces"]["line_states"][0]["line"] = "quali"
        self.assertFinding(self.gp, "ERROR", "unknown racing line 'quali'")

    def test_rubber_on_gravel(self):
        self.stage["surfaces"]["line_states"][0]["kind"] = "rubber"
        self.assertFinding(self.stage, "WARN", "use kind 'swept'")

    def test_dry_line_needs_a_racing_line(self):
        self.gp["water"]["dry_line"] = {"line": "wet", "spread": 0.9, "factor": 0.3}
        self.assertFinding(self.gp, "ERROR", "unknown racing line 'wet'")

    # water
    def test_drivable_and_out_of_bounds(self):
        self.stage["water"]["bodies"][0]["out_of_bounds"] = True
        self.assertFinding(self.stage, "ERROR", "both drivable and out of bounds")

    def test_ford_width(self):
        self.stage["water"]["bodies"][0]["path"][0][3] = 0.0
        self.assertFinding(self.stage, "ERROR", "width and depth must be positive")

    # props, animation, audio
    def test_inertia_triangle(self):
        self.gp["scenery"]["prototypes"]["cone"]["physics"]["inertia"] = [0.1, 0.1, 0.5]
        self.assertFinding(self.gp, "ERROR", "triangle inequality")

    def test_tethered_needs_tether(self):
        del self.gp["scenery"]["prototypes"]["tyre_stack"]["physics"]["tether"]
        self.assertFinding(self.gp, "ERROR", "needs a tether")

    def test_scaled_physical_prop(self):
        self.gp["scenery"]["instances"][0]["transforms"][0].append(1.5)
        self.assertFinding(self.gp, "WARN", "physics values are for scale 1")

    def test_animation_time_range(self):
        self.gp["animated_objects"][0]["time_range"] = [96, 0]
        self.assertFinding(self.gp, "ERROR", "end must be after start")

    def test_animation_node(self):
        self.gp["animated_objects"][1]["target"]["nodes"] = ["/track/props/Gate"]
        self.assertFinding(self.gp, "ERROR", "prim '/track/props/Gate' not in")

    def test_speed_by_and_time_by_exclusive(self):
        self.gp["animated_objects"][1]["speed_by"] = {"signal": "wind_speed", "curve": [[0, 0], [10, 1]]}
        self.assertFinding(self.gp, "ERROR", "animated_objects[1]")

    def test_audio_distances(self):
        e = self.gp["audio"]["emitters"][0]
        e["ref_distance"], e["max_distance"] = 300.0, 250.0
        self.assertFinding(self.gp, "ERROR", "ref_distance must be smaller")

    def test_audio_bank_file(self):
        self.gp["audio"]["emitters"][0]["sound"]["uri"] = "audio/track.bank"
        self.assertFinding(self.gp, "WARN", "WAV, Ogg Vorbis or FLAC")

    # version
    def test_v02_features_in_a_v01_file(self):
        self.gp["_metadata"]["version"] = "0.1"
        self.assertFinding(self.gp, "WARN", "declares 0.1 but uses v0.2 features")


class CoreV02(unittest.TestCase):
    def test_png_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "a.png")
            vals = [(i * 997) % 65536 for i in range(7 * 5)]
            core.write_png(p, 7, 5, vals, 1, 16)
            img = core.read_png(p)
            self.assertEqual((img.width, img.height, img.maxval, img.data), (7, 5, 65535, vals))

    def test_png_filters(self):
        """Rows encoded with None, Sub, Up, Average and Paeth decode to the original bytes."""
        import struct
        import zlib
        w, h, bpp = 4, 5, 3
        rows = [bytes((17 * (i + 3 * j) + 5 * k) % 256 for i in range(w) for k in range(bpp)) for j in range(h)]

        def paeth(a, b, c):
            pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
            return a if pa <= pb and pa <= pc else b if pb <= pc else c

        raw, prev = b"", bytes(w * bpp)
        for j, row in enumerate(rows):
            f = j % 5
            out = bytearray()
            for k, x in enumerate(row):
                a = row[k - bpp] if k >= bpp else 0
                b = prev[k]
                c = prev[k - bpp] if k >= bpp else 0
                pred = [0, a, b, (a + b) // 2, paeth(a, b, c)][f]
                out.append((x - pred) % 256)
            raw += bytes([f]) + bytes(out)
            prev = row

        def chunk(kind, body):
            return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "f.png")
            p.write_bytes(core.PNG_MAGIC + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                          + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
            self.assertEqual(core.read_png(p).data, list(b"".join(rows)))

    def test_terrain_row_zero_is_north(self):
        with tempfile.TemporaryDirectory() as d:
            core.write_png(Path(d, "h.png"), 3, 3, [65535] * 3 + [0] * 6, 1, 16)
            ter = core.Terrain({"heightmap": {"uri": "h.png", "format": "png16", "size": [3, 3],
                                              "extent": [0, 0, 10, 10], "height_min": 0.0, "height_max": 8.0}}, d)
            self.assertAlmostEqual(ter.height(5, 10), 8.0)     # y_max edge = image row 0
            self.assertAlmostEqual(ter.height(5, 0), 0.0)
            self.assertAlmostEqual(ter.height(5, 7.5), 4.0)    # bilinear between rows 0 and 1
            self.assertIsNone(ter.height(11, 5))

    def test_conditions(self):
        cond = {"all": [{"signal": "sun_elevation", "op": "lt", "value": 0.05},
                        {"not": {"signal": "session", "op": "in", "value": ["practice"]}}]}
        self.assertTrue(core.eval_condition(cond, {"sun_elevation": 0.0, "session": "race"}))
        self.assertFalse(core.eval_condition(cond, {"sun_elevation": 0.0, "session": "practice"}))
        self.assertFalse(core.eval_condition(cond, {"session": "race"}))   # missing signal: false
        self.assertAlmostEqual(core.eval_curve([[0, 0], [12, 2]], 6), 1.0)
        self.assertEqual(core.eval_curve([[0, 0], [12, 2]], 30), 2)

    def test_film_depth(self):
        ref = core.ReferenceLine([[0, 0, 0], [100, 0, 0]])
        asphalt = {"class": "asphalt", "roughness": {"mean_profile_depth": 0.0008}}   # holds 0.4 mm
        doc = {"water": {"accumulation_bands": [{"s_start": 40, "s_end": 60, "t_min": -5, "t_max": 5, "factor": 2.0}],
                         "shelter": [{"id": "bridge", "factor": 1.0, "band": {"s_start": 80, "s_end": 90, "t_min": -5, "t_max": 5}}],
                         "dry_line": {"line": "race", "spread": 1.0, "factor": 0.2}}}
        off = [(float(s), 1.0) for s in range(0, 101, 5)]            # racing line 1 m left of the centerline

        def d(s, t, depth=0.002):
            return core.film_depth(doc, ".", asphalt, s, t, s, t, depth, ref, off)

        far = 1.0 - 0.8 * math.exp(-0.5 * 25)                        # 5 m off the line: almost no drying
        self.assertAlmostEqual(d(20, -4), 0.002 * far - 0.0004, places=6)
        self.assertAlmostEqual(d(50, -4), 0.004 * far - 0.0004, places=6)   # standing water x2
        self.assertEqual(d(85, -4), 0.0)                                   # under the bridge
        self.assertAlmostEqual(d(20, 1, 0.004), 0.004 * 0.2 - 0.0004, places=6)   # on the drying line
        self.assertEqual(d(20, 1), 0.0)                                    # 0.4 mm on the line, all held

    def test_line_state_value(self):
        st = {"spread": 1.0, "profile": [[0, 1.0], [100, 2.0]]}
        self.assertAlmostEqual(core.line_state_value(st, 0.5, 50, 3.0, 3.0), 0.75)
        self.assertAlmostEqual(core.line_state_value(st, 0.5, 0, 4.0, 3.0), 0.5 * math.exp(-0.5))

    def test_project(self):
        line = core.ReferenceLine([[0, 0, 0], [100, 0, 0], [100, 100, 0]])
        s, t = line.project(110, 50)
        self.assertAlmostEqual(s, 150.0)
        self.assertAlmostEqual(t, -10.0)                               # right of a +Y heading is +X


class Ground(unittest.TestCase):
    """Layered ground materials (spec §8.7)."""

    def setUp(self):
        self.stage = core.load_document(STAGE)
        self.gm = self.stage["ground"]["materials"][0]

    def assertFinding(self, doc, level, fragment):
        found = messages(run(doc), level)
        self.assertTrue(any(fragment in m for m in found), f"no {level} containing {fragment!r} in {found}")

    def test_unknown_palette_layer(self):
        self.gm["palette"][3] = "moss"
        self.assertFinding(self.stage, "ERROR", "unknown ground layer 'moss'")

    def test_indices_outside_short_palette(self):
        self.gm["palette"] = self.gm["palette"][:2]
        self.assertFinding(self.stage, "ERROR", "indices outside the palette")

    def test_missing_attribute(self):
        self.gm["weights"]["weights"] = "stj_blend"
        self.assertFinding(self.stage, "ERROR", "primvar 'stj_blend' missing")

    def test_missing_texcoord_for_projection(self):
        self.stage["ground"]["layers"]["stage_grass"]["projection"] = {"texcoord": "uv9"}
        self.assertFinding(self.stage, "ERROR", "UV primvar 'uv9' missing")

    def test_unknown_material(self):
        self.gm["material"] = "Ground_Sec02"
        self.assertFinding(self.stage, "ERROR", "no mesh uses material 'Ground_Sec02'")

    def test_tile_given_as_scale(self):
        self.stage["ground"]["layers"]["rock"]["tile"] = 0.0625
        self.stage["ground"]["layers"]["stage_gravel"]["tile"] = 0.004
        self.assertFinding(self.stage, "WARN", "metres per repeat")

    def test_image_encoding_channels(self):
        self.gm["weights"] = {"encoding": "image", "maps": [{"uri": "ground/sec01_tint.png", "channels": "rgb"}], "texcoord": "st"}
        self.assertFinding(self.stage, "ERROR", "3 channels for 4 palette layers")

    def test_alpha_contradicts_height_flag(self):
        self.stage["ground"]["layers"]["rock"]["albedo"].update({"alpha": "specular", "height_in_alpha": True})
        self.assertFinding(self.stage, "ERROR", "contradicts height_in_alpha")

    def test_alpha_height_equals_flag(self):
        self.stage["ground"]["layers"]["rock"]["albedo"].update({"alpha": "height", "height_in_alpha": True})
        self.assertNotIn("contradicts", " ".join(messages(run(self.stage), "ERROR")))

    def test_roughness_and_occlusion_files_checked(self):
        self.stage["ground"]["layers"]["rock"]["roughness"] = {"uri": "ground/missing_r.png"}
        self.stage["ground"]["layers"]["rock"]["occlusion"] = {"uri": "ground/missing_o.png", "channel": "g"}
        found = " ".join(messages(run(self.stage), "WARN"))
        self.assertIn("missing_r.png", found)
        self.assertIn("missing_o.png", found)

    def test_mask_blend_needs_masks(self):
        self.gm["blend"] = {"method": "mask"}
        self.assertFinding(self.stage, "ERROR", "needs blend.mask")

    def test_mask_blend_count(self):
        self.gm["blend"] = {"method": "mask", "mask": {"uri": "ground/rock.png", "tile": 4.0}}
        self.assertFinding(self.stage, "ERROR", "one per layer after the first")

    def test_mask_blend_valid_is_provisional(self):
        n = len(self.gm["palette"]) - 1
        self.gm["blend"] = {"method": "mask", "mask": [{"uri": "ground/rock.png", "tile": 4.0}] * n}
        report = run(self.stage)
        self.assertFalse([m for m in messages(report, "ERROR") if "mask" in m])
        self.assertTrue(any("provisional" in m for m in messages(report, "NOTE")))

    def test_mask_blend_ignored_for_height(self):
        self.gm["blend"] = {"method": "height", "mask": {"uri": "ground/rock.png", "tile": 4.0}}
        self.assertFinding(self.stage, "NOTE", "only used by method 'mask'")

    def test_wetness_macro_is_valid(self):
        self.gm.setdefault("macro", []).append({"kind": "wetness", "uri": "ground/sec01_tint.png", "texcoord": "st"})
        self.assertFalse([m for m in messages(run(self.stage), "ERROR") if "macro" in m])

    def test_mask_blend_factors(self):
        flat = [0.5, 0.5]
        # layer 2's share is 0.7 against a mask of 0.5: fully layer 2; 0.3: fully layer 1
        self.assertEqual(core.ground_blend([0.3, 0.7], flat, flat, [1, 1], "mask", masks=[0.5]), [0.0, 1.0])
        self.assertEqual(core.ground_blend([0.7, 0.3], flat, flat, [1, 1], "mask", masks=[0.5]), [1.0, 0.0])
        # inside the transition: share equals the mask, so half and half
        f = core.ground_blend([0.5, 0.5], flat, flat, [1, 1], "mask", masks=[0.5])
        self.assertAlmostEqual(f[0], 0.5)
        self.assertAlmostEqual(f[1], 0.5)

    def test_mask_blend_chain_sums_to_one(self):
        f = core.ground_blend([0.4, 0.35, 0.25], [0] * 3, [0] * 3, [1] * 3, "mask", masks=[0.3, 0.5])
        self.assertAlmostEqual(sum(f), 1.0)
        self.assertTrue(all(x >= 0 for x in f))

    def test_mask_blend_needs_enough_masks(self):
        with self.assertRaises(ValueError):
            core.ground_blend([0.5, 0.3, 0.2], [0] * 3, [0] * 3, [1] * 3, "mask", masks=[0.5])

    def test_wet_amount(self):
        self.assertEqual(core.wet_amount(0.5, 1.0), 0.5)
        self.assertEqual(core.wet_amount(0.5, 0.0), 0.0)
        self.assertEqual(core.wet_amount(1.0, 1.0, strength=2.0), 1.0)

    def test_terrain_ground_layer(self):
        self.stage["geometry"]["terrain"]["layers"][0]["ground_layer"] = "lichen"
        self.assertFinding(self.stage, "ERROR", "unknown ground layer 'lichen'")

    def test_reference_blend(self):
        flat = [0.5] * 3
        self.assertEqual(core.ground_blend([0.6, 0.3, 0.1], flat, flat, [1, 1, 1]), [1.0, 0.0, 0.0])
        f = core.ground_blend([0.45, 0.4, 0.15], flat, flat, [1, 1, 1])
        self.assertAlmostEqual(f[0], 0.2 / 0.35)                      # within 0.2 of the top: both blend
        self.assertAlmostEqual(f[1], 0.15 / 0.35)
        # a high stone on the weaker layer wins against a low grass texel
        f = core.ground_blend([0.6, 0.4, 0.0], [0.2, 0.9, 0.5], flat, [1, 1, 1])
        self.assertAlmostEqual(f[1], 0.8)                              # scores 0.45 vs 0.6: the stone dominates
        self.assertEqual(core.ground_blend([1, 3, 0], flat, flat, flat, method="linear"), [0.25, 0.75, 0.0])

    def test_macro(self):
        self.assertEqual(core.apply_macro((0.4, 0.4, 0.4), [(0.5, "grey_centred")]), (0.4, 0.4, 0.4))
        self.assertAlmostEqual(core.apply_macro((0.4, 0.4, 0.4), [(0.75, "grey_centred"), (0.5, "multiply")])[0], 0.3)

    def test_bake_runs(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import ground_bake
        rows = ground_bake.bake(self.stage, EX, 0, 120, 24)
        centre, edge = rows[12][60], rows[1][60]
        self.assertNotEqual(centre, (0, 0, 0))
        self.assertNotEqual(centre, edge)                     # road gravel is not forest floor


class TerrainMacro(unittest.TestCase):
    """Macro maps over a heightfield terrain and the `colour` encoding (spec §7.4, §8.7)."""

    def setUp(self):
        self.stage = core.load_document(STAGE)
        self.ter = self.stage["geometry"]["terrain"]
        self.macro = self.ter["macro"][0]

    def assertFinding(self, doc, level, fragment):
        found = messages(run(doc), level)
        self.assertTrue(any(fragment in m for m in found), f"no {level} containing {fragment!r} in {found}")

    def clean(self, doc, levels=("ERROR", "WARN")):
        """Findings at these levels, without the variants' 'base is not this file' ones: run() writes the document
        as a loose .stj.json, so the stage's variant layers point at another file."""
        rep = run(doc)
        return [m for lv in levels for m in messages(rep, lv) if not m.startswith("variants[")]

    def temp_png(self, name, width, height, values, channels):
        path = EX / "terrain" / name
        core.write_png(path, width, height, values, channels)
        self.addCleanup(path.unlink)
        return f"terrain/{name}"

    def test_example_carries_a_colour_macro(self):
        self.assertEqual(self.macro["encoding"], "colour")
        self.assertNotIn("extent", self.macro)                     # defaults to the heightmap's
        self.assertEqual(self.clean(self.stage), [])

    def test_schema_rejects_a_bad_encoding_and_strength(self):
        self.macro["encoding"] = "bogus"
        self.assertFinding(self.stage, "ERROR", "'bogus' is not one of")
        self.macro["encoding"] = "colour"
        self.macro["strength"] = 2
        self.assertFinding(self.stage, "ERROR", "greater than the maximum of 1")

    def test_schema_rejects_a_texcoord(self):
        self.macro["texcoord"] = "st"                              # a heightfield has no UVs
        self.assertFinding(self.stage, "ERROR", "texcoord")

    def test_missing_file(self):
        self.macro["uri"] = "terrain/none.png"
        self.assertFinding(self.stage, "WARN", "file not found: terrain/none.png")

    def test_not_a_png(self):
        self.macro["uri"] = "meshes/coll_de_prova_collision.usda"
        self.assertFinding(self.stage, "ERROR", "not a PNG file")

    def test_extent_covering_the_terrain_is_fine_and_a_part_of_it_warns(self):
        x0, y0, x1, y1 = self.ter["heightmap"]["extent"]
        self.macro["extent"] = [x0, y0, x1, y1]
        self.assertEqual(self.clean(self.stage), [])
        self.macro["extent"] = [x0, y0, (x0 + x1) / 2, y1]
        self.assertFinding(self.stage, "WARN", "covers 50 % of the terrain")
        self.macro["extent"] = [x1, y1, x0, y0]
        self.assertFinding(self.stage, "ERROR", "extent must be [x_min, y_min, x_max, y_max]")

    def test_a_greyscale_colour_map_warns(self):
        self.macro["uri"] = self.temp_png("_grey_macro.png", 4, 4, [100] * 16, 1)
        self.assertFinding(self.stage, "WARN", "greyscale and has no hue")
        self.macro["encoding"] = "grey_centred"                     # a grey map is what that encoding wants
        self.assertEqual(self.clean(self.stage, ("WARN",)), [])

    def test_two_colour_maps_warn(self):
        self.ter["macro"].append(dict(self.macro))
        self.assertFinding(self.stage, "WARN", "more than one colour map")

    def test_an_occlusion_kind_with_the_colour_encoding_warns(self):
        self.macro["kind"] = "occlusion"
        self.assertFinding(self.stage, "WARN", "average colour, not occlusion")

    def test_a_second_colour_map_retargets_instead_of_compounding(self):
        a = core.apply_macro((0.2, 0.2, 0.2), [((0.4, 0.4, 0.4), "colour")])
        twice = core.apply_macro((0.2, 0.2, 0.2), [((0.4, 0.4, 0.4), "colour"), ((0.4, 0.4, 0.4), "colour")])
        self.assertEqual(a, twice)                                             # the same map twice changes nothing more
        last = core.apply_macro((0.2, 0.2, 0.2), [((0.4, 0.4, 0.4), "colour"), ((0.3, 0.3, 0.3), "colour")])
        self.assertAlmostEqual(last[0], 0.3)                                   # only the last map shows
        mixed = core.apply_macro((0.2, 0.2, 0.2), [(0.5, "multiply"), ((0.2, 0.2, 0.2), "colour")], (0.2, 0.2, 0.2))
        self.assertAlmostEqual(mixed[0], 0.2)                                  # a colour map after a multiply still lands on its value

    def test_strength_is_ignored_outside_the_colour_encoding(self):
        self.macro["encoding"] = "multiply"
        self.macro["strength"] = 0.5
        self.assertFinding(self.stage, "NOTE", "only the colour encoding uses strength")

    def test_a_terrain_without_ground_layers_gets_a_note(self):
        del self.ter["layers"][0]["ground_layer"]
        self.assertFinding(self.stage, "NOTE", "no ground layers: the map acts on the base colour only")

    def test_macro_on_several_terrains_is_checked_too(self):
        t = json.loads(json.dumps(self.ter))
        t["id"] = "second"
        t["macro"][0]["uri"] = "terrain/none.png"
        self.stage["geometry"]["terrains"] = [t]
        self.assertFinding(self.stage, "WARN", "geometry.terrains[0].macro[0].uri: file not found")

    def test_colour_is_accepted_on_a_ground_material_too(self):
        gm = self.stage["ground"]["materials"][0]
        gm["macro"][0]["encoding"] = "colour"
        gm["macro"][0]["strength"] = 0.5
        self.assertEqual(self.clean(self.stage, ("ERROR",)), [])

    def test_version_check(self):
        doc = json.loads(json.dumps(self.stage))
        for key in ("marshals", "dynamic", "screens"):
            doc.pop(key, None)
        for key in ("probes", "climate"):
            doc["environment"].pop(key, None)
        doc.get("scenery", {}).pop("crowds", None)
        doc["_metadata"]["version"] = "0.2"
        self.assertFinding(doc, "WARN", "geometry.terrain.macro")
        del doc["geometry"]["terrain"]["macro"]
        doc["ground"]["materials"][0]["macro"][0]["encoding"] = "colour"
        self.assertFinding(doc, "WARN", "ground macro encoding 'colour'")

    def test_apply_macro_colour(self):
        base = (0.4, 0.3, 0.2)
        macro = (0.6, 0.3, 0.1)
        # the detail is its layers' average: the result is the map
        out = core.apply_macro(base, [(macro, "colour")], base)
        self.assertEqual([round(c, 9) for c in out], list(macro))
        # a brighter texel keeps its texture: it is scaled by the same ratio (1.5, 1.0, 0.5)
        out = core.apply_macro((0.8, 0.6, 0.4), [(macro, "colour")], base)
        self.assertEqual([round(c, 9) for c in out], [1.2, 0.6, 0.2])
        # strength 0 leaves it alone, 0.5 goes half way
        self.assertEqual(core.apply_macro((0.8, 0.6, 0.4), [(macro, "colour", 0.0)], base), (0.8, 0.6, 0.4))
        half = core.apply_macro((0.8, 0.6, 0.4), [(macro, "colour", 0.5)], base)
        self.assertEqual([round(c, 9) for c in half], [1.0, 0.6, 0.3])
        # a macro far from the layers' colour is held to the ratio range
        out = core.apply_macro((0.5, 0.5, 0.5), [((100.0, 0.0, 0.0), "colour")], (1.0, 1.0, 1.0))
        self.assertEqual(out, (0.5 * 4.0, 0.5 * 0.25, 0.5 * 0.25))
        # without a base, the colour is its own base
        self.assertEqual([round(c, 9) for c in core.apply_macro(base, [(macro, "colour")])], list(macro))
        # the other encodings are unchanged, with or without a strength in the tuple
        self.assertAlmostEqual(core.apply_macro((0.4, 0.4, 0.4), [(0.75, "grey_centred", 0.1), (0.5, "multiply")])[0], 0.3)

    def test_ground_mean_colour_and_srgb(self):
        self.assertEqual(core.ground_mean_colour([1, 3], [(0.0, 0.0, 0.0), (0.4, 0.8, 0.2)]),
                         (0.30000000000000004, 0.6000000000000001, 0.15000000000000002))
        self.assertEqual(core.ground_mean_colour([0, 0], [(1, 1, 1), (1, 1, 1)]), (0.0, 0.0, 0.0))
        self.assertEqual((core.srgb_to_linear(0.0), core.srgb_to_linear(1.0)), (0.0, 1.0))
        self.assertAlmostEqual(core.srgb_to_linear(0.5), 0.21404, places=4)

    def test_bake_replaces_the_layers_average_colour(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import ground_bake
        gm = self.stage["ground"]["materials"][0]
        flat = self.temp_png("_flat_macro.png", 4, 4, [130, 100, 70] * 16, 3)
        target = [ground_bake.srgb_to_linear(c) for c in (130, 100, 70)]

        def average(strength):
            """Mean colour, in linear light, of the covered pixels of the bake."""
            gm["macro"] = [] if strength is None else [{"kind": "tint", "uri": flat, "texcoord": "st",
                                                         "encoding": "colour", "strength": strength}]
            rows = ground_bake.bake(self.stage, EX, 0, 120, 24)
            px = [p for row in rows for p in row if p != (0, 0, 0)]
            self.assertGreater(len(px), 500)
            return [sum(ground_bake.srgb_to_linear(p[c]) for p in px) / len(px) for c in range(3)]

        plain, full, half = average(None), average(1.0), average(0.5)
        for c in range(3):
            # the macro moves the average to its own colour (the blend only roughly matches the weights' mean)
            self.assertAlmostEqual(full[c], target[c], delta=0.12 * target[c])
            self.assertLess(abs(full[c] - target[c]), abs(plain[c] - target[c]))
            # strength 0.5 sits between the plain blend and the full replacement
            self.assertTrue(min(plain[c], full[c]) <= half[c] <= max(plain[c], full[c]))
        # strength 0 is the plain blend
        self.assertEqual(average(0.0), plain)


class LessonsFromRbr(unittest.TestCase):
    """Surface maps, states, absolute mu, chainage and the smaller additions."""

    def setUp(self):
        self.stage = core.load_document(STAGE)
        self.maps = self.stage["surfaces"]["maps"]

    def assertFinding(self, doc, level, fragment):
        found = messages(run(doc), level)
        self.assertTrue(any(fragment in m for m in found), f"no {level} containing {fragment!r} in {found}")

    def test_example_has_the_features(self):
        s = self.stage
        self.assertEqual(len(self.maps), 2)
        self.assertIn("chainage", s["reference"]["centerline"])
        self.assertTrue(any(b.get("when") for b in s["water"]["bodies"]))
        self.assertTrue(any(e["kind"] == "invisible" for e in s["edges"]))

    def test_surface_map_unknown_surface(self):
        self.maps[1]["palette"][1] = "hardpack"
        self.assertFinding(self.stage, "ERROR", "unknown surface 'hardpack'")

    def test_surface_map_indices_outside_palette(self):
        self.maps[1]["palette"] = self.maps[1]["palette"][:2]
        self.assertFinding(self.stage, "ERROR", "indices outside the palette")

    def test_surface_map_unreachable(self):
        self.maps.reverse()                                  # the unconditional map now hides the worn one
        self.assertFinding(self.stage, "WARN", "never used")

    def test_wear_signal_values(self):
        self.maps[0]["when"]["value"] = 75
        self.assertFinding(self.stage, "WARN", "check the unit")

    def test_mu_needs_reference(self):
        del self.stage["surfaces"]["reference_mu"]["gravel"]
        self.assertFinding(self.stage, "ERROR", "needs surfaces.reference_mu.gravel")

    def test_mu_sliding_above_peak(self):
        self.stage["surfaces"]["library"]["gravel_rutted"]["by_tyre_class"]["gravel"]["mu"]["sliding"] = 0.95
        self.assertFinding(self.stage, "WARN", "sliding mu above peak mu")

    def test_chainage_mismatch(self):
        cl = self.stage["reference"]["centerline"]
        cl["chainage"] = [c * 1.05 for c in cl["chainage"]]
        self.assertFinding(self.stage, "WARN", "more than 1% apart")

    def test_chainage_must_increase(self):
        cl = self.stage["reference"]["centerline"]
        cl["chainage"][5] = cl["chainage"][4]
        self.assertFinding(self.stage, "ERROR", "must increase")

    def test_chainage_count(self):
        self.stage["reference"]["centerline"]["chainage"].pop()
        self.assertFinding(self.stage, "ERROR", "values for")

    def test_invisible_edge_needs_behaviour(self):
        del next(e for e in self.stage["edges"] if e["kind"] == "invisible")["behaviour"]
        self.assertFinding(self.stage, "ERROR", "needs a behaviour")

    def test_weather_option_variant(self):
        self.stage["environment"]["weather_options"][1]["variant"] = "snowstorm"
        self.assertFinding(self.stage, "ERROR", "unknown variant 'snowstorm'")

    def test_sections_order(self):
        sec = self.stage["race"]["sections"][1]
        sec["s_end"] = sec["s_start"] - 10
        self.assertFinding(self.stage, "ERROR", "s_end must be after s_start")

    def test_reflections_order(self):
        self.stage["audio"]["reflections"][2][0] = 1700.0
        self.assertFinding(self.stage, "ERROR", "s must increase")

    def test_distance_to_next_checked(self):
        self.stage["race"]["pacenotes"]["notes"][0]["distance_to_next"] = 500
        self.assertFinding(self.stage, "WARN", "the next note is")

    def test_bendable_without_stiffness(self):
        del self.stage["scenery"]["prototypes"]["birch_sapling"]["physics"]["stiffness"]
        self.assertFinding(self.stage, "WARN", "bendable without stiffness")

    def test_hermite_line(self):
        r = 100.0
        line = core.ReferenceLine([[r, 0, 0], [0, r, 0]], tangents=[[0, r * math.pi / 2, 0], [-r * math.pi / 2, 0, 0]])
        self.assertAlmostEqual(line.length, r * math.pi / 2, delta=2.0)     # a cubic close to the quarter circle
        x, y, _z, h = line.frame(0.0)
        self.assertAlmostEqual(h, math.pi / 2)                             # leaves heading +Y
        s, t = line.project(*line.point(60.0, 2.0)[:2])
        self.assertAlmostEqual(s, 60.0, delta=0.5)
        self.assertAlmostEqual(t, 2.0, delta=0.05)

    def test_chainage_defines_s(self):
        line = core.ReferenceLine([[0, 0, 0], [100, 0, 0], [100, 50, 0]], chainage=[0, 101, 152])
        self.assertEqual(line.length, 152)
        self.assertAlmostEqual(line.point(101)[0], 100.0)                 # the stored distance reaches the corner
        rev = core.reverse_reference({"centerline": {"points": [[0, 0, 0], [100, 0, 0], [100, 50, 0]], "chainage": [0, 101, 152]}})
        self.assertEqual(rev["centerline"]["chainage"], [0.0, 51.0, 152.0])


class Tier3(unittest.TestCase):
    """v0.3: race control, evolution laws, large worlds, presentation."""

    def setUp(self):
        self.gp = core.load_document(GP)
        self.stage = core.load_document(STAGE)

    def assertFinding(self, doc, level, fragment):
        found = messages(run(doc), level)
        self.assertTrue(any(fragment in m for m in found), f"no {level} containing {fragment!r} in {found}")

    def test_sector_flag_needs_sectors(self):
        del self.gp["marshals"]["sectors"]
        del self.gp["marshals"]["posts"][0]["sector"], self.gp["marshals"]["posts"][1]["sector"]
        self.assertFinding(self.gp, "WARN", "no marshal sectors are defined")

    def test_post_outside_its_sector(self):
        self.gp["marshals"]["posts"][0]["s"] = 100.0
        self.assertFinding(self.gp, "WARN", "outside sector 'm2'")

    def test_sectors_must_join(self):
        self.gp["marshals"]["sectors"][2]["s_start"] += 20
        self.assertFinding(self.gp, "WARN", "do not join")

    def test_vehicle_base(self):
        self.gp["marshals"]["vehicles"][1]["base"] = "post_t9"
        self.assertFinding(self.gp, "ERROR", "unknown post 'post_t9'")

    def test_penalty_needs_value(self):
        del self.gp["marshals"]["restricted_zones"][0]["value"]
        self.assertFinding(self.gp, "ERROR", "needs a value")

    def test_speed_limit_in_kmh(self):
        self.stage["marshals"]["restricted_zones"][0]["value"] = 30
        self.assertFinding(self.stage, "WARN", "km/h given?")

    def test_reset_points_only(self):
        self.gp["marshals"]["reset"] = {"mode": "points_only"}
        self.assertFinding(self.gp, "ERROR", "without points")

    def test_dynamic_line_state(self):
        self.gp["dynamic"]["line_states"][0]["line_state"] = "groove"
        self.assertFinding(self.gp, "ERROR", "unknown line state 'groove'")

    def test_ruts(self):
        self.stage["dynamic"]["ruts"][0]["depth_per_pass"] = 0.2
        self.assertFinding(self.stage, "ERROR", "depth_per_pass cannot exceed max_depth")

    def test_chunks(self):
        geo = self.gp["geometry"]
        geo["meshes"][0]["chunk"] = "c1"
        geo["chunks"] = [{"id": "c1", "s_start": 0.0, "s_end": 500.0, "origin": [0.0, 0.0, 0.0], "meshes": ["props"]},
                         {"id": "c2", "s_start": 520.0, "s_end": 970.0, "origin": [100.0, 0.0, 0.0], "terrain": "t9"}]
        rep = run(self.gp)
        errs = [e for e in messages(rep, "ERROR") if not e.startswith("variants")]   # the temp copy is not the variants' base
        self.assertEqual(errs, ["geometry.chunks[1].terrain: unknown terrain 't9'"])
        self.assertTrue(any("do not join" in w for w in messages(rep, "WARN")))
        geo["meshes"][0]["chunk"] = "c7"
        self.assertFinding(self.gp, "ERROR", "unknown chunk 'c7'")

    def test_chunk_mesh_without_chunk(self):
        self.gp["geometry"]["chunks"] = [{"id": "c1", "s_start": 0.0, "s_end": 977.0, "origin": [0.0, 0.0, 0.0], "meshes": ["props"]}]
        self.assertFinding(self.gp, "WARN", "does not say chunk 'c1'")

    def test_tiles(self):
        self.gp["geometry"]["tiles"] = {"size": 500.0, "origin": [-500.0, -500.0, 0.0],
                                        "items": [{"index": [0, 0], "meshes": ["props"]}, {"index": [0, 0]}]}
        self.assertFinding(self.gp, "ERROR", "appears twice")

    def test_terrains_need_ids(self):
        ter = self.stage["geometry"].pop("terrain")
        self.stage["geometry"]["terrains"] = [ter]
        self.assertFinding(self.stage, "ERROR", "need an id")

    def test_screen_image_needs_uri(self):
        self.gp["screens"][0]["content"] = "image"
        self.assertFinding(self.gp, "ERROR", "needs a uri")

    def test_screen_node(self):
        self.gp["screens"][0]["target"]["prim"] = "/track/props/Screen"
        self.assertFinding(self.gp, "ERROR", "prim '/track/props/Screen' not in")

    def test_crowd(self):
        c = self.stage["scenery"]["crowds"][0]
        del c["flee_distance"]
        c["prototype"] = "fan"
        rep = run(self.stage)
        self.assertTrue(any("unknown prototype 'fan'" in e for e in messages(rep, "ERROR")))
        self.assertTrue(any("flee without flee_distance" in w for w in messages(rep, "WARN")))

    def test_climate(self):
        m = self.gp["environment"]["climate"]["monthly"]
        m[1]["month"] = 1
        m[2]["t_min"] = 30
        rep = run(self.gp)
        errs = messages(rep, "ERROR")
        self.assertTrue(any("month 1 appears twice" in e for e in errs), errs)
        self.assertTrue(any("t_min above t_max" in e for e in errs), errs)

    def test_v03_keys_in_v02_file(self):
        self.gp["_metadata"]["version"] = "0.2"
        self.assertFinding(self.gp, "WARN", "declares 0.2 but uses v0.3 features")

    def test_reference_laws(self):
        lvl = 0.2
        for _ in range(100):
            lvl += 0.01 * (1 - lvl)
        self.assertAlmostEqual(core.line_state_after_passes(0.2, 0.01, 100), lvl)
        d = 0.0
        for _ in range(50):
            d += 0.002 * (1 - d / 0.08)
        self.assertAlmostEqual(core.rut_depth_after_passes(0.0, 0.002, 0.08, 50), d)
        self.assertAlmostEqual(core.wear_from_cars(60, 60), 1 - math.exp(-1))
        self.assertAlmostEqual(core.dew_point(20.0, 1.0), 20.0, places=6)
        # a 1 mm film under 4 mm/h of rain with 1 mm/h drainage grows 3 mm/h
        self.assertAlmostEqual(core.water_step(0.001, 3600, 4.0, 1.0, 0.0), 0.004)
        self.assertEqual(core.water_step(0.0005, 3600, 0.0, 2.0, 0.5), 0.0)       # never below zero
        self.assertAlmostEqual(core.line_state_washed(0.5, 0.05, 4.0, 3600), 0.5 * math.exp(-0.2))
        t = core.track_temperature_step(20.0, 1e9, 20.0, 18.0, 1.0, 0.5, 1800.0)
        self.assertAlmostEqual(t, 29.0)                                          # half shade: half the sun gain


@unittest.skipUnless(core.have_pxr(), "needs the pxr module (pip install usd-core)")
class OpenUsd(unittest.TestCase):
    """STJ with OpenUSD: USD meshes, the document inside a layer, .usdz packages (spec §7.7, §7.8)."""

    def setUp(self):
        import shutil
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        for name in ("test_ring_blend.usda", "test_ring_blend_wet.usda"):
            shutil.copy(EX / name, self.dir / name)
        self.track = self.dir / "test_ring_blend.usda"
        self.doc = core.usd_document(self.track)

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, doc=None):
        if doc is not None:
            core.embed_document(doc, self.track)
        return validate.validate(self.track)

    def assertFinding(self, rep, level, fragment):
        found = messages(rep, level)
        self.assertTrue(any(fragment in m for m in found), f"no {level} containing {fragment!r} in {found}")

    def test_extract_matches_embedded(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import stj_usd
        out = self.dir / "out.stj.json"
        stj_usd.main(["extract", str(EX / "test_ring_blend.usdz"), "-o", str(out)])
        self.assertEqual(core.load_json(out), core.usd_document(EX / "test_ring_blend.usda"))

    def test_layer_index_outside_palette(self):
        from pxr import Usd, UsdGeom
        st = Usd.Stage.Open(str(self.track))
        pv = UsdGeom.PrimvarsAPI(st.GetPrimAtPath("/track/ribbon")).GetPrimvar("stj_surf_layers_2")
        vals = list(pv.Get())
        vals[0] = 9
        pv.Set(vals)
        st.GetRootLayer().Save()
        self.assertFinding(self.check(), "ERROR", "indices outside the palette")

    def test_missing_primvar(self):
        self.doc["surfaces"]["maps"][0]["weights"]["weights"] = "stj_blend"
        self.assertFinding(self.check(self.doc), "ERROR", "primvar 'stj_blend' missing")

    def test_unknown_usd_variant(self):
        self.doc["variants"][0]["usd_variants"] = {"stj_condition": "snow"}
        self.assertFinding(self.check(self.doc), "ERROR", "variant 'snow' not in set 'stj_condition'")

    def test_target_needs_time_range_or_kind(self):
        del self.doc["animated_objects"][0]["time_range"]
        del self.doc["animated_objects"][0]["kind"]
        self.assertFinding(self.check(self.doc), "ERROR", "is not valid under any of the given schemas")

    def test_engine_driven_object_needs_an_engine_block(self):
        del self.doc["animated_objects"][0]["time_range"]
        self.doc["animated_objects"][0]["kind"] = "clock"
        self.assertFinding(self.check(self.doc), "WARN", "nothing says how it moves")
        self.doc["animated_objects"][0]["x_rbr"] = {"script": "StartClock"}
        self.assertFalse(any("nothing says" in m for m in messages(self.check(self.doc), "WARN")))

    def test_physics_disagreement(self):
        self.doc["scenery"]["prototypes"]["cone"]["physics"]["mass"] = 6.0
        self.assertFinding(self.check(self.doc), "WARN", "the STJ JSON is normative")

    def test_stage_axes(self):
        from pxr import Usd, UsdGeom
        st = Usd.Stage.Open(str(self.track))
        UsdGeom.SetStageUpAxis(st, UsdGeom.Tokens.y)
        st.GetRootLayer().Save()
        self.assertFinding(self.check(), "WARN", "upAxis Y")

    def test_usdz_holds_no_json(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import stj_usd
        (self.dir / "notes.json").write_text("{}")
        with self.assertRaises(SystemExit):
            stj_usd.write_usdz(self.track, self.dir / "x.usdz", {"notes.json"})

    def test_usdz_alignment(self):
        import zipfile
        with zipfile.ZipFile(EX / "test_ring_blend.usdz") as z:
            infos = z.infolist()
            self.assertEqual(infos[0].filename, "test_ring_blend.usda")            # root layer first
            raw = (EX / "test_ring_blend.usdz").read_bytes()
            for info in infos:
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
                name_len, extra_len = struct.unpack_from("<HH", raw, info.header_offset + 26)
                self.assertEqual((info.header_offset + 30 + name_len + extra_len) % 64, 0, info.filename)



class RbrGaps(unittest.TestCase):
    """Additions from the RBR conversion (tangents, fixed lighting, engine-driven things)."""

    def setUp(self):
        self.doc = core.load_document(STAGE)

    def finding(self, level, fragment):
        found = messages(run(self.doc), level)
        self.assertTrue(any(fragment in m for m in found), f"no {level} containing {fragment!r} in {found}")

    def test_per_segment_tangents(self):
        # two segments of different length with their own tangents meeting at a point
        line = core.ReferenceLine([[0, 0, 0], [10, 0, 0], [33, 0, 0]],
                                  tangents_out=[[10, 0, 0], [23, 0, 0], [23, 0, 0]],
                                  tangents_in=[[10, 0, 0], [10, 0, 0], [23, 0, 0]])
        self.assertAlmostEqual(line.frame(5.0)[0], 5.0)
        self.assertAlmostEqual(line.frame(21.5)[0], 21.5)
        self.assertAlmostEqual(line.length, 33.0)

    def test_shared_tangent_cannot_fit_both_lengths(self):
        # the old single tangent per point is wrong for one of the two segments: the curve bulges
        line = core.ReferenceLine([[0, 0, 0], [10, 0, 0], [33, 0, 0]],
                                  tangents=[[10, 0, 0], [16.5, 0, 0], [23, 0, 0]])
        self.assertNotAlmostEqual(line.frame(2.5)[0], 2.5, places=2)

    def test_tangents_in_defaults_to_out(self):
        line = core.ReferenceLine([[0, 0, 0], [10, 0, 0]], tangents_out=[[10, 0, 0], [10, 0, 0]])
        self.assertEqual(line.t_in, line.t_out)

    def test_reverse_swaps_in_and_out(self):
        ref = {"centerline": {"points": [[0, 0, 0], [10, 0, 0], [33, 0, 0]],
                              "tangents_out": [[10, 0, 0], [23, 0, 0], [23, 0, 0]],
                              "tangents_in": [[10, 0, 0], [10, 0, 0], [23, 0, 0]]}}
        rev = core.reverse_reference(ref)["centerline"]
        self.assertEqual(rev["tangents_out"][0], [-23, 0, 0])      # first segment of the reversed line is the 23 m one
        self.assertEqual(rev["tangents_out"][1], [-10, 0, 0])
        line = core.reference_line({"reference": core.reverse_reference(ref)})
        self.assertAlmostEqual(line.length, 33.0)

    def test_tangents_in_needs_out(self):
        self.doc["reference"]["centerline"]["tangents_in"] = self.doc["reference"]["centerline"]["points"]
        self.finding("ERROR", "tangents_in needs tangents_out")

    def test_sun_direction_checks(self):
        self.doc["environment"]["lighting"] = {"sun": {"direction": [0, 0, 2]}}
        self.finding("WARN", "a unit vector is expected")
        self.doc["environment"]["lighting"] = {"sun": {"direction": [0.6, 0, -0.8]}}
        self.finding("NOTE", "below the horizon")

    def test_ambient_and_schedule_variant(self):
        self.doc["environment"]["lighting"] = {"ambient": {"color": [0.5, 0.5, 0.5]}}
        self.doc["environment"]["weather_schedule"] = [{"session": "race", "time": 0, "variant": "no_such"}]
        self.finding("ERROR", "unknown variant 'no_such'")

    def test_emitter_without_a_sound_file(self):
        self.doc.setdefault("audio", {})["emitters"] = [{"id": "start_voice", "position": [0, 0, 0]}]
        self.finding("ERROR", "no sound file and no x_<engine> block")
        self.doc["audio"]["emitters"][0]["x_rbr"] = {"sound_event": "start_countdown"}
        self.assertFalse(any("no sound file" in m for m in messages(run(self.doc), "ERROR")))

    def test_visual_water_needs_a_mesh(self):
        self.doc.setdefault("water", {})["bodies"] = [{"id": "deco", "kind": "lake", "physical": False,
                                                       "outline": [[0, 0], [10, 0], [0, 10]], "level": 0, "depth": 2}]
        self.finding("WARN", "needs a mesh to draw")
        self.finding("NOTE", "physical is false")

    def test_baked_lighting_and_reflective(self):
        mesh = self.doc["geometry"]["meshes"][0]
        mesh["baked"] = {"shadow_map": {"uri": "missing_shadow.png", "texcoord": "st"},
                         "vertex_colour": {"primvar": "displayColor", "role": "light"}}
        self.finding("WARN", "missing_shadow.png")
        mesh["roles"] = ["collision"]
        mesh["reflective"] = True
        self.finding("WARN", "put the mirror on a separate visual mesh")

    def test_wind_values(self):
        proto = next(iter(self.doc["scenery"]["prototypes"].values()))
        proto["wind"] = {"amplitude": 40, "frequency": 2}
        self.finding("WARN", "unit slip")



def write_las(path, points, fmt=0, scale=0.01):
    """A minimal uncompressed LAS 1.2 file; points are (x, y, z, classification)."""
    rec = {0: 20, 1: 28}[fmt]
    head = bytearray(227)
    head[0:4] = b"LASF"
    head[24], head[25] = 1, 2
    struct.pack_into("<HI", head, 94, 227, 227)
    struct.pack_into("<I", head, 100, 0)
    head[104] = fmt
    struct.pack_into("<HI", head, 105, rec, len(points))
    struct.pack_into("<6d", head, 131, scale, scale, scale, 0.0, 0.0, 0.0)
    body = bytearray()
    for x, y, z, c in points:
        r = bytearray(rec)
        struct.pack_into("<3i", r, 0, round(x / scale), round(y / scale), round(z / scale))
        r[15] = c
        body += r
    Path(path).write_bytes(bytes(head) + bytes(body))


class LidarSupport(unittest.TestCase):
    """LAS gridding, no-data cells and the scan records (spec §5.2, §7.4)."""

    def setUp(self):
        import las_dtm
        self.las_dtm = las_dtm
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        # a 5 x 5 patch of ground, one point per vertex, z = x + 2y, plus a tree top (class 5) and a withheld-free noise point
        self.ground = [(float(x), float(y), x + 2.0 * y, 2) for x in range(5) for y in range(5)]
        self.pts = self.ground + [(2.0, 2.0, 30.0, 5)]
        self.las = self.dir / "tile.las"
        write_las(self.las, self.pts)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_classes(self):
        ground = list(self.las_dtm.read_points(self.las, [2]))
        self.assertEqual(len(ground), 25)
        self.assertEqual(len(list(self.las_dtm.read_points(self.las, None))), 26)
        self.assertAlmostEqual(ground[7][2], ground[7][0] + 2 * ground[7][1], places=6)

    def test_agrees_with_laspy(self):
        try:
            import laspy
        except ImportError:
            self.skipTest("laspy is not installed")
        las = laspy.read(str(self.las))
        mine = list(self.las_dtm.read_points(self.las, None))
        self.assertEqual(len(las.x), len(mine))
        self.assertAlmostEqual(float(las.z[7]), mine[7][2], places=6)
        self.assertEqual(int(las.classification[25]), mine[25][3])

    def test_not_a_las_file(self):
        bad = self.dir / "bad.las"
        bad.write_bytes(b"not a las file at all" * 20)
        with self.assertRaises(self.las_dtm.LasError):
            list(self.las_dtm.read_points(bad))

    def test_grid_is_vertex_registered_north_first(self):
        pts = list(self.las_dtm.read_points(self.las, [2]))
        nx, ny, h, used = self.las_dtm.grid(pts, [0, 0, 4, 4], 1.0)
        self.assertEqual((nx, ny, used), (5, 5, 25))
        self.assertAlmostEqual(h[0], 0 + 2 * 4)          # row 0 is the north edge: x = 0, y = 4
        self.assertAlmostEqual(h[4 * 5 + 4], 4 + 0)      # last row is the south edge: x = 4, y = 0

    def test_voids_and_fill(self):
        pts = [p for p in self.las_dtm.read_points(self.las, [2]) if (p[0], p[1]) != (2.0, 2.0)]
        nx, ny, h, _ = self.las_dtm.grid(pts, [0, 0, 4, 4], 1.0)
        self.assertIsNone(h[2 * 5 + 2])
        filled = self.las_dtm.fill_voids(h, nx, ny, 2)
        self.assertAlmostEqual(filled[2 * 5 + 2], 6.0, places=1)      # the plane's value at (2, 2): 2 + 4

    def run_tool(self, *extra):
        out = self.dir / "height"
        records = self.dir / "records.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.las_dtm.main([str(self.las), "-o", str(out), "--cell", "1.0", "--source-id", "als",
                               "--crs", "EPSG:25831", "--json", str(records), *extra])
        return out, json.loads(records.read_text(encoding="utf-8"))

    def terrain(self, block, out):
        return core.Terrain({"heightmap": {**block, "uri": out.name}}, self.dir)

    def test_tool_raw_f32_round_trip(self):
        out, rec = self.run_tool("--format", "raw_f32")
        block = rec["heightmap"]
        self.assertEqual((block["format"], block["size"], block["nodata"]), ("raw_f32", [5, 5], -9999.0))
        self.assertEqual(block["derived"], {"source": "als", "product": "dtm", "classes": [2], "cell_size": 1.0,
                                            "method": "binning", "void_fill": "none"})
        ter = self.terrain(block, out)
        self.assertEqual(ter.void_count, 0)
        self.assertAlmostEqual(ter.height(0.0, 0.0), 0.0, places=4)
        self.assertAlmostEqual(ter.height(4.0, 4.0), 12.0, places=4)
        self.assertEqual(rec["scan_source"]["crs"], "EPSG:25831")

    def test_tool_png16_nodata_is_a_void(self):
        # drop one ground point: the vertex has no measurement and takes the nodata code
        write_las(self.las, [p for p in self.pts if (p[0], p[1]) != (3.0, 3.0)])
        out, rec = self.run_tool("--format", "png16", "--extent", "0", "0", "4", "4")
        block = rec["heightmap"]
        self.assertEqual(block["nodata"], 0)
        ter = self.terrain(block, out)
        self.assertEqual(ter.void_count, 1)
        self.assertIsNone(ter.height(3.0, 3.0))
        self.assertAlmostEqual(ter.height(1.0, 1.0), 3.0, places=2)
        self.assertEqual(block["derived"]["void_fill"], "none")

    def test_tool_fill_records_the_method(self):
        write_las(self.las, [p for p in self.pts if (p[0], p[1]) != (3.0, 3.0)])
        out, rec = self.run_tool("--format", "raw_f32", "--extent", "0", "0", "4", "4", "--fill-radius", "2")
        self.assertEqual(rec["heightmap"]["derived"]["void_fill"], "interpolated")
        self.assertEqual(self.terrain(rec["heightmap"], out).void_count, 0)

    def test_no_points_of_the_class(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stdout(io.StringIO()):
                self.las_dtm.main([str(self.las), "-o", str(self.dir / "h"), "--cell", "1", "--classes", "9"])


class ScanRecords(unittest.TestCase):
    """provenance.scan.sources and derived (spec §5.2)."""

    def setUp(self):
        self.doc = core.load_document(STAGE)
        self.hm = self.doc["geometry"]["terrain"]["heightmap"]
        self.md = self.doc["_metadata"]
        self.md["provenance"] = {"type": "scanned", "scan": {"method": "lidar", "sources": [
            {"id": "als", "format": "laz", "reference": "tile 0404", "crs": "EPSG:25831", "point_density": 8.0,
             "classified": True}]}}

    def finding(self, level, fragment):
        found = messages(run(self.doc), level)
        self.assertTrue(any(fragment in m for m in found), f"no {level} containing {fragment!r} in {found}")

    def test_unknown_source(self):
        self.hm["derived"] = {"source": "nope", "product": "dtm"}
        self.finding("ERROR", "unknown source 'nope'")

    def test_source_without_crs(self):
        del self.md["provenance"]["scan"]["sources"][0]["crs"]
        self.hm["derived"] = {"source": "als", "product": "dtm", "cell_size": 1.0}
        self.finding("WARN", "has no crs")

    def test_cell_finer_than_the_density_allows(self):
        # 8 points per m2: about 0.71 m between points, so a 0.2 m cell is interpolated
        self.hm["derived"] = {"source": "als", "product": "dtm", "cell_size": 0.2}
        self.finding("NOTE", "detail below that is interpolated")

    def test_cell_the_density_supports_is_quiet(self):
        self.hm["derived"] = {"source": "als", "product": "dtm", "cell_size": 2.0}
        self.assertFalse(any("interpolated" in m for m in messages(run(self.doc), "NOTE")))

    def test_classes_on_an_unclassified_source(self):
        self.md["provenance"]["scan"]["sources"][0]["classified"] = False
        self.hm["derived"] = {"source": "als", "product": "dtm", "classes": [2], "cell_size": 2.0}
        self.finding("WARN", "is not classified")

    def test_png16_nodata_must_be_a_code(self):
        self.hm["format"] = "png16"
        self.hm["nodata"] = -9999.5
        self.finding("ERROR", "16-bit integer code")

    def test_duplicate_source_ids(self):
        self.md["provenance"]["scan"]["sources"].append({"id": "als", "format": "las"})
        self.finding("ERROR", "duplicate scan source id 'als'")

    def test_a_source_that_may_not_be_redistributed(self):
        self.md["provenance"]["scan"]["sources"][0]["licence"] = {"redistributable": False}
        self.hm["derived"] = {"source": "als", "product": "dtm", "cell_size": 2.0}
        self.finding("NOTE", "is not redistributable")

    def test_derived_on_instances_and_crg(self):
        sc = self.doc.setdefault("scenery", {})
        proto = next(iter(sc["prototypes"]))
        sc["instances"] = [{"prototype": proto, "transforms": [[0, 0, 0, 0]], "derived": {"source": "ghost", "product": "chm"}}]
        self.finding("ERROR", "scenery.instances[0].derived.source")



def flat_line_doc(**centerline):
    """A straight 100 m road with one surface band, for the profile tests."""
    cl = {"points": [[0, 0, 0], [100, 0, 0]], "width": {"left": 4.0, "right": 4.0}, **centerline}
    return {"_metadata": {"specification": "STJ", "version": "0.3", "coordinate_system": "OpenDRIVE", "units": "SI"},
            "reference": {"centerline": cl},
            "surfaces": {"default": "gravel", "library": {"gravel": {"class": "gravel"}, "grass": {"class": "grass"}},
                         "bands": [{"s_start": 0, "s_end": 100, "t_min": -4.0, "t_max": 4.0, "surface": "gravel"}]}}


CROWNED = {"points": [{"t": -5.0, "dz": -0.3}, {"t": 0.0, "dz": 0.05, "surface": "grass"}, {"t": 5.0, "dz": -0.3, "surface": "grass"}]}
FLAT = {"points": [{"t": -5.0, "dz": 0.0}, {"t": 0.0, "dz": 0.0, "surface": "grass"}, {"t": 5.0, "dz": 0.0, "surface": "grass"}]}


class RoadProfile(unittest.TestCase):
    """Cross-sections, banking, the terrain rule, roads and junctions (spec §7.1)."""

    def xs(self, **kw):
        return {"templates": {"crowned": CROWNED, "flat": FLAT},
                "sections": [{"s_start": 0, "s_end": 50, "template": "crowned"},
                             {"s_start": 50, "s_end": 100, "template": "flat", "blend": 20}], **kw}

    def finding(self, doc, level, fragment):
        found = messages(run(doc), level)
        self.assertTrue(any(fragment in m for m in found), f"no {level} containing {fragment!r} in {found}")

    # -- core --
    def test_template_blends_point_by_point(self):
        cl = flat_line_doc(cross_section=self.xs())["reference"]["centerline"]
        self.assertEqual(core.template_points(cl, 10)[1][1], 0.05)
        mid = core.template_points(cl, 60)            # halfway through the 20 m blend into 'flat'
        self.assertAlmostEqual(mid[1][1], 0.025)
        self.assertAlmostEqual(mid[0][1], -0.15)
        self.assertEqual(core.template_points(cl, 90)[1][1], 0.0)
        self.assertIsNone(core.template_points({"points": []}, 10))

    def test_bank_tilts_the_profile_about_the_centerline(self):
        cl = flat_line_doc(cross_section={"templates": {"flat": FLAT}, "sections": [{"s_start": 0, "s_end": 100, "template": "flat"}],
                                          "bank": [[0, 0.1]]})["reference"]["centerline"]
        t, z = core.profile_point(cl, 10, 4.0)
        self.assertAlmostEqual(t, 4.0 * math.cos(0.1))
        self.assertAlmostEqual(z, 4.0 * math.sin(0.1))                  # the left side is higher
        self.assertAlmostEqual(core.surface_height(cl, 10, -4.0), -4.0 * math.sin(0.1) / 1.0, places=2)

    def test_surface_continues_at_the_bank_slope_beyond_the_template(self):
        cl = flat_line_doc(cross_section={"templates": {"flat": FLAT}, "sections": [{"s_start": 0, "s_end": 100, "template": "flat"}],
                                          "bank": [[0, 0.1]]})["reference"]["centerline"]
        self.assertAlmostEqual(core.surface_height(cl, 10, 10.0), 10.0 * math.tan(0.1), places=2)

    def test_strip_surface(self):
        cl = flat_line_doc(cross_section=self.xs())["reference"]["centerline"]
        self.assertEqual(core.strip_surface(cl, 10, 3.0), "grass")      # the strip ending at t = 5 is grass
        self.assertIsNone(core.strip_surface(cl, 10, 5.5))

    def test_terrain_rule_sections_override(self):
        cl = {"terrain": {"mode": "carve", "shoulder_blend": 6, "sections": [{"s_start": 20, "s_end": 30, "mode": "free"}]}}
        self.assertEqual(core.terrain_rule_at(cl, 10), ("carve", 6, "smooth"))
        self.assertEqual(core.terrain_rule_at(cl, 25)[0], "free")
        self.assertEqual(core.terrain_rule_at({}, 5), ("free", 0.0, "smooth"))

    def test_carve_puts_the_terrain_on_the_road_and_blends_out(self):
        doc = flat_line_doc(terrain={"mode": "carve", "shoulder_blend": 10.0})
        line = core.reference_line(doc)
        h, road = core.terrain_with_road(doc, line, 5.0, 50.0, 0.0)          # on the road: replaced by its surface
        self.assertEqual((h, road), (0.0, 0.0))
        h, _ = core.terrain_with_road(doc, line, 5.0, 50.0, 9.0)             # 5 m past the edge: half way, smoothstep = 0.5
        self.assertAlmostEqual(h, 2.5)
        h, _ = core.terrain_with_road(doc, line, 5.0, 50.0, 20.0)            # beyond the blend: natural
        self.assertEqual(h, 5.0)

    def test_free_and_drape_leave_the_terrain_alone(self):
        for mode in ("free", "drape"):
            doc = flat_line_doc(terrain={"mode": mode})
            self.assertEqual(core.terrain_with_road(doc, core.reference_line(doc), 5.0, 50.0, 0.0)[0], 5.0)

    def test_rule_hash_follows_its_inputs(self):
        doc = flat_line_doc(cross_section=self.xs())
        before = core.rule_hash(doc)
        self.assertEqual(before, core.rule_hash(copy.deepcopy(doc)))
        doc["surfaces"]["bands"][0]["t_max"] = 3.0
        self.assertNotEqual(before, core.rule_hash(doc))

    # -- reversing --
    def test_reverse_flips_bank_sections_and_templates(self):
        doc = flat_line_doc(cross_section=self.xs(bank=[[10, 0.05], [40, 0.0]]))
        rev = core.reverse_ground(doc)["reference"]["centerline"]["cross_section"]
        self.assertEqual(rev["bank"], [[60.0, 0.0], [90.0, -0.05]])      # s' = L - s, and left becomes right
        self.assertEqual([(x["s_start"], x["s_end"], x["template"]) for x in rev["sections"]],
                         [(0.0, 50.0, "flat"), (50.0, 100.0, "crowned")])
        pts = rev["templates"]["crowned"]["points"]
        self.assertEqual([p["t"] for p in pts], [-5.0, 0.0, 5.0])
        self.assertEqual([p.get("surface") for p in pts], [None, "grass", "grass"])

    def test_reverse_twice_is_the_original(self):
        doc = flat_line_doc(cross_section=self.xs(bank=[[10, 0.05], [40, 0.0]]))
        twice = core.reverse_ground(core.reverse_ground(doc))
        self.assertEqual(twice["reference"]["centerline"]["cross_section"], doc["reference"]["centerline"]["cross_section"])

    def test_reverse_keeps_the_strip_surfaces_on_the_right_strips(self):
        tpl = {"points": [{"t": -4, "dz": 0}, {"t": 0, "dz": 0, "surface": "grass"}, {"t": 4, "dz": 0, "surface": "gravel"}]}
        doc = flat_line_doc(cross_section={"templates": {"a": tpl}, "sections": [{"s_start": 0, "s_end": 100, "template": "a"}]})
        rev = core.reverse_ground(doc)["reference"]
        before = core.strip_surface(doc["reference"]["centerline"], 10, 2.0)       # right of the centre: gravel
        after = core.strip_surface(rev["centerline"], 90, -2.0)                    # the same strip, driven the other way
        self.assertEqual((before, after), ("gravel", "gravel"))

    def test_reverse_layout_keeps_junctions_on_the_base_line_unless_asked(self):
        doc = flat_line_doc()
        doc["junctions"] = [{"id": "j", "roads": [{"road": "reference", "s": 30.0}, {"road": "other", "s": 0.0}]}]
        doc["layouts"] = [{"id": "back", "direction": "reverse"}]
        self.assertEqual(core.layout_document(doc, "back")["junctions"][0]["roads"][0]["s"], 30.0)
        mapped = core.layout_document(doc, "back", ground="layout")["junctions"][0]["roads"]
        self.assertAlmostEqual(mapped[0]["s"], 70.0)
        self.assertEqual(mapped[1]["s"], 0.0)                              # a road other than the reference is not reversed

    # -- ribbon --
    def test_ribbon_follows_banking_and_adds_columns(self):
        import ribbon_usd
        doc = flat_line_doc(cross_section={"templates": {"flat": FLAT}, "sections": [{"s_start": 0, "s_end": 100, "template": "flat"}],
                                           "bank": [[0, 0.1]]})
        points, counts, indices, faces, _ = ribbon_usd.build(doc, step=50.0)
        first = points[:5]                                               # t = -5, -4, 0, 4, 5 at s = 0
        self.assertEqual(len(first), 5)
        self.assertGreater(first[-1][2], first[0][2])                    # the left side (large t) is higher
        self.assertAlmostEqual(first[-1][2] - first[0][2], 10.0 * math.sin(0.1), places=3)
        self.assertEqual(set(faces), {"gravel", "grass"})                # grass from the template strips outside the band

    def test_ribbon_without_a_profile_is_flat(self):
        import ribbon_usd
        points, *_ = ribbon_usd.build(flat_line_doc(), step=50.0)
        self.assertEqual({round(p[2], 6) for p in points}, {0.0})

    # -- validator --
    def test_template_t_must_increase(self):
        bad = {"points": [{"t": 1, "dz": 0}, {"t": 1, "dz": 0}]}
        doc = flat_line_doc(cross_section={"templates": {"a": bad}, "sections": [{"s_start": 0, "s_end": 10, "template": "a"}]})
        self.finding(doc, "ERROR", "t must increase")

    def test_surface_on_the_first_point_has_no_strip(self):
        tpl = {"points": [{"t": -1, "dz": 0, "surface": "grass"}, {"t": 1, "dz": 0}]}
        doc = flat_line_doc(cross_section={"templates": {"a": tpl}, "sections": [{"s_start": 0, "s_end": 10, "template": "a"}]})
        self.finding(doc, "WARN", "no strip ends at the first point")

    def test_unknown_template_and_surface(self):
        doc = flat_line_doc(cross_section={"templates": {"a": {"points": [{"t": -1, "dz": 0, "surface": "nope"}, {"t": 1, "dz": 0}]}},
                                           "sections": [{"s_start": 0, "s_end": 10, "template": "b"}]})
        self.finding(doc, "ERROR", "unknown template 'b'")
        self.finding(doc, "ERROR", "unknown surface 'nope'")

    def test_overlapping_sections(self):
        xs = self.xs()
        xs["sections"][1]["s_start"] = 40
        self.finding(flat_line_doc(cross_section=xs), "ERROR", "overlaps the previous section")

    def test_blend_needs_equal_point_counts(self):
        xs = self.xs()
        xs["templates"]["flat"] = {"points": FLAT["points"][:2]}
        self.finding(flat_line_doc(cross_section=xs), "ERROR", "different number of points")

    def test_bank_in_degrees_is_caught(self):
        self.finding(flat_line_doc(cross_section=self.xs(bank=[[0, 12.0]])), "WARN", "angles are in radians")
        self.finding(flat_line_doc(cross_section=self.xs(bank=[[10, 0.0], [5, 0.0]])), "ERROR", "s must increase")

    def test_template_narrower_than_the_road(self):
        narrow = {"points": [{"t": -2, "dz": 0}, {"t": 2, "dz": 0}]}
        doc = flat_line_doc(cross_section={"templates": {"n": narrow}, "sections": [{"s_start": 0, "s_end": 10, "template": "n"}]})
        self.finding(doc, "WARN", "narrower than the drivable width")

    def test_terrain_rule_without_terrain(self):
        self.finding(flat_line_doc(terrain={"mode": "carve", "shoulder_blend": 5}), "NOTE", "no geometry.terrain")
        self.finding(flat_line_doc(terrain={"mode": "carve"}), "NOTE", "terrain steps up at the road edge")

    def test_drape_warns_when_the_road_leaves_the_terrain(self):
        doc = core.load_document(STAGE)
        doc["reference"]["centerline"]["terrain"] = {"mode": "drape"}
        self.finding(doc, "WARN", "drape: the road is meant to follow the terrain")

    def test_roads_and_junctions(self):
        doc = flat_line_doc()
        doc["roads"] = [{"id": "link", "centerline": {"points": [[50, 0, 0], [50, 60, 0]]}}]
        doc["junctions"] = [{"id": "j", "roads": [{"road": "reference", "s": 50.0}, {"road": "link", "s": 0.0}]}]
        self.assertFalse([m for m in messages(run(doc), "ERROR") if "junction" in m or "road" in m])
        doc["junctions"][0]["roads"][1]["road"] = "ghost"
        self.finding(doc, "ERROR", "unknown road 'ghost'")
        doc["junctions"][0]["roads"][1] = {"road": "link", "s": 0.0}
        doc["junctions"][0]["roads"][0]["s"] = 10.0
        self.finding(doc, "WARN", "apart at their junction points")
        doc["junctions"][0]["roads"][1]["s"] = 500.0
        self.finding(doc, "ERROR", "is beyond road 'link'")

    def test_road_ids(self):
        doc = flat_line_doc()
        line = {"points": [[0, 10, 0], [50, 10, 0]]}
        doc["roads"] = [{"id": "reference", "centerline": line}, {"id": "a", "centerline": line}, {"id": "a", "centerline": line}]
        self.finding(doc, "ERROR", "the reference line's name")
        self.finding(doc, "ERROR", "duplicate road id 'a'")

    def test_side_road_names_a_junction(self):
        doc = flat_line_doc()
        doc["timing"] = {"side_roads": [{"s": 20.0, "side": "left", "junction": "nowhere"}]}
        self.finding(doc, "ERROR", "unknown junction 'nowhere'")

    def test_stale_generated_mesh(self):
        doc = flat_line_doc(cross_section=self.xs())
        doc["geometry"] = {"meshes": [{"id": "ribbon", "uri": "x.usda", "roles": ["collision"],
                                       "generated": {"rule": "reference.centerline.cross_section", "inputs_sha256": core.rule_hash(doc)}}]}
        self.assertFalse([m for m in messages(run(doc), "WARN") if "stale" in m])
        doc["reference"]["centerline"]["cross_section"]["bank"] = [[0, 0.02]]
        self.finding(doc, "WARN", "it is stale")

    def test_example_ribbon_is_current(self):
        doc = core.load_document(STAGE)
        gen = doc["geometry"]["meshes"][0]["generated"]
        self.assertEqual(gen["inputs_sha256"], core.rule_hash(doc))

    def test_exclude_zone_radius(self):
        doc = core.load_document(STAGE)
        layer = doc["scenery"]["scatter"][0]
        layer["exclude_zones"] = [{"center": [0, 0], "radius": 500}]
        self.finding(doc, "WARN", "radii are in metres")



def write_visual_mesh(path, *, surface=True, texture=None, opacity_map=False, threshold=None, two_sided=False,
                      interface_input=None, material="Mat"):
    """A one-quad USD mesh with one material. texture: None, or the sourceColorSpace token ('' for none)."""
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, Vt
    st = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageUpAxis(st, UsdGeom.Tokens.z)
    root = UsdGeom.Xform.Define(st, "/m")
    st.SetDefaultPrim(root.GetPrim())
    mesh = UsdGeom.Mesh.Define(st, "/m/mesh")
    mesh.CreatePointsAttr(Vt.Vec3fArray([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]))
    mesh.CreateFaceVertexCountsAttr(Vt.IntArray([4]))
    mesh.CreateFaceVertexIndicesAttr(Vt.IntArray([0, 1, 2, 3]))
    mesh.CreateDoubleSidedAttr(two_sided)
    mat = UsdShade.Material.Define(st, f"/m/materials/{material}")
    if interface_input:
        mat.CreateInput(interface_input, Sdf.ValueTypeNames.Float).Set(1.0)
    if surface:
        sh = UsdShade.Shader.Define(st, f"/m/materials/{material}/surface")
        sh.CreateIdAttr("UsdPreviewSurface")
        sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.5, 0.5, 0.5))
        if threshold is not None:
            sh.CreateInput("opacityThreshold", Sdf.ValueTypeNames.Float).Set(threshold)
        if texture is not None:
            tx = UsdShade.Shader.Define(st, f"/m/materials/{material}/tex")
            tx.CreateIdAttr("UsdUVTexture")
            tx.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath("tex.png"))
            if texture:
                tx.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set(texture)
            tx.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
            tx.CreateOutput("a", Sdf.ValueTypeNames.Float)
            sh.GetInput("diffuseColor") or sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f)
            sh.GetInput("diffuseColor").ConnectToSource(tx.ConnectableAPI(), "rgb")
            if opacity_map:
                sh.CreateInput("opacity", Sdf.ValueTypeNames.Float).ConnectToSource(tx.ConnectableAPI(), "a")
        mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
    UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(mat)
    st.GetRootLayer().Save()


class MaterialsAndAssets(unittest.TestCase):
    """Material profile, decals, prototype LODs, assets[] and materials[] (spec §5.3, §7.2, §7.7, §8.2, §11.1)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.doc = {"_metadata": {"specification": "STJ", "version": "0.3", "coordinate_system": "OpenDRIVE", "units": "SI"},
                    "geometry": {"meshes": [{"id": "vis", "uri": "vis.usda", "roles": ["visual"]}]}}

    def tearDown(self):
        self.tmp.cleanup()

    def mesh(self, **kw):
        write_visual_mesh(self.dir / "vis.usda", **kw)

    def run_doc(self):
        return run(self.doc, self.dir)

    def finding(self, level, fragment):
        found = messages(self.run_doc(), level)
        self.assertTrue(any(fragment in m for m in found), f"no {level} containing {fragment!r} in {found}")

    def absent(self, level, fragment):
        found = messages(self.run_doc(), level)
        self.assertFalse(any(fragment in m for m in found), f"unexpected {level} {fragment!r} in {found}")

    # -- material profile --
    def test_a_visual_material_needs_a_surface(self):
        self.mesh(surface=False)
        self.finding("ERROR", "has no outputs:surface")

    def test_a_collision_mesh_is_exempt(self):
        self.mesh(surface=False)
        self.doc["geometry"]["meshes"][0]["roles"] = ["collision"]
        self.absent("ERROR", "has no outputs:surface")

    def test_texture_colour_space(self):
        self.mesh(texture="")
        self.finding("WARN", "declares no colour space")
        self.mesh(texture="sRGB")
        self.absent("WARN", "declares no colour space")
        self.mesh(texture="auto")                     # auto is a guess, not a declaration
        self.finding("WARN", "declares no colour space")

    def test_cutout_opacity_needs_a_threshold(self):
        self.mesh(texture="sRGB", opacity_map=True)
        self.finding("WARN", "without opacityThreshold")
        self.mesh(texture="sRGB", opacity_map=True, threshold=0.5, two_sided=True)
        self.absent("WARN", "without opacityThreshold")

    def test_a_card_must_be_two_sided(self):
        self.mesh(texture="sRGB", opacity_map=True, threshold=0.5, two_sided=False)
        self.finding("ERROR", "is not doubleSided")
        self.mesh(texture="sRGB", opacity_map=True, threshold=0.5, two_sided=True)
        self.absent("ERROR", "is not doubleSided")

    def test_a_decal_may_blend_its_opacity(self):
        self.mesh(texture="sRGB", opacity_map=True)
        self.doc["geometry"]["meshes"][0]["roles"] = ["decal"]
        self.absent("WARN", "without opacityThreshold")

    def test_the_maps_a_material_carries_are_listed(self):
        self.mesh(texture="sRGB", opacity_map=True, threshold=0.5, two_sided=True)
        self.finding("NOTE", "carries: diffuseColor+opacity")
        self.mesh()
        self.finding("NOTE", "no texture maps (constants only)")

    # -- decals --
    def test_decal_checks(self):
        self.mesh()
        m = self.doc["geometry"]["meshes"]
        m[0]["roles"] = ["decal", "collision"]
        m[0]["decal"] = {"on": "ghost"}
        self.finding("ERROR", "unknown mesh 'ghost'")
        self.finding("WARN", "a decal is a visual layer")
        m[0]["decal"] = {"on": "vis"}
        self.finding("ERROR", "cannot lie on itself")
        m[0]["decal"] = {"on": "terrain", "opacity_primvar": "displayOpacity"}
        self.absent("ERROR", "decal.on")

    def test_decal_block_without_the_role(self):
        self.mesh()
        self.doc["geometry"]["meshes"][0]["decal"] = {"on": "terrain"}
        self.finding("WARN", "decal object on a mesh without the 'decal' role")

    # -- assets --
    def test_asset_hash_and_licence(self):
        self.mesh()
        (self.dir / "tex.png").write_bytes(b"not really a png")
        self.doc["assets"] = [{"id": "tex", "uri": "tex.png", "role": "texture", "sha256": "0" * 64,
                               "licence": {"redistributable": False}}]
        self.finding("WARN", "does not match its hash")
        self.finding("WARN", "may not be redistributed")
        self.doc["_metadata"]["licence"] = {"redistributable": False}
        self.absent("WARN", "may not be redistributed")

    def test_asset_file_missing_and_duplicates(self):
        self.mesh()
        self.doc["assets"] = [{"id": "a", "uri": "gone.png"}, {"id": "a", "uri": "gone2.png"}]
        self.finding("WARN", "file not found: gone.png")
        self.finding("ERROR", "duplicate asset id 'a'")

    def test_manifest_against_what_usd_names(self):
        self.mesh(texture="sRGB")
        (self.dir / "tex.png").write_bytes(b"x")
        (self.dir / "other.png").write_bytes(b"y")
        self.doc["assets"] = [{"id": "other", "uri": "other.png", "role": "texture"}]
        self.finding("NOTE", "'tex.png' is used by a USD mesh but not listed")
        self.finding("NOTE", "'other.png' is listed as a texture but no USD mesh names it")
        self.doc["assets"] = [{"id": "tex", "uri": "tex.png", "role": "texture"}]
        self.absent("NOTE", "used by a USD mesh but not listed")

    # -- prototype LODs --
    def proto_doc(self, lods, **extra):
        self.mesh()
        self.doc["scenery"] = {"prototypes": {"tree": {"class": "tree", "mesh": {"mesh_ref": "vis", "prim": "/m/mesh"},
                                                       "lods": lods, **extra}}}

    def test_lods_ok(self):
        self.proto_doc([{"prim": "/m/mesh", "level": 1, "switch_distance": 50}, {"prim": "/m/mesh", "level": 2, "switch_distance": 150}],
                       cull_distance=400)
        self.assertEqual([m for m in messages(self.run_doc(), "ERROR") + messages(self.run_doc(), "WARN") if "lods" in m or "cull" in m], [])

    def test_lod_prim_must_exist(self):
        self.proto_doc([{"prim": "/m/nowhere", "level": 1, "switch_distance": 50}])
        self.finding("ERROR", "scenery.prototypes.tree.lods")

    def test_lod_levels_and_distances(self):
        self.proto_doc([{"prim": "/m/mesh", "level": 1, "switch_distance": 50}, {"prim": "/m/mesh", "level": 1, "switch_distance": 80}])
        self.finding("ERROR", "same level")
        self.proto_doc([{"prim": "/m/mesh", "level": 1, "switch_distance": 90}, {"prim": "/m/mesh", "level": 2, "switch_distance": 60}])
        self.finding("ERROR", "switch_distance must increase")
        self.proto_doc([{"prim": "/m/mesh", "level": 1}])
        self.finding("WARN", "without switch_distance")

    def test_cull_distance_must_pass_the_last_lod(self):
        self.proto_doc([{"prim": "/m/mesh", "level": 1, "switch_distance": 200}], cull_distance=100)
        self.finding("WARN", "is not beyond the last LOD switch")

    def test_lods_need_a_mesh(self):
        self.mesh()
        self.doc["scenery"] = {"prototypes": {"tree": {"class": "tree", "lods": [{"prim": "/m/mesh", "level": 1, "switch_distance": 10}]}}}
        self.finding("ERROR", "LODs need the prototype's USD mesh")

    # -- signal-driven materials --
    def test_material_drive(self):
        self.mesh(interface_input="emissive_scale")
        drive = {"material": "Mat", "input": "emissive_scale",
                 "by": {"signal": "sun_elevation", "curve": [[-0.1, 1.0], [0.05, 0.0]]}}
        self.doc["materials"] = [drive]
        self.assertEqual([m for m in messages(self.run_doc(), "ERROR") + messages(self.run_doc(), "WARN") if "materials[" in m], [])

    def test_material_drive_problems(self):
        self.mesh(interface_input="emissive_scale")
        by = {"signal": "sun_elevation", "curve": [[-0.1, 1.0], [0.05, 0.0]]}
        self.doc["materials"] = [{"material": "Ghost", "input": "emissive_scale", "by": by}]
        self.finding("ERROR", "no material 'Ghost'")
        self.doc["materials"] = [{"material": "Mat", "input": "wet_amount", "by": by}]
        self.finding("WARN", "has no interface input 'wet_amount'")
        self.doc["materials"] = [{"material": "Mat", "input": "emissive_scale", "by": by}] * 2
        self.finding("ERROR", "is driven twice")
        self.doc["materials"] = [{"material": "Mat", "mesh_ref": "ghost", "input": "emissive_scale", "by": by}]
        self.finding("ERROR", "unknown mesh 'ghost'")

    def test_material_drive_binding_is_checked_like_any_other(self):
        self.mesh(interface_input="emissive_scale")
        self.doc["materials"] = [{"material": "Mat", "input": "emissive_scale",
                                  "by": {"signal": "no_such_signal", "curve": [[0, 0], [1, 1]]}}]
        self.assertTrue(any("no_such_signal" in m for m in messages(self.run_doc(), "ERROR")))



class Structures(unittest.TestCase):
    """Bridges, tunnels, underpasses and galleries (spec §7.1)."""

    def doc(self, *structs, **extra):
        d = flat_line_doc(**extra)
        d["structures"] = list(structs)
        return d

    def finding(self, doc, level, fragment):
        found = messages(run(doc), level)
        self.assertTrue(any(fragment in m for m in found), f"no {level} containing {fragment!r} in {found}")

    def absent(self, doc, level, fragment):
        found = messages(run(doc), level)
        self.assertFalse(any(fragment in m for m in found), f"unexpected {level} {fragment!r} in {found}")

    # -- defaults --
    def test_defaults_follow_the_kind(self):
        d = self.doc({"id": "t", "kind": "tunnel", "s_start": 10, "s_end": 40},
                     {"id": "b", "kind": "bridge", "s_start": 50, "s_end": 60},
                     {"id": "g", "kind": "gallery", "s_start": 70, "s_end": 80})
        out = core.structure_defaults(d)
        self.assertEqual({sh["id"]: sh["factor"] for sh in out["shelter"]}, {"t_shelter": 1.0, "g_shelter": 0.7})
        self.assertEqual({z["id"]: z["reverb"] for z in out["audio_zones"]}, {"t_reverb": "tunnel", "g_reverb": "underpass"})
        self.assertEqual(sorted(sec["s_start"] for sec in out["terrain_sections"]), [10, 50, 70])   # a bridge is free too
        self.assertTrue(all(sec["mode"] == "free" for sec in out["terrain_sections"]))

    def test_the_band_covers_the_road_and_a_metre_more(self):
        d = self.doc({"id": "t", "kind": "tunnel", "s_start": 10, "s_end": 40})
        band = core.structure_defaults(d)["shelter"][0]["band"]
        self.assertEqual((band["s_start"], band["s_end"], band["t_min"], band["t_max"]), (10, 40, -5.0, 5.0))

    def test_explicit_entries_win(self):
        d = self.doc({"id": "t", "kind": "tunnel", "s_start": 10, "s_end": 40})
        d["water"] = {"shelter": [{"id": "mine", "kind": "tunnel", "factor": 0.9,
                                   "band": {"s_start": 20, "s_end": 30, "t_min": -4, "t_max": 4}}]}
        d["audio"] = {"zones": [{"id": "z", "reverb": "canyon", "shape": {"band": {"s_start": 0, "s_end": 50, "t_min": -9, "t_max": 9}}}]}
        d["reference"]["centerline"]["terrain"] = {"mode": "carve", "sections": [{"s_start": 10, "s_end": 40, "mode": "carve"}]}
        out = core.structure_defaults(d)
        self.assertEqual((out["shelter"], out["audio_zones"], out["terrain_sections"]), ([], [], []))

    def test_other_roads_are_skipped(self):
        d = self.doc({"id": "u", "kind": "underpass", "road": "link", "s_start": 1, "s_end": 9})
        self.assertEqual(core.structure_defaults(d), {"shelter": [], "audio_zones": [], "terrain_sections": []})

    def test_structure_at(self):
        d = self.doc({"id": "b", "kind": "bridge", "s_start": 50, "s_end": 60})
        self.assertEqual(core.structure_at(d, 55)["id"], "b")
        self.assertIsNone(core.structure_at(d, 40))
        self.assertEqual(core.structure_at(d, 40, slack=15)["id"], "b")

    # -- validator --
    def test_ranges(self):
        self.finding(self.doc({"id": "b", "kind": "bridge", "s_start": 60, "s_end": 50}), "ERROR", "s_end must be greater")
        self.finding(self.doc({"id": "b", "kind": "bridge", "s_start": 10, "s_end": 500}), "ERROR", "is beyond road 'reference'")

    def test_unknown_references(self):
        d = self.doc({"id": "b", "kind": "bridge", "road": "ghost", "s_start": 1, "s_end": 9})
        self.finding(d, "ERROR", "unknown road 'ghost'")
        d = self.doc({"id": "u", "kind": "underpass", "s_start": 1, "s_end": 9, "clearance": 4, "carried_by": "nope"})
        self.finding(d, "ERROR", "unknown structure 'nope'")
        d = self.doc({"id": "b", "kind": "bridge", "s_start": 1, "s_end": 9, "mesh": {"mesh_ref": "ghost", "prim": "/x"}})
        self.finding(d, "ERROR", "unknown mesh 'ghost'")

    def test_carried_by_only_for_an_underpass(self):
        d = self.doc({"id": "b", "kind": "bridge", "s_start": 1, "s_end": 9},
                     {"id": "t", "kind": "tunnel", "s_start": 20, "s_end": 30, "clearance": 5, "carried_by": "b"})
        self.finding(d, "WARN", "only an underpass passes under a structure")

    def test_clearance(self):
        self.finding(self.doc({"id": "t", "kind": "tunnel", "s_start": 1, "s_end": 9}), "WARN", "without clearance")
        self.absent(self.doc({"id": "t", "kind": "tunnel", "s_start": 1, "s_end": 9, "clearance": 5}), "WARN", "without clearance")
        self.absent(self.doc({"id": "b", "kind": "bridge", "s_start": 1, "s_end": 9}), "WARN", "without clearance")

    def test_overlap(self):
        d = self.doc({"id": "a", "kind": "bridge", "s_start": 10, "s_end": 30}, {"id": "b", "kind": "tunnel", "s_start": 20, "s_end": 40, "clearance": 5})
        self.finding(d, "WARN", "overlaps structure 'a'")
        d = self.doc({"id": "a", "kind": "bridge", "s_start": 10, "s_end": 30}, {"id": "u", "kind": "underpass", "s_start": 20, "s_end": 25, "clearance": 4})
        self.absent(d, "WARN", "overlaps structure")

    def test_a_structure_stands_apart_from_the_ground(self):
        d = self.doc({"id": "b", "kind": "bridge", "s_start": 10, "s_end": 30}, terrain={"mode": "carve", "shoulder_blend": 4})
        self.finding(d, "WARN", "the terrain rule is 'carve' under this bridge")
        d = self.doc({"id": "b", "kind": "bridge", "s_start": 10, "s_end": 30},
                     terrain={"mode": "carve", "shoulder_blend": 4, "sections": [{"s_start": 10, "s_end": 30, "mode": "free"}]})
        self.absent(d, "WARN", "the terrain rule is")

    def test_an_unexplained_shelter(self):
        d = flat_line_doc()
        d["water"] = {"shelter": [{"id": "s", "kind": "tunnel", "factor": 1.0, "band": {"s_start": 10, "s_end": 30, "t_min": -4, "t_max": 4}}]}
        self.finding(d, "NOTE", "no structure covers it")
        d["structures"] = [{"id": "t", "kind": "tunnel", "s_start": 5, "s_end": 35, "clearance": 5}]
        self.absent(d, "NOTE", "no structure covers it")

    def test_pace_notes(self):
        d = self.doc({"id": "b", "kind": "bridge", "s_start": 50, "s_end": 60})
        d["race"] = {"pacenotes": {"scale": "ascending_1_6", "notes": [
            {"s": 10.0, "kind": "bridge"},                        # nothing there
            {"s": 45.0, "kind": "bridge"},                        # 5 m before the bridge: found with the slack
            {"s": 55.0, "kind": "tunnel", "structure": "b"},      # the wrong kind
            {"s": 58.0, "kind": "bridge", "structure": "gone"}]}}
        self.finding(d, "NOTE", "a bridge note at s = 10 m with no structure there")
        self.absent(d, "NOTE", "at s = 45 m")
        self.finding(d, "WARN", "a tunnel note, but 'b' is a bridge")
        self.finding(d, "ERROR", "unknown structure 'gone'")

    def test_the_example_has_its_bridge(self):
        doc = core.load_document(STAGE)
        st = doc["structures"][0]
        self.assertEqual((st["id"], st["kind"], st["s_start"], st["s_end"]), ("viaduct_1", "bridge", 1500.0, 1560.0))
        flat = next(sec for sec in doc["reference"]["centerline"]["cross_section"]["sections"] if sec["template"] == "bridge_deck")
        self.assertEqual((flat["s_start"], flat["s_end"]), (st["s_start"], st["s_end"]))



class InstanceVariation(unittest.TestCase):
    """Per-instance primvars on a PointInstancer (spec §8.2)."""

    def setUp(self):
        from pxr import Sdf, Usd, UsdGeom, Vt
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        st = Usd.Stage.CreateNew(str(self.dir / "forest.usda"))
        UsdGeom.SetStageUpAxis(st, UsdGeom.Tokens.z)
        root = UsdGeom.Xform.Define(st, "/f")
        st.SetDefaultPrim(root.GetPrim())
        inst = UsdGeom.PointInstancer.Define(st, "/f/trees")
        inst.CreatePositionsAttr(Vt.Vec3fArray([(0, 0, 0), (5, 0, 0)]))
        api = UsdGeom.PrimvarsAPI(inst.GetPrim())
        api.CreatePrimvar("stj_tint", Sdf.ValueTypeNames.Color3fArray, UsdGeom.Tokens.vertex).Set(Vt.Vec3fArray([(1, 1, 1), (0.8, 0.9, 0.7)]))
        api.CreatePrimvar("stj_age", Sdf.ValueTypeNames.FloatArray, UsdGeom.Tokens.vertex).Set(Vt.FloatArray([0.1, 0.9]))
        st.GetRootLayer().Save()
        self.doc = {"_metadata": {"specification": "STJ", "version": "0.3", "coordinate_system": "OpenDRIVE", "units": "SI"},
                    "geometry": {"meshes": [{"id": "forest", "uri": "forest.usda", "roles": ["visual"]}]},
                    "scenery": {"prototypes": {"pine": {"class": "tree"}},
                                "instances": [{"prototype": "pine", "usd": {"mesh_ref": "forest", "prim": "/f/trees", "primvars": []}}]}}

    def tearDown(self):
        self.tmp.cleanup()

    def primvars(self, *pvs):
        self.doc["scenery"]["instances"][0]["usd"]["primvars"] = list(pvs)
        return run(self.doc, self.dir)

    def test_listed_primvars_that_exist_are_fine(self):
        rep = self.primvars({"name": "stj_tint", "role": "tint"}, {"name": "stj_age", "role": "age"})
        self.assertEqual([m for m in messages(rep, "ERROR") + messages(rep, "WARN") if "primvar" in m], [])

    def test_a_missing_primvar(self):
        rep = self.primvars({"name": "stj_phase", "role": "phase"})
        self.assertTrue(any("is not on /f/trees" in m for m in messages(rep, "ERROR")))

    def test_roles_need_the_right_components(self):
        rep = self.primvars({"name": "stj_age", "role": "tint"}, {"name": "stj_tint", "role": "age"})
        warns = " ".join(messages(rep, "WARN"))
        self.assertIn("the role 'tint' needs 3 components", warns)
        self.assertIn("(or 4, the last ignored)", warns)
        self.assertIn("the role 'age' is one number", warns)

    def test_a_four_component_tint_is_accepted(self):
        # Blender's FLOAT_COLOR attribute exports as color4f[]
        from pxr import Sdf, Usd, UsdGeom, Vt
        st = Usd.Stage.Open(str(self.dir / "forest.usda"))
        pv = UsdGeom.PrimvarsAPI(st.GetPrimAtPath("/f/trees")).CreatePrimvar("stj_tint4", Sdf.ValueTypeNames.Color4fArray, UsdGeom.Tokens.vertex)
        pv.Set(Vt.Vec4fArray([(1, 1, 1, 1), (0.8, 0.9, 0.7, 1)]))
        st.GetRootLayer().Save()
        rep = self.primvars({"name": "stj_tint4", "role": "tint"})
        self.assertEqual([m for m in messages(rep, "ERROR") + messages(rep, "WARN") if "primvar" in m or "tint" in m], [])

    def test_a_primvar_listed_twice(self):
        rep = self.primvars({"name": "stj_age", "role": "age"}, {"name": "stj_age", "role": "other"})
        self.assertTrue(any("listed twice" in m for m in messages(rep, "ERROR")))

    def test_the_name_needs_the_stj_prefix(self):
        rep = self.primvars({"name": "age", "role": "age"})
        self.assertTrue(any("age" in m for m in messages(rep, "ERROR")))



class EmbedCreatesTheStage(unittest.TestCase):
    """stj_usd embed on a file that does not exist yet (README, first look)."""

    def test_embed_creates_a_track_stage(self):
        from pxr import UsdGeom
        with tempfile.TemporaryDirectory() as d:
            doc = {"_metadata": {"specification": "STJ", "version": "0.3", "coordinate_system": "OpenDRIVE", "units": "SI"},
                   "reference": {"centerline": {"points": [[0, 0, 0], [100, 0, 0]], "width": {"left": 3, "right": 3}}}}
            target = Path(d, "new.usda")
            core.embed_document(doc, target)
            stage = core.usd_stage(target)
            self.assertEqual((UsdGeom.GetStageUpAxis(stage), UsdGeom.GetStageMetersPerUnit(stage)), ("Z", 1.0))
            self.assertEqual(stage.GetDefaultPrim().GetPath().pathString, "/track")
            self.assertEqual(core.usd_document(target), doc)
            self.assertEqual(messages(validate.validate(target), "ERROR") + messages(validate.validate(target), "WARN"), [])

    def test_embed_with_an_output_leaves_no_input_behind(self):
        with tempfile.TemporaryDirectory() as d:
            doc = {"_metadata": {"specification": "STJ", "version": "0.3", "coordinate_system": "OpenDRIVE", "units": "SI"}}
            core.embed_document(doc, Path(d, "never.usda"), Path(d, "out.usda"))
            self.assertFalse(Path(d, "never.usda").exists())
            self.assertEqual(core.usd_document(Path(d, "out.usda")), doc)

    def test_embed_into_an_existing_stage_keeps_it(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d, "t.usda")
            doc = {"_metadata": {"specification": "STJ", "version": "0.3", "coordinate_system": "OpenDRIVE", "units": "SI"}}
            core.embed_document(doc, target)
            doc["track_info"] = {"name": "Second"}
            core.embed_document(doc, target)
            self.assertEqual(core.usd_document(target)["track_info"]["name"], "Second")



class GroundFallback(unittest.TestCase):
    """The baked fallback of a ground material is a cache of its recipe (spec §8.7)."""

    def setUp(self):
        self.doc = core.load_document(STAGE)
        self.gm = self.doc["ground"]["materials"][0]

    def finding(self, level, fragment):
        found = messages(run(self.doc), level)
        self.assertTrue(any(fragment in m for m in found), f"no {level} containing {fragment!r} in {found}")

    def test_the_example_stamp_is_current(self):
        self.assertEqual(self.gm["fallback"]["inputs_sha256"], core.rule_hash(self.doc, "ground.materials[0]"))
        self.assertEqual([m for m in messages(run(self.doc), "WARN") if "fallback" in m], [])

    def test_the_hash_follows_the_recipe_and_ignores_the_fallback(self):
        before = core.rule_hash(self.doc, "ground.materials[0]")
        self.gm["fallback"]["uri"] = "ground/elsewhere.png"
        self.assertEqual(before, core.rule_hash(self.doc, "ground.materials[0]"))
        self.gm["blend"]["depth"] = 0.5
        self.assertNotEqual(before, core.rule_hash(self.doc, "ground.materials[0]"))

    def test_the_hash_follows_the_layers_it_names(self):
        before = core.rule_hash(self.doc, "ground.materials[0]")
        self.doc["ground"]["layers"]["rock"]["tile"] = 20.0
        self.assertNotEqual(before, core.rule_hash(self.doc, "ground.materials[0]"))

    def test_a_changed_recipe_makes_the_fallback_stale(self):
        self.gm["blend"]["height_influence"] = 0.9
        self.finding("WARN", "it is stale")

    def test_a_fallback_without_a_hash_or_a_file(self):
        del self.gm["fallback"]["inputs_sha256"]
        self.gm["fallback"]["uri"] = "ground/missing_bake.png"
        self.finding("NOTE", "no inputs_sha256")
        self.finding("WARN", "file not found: ground/missing_bake.png")

    def test_an_unknown_rule_is_refused(self):
        with self.assertRaises(ValueError):
            core.rule_hash(self.doc, "ground.materials[x]")

    def test_ground_bake_prints_the_stamp(self):
        import ground_bake
        with tempfile.TemporaryDirectory() as d:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ground_bake.main([str(STAGE), "-o", str(Path(d, "bake.png")), "--size", "32x4"])
            line = next(l for l in buf.getvalue().splitlines() if l.startswith("ground.materials[0].fallback:"))
            stamp = json.loads(line.split(":", 1)[1])
            self.assertEqual(stamp["inputs_sha256"], core.rule_hash(self.doc, "ground.materials[0]"))
            self.assertEqual((stamp["uri"], stamp["texcoord"]), ("bake.png", "st"))



class ClosedLoops(unittest.TestCase):
    """Ranges, profiles and banking across s = 0 on a closed (lapped) line (spec §7.1)."""

    TPL = {"points": [{"t": -6, "dz": -0.2}, {"t": 0, "dz": 0.04, "surface": "asphalt"}, {"t": 6, "dz": -0.2, "surface": "asphalt"}]}
    FLAT = {"points": [{"t": -6, "dz": 0.0}, {"t": 0, "dz": 0.0, "surface": "asphalt"}, {"t": 6, "dz": 0.0, "surface": "asphalt"}]}

    def setUp(self):
        self.ring = core.load_document(EX / "test_ring_minimal.usda")
        self.L = core.reference_line(self.ring).length

    def doc(self, **xs):
        d = copy.deepcopy(self.ring)
        d["reference"]["centerline"]["cross_section"] = {"templates": {"a": self.TPL, "b": self.FLAT}, **xs}
        return d

    def finding(self, doc, level, fragment):
        found = messages(run(doc), level)
        self.assertTrue(any(fragment in m for m in found), f"no {level} containing {fragment!r} in {found}")

    def clean(self, doc):
        return [m for m in messages(run(doc), "ERROR") + messages(run(doc), "WARN")]

    # -- the helpers --
    def test_range_helpers(self):
        L = 1000.0
        self.assertTrue(core.s_in_range(50, 900, 100, L))
        self.assertTrue(core.s_in_range(950, 900, 100, L))
        self.assertFalse(core.s_in_range(500, 900, 100, L))
        self.assertFalse(core.s_in_range(50, 900, 100))                    # an open line does not wrap
        self.assertEqual(core.s_since(50, 900, L), 150)
        self.assertEqual(core.s_since(950, 900, L), 50)
        self.assertEqual(core.s_segments(900, 100, L), [(900, 1000.0), (0.0, 100)])
        self.assertTrue(core.s_overlap((900, 100), (50, 300), L))
        self.assertFalse(core.s_overlap((900, 100), (200, 800), L))
        self.assertFalse(core.s_overlap((100, 300), (300, 500), L))        # touching is not overlapping

    # -- the profile --
    def test_a_section_crosses_the_start_line(self):
        L = self.L
        cl = self.doc(sections=[{"s_start": L - 100, "s_end": 100, "template": "a"}])["reference"]["centerline"]
        for s in (L - 50, 0.0, 20.0, 100.0):
            self.assertIsNotNone(core.template_points(cl, s, L), s)
        self.assertIsNone(core.template_points(cl, 500.0, L))
        self.assertIsNone(core.template_points(cl, 20.0), "an open line does not wrap")

    def test_blend_counts_from_the_start_across_the_wrap(self):
        L = self.L
        cl = self.doc(sections=[{"s_start": 200, "s_end": 400, "template": "a"},
                                {"s_start": L - 100, "s_end": 100, "template": "b", "blend": 40}])["reference"]["centerline"]
        half = core.template_points(cl, L - 80, L)          # 20 m into the 40 m blend: halfway from 'a' to 'b'
        self.assertAlmostEqual(half[1][1], 0.02)
        self.assertEqual(core.template_points(cl, 10.0, L)[1][1], 0.0)     # 110 m in: pure 'b', after the wrap

    def test_bank_wraps_across_the_start_line(self):
        L = self.L
        cl = self.doc(bank=[[20, 0.0], [L - 20, 0.0], [L - 5, 0.04]])["reference"]["centerline"]
        self.assertAlmostEqual(core.bank_at(cl, L - 5, L), 0.04)
        self.assertAlmostEqual(core.bank_at(cl, 0.0, L), 0.04 * (1 - 5.0 / 25.0))        # 5 of 25 m back to 0 over the line
        self.assertAlmostEqual(core.bank_at(cl, 10.0, L), 0.04 * (1 - 15.0 / 25.0))
        self.assertEqual(core.bank_at(cl, 10.0), 0.0, "without the lap length the table is held flat")

    def test_terrain_rule_section_crosses_the_start_line(self):
        L = self.L
        cl = {"terrain": {"mode": "carve", "sections": [{"s_start": L - 50, "s_end": 50, "mode": "free"}]}}
        self.assertEqual(core.terrain_rule_at(cl, 10.0, L)[0], "free")
        self.assertEqual(core.terrain_rule_at(cl, L - 10, L)[0], "free")
        self.assertEqual(core.terrain_rule_at(cl, 300.0, L)[0], "carve")

    def test_reversing_keeps_a_wrapping_section_and_flips_the_bank(self):
        L = self.L
        ref = self.doc(sections=[{"s_start": L - 100, "s_end": 100, "template": "a"}], bank=[[20, 0.0], [L - 20, 0.0], [L - 5, 0.04]])["reference"]
        rev = core.reverse_ground({"reference": ref}, L)["reference"]["centerline"]["cross_section"]
        self.assertEqual((round(rev["sections"][0]["s_start"], 6), round(rev["sections"][0]["s_end"], 6)), (round(L - 100, 6), 100.0))
        self.assertEqual(rev["bank"][0][1], -0.04)
        twice = core.reverse_ground({"reference": {"centerline": {**ref["centerline"], "cross_section": rev}}}, L)["reference"]["centerline"]["cross_section"]
        for got, want in zip(twice["bank"], ref["centerline"]["cross_section"]["bank"]):
            self.assertAlmostEqual(got[0], want[0], places=6)
            self.assertAlmostEqual(got[1], want[1], places=9)

    def test_the_ribbon_follows_the_profile_across_the_start_line(self):
        import ribbon_usd
        d = self.doc(sections=[{"s_start": self.L - 100, "s_end": 100, "template": "a"}])
        d["surfaces"]["bands"] = d["surfaces"].get("bands") or [{"s_start": 0, "s_end": self.L, "t_min": -6, "t_max": 6, "surface": "asphalt"}]
        points, _c, _i, faces, _m = ribbon_usd.build(d, step=20.0)
        crown = [p for p in points if abs(p[2] - 0.04) < 1e-6]
        self.assertTrue(crown, "the crown of the profile appears in the ribbon")
        self.assertTrue(faces)

    # -- structures --
    def test_a_structure_crosses_the_start_line(self):
        d = copy.deepcopy(self.ring)
        d["structures"] = [{"id": "t", "kind": "tunnel", "s_start": self.L - 30, "s_end": 30, "clearance": 5}]
        self.assertEqual(self.clean(d), [])
        self.assertEqual(core.structure_at(d, 10.0)["id"], "t")
        self.assertEqual(core.structure_at(d, self.L - 10)["id"], "t")
        self.assertIsNone(core.structure_at(d, 500.0))
        self.assertEqual(core.structure_at(d, self.L - 50, slack=30)["id"], "t")

    def test_the_defaults_of_a_wrapping_structure(self):
        d = copy.deepcopy(self.ring)
        d["structures"] = [{"id": "t", "kind": "tunnel", "s_start": self.L - 30, "s_end": 30, "clearance": 5}]
        out = core.structure_defaults(d)
        band = out["shelter"][0]["band"]
        self.assertEqual((band["s_start"], band["s_end"]), (self.L - 30, 30))      # a band may cross s = 0 on a closed line
        self.assertEqual(out["terrain_sections"][0]["s_start"], self.L - 30)

    def test_overlaps_are_found_across_the_start_line(self):
        d = copy.deepcopy(self.ring)
        d["structures"] = [{"id": "t", "kind": "tunnel", "s_start": self.L - 30, "s_end": 30, "clearance": 5},
                           {"id": "b", "kind": "bridge", "s_start": 10, "s_end": 60}]
        self.finding(d, "WARN", "overlaps structure 't'")

    # -- the validator --
    def test_a_section_may_cross_s_zero_on_a_closed_line(self):
        d = self.doc(sections=[{"s_start": self.L - 100, "s_end": 100, "template": "a"}])
        self.assertEqual([m for m in self.clean(d) if "sections" in m], [])

    def test_sections_overlapping_across_s_zero(self):
        d = self.doc(sections=[{"s_start": self.L - 100, "s_end": 100, "template": "a"}, {"s_start": 50, "s_end": 300, "template": "a"}])
        self.finding(d, "ERROR", "overlaps the previous section")

    def test_an_empty_range_is_not_a_lap(self):
        d = self.doc(sections=[{"s_start": 10, "s_end": 10, "template": "a"}])
        self.finding(d, "ERROR", "equals s_start (a full lap is s_start 0")

    def test_the_whole_lap_is_s_start_zero_to_the_length(self):
        d = self.doc(sections=[{"s_start": 0, "s_end": self.L, "template": "a"}])
        self.assertEqual([m for m in self.clean(d) if "sections" in m], [])

    def test_terrain_rule_section_may_cross_s_zero(self):
        d = copy.deepcopy(self.ring)
        d["reference"]["centerline"]["terrain"] = {"mode": "free", "sections": [{"s_start": self.L - 50, "s_end": 50, "mode": "free"}]}
        self.assertEqual([m for m in self.clean(d) if "terrain" in m], [])

    def test_an_open_line_still_rejects_a_range_that_wraps(self):
        d = copy.deepcopy(self.ring)
        d["reference"]["centerline"]["closed"] = False
        d["track_info"]["type"] = "point_to_point"
        d["structures"] = [{"id": "t", "kind": "tunnel", "s_start": 900, "s_end": 30, "clearance": 5}]
        self.finding(d, "ERROR", "only a closed line may cross s = 0")

    # -- an OpenDRIVE-only circuit has no centerline object, but it is still a loop --
    def opendrive_ring(self, typ="circuit"):
        return {"_metadata": {"specification": "STJ", "version": "0.3", "coordinate_system": "OpenDRIVE", "units": "SI"},
                "track_info": {"name": "OD ring", "type": typ},
                "reference": {"opendrive": {"uri": "ring.xodr"}, "length": 1000.0},
                "surfaces": {"default": "asphalt", "library": {"asphalt": {"class": "asphalt"}},
                             "bands": [{"s_start": 950, "s_end": 50, "t_min": -4, "t_max": 4, "surface": "asphalt"}]},
                "timing": {"start_finish": {"s": 0.0}},
                "structures": [{"id": "t", "kind": "tunnel", "s_start": 960, "s_end": 30, "clearance": 5}]}

    def test_an_opendrive_only_circuit_takes_its_lap_from_the_type_and_length(self):
        d = self.opendrive_ring()
        self.assertEqual(core.reference_lap(d), 1000.0)
        bad = [m for m in messages(run(d), "ERROR") + messages(run(d), "WARN") if "xodr" not in m]
        self.assertEqual(bad, [])
        self.assertEqual(core.structure_at(d, 10.0)["id"], "t")
        self.assertEqual(core.structure_at(d, 980.0)["id"], "t")
        band = core.structure_defaults(d)["shelter"][0]["band"]
        self.assertEqual((band["s_start"], band["s_end"]), (960, 30))

    def test_the_same_reference_declared_open_has_no_lap(self):
        d = self.opendrive_ring("point_to_point")
        self.assertIsNone(core.reference_lap(d))
        self.assertIsNone(core.structure_at(d, 10.0))

    def test_a_closed_centerline_gives_its_length_as_the_lap(self):
        self.assertAlmostEqual(core.reference_lap(self.ring), self.L)

    def test_the_bank_beyond_the_lap_is_an_error(self):
        d = self.doc(bank=[[0, 0.0], [self.L + 50, 0.02]])
        self.finding(d, "ERROR", "is beyond the line")



class GroundStaysOnTheBaseLine(unittest.TestCase):
    """Ground data keeps its base-line s and t in every layout; reverse_ground maps it on request (spec §3.5)."""

    def setUp(self):
        d = core.load_document(STAGE)
        self.doc = d
        self.L = core.reference_line(d).length

    def test_a_reversed_layout_document_keeps_the_ground_as_it_is(self):
        out = core.layout_document(self.doc, "ss1_reverse")
        self.assertEqual(out["reference"]["centerline"]["cross_section"], self.doc["reference"]["centerline"]["cross_section"])
        self.assertEqual(out["structures"], self.doc["structures"])
        self.assertEqual(out["junctions"], self.doc["junctions"])
        self.assertEqual(out["surfaces"]["bands"], self.doc["surfaces"]["bands"])

    def test_only_the_line_itself_is_reversed(self):
        out = core.layout_document(self.doc, "ss1_reverse")
        base_pts = self.doc["reference"]["centerline"]["points"]
        self.assertEqual(out["reference"]["centerline"]["points"], base_pts[::-1])

    def test_reverse_reference_leaves_the_profile_alone(self):
        rev = core.reverse_reference(self.doc["reference"])
        self.assertEqual(rev["centerline"]["cross_section"], self.doc["reference"]["centerline"]["cross_section"])

    def test_reverse_ground_maps_structures_and_junctions(self):
        out = core.reverse_ground(self.doc)
        st, base = out["structures"][0], self.doc["structures"][0]
        self.assertAlmostEqual(st["s_start"], self.L - base["s_end"])
        self.assertAlmostEqual(st["s_end"], self.L - base["s_start"])
        ref_j = next(r for r in out["junctions"][0]["roads"] if r["road"] == "reference")
        base_j = next(r for r in self.doc["junctions"][0]["roads"] if r["road"] == "reference")
        self.assertAlmostEqual(ref_j["s"], self.L - base_j["s"])
        self.assertEqual(self.doc["structures"][0]["s_start"], base["s_start"], "the input is not changed")

    def test_ground_in_layout_coordinates_pairs_with_the_layouts_pace_notes(self):
        doc = core.layout_document(self.doc, "ss1_reverse", ground="layout")
        st = doc["structures"][0]
        self.assertAlmostEqual(st["s_start"], self.L - self.doc["structures"][0]["s_end"])
        mid = 0.5 * (st["s_start"] + st["s_end"])
        self.assertEqual(core.structure_at(doc, mid)["id"], "viaduct_1")

    def test_the_example_validates_with_its_reverse_layout(self):
        rep = validate.validate(STAGE)
        self.assertEqual(messages(rep, "ERROR") + messages(rep, "WARN"), [])
        self.assertFalse([m for m in messages(rep, "NOTE") if "no structure there" in m])

    def test_a_wrapping_structure_maps_to_a_wrapping_range(self):
        L = 1000.0
        doc = {"reference": {"length": L}, "track_info": {"type": "circuit"},
               "structures": [{"id": "t", "kind": "tunnel", "s_start": 970.0, "s_end": 30.0, "clearance": 5}]}
        out = core.reverse_ground(doc, L)["structures"][0]
        self.assertEqual((out["s_start"], out["s_end"]), (970.0, 30.0))      # the same stretch, driven the other way



def loop_doc(**extra):
    """Four straight 100 m roads (the reference and a, b, c) that form a square, with their joints and a closed route."""
    doc = flat_line_doc()

    def road(rid, pts):
        return {"id": rid, "centerline": {"points": pts}}
    doc["roads"] = [road("a", [[100, 0, 0], [100, 100, 0]]), road("b", [[100, 100, 0], [0, 100, 0]]), road("c", [[0, 100, 0], [0, 0, 0]])]
    doc["junctions"] = [
        {"id": "j1", "roads": [{"road": "reference", "s": 100, "end": "end"}, {"road": "a", "s": 0, "end": "start"}]},
        {"id": "j2", "roads": [{"road": "a", "s": 100, "end": "end"}, {"road": "b", "s": 0, "end": "start"}]},
    ]
    doc["continues"] = [{"from": {"road": "b", "end": "end"}, "to": {"road": "c", "end": "start"}},
                        {"from": {"road": "c", "end": "end"}, "to": {"road": "reference", "end": "start"}}]
    doc["routes"] = [{"id": "loop", "closed": True, "steps": [{"road": "reference"}, {"road": "a"}, {"road": "b"}, {"road": "c"}]}]
    doc.update(extra)
    return doc


class JointsAndRoutes(unittest.TestCase):
    """Junction data, continuations and routes through several roads (spec §7.1)."""

    def finding(self, doc, level, fragment):
        found = messages(run(doc), level)
        self.assertTrue(any(fragment in m for m in found), f"no {level} containing {fragment!r} in {found}")

    def clean(self, doc):
        rep = run(doc)
        return messages(rep, "ERROR") + messages(rep, "WARN")

    def test_a_loop_of_four_roads_is_valid(self):
        self.assertEqual(self.clean(loop_doc()), [])

    def test_route_length_and_locating(self):
        doc = loop_doc()
        self.assertAlmostEqual(core.route_length(doc, "loop"), 400.0)
        self.assertEqual(core.route_locate(doc, "loop", 250.0), ("b", 50.0))
        self.assertEqual(core.route_locate(doc, "loop", 450.0)[0], "reference")          # a closed route wraps
        self.assertEqual(core.route_s(doc, "loop", "b", 50.0), [250.0])

    def test_a_step_driven_backwards(self):
        doc = loop_doc()
        doc["routes"] = [{"id": "back", "steps": [{"road": "a", "direction": "backward"}, {"road": "reference", "direction": "backward"}]}]
        self.assertEqual(core.route_locate(doc, "back", 30.0), ("a", 70.0))
        self.assertEqual(core.route_locate(doc, "back", 130.0), ("reference", 70.0))
        pts = core.route_centerline(doc, "back")["points"]
        self.assertEqual([tuple(q[:2]) for q in pts], [(100.0, 100.0), (100.0, 0.0), (0.0, 0.0)])

    def test_a_route_is_a_centerline(self):
        cl = core.route_centerline(loop_doc(), "loop")
        self.assertTrue(cl["closed"])
        self.assertEqual([tuple(q[:2]) for q in cl["points"]], [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)])

    def test_a_layout_takes_a_route_as_its_reference_line(self):
        doc = loop_doc(layouts=[{"id": "lap", "route": "loop"}])
        line = core.reference_line(core.layout_document(doc, "lap"))
        self.assertTrue(line.closed)
        self.assertAlmostEqual(line.length, 400.0)
        self.assertEqual(self.clean(doc), [])

    def test_a_layout_route_must_exist_and_stand_alone(self):
        self.finding(loop_doc(layouts=[{"id": "x", "route": "nope"}]), "ERROR", "unknown route 'nope'")
        self.finding(loop_doc(layouts=[{"id": "x", "route": "loop", "direction": "reverse"}]), "ERROR", "not together with reference")

    def test_steps_that_do_not_meet_are_an_error(self):
        doc = loop_doc()
        doc["routes"][0]["steps"] = [{"road": "reference"}, {"road": "b"}]
        self.finding(doc, "ERROR", "from where the previous step ends")

    def test_a_closed_route_must_come_back(self):
        doc = loop_doc()
        doc["routes"][0]["steps"] = doc["routes"][0]["steps"][:3]
        self.finding(doc, "ERROR", "closed, but the last step ends")

    def test_a_missing_link_is_a_note(self):
        doc = loop_doc()
        doc["continues"], doc["junctions"] = [], []
        rep = run(doc)
        self.assertEqual(messages(rep, "ERROR") + messages(rep, "WARN"), [])
        self.assertTrue(any("no junction or continuation joins" in m for m in messages(rep, "NOTE")))

    def test_step_ranges_are_checked(self):
        doc = loop_doc()
        doc["routes"][0]["steps"][1] = {"road": "a", "s_start": 60, "s_end": 20}
        self.finding(doc, "ERROR", "s_end must be greater than s_start")
        doc["routes"][0]["steps"][1] = {"road": "a", "s_start": 0, "s_end": 400}
        self.finding(doc, "ERROR", "outside road 'a'")
        doc["routes"][0]["steps"][1] = {"road": "ghost"}
        self.finding(doc, "ERROR", "unknown road 'ghost'")

    def test_the_through_road_is_a_member(self):
        doc = loop_doc()
        doc["junctions"][0]["through"] = "c"
        self.finding(doc, "ERROR", "'c' is not a member of the junction")

    def test_end_must_match_s(self):
        doc = loop_doc()
        doc["junctions"][0]["roads"][1]["end"] = "end"
        self.finding(doc, "WARN", "is not at the end of road 'a'")

    def test_the_through_road_has_the_best_rank(self):
        doc = loop_doc()
        doc["junctions"][0].update(through="reference")
        doc["junctions"][0]["roads"][0]["rank"] = 2
        doc["junctions"][0]["roads"][1]["rank"] = 1
        self.finding(doc, "WARN", "has a better rank than the through road")

    def test_roads_that_meet_agree_in_height(self):
        doc = loop_doc()
        doc["roads"][0]["centerline"]["points"][0] = [100, 0, 3]
        self.finding(doc, "WARN", "differ by 3.0 m in height")
        doc["junctions"][0]["kind"] = "grade_separated"
        self.assertEqual([m for m in self.clean(doc) if "differ by" in m and "junctions" in m], [])

    def test_grade_separated_roads_need_not_meet(self):
        doc = loop_doc()
        doc["junctions"].append({"id": "over", "kind": "grade_separated",
                                 "roads": [{"road": "reference", "s": 50}, {"road": "b", "s": 50}]})
        self.assertEqual([m for m in self.clean(doc) if "apart" in m], [])
        doc["junctions"][-1]["kind"] = "at_grade"
        self.finding(doc, "WARN", "apart at their junction points")

    def test_a_continuation_joins_two_ends(self):
        doc = loop_doc()
        doc["continues"][0]["to"] = {"road": "reference", "end": "end"}
        self.finding(doc, "WARN", "road ends are")
        doc["continues"][0] = {"from": {"road": "b", "end": "end"}, "to": {"road": "b", "end": "end"}}
        self.finding(doc, "ERROR", "joins a road end to itself")

    def test_an_end_continues_only_once(self):
        doc = loop_doc()
        doc["continues"].append({"from": {"road": "b", "end": "end"}, "to": {"road": "c", "end": "start"}})
        self.finding(doc, "WARN", "already carries on")

    def test_join_notes(self):
        doc = loop_doc()
        doc["junctions"][0]["through"] = "reference"
        doc["junctions"][0]["roads"][1]["join"] = {"mode": "edge_snap"}
        doc["junctions"][0]["height"] = {"mode": "blend"}
        notes = messages(run(doc), "NOTE")
        self.assertTrue(any("edge_snap without a reach" in m for m in notes))
        self.assertTrue(any("blend without a radius" in m for m in notes))

    def test_joint_point_is_the_through_road(self):
        doc = loop_doc()
        doc["junctions"][0]["through"] = "a"
        self.assertEqual(tuple(round(v, 6) for v in core.joint_point(doc, "j1")), (100.0, 0.0, 0.0))
        self.assertTrue(core.roads_linked(doc, "reference", "a"))
        self.assertFalse(core.roads_linked(doc, "reference", "b"))



class DataSourcesAndLicences(unittest.TestCase):
    """provenance.sources[], several sources in derived, derived on the line, licence rules (spec §5.2)."""

    def setUp(self):
        self.doc = core.load_document(STAGE)
        self.hm = self.doc["geometry"]["terrain"]["heightmap"]
        self.md = self.doc["_metadata"]
        self.md["provenance"] = {"type": "scanned", "scan": {"method": "lidar", "sources": [
            {"id": "als", "format": "laz", "reference": "tile 0404", "crs": "EPSG:25831", "point_density": 8.0, "classified": True}]},
            "sources": [
                {"id": "osm", "kind": "osm", "reference": "overpass extract", "retrieved": "2026-10-01", "crs": "EPSG:4326",
                 "licence": {"spdx": "ODbL-1.0", "attribution": "(c) OpenStreetMap contributors", "share_alike": True}},
                {"id": "glo", "kind": "dem", "reference": "global DEM tile", "crs": "EPSG:4326",
                 "licence": {"spdx": "CC-BY-4.0", "attribution": "Global DEM team"}}]}

        for m in self.doc["geometry"].get("meshes", []):
            m.pop("generated", None)                                    # the line changes below: the stamp would be stale
        self.baseline = set(self.problems())                            # a temp copy of the example has findings of its own

    def problems(self):
        rep = run(self.doc)
        return messages(rep, "ERROR") + messages(rep, "WARN")

    def new_problems(self):
        return [m for m in self.problems() if m not in self.baseline]

    def level(self, level):
        return messages(run(self.doc), level)

    def finding(self, level, fragment):
        found = self.level(level)
        self.assertTrue(any(fragment in m for m in found), f"no {level} containing {fragment!r} in {found}")

    def test_the_example_with_sources_is_clean(self):
        self.assertEqual(self.new_problems(), [])

    def test_derived_may_name_several_sources_and_a_void_source(self):
        self.hm["derived"] = {"sources": ["als", "glo"], "product": "dtm", "cell_size": 2.0, "void_fill": "from_other_source", "void_source": "glo"}
        self.assertEqual(self.new_problems(), [])

    def test_derived_can_use_a_data_source(self):
        self.hm["derived"] = {"source": "glo", "product": "dtm", "cell_size": 30.0}
        self.assertEqual(self.new_problems(), [])

    def test_unknown_source_in_the_list_and_the_void_source(self):
        self.hm["derived"] = {"sources": ["als", "nope"], "product": "dtm", "cell_size": 2.0, "void_fill": "from_other_source", "void_source": "gone"}
        self.finding("ERROR", "sources: unknown source 'nope'")
        self.finding("ERROR", "void_source: unknown source 'gone'")

    def test_derived_needs_a_source(self):
        self.hm["derived"] = {"product": "dtm"}
        self.assertTrue(any("heightmap.derived" in m for m in self.level("ERROR")))

    def test_void_source_and_void_fill_go_together(self):
        self.hm["derived"] = {"source": "als", "product": "dtm", "cell_size": 2.0, "void_fill": "from_other_source"}
        self.finding("NOTE", "void_source does not say which")
        self.hm["derived"] = {"source": "als", "product": "dtm", "cell_size": 2.0, "void_source": "glo"}
        self.finding("NOTE", "void_fill is not from_other_source")

    def test_ids_are_shared_between_scans_and_data_sources(self):
        self.md["provenance"]["sources"][0]["id"] = "als"
        self.finding("ERROR", "is also a scan source")

    def test_derived_on_the_centerline_and_the_cross_section(self):
        cl = self.doc["reference"]["centerline"]
        cl["derived"] = {"source": "als", "product": "road_surface", "classes": [11], "method": "median of ground points under the road"}
        cl.setdefault("cross_section", {})["derived"] = {"source": "glo", "product": "dtm", "method": "cross-slope of the DEM"}
        self.assertEqual(self.new_problems(), [])
        self.assertEqual([m for m in self.level("NOTE") if "cell_size" in m and "centerline" in m], [])
        cl["derived"]["source"] = "nope"
        self.finding("ERROR", "reference.centerline.derived.source: unknown source 'nope'")

    def test_a_source_that_is_not_redistributable_contradicts_a_redistributable_file(self):
        self.md["licence"] = {"spdx": "CC-BY-4.0", "redistributable": True}
        self.md["provenance"]["sources"][1]["licence"]["redistributable"] = False
        self.finding("WARN", "true, but source 'glo' is not redistributable")
        self.assertFalse(core.licence_summary(self.doc)["redistributable"])

    def test_the_summary_collects_attribution_and_share_alike(self):
        summary = core.licence_summary(self.doc)
        self.assertTrue(summary["redistributable"])
        self.assertEqual(summary["share_alike"], ["osm"])
        self.assertEqual(summary["attribution"], ["(c) OpenStreetMap contributors", "Global DEM team"])

    def test_share_alike_and_non_commercial_are_notes(self):
        self.md["provenance"]["sources"][1]["licence"]["commercial_use"] = False
        self.finding("NOTE", "source 'osm' is share-alike")
        self.finding("NOTE", "source 'glo' forbids commercial use")

    def test_a_licence_that_asks_for_a_credit_line_needs_one(self):
        del self.md["provenance"]["sources"][1]["licence"]["attribution"]
        self.finding("WARN", "source 'glo' has a licence that asks for attribution")
        self.assertEqual(core.licence_summary(self.doc)["missing_attribution"], ["glo"])


if __name__ == "__main__":
    unittest.main()
