"""Probe the v0.3 conventions of docs/blender_mapping.md in Blender 5.2.

    blender -b --factory-startup --python blend_probe_v03.py -- <out_dir>

A. The road profile (spec §7.1): a Geometry Nodes modifier turns a reference curve into a mesh with a
   profile curve (Curve to Mesh). Which way do the profile axes land in the world, which way does a
   positive curve tilt bank, and does the result agree with stj_core.profile_point?
B. Material inputs (spec §11.1, materials[]): does Blender's USD export write a node-group input or a
   custom property as an interface input (inputs:<name>) on the UsdShade.Material?
C. Per-instance variation (spec §8.2): do FLOAT and colour point attributes named stj_* come out as primvars,
   and with which types?
D. Names (spec §7.2): do STJ__<category>__<id> names and collections survive the USD export?

Writes <out_dir>/report_v03.json.
"""
import json
import math
import sys
import traceback
from pathlib import Path

import bpy
from pxr import Usd, UsdGeom, UsdShade

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import stj_core as core  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
out = Path(args[0])
out.mkdir(parents=True, exist_ok=True)
report = {"blender": bpy.app.version_string, "usd": ".".join(map(str, Usd.GetVersion()))}


def probe(name, fn):
    try:
        report[name] = fn()
    except Exception as e:  # noqa: BLE001
        report[name] = f"FAILED: {type(e).__name__}: {e}"
        traceback.print_exc()


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)


def r3(v):
    return [round(c, 4) for c in v]


