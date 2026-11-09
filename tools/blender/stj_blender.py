"""The STJ Blender profile, run inside Blender: read the scene, check it, export the delivery package.

    blender -b track.blend --python tools/blender/stj_blender.py -- lint
    blender -b track.blend --python tools/blender/stj_blender.py -- export <out_dir> [name]
    blender -b --factory-startup --python tools/blender/stj_blender.py -- import <track.stj.json|.usd> <out.blend>
    blender -b track.blend --python tools/blender/stj_blender.py -- dump <scene.json>

`lint` prints the findings and exits 1 when there is an ERROR. `export` writes <name>.stj.json (the document:
the text block `track.stj.json` with the objects applied over it) and <name>.usd (Blender's USD export with
the document embedded in customLayerData["stj"]), and refuses to export when the lint has an ERROR.
`import` builds a profile scene from a document (JSON, or the document inside a USD) and saves it as a
.blend: the reference curve, gates, grid, pit boxes and spawns as objects, the surfaces as materials, and the
rest of the document in the text block `track.stj.json`.
The rules are in spec/STJ_Blender_Profile.md; the decisions are in stj_profile.py, which does not need Blender.
"""
import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stj_profile as profile  # noqa: E402
import stj_core as core  # noqa: E402


def _plain(value):
    """A custom property as plain Python (ID property groups and arrays become dicts and lists)."""
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "to_list"):
        return value.to_list()
    return value


def _props(idblock):
    return {k: _plain(idblock[k]) for k in idblock.keys() if not k.startswith("_RNA_UI")}


def _vec(v):
    return [float(v[0]), float(v[1]), float(v[2])]


def _curve(obj):
    """Points (and Hermite tangents for a Bezier spline) of the first spline, in world coordinates."""
    spline = obj.data.splines[0] if obj.data.splines else None
    if spline is None:
        return {"points": [], "cyclic": False}
    m = obj.matrix_world
    out = {"cyclic": bool(spline.use_cyclic_u)}
    if spline.type == "BEZIER":
        pts = spline.bezier_points
        out["points"] = [_vec(m @ p.co) for p in pts]
        # a cubic Bezier segment P0..P3 is the Hermite segment with tangents 3 (P1 - P0) and 3 (P3 - P2)
        out["tangents_out"] = [_vec(3.0 * ((m @ p.handle_right) - (m @ p.co))) for p in pts]
        out["tangents_in"] = [_vec(3.0 * ((m @ p.co) - (m @ p.handle_left))) for p in pts]
    else:
        out["points"] = [_vec(m @ p.co.to_3d()) for p in spline.points]
    return out


def read_scene(scene=None):
    """The scene description of the current .blend (see stj_profile.py)."""
    scene = scene or bpy.context.scene
    objects = []
    for obj in bpy.data.objects:
        axis = obj.matrix_world.to_3x3().col[0]
        entry = {"name": obj.name, "type": obj.type, "location": _vec(obj.matrix_world.translation),
                 "heading": profile.heading_of(axis), "collections": [c.name for c in obj.users_collection],
                 "props": _props(obj)}
        if obj.type == "CURVE":
            entry.update(_curve(obj))
        elif obj.type == "MESH" and (profile.parse_name(obj.name) or ("",))[0] == "instance":
            # an instance set: one vertex per instance, with the heading and the scale as point attributes
            mesh = obj.data
            entry["points"] = [_vec(obj.matrix_world @ v.co) for v in mesh.vertices]
            for key, attr in (("headings", "stj_heading"), ("scales", "stj_scale")):
                a = mesh.attributes.get(attr)
                entry[key] = [float(d.value) for d in a.data] if a is not None else []
        elif obj.type == "MESH" and (profile.parse_name(obj.name) or ("",))[0] == "terrain":
            m = obj.matrix_world
            entry["points"] = [_vec(m @ v.co) for v in obj.data.vertices]
        elif obj.type == "MESH" and (profile.parse_name(obj.name) or ("",))[0] == "prototype":
            rb = obj.rigid_body                     # the proxy body of a prototype (a Rigid Body, or none)
            if rb is not None:
                entry["rigid_body"] = {"type": rb.type, "mass": rb.mass, "friction": rb.friction,
                                       "restitution": rb.restitution, "collision_shape": rb.collision_shape}
            entry["dimensions"] = _vec(obj.dimensions)
        elif obj.type == "CAMERA":
            entry["forward"] = _vec((-obj.matrix_world.to_3x3().col[2]).normalized())      # a camera looks along -Z
        elif obj.type == "LIGHT":
            z = obj.matrix_world.to_3x3().col[2]          # a Sun light shines along -Z, so +Z points at the sun
            entry.update({"light_type": obj.data.type, "direction": _vec(z.normalized())})
        objects.append(entry)
    collections = [{"name": c.name, "props": _props(c),
                    "objects": [o.name for o in c.all_objects if o.type == "MESH"]}
                   for c in bpy.data.collections if profile.parse_name(c.name)]
    return {"blender": bpy.app.version_string, "profile": scene.get(profile.PROFILE_PROP),
            "objects": objects, "collections": collections,
            "materials": [{"name": m.name, "props": _props(m)} for m in bpy.data.materials],
            "texts": {t.name: t.as_string() for t in bpy.data.texts},
            "scene_props": _props(scene)}


