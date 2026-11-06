"""
Ground to MaterialX
===================
Writes the layered ground of a track (spec §8.7) as a MaterialX network on the ground material of its USD
mesh, so Blender and USD viewers show the real layers and blend instead of a baked image. The network is
a **derived view**: the `ground` block stays the source of truth, and where the two disagree the block wins.
Needs the pxr module: pip install usd-core.

    python tools/ground_materialx.py <track.usda | doc.stj.json> -o <mesh.usda> [--material NAME]

The mesh file named by the ground material is copied to -o with `outputs:mtlx:surface` added to that
material (its UsdPreviewSurface fallback stays). Texture paths are rewritten relative to the new file.

What it writes, with the same maths as `stj_core.ground_blend` and `apply_macro`:
- the vertex_top3 weights: the three per-face layer index primvars and the faceVarying weight primvar
- every palette layer's albedo, projected as the layer says (world_xy, road through the `road_uv`
  primvar, or a texcoord primvar), with its height from the albedo alpha or its mean
- the height, linear and mask blends (the mask blend orders the three layers present by palette index)
- macro maps given by a texcoord primvar (grey_centred, multiply and colour)
What it leaves out, and says so: other weight encodings, macro maps over an extent, wetness maps, the
normal, roughness and occlusion maps of the layers. The surface is an OpenPBR surface (what Blender's own USD
export writes) with a constant roughness of 0.9.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ground_bake as gb  # noqa: E402
import stj_core as core  # noqa: E402

MAX_PALETTE = 10            # the MaterialX switch node takes ten inputs
EPS = 1e-6
ROUGHNESS = 0.9

_F = "float"
_IMG = {"file": "filename", "texcoord": "vector2", "uaddressmode": "string", "vaddressmode": "string"}
_SW = {**{f"in{i}": "float" for i in range(1, 11)}, "which": "float"}
_SWC = {**{f"in{i}": "color3" for i in range(1, 11)}, "which": "float"}
_BIN = {"in1": _F, "in2": _F}
_CBIN = {"in1": "color3", "in2": "color3"}
# MaterialX standard library nodes used here: id -> (inputs {name: type}, outputs {name: type})
NODES = {
    "ND_image_color3": (_IMG, {"out": "color3"}),
    "ND_image_color4": (_IMG, {"out": "color4"}),
    "ND_separate4_color4": ({"in": "color4"}, {"outr": _F, "outg": _F, "outb": _F, "outa": _F}),
    "ND_separate3_color3": ({"in": "color3"}, {"outr": _F, "outg": _F, "outb": _F}),
    "ND_combine3_color3": ({"in1": _F, "in2": _F, "in3": _F}, {"out": "color3"}),
    "ND_position_vector3": ({"space": "string"}, {"out": "vector3"}),
    "ND_separate3_vector3": ({"in": "vector3"}, {"outx": _F, "outy": _F, "outz": _F}),
    "ND_separate2_vector2": ({"in": "vector2"}, {"outx": _F, "outy": _F}),
    "ND_combine2_vector2": (_BIN, {"out": "vector2"}),
    "ND_geompropvalue_vector2": ({"geomprop": "string"}, {"out": "vector2"}),
    "ND_geompropvalue_integer": ({"geomprop": "string"}, {"out": "integer"}),
    "ND_convert_integer_float": ({"in": "integer"}, {"out": _F}),
    "ND_add_float": (_BIN, {"out": _F}),
    "ND_subtract_float": (_BIN, {"out": _F}),
    "ND_multiply_float": (_BIN, {"out": _F}),
    "ND_divide_float": (_BIN, {"out": _F}),
    "ND_max_float": (_BIN, {"out": _F}),
    "ND_min_float": (_BIN, {"out": _F}),
    "ND_clamp_float": ({"in": _F, "low": _F, "high": _F}, {"out": _F}),
    "ND_ifgreater_float": ({"value1": _F, "value2": _F, "in1": _F, "in2": _F}, {"out": _F}),
    "ND_switch_float": (_SW, {"out": _F}),
    "ND_switch_color3": (_SWC, {"out": "color3"}),
    "ND_add_color3": (_CBIN, {"out": "color3"}),
    "ND_subtract_color3": (_CBIN, {"out": "color3"}),
    "ND_multiply_color3": (_CBIN, {"out": "color3"}),
    "ND_divide_color3": (_CBIN, {"out": "color3"}),
    "ND_max_color3": (_CBIN, {"out": "color3"}),
    "ND_multiply_color3FA": ({"in1": "color3", "in2": _F}, {"out": "color3"}),
    "ND_clamp_color3": ({"in": "color3", "low": "color3", "high": "color3"}, {"out": "color3"}),
    "ND_mix_color3": ({"fg": "color3", "bg": "color3", "mix": _F}, {"out": "color3"}),
    "ND_open_pbr_surface_surfaceshader": ({"base_color": "color3", "specular_roughness": _F}, {"out": "surfaceshader"}),
}


class Ref:
    """One output of a node."""

    def __init__(self, shader, name, typ):
        self.shader, self.name, self.type = shader, name, typ


class Graph:
    """Builds MaterialX nodes as UsdShade shaders under one prim."""

    def __init__(self, stage, parent_path):
        self.stage, self.parent = stage, parent_path
        self.count = 0
        from pxr import Sdf
        self.T = {"float": Sdf.ValueTypeNames.Float, "integer": Sdf.ValueTypeNames.Int, "color3": Sdf.ValueTypeNames.Color3f,
                  "color4": Sdf.ValueTypeNames.Color4f, "vector2": Sdf.ValueTypeNames.Float2,
                  "vector3": Sdf.ValueTypeNames.Float3, "string": Sdf.ValueTypeNames.String,
                  "filename": Sdf.ValueTypeNames.Asset, "surfaceshader": Sdf.ValueTypeNames.Token}

    def _const(self, typ, value):
        from pxr import Gf, Sdf
        if typ == "color3":
            return Gf.Vec3f(*[float(c) for c in value])
        if typ == "filename":
            return Sdf.AssetPath(value)
        if typ == "integer":
            return int(value)
        if typ == "float":
            return float(value)
        return value

    def node(self, nid, name=None, colorspaces=None, **inputs):
        """Create a node; every input is a constant or a Ref. Returns the Ref of its only output, or a dict of Refs."""
        from pxr import UsdShade
        ins, outs = NODES[nid]
        self.count += 1
        sh = UsdShade.Shader.Define(self.stage, f"{self.parent}/{name or nid[3:]}_{self.count}")
        sh.CreateIdAttr(nid)
        for key, val in inputs.items():
            typ = ins[key]
            inp = sh.CreateInput(key, self.T[typ])
            if isinstance(val, Ref):
                inp.ConnectToSource(val.shader.ConnectableAPI(), val.name)
            else:
                inp.Set(self._const(typ, val))
                if colorspaces and key in colorspaces:
                    inp.GetAttr().SetColorSpace(colorspaces[key])
        refs = {n: Ref(sh, n, t) for n, t in outs.items()}
        for n, t in outs.items():
            sh.CreateOutput(n, self.T[t])
        return refs["out"] if "out" in refs else refs

    # small helpers
    def f(self, nid, a, b):
        return self.node(nid, in1=a, in2=b)

    def add(self, a, b):
        return self.f("ND_add_float", a, b)

    def sub(self, a, b):
        return self.f("ND_subtract_float", a, b)

    def mul(self, a, b):
        return self.f("ND_multiply_float", a, b)

    def div(self, a, b):
        return self.f("ND_divide_float", a, b)

    def mx(self, a, b):
        return self.f("ND_max_float", a, b)

    def clamp(self, a, lo, hi):
        return self.node("ND_clamp_float", **{"in": a, "low": lo, "high": hi})

    def cmul(self, c, k):
        return self.node("ND_multiply_color3FA", in1=c, in2=k)

    def cadd(self, a, b):
        return self.f("ND_add_color3", a, b)

    def switch(self, which, values, color=False):
        """values[which], as a switch; a constant when every value is the same constant."""
        if not any(isinstance(v, Ref) for v in values) and len(set(map(tuple if color else float, values))) == 1:
            return values[0]
        inputs = {f"in{i + 1}": v for i, v in enumerate(values)}
        return self.node("ND_switch_color3" if color else "ND_switch_float", which=which, **inputs)


def _uv(g, layer, mesh_pvs, notes, what):
    """The texture coordinate of a layer or mask, as in ground_bake (v runs the other way: image rows go down)."""
    proj = layer.get("projection", "world_xy")
    tile = layer["tile"]
    if proj == "world_xy":
        pos = g.node("ND_position_vector3", space="world")
        sep = g.node("ND_separate3_vector3", **{"in": pos})
        a, b = sep["outx"], sep["outy"]
        scale = 1.0 / tile
    else:
        pvname = "road_uv" if proj == "road" else proj["texcoord"]
        if pvname not in mesh_pvs:
            notes.append(f"{what}: the mesh has no '{pvname}' primvar")
            return None
        pv = g.node("ND_geompropvalue_vector2", geomprop=pvname)
        sep = g.node("ND_separate2_vector2", **{"in": pv})
        a, b = sep["outx"], sep["outy"]
        scale = (1.0 if proj == "road" else proj.get("scale", 1.0)) / tile
    u = g.mul(a, scale)
    v = g.mul(b, -scale)
    return g.node("ND_combine2_vector2", in1=u, in2=v)


def _image(g, rel, uv, four=False, space="srgb_texture", address="periodic"):
    return g.node("ND_image_color4" if four else "ND_image_color3", name="image",
                  colorspaces={"file": space}, file=rel, texcoord=uv, uaddressmode=address, vaddressmode=address)


def build_network(stage, material_prim, doc, gm, base_dir, mesh_file):
    """Write the MaterialX network of ground.materials entry `gm` under a material prim. Returns notes."""
    from pxr import UsdGeom, UsdShade
    notes = []
    layers = [doc["ground"]["layers"][lid] for lid in gm["palette"]]
    n = len(layers)
    if n > MAX_PALETTE:
        raise SystemExit(f"ground_materialx: {n} palette layers; at most {MAX_PALETTE} are supported")
    w = gm["weights"]
    if w["encoding"] != "vertex_top3" or not isinstance(w.get("indices"), list):
        raise SystemExit("ground_materialx: only the vertex_top3 encoding with three index primvars is supported")
    idx_names = [core.usd_attr_name(x) for x in w["indices"]]
    wt_name = core.usd_attr_name(w.get("weights", "_STJ_SURF_WEIGHTS"))
    mesh_pvs = set()
    for mesh, _faces in core.usd_material_meshes(stage, material_prim.GetName()):
        mesh_pvs.update(pv.GetPrimvarName() for pv in UsdGeom.PrimvarsAPI(mesh).GetPrimvars())

    def rel(uri):
        target = (Path(base_dir) / uri).resolve()
        try:
            return Path(os.path.relpath(target, Path(mesh_file).resolve().parent)).as_posix()
        except ValueError:                  # another drive: no relative path exists
            return target.as_posix()

    g = Graph(stage, f"{material_prim.GetPath()}/mtlx")
    UsdGeom.Scope.Define(stage, g.parent)

    # per-face indices and the three weights
    idx = [g.node("ND_convert_integer_float", **{"in": g.node("ND_geompropvalue_integer", geomprop=nm)}) for nm in idx_names]
    wsep = g.node("ND_separate2_vector2", **{"in": g.node("ND_geompropvalue_vector2", geomprop=wt_name)})
    wa, wb = wsep["outx"], wsep["outy"]
    wc = g.mx(g.sub(g.sub(1.0, wa), wb), 0.0)
    ws = [wa, wb, wc]

    # every palette layer: colour, height, constants
    cols, heights, means, contrasts, mean_rgb = [], [], [], [], []
    for j, layer in enumerate(layers):
        tex = gb.Texture(Path(base_dir) / layer["albedo"]["uri"])
        mean_rgb.append(tex.mean_rgb)
        means.append(tex.mean_alpha)
        contrasts.append(layer.get("height_contrast", 1.0))
        uv = _uv(g, layer, mesh_pvs, notes, f"layer '{gm['palette'][j]}'")
        if uv is None:
            cols.append(tuple(tex.mean_rgb))             # a constant: the layer's own average colour
            heights.append(tex.mean_alpha)
            continue
        alpha_h = layer["albedo"].get("height_in_alpha") or layer["albedo"].get("alpha") == "height"
        if alpha_h:
            img = _image(g, rel(layer["albedo"]["uri"]), uv, four=True)
            sep = g.node("ND_separate4_color4", **{"in": img})
            cols.append(g.node("ND_combine3_color3", in1=sep["outr"], in2=sep["outg"], in3=sep["outb"]))
            heights.append(sep["outa"])
        else:
            cols.append(_image(g, rel(layer["albedo"]["uri"]), uv))
            heights.append(tex.mean_alpha)

    blend = gm.get("blend") or {}
    method = blend.get("method", "height")
    slot_c = [g.switch(idx[k], cols, color=True) for k in range(3)]
    if method == "linear":
        tot = g.mx(g.add(g.add(ws[0], ws[1]), ws[2]), EPS)
        f = [g.div(ws[k], tot) for k in range(3)]
        colour = _mix3(g, slot_c, f)
    elif method == "height":
        infl, depth = blend.get("height_influence", 0.5), blend.get("depth", 0.2)
        sc = []
        for k in range(3):
            h = g.switch(idx[k], heights)
            m = g.switch(idx[k], means)
            c = g.switch(idx[k], contrasts)
            sc.append(g.add(ws[k], g.mul(g.sub(h, m), g.mul(c, infl))))
        top = g.mx(sc[0], g.mx(sc[1], sc[2]))
        thr = g.sub(top, depth)
        keep = [g.mx(g.sub(sc[k], thr), 0.0) for k in range(3)]
        tot = g.add(g.add(keep[0], keep[1]), keep[2])
        colour = _mix3(g, slot_c, [g.div(keep[k], tot) for k in range(3)])
    elif method == "mask":
        colour = _mask_blend(g, blend, layers, gm, idx, ws, cols, rel, mesh_pvs, notes)
    else:
        raise SystemExit(f"ground_materialx: unknown blend method '{method}'")

    # macro maps over a texcoord primvar, then the surface
    mean_c = [tuple(m) for m in mean_rgb]
    ref = _weighted_mean(g, idx, ws, mean_c)
    for i, mc in enumerate(gm.get("macro", [])):
        if mc["kind"] == "wetness":
            notes.append(f"macro[{i}]: a wetness map drives the engine, not the colour: left out")
            continue
        if "extent" in mc or mc.get("texcoord", "st") not in mesh_pvs:
            notes.append(f"macro[{i}]: {'a map over an extent is' if 'extent' in mc else 'primvar ' + repr(mc.get('texcoord', 'st')) + ' is missing; it is'} not written")
            continue
        enc = mc.get("encoding", "grey_centred")
        uv = g.node("ND_geompropvalue_vector2", geomprop=mc.get("texcoord", "st"))
        val = _image(g, rel(mc["uri"]), uv, space="srgb_texture" if enc == "colour" else "raw", address="clamp")
        if enc == "colour":
            ratio = g.node("ND_clamp_color3", **{"in": g.f("ND_divide_color3", val, g.f("ND_max_color3", ref, (EPS,) * 3)),
                                                  "low": (0.25,) * 3, "high": (4.0,) * 3})
            strength = mc.get("strength", 1.0)
            factor = g.cadd((1.0,) * 3, g.cmul(g.f("ND_subtract_color3", ratio, (1.0,) * 3), strength))
        elif enc == "multiply":
            factor = val
        else:
            factor = g.cmul(val, 2.0)
        colour = g.f("ND_multiply_color3", colour, factor)
        ref = g.f("ND_multiply_color3", ref, factor)

    surf = g.node("ND_open_pbr_surface_surfaceshader", name="surface", base_color=colour, specular_roughness=ROUGHNESS)
    UsdShade.Material(material_prim).CreateSurfaceOutput("mtlx").ConnectToSource(surf.shader.ConnectableAPI(), "out")
    return notes


def _mix3(g, colours, factors):
    total = g.cmul(colours[0], factors[0])
    for c, f in zip(colours[1:], factors[1:]):
        total = g.cadd(total, g.cmul(c, f))
    return total


def _weighted_mean(g, idx, ws, mean_rgb):
    """sum(w_k * mean colour of slot k) / sum(w_k): the layers' own average colour (ground_mean_colour)."""
    tot = g.mx(g.add(g.add(ws[0], ws[1]), ws[2]), EPS)
    acc = None
    for k in range(3):
        m = g.switch(idx[k], mean_rgb, color=True)
        term = g.cmul(m, g.div(ws[k], tot))
        acc = term if acc is None else g.cadd(acc, term)
    return acc


