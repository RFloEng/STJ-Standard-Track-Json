"""A small evaluator for the MaterialX nodes tools/ground_materialx.py writes, reading the USD it produced.

It exists to check the generated network against the reference implementation (stj_core.ground_blend and
apply_macro): it does what the MaterialX standard library says each node does, with nearest-texel image
reads so that the comparison is exact. It is not a renderer. Image orientation follows USD: v = 0 is the
bottom row.
"""

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ground_bake as gb  # noqa: E402


class Evaluator:
    """Evaluates the MaterialX network on a material: Evaluator(material_prim, env).base_color()."""

    def __init__(self, material, env):
        from pxr import UsdShade
        self.UsdShade = UsdShade
        self.material = UsdShade.Material(material)
        self.env = env                      # geomprops {name: value}, "position": (x, y, z)
        self.cache = {}
        self.textures = {}

    # -- plumbing --
    def base_color(self):
        out = self.material.GetOutput("mtlx:surface")
        src = out.GetConnectedSource()
        return self.value(src[0].GetPrim(), src[1] if len(src) > 1 else "out", "base_color")

    def surface(self):
        """Every input of the surface shader that has a value: {base_color, specular_roughness, base_metalness, ...}."""
        src = self.material.GetOutput("mtlx:surface").GetConnectedSource()
        return self.output(src[0].GetPrim(), src[1] if len(src) > 1 else "out")

    def value(self, prim, out_name, input_name):
        """The value of input `input_name` of the shader at `prim`."""
        sh = self.UsdShade.Shader(prim)
        inp = sh.GetInput(input_name)
        if not inp:
            return None
        if inp.HasConnectedSource():
            src = inp.GetConnectedSource()
            return self.output(src[0].GetPrim(), src[1])
        return self.const(inp.Get())

    @staticmethod
    def const(v):
        try:
            return tuple(v) if hasattr(v, "__len__") and not isinstance(v, str) else v
        except TypeError:
            return v

    def output(self, prim, name):
        key = (str(prim.GetPath()), name)
        if key not in self.cache:
            self.cache[key] = self.node(prim, name)
        return self.cache[key]

    # -- nodes --
    def node(self, prim, out):
        sh = self.UsdShade.Shader(prim)
        nid = str(sh.GetIdAttr().Get())
        g = lambda n: self.value(prim, "out", n)  # noqa: E731
        base = nid[3:]
        if nid.startswith("ND_image_"):
            return self.image(prim, nid.endswith("color4"))
        if nid == "ND_position_vector3":
            return tuple(self.env["position"])
        if nid.startswith("ND_geompropvalue_"):
            v = self.env["geomprops"][g("geomprop")]
            return float(v) if nid.endswith("integer") or nid.endswith("float") else tuple(v)
        if nid == "ND_convert_integer_float":
            return float(g("in"))
        if nid.startswith("ND_separate"):
            v = g("in")
            names = {"separate2_vector2": "xy", "separate3_vector3": "xyz", "separate3_color3": "rgb", "separate4_color4": "rgba"}[base]
            return v[names.index(out[3:])]
        if nid in ("ND_combine2_vector2", "ND_combine3_color3"):
            return tuple(g(f"in{i}") for i in range(1, 4 if nid == "ND_combine3_color3" else 3))
        if nid.endswith("_float") and base[:-6] in ("add", "subtract", "multiply", "divide", "max", "min"):
            a, b = g("in1"), g("in2")
            return {"add": a + b, "subtract": a - b, "multiply": a * b, "divide": a / b if b else 0.0,
                    "max": max(a, b), "min": min(a, b)}[base[:-6]]
        if nid == "ND_clamp_float":
            return min(max(g("in"), g("low")), g("high"))
        if nid == "ND_ifgreater_float":
            return g("in1") if g("value1") > g("value2") else g("in2")
        if nid in ("ND_switch_float", "ND_switch_color3"):
            which = int(math.floor(g("which")))
            return g(f"in{min(max(which, 0), 9) + 1}")
        if nid.endswith("_color3") and base[:-7] in ("add", "subtract", "multiply", "divide", "max"):
            a, b = g("in1"), g("in2")
            f = {"add": lambda x, y: x + y, "subtract": lambda x, y: x - y, "multiply": lambda x, y: x * y,
                 "divide": lambda x, y: x / y if y else 0.0, "max": max}[base[:-7]]
            return tuple(f(x, y) for x, y in zip(a, b))
        if nid == "ND_multiply_color3FA":
            return tuple(x * g("in2") for x in g("in1"))
        if nid == "ND_clamp_color3":
            return tuple(min(max(x, lo), hi) for x, lo, hi in zip(g("in"), g("low"), g("high")))
        if nid in ("ND_mix_color3", "ND_mix_vector3"):
            m = g("mix")
            return tuple(b * (1.0 - m) + f * m for f, b in zip(g("fg"), g("bg")))
        if nid == "ND_mix_float":
            return g("bg") * (1.0 - g("mix")) + g("fg") * g("mix")
        if nid == "ND_normalmap_float":
            return g("in")                       # tangent space: the map's own vector, before the tangent frame
        if nid == "ND_open_pbr_surface_surfaceshader":
            keys = ("base_color", "specular_roughness", "base_metalness", "geometry_normal", "geometry_opacity",
                    "emission_color", "emission_luminance")
            return {k: g(k) for k in keys if g(k) is not None}
        raise NotImplementedError(nid)

    def image(self, prim, four):
        sh = self.UsdShade.Shader(prim)
        fattr = sh.GetInput("file")
        path = fattr.Get().resolvedPath or fattr.Get().path
        if not Path(path).is_absolute() or not Path(path).exists():
            path = str(Path(prim.GetStage().GetRootLayer().realPath).parent / fattr.Get().path)
        space = fattr.GetAttr().GetColorSpace()
        tex = self.textures.setdefault(path, gb.Texture(path))
        u, v = self.value(prim, "out", "texcoord")
        mode = sh.GetInput("uaddressmode").Get()
        img = tex.img
        if mode == "clamp":
            u, v = min(max(u, 0.0), 1.0), min(max(v, 0.0), 1.0)
            i = min(int(u * img.width), img.width - 1)
            j = min(int((1.0 - v) * img.height), img.height - 1)
        else:
            i = int((u % 1.0) * img.width) % img.width
            j = int(((1.0 - (v % 1.0)) % 1.0 * img.height)) % img.height
        k = (j * img.width + i) * img.channels
        px = img.data[k:k + img.channels]
        rgb = tuple((gb.srgb_to_linear(px[min(c, len(px) - 1)] * 255.0 / img.maxval) if space == "srgb_texture"
                     else px[min(c, len(px) - 1)] / img.maxval) for c in range(3))
        if not four:
            return rgb
        alpha = px[3] / img.maxval if img.channels == 4 else 1.0
        return (*rgb, alpha)
