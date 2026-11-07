"""The STJ Blender profile: names, entity rules, and the step from a scene description to an STJ document.

This module does not import Blender. `stj_blender.py` reads a .blend into a *scene description* (plain
dicts, see `SCENE`), and everything the profile decides is here, so it runs and is tested anywhere:

    scene description + base document -> patch -> document        (`apply_scene`)
    scene description + document      -> findings                 (`lint_scene`)

The profile is defined in spec/STJ_Blender_Profile.md. `PROFILE_VERSION` is independent of the spec.

SCENE (what `stj_blender.read_scene` produces):
    {"blender": "5.2.2", "profile": "0.1" | None,
     "objects": [{"name", "type", "location": [x, y, z], "heading": rad, "collections": [names],
                  "cyclic": bool, "points": [...], "tangents_out": [...], "tangents_in": [...],
                  "props": {...}}],
     "materials": [{"name", "props": {...}}],
     "texts": {name: str},
     "scene_props": {...}}
"""
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stj_core as core  # noqa: E402

PROFILE_VERSION = "0.1"
BASE_TEXT = "track.stj.json"
PROFILE_PROP = "stj_blender_profile"
TESTED_BLENDER = ("5.2",)                    # major.minor the rows were probed on (LTS releases only)
ID_RE = re.compile(r"^[a-z0-9_]+$")
NAME_RE = re.compile(r"^STJ(?P<sep>::|__)(?P<category>[A-Za-z_]+?)(?P=sep)(?P<rest>.+)$")
DUP_SUFFIX = re.compile(r"\.\d{3}$")         # Blender's ".001" for a second object of the same name

# category -> (Blender types it may use, what it fills)
CATEGORIES = {
    "reference": ({"CURVE"}, "reference.centerline"),
    "timing": ({"EMPTY"}, "timing"),
    "grid": ({"EMPTY"}, "race.grid"),
    "pit": ({"EMPTY"}, "race.pit_boxes"),
    "spawn": ({"EMPTY"}, "race.spawns"),
    "surface": ({"MATERIAL"}, "surfaces.library"),
}
TIMING_LINES = ("start_finish", "start", "finish", "stop")      # the others are split points


def parse_name(name):
    """(category, id, part) of an STJ name, or None when it is not one.

    `STJ::timing::start`, `STJ__timing__start` and `STJ::timing::start.001` give ('timing', 'start', None);
    a third segment is the part: `STJ::pit::box1::garage` -> ('pit', 'box1', 'garage')."""
    m = NAME_RE.match(DUP_SUFFIX.sub("", name))
    if not m:
        return None
    parts = m.group("rest").split(m.group("sep"))
    return m.group("category"), parts[0], (parts[1] if len(parts) > 1 else None)


def stj_names(scene):
    """[(kind, item, (category, id, part))] for every object and material whose name starts with STJ."""
    out = []
    for o in scene.get("objects", []):
        if o["name"].startswith("STJ"):
            out.append(("OBJECT", o, parse_name(o["name"])))
    for m in scene.get("materials", []):
        if m["name"].startswith("STJ"):
            out.append(("MATERIAL", m, parse_name(m["name"])))
    return out


def base_document(scene):
    """The document in the text block `track.stj.json`, or None."""
    text = (scene.get("texts") or {}).get(BASE_TEXT)
    if text is None:
        return None
    import json
    return json.loads(text)


def _pose(o):
    x, y, z = o["location"]
    return {"position": [round(x, 4), round(y, 4), round(z, 4)], "heading": round(o["heading"], 6)}


def _stj_props(o):
    p = o.get("props", {}).get("stj")
    return p if isinstance(p, dict) else {}


