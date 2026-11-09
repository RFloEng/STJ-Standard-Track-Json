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
    "geo": ({"EMPTY"}, "environment.geo_reference, north_heading, timezone, default_time"),
    "sun": ({"LIGHT"}, "environment.lighting.sun.direction"),
    "mesh": ({"COLLECTION"}, "geometry.meshes"),
    "road": ({"CURVE"}, "roads"),
    "junction": ({"EMPTY"}, "junctions"),
    "camera": ({"CAMERA"}, "cameras.sets"),
    "edge": ({"CURVE"}, "edges"),
    "marking": ({"CURVE"}, "markings"),
    "line": ({"CURVE"}, "race.racing_lines"),
    "structure": ({"EMPTY"}, "structures"),
    "animated": ({"EMPTY"}, "animated_objects"),
    "prototype": ({"EMPTY"}, "scenery.prototypes"),
    "emitter": ({"EMPTY"}, "audio.emitters"),
    "crowd": ({"EMPTY"}, "scenery.crowds"),
    "instance": ({"MESH"}, "scenery.instances"),
    "building": ({"CURVE"}, "buildings"),
    "area": ({"CURVE"}, "areas"),
    "terrain": ({"MESH"}, "geometry.terrain, geometry.terrains"),
    "water": ({"EMPTY", "CURVE"}, "water.bodies"),
    "scatter": ({"EMPTY"}, "scenery.scatter"),
    "sector": ({"EMPTY"}, "marshals.sectors"),
    "post": ({"EMPTY"}, "marshals.posts"),
    "marshal_vehicle": ({"EMPTY"}, "marshals.vehicles"),
    "restricted": ({"EMPTY"}, "marshals.restricted_zones"),
    "audio_zone": ({"EMPTY"}, "audio.zones"),
    "probe": ({"EMPTY"}, "environment.probes"),
    "service": ({"CURVE"}, "race.service_areas"),
    "ground_layer": ({"EMPTY"}, "ground.layers"),
    "ground_material": ({"EMPTY"}, "ground.materials"),
    "sky": ({"EMPTY"}, "environment.sky"),
    "screen": ({"EMPTY"}, "screens"),
    "chunk": ({"EMPTY"}, "geometry.chunks"),
    "tiles": ({"EMPTY"}, "geometry.tiles"),
    "dynamic": ({"EMPTY"}, "dynamic"),
}
RING_KEY = {"building": "footprint", "area": "polygon"}        # the field of the entry that a closed curve holds
# records that live in the scene as an empty whose `stj` property is the entry: category -> (path, "list" | "dict")
RECORDS = {"structure": ("structures", "list"), "animated": ("animated_objects", "list"),
           "prototype": ("scenery.prototypes", "dict"), "emitter": ("audio.emitters", "list"),
           "crowd": ("scenery.crowds", "list"),
           "water": ("water.bodies", "list"), "scatter": ("scenery.scatter", "list"),
           "sector": ("marshals.sectors", "list"), "post": ("marshals.posts", "list"),
           "marshal_vehicle": ("marshals.vehicles", "list"), "restricted": ("marshals.restricted_zones", "list"),
           "audio_zone": ("audio.zones", "list"), "probe": ("environment.probes", "list"),
           "service": ("race.service_areas", "list"),
           "ground_layer": ("ground.layers", "dict"), "ground_material": ("ground.materials", "list_noid"),
           "sky": ("environment.sky", "object"), "screen": ("screens", "list"),
           "chunk": ("geometry.chunks", "list"), "tiles": ("geometry.tiles", "object"),
           "dynamic": ("dynamic", "object")}
# records that are a closed curve when they have the ring: category -> (field of the entry, numbers per point)
RECORD_RING = {"water": ("outline", 2), "service": ("polygon", 3)}
# records that sit at their `position` (shown there; a moved empty writes the new position)
AT_POSITION = {"emitter": "position", "probe": "position", "post": "position", "chunk": "origin"}
HANDLED = ("reference", "surface", "geo", "sun", "road", "junction", "camera", "edge", "marking", "line", "instance", "building", "area", "terrain") + tuple(RECORDS)
INTERNAL = ("_i", "_set", "_shared", "_grid", "_h", "_many", "_cols")        # keys of an object's `stj` property that the exporter reads and does not write
MESH_ROLES = ("visual", "collision", "lod", "decal")
GEO_KEYS = ("latitude", "longitude", "altitude", "proj", "vertical_datum")      # on the geo origin's `stj` property
SUN_TOLERANCE = math.radians(0.5)        # a sun within this of the computed one follows date and time
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
    for c in scene.get("collections", []):
        if parse_name(c["name"]):            # the plain collections of the layout (STJ, STJ_Collision) are not entities
            out.append(("COLLECTION", c, parse_name(c["name"])))
    return out


def base_document(scene):
    """The document in the text block `track.stj.json`, or None."""
    text = (scene.get("texts") or {}).get(BASE_TEXT)
    if text is None:
        return None
    import json
    return json.loads(text)


def world_pose(p, line):
    """(x, y, z, heading) of a pose, or None when it has keys a scene cannot hold."""
    if set(p) <= {"position", "heading"} and "position" in p and "heading" in p:
        x, y, z = _vec3(p["position"])
        return x, y, z, p["heading"]
    if set(p) <= {"s", "t", "heading_offset"} and line is not None and "s" in p and "t" in p:
        x, y, z = line.point(p["s"], p["t"])
        return x, y, z, line.frame(p["s"])[3] + p.get("heading_offset", 0.0)
    return None


def _pose(o, line=None):
    """The pose of an empty. A pose imported from a document is kept in the object's `stj.pose`, and written
    back as it was (an `s`, `t` pose stays one) while the empty is still where that pose puts it."""
    x, y, z = o["location"]
    stored = _stj_props(o).get("pose")
    if isinstance(stored, dict):
        w = world_pose(stored, line)
        if w is not None and math.dist((x, y, z), w[:3]) < 0.01 and                 abs(math.atan2(math.sin(o["heading"] - w[3]), math.cos(o["heading"] - w[3]))) < 1e-4:
            return stored
    return {"position": [round(x, 4), round(y, 4), round(z, 4)], "heading": round(o["heading"], 6)}


