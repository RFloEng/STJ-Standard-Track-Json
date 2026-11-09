"""Build the reference .blend of the STJ Blender profile (spec/STJ_Blender_Profile.md).

    blender -b --factory-startup --python examples/make_blender_reference.py -- <out_dir>

Writes <out_dir>/test_ring_profile.blend: the Test Ring as the profile wants it. The reference curve is a
Bezier curve with handles, the timing gates, grid slots, a pit box with its garage and a spawn are empties,
the surfaces are materials, and the text block `track.stj.json` holds everything the scene does not (the
document without centerline, timing and grid). It uses every row of the profile that is normative, so a
translator is conformant when it round-trips this file.
"""
import copy
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parent / "tools" / "blender"))
import make_examples  # noqa: E402
import stj_core as core  # noqa: E402
import stj_profile as profile  # noqa: E402

out = Path(sys.argv[sys.argv.index("--") + 1]) if "--" in sys.argv else HERE
out.mkdir(parents=True, exist_ok=True)

# ── the document, minus what the scene carries ───────────────────────────────
doc = make_examples.test_ring()
pts = doc["reference"]["centerline"]["points"]
line = core.ReferenceLine(pts, closed=True)
doc["environment"].update({"geo_reference": {"latitude": 41.35, "longitude": 2.1, "altitude": 120.0, "vertical_datum": "EGM2008"},
                           "timezone": "Europe/Madrid", "default_time": {"date": "2026-06-20", "local_time": "15:30"}})
base = copy.deepcopy(doc)
base["environment"].pop("geo_reference")
base["environment"].pop("timezone")
base["environment"].pop("default_time")
del base["reference"]["centerline"]["points"]
base["reference"]["centerline"].pop("closed", None)
base.pop("timing")
base.pop("race")
base["timing"] = {"sectors": [{"id": "s1", "s_start": 150.0, "s_end": 420.0},
                              {"id": "s2", "s_start": 420.0, "s_end": 720.0},
                              {"id": "s3", "s_start": 720.0, "s_end": 150.0}]}

# ── a clean scene ─────────────────────────────────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene[profile.PROFILE_PROP] = profile.PROFILE_VERSION
root = bpy.data.collections.new("STJ")
scene.collection.children.link(root)


def add(obj):
    root.objects.link(obj)
    return obj


# the reference curve: a closed Bezier spline with automatic-looking handles along the polyline
cu = bpy.data.curves.new("STJ::reference::centerline", "CURVE")
cu.dimensions = "3D"
sp = cu.splines.new("BEZIER")
sp.use_cyclic_u = True
sp.bezier_points.add(len(pts) - 1)
n = len(pts)
for i, bp in enumerate(sp.bezier_points):
    prev, cur, nxt = Vector(pts[i - 1]), Vector(pts[i]), Vector(pts[(i + 1) % n])
    bp.co = cur
    tangent = (nxt - prev) / 6.0
    bp.handle_left_type = bp.handle_right_type = "FREE"
    bp.handle_left = cur - tangent
    bp.handle_right = cur + tangent
add(bpy.data.objects.new("STJ::reference::centerline", cu))


def empty(name, x, y, z, heading):
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = "ARROWS"
    e.location = (x, y, z)
    e.rotation_euler = (0.0, 0.0, heading)
    return add(e)


# the gates and slots lie on the curve Blender draws (the Bezier handles above), not on the bare polyline
tangents = [list((Vector(pts[(i + 1) % n]) - Vector(pts[i - 1])) / 2.0) for i in range(n)]
line = core.ReferenceLine(pts, closed=True, tangents=tangents)


# timing gates and splits
for name, s in (("start_finish", 150.0), ("split_1", 420.0), ("split_2", 720.0)):
    x, y, z = line.point(s)
    empty(f"STJ::timing::{name}", x, y, z, line.frame(s)[3])

# grid, pit box with garage, spawn
for i in range(4):
    s, t = 150.0 - 6.0 - 8.0 * i, (2.0 if i % 2 == 0 else -2.0)
    x, y, z = line.point(s, t)
    empty(f"STJ::grid::{i + 1}", x, y, z, line.frame(s)[3])
x, y, z = line.point(100.0, -9.0)
empty("STJ::pit::box1", x, y, z, line.frame(100.0)[3])
x, y, z = line.point(100.0, -14.0)
empty("STJ::pit::box1::garage", x, y, z, line.frame(100.0)[3])
x, y, z = line.point(40.0, 0.0)
empty("STJ::spawn::hotlap", x, y, z, line.frame(40.0)[3])

# the place (coordinates, height, time, true north) and the sun, which follows the date and time
geo = empty("STJ::geo::origin", 0.0, 0.0, 0.0, doc["environment"]["north_heading"])
geo["stj"] = {**doc["environment"]["geo_reference"], "timezone": doc["environment"]["timezone"],
              **doc["environment"]["default_time"]}
sun_dir = Vector(core.sun_direction(doc)).normalized()
sun = bpy.data.objects.new("STJ::sun::main", bpy.data.lights.new("STJ::sun::main", "SUN"))
sun.location = sun_dir * 100.0
sun.rotation_euler = sun_dir.to_track_quat("Z", "Y").to_euler()
add(sun)

# surfaces
for sid, entry in doc["surfaces"]["library"].items():
    mat = bpy.data.materials.new(f"STJ::surface::{sid}")
    mat.use_fake_user = True
    mat["stj"] = entry                          # the library entry lives on the material (profile section 4)
base["surfaces"].pop("library")
if "track_info" in doc:                         # and the track info on its own empty
    info = empty("STJ::track_info::track_info", 0.0, 0.0, 0.0, 0.0)
    info["stj"] = doc["track_info"]
    base.pop("track_info")

# the base document
text = bpy.data.texts.new(profile.BASE_TEXT)
text.write(json.dumps(base, indent=2))

path = out / "test_ring_profile.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(path))
print("wrote", path)