def _mask_blend(g, blend, layers, gm, idx, ws, cols, rel, mesh_pvs, notes):
    masks = blend.get("mask")
    masks = [masks] if isinstance(masks, dict) else (masks or [])
    n = len(layers)
    if len(masks) != n - 1:
        raise SystemExit(f"ground_materialx: the mask blend needs {n - 1} masks, the document has {len(masks)}")
    softness = blend.get("softness", core.MASK_DEFAULT_SOFTNESS)
    # one sample per palette layer after the first; the first layer's mask is never used
    mvals = [0.5]
    for j, mk in enumerate(masks):
        uv = _uv(g, mk, mesh_pvs, notes, f"mask {j}")
        if uv is None:
            mvals.append(0.5)
            continue
        ch = mk.get("channel", "r")
        if ch == "a":
            img = _image(g, rel(mk["uri"]), uv, four=True, space="raw")
            mvals.append(g.node("ND_separate4_color4", **{"in": img})["outa"])
        else:
            img = _image(g, rel(mk["uri"]), uv, space="raw")
            mvals.append(g.node("ND_separate3_color3", **{"in": img})["out" + ("r" if ch in ("r", "gray") else ch)])
    # order the three present layers by palette index (a 3-element sorting network, as ground_bake does)
    sl = [(idx[k], ws[k]) for k in range(3)]

    def cswap(a, b):
        lo_i, hi_i = g.f("ND_min_float", a[0], b[0]), g.f("ND_max_float", a[0], b[0])
        gt = lambda x, y: g.node("ND_ifgreater_float", value1=a[0], value2=b[0], in1=x, in2=y)  # noqa: E731
        return (lo_i, gt(b[1], a[1])), (hi_i, gt(a[1], b[1]))
    sl[0], sl[1] = cswap(sl[0], sl[1])
    sl[1], sl[2] = cswap(sl[1], sl[2])
    sl[0], sl[1] = cswap(sl[0], sl[1])
    c = [g.switch(sl[s][0], cols, color=True) for s in range(3)]
    run1 = g.mx(g.add(sl[0][1], sl[1][1]), EPS)
    run2 = g.mx(g.add(run1, sl[2][1]), EPS)
    shares = [None, g.div(sl[1][1], run1), g.div(sl[2][1], run2)]
    colour = c[0]
    for s in (1, 2):
        k = g.switch(sl[s][0], mvals)
        t = g.clamp(g.add(g.div(g.sub(shares[s], k), softness), 0.5), 0.0, 1.0)
        colour = g.node("ND_mix_color3", fg=c[s], bg=colour, mix=t)
    return colour


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file")
    ap.add_argument("-o", "--out", required=True, help="the mesh file to write, with the network added")
    ap.add_argument("--material", help="ground.materials material name (default: the first)")
    a = ap.parse_args(argv)
    from pxr import Sdf, UsdShade
    doc, chain = core.resolve(a.file)
    mats = (doc.get("ground") or {}).get("materials") or []
    if not mats:
        raise SystemExit("ground_materialx: the document has no ground.materials")
    gm = next((m for m in mats if m["material"] == a.material), None) if a.material else mats[0]
    if gm is None:
        raise SystemExit(f"ground_materialx: no ground material '{a.material}'")
    base_dir = chain[0].parent
    mesh = next(m for m in doc["geometry"]["meshes"] if m["id"] == gm["mesh_ref"])
    src = base_dir / mesh["uri"]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    Sdf.Layer.FindOrOpen(str(src)).Export(str(out))
    stage = core.usd_stage(out)
    prim = next((p for p in stage.Traverse() if p.IsA(UsdShade.Material) and p.GetName() == gm["material"]), None)
    if prim is None:
        raise SystemExit(f"ground_materialx: no material '{gm['material']}' in {src.name}")
    notes = build_network(stage, prim, doc, gm, base_dir, out)
    stage.GetRootLayer().Save()
    print(f"wrote {out}: MaterialX network on {prim.GetPath()}")
    for note in notes:
        print(f"  left out: {note}")


if __name__ == "__main__":
    main()
