"""Probe OpenUSD as a rich container for STJ, from Blender 5.2 (which bundles OpenUSD and its pxr module).

    blender -b --factory-startup --python usd_probe.py -- <out_dir> <any.wav>

A. Builds a scene with what STJ needs, exports it with Blender's USD exporter (.usda) and inspects
   the result with pxr.
B. Writes what Blender does not export directly with pxr (variant sets, UsdPhysics, SpatialAudio,
   per-face primvars, STJ data in layer metadata) and checks what Blender's importer reads back.

Writes <out_dir>/report_usd.json.
"""
import json
import math
import sys
import traceback
from pathlib import Path

import bpy
from pxr import Sdf, Usd, UsdGeom, UsdMedia, UsdPhysics, UsdShade, Vt

args = sys.argv[sys.argv.index("--") + 1:]
out = Path(args[0])
wav = Path(args[1])
out.mkdir(parents=True, exist_ok=True)
report = {"blender": bpy.app.version_string, "usd": ".".join(map(str, Usd.GetVersion()))}


def probe(name, fn):
    try:
        report[name] = fn()
    except Exception as e:  # noqa: BLE001
        report[name] = f"FAILED: {type(e).__name__}: {e}"
        traceback.print_exc()


STJ_DOC = {"_metadata": {"specification": "STJ", "version": "0.3"}, "timing": {"start": {"s": 30}}}