# ── A. the road profile ──────────────────────────────────────────────────────
def make_curve(name, points, tilt=0.0):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("POLY")
    sp.points.add(len(points) - 1)
    for p, xyz in zip(sp.points, points):
        p.co = (*xyz, 1.0)
        p.tilt = tilt
    ob = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def road_modifier(road, profile):
    ng = bpy.data.node_groups.new("STJ_Road", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gi, go = ng.nodes.new("NodeGroupInput"), ng.nodes.new("NodeGroupOutput")
    c2m, oi = ng.nodes.new("GeometryNodeCurveToMesh"), ng.nodes.new("GeometryNodeObjectInfo")
    oi.inputs["Object"].default_value = profile
    oi.transform_space = "ORIGINAL"
    ng.links.new(gi.outputs[0], c2m.inputs["Curve"])
    ng.links.new(oi.outputs["Geometry"], c2m.inputs["Profile Curve"])
    ng.links.new(c2m.outputs["Mesh"], go.inputs[0])
    mod = road.modifiers.new("STJ_Road_main", "NODES")
    mod.node_group = ng


def evaluated_ring(road, x_at=0.0):
    """Vertices of the evaluated mesh at the cross-section nearest x_at, ordered by profile point."""
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(road.evaluated_get(dg))
    ring = [tuple(v.co) for v in me.vertices if abs(v.co.x - x_at) < 0.2]
    bpy.data.meshes.remove(me)
    return sorted(ring, key=lambda p: p[1])


def road_profile():
    clear()
    road = make_curve("road", [(0, 0, 0), (10, 0, 0), (20, 0, 0)])
    # profile in its own object space: three points drawn as (x, y) = (t, dz)
    profile = make_curve("profile", [(-4, 0, 0), (0, 0.1, 0), (4, 0, 0)])
    road_modifier(road, profile)
    res = {}
    flat = evaluated_ring(road)
    res["flat_ring_xyz"] = [r3(p) for p in flat]
    # where do the profile's axes land? x = -4 and +4 give the ends; y = +0.1 gives the middle point's height
    res["profile_x_lands_on"] = "world +Y (left)" if flat and flat[-1][1] > 3 else "other"
    mid = [p for p in flat if abs(p[1]) < 0.5]
    res["profile_y_lands_on"] = "world +Z (up)" if mid and mid[0][2] > 0 else "world -Z (down)"
    flipped = bool(mid and mid[0][2] < 0)
    res["so_the_profile_must_be_drawn_with"] = "y = -dz" if flipped else "y = dz"
    # rebuild the profile the way the convention says, then bank the road by +0.1 rad (tilt)
    sign = -1.0 if flipped else 1.0
    bpy.data.objects.remove(profile)
    profile = make_curve("profile", [(-4, 0, 0), (0, sign * 0.1, 0), (4, 0, 0)])
    road.modifiers[0].node_group.nodes["Object Info"].inputs["Object"].default_value = profile
    for p in road.data.splines[0].points:
        p.tilt = 0.1
    banked = evaluated_ring(road)
    res["banked_ring_xyz"] = [r3(p) for p in banked]
    if len(banked) >= 2:
        res["positive_tilt_raises"] = "left" if banked[-1][2] > banked[0][2] else "right"
    # what STJ computes for the same template (t, dz) and a positive bank of 0.1
    cl = {"points": [[0, 0, 0], [20, 0, 0]],
          "cross_section": {"templates": {"a": {"points": [{"t": -4, "dz": 0}, {"t": 0, "dz": 0.1}, {"t": 4, "dz": 0}]}},
                            "sections": [{"s_start": 0, "s_end": 20, "template": "a"}], "bank": [[0, 0.1]]}}
    exp = [core.profile_point(cl, 0, t) for t in (-4.0, 0.0, 4.0)]
    res["stj_expected_lateral_height"] = [r3(e) for e in exp]
    if len(banked) == 3:
        res["agrees_with_stj_profile_point"] = all(abs(b[1] - e[0]) < 0.01 and abs(b[2] - e[1]) < 0.01
                                                    for b, e in zip(banked, exp))
    return res


# ── B. material inputs ───────────────────────────────────────────────────────
def material_inputs():
    clear()
    me = bpy.data.meshes.new("hut")
    me.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    ob = bpy.data.objects.new("hut", me)
    bpy.context.scene.collection.objects.link(ob)
    mat = bpy.data.materials.new("Hut_windows")
    mat["emissive_scale"] = 1.0                          # a custom property on the material
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    grp = bpy.data.node_groups.new("Glow", "ShaderNodeTree")
    grp.interface.new_socket("emissive_scale", in_out="INPUT", socket_type="NodeSocketFloat")
    grp.interface.new_socket("Emission", in_out="OUTPUT", socket_type="NodeSocketFloat")
    gi, go = grp.nodes.new("NodeGroupInput"), grp.nodes.new("NodeGroupOutput")
    grp.links.new(gi.outputs[0], go.inputs[0])
    node = nt.nodes.new("ShaderNodeGroup")
    node.node_tree = grp
    node.inputs["emissive_scale"].default_value = 2.5
    nt.links.new(node.outputs["Emission"], bsdf.inputs["Emission Strength"])
    me.materials.append(mat)
    path = out / "material_inputs.usda"
    bpy.ops.wm.usd_export(filepath=str(path), export_materials=True)
    st = Usd.Stage.Open(str(path))
    res = {"materials": {}}
    for p in st.Traverse():
        if p.IsA(UsdShade.Material):
            m = UsdShade.Material(p)
            res["materials"][p.GetName()] = {
                "interface_inputs": sorted(i.GetBaseName() for i in m.GetInputs()),
                "userProperties": sorted(a.GetName() for a in p.GetAttributes() if "userProperties" in a.GetName()),
                "shader_inputs": sorted({i.GetBaseName() for c in p.GetChildren() if c.IsA(UsdShade.Shader)
                                         for i in UsdShade.Shader(c).GetInputs()})[:40],
            }
    return res


# ── C. point attributes as primvars ──────────────────────────────────────────
def point_attributes():
    clear()
    me = bpy.data.meshes.new("trees")
    me.from_pydata([(0, 0, 0), (5, 0, 0), (10, 0, 0)], [], [])
    me.attributes.new("stj_age", "FLOAT", "POINT")
    me.attributes.new("stj_phase", "FLOAT", "POINT")
    me.attributes.new("stj_tint", "FLOAT_COLOR", "POINT")
    me.attributes.new("stj_tint_b", "FLOAT_VECTOR", "POINT")
    for i in range(3):
        me.attributes["stj_age"].data[i].value = 0.1 + 0.4 * i
        me.attributes["stj_phase"].data[i].value = 0.25 * i
        me.attributes["stj_tint"].data[i].color = (1.0, 0.9 - 0.1 * i, 0.8, 1.0)
        me.attributes["stj_tint_b"].data[i].vector = (1.0, 0.9 - 0.1 * i, 0.8)
    ob = bpy.data.objects.new("trees", me)
    bpy.context.scene.collection.objects.link(ob)
    path = out / "point_attributes.usda"
    bpy.ops.wm.usd_export(filepath=str(path))
    st = Usd.Stage.Open(str(path))
    res = {"prims": {}}
    for p in st.Traverse():
        pv = UsdGeom.PrimvarsAPI(p).GetPrimvars()
        if pv:
            res["prims"][str(p.GetPath())] = {v.GetPrimvarName(): [str(v.GetTypeName()), str(v.GetInterpolation())] for v in pv}
    return res


# ── D. names and collections ─────────────────────────────────────────────────
def names():
    clear()
    col = bpy.data.collections.new("STJ__structure__viaduct_1")
    col["stj"] = {"kind": "bridge", "clearance": 5.2}
    bpy.context.scene.collection.children.link(col)
    me = bpy.data.meshes.new("deck")
    me.from_pydata([(0, 0, 0), (10, 0, 0), (10, 8, 0), (0, 8, 0)], [], [(0, 1, 2, 3)])
    ob = bpy.data.objects.new("STJ__structure__viaduct_1__deck", me)
    col.objects.link(ob)
    em = bpy.data.objects.new("STJ::timing::start", None)
    bpy.context.scene.collection.objects.link(em)
    path = out / "names.usda"
    bpy.ops.wm.usd_export(filepath=str(path))
    st = Usd.Stage.Open(str(path))
    return {"prim_paths": [str(p.GetPath()) for p in st.Traverse()]}


probe("A_road_profile", road_profile)
probe("B_material_inputs", material_inputs)
probe("C_point_attributes", point_attributes)
probe("D_names", names)
(out / "report_v03.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