def _kept_position(stored, o):
    """A stored position while the empty is still there, otherwise the empty's."""
    x, y, z = o["location"]
    if stored is not None and math.dist((x, y, z), stored) < 0.01:
        return stored
    return [round(x, 4), round(y, 4), round(z, 4)]


def _look_at(o, stored, pos):
    """The look-at point: the stored one while the camera still faces it, else the point on its axis at the
    stored distance."""
    f = o["forward"]
    to = [stored[i] - pos[i] for i in range(3)]
    d = math.sqrt(sum(c * c for c in to)) or 1.0
    if _angle_between(f, to) < math.radians(0.5):
        return stored
    n = math.sqrt(sum(c * c for c in f)) or 1.0
    return [round(pos[i] + f[i] / n * d, 4) for i in range(3)]


def _wrap(ds, line):
    """A station difference, wrapped to +-half the lap on a closed line."""
    if line.closed and line.length:
        return (ds + line.length / 2.0) % line.length - line.length / 2.0
    return ds


def _stj_props(o):
    p = o.get("props", {}).get("stj")
    return p if isinstance(p, dict) else {}


def centerline_geometry(obj):
    """The `points`, `closed` and Hermite tangents of a curve object."""
    cl = {"points": [[round(c, 4) for c in p] for p in obj["points"]]}
    if obj.get("cyclic"):
        cl["closed"] = True
    if obj.get("tangents_out"):
        out = [[round(c, 4) for c in t] for t in obj["tangents_out"]]
        if _stj_props(obj).get("_shared"):          # the document gave one tangent per point
            cl["tangents"] = out
        else:
            cl["tangents_out"] = out
            cl["tangents_in"] = [[round(c, 4) for c in t] for t in obj["tangents_in"]]
    return cl


def reference_patch(obj):
    """The `reference.centerline` of a reference curve."""
    return core.merge_patch(centerline_geometry(obj), _entity(obj))


def terrain_hash(heights):
    """A fingerprint of the heights as the mesh holds them (float32), to tell whether they were edited."""
    import hashlib
    import struct
    return hashlib.sha1(struct.pack(f"<{len(heights)}f", *heights)).hexdigest()[:16]


def terrain_state(o):
    """What a terrain mesh says: the grid size, the heights, whether they were edited since import."""
    props = _stj_props(o)
    hm = props.get("heightmap") or {}
    grid = props.get("_grid") or hm.get("size")
    zs = [p[2] for p in o.get("points") or []]
    edited = props.get("_h") != terrain_hash(zs) if zs else False
    return {"grid": grid, "heights": zs, "edited": edited, "heightmap": hm}


def terrain_entry(o, ident, many):
    """(entry, file) of a terrain mesh. file is None while the heights are as imported, otherwise
    (uri, bytes): the heightmap written again from the mesh, in the format the entry names."""
    st = terrain_state(o)
    entry = _entity(o)
    if many:
        entry = {"id": ident, **entry}
    if not st["edited"] or not st["grid"] or len(st["heights"]) != st["grid"][0] * st["grid"][1]:
        return entry, None             # untouched, or a mesh that lint rejects
    import struct
    hm = dict(st["heightmap"])
    nx, ny = st["grid"]
    zs = st["heights"]
    if hm.get("format") == "raw_f32":
        data = struct.pack(f"<{len(zs)}f", *zs)
    else:
        lo, hi = round(min(zs), 4), round(max(zs), 4)
        if hi <= lo:
            hi = lo + 1.0
        values = [min(65535, max(0, round((z - lo) / (hi - lo) * 65535))) for z in zs]
        data = core.png_bytes(nx, ny, values, 1, 16)
        hm.update({"height_min": lo, "height_max": hi})
    hm["nodata"] = None                 # the mesh holds a height everywhere
    entry["heightmap"] = hm
    return entry, (hm["uri"], data)


def terrain_objects(scene):
    found = [(i, n) for k, i, n in stj_names(scene) if k == "OBJECT" and n and n[0] == "terrain"]
    many = len(found) > 1 or any(_stj_props(i).get("_many") for i, _n in found)
    return found, many


def terrain_files(scene):
    """[(uri, bytes)] of the heightmaps that have to be written again because the mesh was edited."""
    found, many = terrain_objects(scene)
    files = [terrain_entry(i, n[1], many)[1] for i, n in found]
    return [f for f in files if f]


def _order(o):
    return _stj_props(o).get("_i", 1e9)


def _entity(o, drop=()):
    """The fields an object's `stj` property carries for its entity, without the internal keys."""
    return {k: v for k, v in _stj_props(o).items() if k not in INTERNAL and k not in drop}


def road_entry(o, ident):
    props = _entity(o, drop=("centerline",))
    extras = _stj_props(o).get("centerline") or {}
    return {"id": ident, **props, "centerline": core.merge_patch(centerline_geometry(o), extras)}


def edge_entry(o, ident, line, doc=None):
    """An edge from its object: the stored fields, unless the curve was moved, then side, range and offset
    from the curve."""
    stored = _entity(o)
    entry = {"id": ident, **stored}
    pts = o.get("points") or []
    regen = edge_points(stored, line, doc) if line is not None else None
    if line is None or not pts or regen is None or (len(regen) == len(pts) and
            all(math.dist(a, b) < 0.05 for a, b in zip(regen, pts))):
        return entry
    proj = [line.project(p[0], p[1]) for p in pts]
    entry["s_start"] = round(proj[0][0], 3)
    entry["s_end"] = round(proj[-1][0], 3)
    t = sum(q[1] for q in proj) / len(proj)
    entry["t"] = round(t, 3)
    entry["side"] = "left" if t >= 0 else "right"
    return entry


