"""Probe the Blender side of STJ v0.2: actions, speakers, rigid bodies and 16-bit images.

blender -b --factory-startup --python blend_probe_v02.py -- <out_dir> <wav_file>

Writes <out_dir>/report_v02.json and a 16-bit PNG that tools/stj_core.read_png must decode.
"""
import json
import math
import sys
import traceback
from pathlib import Path

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
out = Path(args[0])
wav = Path(args[1])
out.mkdir(parents=True, exist_ok=True)
report = {"blender": bpy.app.version_string}


def probe(name, fn):
    try:
        report[name] = fn()
    except Exception as e:  # noqa: BLE001
        report[name] = f"FAILED: {type(e).__name__}: {e}"
        traceback.print_exc()


for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
scene = bpy.context.scene


def build():
    r = {}
    # animated windmill rotor: an action on an empty
    rotor = bpy.data.objects.new("Windmill_Rotor", None)
    scene.collection.objects.link(rotor)
    rotor["stj"] = {"animated_object": "windmill", "speed_by": {"signal": "wind_speed", "curve": [[0, 0], [12, 2]]}}
    for f, a in ((1, 0.0), (25, math.pi), (49, 2 * math.pi)):
        rotor.rotation_euler = (a, 0.0, 0.0)
        rotor.keyframe_insert("rotation_euler", frame=f)
    rotor.animation_data.action.name = "rotor_spin"

    # speaker with a packed sound
    snd = bpy.data.sounds.load(str(wav))
    snd.pack()
    spk_data = bpy.data.speakers.new("PA")
    spk_data.sound = snd
    spk_data.volume = 0.6
    spk_data.distance_reference = 10.0
    spk_data.distance_max = 250.0
    spk_data.attenuation = 1.0
    spk_data.cone_angle_inner = math.radians(90)
    spk_data.cone_angle_outer = math.radians(180)
    spk_data.cone_volume_outer = 0.3
    spk = bpy.data.objects.new("STJ::audio::pa_main", spk_data)
    spk["stj"] = {"kind": "pa", "loop": True}
    scene.collection.objects.link(spk)

    # rigid-body cone
    bpy.ops.mesh.primitive_cone_add(radius1=0.18, depth=0.7)
    cone = bpy.context.active_object
    cone.name = "cone"
    bpy.ops.rigidbody.object_add()
    rb = cone.rigid_body
    rb.mass = 4.5
    rb.friction = 0.7
    rb.restitution = 0.2
    rb.collision_shape = "CYLINDER"
    r["rigid_body_shapes"] = [i.identifier for i in rb.bl_rna.properties["collision_shape"].enum_items]

    # 16-bit greyscale heightmap, saved and packed
    img = bpy.data.images.new("terrain_height", 9, 9, float_buffer=True, is_data=True)
    px = []
    for j in range(9):
        for i in range(9):
            v = (i + 9 * j) / 80.0
            px += [v, v, v, 1.0]
    img.pixels = px
    img.filepath_raw = str(out / "height16.png")
    img.file_format = "PNG"
    scene.render.image_settings.color_depth = "16"
    img.save_render(str(out / "height16.png"), scene=scene) if hasattr(img, "save_render") else img.save()
    img16 = bpy.data.images.load(str(out / "height16.png"))
    img16.pack()
    img16.use_fake_user = True
    r["png16_is_float_on_load"] = img16.is_float
    r["png16_depth_on_load"] = img16.depth
    return r


probe("build", build)
blend = out / "probe_v02.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(blend))
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.open_mainfile(filepath=str(blend))
scene = bpy.context.scene


def readback():
    r = {}
    rotor = bpy.data.objects["Windmill_Rotor"]
    r["action_name"] = rotor.animation_data.action.name if rotor.animation_data and rotor.animation_data.action else None
    r["rotor_idprop"] = rotor["stj"].to_dict()
    spk = bpy.data.objects["STJ::audio::pa_main"]
    d = spk.data
    r["speaker"] = {"volume": round(d.volume, 3), "distance_reference": d.distance_reference, "distance_max": d.distance_max,
                    "attenuation": d.attenuation, "cone_inner": round(d.cone_angle_inner, 4),
                    "cone_outer": round(d.cone_angle_outer, 4), "cone_volume_outer": round(d.cone_volume_outer, 3),
                    "sound_packed": d.sound is not None and d.sound.packed_file is not None}
    rb = bpy.data.objects["cone"].rigid_body
    r["rigid_body"] = {"mass": round(rb.mass, 3), "friction": round(rb.friction, 3), "restitution": round(rb.restitution, 3),
                       "shape": rb.collision_shape, "type": rb.type}
    r["png16_packed"] = bpy.data.images["height16.png"].packed_file is not None
    return r


probe("readback", readback)


def export():
    props = {p.identifier for p in bpy.ops.export_scene.gltf.get_rna_type().properties}
    kw = dict(filepath=str(out / "probe_v02.gltf"), export_format="GLTF_SEPARATE", export_extras=True)
    for opt in ("export_animations", "export_lights"):
        if opt in props:
            kw[opt] = True
    bpy.ops.export_scene.gltf(**kw)
    g = json.loads((out / "probe_v02.gltf").read_text(encoding="utf-8"))
    return {
        "extensionsUsed": g.get("extensionsUsed", []),
        "animations": [a.get("name") for a in g.get("animations", [])],
        "nodes": {n.get("name"): sorted(k for k in n if k not in ("name",)) for n in g.get("nodes", [])},
        "node_extras": {n.get("name"): n.get("extras") for n in g.get("nodes", []) if n.get("extras")},
        "physics_or_audio_options": sorted(p for p in props if any(k in p for k in ("physic", "audio", "sound", "speaker", "rigid"))),
    }


probe("gltf", export)
(out / "report_v02.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
print("PROBE_DONE")
