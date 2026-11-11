"""
Material to MaterialX
=====================
Writes an ordinary material (spec §7.7, "Materials stay as the source") as a MaterialX network on a USD material, next to
its UsdPreviewSurface, so a converter does not have to flatten what UsdPreviewSurface cannot say: a colour tint, a
vertex-colour multiplier, a channel-packed roughness or metalness map, a gloss map, an occlusion map, a normal map, an
emissive map, an opacity map, and a blend of two layers by a vertex value or a map. Needs the pxr module (pip install usd-core).
The network is an OpenPBR surface on `outputs:mtlx:surface`; the UsdPreviewSurface stays the fallback every USD reader has.

A converter calls it with a description of the source material, in the source's own terms:

    import material_mtlx
    notes = material_mtlx.write_material(stage, "/m/materials/Wall", {
        "uv": {"primvar": "st", "scale": [2, 2]},
        "base_color": {"uri": "wall_d.png", "tint": [0.9, 0.9, 0.8], "vertex_colour": "displayColor"},
        "roughness": {"uri": "wall_orm.png", "channel": "g"},
        "metalness": {"uri": "wall_orm.png", "channel": "b"},
        "occlusion": {"uri": "wall_orm.png", "channel": "r"},
        "normal": {"uri": "wall_n.png", "scale": 1.0},
    })

and for two layers mixed by a weight (a vertex primvar, a map channel or a constant):

    {"layers": [ {...first layer...}, {...second layer...} ], "weight": {"primvar": "stj_mix"}}

The weight 0 shows the first layer and 1 the second. Each layer is a description like the one above (without `layers`). What
it writes: `base_color` (map or constant, times `tint`, times the `vertex_colour` primvar, times `occlusion`),
`roughness` (a channel of a map, `gloss` inverts it, or a `value`), `metalness`, `normal` (a tangent-space map through
`ND_normalmap_float`), `emissive` (map or `color`, with `luminance`), `opacity` (a channel or a `value`). A key that is
absent is left at the surface default. It returns notes for anything it could not write and says so.

The network is a derived view of the source description: keep that description (or the source engine's own data under
`x_<engine>` in the material's customData) as the source of truth. Texture paths are written as given, relative to the
USD file. The node names and inputs are checked against the MaterialX 1.39 standard library in tests/test_material_mtlx.py,
and the maths against tests/mtlx_eval.py; the network has not been rendered in a viewer (image orientation as in
tools/ground_materialx.py: v is the USD primvar's v).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ground_materialx as gm_tool  # noqa: E402

_F = "float"
# MaterialX standard library nodes this writer adds to those of ground_materialx: id -> (inputs, outputs)
EXTRA = {
    "ND_image_color3": gm_tool.NODES["ND_image_color3"],
    "ND_image_color4": gm_tool.NODES["ND_image_color4"],
    "ND_normalmap_float": ({"in": "vector3", "scale": _F}, {"out": "vector3"}),
    "ND_image_vector3": (gm_tool._IMG, {"out": "vector3"}),
    "ND_geompropvalue_color3": ({"geomprop": "string"}, {"out": "color3"}),
    "ND_geompropvalue_float": ({"geomprop": "string"}, {"out": _F}),
    "ND_mix_float": ({"fg": _F, "bg": _F, "mix": _F}, {"out": _F}),
    "ND_mix_vector3": ({"fg": "vector3", "bg": "vector3", "mix": _F}, {"out": "vector3"}),
    "ND_open_pbr_surface_surfaceshader": ({
        "base_color": "color3", "base_metalness": _F, "specular_roughness": _F, "geometry_normal": "vector3",
        "geometry_opacity": _F, "emission_color": "color3", "emission_luminance": _F}, {"out": "surfaceshader"}),
}
gm_tool.NODES.update(EXTRA)
SURFACE_INPUTS = EXTRA["ND_open_pbr_surface_surfaceshader"][0]
CHANNELS = {"r": "outr", "g": "outg", "b": "outb", "a": "outa"}
WHITE = (1.0, 1.0, 1.0)


class _Writer:
    def __init__(self, stage, parent):
        self.g = gm_tool.Graph(stage, parent)
        self.notes = []

    # -- inputs --
    def uv(self, uv):
        uv = uv or {}
        g = self.g
        sep = g.node("ND_separate2_vector2", **{"in": g.node("ND_geompropvalue_vector2", geomprop=uv.get("primvar", "st"))})
        su, sv = uv.get("scale", (1.0, 1.0))
        return g.node("ND_combine2_vector2", in1=g.mul(sep["outx"], float(su)), in2=g.mul(sep["outy"], float(sv)))

    def image(self, tex, uv, space, four=False):
        return self.g.node("ND_image_color4" if four else "ND_image_color3", name="image", colorspaces={"file": space},
                           file=tex["uri"], texcoord=uv, uaddressmode=tex.get("address", "periodic"),
                           vaddressmode=tex.get("address", "periodic"))

    def channel(self, tex, uv, default=0.0):
        """A single value from a map (`channel` r, g, b or a; grey when absent) or a constant `value`."""
        if "uri" not in tex:
            return float(tex.get("value", default))
        ch = tex.get("channel", "r")
        if ch == "a":
            return self.g.node("ND_separate4_color4", **{"in": self.image(tex, uv, "raw", four=True)})["outa"]
        if ch == "gray":
            ch = "r"
        return self.g.node("ND_separate3_color3", **{"in": self.image(tex, uv, "raw")})[CHANNELS[ch]]

    # -- one layer --
    def layer(self, spec, uv):
        """{base_color, specular_roughness, ...} of one layer description, as Refs or constants."""
        g, out = self.g, {}
        bc = spec.get("base_color")
        if bc is not None:
            colour = self.image(bc, uv, bc.get("space", "srgb_texture")) if "uri" in bc else tuple(bc.get("value", WHITE))
            if bc.get("tint"):
                colour = g.f("ND_multiply_color3", colour, tuple(bc["tint"]))
            if bc.get("vertex_colour"):
                colour = g.f("ND_multiply_color3", colour, g.node("ND_geompropvalue_color3", geomprop=bc["vertex_colour"]))
            out["base_color"] = colour
        occ = spec.get("occlusion")
        if occ is not None and "uri" in occ:
            ao = self.channel(occ, uv, 1.0)
            out["base_color"] = g.f("ND_multiply_color3", out.get("base_color", WHITE),
                                    g.node("ND_combine3_color3", in1=ao, in2=ao, in3=ao))
        for key, name in (("roughness", "specular_roughness"), ("metalness", "base_metalness")):
            tex = spec.get(key)
            if tex is None:
                continue
            v = self.channel(tex, uv, 0.0)
            if key == "roughness" and tex.get("gloss"):
                v = g.sub(1.0, v)
            out[name] = v
        nm = spec.get("normal")
        if nm is not None and "uri" in nm:
            n = g.node("ND_image_vector3", name="image", colorspaces={"file": "raw"}, file=nm["uri"], texcoord=uv,
                       uaddressmode="periodic", vaddressmode="periodic")
            out["geometry_normal"] = g.node("ND_normalmap_float", **{"in": n, "scale": float(nm.get("scale", 1.0))})
            if nm.get("y_down"):
                self.notes.append("normal: a Y-down (DirectX) normal map is written as it is; flip its green channel in the file")
        em = spec.get("emissive")
        if em is not None:
            out["emission_color"] = self.image(em, uv, "srgb_texture") if "uri" in em else tuple(em.get("color", WHITE))
            out["emission_luminance"] = float(em.get("luminance", 1.0))
        op = spec.get("opacity")
        if op is not None:
            out["geometry_opacity"] = self.channel(op, uv, 1.0)
        return out

    def mix(self, a, b, w):
        """Mix two layers' outputs by the weight w (0 = a, 1 = b)."""
        g, out = self.g, {}
        for key in set(a) | set(b):
            if key not in a or key not in b:
                self.notes.append(f"layers: '{key}' is on one layer only; the mix uses it for both")
            va, vb = a.get(key, b.get(key)), b.get(key, a.get(key))
            typ = SURFACE_INPUTS[key]
            if typ == "color3":
                out[key] = g.node("ND_mix_color3", fg=vb, bg=va, mix=w)
            elif typ == "vector3":
                out[key] = g.node("ND_mix_vector3", fg=vb, bg=va, mix=w)
            else:
                out[key] = g.node("ND_mix_float", fg=vb, bg=va, mix=w)
        return out

    def weight(self, spec, uv):
        if "primvar" in spec:
            return self.g.node("ND_geompropvalue_float", geomprop=spec["primvar"])
        return self.channel(spec, uv, 0.0)


def write_material(stage, material_path, spec):
    """Write `spec` (see the module docstring) as an OpenPBR MaterialX network on the material at `material_path` of an
    open pxr stage. Returns a list of notes."""
    from pxr import UsdShade
    mat = UsdShade.Material.Get(stage, material_path) or UsdShade.Material.Define(stage, material_path)
    w = _Writer(stage, f"{material_path}/mtlx")
    uv = w.uv(spec.get("uv"))
    if "layers" in spec:
        if len(spec["layers"]) != 2 or "weight" not in spec:
            w.notes.append("layers: two layers and a weight are needed; the first layer is written alone")
            ins = w.layer(spec["layers"][0], uv)
        else:
            ins = w.mix(w.layer(spec["layers"][0], uv), w.layer(spec["layers"][1], uv), w.weight(spec["weight"], uv))
    else:
        ins = w.layer(spec, uv)
    surf = w.g.node("ND_open_pbr_surface_surfaceshader", name="surface", **ins)
    mat.CreateSurfaceOutput("mtlx").ConnectToSource(surf.shader.ConnectableAPI(), "out")
    return w.notes