def edge_t(edge, line, doc=None):
    """Lateral offset of an edge's inner side: `t`, or the road edge on its side."""
    if "t" in edge:
        return edge["t"]
    w = core.half_widths(doc, edge["s_start"]) if doc is not None else None
    if w is None:
        return 0.0
    return w[0] if edge.get("side") == "left" else -w[1]


def edge_points(edge, line, doc=None, step=5.0):
    """The points of an edge's curve along the reference line, or None."""
    if line is None or "s_start" not in edge or "s_end" not in edge:
        return None
    a, b = edge["s_start"], edge["s_end"]
    span = (b - a) % line.length if line.closed and b < a else b - a
    n = max(1, int(math.ceil(span / step)))
    t = edge_t(edge, line, doc)
    return [[round(c, 4) for c in line.point((a + span * k / n) % line.length if line.closed else a + span * k / n, t)]
            for k in range(n + 1)]


def marking_points(m, doc, step=5.0):
    """The curve of a marking along its road: a line at `t`, or the four corners of a patch. None when it
    cannot be drawn (no road, no range)."""
    line = core.road_line(doc, m.get("road", "reference"))
    if line is None or "s_start" not in m or "s_end" not in m:
        return None
    a, b = m["s_start"], m["s_end"]
    span = (b - a) % line.length if line.closed and b < a else b - a

    def at(k, t):
        s = a + span * k
        return [round(c, 4) for c in line.point(s % line.length if line.closed else s, t)]
    if "t" in m:
        n = max(1, int(math.ceil(span / step)))
        return [at(k / n, m["t"]) for k in range(n + 1)]
    if "t_min" in m and "t_max" in m:
        return [at(0, m["t_min"]), at(1, m["t_min"]), at(1, m["t_max"]), at(0, m["t_max"])]
    return None


def marking_entry(o, ident, doc):
    """A marking from its object: the stored fields, unless the curve was moved, then range and offsets are
    read from the curve."""
    stored = _entity(o)
    entry = {"id": ident, **stored}
    pts = o.get("points") or []
    regen = marking_points(stored, doc)
    line = core.road_line(doc, stored.get("road", "reference"))
    if line is None or not pts or regen is None or (len(regen) == len(pts) and
            all(math.dist(a, b) < 0.05 for a, b in zip(regen, pts))):
        return entry
    proj = [line.project(p[0], p[1]) for p in pts]
    entry["s_start"] = round(min(q[0] for q in proj) if "t" not in stored else proj[0][0], 3)
    entry["s_end"] = round(max(q[0] for q in proj) if "t" not in stored else proj[-1][0], 3)
    if "t" in stored:
        entry["t"] = round(sum(q[1] for q in proj) / len(proj), 3)
    else:
        entry["t_min"] = round(min(q[1] for q in proj), 3)
        entry["t_max"] = round(max(q[1] for q in proj), 3)
    return entry