def reference_patch(obj):
    """The `reference.centerline` of a reference curve."""
    cl = {"points": [[round(c, 4) for c in p] for p in obj["points"]]}
    if obj.get("cyclic"):
        cl["closed"] = True
    if obj.get("tangents_out"):
        cl["tangents_out"] = [[round(c, 4) for c in t] for t in obj["tangents_out"]]
        cl["tangents_in"] = [[round(c, 4) for c in t] for t in obj["tangents_in"]]
    return core.merge_patch(cl, _stj_props(obj))


def scene_patch(scene, base):
    """The patch the objects of the scene make over the base document (spec/STJ_Blender_Profile.md, §5).

    Returns (patch, findings). The reference curve is applied first, because gates are projected onto it."""
    findings = []
    patch = {}
    named = [(k, i, n) for k, i, n in stj_names(scene) if n and n[0] in CATEGORIES]
    refs = [i for k, i, n in named if n[0] == "reference"]
    if refs:
        patch["reference"] = {"centerline": reference_patch(refs[0])}
    doc = core.merge_patch(base or {}, patch)
    line = None
    try:
        if (doc.get("reference") or {}).get("centerline"):
            line = core.reference_line(doc)
    except Exception as e:  # noqa: BLE001  (a bad curve is reported by the checker, not raised)
        findings.append(("ERROR", "reference", f"the reference line cannot be built: {e}"))

    timing, splits, grid, pits, spawns = {}, [], [], {}, []
    for kind, o, (cat, ident, part) in named:
        if kind != "OBJECT" or cat in ("reference", "surface"):
            continue
        if cat == "timing":
            if line is None:
                continue
            s, t = line.project(o["location"][0], o["location"][1])
            props = _stj_props(o)
            entry = {"s": round(s, 3)}
            entry.update({k: v for k, v in props.items() if k in ("t_min", "t_max")})
            if ident in TIMING_LINES:
                timing[ident] = entry
            else:
                splits.append({"id": ident, **entry})
        elif cat == "grid":
            if ident.isdigit():
                grid.append({"position": int(ident), "pose": _pose(o)})
        elif cat == "pit":
            pit = pits.setdefault(ident, {"id": ident})
            pit["garage_pose" if part == "garage" else "pose"] = _pose(o)
        elif cat == "spawn":
            spawns.append({"id": ident, "pose": _pose(o)})
    if timing or splits:
        patch["timing"] = dict(timing)
        if splits:
            patch["timing"]["split_points"] = sorted(splits, key=lambda e: e["s"])
    race = {}
    if grid:
        race["grid"] = sorted(grid, key=lambda e: e["position"])
    if pits:
        race["pit_boxes"] = [p for p in pits.values() if "pose" in p]
    if spawns:
        race["spawns"] = spawns
    if race:
        patch["race"] = race
    return patch, findings


def apply_scene(scene, base=None):
    """The document the scene describes: the base document with the objects' patch applied over it."""
    base = base if base is not None else base_document(scene)
    patch, _ = scene_patch(scene, base)
    return core.merge_patch(base or {}, patch)


def _changed(base, patch, path=""):
    """Paths where the patch overwrites a different value in the base."""
    out = []
    if not isinstance(patch, dict):
        if base is not None and base != patch:
            out.append(path)
        return out
    for k, v in patch.items():
        out += _changed((base or {}).get(k) if isinstance(base, dict) else None, v, f"{path}.{k}" if path else k)
    return out


