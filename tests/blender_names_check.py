"""Runs inside Blender (tests/test_blender_profile.py starts it): imports a document, then reports the names of the objects
in the mesh collections, the placeholders, and what the export writes. Prints one JSON line.

    blender -b --factory-startup --python tests/blender_names_check.py -- <doc> <out_dir>
"""
import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "blender"))
import stj_blender  # noqa: E402

doc_path, out_dir = (Path(a) for a in sys.argv[sys.argv.index("--") + 1:][:2])
findings = stj_blender.load_into_scene(doc_path, say=lambda m: None)
mesh_objects = [o.name for c in bpy.data.collections if c.name.startswith("STJ::mesh::") for o in c.all_objects]
placeholders = {o.name: [c.name for c in o.users_collection] for o in bpy.data.objects if o.get(stj_blender.PLACEHOLDER)}
worlds = {w.name: bool(w.get(stj_blender.PLACEHOLDER)) for w in bpy.data.worlds}
code = stj_blender.export(out_dir, "track", say=lambda m: None)
exported = (out_dir / "track.stj.json").read_text(encoding="utf-8") if (out_dir / "track.stj.json").is_file() else ""
print("RESULT " + json.dumps({"mesh_objects": mesh_objects, "placeholders": placeholders, "worlds": worlds, "export": code,
                              "placeholder_in_export": "Placeholder s" in exported or "stj_placeholder" in exported,
                              "findings": [(l, m) for l, _p, m in findings if l in ("ERROR", "WARN")],
                              "layout_notes": [m for l, p, m in findings if p == "layout"]}))