def _angle_between(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return math.acos(max(-1.0, min(1.0, dot / (na * nb)))) if na and nb else 0.0


def _environment_patch(named, base, patch):
    """The place, the north and the sun that the geo origin and the sun light give (spec/STJ_Blender_Profile.md §4).

    North heading is written only when it differs from the document's (or from +Y, when the document has none),
    and the sun direction only when the sun has been moved off the one the date and time give."""
    env = {}
    geos = [i for k, i, n in named if k == "OBJECT" and n[0] == "geo"]
    suns = [i for k, i, n in named if k == "OBJECT" and n[0] == "sun"]
    if geos:
        o = geos[0]
        props = _stj_props(o)
        geo = {k: props[k] for k in GEO_KEYS if k in props}
        if geo:
            env["geo_reference"] = geo
        if "timezone" in props:
            env["timezone"] = props["timezone"]
        time = {k: props[k] for k in ("date", "local_time") if k in props}
        if time:
            env["default_time"] = time
        have = ((base or {}).get("environment") or {}).get("north_heading")
        want = have if have is not None else math.pi / 2
        diff = math.atan2(math.sin(o["heading"] - want), math.cos(o["heading"] - want))
        if abs(diff) > 1e-5:
            env["north_heading"] = round(o["heading"], 6)
    if suns and suns[0].get("direction"):
        merged = core.merge_patch(base or {}, dict(patch, environment=env))
        d = suns[0]["direction"]
        ref = core.sun_direction(merged)
        if ref is None or _angle_between(d, ref) > SUN_TOLERANCE:
            n = math.sqrt(sum(c * c for c in d))
            env.setdefault("lighting", {})["sun"] = {"direction": [round(c / n, 6) for c in d]}
    return env


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
    named.sort(key=lambda x: _order(x[1]) if x[0] == "OBJECT" else 1e9)
    for kind, o, (cat, ident, part) in named:
        if kind != "OBJECT" or cat in HANDLED:
            continue
        if cat == "timing":
            if line is None:
                continue
            s, t = line.project(o["location"][0], o["location"][1])
            props = _stj_props(o)
            stored = props.get("s")
            same = stored is not None and abs(_wrap(s - stored, line)) < 0.05      # the gate has not been moved
            entry = {"s": stored if same else round(s, 3)}
            entry.update({k: v for k, v in props.items() if k in ("t_min", "t_max")})
            if ident in TIMING_LINES:
                timing[ident] = entry
            else:
                splits.append({"id": ident, **entry})
        elif cat == "grid":
            if ident.isdigit():
                grid.append({"position": int(ident), "pose": _pose(o, line)})
        elif cat == "pit":
            pit = pits.setdefault(ident, {"id": ident})
            pit["garage_pose" if part == "garage" else "pose"] = _pose(o, line)
        elif cat == "spawn":
            spawns.append({"id": ident, "pose": _pose(o, line)})
    def objs(cat):
        return sorted([(i, n) for k, i, n in named if k == "OBJECT" and n[0] == cat], key=lambda x: (_order(x[0]), x[0]["name"]))

    roads = objs("road")
    if roads:
        patch["roads"] = [road_entry(o, n[1]) for o, n in roads]
    junctions = objs("junction")
    if junctions:
        patch["junctions"] = [{"id": n[1], **_entity(o)} for o, n in junctions]
    edges = objs("edge")
    if edges:
        patch["edges"] = [edge_entry(o, n[1], line, doc) for o, n in edges]
    marks = objs("marking")
    if marks:
        now = core.merge_patch(doc, patch)
        patch["markings"] = [marking_entry(o, n[1], now) for o, n in marks]
    cams = objs("camera")
    if cams:
        sets = {}
        for o, (_c, set_id, cam_id) in cams:
            if cam_id is None:
                continue
            cam = _entity(o)
            pos = cam.pop("position", None)
            x, y, z = o["location"]
            if pos is None or math.dist((x, y, z), pos) >= 0.01:
                pos = [round(x, 4), round(y, 4), round(z, 4)]
            entry = {"id": cam_id, **cam, "position": pos}
            if "look_at" in cam and o.get("forward"):
                entry["look_at"] = _look_at(o, cam["look_at"], pos)
            st = sets.setdefault(set_id, {"id": set_id, **(_stj_props(o).get("_set") or {}), "cameras": []})
            st["cameras"].append(entry)
        patch["cameras"] = {"sets": list(sets.values())}
    for cat, (path, shape) in RECORDS.items():
        found = objs(cat)
        if not found:
            continue
        if shape == "list":
            value = []
            for o, n in found:
                entry = {"id": n[1], **_entity(o)}
                if cat == "water" and o["type"] == "CURVE" and "_cols" in _stj_props(o):
                    cols = _stj_props(o)["_cols"]              # width and depth per point; the last ones carry on
                    entry["path"] = [[round(c, 4) for c in p] + list(cols[min(k, len(cols) - 1)])
                                     for k, p in enumerate(o["points"])]
                elif cat in RECORD_RING and o["type"] == "CURVE":
                    key, dim = RECORD_RING[cat]
                    entry[key] = [[round(c, 4) for c in p[:dim]] for p in o["points"]]
                if cat in AT_POSITION and AT_POSITION[cat] in entry:
                    entry[AT_POSITION[cat]] = _kept_position(entry[AT_POSITION[cat]], o)
                value.append(entry)
        elif shape == "list_noid":
            value = [_entity(o) for o, n in found]
        elif shape == "object":
            value = _entity(found[0][0])
        else:
            value = {n[1]: _entity(o) for o, n in found}
        node = patch
        *parents, leaf = path.split(".")
        for key in parents:
            node = node.setdefault(key, {})
        node[leaf] = value
    for cat, path in (("building", "buildings"), ("area", "areas")):
        found = objs(cat)
        if found:
            patch[path] = [{"id": n[1], **_entity(o), RING_KEY[cat]: [[round(p[0], 4), round(p[1], 4)] for p in o["points"]]}
                           for o, n in found]
    found, many = terrain_objects(scene)
    if found:
        entries = [terrain_entry(i, n[1], many)[0] for i, n in found]
        patch.setdefault("geometry", {})["terrains" if many else "terrain"] = entries if many else entries[0]
    sets = objs("instance")
    if sets:
        value = []
        for o, n in sets:
            pts, heads, scales = o.get("points") or [], o.get("headings") or [], o.get("scales") or []
            rows = []
            for k, p in enumerate(pts):
                row = [round(p[0], 4), round(p[1], 4), round(p[2], 4), round(heads[k] if k < len(heads) else 0.0, 5)]
                if k < len(scales) and scales[k] > 0:
                    row.append(round(scales[k], 5))
                rows.append(row)
            value.append({**_entity(o), "transforms": rows})
        patch.setdefault("scenery", {})["instances"] = value
    meshes = [(i, n) for k, i, n in named if k == "COLLECTION" and n[0] == "mesh"]
    if meshes:
        entries = []
        for coll, (_cat, ident, _part) in meshes:
            props = dict(_stj_props(coll))
            uri = props.pop("uri", f"{ident}.usd")
            entries.append({"id": ident, "uri": uri, **props})
        patch.setdefault("geometry", {})["meshes"] = entries
    env = _environment_patch(named, base, patch)
    if env:
        patch["environment"] = core.merge_patch(patch.get("environment") or {}, env)
    if timing or splits:
        patch["timing"] = dict(timing)
        if splits:
            patch["timing"]["split_points"] = sorted(splits, key=lambda e: e["s"])
    race = {}
    lines = objs("line")
    if lines:
        race["racing_lines"] = []
        for o, n in lines:
            entry = {"id": n[1], **_entity(o), "points": [[round(c, 4) for c in p] for p in o["points"]]}
            if o.get("cyclic"):
                entry["closed"] = True
            race["racing_lines"].append(entry)
    if grid:
        race["grid"] = sorted(grid, key=lambda e: e["position"])
    if pits:
        race["pit_boxes"] = [p for p in pits.values() if "pose" in p]
    if spawns:
        race["spawns"] = spawns
    if race:
        patch["race"] = core.merge_patch(patch.get("race") or {}, race)
    return patch, findings


def apply_scene(scene, base=None):
    """The document the scene describes: the base document with the objects' patch applied over it."""
    base = base if base is not None else base_document(scene)
    patch, _ = scene_patch(scene, base)
    return core.merge_patch(base or {}, patch)


# ── document -> scene description (import) ──────────────────────────────────

GATE_KEYS = {"s", "t_min", "t_max"}


def _vec3(v):
    return [float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0]


def scene_from_document(doc, base_dir=None):
    """The scene description of a document (the inverse of `apply_scene`), and so what an importer builds.

    The reference curve, the timing lines and splits, the grid, the pit boxes and the spawns become objects;
    each surface of the library becomes a material. What becomes an object is removed from the document in
    the text block `track.stj.json`, which keeps the rest. Data an object cannot hold (a split with a name, a
    pose with extra keys, a timing line given by two end points) stays in the text block instead."""
    import copy
    import json
    base = copy.deepcopy(doc)
    objects = []
    line = None

    def obj(name, otype="EMPTY", location=(0.0, 0.0, 0.0), heading=0.0, props=None, **more):
        entry = {"name": name, "type": otype, "location": [float(c) for c in location], "heading": float(heading),
                 "collections": ["STJ"], "props": props or {}}
        entry.update(more)
        objects.append(entry)

    cl = (base.get("reference") or {}).get("centerline")
    if isinstance(cl, dict) and cl.get("points"):
        extra = {}
        t_out = cl.get("tangents_out") or cl.get("tangents")
        t_in = cl.get("tangents_in") or t_out
        if t_out:
            extra = {"tangents_out": [_vec3(t) for t in t_out], "tangents_in": [_vec3(t) for t in t_in]}
        obj("STJ::reference::centerline", "CURVE", cyclic=bool(cl.get("closed")),
            points=[_vec3(p) for p in cl["points"]], props=({"stj": {**({"_shared": True} if "tangents" in cl else {}),
                            **({"closed": False} if cl.get("closed") is False else {})}}
                   if ("tangents" in cl or cl.get("closed") is False) else {}), **extra)
        line = core.reference_line(doc)
        for key in ("points", "closed", "tangents", "tangents_out", "tangents_in"):
            cl.pop(key, None)

    def pose_of(p):
        return world_pose(p, line)

    def gate(name, tl):
        x, y, z = line.point(tl["s"])
        obj(f"STJ::timing::{name}", location=(x, y, z), heading=line.frame(tl["s"])[3], props={"stj": dict(tl)})

    timing = base.get("timing")
    if isinstance(timing, dict) and line is not None:
        for key in TIMING_LINES:
            tl = timing.get(key)
            if isinstance(tl, dict) and "s" in tl and set(tl) <= GATE_KEYS:
                gate(key, tl)
                del timing[key]
        splits = timing.get("split_points")
        if splits and all(isinstance(e, dict) and "s" in e and set(e) <= GATE_KEYS | {"id"} and
                          ID_RE.match(str(e.get("id", ""))) and "__" not in e["id"] and e["id"] not in TIMING_LINES
                          for e in splits):
            for e in splits:
                gate(e["id"], e)
            del timing["split_points"]
        if not timing:
            del base["timing"]

    race = base.get("race")
    if isinstance(race, dict):
        grid = race.get("grid")
        if grid and all(set(e) <= {"position", "pose"} and pose_of(e["pose"]) for e in grid):
            for e in grid:
                x, y, z, h = pose_of(e["pose"])
                obj(f"STJ::grid::{e['position']}", location=(x, y, z), heading=h, props={"stj": {"pose": e["pose"]}})
            del race["grid"]
        boxes = race.get("pit_boxes")
        if boxes and all(set(e) <= {"id", "pose", "garage_pose"} and ID_RE.match(e["id"]) and "__" not in e["id"] and
                         pose_of(e["pose"]) and (("garage_pose" not in e) or pose_of(e["garage_pose"])) for e in boxes):
            for e in boxes:
                x, y, z, h = pose_of(e["pose"])
                obj(f"STJ::pit::{e['id']}", location=(x, y, z), heading=h, props={"stj": {"pose": e["pose"]}})
                if "garage_pose" in e:
                    x, y, z, h = pose_of(e["garage_pose"])
                    obj(f"STJ::pit::{e['id']}::garage", location=(x, y, z), heading=h, props={"stj": {"pose": e["garage_pose"]}})
            del race["pit_boxes"]
        rlines = race.get("racing_lines")
        if rlines and all(isinstance(e, dict) and ID_RE.match(str(e.get("id", ""))) and "__" not in e["id"]
                          and isinstance(e.get("points"), list) and len(e["points"]) >= 2 for e in rlines):
            for i, e in enumerate(rlines):
                obj(f"STJ::line::{e['id']}", "CURVE", cyclic=bool(e.get("closed")), points=[_vec3(p) for p in e["points"]],
                    props={"stj": {**{k: v for k, v in e.items() if k not in ("id", "points")}, "_i": i}})
            del race["racing_lines"]
        spawns = race.get("spawns")
        if spawns and all(set(e) <= {"id", "pose"} and ID_RE.match(e["id"]) and "__" not in e["id"] and
                          pose_of(e["pose"]) for e in spawns):
            for e in spawns:
                x, y, z, h = pose_of(e["pose"])
                obj(f"STJ::spawn::{e['id']}", location=(x, y, z), heading=h, props={"stj": {"pose": e["pose"]}})
            del race["spawns"]
        if not race:
            del base["race"]

    env = base.get("environment")
    if isinstance(env, dict):
        geo = env.get("geo_reference") if isinstance(env.get("geo_reference"), dict) else {}
        time = env.get("default_time") if isinstance(env.get("default_time"), dict) else {}
        place = {k: geo[k] for k in GEO_KEYS if k in geo}
        place.update({k: env[k] for k in ("timezone",) if k in env})
        place.update({k: time[k] for k in ("date", "local_time") if k in time})
        if (place or "north_heading" in env) and set(geo) <= set(GEO_KEYS) and set(time) <= {"date", "local_time"}:
            obj("STJ::geo::origin", heading=env.get("north_heading", math.pi / 2), props={"stj": place} if place else {})
            for key in ("geo_reference", "timezone", "default_time"):
                env.pop(key, None)
            if not env:
                del base["environment"]
    direction = core.sun_direction(doc)
    if direction is not None:
        n = math.sqrt(sum(c * c for c in direction))
        direction = [c / n for c in direction]
        obj("STJ::sun::main", "LIGHT", location=[100.0 * c for c in direction], direction=direction, light_type="SUN")

    def geometry_of(cl):
        """(object fields, extras) of a centerline: the curve the object holds, and what stays in its property."""
        t_out = cl.get("tangents_out") or cl.get("tangents")
        t_in = cl.get("tangents_in") or t_out
        more = {"tangents_out": [_vec3(t) for t in t_out], "tangents_in": [_vec3(t) for t in t_in]} if t_out else {}
        extras = {k: v for k, v in cl.items() if k not in ("points", "closed", "tangents", "tangents_out", "tangents_in")}
        if cl.get("closed") is False:
            extras["closed"] = False                    # written as given, not left out
        return {"cyclic": bool(cl.get("closed")), "points": [_vec3(p) for p in cl["points"]], **more}, extras

    roads = base.get("roads")
    if roads and all(isinstance(r, dict) and ID_RE.match(str(r.get("id", ""))) and "__" not in r["id"] and
                     isinstance(r.get("centerline"), dict) and r["centerline"].get("points") for r in roads):
        for i, r in enumerate(roads):
            geo_, extras = geometry_of(r["centerline"])
            stj = {k: v for k, v in r.items() if k not in ("id", "centerline")}
            stj["_i"] = i
            if extras:
                stj["centerline"] = extras
            if "tangents" in r["centerline"]:
                stj["_shared"] = True
            obj(f"STJ::road::{r['id']}", "CURVE", props={"stj": stj}, **geo_)
        del base["roads"]

    junctions = base.get("junctions")
    if junctions and all(isinstance(j, dict) and ID_RE.match(str(j.get("id", ""))) and "__" not in j["id"] for j in junctions):
        for i, j in enumerate(junctions):
            try:
                x, y, z = core.joint_point(doc, j)[:3]
            except Exception:  # noqa: BLE001  (a junction whose roads are missing is the validator's finding)
                x = y = z = 0.0
            obj(f"STJ::junction::{j['id']}", location=(x, y, z), props={"stj": {**{k: v for k, v in j.items() if k != "id"}, "_i": i}})
        del base["junctions"]

    edges = base.get("edges")
    if edges and line is not None and all(isinstance(e, dict) and ID_RE.match(str(e.get("id", ""))) and "__" not in e["id"]
                                          and edge_points(e, line, doc) for e in edges):
        for i, e in enumerate(edges):
            obj(f"STJ::edge::{e['id']}", "CURVE", cyclic=False, points=edge_points(e, line, doc),
                props={"stj": {**{k: v for k, v in e.items() if k != "id"}, "_i": i}})
        del base["edges"]

    marks = base.get("markings")
    if marks and all(isinstance(m, dict) and ID_RE.match(str(m.get("id", ""))) and "__" not in m["id"]
                     and marking_points(m, doc) for m in marks):
        for i, m in enumerate(marks):
            obj(f"STJ::marking::{m['id']}", "CURVE", cyclic="t" not in m, points=marking_points(m, doc),
                props={"stj": {**{k: v for k, v in m.items() if k != "id"}, "_i": i}})
        del base["markings"]

    sets = (base.get("cameras") or {}).get("sets") if isinstance(base.get("cameras"), dict) else None
    if sets and set(base["cameras"]) == {"sets"} and all(
            isinstance(st, dict) and ID_RE.match(str(st.get("id", ""))) and "__" not in st["id"] and st.get("cameras") and
            all(isinstance(c, dict) and ID_RE.match(str(c.get("id", ""))) and "__" not in c["id"] and "position" in c
                for c in st["cameras"]) for st in sets):
        n = 0
        for st in sets:
            extra = {k: v for k, v in st.items() if k not in ("id", "cameras")}
            for c in st["cameras"]:
                pos = _vec3(c["position"])
                if "look_at" in c:
                    fwd = [c["look_at"][k] - pos[k] for k in range(3)]
                    norm = math.sqrt(sum(v * v for v in fwd)) or 1.0
                    fwd = [v / norm for v in fwd]
                else:
                    fwd = [1.0, 0.0, 0.0]
                stj = {**{k: v for k, v in c.items() if k != "id"}, "_i": n}
                if extra:
                    stj["_set"] = extra
                obj(f"STJ::camera::{st['id']}::{c['id']}", "CAMERA", location=pos, forward=fwd, props={"stj": stj})
                n += 1
        del base["cameras"]

    def record_ok(e, key="id"):
        return isinstance(e, dict) and ID_RE.match(str(e.get(key, ""))) and "__" not in str(e[key])

    def record_objects(cat, name_of, value, pos_of=None):
        for i, e in enumerate(value):
            x, y, z = pos_of(e) if pos_of else (0.0, 0.0, 0.0)
            path = e.get("path") if cat == "water" else None
            if isinstance(path, list) and len(path) >= 2 and all(
                    isinstance(p, list) and len(p) == 5 and all(isinstance(c, (int, float)) for c in p) for p in path):
                obj(name_of(e), "CURVE", cyclic=False, points=[p[:3] for p in path],
                    props={"stj": {**{k: v for k, v in e.items() if k not in ("id", "path")}, "_i": i,
                                   "_cols": [p[3:] for p in path]}})
                continue
            ring_key, dim = RECORD_RING.get(cat, (None, 0))
            ring = e.get(ring_key) if ring_key else None
            if isinstance(ring, list) and len(ring) >= 3 and all(
                    isinstance(p, list) and len(p) == dim and all(isinstance(c, (int, float)) for c in p) for p in ring):
                z0 = float(e["level"]) if dim == 2 and isinstance(e.get("level"), (int, float)) else 0.0
                obj(name_of(e), "CURVE", cyclic=True, points=[[p[0], p[1], p[2] if dim == 3 else z0] for p in ring],
                    props={"stj": {**{k: v for k, v in e.items() if k not in ("id", ring_key)}, "_i": i}})
                continue
            obj(name_of(e), location=(x, y, z), props={"stj": {**{k: v for k, v in e.items() if k != "id"}, "_i": i}})

    def midpoint(e):
        try:
            road = e.get("road")
            ref = core.road_line(doc, road) if road and road != "reference" else line
            return ref.point((e["s_start"] + e["s_end"]) / 2.0) if ref is not None else (0.0, 0.0, 0.0)
        except Exception:  # noqa: BLE001
            return (0.0, 0.0, 0.0)

    for cat, path in (("building", "buildings"), ("area", "areas")):
        items = base.get(path)
        key = RING_KEY[cat]
        if items and all(record_ok(e) and isinstance(e.get(key), list) and len(e[key]) >= 3 for e in items):
            for i, e in enumerate(items):
                z = float(e.get("z", 0.0)) if isinstance(e.get("z", 0.0), (int, float)) else 0.0
                obj(f"STJ::{cat}::{e['id']}", "CURVE", cyclic=True, points=[[p[0], p[1], z] for p in e[key]],
                    props={"stj": {**{k: v for k, v in e.items() if k not in ("id", key)}, "_i": i}})
            del base[path]

    structs = base.get("structures")
    if structs and all(record_ok(e) for e in structs):
        record_objects("structure", lambda e: f"STJ::structure::{e['id']}", structs, midpoint)
        del base["structures"]
    anim = base.get("animated_objects")
    if anim and all(record_ok(e) for e in anim):
        record_objects("animated", lambda e: f"STJ::animated::{e['id']}", anim)
        del base["animated_objects"]
    audio = base.get("audio")
    emitters = audio.get("emitters") if isinstance(audio, dict) else None
    if emitters and all(record_ok(e) for e in emitters):
        record_objects("emitter", lambda e: f"STJ::emitter::{e['id']}", emitters,
                       lambda e: _vec3(e["position"]) if "position" in e else (0.0, 0.0, 0.0))
        del audio["emitters"]
        if not audio:
            del base["audio"]
    for cat, (path, _kind) in RECORDS.items():
        if cat in ("structure", "animated", "prototype", "emitter", "crowd"):
            continue                                    # handled above and below
        *parents, leaf = path.split(".")
        holder = base
        for key in parents:
            holder = holder.get(key) if isinstance(holder, dict) else None
        items = holder.get(leaf) if isinstance(holder, dict) else None
        kind = RECORDS[cat][1]
        done = False
        if kind == "list" and items and all(record_ok(e) for e in items):
            record_objects(cat, lambda e, cat=cat: f"STJ::{cat}::{e['id']}", items,
                           (lambda e, key=AT_POSITION.get(cat): _vec3(e[key]) if isinstance(e.get(key), list) else (0.0, 0.0, 0.0))
                           if cat in AT_POSITION else None)
            done = True
        elif kind == "dict" and isinstance(items, dict) and items and all(
                ID_RE.match(str(k)) and "__" not in k and isinstance(v, dict) for k, v in items.items()):
            for i, (k, v) in enumerate(items.items()):
                obj(f"STJ::{cat}::{k}", props={"stj": {**v, "_i": i}})
            done = True
        elif kind == "list_noid" and isinstance(items, list) and items and all(
                isinstance(e, dict) and ID_RE.match(str(e.get("mesh_ref", ""))) and "__" not in e["mesh_ref"] for e in items):
            for i, e in enumerate(items):
                obj(f"STJ::{cat}::{e['mesh_ref']}_{i}", props={"stj": {**e, "_i": i}})
            done = True
        elif kind == "object" and isinstance(items, dict) and items:
            obj(f"STJ::{cat}::{cat}", props={"stj": dict(items)})
            done = True
        if done:
            del holder[leaf]
            node = base
            trail = []
            for key in parents:
                trail.append((node, key))
                node = node[key]
            for owner, key in reversed(trail):
                if not owner[key]:
                    del owner[key]
    scenery = base.get("scenery")
    if isinstance(scenery, dict):
        protos = scenery.get("prototypes")
        if protos and all(ID_RE.match(str(k)) and "__" not in k and isinstance(v, dict) for k, v in protos.items()):
            for i, (k, v) in enumerate(protos.items()):
                obj(f"STJ::prototype::{k}", props={"stj": {**v, "_i": i}})
            del scenery["prototypes"]
        crowds = scenery.get("crowds")
        if crowds and all(record_ok(e) for e in crowds):
            record_objects("crowd", lambda e: f"STJ::crowd::{e['id']}", crowds)
            del scenery["crowds"]
        insts = scenery.get("instances")
        if insts and all(isinstance(e, dict) and ID_RE.match(str(e.get("prototype", ""))) and e.get("transforms") and
                         all(isinstance(t, list) and len(t) in (4, 5) for t in e["transforms"]) for e in insts):
            for i, e in enumerate(insts):
                t = e["transforms"]
                obj(f"STJ::instance::{e['prototype']}_{i}", "MESH", points=[[r[0], r[1], r[2]] for r in t],
                    headings=[r[3] for r in t], scales=[r[4] if len(r) == 5 else 0.0 for r in t],
                    props={"stj": {**{k: v for k, v in e.items() if k != "transforms"}, "_i": i}})
            del scenery["instances"]
        if not scenery:
            del base["scenery"]

    geometry = base.get("geometry")
    if isinstance(geometry, dict) and base_dir is not None:
        many = isinstance(geometry.get("terrains"), list) and bool(geometry["terrains"])
        entries = geometry["terrains"] if many else ([geometry["terrain"]] if isinstance(geometry.get("terrain"), dict) else [])
        built = []
        for e in entries:
            ident = e.get("id") if many else (e.get("id") or "terrain")
            if not isinstance(e, dict) or not ID_RE.match(str(ident)) or "__" in str(ident) or "heightmap" not in e:
                built = None
                break
            try:
                t = core.Terrain(e, base_dir)
            except Exception:  # noqa: BLE001  (a missing or odd file leaves the terrain in the text block)
                built = None
                break
            nx, ny = e["heightmap"]["size"]
            x0, y0, x1, y1 = e["heightmap"]["extent"]
            valid = [v for v in t.heights.data if v == v]
            fill = min(valid) if valid else 0.0
            zs = [(v if v == v else fill) for v in t.heights.data]
            pts = [[x0 + i * (x1 - x0) / (nx - 1), y1 - j * (y1 - y0) / (ny - 1), zs[j * nx + i]]
                   for j in range(ny) for i in range(nx)]
            stj = {**e, "_grid": [nx, ny], "_h": terrain_hash([p[2] for p in pts])}
            if many:
                stj["_many"] = True
                stj.pop("id", None)
            built.append(("STJ::terrain::" + str(ident), pts, [nx, ny], stj))
        if built:
            for name, pts, grid, stj in built:
                obj(name, "MESH", points=pts, grid=grid, props={"stj": stj})
            geometry.pop("terrains" if many else "terrain", None)
            if not geometry:
                del base["geometry"]
    collections = []
    geometry = base.get("geometry")
    meshes = geometry.get("meshes") if isinstance(geometry, dict) else None
    if meshes and base_dir is not None:
        base_dir = Path(base_dir)
        ok = all(isinstance(e, dict) and ID_RE.match(str(e.get("id", ""))) and "__" not in e["id"] and e.get("roles")
                 and isinstance(e.get("uri"), str) and e["uri"].lower().endswith((".usd", ".usda", ".usdc"))
                 and (base_dir / e["uri"]).is_file() for e in meshes)
        if ok:
            for e in meshes:
                collections.append({"name": f"STJ::mesh::{e['id']}", "props": {"stj": {k: v for k, v in e.items() if k != "id"}},
                                    "usd": str(base_dir / e["uri"]), "objects": []})
            del geometry["meshes"]
            if not geometry:
                del base["geometry"]

    library = (base.get("surfaces") or {}).get("library") or {}
    materials = [{"name": f"STJ::surface::{sid}", "props": {}} for sid in library
                 if ID_RE.match(sid) and "__" not in sid]
    return {"blender": None, "profile": PROFILE_VERSION, "objects": objects, "materials": materials, "collections": collections,
            "texts": {BASE_TEXT: json.dumps(base, indent=2, ensure_ascii=False)}, "scene_props": {}}


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
        actual = kind if kind in ("MATERIAL", "COLLECTION") else item["type"]
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
    for cat, what in (("geo", "geo origin"), ("sun", "sun")):
        if sum(1 for _k, _i, n in stj_names(scene) if n and n[0] == cat) > 1:
            f.append(("ERROR", cat, f"more than one {what}: there is one"))
    for kind, item, parsed in stj_names(scene):
        if parsed and parsed[0] == "sun" and kind == "OBJECT" and item.get("light_type") not in (None, "SUN"):
            f.append(("ERROR", f"object '{item['name']}'", f"a sun must be a Sun light, this is {item['light_type']}"))
        if parsed and parsed[0] == "geo" and kind == "OBJECT":
            g = _stj_props(item)
            if not -90 <= g.get("latitude", 0) <= 90 or not -180 <= g.get("longitude", 0) <= 180:
                f.append(("ERROR", f"object '{item['name']}'", "latitude must be -90..90 and longitude -180..180 (degrees)"))
    for kind, item, parsed in stj_names(scene):
        if kind == "OBJECT" and parsed and parsed[0] == "terrain" and item["type"] == "MESH":
            label = f"object '{item['name']}'"
            st = terrain_state(item)
            hm = st["heightmap"]
            if not all(k in hm for k in ("uri", "format", "size", "extent")):
                f.append(("ERROR", label, "needs a custom property stj.heightmap with uri, format, size and extent"))
            elif not st["grid"] or len(item.get("points") or []) != st["grid"][0] * st["grid"][1]:
                f.append(("ERROR", label, f"{len(item.get('points') or [])} vertices for a {st['grid']} grid: "
                                          "the mesh must keep one vertex per heightmap sample"))
            elif st["edited"]:
                f.append(("NOTE", label, f"heights edited: the heightmap {hm['uri']} is written again from the mesh"))
    for kind, item, parsed in stj_names(scene):
        if kind == "OBJECT" and parsed and parsed[0] == "line" and item["type"] == "CURVE":
            n = len(item.get("points") or [])
            for key in ("speed", "width"):
                vals = _stj_props(item).get(key)
                if isinstance(vals, list) and len(vals) != n:
                    f.append(("WARN", f"object '{item['name']}'", f"{key} has {len(vals)} values for {n} points: "
                                                                  "the arrays are per point, so edit them with the curve"))
    for kind, item, parsed in stj_names(scene):
        if kind == "COLLECTION" and parsed and parsed[0] == "mesh":
            props = _stj_props(item)
            roles = props.get("roles")
            label = f"collection '{item['name']}'"
            if not roles or not isinstance(roles, list):
                f.append(("ERROR", label, "needs a custom property stj.roles: a list of " + ", ".join(MESH_ROLES)))
            elif any(r not in MESH_ROLES for r in roles):
                f.append(("ERROR", label, f"unknown role in {roles}: use {', '.join(MESH_ROLES)}"))
            if not item.get("objects"):
                f.append(("WARN", label, "no mesh objects inside: nothing is exported for this mesh"))
    if len(refs) > 1:
        f.append(("ERROR", "reference", f"{len(refs)} reference curves: there is one (use roads or routes for the others)"))
    has_ref = bool(refs) or bool(((base or {}).get("reference") or {}).get("centerline"))
    if not has_ref:
        f.append(("ERROR", "reference", "no reference curve and no reference.centerline in the base document"))

    if base is not None:
        patch, more = scene_patch(scene, base)
        f += more
        sun = (((patch.get("environment") or {}).get("lighting") or {}).get("sun") or {}).get("direction")
        if sun:
            f.append(("NOTE", "environment.lighting.sun.direction",
                      "the sun is fixed where it is in the scene: it will not follow date and time"))
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