# ── A. build ──────────────────────────────────────────────────────────────────
def build():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    scene = bpy.context.scene
    scene["stj"] = {"north_heading": 1.5708}
    bpy.data.texts.new("track.stj.json").write(json.dumps(STJ_DOC))

    col = bpy.data.collections.new("STJ_Collision")
    col["stj"] = {"role": "collision"}
    scene.collection.children.link(col)
    me = bpy.data.meshes.new("road")
    me.from_pydata([(0, 0, 0), (10, 0, 0), (10, 5, 0), (0, 5, 0), (20, 0, 0), (20, 5, 0)], [], [(0, 1, 2, 3), (1, 4, 5, 2)])
    gravel = bpy.data.materials.new("STJ::surface::gravel_loose")
    gravel["stj"] = {"class": "gravel", "mf_scaling": {"LMUX": 0.62}}
    # a procedural node material: noise -> colour ramp -> base colour
    nt = gravel.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    tarmac = bpy.data.materials.new("Tarmac")
    tarmac["stj_surface"] = "asphalt"
    me.materials.append(gravel)
    me.materials.append(tarmac)
    me.polygons[1].material_index = 1
    me.attributes.new("stj_surface_id", "INT", "FACE").data.foreach_set("value", [3, 7])
    me.attributes.new("_STJ_DENSITY", "FLOAT", "POINT").data.foreach_set("value", [0.0, 0.5, 1.0, 0.2, 0.8, 0.1])
    w = me.attributes.new("_STJ_SURF_WEIGHTS", "FLOAT2", "CORNER")
    w.data.foreach_set("vector", [0.5, 0.25] * 8)
    ob = bpy.data.objects.new("road", me)
    ob["stj"] = {"role": "collision"}
    col.objects.link(ob)

    cu = bpy.data.curves.new("reference", "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("POLY")
    sp.points.add(3)
    for i, p in enumerate([(0, 2.5, 0), (10, 2.5, 0), (20, 2.5, 0.5), (30, 4, 1)]):
        sp.points[i].co = (*p, 1)
    ref = bpy.data.objects.new("STJ::reference::centerline", cu)
    ref["stj"] = {"closed": False}
    scene.collection.objects.link(ref)
    bz = bpy.data.curves.new("racing_line", "CURVE")
    bs = bz.splines.new("BEZIER")
    bs.bezier_points.add(1)
    bs.bezier_points[0].co, bs.bezier_points[1].co = (0, 1, 0), (30, 3, 1)
    scene.collection.objects.link(bpy.data.objects.new("STJ::race::racing_line", bz))

    e = bpy.data.objects.new("STJ::timing::start", None)
    e["stj"] = {"kind": "start", "s": 30.0}
    scene.collection.objects.link(e)
    for f, a in ((1, 0.0), (25, math.pi)):
        e.rotation_euler = (0, 0, a)
        e.keyframe_insert("rotation_euler", frame=f)
    e.animation_data.action.name = "gate_spin"

    scene.collection.objects.link(bpy.data.objects.new("cam_tv1", bpy.data.cameras.new("cam_tv1")))
    scene.collection.objects.link(bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")))
    spot = bpy.data.objects.new("flood_1", bpy.data.lights.new("flood_1", "SPOT"))
    spot["stj"] = {"when": {"signal": "sun_elevation", "op": "lt", "value": 0.05}}
    scene.collection.objects.link(spot)
    world = bpy.data.worlds.new("World")
    scene.world = world
    sky = world.node_tree.nodes.new("ShaderNodeTexSky")
    world.node_tree.links.new(sky.outputs["Color"], world.node_tree.nodes["Background"].inputs["Color"])

    bpy.ops.mesh.primitive_cone_add(radius1=0.18, depth=0.7)
    cone = bpy.context.active_object
    cone.name = "cone"
    bpy.ops.rigidbody.object_add()
    cone.rigid_body.mass = 4.5
    cone.rigid_body.friction = 0.7

    snd = bpy.data.sounds.load(str(wav))
    spk = bpy.data.objects.new("STJ::audio::pa", bpy.data.speakers.new("pa"))
    spk.data.sound = snd
    spk.data.distance_max = 250.0
    scene.collection.objects.link(spk)

    # instancing: linked duplicates and a geometry-nodes scatter
    pine = bpy.data.meshes.new("pine")
    pine.from_pydata([(0, 0, 0), (0.5, 0, 0), (0, 0, 3)], [], [(0, 1, 2)])
    for i in range(3):
        o = bpy.data.objects.new(f"pine_{i}", pine)
        o.location = (i * 4.0, 20.0, 0.0)
        scene.collection.objects.link(o)
    host = bpy.data.objects.new("scatter_host", bpy.data.meshes.new("plane"))
    host.data.from_pydata([(0, 30, 0), (20, 30, 0), (20, 50, 0), (0, 50, 0)], [], [(0, 1, 2, 3)])
    scene.collection.objects.link(host)
    mod = host.modifiers.new("STJ_Scatter_grass", "NODES")
    g = bpy.data.node_groups.new("scatter", "GeometryNodeTree")
    g.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    g.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gi, go = g.nodes.new("NodeGroupInput"), g.nodes.new("NodeGroupOutput")
    dist = g.nodes.new("GeometryNodeDistributePointsOnFaces")
    dist.inputs["Density"].default_value = 0.5
    inst = g.nodes.new("GeometryNodeInstanceOnPoints")
    oi = g.nodes.new("GeometryNodeObjectInfo")
    oi.inputs["Object"].default_value = bpy.data.objects["pine_0"]
    g.links.new(gi.outputs[0], dist.inputs["Mesh"])
    g.links.new(dist.outputs["Points"], inst.inputs["Points"])
    g.links.new(oi.outputs["Geometry"], inst.inputs["Instance"])
    g.links.new(inst.outputs["Instances"], go.inputs[0])
    mod.node_group = g
    return {"objects": len(bpy.data.objects)}


probe("build", build)
usda = out / "probe.usda"


def export():
    bpy.ops.wm.usd_export(filepath=str(usda), export_animation=True, use_instancing=True,
                          generate_materialx_network=True, export_custom_properties=True,
                          convert_world_material=True, export_textures_mode="KEEP")
    return {"bytes": usda.stat().st_size}


probe("export", export)


# ── A. inspect ────────────────────────────────────────────────────────────────
def inspect(path):
    st = Usd.Stage.Open(str(path))
    r = {"upAxis": UsdGeom.GetStageUpAxis(st), "metersPerUnit": UsdGeom.GetStageMetersPerUnit(st),
         "layer_customData": dict(st.GetRootLayer().customLayerData)}
    prims = {}
    for p in st.Traverse():
        prims[str(p.GetPath())] = {
            "type": p.GetTypeName(),
            "apis": [str(a) for a in p.GetAppliedSchemas()],
            "user": {a.GetName(): str(a.Get())[:80] for a in p.GetAttributes() if a.GetName().startswith("userProperties:")},
        }
    r["prim_types"] = sorted({v["type"] for v in prims.values() if v["type"]})
    r["applied_apis"] = sorted({a for v in prims.values() for a in v["apis"]})
    mesh = next((c for p in st.Traverse() if p.GetName() == "road" for c in Usd.PrimRange(p) if c.IsA(UsdGeom.Mesh)), None)
    if mesh:
        pv = UsdGeom.PrimvarsAPI(mesh)
        r["road_primvars"] = {x.GetPrimvarName(): [x.GetInterpolation(), str(x.GetTypeName())] for x in pv.GetPrimvars()}
        r["road_geomsubsets"] = [str(s.GetPath().name) for s in UsdGeom.Subset.GetAllGeomSubsets(UsdGeom.Imageable(mesh))]
        r["road_user"] = prims[str(mesh.GetPath())]["user"]
    r["materials"] = {}
    for p in st.Traverse():
        if p.IsA(UsdShade.Material):
            shaders = [str(c.GetAttribute("info:id").Get()) for c in Usd.PrimRange(p) if c.IsA(UsdShade.Shader)]
            r["materials"][p.GetName()] = {"shader_ids": sorted(set(s for s in shaders if s != "None")),
                                           "user": prims[str(p.GetPath())]["user"]}
    r["curves"] = {p.GetName(): p.GetTypeName() for p in st.Traverse() if p.IsA(UsdGeom.Curves)}
    r["point_instancers"] = {p.GetName(): len(UsdGeom.PointInstancer(p).GetPositionsAttr().Get() or [])
                             for p in st.Traverse() if p.IsA(UsdGeom.PointInstancer)}
    r["native_instances"] = sum(1 for p in st.Traverse() if p.IsInstance())
    r["animated_xforms"] = [p.GetName() for p in st.Traverse() if p.IsA(UsdGeom.Xformable)
                            and any(op.GetAttr().GetNumTimeSamples() > 1 for op in UsdGeom.Xformable(p).GetOrderedXformOps())]
    r["user_props_on"] = sorted(k.rsplit("/", 1)[-1] for k, v in prims.items() if v["user"])
    r["names"] = sorted(k.rsplit("/", 1)[-1] for k in prims)[:60]
    return r


probe("A_exported", lambda: inspect(usda))


# ── B. what USD can hold, written with pxr ────────────────────────────────────
rich = out / "probe_rich.usda"


def mesh_under(st, xform_name):
    """The first Mesh at or below the prim Blender exported for object `xform_name`."""
    for p in st.Traverse():
        if p.GetName() == xform_name:
            return next(c for c in Usd.PrimRange(p) if c.IsA(UsdGeom.Mesh))
    raise LookupError(xform_name)


def enrich():
    st = Usd.Stage.Open(str(usda))
    layer = st.GetRootLayer()
    layer.customLayerData = {"stj": json.dumps(STJ_DOC)}
    UsdGeom.SetStageUpAxis(st, UsdGeom.Tokens.z)
    mesh = mesh_under(st, "road")
    pv = UsdGeom.PrimvarsAPI(mesh)
    pv.CreatePrimvar("stj_surface_id", Sdf.ValueTypeNames.IntArray, UsdGeom.Tokens.uniform).Set(Vt.IntArray([3, 7]))
    pv.CreatePrimvar("STJ_SURF_LAYERS", Sdf.ValueTypeNames.Int3Array, UsdGeom.Tokens.uniform).Set(
        Vt.Vec3iArray([(0, 1, 2), (0, 1, 3)]))
    mesh.CreateAttribute("stj:surface", Sdf.ValueTypeNames.String).Set("gravel_loose")
    # variants: dry / wet changing a surface value
    vs = mesh.GetVariantSets().AddVariantSet("stj_condition")
    for name, val in (("dry", 0.0), ("wet", 0.0015)):
        vs.AddVariant(name)
        vs.SetVariantSelection(name)
        with vs.GetVariantEditContext():
            mesh.CreateAttribute("stj:water_depth", Sdf.ValueTypeNames.Float).Set(val)
    vs.SetVariantSelection("dry")
    # physics: rigid body, mass, collider, physics material
    cone = mesh_under(st, "cone")
    UsdPhysics.RigidBodyAPI.Apply(cone.GetParent() if cone.GetParent().IsA(UsdGeom.Xform) else cone)
    UsdPhysics.CollisionAPI.Apply(cone)
    UsdPhysics.MassAPI.Apply(cone).CreateMassAttr(4.5)
    pm = UsdShade.Material.Define(st, "/root/physics_gravel")
    pma = UsdPhysics.MaterialAPI.Apply(pm.GetPrim())
    pma.CreateStaticFrictionAttr(0.62)
    pma.CreateRestitutionAttr(0.1)
    # audio
    au = UsdMedia.SpatialAudio.Define(st, "/root/pa_audio")
    au.CreateFilePathAttr(Sdf.AssetPath(wav.name))
    au.CreateAuralModeAttr(UsdMedia.Tokens.spatial)
    au.CreatePlaybackModeAttr(UsdMedia.Tokens.loopFromStart)
    # a payload: streaming a chunk
    chunk = out / "chunk_c01.usda"
    cst = Usd.Stage.CreateNew(str(chunk))
    UsdGeom.Xform.Define(cst, "/c01")
    cst.SetDefaultPrim(cst.GetPrimAtPath("/c01"))
    cst.GetRootLayer().Save()
    st.DefinePrim("/root/chunk_c01").GetPayloads().AddPayload(chunk.name)
    st.GetRootLayer().Export(str(rich))
    r = inspect(rich)
    st2 = Usd.Stage.Open(str(rich))
    m2 = st2.GetPrimAtPath(mesh.GetPath())
    vset = m2.GetVariantSets().GetVariantSet("stj_condition")
    r["variants"] = vset.GetVariantNames()
    vset.SetVariantSelection("wet")
    r["wet_water_depth"] = m2.GetAttribute("stj:water_depth").Get()
    r["layer_stj_roundtrip"] = json.loads(st2.GetRootLayer().customLayerData["stj"]) == STJ_DOC
    r["payloads"] = [str(p.GetPath()) for p in st2.Traverse() if p.HasPayload()]
    return r


probe("B_rich", enrich)


# ── re-import both into Blender ───────────────────────────────────────────────
def reimport(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.usd_import(filepath=str(path), property_import_mode="ALL", read_mesh_attributes=True, import_all_materials=True)
    r = {"objects": sorted(o.name for o in bpy.data.objects)[:40], "types": sorted({o.type for o in bpy.data.objects})}
    road = next((o for o in bpy.data.objects if o.name.startswith("road")), None)
    if road:
        r["road_attributes"] = {a.name: [a.domain, a.data_type] for a in road.data.attributes if not a.name.startswith(".")}
        r["road_props"] = {k: str(v)[:80] for k, v in road.items()}
        r["road_data_props"] = {k: str(v)[:80] for k, v in road.data.items()}
    r["materials"] = {m.name: {k: str(v)[:60] for k, v in m.items()} for m in bpy.data.materials}
    r["curves"] = [o.name for o in bpy.data.objects if o.type == "CURVE" or o.type == "CURVES"]
    r["rigid_bodies"] = [o.name for o in bpy.data.objects if o.rigid_body]
    r["speakers"] = [o.name for o in bpy.data.objects if o.type == "SPEAKER"]
    r["animated"] = [o.name for o in bpy.data.objects if o.animation_data and o.animation_data.action]
    r["world_nodes"] = [n.bl_idname for n in bpy.context.scene.world.node_tree.nodes] if bpy.context.scene.world else None
    return r


probe("A_reimport", lambda: reimport(usda))
probe("B_reimport", lambda: reimport(rich))
(out / "report_usd.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
print("PROBE_DONE")
