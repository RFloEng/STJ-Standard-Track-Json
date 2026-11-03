"""Probe what a .blend can hold for STJ, and what survives glTF export.

blender -b --factory-startup --python blend_probe.py -- <out_dir>
"""
import json
import struct
import sys
import traceback
from pathlib import Path

import bpy

out = Path(sys.argv[sys.argv.index("--") + 1])
out.mkdir(parents=True, exist_ok=True)
report = {"blender": bpy.app.version_string}


def probe(name, fn):
    try:
        report[name] = fn()
    except Exception as e:  # noqa: BLE001
        report[name] = f"FAILED: {type(e).__name__}: {e}"
        traceback.print_exc()


# ── build ───────────────────────────────────────────────────────────────────
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
scene = bpy.context.scene

STJ_DOC = {"_metadata": {"specification": "STJ", "version": "0.1"}, "timing": {"start": {"s": 30}}}


def build():
    t = bpy.data.texts.new("track.stj.json")
    t.write(json.dumps(STJ_DOC, indent=2))
    scene["stj"] = {"version": "0.1", "north_heading": 1.5708, "grid": [1, 2, 3]}

    col = bpy.data.collections.new("STJ_Collision")
    scene.collection.children.link(col)
    me = bpy.data.meshes.new("road")
    me.from_pydata([(0, 0, 0), (10, 0, 0), (10, 5, 0), (0, 5, 0), (20, 0, 0), (20, 5, 0)], [], [(0, 1, 2, 3), (1, 4, 5, 2)])
    mat_a = bpy.data.materials.new("STJ::surface::gravel_loose")
    mat_a["stj_surface"] = "gravel_loose"
    mat_a["stj"] = {"class": "gravel", "mf_scaling": {"LMUX": 0.62}}
    mat_b = bpy.data.materials.new("Tarmac")
    mat_b["stj_surface"] = "asphalt"
    me.materials.append(mat_a)
    me.materials.append(mat_b)
    me.polygons[1].material_index = 1
    a = me.attributes.new("stj_surface_id", "INT", "FACE")
    a.data.foreach_set("value", [3, 7])
    d = me.attributes.new("_STJ_DENSITY", "FLOAT", "POINT")
    d.data.foreach_set("value", [0.0, 0.5, 1.0, 0.2, 0.8, 0.1])
    ob = bpy.data.objects.new("road", me)
    ob["stj_role"] = "collision"
    col.objects.link(ob)

    # reference line as a curve
    cu = bpy.data.curves.new("reference", "CURVE")
    sp = cu.splines.new("POLY")
    sp.points.add(2)
    for i, p in enumerate([(0, 2.5, 0, 1), (10, 2.5, 0, 1), (20, 2.5, 0, 1)]):
        sp.points[i].co = p
    cob = bpy.data.objects.new("STJ::reference::centerline", cu)
    scene.collection.objects.link(cob)

    # timing empty
    e = bpy.data.objects.new("STJ::timing::start", None)
    e["stj"] = {"s": 30.0}
    scene.collection.objects.link(e)

    # sun + world sky
    sun = bpy.data.lights.new("sun", "SUN")
    sun.energy = 4.0
    sob = bpy.data.objects.new("STJ::light::sun", sun)
    scene.collection.objects.link(sob)
    world = bpy.data.worlds.new("STJ_World")
    world.use_nodes = True
    sky = world.node_tree.nodes.new("ShaderNodeTexSky")
    report["sky_types"] = [i.identifier for i in sky.bl_rna.properties["sky_type"].enum_items]
    world.node_tree.links.new(sky.outputs[0], world.node_tree.nodes["Background"].inputs[0])
    world["stj"] = {"turbidity": 2.5}
    scene.world = world

    # tree prototype + instances: collection instance and geometry-nodes scatter
    protos = bpy.data.collections.new("STJ_Prototypes")
    scene.collection.children.link(protos)
    tme = bpy.data.meshes.new("pine")
    tme.from_pydata([(0, 0, 0), (1, 0, 0), (0, 0, 8)], [], [(0, 1, 2)])
    tob = bpy.data.objects.new("pine_01", tme)
    tob["stj"] = {"class": "tree", "species": "pinus_sylvestris", "height": 18.0,
                  "x_ac": {"_note": "illustrative"}, "x_beamng": {"forest_item": "tree_pine"}}
    protos.objects.link(tob)
    inst = bpy.data.objects.new("pine_01.inst", None)
    inst.instance_type = "COLLECTION"
    inst.instance_collection = protos
    inst.location = (5, 20, 0)
    scene.collection.objects.link(inst)

    host = bpy.data.objects.new("scatter_host", me.copy())
    scene.collection.objects.link(host)
    mod = host.modifiers.new("STJ_Scatter", "NODES")
    ng = bpy.data.node_groups.new("STJ_Scatter", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    n_in = ng.nodes.new("NodeGroupInput")
    n_out = ng.nodes.new("NodeGroupOutput")
    dist = ng.nodes.new("GeometryNodeDistributePointsOnFaces")
    dist.inputs["Density"].default_value = 2.0
    iop = ng.nodes.new("GeometryNodeInstanceOnPoints")
    oi = ng.nodes.new("GeometryNodeObjectInfo")
    oi.inputs["Object"].default_value = tob
    ng.links.new(n_in.outputs[0], dist.inputs["Mesh"])
    ng.links.new(dist.outputs["Points"], iop.inputs["Points"])
    ng.links.new(oi.outputs["Geometry"], iop.inputs["Instance"])
    ng.links.new(iop.outputs["Instances"], n_out.inputs[0])
    mod.node_group = ng
    host["stj"] = {"scatter": {"layer": "pines", "density": 0.5}}

    # packed image
    img = bpy.data.images.new("density_mask", 8, 8)
    img.pixels = [0.5] * (8 * 8 * 4)
    img.filepath_raw = str(out / "density_mask.png")
    img.file_format = "PNG"
    img.save()
    img.pack()
    img.use_fake_user = True
    xt = bpy.data.texts.new('track.xodr')
    xt.write('<?xml version="1.0"?><OpenDRIVE><header revMajor="1" revMinor="8"/><road id="1" length="20.0"/></OpenDRIVE>')
    col['stj'] = {'role': 'collision'}
    holder = bpy.data.objects.new('STJ::scatter::pines_gpu', None)
    scene.collection.objects.link(holder)
    for k in range(5):
        c = bpy.data.objects.new(f'pine_gpu_{k}', tme)
        c.location = (k * 3.0, 40, 0)
        c.parent = holder
        scene.collection.objects.link(c)

    # asset marking
    tob.asset_mark()
    return "ok"


probe("build", build)
blend = out / "probe.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(blend))

# ── reopen and read back ─────────────────────────────────────────────────────
bpy.ops.wm.open_mainfile(filepath=str(blend))
scene = bpy.context.scene


def readback():
    r = {}
    r["text_json_roundtrip"] = json.loads(bpy.data.texts["track.stj.json"].as_string()) == STJ_DOC
    r["scene_idprop"] = scene["stj"].to_dict() if hasattr(scene["stj"], "to_dict") else str(scene["stj"])
    m = bpy.data.materials["STJ::surface::gravel_loose"]
    r["material_idprop"] = m["stj"].to_dict()
    me = bpy.data.objects["road"].data
    r["face_int_attr"] = [v.value for v in me.attributes["stj_surface_id"].data]
    r["point_float_attr"] = [round(v.value, 3) for v in me.attributes["_STJ_DENSITY"].data]
    r["curve_points"] = [tuple(p.co)[:3] for p in bpy.data.objects["STJ::reference::centerline"].data.splines[0].points]
    r["empty_idprop"] = bpy.data.objects["STJ::timing::start"]["stj"].to_dict()
    r["world_sky_node"] = [n.bl_idname for n in scene.world.node_tree.nodes]
    r["world_idprop"] = scene.world["stj"].to_dict()
    r["proto_idprop"] = bpy.data.objects["pine_01"]["stj"].to_dict()
    r["image_packed"] = bpy.data.images["density_mask"].packed_file is not None
    r["xodr_text"] = bpy.data.texts['track.xodr'].as_string()[:60]
    r["collection_idprop"] = bpy.data.collections['STJ_Collision']['stj'].to_dict()
    r["asset_marked"] = bpy.data.objects["pine_01"].asset_data is not None
    deps = bpy.context.evaluated_depsgraph_get()
    host = bpy.data.objects["scatter_host"].evaluated_get(deps)
    n_inst = sum(1 for i in deps.object_instances if i.is_instance and i.parent and i.parent.original.name == "scatter_host")
    r["gn_scatter_instances"] = n_inst
    return r


probe("readback", readback)

# ── glTF export ──────────────────────────────────────────────────────────────
props = bpy.ops.export_scene.gltf.get_rna_type().properties
report["gltf_export_options"] = sorted(p.identifier for p in props if any(k in p.identifier for k in ("extra", "attribute", "instanc", "light", "custom", "gpu", "hierarchy", "collection")))


def export():
    kw = dict(export_hierarchy_full_collections=True, filepath=str(out / "probe.gltf"), export_format="GLTF_SEPARATE", use_selection=False, export_extras=True)
    names = {p.identifier for p in props}
    for opt in ("export_attributes", "export_gpu_instances", "export_lights"):
        if opt in names:
            kw[opt] = True
    bpy.ops.export_scene.gltf(**kw)
    g = json.loads((out / "probe.gltf").read_text(encoding="utf-8"))
    r = {"extensionsUsed": g.get("extensionsUsed", [])}
    r["material_extras"] = {m["name"]: m.get("extras") for m in g.get("materials", [])}
    r["node_extras"] = {n.get("name"): n.get("extras") for n in g.get("nodes", []) if n.get("extras")}
    r["scene_extras"] = [s.get("extras") for s in g.get("scenes", [])]
    attrs = set()
    for m in g.get("meshes", []):
        for p in m["primitives"]:
            attrs |= set(p["attributes"])
    r["primitive_attributes"] = sorted(attrs)
    r["node_names"] = [n.get("name") for n in g.get("nodes", [])]
    r["gpu_instancing_nodes"] = sum(1 for n in g.get("nodes", []) if "EXT_mesh_gpu_instancing" in n.get("extensions", {}))
    r["export_kwargs"] = sorted(kw)
    r["gpu_nodes"] = [n.get('name') for n in g.get('nodes', []) if 'EXT_mesh_gpu_instancing' in n.get('extensions', {})]
    r["collection_extras"] = [n.get('extras') for n in g.get('nodes', []) if n.get('name') == 'STJ_Collision']
    return r


probe("gltf", export)
(out / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
print("PROBE_DONE")