def lint():
    findings = profile.lint_scene(read_scene())
    for line in profile.format_findings(findings):
        print(line)
    errors = [f for f in findings if f[0] == "ERROR"]
    print(f"{len(errors)} error(s), {sum(1 for f in findings if f[0] == 'WARN')} warning(s), "
          f"{sum(1 for f in findings if f[0] == 'NOTE')} note(s)")
    return 1 if errors else 0


def export(out_dir, name="track"):
    scene = read_scene()
    findings = profile.lint_scene(scene)
    for line in profile.format_findings(findings):
        print(line)
    if any(f[0] == "ERROR" for f in findings):
        print("not exported: fix the errors above")
        return 1
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    doc = profile.apply_scene(scene)
    json_path = out / f"{name}.stj.json"
    json_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    usd_path = out / f"{name}.usd"
    if usd_path.exists():
        usd_path.unlink()
    core.embed_document(doc, usd_path)                 # the track stage: the document, Z up, metres
    written = [json_path, usd_path]
    for uri, data in profile.terrain_files(scene):
        target = out / uri
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append(target)
    for entry in (doc.get("geometry") or {}).get("meshes", []):
        coll = bpy.data.collections.get(next((c["name"] for c in scene["collections"]
                                              if profile.parse_name(c["name"]) == ("mesh", entry["id"], None)), ""))
        if coll is None:
            continue
        target = out / entry["uri"]
        target.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.usd_export(filepath=str(target), collection=coll.name, export_materials=True,
                              generate_preview_surface=True, generate_materialx_network=True)
        written.append(target)
    print("wrote " + ", ".join(str(w) for w in written))
    return 0


def clear_scene():
    """Empty the open file without reloading Blender's settings (an add-on stays enabled)."""
    for coll in (bpy.data.objects, bpy.data.collections, bpy.data.meshes, bpy.data.curves, bpy.data.cameras,
                 bpy.data.lights, bpy.data.speakers, bpy.data.materials, bpy.data.texts, bpy.data.images):
        for item in list(coll):
            coll.remove(item)
    for world in list(bpy.data.worlds):
        if world.name.startswith("STJ::"):
            bpy.data.worlds.remove(world)
    scene = bpy.context.scene
    for key in list(scene.keys()):
        del scene[key]


