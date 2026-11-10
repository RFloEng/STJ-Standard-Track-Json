"""Runs inside Blender (tests/test_blender_profile.py starts it): imports a document whose scenery is a `usd`-form
instance set (a PointInstancer in a mesh file), then reports what Blender holds and what the export keeps. Prints one JSON line.

    blender -b --factory-startup --python tests/blender_instancer_check.py -- <doc.stj.json> <out_dir>
"""
import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "blender"))
import stj_blender  # noqa: E402
import stj_profile as profile  # noqa: E402

doc_path, out_dir = (Path(a) for a in sys.argv[sys.argv.index("--") + 1:][:2])
findings = stj_blender.load_into_scene(doc_path, say=lambda m: None)
dg = bpy.context.evaluated_depsgraph_get()
pts = [o for o in bpy.data.objects if o.type == "POINTCLOUD"]
inst = [(i.object.name, [round(c, 3) for c in i.matrix_world.translation], [round(c, 3) for c in i.matrix_world.to_scale()])
        for i in dg.object_instances if i.is_instance]
result = {"pointclouds": [(o.name, [c.name for c in o.users_collection]) for o in pts],
          "instances": len(inst), "scales": [x[2] for x in inst],
          "findings": [(lvl, msg) for lvl, _p, msg in findings if lvl in ("ERROR", "WARN")],
          "layout_notes": [msg for lvl, p, msg in findings if p == "layout"]}
stj_blender.export(out_dir, "track", say=lambda m: None)
exported = json.loads((out_dir / "track.stj.json").read_text(encoding="utf-8")) if (out_dir / "track.stj.json").is_file() else None
src = json.loads(doc_path.read_text(encoding="utf-8"))
result["same_document"] = exported == src
from pxr import Usd, UsdGeom  # noqa: E402
out_stage = Usd.Stage.Open(str(out_dir / "scenery.usda"))
inst_prims = [p for p in out_stage.Traverse() if p.IsA(UsdGeom.PointInstancer)]
result["exported_instancers"] = [str(p.GetPath()) for p in inst_prims]
result["exported_count"] = len(UsdGeom.PointInstancer(inst_prims[0]).GetPositionsAttr().Get()) if inst_prims else 0
result["exported_prims"] = len(list(out_stage.Traverse()))
print("RESULT " + json.dumps(result))
