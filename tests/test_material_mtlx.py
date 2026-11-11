"""The MaterialX writer for ordinary materials (tools/material_mtlx.py) against the maths of its own description, and its
node names against the MaterialX standard library. Needs pxr."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stj_core as core  # noqa: E402

HAVE = core.have_pxr()
if HAVE:
    import material_mtlx as mm  # noqa: E402
    from mtlx_eval import Evaluator  # noqa: E402


def srgb(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


@unittest.skipUnless(HAVE, "pxr not installed")
class MaterialMtlx(unittest.TestCase):
    def setUp(self):
        from pxr import Usd
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        # a 2 x 1 colour map, a 2 x 1 packed map (r = occlusion, g = roughness, b = metalness) and a normal map
        core.write_png(self.dir / "d.png", 2, 1, [200, 100, 50, 10, 20, 30], channels=3)
        core.write_png(self.dir / "orm.png", 2, 1, [255, 128, 0, 64, 200, 255], channels=3)
        core.write_png(self.dir / "n.png", 2, 1, [128, 128, 255, 128, 128, 255], channels=3)
        self.stage = Usd.Stage.CreateNew(str(self.dir / "m.usda"))
        self.env = {"geomprops": {"st": (0.25, 0.5), "displayColor": (0.5, 1.0, 0.5), "mixw": 0.25, "stj_mix": 0.25},
                    "position": (0, 0, 0)}

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, spec, name="M"):
        notes = mm.write_material(self.stage, f"/m/materials/{name}", spec)
        ev = Evaluator(self.stage.GetPrimAtPath(f"/m/materials/{name}"), self.env)
        return ev.surface(), notes

    def test_a_packed_material_with_tint_vertex_colour_and_normal(self):
        s, notes = self.write({"base_color": {"uri": "d.png", "tint": [0.5, 1.0, 1.0], "vertex_colour": "displayColor"},
                               "roughness": {"uri": "orm.png", "channel": "g"}, "metalness": {"uri": "orm.png", "channel": "b"},
                               "occlusion": {"uri": "orm.png", "channel": "r"}, "normal": {"uri": "n.png"}})
        self.assertEqual(notes, [])
        d0 = [srgb(200), srgb(100), srgb(50)]                       # u = 0.25 reads the first texel
        want = [d0[0] * 0.5 * 0.5, d0[1] * 1.0 * 1.0, d0[2] * 1.0 * 0.5]      # tint x vertex colour (occlusion is 1 here)
        for got, w in zip(s["base_color"], want):
            self.assertAlmostEqual(got, w, places=6)
        self.assertAlmostEqual(s["specular_roughness"], 128 / 255.0, places=6)
        self.assertAlmostEqual(s["base_metalness"], 0.0, places=6)
        self.assertEqual(len(s["geometry_normal"]), 3)

    def test_gloss_is_inverted_and_constants_are_written(self):
        s, _ = self.write({"base_color": {"value": [0.2, 0.3, 0.4]}, "roughness": {"uri": "orm.png", "channel": "g", "gloss": True},
                           "metalness": {"value": 0.7}, "emissive": {"color": [1, 0.5, 0], "luminance": 3.0},
                           "opacity": {"value": 0.4}})
        self.assertAlmostEqual(s["specular_roughness"], 1.0 - 128 / 255.0, places=6)
        self.assertAlmostEqual(s["base_metalness"], 0.7, places=6)
        self.assertEqual(tuple(round(c, 6) for c in s["base_color"]), (0.2, 0.3, 0.4))
        self.assertAlmostEqual(s["emission_luminance"], 3.0)
        self.assertAlmostEqual(s["geometry_opacity"], 0.4, places=6)

    def test_two_layers_mixed_by_a_vertex_value(self):
        a = {"base_color": {"value": [1.0, 0.0, 0.0]}, "roughness": {"value": 0.2}}
        b = {"base_color": {"value": [0.0, 0.0, 1.0]}, "roughness": {"value": 0.8}}
        s, notes = self.write({"layers": [a, b], "weight": {"primvar": "stj_mix"}})
        self.assertEqual(notes, [])
        self.assertEqual(tuple(round(c, 6) for c in s["base_color"]), (0.75, 0.0, 0.25))
        self.assertAlmostEqual(s["specular_roughness"], 0.2 * 0.75 + 0.8 * 0.25, places=6)

    def test_a_weight_from_a_map_channel(self):
        a = {"base_color": {"value": [1.0, 1.0, 1.0]}}
        b = {"base_color": {"value": [0.0, 0.0, 0.0]}}
        s, _ = self.write({"layers": [a, b], "weight": {"uri": "orm.png", "channel": "g"}})
        self.assertAlmostEqual(s["base_color"][0], 1.0 - 128 / 255.0, places=6)

    def test_a_key_on_one_layer_only_is_noted(self):
        _, notes = self.write({"layers": [{"base_color": {"value": [1, 1, 1]}},
                                          {"base_color": {"value": [0, 0, 0]}, "roughness": {"value": 0.5}}],
                               "weight": {"primvar": "mixw"}})
        self.assertTrue(any("one layer only" in n for n in notes))

    def test_the_preview_surface_is_not_touched(self):
        from pxr import UsdShade
        mat = UsdShade.Material.Define(self.stage, "/m/materials/P")
        sh = UsdShade.Shader.Define(self.stage, "/m/materials/P/surface")
        sh.CreateIdAttr("UsdPreviewSurface")
        mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
        mm.write_material(self.stage, "/m/materials/P", {"base_color": {"value": [1, 1, 1]}})
        rp = core.usd_material_report(self.stage.GetPrimAtPath("/m/materials/P"))
        self.assertEqual(rp["surface"], "UsdPreviewSurface")
        self.assertTrue(rp["mtlx"])

    def test_only_standard_library_nodes_with_the_right_inputs(self):
        try:
            import MaterialX as mx
        except ImportError:
            self.skipTest("the MaterialX package is not installed")
        doc = mx.createDocument()
        mx.loadLibraries(mx.getDefaultDataLibraryFolders(), mx.getDefaultDataSearchPath(), doc)
        for nid, (ins, outs) in mm.EXTRA.items():
            nd = doc.getNodeDef(nid)
            self.assertIsNotNone(nd, nid)
            have_in = {i.getName(): i.getType() for i in nd.getInputs()}
            for name, typ in ins.items():
                self.assertEqual(have_in.get(name), typ, f"{nid}.{name}")
            have_out = {o.getName(): o.getType() for o in nd.getOutputs()} or {"out": nd.getType()}
            for name, typ in outs.items():
                self.assertEqual(have_out.get(name), typ, f"{nid} output {name}")


if __name__ == "__main__":
    unittest.main()
