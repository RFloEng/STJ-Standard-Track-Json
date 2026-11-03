"""
Ground bake
===========
Bakes a layered ground material (spec §8.7) into an image in one of the mesh's UV primvars, with
the reference blend. It shows what the recipe looks like without any engine, and is the "bake"
fallback for engines that cannot rebuild the blend. Needs the pxr module: pip install usd-core.

    python tools/ground_bake.py <track.usda | doc.stj.json> -o out.png [--material NAME] [--uv st] [--size 1024x128]

Supports the vertex_top3 encoding (one int3 primvar or three int primvars), the world_xy, road and
texcoord projections, and grey_centred or multiply macro maps on the bake's own UV primvar.
Standard library plus pxr; slow on big meshes by design.
"""

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stj_core as core  # noqa: E402


def srgb_to_linear(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c):
    c = min(max(c, 0.0), 1.0)
    return round(255 * (12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055))


class Texture:
    def __init__(self, path):
        self.img = core.read_png(path)
        img = self.img
        self.mean_alpha = (sum(img.data[3::4]) / (img.width * img.height) / img.maxval) if img.channels == 4 else 0.5

    def sample(self, u, v, data=False):
        """Nearest texel with wrapping: ((r, g, b) linear, alpha 0..1). data=True reads the values as they are."""
        img = self.img
        i = int((u % 1.0) * img.width) % img.width
        j = int((v % 1.0) * img.height) % img.height
        k = (j * img.width + i) * img.channels
        px = img.data[k:k + img.channels]
        rgb = tuple((px[min(c, len(px) - 1)] / img.maxval) if data else srgb_to_linear(px[min(c, len(px) - 1)] * 255.0 / img.maxval)
                    for c in range(3))
        alpha = px[3] / img.maxval if img.channels == 4 else 0.5
        return rgb, alpha


class Primvar:
    """A primvar's values looked up per face, face corner or vertex, by its interpolation."""

    def __init__(self, mesh, name):
        pv = core.usd_primvar(mesh, name)
        if pv is None:
            raise SystemExit(f"primvar '{name}' missing on {mesh.GetPath()}")
        self.interp, self.values = pv

    def at(self, face, corner, vertex):
        if self.interp == "uniform":
            return self.values[face]
        if self.interp == "faceVarying":
            return self.values[corner]
        if self.interp in ("vertex", "varying"):
            return self.values[vertex]
        return self.values[0]


def layer_lookup(mesh, indices):
    """A function face -> (i0, i1, i2) from one int3 primvar or three int primvars."""
    if isinstance(indices, list):
        parts = [Primvar(mesh, core.usd_attr_name(n)) for n in indices]
        return lambda f: tuple(int(p.values[f][0]) for p in parts)
    pv = Primvar(mesh, core.usd_attr_name(indices))
    return lambda f: tuple(int(x) for x in pv.values[f])


def bake(doc, base_dir, index=0, width=1024, height=128, uv="st"):
    """Rows of (r, g, b) bytes for ground.materials[index], drawn in the UV primvar `uv`."""
    base_dir = Path(base_dir)
    ground = doc["ground"]
    gm = ground["materials"][index]
    w = gm["weights"]
    if w["encoding"] != "vertex_top3":
        raise SystemExit("ground_bake: only the vertex_top3 encoding is implemented")
    mesh_entry = next(m for m in doc["geometry"]["meshes"] if m["id"] == gm["mesh_ref"])
    stage = core.usd_stage(base_dir / mesh_entry["uri"])
    ref = core.reference_line(doc)
    layers = [ground["layers"][lid] for lid in gm["palette"]]
    tex = [Texture(base_dir / l["albedo"]["uri"]) for l in layers]
    blend = gm.get("blend") or {}
    macros = [(Texture(base_dir / m["uri"]), m.get("encoding", "grey_centred")) for m in gm.get("macro", [])
              if m.get("texcoord", uv) == uv and "extent" not in m]
    out = [[(0, 0, 0)] * width for _ in range(height)]
    for mesh, faces in core.usd_material_meshes(stage, gm["material"]):
        pts = mesh.GetAttribute("points").Get()
        counts = list(mesh.GetAttribute("faceVertexCounts").Get())
        idx = list(mesh.GetAttribute("faceVertexIndices").Get())
        bake_uv = Primvar(mesh, uv)
        lay_of = layer_lookup(mesh, w.get("indices", "_STJ_SURF_LAYERS"))
        wts = Primvar(mesh, core.usd_attr_name(w.get("weights", "_STJ_SURF_WEIGHTS")))
        uvsets = {l["projection"]["texcoord"]: Primvar(mesh, l["projection"]["texcoord"])
                  for l in layers if isinstance(l.get("projection"), dict)}
        needs_st = ref is not None and any(l.get("projection") == "road" for l in layers)
        st_cache = {}
        wanted = None if faces is None else set(faces)
        corner = 0
        for f, n in enumerate(counts):
            first = corner
            corner += n
            if wanted is not None and f not in wanted:
                continue
            lay = lay_of(f)
            ring = [(first + k, idx[first + k]) for k in range(n)]
            for k in range(1, n - 1):
                tri = [ring[0], ring[k], ring[k + 1]]
                _raster(out, width, height, tri, f, pts, bake_uv, wts, uvsets, layers, tex, lay, blend, macros,
                        ref if needs_st else None, st_cache)
    return out


