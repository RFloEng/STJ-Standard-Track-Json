"""Runs inside Blender (tests/test_blender_ground.py starts it): builds the layered ground nodes for a document,
renders the ground from above with the colour on an Emission shader, and compares pixels with the reference maths
(stj_core.ground_blend and the layer textures, as tools/ground_bake.py reads them). Prints one JSON line.

    blender -b --factory-startup --python tests/blender_ground_check.py -- <doc.usda|json> <out.png> [window_m] [size] [patch_json]
"""
import json
import math
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "blender"))
import ground_bake as gb  # noqa: E402
import stj_blender  # noqa: E402
import stj_core as core  # noqa: E402
import stj_ground  # noqa: E402
import stj_profile as profile  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
doc_path, out_png = Path(argv[0]), argv[1]
window = float(argv[2]) if len(argv) > 2 else 40.0
size = int(argv[3]) if len(argv) > 3 else 200
patch = json.loads(argv[4]) if len(argv) > 4 else {}          # a merge patch for ground.materials[0]

doc = core.load_document(doc_path)
if patch:
    doc["ground"]["materials"][0] = core.merge_patch(doc["ground"]["materials"][0], patch)
base_dir = doc_path.resolve().parent
stj_blender.build_scene(profile.scene_from_document(doc, base_dir))
report = stj_ground.build_ground(doc, base_dir, interpolation="Closest")
gm = doc["ground"]["materials"][0]
mat = bpy.data.materials[gm["material"]]
built = bool(mat.get("stj_ground_nodes"))
result = {"built": built, "notes": report.get(gm["material"], [])}
if not built:
    print("RESULT " + json.dumps(result))
    sys.exit(0)