def build_scene(desc, reset=True):
    """Create the objects, materials and text block of a scene description in a fresh, empty file.

    reset: reload Blender's factory settings first (the command line); False empties the open file instead,
    which is what the add-on does."""
    from mathutils import Vector
    if reset:
        bpy.ops.wm.read_factory_settings(use_empty=True)
    else:
        clear_scene()
    scene = bpy.context.scene
    scene[profile.PROFILE_PROP] = profile.PROFILE_VERSION
    root = bpy.data.collections.new("STJ")
    scene.collection.children.link(root)
    for o in desc["objects"]:
        if o["type"] == "CURVE":
            cu = bpy.data.curves.new(o["name"], "CURVE")
            cu.dimensions = "3D"
            pts = o["points"]
            if o.get("tangents_out"):
                sp = cu.splines.new("BEZIER")
                sp.bezier_points.add(len(pts) - 1)
                for bp, p, t_out, t_in in zip(sp.bezier_points, pts, o["tangents_out"], o["tangents_in"]):
                    co = Vector(p)
                    bp.co = co
                    bp.handle_left_type = bp.handle_right_type = "FREE"
                    bp.handle_right = co + Vector(t_out) / 3.0
                    bp.handle_left = co - Vector(t_in) / 3.0
            else:
                sp = cu.splines.new("POLY")
                sp.points.add(len(pts) - 1)
                for sp_pt, p in zip(sp.points, pts):
                    sp_pt.co = (p[0], p[1], p[2], 1.0)
            sp.use_cyclic_u = bool(o.get("cyclic"))
            ob = bpy.data.objects.new(o["name"], cu)
        elif o["type"] == "MESH":
            mesh = bpy.data.meshes.new(o["name"])
            if o.get("proxy"):                 # the proxy body of a prototype's physics
                import bmesh
                bm = bmesh.new()
                dx, dy, dz = o["dimensions"]
                if o["proxy"] == "SPHERE":
                    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=0.5)
                elif o["proxy"] in ("CYLINDER", "CAPSULE"):
                    bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.5, radius2=0.5, depth=1.0)
                else:
                    bmesh.ops.create_cube(bm, size=1.0)
                for v in bm.verts:
                    v.co = (v.co.x * dx, v.co.y * dy, v.co.z * dz + dz / 2.0)      # the base centre is the origin
                bm.to_mesh(mesh)
                bm.free()
            faces = []
            if o.get("grid"):                  # a terrain: a regular grid, row 0 at the north edge
                nx, ny = o["grid"]
                faces = [(j * nx + i, (j + 1) * nx + i, (j + 1) * nx + i + 1, j * nx + i + 1)
                         for j in range(ny - 1) for i in range(nx - 1)]
            if "points" in o:
                mesh.from_pydata([tuple(p) for p in o["points"]], [], faces)
            for attr, key in (("stj_heading", "headings"), ("stj_scale", "scales")):
                if key in o:
                    a = mesh.attributes.new(attr, "FLOAT", "POINT")
                    a.data.foreach_set("value", o[key])
            ob = bpy.data.objects.new(o["name"], mesh)
        elif o["type"] == "CAMERA":
            ob = bpy.data.objects.new(o["name"], bpy.data.cameras.new(o["name"]))
            ob.location = o["location"]
            ob.rotation_euler = Vector(o["forward"]).to_track_quat("-Z", "Y").to_euler()
        elif o["type"] == "SPEAKER":
            ob = bpy.data.objects.new(o["name"], bpy.data.speakers.new(o["name"]))      # an audio emitter: heard in the viewport
            ob.location = o["location"]
            ob.rotation_euler = (0.0, 0.0, o["heading"])
        elif o["type"] == "LIGHT":
            light = bpy.data.lights.new(o["name"], o.get("light_type", "SUN"))
            ob = bpy.data.objects.new(o["name"], light)
            ob.location = o["location"]
            ob.rotation_euler = Vector(o["direction"]).to_track_quat("Z", "Y").to_euler()
        else:
            ob = bpy.data.objects.new(o["name"], None)
            ob.empty_display_type = "ARROWS"
            ob.location = o["location"]
            ob.rotation_euler = (0.0, 0.0, o["heading"])
        for k, v in o.get("props", {}).items():
            ob[k] = v
        root.objects.link(ob)
        if o.get("rigid_body"):
            bpy.context.view_layer.objects.active = ob
            ob.select_set(True)
            bpy.ops.rigidbody.object_add()
            for attr, value in o["rigid_body"].items():
                setattr(ob.rigid_body, attr, value)
            ob.select_set(False)
    if any(o["name"] == "STJ::sky::sky" for o in desc["objects"]):
        world = bpy.data.worlds.new("STJ::sky")             # the sky shows in the viewport; the document keeps the data on the empty
        world.use_nodes = True
        nodes, links = world.node_tree.nodes, world.node_tree.links
        sky_node = nodes.new("ShaderNodeTexSky")
        links.new(sky_node.outputs["Color"], nodes["Background"].inputs["Color"])
        scene.world = world
    for c in desc.get("collections", []):
        coll = bpy.data.collections.new(c["name"])
        scene.collection.children.link(coll)
        for k, v in c.get("props", {}).items():
            coll[k] = v
        if c.get("usd"):
            before = set(bpy.data.materials.keys())
            layer = bpy.context.view_layer.layer_collection.children[coll.name]
            bpy.context.view_layer.active_layer_collection = layer         # the import lands in the active collection
            bpy.ops.wm.usd_import(filepath=c["usd"])
            for mat in list(bpy.data.materials):
                if mat.name not in before:
                    parsed = profile.parse_name(mat.name)
                    if parsed and "::" not in mat.name:
                        target = "STJ::" + "::".join(p for p in parsed if p)         # the same name, the Blender spelling
                        if target in bpy.data.materials:
                            mat.user_remap(bpy.data.materials[target])               # a second file using the same surface
                            bpy.data.materials.remove(mat)
                        else:
                            mat.name = target
    for m in desc["materials"]:
        mat = bpy.data.materials.get(m["name"]) or bpy.data.materials.new(m["name"])
        mat.use_fake_user = True                   # a surface that no mesh uses yet must still be saved
        for k, v in m.get("props", {}).items():
            mat[k] = v
    for name, text in desc["texts"].items():
        bpy.data.texts.new(name).write(text)


def import_document(doc_path, out_blend):
    doc = core.load_document(doc_path)
    build_scene(profile.scene_from_document(doc, Path(doc_path).resolve().parent))
    bpy.ops.wm.save_as_mainfile(filepath=str(out_blend))
    findings = profile.lint_scene(read_scene())
    for line in profile.format_findings(findings):
        print(line)
    print(f"wrote {out_blend}")
    return 1 if any(f[0] == "ERROR" for f in findings) else 0


def dump(path):
    """The scene description as JSON (for comparing two .blend files)."""
    Path(path).write_text(json.dumps(read_scene(), indent=1, sort_keys=True), encoding="utf-8")
    return 0


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "lint":
        return lint()
    if argv[0] == "export" and len(argv) >= 2:
        return export(argv[1], argv[2] if len(argv) > 2 else "track")
    if argv[0] == "dump" and len(argv) >= 2:
        return dump(argv[1])
    if argv[0] == "import" and len(argv) >= 3:
        return import_document(argv[1], argv[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    try:
        code = main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    except Exception:  # noqa: BLE001  (Blender exits 0 after a script error; a failed command must not)
        import traceback
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    if "--" in sys.argv:
        sys.exit(code)