def lint_scene(scene, base=None):
    """Findings [(level, path, message)] for a scene description against the profile."""
    f = []
    base = base if base is not None else (base_document(scene) if (scene.get("texts") or {}).get(BASE_TEXT) else None)
    version = scene.get("profile")
    if version is None:
        f.append(("WARN", "scene", f"no scene property '{PROFILE_PROP}': the profile version is unknown (this is {PROFILE_VERSION})"))
    elif _version_tuple(version) > _version_tuple(PROFILE_VERSION):
        f.append(("ERROR", "scene", f"profile {version} is newer than this checker ({PROFILE_VERSION})"))
    bl = ".".join(str(scene.get("blender", "")).split(".")[:2])
    if bl and bl not in TESTED_BLENDER:
        f.append(("WARN", "scene", f"Blender {scene.get('blender')}: the profile rows were probed on {', '.join(TESTED_BLENDER)} (LTS) only"))
    if base is None:
        f.append(("ERROR", f"text '{BASE_TEXT}'", "no base document: the text block is missing"))

    seen = {}
    refs = []
    for kind, item, parsed in stj_names(scene):
        label = f"{kind.lower()} '{item['name']}'"
        if parsed is None:
            f.append(("ERROR", label, "starts with STJ but is not STJ::<category>::<id> (or STJ__<category>__<id>)"))
            continue
        cat, ident, part = parsed
        if cat not in CATEGORIES:
            f.append(("WARN", label, f"unknown category '{cat}': known are {', '.join(CATEGORIES)}"))
            continue
        types, _fills = CATEGORIES[cat]
        actual = "MATERIAL" if kind == "MATERIAL" else item["type"]
        if actual not in types:
            f.append(("ERROR", label, f"category '{cat}' is for {'/'.join(sorted(types))}, this is {actual}"))
        if not ID_RE.match(ident):
            f.append(("ERROR", label, f"id '{ident}' must be lowercase letters, digits and underscores"))
        key = (cat, ident, part)
        if key in seen:
            f.append(("ERROR", label, f"same STJ name as '{seen[key]}'"))
        seen[key] = item["name"]
        if cat == "reference":
            refs.append(item)
        if cat == "grid" and not ident.isdigit():
            f.append(("ERROR", label, "a grid slot is named by its position: STJ::grid::<n>"))
        if cat == "pit" and part not in (None, "garage"):
            f.append(("ERROR", label, f"unknown part '{part}': a pit box has no part or 'garage'"))
    if len(refs) > 1:
        f.append(("ERROR", "reference", f"{len(refs)} reference curves: there is one (use roads or routes for the others)"))
    has_ref = bool(refs) or bool(((base or {}).get("reference") or {}).get("centerline"))
    if not has_ref:
        f.append(("ERROR", "reference", "no reference curve and no reference.centerline in the base document"))

    if base is not None:
        patch, more = scene_patch(scene, base)
        f += more
        for path in _changed(base, patch):
            f.append(("NOTE", path, "the scene overwrites a different value in the text block (objects win)"))
        doc = core.merge_patch(base, patch)
        f += _gate_findings(scene, doc)
        library = ((doc.get("surfaces") or {}).get("library")) or {}
        for kind, item, parsed in stj_names(scene):
            if kind == "MATERIAL" and parsed and parsed[0] == "surface" and parsed[1] not in library:
                f.append(("WARN", f"material '{item['name']}'", f"surface '{parsed[1]}' is not in surfaces.library"))
    return f


def _gate_findings(scene, doc):
    out = []
    cl = (doc.get("reference") or {}).get("centerline")
    if not cl:
        return out
    try:
        line = core.reference_line(doc)
    except Exception:  # noqa: BLE001
        return out
    for kind, o, parsed in stj_names(scene):
        if kind != "OBJECT" or not parsed or parsed[0] != "timing":
            continue
        s, t = line.project(o["location"][0], o["location"][1])
        widths = core.half_widths(doc, s)
        limit = (max(widths) if widths else 20.0) + 5.0
        if abs(t) > limit:
            out.append(("WARN", f"object '{o['name']}'", f"{abs(t):.1f} m from the reference line: a timing gate belongs on the track"))
    return out


def _version_tuple(v):
    return tuple(int(p) if p.isdigit() else 0 for p in str(v).split("."))


def format_findings(findings):
    return [f"{lvl}: {where}: {msg}" for lvl, where, msg in findings]


def heading_of(matrix_x_axis):
    """Heading (rad, counter-clockwise from +X) of a world X axis [x, y, z]."""
    return math.atan2(matrix_x_axis[1], matrix_x_axis[0])
