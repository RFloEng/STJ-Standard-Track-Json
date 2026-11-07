"""The STJ Blender profile, run inside Blender: read the scene, check it, export the delivery package.

    blender -b track.blend --python tools/blender/stj_blender.py -- lint
    blender -b track.blend --python tools/blender/stj_blender.py -- export <out_dir> [name]

`lint` prints the findings and exits 1 when there is an ERROR. `export` writes <name>.stj.json (the document:
the text block `track.stj.json` with the objects applied over it) and <name>.usd (Blender's USD export with
the document embedded in customLayerData["stj"]), and refuses to export when the lint has an ERROR.
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
        objects.append(entry)
    return {"blender": bpy.app.version_string, "profile": scene.get(profile.PROFILE_PROP),
            "objects": objects,
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
    bpy.ops.wm.usd_export(filepath=str(usd_path))
    core.embed_document(doc, usd_path)
    print(f"wrote {json_path} and {usd_path}")
    return 0


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "lint":
        return lint()
    if argv[0] == "export" and len(argv) >= 2:
        return export(argv[1], argv[2] if len(argv) > 2 else "track")
    print(__doc__)
    return 2


if __name__ == "__main__":
    code = main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    sys.stdout.flush()
    if "--" in sys.argv:
        sys.exit(code)
