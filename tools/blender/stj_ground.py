"""The layered ground (spec §8.7) as Blender shader nodes.

Blender's USD import reads only the preview-surface fallback of a material, so the layered ground of a stage looks
like one image. This builds the blend again as nodes on the ground material of the imported mesh: the same maths as
`stj_core.ground_blend` and `tools/ground_bake.py`, from the `ground` block, which stays the source of truth. The
nodes are a view; the export never reads them.

Supported: the `vertex_top3` encoding, the `height` and `linear` blends, the `world_xy`, `road` and texcoord
projections, and `grey_centred`, `multiply` and `colour` macro maps over a UV map. Left out (and reported): the
`mask` blend, macro maps over an extent, wetness maps, the normal/roughness/occlusion maps of the layers. A material
with something left out that changes the colour keeps its preview surface.

Blender only: run inside Blender (`import bpy`).
"""

import os
from pathlib import Path

import bpy

import stj_core as core

EPS = 1e-6
ROUGHNESS = 0.9
GRID = 220                      # node spacing in the editor


class Builder:
    """Creates nodes in one material, laid out in columns."""

    def __init__(self, tree):
        self.tree = tree
        self.n = 0

    def node(self, idname, **props):
        nd = self.tree.nodes.new(idname)
        for k, v in props.items():
            setattr(nd, k, v)
        self.n += 1
        nd.location = ((self.n % 12) * GRID, -(self.n // 12) * 260)
        return nd

    def link(self, out, inp):
        self.tree.links.new(out, inp)

    # values are either a float or an output socket
    def _in(self, nd, i, v):
        if isinstance(v, (int, float)):
            nd.inputs[i].default_value = float(v)
        else:
            self.link(v, nd.inputs[i])

    def math(self, op, a, b=None, c=None, clamp=False):
        nd = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b, c)):
            if v is not None:
                self._in(nd, i, v)
        return nd.outputs[0]

    def add(self, a, b):
        return self.math("ADD", a, b)

    def sub(self, a, b):
        return self.math("SUBTRACT", a, b)

    def mul(self, a, b):
        return self.math("MULTIPLY", a, b)

    def div(self, a, b):
        return self.math("DIVIDE", a, b)

    def mx(self, a, b):
        return self.math("MAXIMUM", a, b)

    def vec(self, op, a, b=None, scale=None):
        nd = self.node("ShaderNodeVectorMath", operation=op)
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (tuple, list)):
                nd.inputs[i].default_value = tuple(v)
            else:
                self.link(v, nd.inputs[i])
        if scale is not None:
            self._in(nd, 3, scale)
        return nd.outputs[0]

    def select(self, which, values):
        """values[which] for an integer-valued socket, as a sum of equals; a constant stays a constant."""
        if all(not hasattr(v, "node") for v in values) and len(set(values)) == 1:
            return values[0]
        total = None
        for j, v in enumerate(values):
            mask = self.math("COMPARE", which, float(j), 0.1)
            term = self.mul(mask, v) if not isinstance(v, (tuple, list)) else None
            total = term if total is None else self.add(total, term)
        return total

    def select_colour(self, which, colours):
        total = None
        for j, col in enumerate(colours):
            mask = self.math("COMPARE", which, float(j), 0.1)
            term = self.vec("SCALE", col, scale=mask)
            total = term if total is None else self.vec("ADD", total, term)
        return total


def _image(b, path, uv, colour=True, interpolation="Linear", extension="REPEAT"):
    img = bpy.data.images.load(str(path), check_existing=True)
    img.alpha_mode = "CHANNEL_PACKED"                       # the alpha is height data, not transparency
    img.colorspace_settings.name = "sRGB" if colour else "Non-Color"
    tex = b.node("ShaderNodeTexImage", image=img, interpolation=interpolation, extension=extension)
    b.link(uv, tex.inputs["Vector"])
    return tex


def _uv(b, layer, mesh_attrs, notes, what):
    """The texture coordinate of a layer: world x and y, the road's (t, s), or a UV map, over the tile length."""
    proj = layer.get("projection", "world_xy")
    tile = layer["tile"]
    if proj == "world_xy":
        pos = b.node("ShaderNodeNewGeometry").outputs["Position"]
        sep = b.node("ShaderNodeSeparateXYZ")
        b.link(pos, sep.inputs[0])
        a, c, scale = sep.outputs["X"], sep.outputs["Y"], 1.0 / tile
    else:
        name = "road_uv" if proj == "road" else proj["texcoord"]
        if name not in mesh_attrs:
            notes.append(f"{what}: the mesh has no '{name}' primvar")
            return None
        uvn = b.node("ShaderNodeUVMap", uv_map=name)
        sep = b.node("ShaderNodeSeparateXYZ")
        b.link(uvn.outputs["UV"], sep.inputs[0])
        a, c, scale = sep.outputs["X"], sep.outputs["Y"], (1.0 if proj == "road" else proj.get("scale", 1.0)) / tile
    comb = b.node("ShaderNodeCombineXYZ")
    b.link(b.mul(a, scale), comb.inputs["X"])
    b.link(b.mul(c, -scale), comb.inputs["Y"])     # image rows run up in Blender: minus, as the MaterialX network has it
    return comb.outputs[0]


