"""Runs inside Blender (tests/test_blender_addon.py starts it): loads the built add-on from its zip, registers it,
imports a document with the operator, checks it, exports it, and prints one JSON line.

    blender -b --factory-startup --python tests/blender_addon_check.py -- <stj_track.zip> <doc.stj.json> <out_dir>
"""
import json
import sys
import tempfile
import zipfile
from pathlib import Path

import bpy

zip_path, doc_path, out_dir = (Path(a) for a in sys.argv[sys.argv.index("--") + 1:][:3])
pkgs = Path(tempfile.mkdtemp())
with zipfile.ZipFile(zip_path) as z:
    z.extractall(pkgs / "stj_track")
sys.path.insert(0, str(pkgs))

import stj_track  # noqa: E402

stj_track.register()
result = {"menus": [], "ops": {}}
result["operators"] = [hasattr(bpy.ops.stj, n) for n in ("import_track", "lint", "export_track")]
result["panel"] = hasattr(bpy.types, "STJ_PT_panel")
result["ops"]["import"] = sorted(bpy.ops.stj.import_track(filepath=str(doc_path)))
result["objects"] = sum(1 for o in bpy.data.objects if o.name.startswith("STJ::"))
result["ops"]["lint"] = sorted(bpy.ops.stj.lint())
result["panel_lines"] = len(stj_track.LAST["lines"])
result["ops"]["export"] = sorted(bpy.ops.stj.export_track(filepath=str(out_dir / "ring.stj.json")))
result["exported"] = sorted(p.name for p in out_dir.iterdir())
src = json.loads(Path(doc_path).read_text(encoding="utf-8"))
back = json.loads((out_dir / "ring.stj.json").read_text(encoding="utf-8"))
result["same_document"] = src == back
stj_track.unregister()
result["unregistered"] = not hasattr(bpy.types, "STJ_PT_panel")
print("RESULT " + json.dumps(result))
