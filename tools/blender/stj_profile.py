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
}
INTERNAL = ("_i", "_set")        # keys of an object's `stj` property that the exporter reads and does not write
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
        cl["tangents_out"] = [[round(c, 4) for c in t] for t in obj["tangents_out"]]
        cl["tangents_in"] = [[round(c, 4) for c in t] for t in obj["tangents_in"]]
    return cl


def reference_patch(obj):
    """The `reference.centerline` of a reference curve."""
    return core.merge_patch(centerline_geometry(obj), _stj_props(obj))


def _order(o):
    return _stj_props(o).get("_i", 1e9)


def _entity(o, drop=()):
    """The fields an object's `stj` property carries for its entity, without the internal keys."""
    return {k: v for k, v in _stj_props(o).items() if k not in INTERNAL and k not in drop}


def road_entry(o, ident):
    props = _entity(o, drop=("centerline",))
    extras = _stj_props(o).get("centerline") or {}
    return {"id": ident, **props, "centerline": core.merge_patch(centerline_geometry(o), extras)}


def edge_entry(o, ident, line):
    """An edge from its object: the stored fields, unless the curve was moved, then side, range and offset
    from the curve."""
    stored = _entity(o)
    entry = {"id": ident, **stored}
    pts = o.get("points") or []
    regen = edge_points(stored, line) if line is not None else None
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
        if kind != "OBJECT" or cat in ("reference", "surface", "geo", "sun", "road", "junction", "camera", "edge"):
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
        patch["edges"] = [edge_entry(o, n[1], line) for o, n in edges]
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
    meshes = [(i, n) for k, i, n in named if k == "COLLECTION" and n[0] == "mesh"]
    if meshes:
        entries = []
        for coll, (_cat, ident, _part) in meshes:
            props = dict(_stj_props(coll))
            uri = props.pop("uri", f"{ident}.usd")
            entries.append({"id": ident, "uri": uri, **props})
        patch["geometry"] = {"meshes": entries}
    env = _environment_patch(named, base, patch)
    if env:
        patch["environment"] = env
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
            points=[_vec3(p) for p in cl["points"]], **extra)
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
