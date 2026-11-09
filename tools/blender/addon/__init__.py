"""STJ Track: the Standard Track JSON Blender profile as an add-on.

File > Import > STJ track     builds the profile scene of a track (JSON, or a USD that carries the document)
File > Export > STJ track     writes <name>.stj.json and <name>.usd (and the heightmaps and meshes it names)
3D Viewport > Sidebar > STJ   imports, checks (lint) and shows the findings

The rules are in spec/STJ_Blender_Profile.md. The work is done by the modules in `lib/` (stj_blender, stj_profile,
stj_core, stj_ground, ground_bake), which also run from the command line without this add-on.
"""
import sys
from pathlib import Path

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

_LIB = str(Path(__file__).resolve().parent / "lib")

LAST = {"title": "", "lines": [], "errors": 0}          # what the panel shows: the last import, check or export


def _modules():
    if _LIB not in sys.path:
        sys.path.insert(0, _LIB)
    import stj_blender
    return stj_blender


def _collect(title, run):
    """Run `run(say)` and keep what it said for the panel. Returns (result, lines)."""
    lines = []
    result = run(lines.append)
    LAST["title"], LAST["lines"] = title, lines
    LAST["errors"] = sum(1 for line in lines if line.startswith("ERROR"))
    return result, lines


def _report(op, lines, ok_message):
    errors = [x for x in lines if x.startswith("ERROR")]
    if errors:
        op.report({"ERROR"}, f"{len(errors)} error(s): {errors[0]}")
    else:
        op.report({"INFO"}, ok_message)


class STJ_OT_import(bpy.types.Operator, ImportHelper):
    bl_idname = "stj.import_track"
    bl_label = "Import STJ track"
    bl_description = "Build the STJ profile scene of a track in this file, replacing the scene"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json;*.usd;*.usda;*.usdc;*.usdz", options={"HIDDEN"})

    def execute(self, context):
        try:
            sb = _modules()
            _result, lines = _collect("Import", lambda say: sb.load_into_scene(self.filepath, say=say, reset=False))
        except Exception as e:  # noqa: BLE001
            self.report({"ERROR"}, f"{type(e).__name__}: {e}")
            return {"CANCELLED"}
        _report(self, lines, f"Imported {Path(self.filepath).name}")
        return {"FINISHED"}


class STJ_OT_lint(bpy.types.Operator):
    bl_idname = "stj.lint"
    bl_label = "Check against the STJ profile"
    bl_description = "Check the scene against the STJ Blender profile and list the findings"

    def execute(self, context):
        try:
            sb = _modules()
            _result, lines = _collect("Check", lambda say: sb.lint(say=say))
        except Exception as e:  # noqa: BLE001
            self.report({"ERROR"}, f"{type(e).__name__}: {e}")
            return {"CANCELLED"}
        _report(self, lines, lines[-1] if lines else "Checked")
        return {"FINISHED"}


class STJ_OT_export(bpy.types.Operator, ExportHelper):
    bl_idname = "stj.export_track"
    bl_label = "Export STJ track"
    bl_description = "Write the track document (<name>.stj.json), the USD that carries it and the files it names"
    filename_ext = ".stj.json"
    filter_glob: StringProperty(default="*.stj.json;*.json", options={"HIDDEN"})

    def execute(self, context):
        path = Path(self.filepath)
        name = path.name
        for suffix in (".stj.json", ".json"):
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                break
        try:
            sb = _modules()
            code, lines = _collect("Export", lambda say: sb.export(str(path.parent), name or "track", say=say))
        except Exception as e:  # noqa: BLE001
            self.report({"ERROR"}, f"{type(e).__name__}: {e}")
            return {"CANCELLED"}
        if code:
            self.report({"ERROR"}, "Not exported: the scene has errors (see the STJ panel)")
            return {"CANCELLED"}
        _report(self, lines, f"Exported {name}")
        return {"FINISHED"}


class STJ_PT_panel(bpy.types.Panel):
    bl_label = "STJ Track"
    bl_idname = "STJ_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "STJ"

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("stj.import_track", icon="IMPORT")
        col.operator("stj.lint", icon="CHECKMARK")
        col.operator("stj.export_track", icon="EXPORT")
        if LAST["lines"]:
            box = self.layout.box()
            box.label(text=LAST["title"] + (f": {LAST['errors']} error(s)" if LAST["errors"] else ""),
                      icon="ERROR" if LAST["errors"] else "INFO")
            for line in LAST["lines"][-12:]:
                box.label(text=line[:90])


def _menu_import(self, _context):
    self.layout.operator(STJ_OT_import.bl_idname, text="STJ track (.stj.json, .usd)")


def _menu_export(self, _context):
    self.layout.operator(STJ_OT_export.bl_idname, text="STJ track (.stj.json + .usd)")


CLASSES = (STJ_OT_import, STJ_OT_lint, STJ_OT_export, STJ_PT_panel)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)
    bpy.types.TOPBAR_MT_file_export.append(_menu_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(_menu_export)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    if _LIB in sys.path:
        sys.path.remove(_LIB)
