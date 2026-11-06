"""The MaterialX network of tools/ground_materialx.py against the reference blend (spec §8.7)."""

import copy
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import ground_bake as gb  # noqa: E402
import ground_materialx as gm_tool  # noqa: E402
import mtlx_eval  # noqa: E402
import stj_core as core  # noqa: E402

EX = ROOT / "examples"
STAGE = EX / "coll_de_prova_gravel.usda"


def reference(doc, gm, base_dir, idx, wa, wb, position, road_uv, st):
    """The colour the bake would give: the same code path as ground_bake._raster, for one fragment."""
    layers = [doc["ground"]["layers"][lid] for lid in gm["palette"]]
    tex = [gb.Texture(Path(base_dir) / l["albedo"]["uri"]) for l in layers]
    blend = gm.get("blend") or {}
    weights = [wa, wb, max(0.0, 1.0 - wa - wb)]
    x, y = position[0], position[1]
    cols, hts, means, cons = [], [], [], []
    for li in idx:
        layer = layers[li]
        proj = layer.get("projection", "world_xy")
        if proj == "world_xy":
            u, v = x / layer["tile"], y / layer["tile"]
        elif proj == "road":
            u, v = road_uv[0] / layer["tile"], road_uv[1] / layer["tile"]
        else:
            sc = proj.get("scale", 1.0) / layer["tile"]
            u, v = sc * road_uv[0], sc * road_uv[1]          # the example's texcoord primvar is road_uv
        rgb, h = tex[li].sample(u, v)
        cols.append(rgb)
        hts.append(h if layer["albedo"].get("height_in_alpha") else tex[li].mean_alpha)
        means.append(tex[li].mean_alpha)
        cons.append(layer.get("height_contrast", 1.0))
    method = blend.get("method", "height")
    if method == "mask":
        masks = blend.get("mask")
        masks = [masks] if isinstance(masks, dict) else masks
        vals = []
        for mk in masks:
            mt = gb.Texture(Path(base_dir) / mk["uri"])
            rgb, _a = mt.sample(x / mk["tile"], y / mk["tile"], data=True)
            vals.append(rgb[{"r": 0, "g": 1, "b": 2, "gray": 0}[mk.get("channel", "r")]])
        order = sorted(range(3), key=lambda i: idx[i])
        part = core.ground_blend([weights[i] for i in order], [hts[i] for i in order], [means[i] for i in order],
                                 [cons[i] for i in order], "mask", masks=[vals[idx[i] - 1] for i in order[1:]],
                                 softness=blend.get("softness", core.MASK_DEFAULT_SOFTNESS))
        fb = [0.0] * 3
        for i, share in zip(order, part):
            fb[i] += share
    else:
        fb = core.ground_blend(weights, hts, means, cons, method, blend.get("height_influence", 0.5), blend.get("depth", 0.2))
    colour = tuple(sum(f * c[ch] for f, c in zip(fb, cols)) for ch in range(3))
    macros = []
    for mc in gm.get("macro", []):
        enc = mc.get("encoding", "grey_centred")
        mt = gb.Texture(Path(base_dir) / mc["uri"])
        rgb, _a = mt.sample(st[0], 1.0 - st[1], data=enc != "colour")
        macros.append((rgb, enc, mc.get("strength", 1.0)))
    base = core.ground_mean_colour(weights, [tex[li].mean_rgb for li in idx])
    return core.apply_macro(colour, macros, base)