# the colour on an Emission shader, so the render shows the colour and no lighting
tree = mat.node_tree
bsdf = next(n for n in tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
out = next(n for n in tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial")
emi = tree.nodes.new("ShaderNodeEmission")
tree.links.new(bsdf.inputs["Base Color"].links[0].from_socket, emi.inputs["Color"])
tree.links.new(emi.outputs[0], out.inputs["Surface"])

ob = next(o for o in bpy.data.objects if o.type == "MESH" and any(s.material == mat for s in o.material_slots))
mesh = ob.data
for other in bpy.data.objects:
    if other is not ob and other.type in ('MESH', 'LIGHT'):
        other.hide_render = True                      # only the ground in the picture
M = ob.matrix_world
pts = [tuple(M @ v.co) for v in mesh.vertices]
loops = [lp.vertex_index for lp in mesh.loops]
starts = [p.loop_start for p in mesh.polygons]
counts = [p.loop_total for p in mesh.polygons]
w_name = core.usd_attr_name(gm["weights"].get("weights", "_STJ_SURF_WEIGHTS"))
idx_names = [core.usd_attr_name(x) for x in gm["weights"]["indices"]]
wuv = mesh.uv_layers[w_name].data
ruv = mesh.uv_layers["road_uv"].data if "road_uv" in mesh.uv_layers else None
faces_idx = [[int(mesh.attributes[n].data[f].value) for n in idx_names] for f in range(len(starts))]

# the centre of the window: a point on the mesh, a third of the way along
xs = [p[0] for p in pts]
ys = [p[1] for p in pts]
cx, cy = (min(xs) + max(xs)) / 2.0, min(ys) + (max(ys) - min(ys)) / 3.0

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
cam.data.type = "ORTHO"
cam.data.ortho_scale = window
cam.location = (cx, cy, max(p[2] for p in pts) + 50.0)
bpy.context.scene.collection.objects.link(cam)
bpy.context.scene.camera = cam
sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = 1
sc.cycles.use_denoising = False
sc.cycles.filter_width = 0.01
sc.render.resolution_x = sc.render.resolution_y = size
sc.render.resolution_percentage = 100
sc.view_settings.view_transform = "Standard"
sc.view_settings.look = "None"
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_depth = "16"
sc.render.filepath = out_png
sc.world = bpy.data.worlds.new("black")
sc.world.use_nodes = False
sc.world.color = (0, 0, 0)
bpy.ops.render.render(write_still=True)
img = bpy.data.images.load(out_png)
img.colorspace_settings.name = "Non-Color"
px = list(img.pixels)

# reference
ground = doc["ground"]
layers = [ground["layers"][lid] for lid in gm["palette"]]
def ref_uri(uri):
    """The reference reads PNG only (Blender has no Pillow): a DDS layer texture has its PNG master beside it."""
    return str(Path(uri).with_suffix(".png")) if uri.lower().endswith(".dds") else uri


tex = [gb.Texture(base_dir / ref_uri(l["albedo"]["uri"])) for l in layers]
blend = gm.get("blend") or {}
macros = [(gb.Texture(base_dir / m["uri"]), m.get("encoding", "grey_centred"), m.get("strength", 1.0), m.get("texcoord", "st"))
          for m in gm.get("macro", []) if "extent" not in m and m["kind"] != "wetness"]
masks_ = blend.get("mask") if blend.get("method") == "mask" else None
masks_ = [masks_] if isinstance(masks_, dict) else (masks_ or [])
mask_tex = [(gb.Texture(base_dir / mk["uri"]), mk) for mk in masks_]


def locate(x, y):
    """(face, corner triple, barycentric) of the point, fan triangulation from the first corner."""
    for f in range(len(starts)):
        c0, n = starts[f], counts[f]
        for k in range(1, n - 1):
            tri = (c0, c0 + k, c0 + k + 1)
            a, b, c = (pts[loops[t]] for t in tri)
            den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(den) < 1e-12:
                continue
            l0 = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / den
            l1 = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / den
            l2 = 1.0 - l0 - l1
            if min(l0, l1, l2) >= -1e-9:
                return f, tri, (l0, l1, l2)
    return None


def linear_to_srgb(c):
    c = min(max(c, 0.0), 1.0)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


errs, worst = [], (0.0, None)
step = max(1, size // 24)
for j in range(step // 2, size, step):
    for i in range(step // 2, size, step):
        x = cx + (i + 0.5) / size * window - window / 2.0
        y = cy + window / 2.0 - (j + 0.5) / size * window          # image row 0 is the top
        hit = locate(x, y)
        if hit is None:
            continue
        f, tri, bc = hit
        wa = sum(b * wuv[t].uv[0] for b, t in zip(bc, tri))
        wb = sum(b * wuv[t].uv[1] for b, t in zip(bc, tri))
        weights = [wa, wb, max(0.0, 1.0 - wa - wb)]
        lay = faces_idx[f]
        cols, hts, means, cons = [], [], [], []
        for li in lay:
            layer = layers[li]
            proj = layer.get("projection", "world_xy")
            if proj == "world_xy":
                u, v = x / layer["tile"], y / layer["tile"]
            else:
                q = ruv if proj == "road" else mesh.uv_layers[proj["texcoord"]].data
                scale = (1.0 if proj == "road" else proj.get("scale", 1.0)) / layer["tile"]
                u = scale * sum(b * q[t].uv[0] for b, t in zip(bc, tri))
                v = scale * sum(b * q[t].uv[1] for b, t in zip(bc, tri))
                if proj == "road":                                   # the reference's (u, v) is (t, s)
                    pass
            rgb, h = tex[li].sample(u, v)
            cols.append(rgb)
            hts.append(h if layer["albedo"].get("height_in_alpha") or layer["albedo"].get("alpha") == "height" else tex[li].mean_alpha)
            means.append(tex[li].mean_alpha)
            cons.append(layer.get("height_contrast", 1.0))
        if blend.get("method") == "mask":
            kvals = []
            for mtex, mk in mask_tex:
                if mk.get("projection", "world_xy") == "road":
                    mu_ = sum(b * ruv[t].uv[0] for b, t in zip(bc, tri)) / mk["tile"]
                    mv_ = sum(b * ruv[t].uv[1] for b, t in zip(bc, tri)) / mk["tile"]
                else:
                    mu_, mv_ = x / mk["tile"], y / mk["tile"]
                mrgb, malpha = mtex.sample(mu_, mv_, data=True)
                ch = mk.get("channel", "r")
                kvals.append(malpha if ch == "a" else mrgb[{"r": 0, "g": 1, "b": 2, "gray": 0}[ch]])
            order = sorted(range(len(lay)), key=lambda m: lay[m])
            part = core.ground_blend([weights[m] for m in order], [hts[m] for m in order], [means[m] for m in order],
                                     [cons[m] for m in order], "mask", masks=[kvals[lay[m] - 1] for m in order[1:]],
                                     softness=blend.get("softness", core.MASK_DEFAULT_SOFTNESS))
            fb = [0.0] * len(lay)
            for m, share in zip(order, part):
                fb[m] += share
        else:
            fb = core.ground_blend(weights, hts, means, cons, blend.get("method", "height"),
                                   blend.get("height_influence", 0.5), blend.get("depth", 0.2))
        colour = tuple(sum(fi * c[ch] for fi, c in zip(fb, cols)) for ch in range(3))
        if macros:
            mean_base = core.ground_mean_colour(weights, [tex[li].mean_rgb for li in lay]) if any(
                m[1] == "colour" for m in macros) else None
            vals = []
            for mtex, enc, st, name in macros:
                q = mesh.uv_layers[name].data
                mu = sum(b * q[t].uv[0] for b, t in zip(bc, tri))
                mv = sum(b * q[t].uv[1] for b, t in zip(bc, tri))
                vals.append((mtex.sample(mu, 1.0 - mv, data=enc != "colour")[0], enc, st))
            colour = core.apply_macro(colour, vals, mean_base)
        want = [linear_to_srgb(c) for c in colour]       
        want_lin = [min(max(c, 0.0), 1.0) for c in colour]
        k = ((size - 1 - j) * size + i) * 4                 # Blender image rows run up
        got = px[k:k + 3]
        e = max(abs(a - b) for a, b in zip(got, want))   # the render is sRGB encoded (Standard view)
        if e > 0.02 and len(errs) < 400:
            print("BAD", round(x, 1), round(y, 1), [round(c, 3) for c in got], [round(c, 3) for c in want], lay, [round(c, 2) for c in weights])
        errs.append(e)
        if e > worst[0]:
            worst = (e, {"x": round(x, 2), "y": round(y, 2), "got": [round(c, 3) for c in got], "want": [round(c, 3) for c in want]})
result.update({"samples": len(errs), "mean_err": round(sum(errs) / max(1, len(errs)), 4),
               "max_err": round(max(errs or [0.0]), 4), "worst": worst[1],
               "within_0_02": round(sum(1 for e in errs if e < 0.02) / max(1, len(errs)), 3)})
print("RESULT " + json.dumps(result))