def _raster(out, width, height, tri, f, pts, bake_uv, wts, uvsets, layers, tex, lay, blend, macros, ref, st_cache):
    uvs = [bake_uv.at(f, c, v) for c, v in tri]
    pix = [(u[0] * (width - 1), (1.0 - u[1]) * (height - 1)) for u in uvs]       # USD v runs up, images down
    (x0, y0), (x1, y1), (x2, y2) = pix
    den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if abs(den) < 1e-12:
        return
    wv = [wts.at(f, c, v) for c, v in tri]
    pos = [pts[v] for _c, v in tri]
    if ref is not None:
        for _c, v in tri:
            if v not in st_cache:
                st_cache[v] = ref.project(pts[v][0], pts[v][1])
    for py in range(max(0, int(min(y0, y1, y2))), min(height - 1, int(math.ceil(max(y0, y1, y2)))) + 1):
        for px in range(max(0, int(min(x0, x1, x2))), min(width - 1, int(math.ceil(max(x0, x1, x2)))) + 1):
            l0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / den
            l1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / den
            l2 = 1.0 - l0 - l1
            if min(l0, l1, l2) < -1e-6:
                continue
            bc = (l0, l1, l2)
            wa = sum(b * q[0] for b, q in zip(bc, wv))
            wb = sum(b * q[1] for b, q in zip(bc, wv))
            weights = [wa, wb, max(0.0, 1.0 - wa - wb)]
            x = sum(b * p[0] for b, p in zip(bc, pos))
            y = sum(b * p[1] for b, p in zip(bc, pos))
            cols, hts, means, cons = [], [], [], []
            for li in lay:
                layer = layers[li]
                proj = layer.get("projection", "world_xy")
                if proj == "world_xy":
                    u, v = x / layer["tile"], y / layer["tile"]
                elif proj == "road":
                    s = sum(b * st_cache[vv][0] for b, (_c, vv) in zip(bc, tri))
                    t = sum(b * st_cache[vv][1] for b, (_c, vv) in zip(bc, tri))
                    u, v = t / layer["tile"], s / layer["tile"]
                else:
                    q = uvsets[proj["texcoord"]]
                    sc = proj.get("scale", 1.0) / layer["tile"]
                    u = sc * sum(b * q.at(f, c, vv)[0] for b, (c, vv) in zip(bc, tri))
                    v = sc * sum(b * q.at(f, c, vv)[1] for b, (c, vv) in zip(bc, tri))
                rgb, h = tex[li].sample(u, v)
                cols.append(rgb)
                hts.append(h if layer["albedo"].get("height_in_alpha") else tex[li].mean_alpha)
                means.append(tex[li].mean_alpha)
                cons.append(layer.get("height_contrast", 1.0))
            fb = core.ground_blend(weights, hts, means, cons, blend.get("method", "height"),
                                   blend.get("height_influence", 0.5), blend.get("depth", 0.2))
            colour = tuple(sum(fi * c[ch] for fi, c in zip(fb, cols)) for ch in range(3))
            mu, mv = px / (width - 1), 1.0 - py / (height - 1)
            # macro maps are linear data (0.5 = unchanged for grey_centred)
            colour = core.apply_macro(colour, [(m.sample(mu, 1.0 - mv, data=True)[0], enc) for m, enc in macros])
            out[py][px] = tuple(linear_to_srgb(c) for c in colour)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--material", help="ground.materials material name (default: the first)")
    ap.add_argument("--uv", default="st", help="UV primvar to bake into (default st)")
    ap.add_argument("--size", default="1024x128")
    a = ap.parse_args(argv)
    doc, chain = core.resolve(a.file)
    mats = doc["ground"]["materials"]
    index = next(i for i, m in enumerate(mats) if m["material"] == a.material) if a.material else 0
    w, h = (int(v) for v in a.size.lower().split("x"))
    rows = bake(doc, chain[0].parent, index, w, h, a.uv)
    core.write_png(a.out, w, h, [c for row in rows for px in row for c in px], 3)
    print(f"baked {mats[index]['material']} -> {a.out} ({w} x {h})")


if __name__ == "__main__":
    main()