def build_ground_material(mat, doc, gm, base_dir, mesh_attrs, interpolation="Linear"):
    """Rebuild material `mat` from `ground.materials` entry `gm`. Returns (notes, done); done is False when the
    preview surface was kept."""
    notes = []
    w = gm["weights"]
    if w.get("encoding") != "vertex_top3" or not isinstance(w.get("indices"), list):
        return ["only the vertex_top3 encoding with three index attributes is built"], False
    blend = gm.get("blend") or {}
    method = blend.get("method", "height")
    if method not in ("height", "linear"):
        return [f"the '{method}' blend is not built: the preview surface stays"], False
    ground = doc["ground"]
    layers = [ground["layers"][lid] for lid in gm["palette"]]
    idx_names = [core.usd_attr_name(x) for x in w["indices"]]
    wt_name = core.usd_attr_name(w.get("weights", "_STJ_SURF_WEIGHTS"))
    for name in idx_names + [wt_name]:
        if name not in mesh_attrs:
            return [f"the mesh has no '{name}' attribute: the preview surface stays"], False

    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    b = Builder(tree)
    base_dir = Path(base_dir)

    idx = []
    for nm in idx_names:
        at = b.node("ShaderNodeAttribute", attribute_name=nm, attribute_type="GEOMETRY")
        idx.append(at.outputs["Fac"])
    wuv = b.node("ShaderNodeUVMap", uv_map=wt_name)
    wsep = b.node("ShaderNodeSeparateXYZ")
    b.link(wuv.outputs["UV"], wsep.inputs[0])
    wa, wb = wsep.outputs["X"], wsep.outputs["Y"]
    wc = b.mx(b.sub(b.sub(1.0, wa), wb), 0.0)
    ws = [wa, wb, wc]

    cols, deltas, mean_rgb = [], [], []
    infl = blend.get("height_influence", 0.5)
    for j, layer in enumerate(layers):
        tex_ref = _load_stats(base_dir / layer["albedo"]["uri"])
        mean_rgb.append(tex_ref[0])
        uv = _uv(b, layer, mesh_attrs, notes, f"layer '{gm['palette'][j]}'")
        if uv is None:
            cols.append(tuple(tex_ref[0]))
            deltas.append(0.0)
            continue
        tex = _image(b, base_dir / layer["albedo"]["uri"], uv, interpolation=interpolation)
        cols.append(tex.outputs["Color"])
        alpha_h = layer["albedo"].get("height_in_alpha") or layer["albedo"].get("alpha") == "height"
        con = layer.get("height_contrast", 1.0)
        # (height - mean height) * contrast * influence: what the height blend adds to a layer's weight
        deltas.append(b.mul(b.sub(tex.outputs["Alpha"], tex_ref[1]), con * infl) if alpha_h else 0.0)

    cols_v = [c if hasattr(c, "node") else None for c in cols]
    const_cols = [c if not hasattr(c, "node") else (0.0, 0.0, 0.0) for c in cols]
    slot_c = []
    for k in range(3):
        parts = []
        for j in range(len(layers)):
            mask = b.math("COMPARE", idx[k], float(j), 0.1)
            src = cols_v[j] if cols_v[j] is not None else b.vec("ADD", const_cols[j], (0.0, 0.0, 0.0))
            parts.append(b.vec("SCALE", src, scale=mask))
        total = parts[0]
        for p in parts[1:]:
            total = b.vec("ADD", total, p)
        slot_c.append(total)

    if method == "linear":
        tot = b.mx(b.add(b.add(ws[0], ws[1]), ws[2]), EPS)
        shares = [b.div(ws[k], tot) for k in range(3)]
    else:
        depth = blend.get("depth", 0.2)
        sc = []
        for k in range(3):
            d = b.select(idx[k], deltas)
            sc.append(b.add(ws[k], d) if hasattr(d, "node") else b.add(ws[k], float(d)))
        top = b.mx(sc[0], b.mx(sc[1], sc[2]))
        thr = b.sub(top, depth)
        keep = [b.mx(b.sub(sc[k], thr), 0.0) for k in range(3)]
        tot = b.add(b.add(keep[0], keep[1]), keep[2])
        shares = [b.div(keep[k], tot) for k in range(3)]
    colour = None
    for k in range(3):
        term = b.vec("SCALE", slot_c[k], scale=shares[k])
        colour = term if colour is None else b.vec("ADD", colour, term)

    # macro maps over a UV map, then the surface (as tools/ground_materialx.py does)
    ref = None
    for i, mc in enumerate(gm.get("macro", [])):
        if mc["kind"] == "wetness":
            notes.append(f"macro[{i}]: a wetness map drives the engine, not the colour: left out")
            continue
        name = mc.get("texcoord", "st")
        if "extent" in mc or name not in mesh_attrs:
            notes.append(f"macro[{i}]: {'a map over an extent is' if 'extent' in mc else 'attribute ' + repr(name) + ' is missing; it is'} not built")
            continue
        enc = mc.get("encoding", "grey_centred")
        uvn = b.node("ShaderNodeUVMap", uv_map=name)
        tex = _image(b, base_dir / mc["uri"], uvn.outputs["UV"], colour=(enc == "colour"), interpolation=interpolation,
                     extension="EXTEND")
        if enc == "colour":
            if ref is None:
                ref = _weighted_mean(b, idx, ws, mean_rgb)
            ratio = b.vec("DIVIDE", tex.outputs["Color"], b.vec("MAXIMUM", ref, (EPS, EPS, EPS)))
            ratio = b.vec("MAXIMUM", ratio, (0.25, 0.25, 0.25))
            ratio = b.vec("MINIMUM", ratio, (4.0, 4.0, 4.0))
            strength = mc.get("strength", 1.0)
            factor = b.vec("ADD", (1.0, 1.0, 1.0), b.vec("SCALE", b.vec("SUBTRACT", ratio, (1.0, 1.0, 1.0)), scale=strength))
        elif enc == "multiply":
            factor = tex.outputs["Color"]
        else:
            factor = b.vec("SCALE", tex.outputs["Color"], scale=2.0)
        colour = b.vec("MULTIPLY", colour, factor)
        if ref is not None:
            ref = b.vec("MULTIPLY", ref, factor)

    bsdf = b.node("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = ROUGHNESS
    b.link(colour, bsdf.inputs["Base Color"])
    out = b.node("ShaderNodeOutputMaterial")
    b.link(bsdf.outputs["BSDF"], out.inputs["Surface"])
    mat["stj_ground_nodes"] = True
    return notes, True


def _weighted_mean(b, idx, ws, mean_rgb):
    tot = b.mx(b.add(b.add(ws[0], ws[1]), ws[2]), EPS)
    acc = None
    for k in range(3):
        parts = []
        for j, m in enumerate(mean_rgb):
            parts.append(b.vec("SCALE", b.vec("ADD", tuple(m), (0.0, 0.0, 0.0)), scale=b.math("COMPARE", idx[k], float(j), 0.1)))
        m_k = parts[0]
        for p in parts[1:]:
            m_k = b.vec("ADD", m_k, p)
        term = b.vec("SCALE", m_k, scale=b.div(ws[k], tot))
        acc = term if acc is None else b.vec("ADD", acc, term)
    return acc


_STATS = {}


def _load_stats(path):
    """(mean colour in linear light, mean alpha) of a PNG, with the same reader the reference tools use."""
    key = str(path)
    if key not in _STATS:
        import ground_bake as gb
        t = gb.Texture(Path(path))
        _STATS[key] = (tuple(t.mean_rgb), t.mean_alpha)
    return _STATS[key]


def build_ground(doc, base_dir, interpolation="Linear"):
    """Rebuild the ground materials of an imported document. Returns {material name: notes}; a material whose
    mesh or attributes are not in the file is skipped."""
    report = {}
    for gm in (doc.get("ground") or {}).get("materials") or []:
        mat = bpy.data.materials.get(gm["material"])
        if mat is None:
            report[gm["material"]] = ["no such material in the open file"]
            continue
        mesh_attrs = set()
        for ob in bpy.data.objects:
            if ob.type == "MESH" and any(s.material == mat for s in ob.material_slots):
                mesh_attrs.update(a.name for a in ob.data.attributes)
                mesh_attrs.update(u.name for u in ob.data.uv_layers)
        if not mesh_attrs:
            report[gm["material"]] = ["no mesh uses the material"]
            continue
        notes, done = build_ground_material(mat, doc, gm, base_dir, mesh_attrs, interpolation)
        report[gm["material"]] = notes + ([] if done else ["preview surface kept"])
    return report