class GroundMaterialX(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc, cls.chain = core.resolve(STAGE)
        cls.base_dir = cls.chain[0].parent
        cls.tmp = tempfile.TemporaryDirectory()
        cls.count = 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def network(self, gm):
        """Write the network for `gm` into a copy of the ground mesh; returns (doc, stage, notes)."""
        from pxr import Sdf, UsdShade
        doc = copy.deepcopy(self.doc)
        doc["ground"]["materials"][0] = gm
        mesh = next(m for m in doc["geometry"]["meshes"] if m["id"] == gm["mesh_ref"])
        type(self).count += 1
        out = Path(self.tmp.name) / f"g{self.count}.usda"
        Sdf.Layer.FindOrOpen(str(self.base_dir / mesh["uri"])).Export(str(out))
        stage = core.usd_stage(out)
        prim = next(p for p in stage.Traverse() if p.IsA(UsdShade.Material) and p.GetName() == gm["material"])
        notes = gm_tool.build_network(stage, prim, doc, gm, self.base_dir, out)
        stage.GetRootLayer().Save()
        return doc, core.usd_stage(out), notes

    def compare(self, gm, samples=60, seed=7):
        from pxr import UsdShade
        doc, stage, notes = self.network(gm)
        prim = next(p for p in stage.Traverse() if p.IsA(UsdShade.Material) and p.GetName() == gm["material"])
        rng = random.Random(seed)
        worst = 0.0
        n = len(gm["palette"])
        for _ in range(samples):
            idx = [rng.randrange(n) for _ in range(3)]
            wa = rng.random() * 0.8
            wb = rng.random() * (1.0 - wa)
            pos = (rng.uniform(-300, 900), rng.uniform(-300, 900), 0.0)
            ruv = (rng.uniform(-6, 6), rng.uniform(0, 600))
            st = (rng.uniform(0.02, 0.98), rng.uniform(0.02, 0.98))
            env = {"position": pos, "geomprops": {"stj_ground_layers_0": idx[0], "stj_ground_layers_1": idx[1],
                                                  "stj_ground_layers_2": idx[2], "stj_ground_weights": (wa, wb),
                                                  "road_uv": ruv, "st": st}}
            got = mtlx_eval.Evaluator(prim, env).base_color()
            want = reference(doc, gm, self.base_dir, idx, wa, wb, pos, ruv, st)
            worst = max(worst, max(abs(a - b) for a, b in zip(got, want)))
        return worst, notes

    def gm(self, **blend):
        gm = copy.deepcopy(self.doc["ground"]["materials"][0])
        if blend:
            gm["blend"] = blend
        return gm

    def test_height_blend_matches_the_reference(self):
        worst, notes = self.compare(self.gm())
        self.assertLess(worst, 1e-4, notes)

    def test_linear_blend_matches_the_reference(self):
        worst, _ = self.compare(self.gm(method="linear"))
        self.assertLess(worst, 1e-4)

    def test_mask_blend_matches_the_reference(self):
        mk = {"uri": "ground/rock.png", "tile": 4.0, "channel": "r"}
        gm = self.gm(method="mask", softness=0.2, mask=[mk, {**mk, "tile": 6.0, "channel": "g"}, {**mk, "tile": 9.0}])
        worst, _ = self.compare(gm)
        self.assertLess(worst, 1e-4)

    def test_every_macro_encoding_matches_the_reference(self):
        gm = self.gm()
        gm["macro"] = [{"kind": "tint", "uri": "ground/sec01_tint.png", "texcoord": "st", "encoding": "grey_centred"},
                       {"kind": "tint", "uri": "ground/sec01_tint.png", "texcoord": "st", "encoding": "multiply"},
                       {"kind": "tint", "uri": "ground/sec01_tint.png", "texcoord": "st", "encoding": "colour", "strength": 0.7}]
        worst, notes = self.compare(gm)
        self.assertLess(worst, 1e-4, notes)

    def test_what_is_left_out_is_reported(self):
        gm = self.gm()
        gm["macro"] = [{"kind": "tint", "uri": "ground/sec01_tint.png", "extent": [0, 0, 100, 100]},
                       {"kind": "wetness", "uri": "ground/sec01_tint.png", "texcoord": "st"}]
        _doc, _stage, notes = self.network(gm)
        self.assertTrue(any("over an extent" in n for n in notes))
        self.assertTrue(any("wetness" in n for n in notes))

    def test_the_fallback_surface_is_kept(self):
        from pxr import UsdShade
        _doc, stage, _notes = self.network(self.gm())
        mat = next(p for p in stage.Traverse() if p.IsA(UsdShade.Material) and p.GetName() == "Ground_Sec01")
        names = {o.GetFullName() for o in UsdShade.Material(mat).GetOutputs()}
        self.assertEqual(names, {"outputs:surface", "outputs:mtlx:surface"})

    def test_unsupported_encodings_stop_with_a_message(self):
        gm = self.gm()
        gm["weights"] = {"encoding": "image", "maps": [{"uri": "ground/sec01_tint.png"}], "texcoord": "st"}
        with self.assertRaises(SystemExit):
            self.network(gm)

    def test_only_standard_library_nodes_with_the_right_inputs(self):
        """Every node id, input and output name checked against the MaterialX standard library, when it is installed."""
        try:
            import MaterialX as mx
        except ImportError:
            self.skipTest("the MaterialX package is not installed")
        doc = mx.createDocument()
        mx.loadLibraries(mx.getDefaultDataLibraryFolders(), mx.getDefaultDataSearchPath(), doc)
        for nid, (ins, outs) in gm_tool.NODES.items():
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
