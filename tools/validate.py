"""
STJ Validator
=============
Validates STJ files (.stj.json) and override files (.stj-override.json).

Usage:
    python tools/validate.py <file> [file2 ...] [--schema PATH] [--strict]

Options:
    --schema PATH   Override the schema file (default: schema/stj.schema.json)
    --strict        Exit non-zero on warnings too
    -h, --help      Show this help text and exit.

Steps for each file:
  1. Load, expand $ref (spec §3.2); for an override, check it against
     schema/stj-override.schema.json and apply it to its base (spec §3.3, RFC 7396).
  2. Validate the resulting document against the JSON Schema.
  3. Cross-reference rules the schema cannot express (spec §12): surface, mesh, CRG and
     prototype ids exist; s values lie on the reference line; start, splits, sectors,
     finish and pacenotes are ordered along it; grid order; unit sanity (rad vs deg, m/s vs km/h).
     v0.2: signal names and values, terrain grid rules and terrain above the road, water,
     substitutions, line states, prop inertia, USD prims and primvars, audio ranges.

Levels: ERROR fails the file; WARN fails it with --strict; NOTE never fails.
"""

import copy
import json
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stj_core as core  # noqa: E402

try:
    from jsonschema import Draft7Validator
except ImportError:
    print("Error: jsonschema is not installed.  Run:  pip install jsonschema")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schema" / "stj.schema.json"
OVERRIDE_SCHEMA = ROOT / "schema" / "stj-override.schema.json"

TOL = 0.01                      # m, for s comparisons
LOOSE_CLASSES = {"gravel", "sand", "mud", "snow", "dirt", "grass"}


class Report:
    def __init__(self):
        self.items = []

    def add(self, level, path, msg):
        self.items.append((level, path, msg))

    def error(self, path, msg):
        self.add("ERROR", path, msg)

    def warn(self, path, msg):
        self.add("WARN", path, msg)

    def note(self, path, msg):
        self.add("NOTE", path, msg)

    def count(self, level):
        return sum(1 for i in self.items if i[0] == level)


def _path(parts):
    out = ""
    for p in parts:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out or "(root)"


# ── schema ───────────────────────────────────────────────────────────────────

def schema_errors(doc, schema, rep):
    s = copy.deepcopy(schema)
    s.pop("$id", None)
    for err in sorted(Draft7Validator(s).iter_errors(doc), key=lambda e: list(e.absolute_path)):
        rep.error(_path(err.absolute_path), err.message if len(err.message) < 300 else err.message[:300] + " ...")


# ── context ──────────────────────────────────────────────────────────────────

class Ctx:
    """What the cross-reference checks need to know about the document."""

    def __init__(self, doc, base_dir, rep):
        self.doc = doc
        self.base_dir = Path(base_dir)
        self.rep = rep
        surf = doc.get("surfaces") or {}
        self.surface_ids = {k for k in (surf.get("library") or {}) if not k.startswith(("x_", "_"))}
        geo = doc.get("geometry") or {}
        self.meshes = {m["id"]: m for m in geo.get("meshes", []) if isinstance(m, dict) and "id" in m}
        self.crg_ids = {c["id"] for c in geo.get("crg", []) if isinstance(c, dict) and "id" in c}
        scen = doc.get("scenery") or {}
        self.prototype_ids = {k for k in (scen.get("prototypes") or {}) if not k.startswith(("x_", "_"))}
        self.track_type = (doc.get("track_info") or {}).get("type")
        self.line = core.reference_line(doc)
        self.length = None
        self.closed = self.line.closed if self.line else self.track_type in core.LAPPED_TYPES
        self.mesh_names = {}    # mesh id -> (material names, prim names and paths) of USD files that could be read
        self.used_surfaces = set()

    def lapped(self):
        return self.closed

    def file(self, uri):
        return (self.base_dir / uri).resolve()


# ── reference ────────────────────────────────────────────────────────────────

def check_reference(ctx):
    rep, doc = ctx.rep, ctx.doc
    ref = doc.get("reference") or {}
    lengths = {}
    if ctx.line:
        cl = ref["centerline"]
        lengths["centerline"] = ctx.line.length
        for i in ctx.line.zero_length_segments():
            rep.warn(f"reference.centerline.points[{i}]", "zero-length segment (repeated point)")
        pts = cl["points"]
        if cl.get("closed") and len(pts) > 2 and math.dist(pts[0][:2], pts[-1][:2]) < 1e-6:
            rep.warn("reference.centerline.points", "closed line repeats its first point at the end; leave it out (spec §4.2)")
        prof = cl.get("width_profile")
        if prof:
            for i in range(1, len(prof)):
                if prof[i][0] <= prof[i - 1][0]:
                    rep.error(f"reference.centerline.width_profile[{i}]", "s must increase")
        extent = max(max(abs(p[0]), abs(p[1])) for p in pts)
        geo = doc.get("geometry") or {}
        if extent > 10000 and (geo.get("chunks") or geo.get("tiles")):
            rep.note("reference.centerline", f"geometry reaches {extent:.0f} m from the origin; meshes use chunk or tile origins (spec §7.6)")
        elif extent > 10000:
            rep.warn("reference.centerline", f"geometry reaches {extent:.0f} m from the origin; float32 engines lose precision "
                     "beyond ~10 km. Re-origin near the centroid and record environment.origin_offset (spec §4.4)")
    od = ref.get("opendrive")
    if od:
        path = ctx.file(od["uri"])
        if path.is_file():
            try:
                roads = core.opendrive_road_lengths(path)
                route = od.get("route") or ([{"road": next(iter(roads))}] if len(roads) == 1 else None)
                if route is None:
                    rep.error("reference.opendrive.route", f"{len(roads)} roads in the file; give a route to define s")
                else:
                    total = 0.0
                    for i, r in enumerate(route):
                        if r["road"] not in roads:
                            rep.error(f"reference.opendrive.route[{i}].road", f"road '{r['road']}' not in {od['uri']}")
                        else:
                            total += roads[r["road"]]
                    lengths["opendrive"] = total
            except Exception as e:  # noqa: BLE001
                rep.error("reference.opendrive.uri", f"cannot read OpenDRIVE file: {e}")
        else:
            rep.warn("reference.opendrive.uri", f"file not found: {od['uri']}")
    if "length" in ref:
        lengths["stated"] = ref["length"]
    # authority: OpenDRIVE > centerline > stated length
    for key in ("opendrive", "centerline", "stated"):
        if key in lengths:
            ctx.length = lengths[key]
            break
    for key, val in lengths.items():
        if ctx.length and abs(val - ctx.length) > 0.01 * ctx.length:
            rep.warn("reference", f"{key} length {val:.1f} m differs from {ctx.length:.1f} m by more than 1%")
    if od and ctx.line:
        rep.note("reference", "both OpenDRIVE and centerline given: OpenDRIVE is authoritative, (s, t) poses are resolved on the centerline")

    info = doc.get("track_info") or {}
    if ctx.line and ctx.track_type:
        if ctx.track_type in core.LAPPED_TYPES and not ctx.line.closed:
            rep.warn("reference.centerline.closed", f"track_info.type is '{ctx.track_type}' but the centerline is open")
        if ctx.track_type in core.OPEN_TYPES and ctx.line.closed:
            rep.warn("reference.centerline.closed", f"track_info.type is '{ctx.track_type}' but the centerline is closed")
    if info.get("length") and ctx.length and abs(info["length"] - ctx.length) > 0.02 * ctx.length:
        rep.warn("track_info.length", f"stated {info['length']:.0f} m, reference line is {ctx.length:.0f} m")


def check_s(ctx, path, s, what="s"):
    """s must lie on the reference line."""
    if s is None:
        return False
    if ctx.length is None:
        ctx.rep.error(path, f"{what} needs a reference line (reference.centerline, or reference.opendrive / reference.length)")
        return False
    if s > ctx.length + TOL:
        ctx.rep.error(path, f"{what} = {s:.2f} m is beyond the reference line ({ctx.length:.2f} m)")
        return False
    return True


def lap_d(ctx, s, s0):
    """Distance in race direction from s0 to s (wraps on lapped tracks)."""
    d = s - s0
    if ctx.lapped() and ctx.length:
        d %= ctx.length
        if abs(d - ctx.length) < TOL:
            d = 0.0
    return d


# ── geometry ─────────────────────────────────────────────────────────────────

def check_geometry(ctx):
    rep = ctx.rep
    geo = ctx.doc.get("geometry") or {}
    seen = set()
    for i, m in enumerate(geo.get("meshes", [])):
        p = f"geometry.meshes[{i}]"
        if m["id"] in seen:
            rep.error(f"{p}.id", f"duplicate mesh id '{m['id']}'")
        seen.add(m["id"])
        roles = set(m.get("roles", []))
        if "lod" in roles and "lod" not in m:
            rep.error(p, "role 'lod' needs a lod object (of, level)")
        if "lod" in m:
            if "lod" not in roles:
                rep.warn(p, "lod object on a mesh without the 'lod' role")
            if m["lod"]["of"] not in ctx.meshes:
                rep.error(f"{p}.lod.of", f"unknown mesh '{m['lod']['of']}'")
            elif m["lod"]["of"] == m["id"]:
                rep.error(f"{p}.lod.of", "a mesh cannot be a LOD of itself")
        path = ctx.file(m["uri"])
        if not path.is_file():
            rep.warn(f"{p}.uri", f"file not found: {m['uri']}")
            continue
        if not core.have_pxr():
            rep.note(f"{p}.uri", "USD file not checked: install the pxr module (pip install usd-core)")
            continue
        try:
            ctx.mesh_names[m["id"]] = core.usd_names(path)
            up, mpu = core.usd_frame(path)
            if up != "Z" or abs(mpu - 1.0) > 1e-9:
                rep.warn(f"{p}.uri", f"stage declares upAxis {up}, metersPerUnit {mpu}: STJ is Z up in metres; "
                                     "converters must apply the stage's own values (spec §7.2)")
        except Exception as e:  # noqa: BLE001
            rep.error(f"{p}.uri", f"cannot read USD: {e}")
    seen = set()
    for i, c in enumerate(geo.get("crg", [])):
        p = f"geometry.crg[{i}]"
        if c["id"] in seen:
            rep.error(f"{p}.id", f"duplicate CRG id '{c['id']}'")
        seen.add(c["id"])
        if not ctx.file(c["uri"]).is_file():
            rep.warn(f"{p}.uri", f"file not found: {c['uri']}")
        if "s_start" in c and "s_end" in c and c["s_end"] <= c["s_start"]:
            rep.error(p, "s_end must be greater than s_start")
        for k in ("s_start", "s_end"):
            if k in c:
                check_s(ctx, f"{p}.{k}", c[k])


# ── surfaces ─────────────────────────────────────────────────────────────────

def check_curve(rep, path, curve, lo=0.0, hi=1.5):
    xs = [p[0] for p in curve]
    if any(b <= a for a, b in zip(xs, xs[1:])):
        rep.error(path, "x values must increase")
    if xs and xs[0] != 0:
        rep.warn(path, "curve should start at water depth 0")
    for j, p in enumerate(curve):
        if not lo <= p[1] <= hi:
            rep.warn(f"{path}[{j}]", f"factor {p[1]} outside {lo}..{hi}")
        if p[0] > 0.05:
            rep.warn(f"{path}[{j}]", f"water depth {p[0]} m: depths are in metres (1 mm = 0.001)")


def check_surface_values(ctx, p, s, sid, cls):
    rep = ctx.rep
    for k, v in (s.get("mf_scaling") or {}).items():
        if k.startswith(("x_", "_")):
            continue
        if k in ("LMUX", "LMUY") and v > 1.5:
            rep.warn(f"{p}.mf_scaling.{k}", f"{v}: more than 1.5x the grip of dry asphalt (STJ-REF)")
        if v == 0:
            rep.warn(f"{p}.mf_scaling.{k}", "0 removes the force entirely")
    if "wet_response" in s:
        check_curve(rep, f"{p}.wet_response", s["wet_response"])
    if s.get("rolling_resistance", 0) > 0.5:
        rep.warn(f"{p}.rolling_resistance", "above 0.5: check the value is a coefficient, not a force")
    rough = s.get("roughness") or {}
    if "crg_ref" in rough and rough["crg_ref"] not in ctx.crg_ids:
        rep.error(f"{p}.roughness.crg_ref", f"unknown CRG '{rough['crg_ref']}'")
    if rough.get("mean_profile_depth", 0) > 0.02:
        rep.warn(f"{p}.roughness.mean_profile_depth", "above 20 mm: macrotexture is in metres")
    d = s.get("deformable")
    if d:
        if cls and cls not in LOOSE_CLASSES:
            rep.warn(f"{p}.deformable", f"deformable data on a '{cls}' surface")
        eff = d.get("effective") or {}
        base = eff.get("base_surface")
        if base is not None:
            if base not in ctx.surface_ids:
                rep.error(f"{p}.deformable.effective.base_surface", f"unknown surface '{base}'")
            elif base == sid:
                rep.error(f"{p}.deformable.effective.base_surface", "a surface cannot be its own base")
            ctx.used_surfaces.add(base)
        if "terramechanics" in d and not eff and "mf_scaling" not in s:
            rep.note(f"{p}.deformable", "Tier B only: engines without a soil model get nothing; add Tier A (spec §6.6)")


def check_surfaces(ctx):
    rep, doc = ctx.rep, ctx.doc
    surf = doc.get("surfaces") or {}
    lib = surf.get("library") or {}
    for sid, s in lib.items():
        if sid.startswith(("x_", "_")) or not isinstance(s, dict):
            continue
        p = f"surfaces.library.{sid}"
        check_surface_values(ctx, p, s, sid, s.get("class"))
        for tc, ov in (s.get("by_tyre_class") or {}).items():
            if not tc.startswith(("x_", "_")):
                check_surface_values(ctx, f"{p}.by_tyre_class.{tc}", ov, sid, s.get("class"))

    def ref(path, sid):
        ctx.used_surfaces.add(sid)
        if sid not in ctx.surface_ids:
            rep.error(path, f"unknown surface '{sid}'")

    if "default" in surf:
        ref("surfaces.default", surf["default"])
    seen = {}
    for i, b in enumerate(surf.get("bindings", [])):
        p = f"surfaces.bindings[{i}]"
        ref(f"{p}.surface", b["surface"])
        mesh = ctx.meshes.get(b["mesh_ref"])
        if mesh is None:
            rep.error(f"{p}.mesh_ref", f"unknown mesh '{b['mesh_ref']}'")
            continue
        if "collision" not in mesh.get("roles", []):
            rep.warn(f"{p}.mesh_ref", f"mesh '{b['mesh_ref']}' has no 'collision' role; surfaces act on collision meshes")
        names = ctx.mesh_names.get(b["mesh_ref"])
        if names:
            if "material" in b and b["material"] not in names[0]:
                rep.error(f"{p}.material", f"material '{b['material']}' not in {mesh['uri']}")
            if "prim" in b and b["prim"] not in names[1]:
                rep.error(f"{p}.prim", f"prim '{b['prim']}' not in {mesh['uri']}")
        key = (b["mesh_ref"], b.get("material"), b.get("prim"))
        if key in seen and seen[key] != b["surface"] and "when" not in b:
            rep.error(p, f"binds {key[1] or key[2]} to '{b['surface']}', an earlier binding says '{seen[key]}'")
        seen[key] = b["surface"]
    bound = {(k[0], k[1]) for k in seen if k[1]} | {(m["mesh_ref"], m["material"]) for m in surf.get("maps", [])}
    for mid, (materials, _nodes) in ctx.mesh_names.items():
        if "collision" not in ctx.meshes[mid].get("roles", []):
            continue
        for mat in materials:
            if mat.startswith(("STJ::surface::", "STJ__surface__")):
                ref(f"geometry.meshes[{mid}] material '{mat}'", mat[len("STJ::surface::"):])
            elif (mid, mat) not in bound:
                if "default" in surf:
                    rep.note(f"geometry.meshes[{mid}]", f"material '{mat}' has no binding; it uses the default surface '{surf['default']}'")
                else:
                    rep.warn(f"geometry.meshes[{mid}]", f"material '{mat}' has no binding and there is no default surface")
    for name, sid in (surf.get("opendrive_materials") or {}).items():
        ref(f"surfaces.opendrive_materials.{name}", sid)
    for i, b in enumerate(surf.get("bands", [])):
        p = f"surfaces.bands[{i}]"
        ref(f"{p}.surface", b["surface"])
        check_band(ctx, p, b)
    if ctx.surface_ids and not (surf.get("default") or surf.get("bindings") or surf.get("bands") or ctx.mesh_names):
        rep.warn("surfaces", "a library but no default, bindings or bands: nothing says where the surfaces are")


def check_band(ctx, p, b):
    rep = ctx.rep
    if b["t_min"] >= b["t_max"]:
        rep.error(p, "t_min must be smaller than t_max")
    ok = check_s(ctx, f"{p}.s_start", b["s_start"]) & check_s(ctx, f"{p}.s_end", b["s_end"])
    if ok:
        if abs(b["s_end"] - b["s_start"]) < 1e-9:
            rep.error(p, "s_start equals s_end")
        elif b["s_end"] < b["s_start"] and not ctx.lapped():
            rep.error(p, "s_end before s_start on an open reference line")


# ── timing ───────────────────────────────────────────────────────────────────

def line_s(ctx, path, line):
    if not isinstance(line, dict):
        return None
    if "t_min" in line and "t_max" in line and line["t_min"] >= line["t_max"]:
        ctx.rep.error(path, "t_min must be smaller than t_max")
    if "s" in line and check_s(ctx, f"{path}.s", line["s"]):
        return line["s"]
    return None


def check_timing(ctx):
    rep = ctx.rep
    tm = ctx.doc.get("timing") or {}
    if not tm:
        return None
    lapped = ctx.lapped()
    sf = line_s(ctx, "timing.start_finish", tm.get("start_finish"))
    st = line_s(ctx, "timing.start", tm.get("start"))
    fi = line_s(ctx, "timing.finish", tm.get("finish"))
    sp = line_s(ctx, "timing.stop", tm.get("stop"))
    if lapped and ("start" in tm or "finish" in tm):
        rep.warn("timing", "lapped track uses start/finish; use start_finish")
    if not lapped and "start_finish" in tm and ctx.length is not None:
        rep.warn("timing.start_finish", "open track: use start and finish")

    origin = sf if lapped else st
    end_d = ctx.length if lapped else None
    if not lapped and st is not None and fi is not None:
        if fi <= st:
            rep.error("timing.finish.s", f"finish ({fi:.1f}) must come after start ({st:.1f})")
        end_d = fi - st
        if sp is not None and sp < fi:
            rep.error("timing.stop.s", f"stop ({sp:.1f}) must not come before finish ({fi:.1f})")

    # split points: strictly increasing between start and finish
    prev = 0.0
    for i, s in enumerate(tm.get("split_points", [])):
        p = f"timing.split_points[{i}]"
        val = line_s(ctx, p, s)
        if val is None or origin is None:
            continue
        d = lap_d(ctx, val, origin)
        if d <= prev + (TOL if i else 0):
            rep.error(f"{p}.s", f"split '{s['id']}' at s = {val:.1f} is not after the previous timing point")
        if end_d is not None and d >= end_d - TOL:
            rep.error(f"{p}.s", f"split '{s['id']}' is not before the finish")
        prev = d
    ids = [s["id"] for s in tm.get("split_points", [])]
    for dup in {x for x in ids if ids.count(x) > 1}:
        rep.error("timing.split_points", f"duplicate split id '{dup}'")

    # sectors: contiguous from origin to finish
    secs = tm.get("sectors", [])
    if secs:
        if origin is None:
            rep.error("timing.sectors", "sectors need a start_finish (lapped) or start (open) line given by s")
        else:
            ids = [s["id"] for s in secs]
            for dup in {x for x in ids if ids.count(x) > 1}:
                rep.error("timing.sectors", f"duplicate sector id '{dup}'")
            covered = 0.0
            for i, sec in enumerate(secs):
                p = f"timing.sectors[{i}]"
                if not (check_s(ctx, f"{p}.s_start", sec["s_start"]) and check_s(ctx, f"{p}.s_end", sec["s_end"])):
                    return origin
                d0 = lap_d(ctx, sec["s_start"], origin)
                d1 = lap_d(ctx, sec["s_end"], origin)
                if lapped and i == len(secs) - 1 and d1 < TOL:
                    d1 = ctx.length
                if abs(d0 - covered) > TOL:
                    what = "the start line" if i == 0 else f"the end of sector '{secs[i - 1]['id']}'"
                    rep.error(f"{p}.s_start", f"sector '{sec['id']}' starts at s = {sec['s_start']:.2f}, not at {what}")
                if d1 <= d0:
                    rep.error(p, f"sector '{sec['id']}' ends before it starts (in race direction)")
                covered = d1
            if end_d is not None and abs(covered - end_d) > TOL:
                rep.error("timing.sectors", f"sectors end {covered:.1f} m after the start; the {'lap' if lapped else 'finish'} is at {end_d:.1f} m")

    pit = tm.get("pit_lane")
    if pit:
        for k in ("entry_s", "exit_s"):
            if k in pit:
                check_s(ctx, f"timing.pit_lane.{k}", pit[k])
        if not lapped and pit:
            rep.warn("timing.pit_lane", "pit lane on an open track")
        if pit.get("speed_limit", 0) > 40:
            rep.warn("timing.pit_lane.speed_limit", f"{pit['speed_limit']} m/s = {pit['speed_limit'] * 3.6:.0f} km/h: speeds are in m/s")
        for k in ("limit_start", "limit_end"):
            line_s(ctx, f"timing.pit_lane.{k}", pit.get(k))
        for k, v in (pit.get("session_speed_limits") or {}).items():
            if v > 40:
                rep.warn(f"timing.pit_lane.session_speed_limits.{k}", f"{v} m/s = {v * 3.6:.0f} km/h: speeds are in m/s")

    ids = [z["id"] for z in tm.get("drs_zones", [])]
    for dup in {x for x in ids if ids.count(x) > 1}:
        rep.error("timing.drs_zones", f"duplicate zone id '{dup}'")
    for i, z in enumerate(tm.get("drs_zones", [])):
        p = f"timing.drs_zones[{i}]"
        if not lapped:
            rep.warn(p, "DRS zone on an open track")
        if all(check_s(ctx, f"{p}.{k}", z[k]) for k in ("detection_s", "activation_s", "deactivation_s")):
            act = lap_d(ctx, z["activation_s"], z["detection_s"])
            deact = lap_d(ctx, z["deactivation_s"], z["detection_s"])
            if not act < deact:
                rep.error(p, "order must be detection, activation, deactivation in race direction")

    ids = [c["id"] for c in tm.get("controls", [])]
    for dup in {x for x in ids if ids.count(x) > 1}:
        rep.error("timing.controls", f"duplicate control id '{dup}'")
    for i, c in enumerate(tm.get("controls", [])):
        if "s" in c:
            check_s(ctx, f"timing.controls[{i}].s", c["s"])
    for i, sr in enumerate(tm.get("side_roads", [])):
        p = f"timing.side_roads[{i}]"
        check_s(ctx, f"{p}.s", sr["s"])
        if "heading_offset" in sr:
            check_heading(rep, f"{p}.heading_offset", sr["heading_offset"])
    for i, b in enumerate((tm.get("track_limits") or {}).get("boundaries", [])):
        p = f"timing.track_limits.boundaries[{i}]"
        check_s(ctx, f"{p}.s_start", b["s_start"])
        check_s(ctx, f"{p}.s_end", b["s_end"])
        if (b["side"] == "left") != (b["t"] > 0):
            rep.warn(f"{p}.t", f"side '{b['side']}' with t = {b['t']}: t is positive to the left")
    return origin


# ── race ─────────────────────────────────────────────────────────────────────

def check_heading(rep, path, h):
    if abs(h) > 2 * math.pi + 1e-6:
        rep.warn(path, f"{h} rad: angles are in radians (degrees given?)")


def pose_s(ctx, path, pose):
    """Check a pose; return its s for (s, t) poses."""
    rep = ctx.rep
    if not isinstance(pose, dict):
        return None
    if "heading" in pose:
        check_heading(rep, f"{path}.heading", pose["heading"])
    if "heading_offset" in pose:
        check_heading(rep, f"{path}.heading_offset", pose["heading_offset"])
    if "s" in pose:
        if ctx.line is None and ctx.length is not None:
            rep.warn(path, "(s, t) pose with an OpenDRIVE-only reference: the validator cannot place it")
        if not check_s(ctx, f"{path}.s", pose["s"]):
            return None
        hw = core.half_widths(ctx.doc, pose["s"])
        if hw and not (-hw[1] - 5 <= pose["t"] <= hw[0] + 5):
            rep.warn(f"{path}.t", f"t = {pose['t']} m is more than 5 m off the road edge")
        return pose["s"]
    return None


def check_race(ctx, origin):
    rep = ctx.rep
    race = ctx.doc.get("race") or {}
    grid = race.get("grid", [])
    positions = [g["position"] for g in grid]
    if positions and sorted(positions) != list(range(1, len(positions) + 1)):
        rep.error("race.grid", f"positions must be 1..{len(positions)} without gaps or duplicates")
    behind = []
    for i, g in enumerate(grid):
        s = pose_s(ctx, f"race.grid[{i}].pose", g["pose"])
        if s is not None and origin is not None and ctx.length:
            b = (origin - s) % ctx.length if ctx.lapped() else origin - s
            behind.append((g["position"], b))
    behind.sort()
    for (p1, b1), (p2, b2) in zip(behind, behind[1:]):
        if b2 < b1 - TOL:
            rep.warn("race.grid", f"position {p2} is ahead of position {p1} along the track")
    for key in ("pit_boxes", "spawns", "racing_lines"):
        ids = [x["id"] for x in race.get(key, [])]
        for dup in {x for x in ids if ids.count(x) > 1}:
            rep.error(f"race.{key}", f"duplicate id '{dup}'")
    for i, b in enumerate(race.get("pit_boxes", [])):
        pose_s(ctx, f"race.pit_boxes[{i}].pose", b["pose"])
        if "garage_pose" in b:
            pose_s(ctx, f"race.pit_boxes[{i}].garage_pose", b["garage_pose"])
    for i, sp in enumerate(race.get("spawns", [])):
        pose_s(ctx, f"race.spawns[{i}].pose", sp["pose"])
    for i, rl in enumerate(race.get("racing_lines", [])):
        p = f"race.racing_lines[{i}]"
        for key in ("speed", "width"):
            if key in rl and len(rl[key]) != len(rl["points"]):
                rep.error(f"{p}.{key}", f"{len(rl[key])} values for {len(rl['points'])} points")
        if rl.get("speed") and max(rl["speed"]) > 120:
            rep.warn(f"{p}.speed", f"max {max(rl['speed'])} m/s: speeds are in m/s")
    check_pacenotes(ctx, race.get("pacenotes"), origin)
    check_ai(ctx, race.get("ai"))
    check_start_procedure(ctx, race.get("start_procedure"))
    ids = [a["id"] for a in race.get("service_areas", [])]
    for dup in {x for x in ids if ids.count(x) > 1}:
        rep.error("race.service_areas", f"duplicate id '{dup}'")


def check_ai(ctx, ai):
    rep = ctx.rep
    if not ai:
        return
    prev = None
    for i, (s, t_min, t_max) in enumerate(ai.get("corridor", [])):
        p = f"race.ai.corridor[{i}]"
        check_s(ctx, p, s)
        if prev is not None and s <= prev:
            rep.error(p, "s must increase")
        if t_min >= t_max:
            rep.error(p, "t_min must be smaller than t_max")
        hw = core.half_widths(ctx.doc, s)
        if hw and (t_max > hw[0] + 2.0 or t_min < -hw[1] - 2.0):
            rep.warn(p, "corridor reaches more than 2 m past the road edge")
        prev = s
    for i, h in enumerate(ai.get("hints", [])):
        p = f"race.ai.hints[{i}]"
        if check_s(ctx, f"{p}.s_start", h["s_start"]) and check_s(ctx, f"{p}.s_end", h["s_end"]):
            if h["s_end"] < h["s_start"] and not ctx.lapped():
                rep.error(p, "s_end before s_start on an open reference line")
        if h["kind"] in ("brake", "speed_limit") and h.get("value", 0) > 120:
            rep.warn(f"{p}.value", f"{h['value']} m/s: speeds are in m/s")
        if h["kind"] in ("danger", "caution") and not 0 <= h.get("value", 0) <= 1:
            rep.warn(f"{p}.value", "danger and caution values are 0..1")


def check_start_procedure(ctx, sp):
    rep = ctx.rep
    if not sp:
        return
    for k in ("formation_speed", "rolling_start_speed"):
        if sp.get(k, 0) > 60:
            rep.warn(f"race.start_procedure.{k}", f"{sp[k]} m/s = {sp[k] * 3.6:.0f} km/h: speeds are in m/s")
    if sp.get("type") == "rolling" and "rolling_start_speed" not in sp:
        rep.note("race.start_procedure", "rolling start without rolling_start_speed")
    if sp.get("type") == "staggered" and "start_interval" not in sp:
        rep.note("race.start_procedure", "staggered start without start_interval")
    if sp.get("type") in ("standing", "rolling") and not ctx.lapped():
        rep.warn("race.start_procedure.type", f"'{sp['type']}' start on an open track")
    lights = sp.get("lights") or {}
    if "mesh_ref" in lights:
        if lights["mesh_ref"] not in ctx.meshes:
            rep.error("race.start_procedure.lights.mesh_ref", f"unknown mesh '{lights['mesh_ref']}'")
        elif lights["mesh_ref"] in ctx.mesh_names:
            for j, n in enumerate(lights.get("prims", [])):
                if n not in ctx.mesh_names[lights["mesh_ref"]][1]:
                    rep.error(f"race.start_procedure.lights.prims[{j}]", f"prim '{n}' not in {ctx.meshes[lights['mesh_ref']]['uri']}")
    if "prims" in lights and "count" in lights and len(lights["prims"]) != lights["count"]:
        rep.warn("race.start_procedure.lights", f"{len(lights['prims'])} prims for {lights['count']} light steps")


# ── edges, cameras ───────────────────────────────────────────────────────────

EDGE_STYLES = {
    "invisible": {"other"},
    "kerb": {"flat", "raised", "rumble", "sausage", "negative", "other"},
    "verge": {"grass", "gravel_trap", "paved_runoff", "other"},
    "barrier": {"wall", "armco", "tyre_wall", "tecpro", "fence", "debris_fence", "tape", "hay_bale", "concrete_block",
                "rock", "earth_bank", "snow_bank", "other"},
}


def check_edges(ctx, path="edges"):
    rep = ctx.rep
    edges = ctx.doc.get("edges") or []
    ids = [e["id"] for e in edges if "id" in e]
    for dup in {x for x in ids if ids.count(x) > 1}:
        rep.error(path, f"duplicate edge id '{dup}'")
    for i, e in enumerate(edges):
        p = f"{path}[{i}]"
        if "style" in e and e["style"] not in EDGE_STYLES[e["kind"]]:
            rep.warn(f"{p}.style", f"'{e['style']}' is not a {e['kind']} style")
        ok = check_s(ctx, f"{p}.s_start", e["s_start"]) & check_s(ctx, f"{p}.s_end", e["s_end"])
        if ok and e["s_end"] < e["s_start"] and not ctx.lapped():
            rep.error(p, "s_end before s_start on an open reference line")
        if "t" in e and (e["side"] == "left") != (e["t"] > 0):
            rep.warn(f"{p}.t", f"side '{e['side']}' with t = {e['t']}: t is positive to the left")
        if "surface" in e:
            ctx.used_surfaces.add(e["surface"])
            if e["surface"] not in ctx.surface_ids:
                rep.error(f"{p}.surface", f"unknown surface '{e['surface']}'")
        m = e.get("mesh")
        if m and m["mesh_ref"] not in ctx.meshes:
            rep.error(f"{p}.mesh.mesh_ref", f"unknown mesh '{m['mesh_ref']}'")
        if e.get("width", 0) > 50:
            rep.warn(f"{p}.width", f"{e['width']} m wide: lengths are in metres")
        if abs(e.get("height", 0)) > 10:
            rep.warn(f"{p}.height", f"{e['height']} m high: lengths are in metres")
        if "restitution" in e and e["kind"] != "barrier":
            rep.note(f"{p}.restitution", "restitution only matters for barriers")


def check_cameras(ctx):
    rep = ctx.rep
    sets = (ctx.doc.get("cameras") or {}).get("sets", [])
    ids = [s["id"] for s in sets]
    for dup in {x for x in ids if ids.count(x) > 1}:
        rep.error("cameras.sets", f"duplicate set id '{dup}'")
    for i, cs in enumerate(sets):
        cam_ids = [c["id"] for c in cs["cameras"]]
        for dup in {x for x in cam_ids if cam_ids.count(x) > 1}:
            rep.error(f"cameras.sets[{i}]", f"duplicate camera id '{dup}'")
        for j, c in enumerate(cs["cameras"]):
            p = f"cameras.sets[{i}].cameras[{j}]"
            fov = c.get("fov")
            if fov:
                if fov[0] > fov[1]:
                    rep.error(f"{p}.fov", "min must not exceed max")
                if fov[1] >= math.pi:
                    rep.warn(f"{p}.fov", f"{fov[1]} rad: field of view is in radians")
            if c["kind"] == "static" and "look_at" not in c:
                rep.warn(p, "a static camera needs look_at")
            if "active" in c:
                check_s(ctx, f"{p}.active.s_start", c["active"]["s_start"])
                check_s(ctx, f"{p}.active.s_end", c["active"]["s_end"])
            if "active" not in c and "spheres" not in c:
                rep.note(p, "no activation (active range or spheres): engines decide when to use it")
            if c.get("near") and c.get("far") and c["near"] >= c["far"]:
                rep.error(p, "near must be smaller than far")


def check_pacenotes(ctx, pn, origin):
    rep = ctx.rep
    if not pn:
        return
    tm = ctx.doc.get("timing") or {}
    finish = (tm.get("finish") or {}).get("s")
    prev = None
    for i, n in enumerate(pn.get("notes", [])):
        p = f"race.pacenotes.notes[{i}]"
        kind = n["kind"]
        if kind == "turn" and ("direction" not in n or "severity" not in n):
            rep.warn(p, "a turn needs direction and severity")
        if kind in ("hairpin", "square", "acute") and "direction" not in n:
            rep.warn(p, f"a {kind} needs a direction")
        if "severity" in n and kind != "turn":
            rep.warn(f"{p}.severity", f"severity only applies to turns, not '{kind}'")
        if not check_s(ctx, f"{p}.s", n["s"]):
            continue
        d = lap_d(ctx, n["s"], origin) if origin is not None else n["s"]
        if prev is not None and d < prev - TOL:
            rep.error(f"{p}.s", f"note at s = {n['s']:.1f} comes before the previous note")
        prev = d
        if not ctx.lapped() and origin is not None:
            if n["s"] < origin - TOL:
                rep.warn(f"{p}.s", "note before the start line")
            if finish is not None and n["s"] > finish + 50 and kind != "finish":
                rep.warn(f"{p}.s", "note more than 50 m after the finish")


# ── environment, scenery ─────────────────────────────────────────────────────

def check_environment(ctx):
    rep = ctx.rep
    env = ctx.doc.get("environment") or {}
    for k in ("north_heading",):
        if k in env:
            check_heading(rep, f"environment.{k}", env[k])
    geo = env.get("geo_reference") or {}
    proj = (geo.get("proj") or "").lower()
    if any(t in proj for t in ("longlat", "latlong", "epsg:4326", "epsg:4979")):
        rep.error("environment.geo_reference.proj", "x/y must be projected metres, not geographic degrees (spec §4.3)")
    elif "+proj=utm" in proj or "epsg:326" in proj or "epsg:327" in proj:
        rep.note("environment.geo_reference.proj", "UTM distorts lengths by up to ~1 m/km; a local Transverse Mercator is recommended (spec §4.3)")
    if geo and "north_heading" not in env:
        rep.note("environment.north_heading", "not given: engines assume +Y is true north")
    check_weather(rep, "environment.default_weather", env.get("default_weather") or {})
    last = {}
    for i, entry in enumerate(env.get("weather_schedule", [])):
        p = f"environment.weather_schedule[{i}]"
        check_weather(rep, f"{p}.weather", entry["weather"])
        if entry["time"] < last.get(entry["session"], -1):
            rep.error(f"{p}.time", f"times of session '{entry['session']}' must not decrease")
        last[entry["session"]] = entry["time"]
    sky = env.get("sky") or {}
    if "hdri" in sky and not ctx.file(sky["hdri"]["uri"]).is_file():
        rep.warn("environment.sky.hdri.uri", f"file not found: {sky['hdri']['uri']}")
    if sky.get("model") == "hdri" and "hdri" not in sky:
        rep.error("environment.sky", "model 'hdri' needs an hdri block")
    light = env.get("lighting") or {}
    if "usd_lights" in light and light["usd_lights"] not in ctx.meshes:
        rep.error("environment.lighting.usd_lights", f"unknown mesh '{light['usd_lights']}'")
    ids = [x["id"] for x in light.get("lights", [])]
    for dup in {x for x in ids if ids.count(x) > 1}:
        rep.error("environment.lighting.lights", f"duplicate light id '{dup}'")
    for i, lt in enumerate(light.get("lights", [])):
        if lt["type"] == "spot" and "direction" not in lt:
            rep.error(f"environment.lighting.lights[{i}]", "a spot light needs a direction")
        if lt.get("outer_cone_angle", 0) > math.pi / 2:
            rep.warn(f"environment.lighting.lights[{i}].outer_cone_angle", "above pi/2: angles are in radians")


def check_weather(rep, p, w):
    if "wind_from_heading" in w:
        check_heading(rep, f"{p}.wind_from_heading", w["wind_from_heading"])
    if w.get("water_depth", 0) > 0.02:
        rep.warn(f"{p}.water_depth", f"{w['water_depth']} m of water: depths are in metres")
    for k in ("air_temperature", "track_temperature"):
        if k in w and not -50 <= w[k] <= 80:
            rep.warn(f"{p}.{k}", f"{w[k]} °C is implausible")


def check_scenery(ctx):
    rep = ctx.rep
    sc = ctx.doc.get("scenery") or {}
    used = set()

    def proto(path, pid):
        used.add(pid)
        if pid not in ctx.prototype_ids:
            rep.error(path, f"unknown prototype '{pid}'")

    for pid, pr in (sc.get("prototypes") or {}).items():
        if pid.startswith(("x_", "_")):
            continue
        m = pr.get("mesh")
        if m and m["mesh_ref"] not in ctx.meshes:
            rep.error(f"scenery.prototypes.{pid}.mesh.mesh_ref", f"unknown mesh '{m['mesh_ref']}'")
        if pr.get("collision") == "trunk" and "collision_radius" not in pr:
            rep.note(f"scenery.prototypes.{pid}", "trunk collision without collision_radius")
        if pr.get("height", 0) > 150:
            rep.warn(f"scenery.prototypes.{pid}.height", f"{pr['height']} m: heights are in metres")
    for i, ins in enumerate(sc.get("instances", [])):
        p = f"scenery.instances[{i}]"
        proto(f"{p}.prototype", ins["prototype"])
        for j, t in enumerate(ins.get("transforms", [])):
            check_heading(rep, f"{p}.transforms[{j}][3]", t[3])
            if len(t) == 5 and t[4] <= 0:
                rep.error(f"{p}.transforms[{j}][4]", "scale must be positive")
        g = ins.get("usd")
        if g:
            if g["mesh_ref"] not in ctx.meshes:
                rep.error(f"{p}.usd.mesh_ref", f"unknown mesh '{g['mesh_ref']}'")
            elif g["mesh_ref"] in ctx.mesh_names and g["prim"] not in ctx.mesh_names[g["mesh_ref"]][1]:
                rep.error(f"{p}.usd.prim", f"prim '{g['prim']}' not in {ctx.meshes[g['mesh_ref']]['uri']}")
    ids = [x["id"] for x in sc.get("scatter", [])]
    for dup in {x for x in ids if ids.count(x) > 1}:
        rep.error("scenery.scatter", f"duplicate scatter id '{dup}'")
    for i, layer in enumerate(sc.get("scatter", [])):
        p = f"scenery.scatter[{i}]"
        for j, pr in enumerate(layer["prototypes"]):
            proto(f"{p}.prototypes[{j}].prototype", pr["prototype"])
        if layer["density"] > 1000:
            rep.warn(f"{p}.density", f"{layer['density']} per m²: density is instances per square metre")
        area = layer["area"]
        for j, sid in enumerate(area.get("surfaces", [])):
            if sid not in ctx.surface_ids:
                rep.error(f"{p}.area.surfaces[{j}]", f"unknown surface '{sid}'")
        for j, sid in enumerate(layer.get("exclude_surfaces", [])):
            if sid not in ctx.surface_ids:
                rep.error(f"{p}.exclude_surfaces[{j}]", f"unknown surface '{sid}'")
        for j, b in enumerate(area.get("bands", [])):
            check_band(ctx, f"{p}.area.bands[{j}]", {**b, "surface": None})
        mask = area.get("mask")
        if mask:
            e = mask["extent"]
            if e[2] <= e[0] or e[3] <= e[1]:
                rep.error(f"{p}.area.mask.extent", "extent must be [x_min, y_min, x_max, y_max]")
            if not ctx.file(mask["uri"]).is_file():
                rep.warn(f"{p}.area.mask.uri", f"file not found: {mask['uri']}")
        ma = area.get("mesh_attribute")
        if ma and ma["mesh_ref"] not in ctx.meshes:
            rep.error(f"{p}.area.mesh_attribute.mesh_ref", f"unknown mesh '{ma['mesh_ref']}'")
        sr = layer.get("scale_range")
        if sr and sr[0] > sr[1]:
            rep.error(f"{p}.scale_range", "min must not exceed max")
    used.update(e["prototype"] for e in ctx.doc.get("edges") or [] if "prototype" in e)
    used.update(c["prototype"] for c in sc.get("crowds", []) if "prototype" in c)
    for pid in sorted(ctx.prototype_ids - used):
        rep.note(f"scenery.prototypes.{pid}", "not used by any instance set or scatter layer")


# ── v0.2: signals, terrain, water, line states, props, animation, audio, UI ──

ENUM_OPS = {"eq", "ne", "in"}


def _dups(rep, path, items, what):
    ids = [x["id"] for x in items if isinstance(x, dict) and "id" in x]
    for dup in sorted({x for x in ids if ids.count(x) > 1}):
        rep.error(path, f"duplicate {what} id '{dup}'")


def _walk_signals(node, path, found):
    """Collect (path, kind, object) for every condition leaf and binding, skipping x_ blocks."""
    if isinstance(node, dict):
        if "signal" in node and ("op" in node or "curve" in node or "map" in node):
            found.append((path, "condition" if "op" in node else "binding", node))
        for k, v in node.items():
            if not k.startswith("x_"):
                _walk_signals(v, f"{path}.{k}" if path else k, found)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk_signals(v, f"{path}[{i}]", found)


def check_signals(ctx):
    """Signal names, operators, values and curves of every condition and binding (spec §11.1)."""
    rep = ctx.rep
    found = []
    _walk_signals({k: v for k, v in ctx.doc.items() if k not in ("layouts", "variants")}, "", found)
    lights = (((ctx.doc.get("race") or {}).get("start_procedure") or {}).get("lights") or {}).get("count")
    for p, kind, n in found:
        sig = n["signal"]
        if sig.startswith("x_"):
            continue
        skind, values, rng = core.SIGNALS[sig]
        if kind == "condition":
            op, val = n["op"], n["value"]
            vals = val if op == "in" else [val]
            if op == "in" and not isinstance(val, list):
                rep.error(f"{p}.value", "op 'in' needs a list")
                continue
            if op != "in" and isinstance(val, list):
                rep.error(f"{p}.value", f"op '{op}' needs a single value")
                continue
            if skind == "enum":
                if op not in ENUM_OPS:
                    rep.error(f"{p}.op", f"'{sig}' is an enum signal: use eq, ne or in")
                for v in vals:
                    if v not in values:
                        rep.error(f"{p}.value", f"'{v}' is not a value of '{sig}' ({', '.join(values)})")
            else:
                for v in vals:
                    if not isinstance(v, (int, float)) or isinstance(v, bool):
                        rep.error(f"{p}.value", f"'{sig}' is numeric ({values})")
                    elif rng and ((rng[0] is not None and v < rng[0]) or (rng[1] is not None and v > rng[1])):
                        rep.warn(f"{p}.value", f"{v} outside {rng[0]}..{rng[1]} {values}: check the unit")
                    elif sig == "start_lights_lit" and lights is not None and v > lights:
                        rep.warn(f"{p}.value", f"{v} lights lit, but start_procedure.lights.count is {lights}")
        else:
            if skind == "enum" and "curve" in n:
                rep.error(p, f"'{sig}' is an enum signal: use map, not curve")
            if skind != "enum" and "map" in n:
                rep.error(p, f"'{sig}' is numeric: use curve, not map")
            for key in n.get("map", {}):
                if skind == "enum" and key not in values:
                    rep.error(f"{p}.map.{key}", f"'{key}' is not a value of '{sig}'")
            xs = [q[0] for q in n.get("curve", [])]
            if any(b <= a for a, b in zip(xs, xs[1:])):
                rep.error(f"{p}.curve", "signal values must increase")
            if rng and xs and ((rng[0] is not None and xs[0] < rng[0] - 1e-9) or (rng[1] is not None and xs[-1] > rng[1] + 1e-9)):
                rep.warn(f"{p}.curve", f"signal values outside {rng[0]}..{rng[1]} {values}: check the unit")


def _mesh_has(ctx, rep, path, mesh_ref, material=None, nodes=()):
    if mesh_ref not in ctx.meshes:
        rep.error(f"{path}.mesh_ref", f"unknown mesh '{mesh_ref}'")
        return
    names = ctx.mesh_names.get(mesh_ref)
    if not names:
        return
    if material is not None and material not in names[0]:
        rep.error(f"{path}.material", f"material '{material}' not in {ctx.meshes[mesh_ref]['uri']}")
    for n in nodes:
        if n not in names[1]:
            rep.error(f"{path}.nodes", f"prim '{n}' not in {ctx.meshes[mesh_ref]['uri']}")


def _extent_ok(rep, path, e):
    if e[2] <= e[0] or e[3] <= e[1]:
        rep.error(path, "extent must be [x_min, y_min, x_max, y_max]")
        return False
    return True


PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _png_header(path):
    """(width, height, channels) from a PNG's IHDR, without decoding the image."""
    head = Path(path).read_bytes()[:33]
    if head[:8] != core.PNG_MAGIC:
        raise core.StjLoadError(f"{Path(path).name}: not a PNG file")
    width, height, _depth, ctype = struct.unpack(">IIBB", head[16:26])
    return width, height, PNG_CHANNELS.get(ctype, 1)


def check_terrain_macro(ctx, ter, p):
    """Macro maps over a heightfield (spec §7.4, §8.7)."""
    rep = ctx.rep
    maps = ter.get("macro") or []
    if not maps:
        return
    hm_ext = ter["heightmap"]["extent"]
    has_ground = any("ground_layer" in l for l in ter.get("layers", []))
    if sum(1 for m in maps if m.get("encoding") == "colour") > 1:
        rep.warn(f"{p}.macro", "more than one colour map: each replaces the layers' mean colour in turn, only the last shows")
    for i, m in enumerate(maps):
        mp = f"{p}.macro[{i}]"
        enc = m.get("encoding", "grey_centred")
        if "strength" in m and enc != "colour":
            rep.note(f"{mp}.strength", f"only the colour encoding uses strength; ignored for {enc}")
        if enc == "colour" and m.get("kind") == "occlusion":
            rep.warn(f"{mp}.kind", "the colour encoding is an average colour, not occlusion: use kind 'tint'")
        if enc in ("colour", "multiply") and not has_ground:
            rep.note(mp, "the terrain has no ground layers: the map acts on the base colour only")
        ext = m.get("extent", hm_ext)
        if "extent" in m and _extent_ok(rep, f"{mp}.extent", ext):
            ix = max(0.0, min(ext[2], hm_ext[2]) - max(ext[0], hm_ext[0]))
            iy = max(0.0, min(ext[3], hm_ext[3]) - max(ext[1], hm_ext[1]))
            area = (hm_ext[2] - hm_ext[0]) * (hm_ext[3] - hm_ext[1])
            share = ix * iy / area if area > 0 else 0.0
            if share < 0.9:
                rep.warn(f"{mp}.extent", f"covers {share * 100:.0f} % of the terrain: the rest has no macro")
        f = ctx.file(m["uri"])
        if not f.is_file():
            rep.warn(f"{mp}.uri", f"file not found: {m['uri']}")
            continue
        try:
            w, h, ch = _png_header(f)
        except (core.StjLoadError, OSError, struct.error) as e:
            rep.error(f"{mp}.uri", str(e))
            continue
        if w < 2 or h < 2:
            rep.error(f"{mp}.uri", f"image is {w} x {h}: a raster over an extent needs at least 2 x 2")
        if enc == "colour" and ch < 3:
            rep.warn(f"{mp}.uri", "a colour map is expected to be RGB or RGBA; this one is greyscale and has no hue")


def check_terrain(ctx):
    """Grid rules, layers and terrain-above-road sampling (spec §7.4)."""
    ter = (ctx.doc.get("geometry") or {}).get("terrain")
    if ter:
        check_one_terrain(ctx, ter, "geometry.terrain")


def check_one_terrain(ctx, ter, p):
    rep = ctx.rep
    hm = ter["heightmap"]
    nx, ny = hm["size"]
    ext_ok = _extent_ok(rep, f"{p}.heightmap.extent", hm["extent"])
    if hm["format"] == "png16" and not hm.get("height_min", 0) < hm.get("height_max", 0):
        rep.error(f"{p}.heightmap", "png16 needs height_min < height_max")
    if ext_ok:
        dx = (hm["extent"][2] - hm["extent"][0]) / (nx - 1)
        dy = (hm["extent"][3] - hm["extent"][1]) / (ny - 1)
        if abs(dx - dy) > 1e-6 * max(dx, dy):
            rep.warn(f"{p}.heightmap", f"cells are {dx:.3f} x {dy:.3f} m; terrain engines need square cells")
        if any((n - 1) & (n - 2) for n in (nx, ny)):
            rep.note(f"{p}.heightmap.size", f"{nx} x {ny}: UE, Unity and RoR need 2^n + 1 samples per side; converters will resample")
    _dups(rep, f"{p}.layers", ter.get("layers", []), "layer")
    for i, layer in enumerate(ter.get("layers", [])):
        lp = f"{p}.layers[{i}]"
        ctx.used_surfaces.add(layer["surface"])
        if layer["surface"] not in ctx.surface_ids:
            rep.error(f"{lp}.surface", f"unknown surface '{layer['surface']}'")
        if i == 0 and "weight" in layer:
            rep.warn(f"{lp}.weight", "the first layer is the base: its weight is 1 minus the others, this map is ignored")
        if i > 0 and "weight" not in layer:
            rep.warn(lp, "no weight map: this layer never shows")
        if "weight" in layer and not ctx.file(layer["weight"]["uri"]).is_file():
            rep.warn(f"{lp}.weight.uri", f"file not found: {layer['weight']['uri']}")
        if "material" in layer:
            _mesh_has(ctx, rep, f"{lp}.material", layer["material"]["mesh_ref"], layer["material"]["material"])
    check_terrain_macro(ctx, ter, p)
    files = [hm["uri"]] + ([ter["holes"]["uri"]] if "holes" in ter else [])
    missing = [u for u in files if not ctx.file(u).is_file()]
    for u in missing:
        rep.warn(p, f"file not found: {u}")
    if missing or not ext_ok:
        return
    try:
        terrain = core.Terrain(ter, ctx.base_dir)
    except (core.StjLoadError, OSError, ValueError) as e:
        rep.error(p, str(e))
        return
    if terrain.height_channels > 1:
        rep.note(f"{p}.heightmap.uri", f"{terrain.height_channels}-channel PNG: only the first channel is the height")
    if terrain.holes is not None and (terrain.holes.width, terrain.holes.height) != (nx, ny):
        rep.error(f"{p}.holes", f"mask is {terrain.holes.width} x {terrain.holes.height}, heightmap is {nx} x {ny}")
        return
    if ctx.line:
        above = []
        s = 0.0
        while s <= ctx.line.length:
            x, y, z, _h = ctx.line.frame(s)
            h = terrain.height(x, y)
            if h is not None and h > z + 0.02 and not terrain.is_hole(x, y):
                above.append((s, h - z))
            s += 2.0
        if above:
            worst = max(above, key=lambda a: a[1])
            rep.warn(p, f"terrain rises above the road at {len(above)} of the sampled points (2 m apart), "
                        f"worst {worst[1]:.2f} m at s = {worst[0]:.0f}: lower it or cut holes (spec §7.4)")


POLYGON_BODIES = {"sea", "lake", "pond", "puddle", "pool"}
PATH_BODIES = {"river", "stream", "ford"}


def check_water(ctx):
    """Water bodies, accumulation, drains, shelter and the dry line (spec §6.9, §7.5)."""
    rep = ctx.rep
    w = ctx.doc.get("water")
    if not w:
        return
    bodies = w.get("bodies", [])
    _dups(rep, "water.bodies", bodies, "water body")
    for i, b in enumerate(bodies):
        p = f"water.bodies[{i}]"
        if b["kind"] in POLYGON_BODIES and "outline" not in b:
            rep.warn(p, f"a {b['kind']} is normally an outline with a level")
        if b["kind"] in PATH_BODIES and "path" not in b:
            rep.warn(p, f"a {b['kind']} is normally a path with widths and depths")
        for j, q in enumerate(b.get("path", [])):
            if q[3] <= 0 or q[4] <= 0:
                rep.error(f"{p}.path[{j}]", "width and depth must be positive")
            if q[4] > 50:
                rep.warn(f"{p}.path[{j}]", f"{q[4]} m deep: depths are in metres")
        if "bed_surface" in b:
            ctx.used_surfaces.add(b["bed_surface"])
            if b["bed_surface"] not in ctx.surface_ids:
                rep.error(f"{p}.bed_surface", f"unknown surface '{b['bed_surface']}'")
        if b.get("drivable") and b.get("out_of_bounds"):
            rep.error(p, "a body cannot be both drivable and out of bounds")
        if b["kind"] == "ford" and b.get("drivable") is False:
            rep.warn(f"{p}.drivable", "a ford that cannot be driven through")
        if "fill" in b and b["kind"] != "puddle":
            rep.note(f"{p}.fill", "fill is meant for puddles")
        if b.get("mesh"):
            _mesh_has(ctx, rep, f"{p}.mesh", b["mesh"]["mesh_ref"], nodes=[b["mesh"]["prim"]] if "prim" in b["mesh"] else ())
    if "sea_level" in w and ctx.line:
        low = [s for s, (x, y, z, _h) in ((s, ctx.line.frame(s)) for s in ctx.line.s) if z < w["sea_level"]]
        if low:
            rep.warn("water.sea_level", f"{len(low)} reference-line points lie below sea level")
    acc = w.get("accumulation")
    if acc and _extent_ok(rep, "water.accumulation.extent", acc["extent"]):
        if not ctx.file(acc["uri"]).is_file():
            rep.warn("water.accumulation.uri", f"file not found: {acc['uri']}")
        else:
            try:
                img = core.read_png(ctx.file(acc["uri"]))
                if img.channels != 1:
                    rep.warn("water.accumulation.uri", "use a greyscale PNG; only the first channel is read")
            except core.StjLoadError as e:
                rep.error("water.accumulation.uri", str(e))
    for i, b in enumerate(w.get("accumulation_bands", [])):
        check_band(ctx, f"water.accumulation_bands[{i}]", {**b, "surface": None})
    _dups(rep, "water.drains", w.get("drains", []), "drain")
    for i, d in enumerate(w.get("drains", [])):
        if "band" in d:
            check_band(ctx, f"water.drains[{i}].band", {**d["band"], "surface": None})
        if d["capacity"] > 1000:
            rep.warn(f"water.drains[{i}].capacity", f"{d['capacity']} mm/h: capacity is in mm/h")
    _dups(rep, "water.shelter", w.get("shelter", []), "shelter")
    for i, sh in enumerate(w.get("shelter", [])):
        if "band" in sh:
            check_band(ctx, f"water.shelter[{i}].band", {**sh["band"], "surface": None})
    dl = w.get("dry_line")
    if dl:
        lines = {l["id"] for l in (ctx.doc.get("race") or {}).get("racing_lines", [])}
        if dl["line"] not in lines:
            rep.error("water.dry_line.line", f"unknown racing line '{dl['line']}'")
        if dl["spread"] > 5:
            rep.warn("water.dry_line.spread", f"{dl['spread']} m: spread is one standard deviation across the line")


def check_surfaces_v02(ctx):
    """Surface water blocks, substitutions and line states (spec §6.3, §6.8, §6.9)."""
    rep = ctx.rep
    surf = ctx.doc.get("surfaces") or {}
    lib = surf.get("library") or {}
    for sid, s in lib.items():
        if sid.startswith(("x_", "_")) or not isinstance(s, dict):
            continue
        wb = s.get("water") or {}
        if wb.get("storage_depth", 0) > 0.01:
            rep.warn(f"surfaces.library.{sid}.water.storage_depth", f"{wb['storage_depth']} m: depths are in metres")
        if wb.get("drain_rate", 0) > 1000:
            rep.warn(f"surfaces.library.{sid}.water.drain_rate", f"{wb['drain_rate']} mm/h: drain rate is in mm/h")
    subs = surf.get("substitutions") or {}
    for src, dst in subs.items():
        p = f"surfaces.substitutions.{src}"
        for sid in (src, dst):
            if sid not in ctx.surface_ids:
                rep.error(p, f"unknown surface '{sid}'")
        ctx.used_surfaces.add(dst)
        if src == dst:
            rep.error(p, "a surface substituted by itself")
        elif dst in subs:
            rep.error(p, f"'{dst}' is itself substituted: substitution is one step, no chains")
    states = surf.get("line_states", [])
    _dups(rep, "surfaces.line_states", states, "line state")
    lines = {l["id"] for l in (ctx.doc.get("race") or {}).get("racing_lines", [])}
    for i, st in enumerate(states):
        p = f"surfaces.line_states[{i}]"
        if st["line"] not in lines:
            rep.error(f"{p}.line", f"unknown racing line '{st['line']}'")
        for j, sid in enumerate(st.get("applies_to", [])):
            if sid not in ctx.surface_ids:
                rep.error(f"{p}.applies_to[{j}]", f"unknown surface '{sid}'")
                continue
            s = lib[sid]
            loose = s.get("class") in LOOSE_CLASSES
            if st["kind"] == "rubber" and loose:
                rep.warn(f"{p}.applies_to[{j}]", f"rubber on a loose '{s.get('class')}' surface: use kind 'swept'")
            if st["kind"] == "swept" and not s.get("deformable"):
                rep.warn(f"{p}.applies_to[{j}]", f"'{sid}' has no deformable layer to sweep")
        for k, g in (st.get("grip_gain") or {}).items():
            if not k.startswith("_") and abs(g) > 0.5:
                rep.warn(f"{p}.grip_gain.{k}", f"{g}: a gain above 0.5 changes grip by more than 50%")
        if "loose_layer_factor" in st and st["kind"] != "swept":
            rep.note(f"{p}.loose_layer_factor", "only swept lines change the loose layer")
        if st["spread"] > 5:
            rep.warn(f"{p}.spread", f"{st['spread']} m: spread is one standard deviation across the line")
        prof = st.get("profile") or []
        if any(b[0] <= a[0] for a, b in zip(prof, prof[1:])):
            rep.error(f"{p}.profile", "s must increase")
        for j, q in enumerate(prof):
            check_s(ctx, f"{p}.profile[{j}]", q[0])


def check_props(ctx):
    """Rigid-body data of prototypes and how they are placed (spec §8.4)."""
    rep = ctx.rep
    sc = ctx.doc.get("scenery") or {}
    protos = sc.get("prototypes") or {}
    physical = set()
    for pid, pr in protos.items():
        ph = pr.get("physics") if isinstance(pr, dict) and not pid.startswith(("x_", "_")) else None
        if not ph:
            continue
        p = f"scenery.prototypes.{pid}.physics"
        if ph["mode"] != "static":
            physical.add(pid)
        if ph["mode"] != "static" and "mass" not in ph:
            rep.error(p, f"mode '{ph['mode']}' needs a mass")
        if ph["mode"] == "tethered" and "tether" not in ph:
            rep.error(p, "mode 'tethered' needs a tether")
        if ph["mode"] == "breakable" and "break_impulse" not in ph:
            rep.warn(p, "breakable without break_impulse: engines will guess")
        inertia = ph.get("inertia")
        if inertia:
            a, b, c = inertia
            if a > b + c + 1e-9 or b > a + c + 1e-9 or c > a + b + 1e-9:
                rep.error(f"{p}.inertia", "violates the triangle inequality (each moment ≤ sum of the other two)")
        if ph.get("mass", 0) > 50000:
            rep.warn(f"{p}.mass", f"{ph['mass']} kg: mass is in kg")
        shape = ph.get("shape") or {}
        need = {"box": ("size",), "cylinder": ("radius", "height"), "capsule": ("radius", "height"),
                "sphere": ("radius",)}.get(shape.get("kind"), ())
        for k in need:
            if k not in shape:
                rep.error(f"{p}.shape", f"a {shape['kind']} needs {k}")
        if shape.get("kind") == "mesh" and "mesh" not in pr:
            rep.error(f"{p}.shape", "shape 'mesh' needs the prototype's mesh")
    for i, ins in enumerate(sc.get("instances", [])):
        if ins["prototype"] in physical:
            for j, t in enumerate(ins.get("transforms", [])):
                if len(t) == 5 and abs(t[4] - 1) > 1e-9:
                    rep.warn(f"scenery.instances[{i}].transforms[{j}][4]",
                             f"physical prop '{ins['prototype']}' scaled by {t[4]}: physics values are for scale 1")
    for i, e in enumerate(ctx.doc.get("edges") or []):
        if "prototype" in e and e["prototype"] not in ctx.prototype_ids:
            rep.error(f"edges[{i}].prototype", f"unknown prototype '{e['prototype']}'")
        if "spacing" in e and "prototype" not in e:
            rep.warn(f"edges[{i}].spacing", "spacing without a prototype")


def check_animated(ctx):
    """Targets and time ranges (spec §8.5)."""
    rep = ctx.rep
    objs = ctx.doc.get("animated_objects") or []
    _dups(rep, "animated_objects", objs, "animated object")
    for i, a in enumerate(objs):
        p = f"animated_objects[{i}]"
        tgt = a["target"]
        _mesh_has(ctx, rep, f"{p}.target", tgt["mesh_ref"], nodes=tgt["nodes"])
        if a["time_range"][1] <= a["time_range"][0]:
            rep.error(f"{p}.time_range", "end must be after start")
        if "time_by" in a and "playback" in a:
            rep.note(f"{p}.playback", "ignored: time_by scrubs the animation")


AUDIO_EXT = {".wav", ".ogg", ".flac"}


def check_audio(ctx):
    """Emitters and reverb zones (spec §8.6)."""
    rep = ctx.rep
    au = ctx.doc.get("audio")
    if not au:
        return
    _dups(rep, "audio.emitters", au.get("emitters", []), "emitter")
    for i, e in enumerate(au.get("emitters", [])):
        p = f"audio.emitters[{i}]"
        if "position" in e and "path" in e:
            rep.warn(p, "both position and path: a point source or a line source, not both")
        if e.get("ref_distance", 0) and e.get("max_distance") and e["ref_distance"] >= e["max_distance"]:
            rep.error(p, "ref_distance must be smaller than max_distance")
        uri = e["sound"]["uri"]
        if Path(uri).suffix.lower() not in AUDIO_EXT:
            rep.warn(f"{p}.sound.uri", "use WAV, Ogg Vorbis or FLAC; engine sound banks go in x_<engine>")
        if not ctx.file(uri).is_file():
            rep.warn(f"{p}.sound.uri", f"file not found: {uri}")
        if e.get("gain", 1) > 10:
            rep.warn(f"{p}.gain", f"{e['gain']}: gain is linear, not dB")
        cone = e.get("cone") or {}
        if "inner_angle" in cone and "outer_angle" in cone and cone["inner_angle"] > cone["outer_angle"]:
            rep.error(f"{p}.cone", "inner_angle must not exceed outer_angle")
    _dups(rep, "audio.zones", au.get("zones", []), "zone")
    for i, z in enumerate(au.get("zones", [])):
        p = f"audio.zones[{i}].shape"
        sh = z["shape"]
        if "band" in sh:
            check_band(ctx, f"{p}.band", {**sh["band"], "surface": None})
        if "z_min" in sh and "z_max" in sh and sh["z_min"] >= sh["z_max"]:
            rep.error(p, "z_min must be smaller than z_max")
        if sum(k in sh for k in ("band", "polygon", "sphere")) != 1:
            rep.error(p, "give exactly one of band, polygon, sphere")


def check_track_info(ctx):
    """Media, minimap and records (spec §5.1)."""
    rep = ctx.rep
    info = ctx.doc.get("track_info") or {}
    for k, uri in (info.get("media") or {}).items():
        if not ctx.file(uri).is_file():
            rep.warn(f"track_info.media.{k}", f"file not found: {uri}")
    m = info.get("map")
    if m:
        _extent_ok(rep, "track_info.map.extent", m["extent"])
        if not ctx.file(m["uri"]).is_file():
            rep.warn("track_info.map.uri", f"file not found: {m['uri']}")
    for i, r in enumerate(info.get("records", [])):
        if r["time"] > 36000:
            rep.warn(f"track_info.records[{i}].time", f"{r['time']} s: times are in seconds")


def check_v02_extras(ctx):
    """Environment additions, and v0.2 keys in a file that declares v0.1."""
    rep, doc = ctx.rep, ctx.doc
    env = doc.get("environment") or {}
    season = env.get("season") or {}
    if season.get("snow_depth", 0) > 5:
        rep.warn("environment.season.snow_depth", f"{season['snow_depth']} m of snow: depths are in metres")
    for p, wx in [("environment.default_weather", env.get("default_weather") or {})] + \
                 [(f"environment.weather_schedule[{i}].weather", e["weather"]) for i, e in enumerate(env.get("weather_schedule", []))]:
        if wx.get("precipitation", 0) > 300:
            rep.warn(f"{p}.precipitation", f"{wx['precipitation']} mm/h is beyond any recorded rain rate")
    for i, lt in enumerate((env.get("lighting") or {}).get("lights", [])):
        if "when" in lt and "schedule" in lt:
            rep.note(f"environment.lighting.lights[{i}]", "both schedule and when: when wins")
    if (doc.get("_metadata") or {}).get("version") == "0.1":
        found = [k for k in ("water", "audio", "animated_objects") if k in doc]
        found += ["geometry.terrain"] * ("terrain" in (doc.get("geometry") or {}))
        found += [f"surfaces.{k}" for k in ("substitutions", "line_states") if k in (doc.get("surfaces") or {})]
        found += ["environment.season"] * ("season" in env)
        found += ["ground"] * ("ground" in doc)
        sig = []
        _walk_signals(doc, "", sig)
        found += [p for p, _k, _n in sig[:1]]
        if found:
            rep.warn("_metadata.version", f"declares 0.1 but uses v0.2 features: {', '.join(found[:4])}")


def check_ground(ctx):
    """Ground layers, layered materials and their USD primvars (spec §8.7)."""
    rep, doc = ctx.rep, ctx.doc
    gr = doc.get("ground") or {}
    layers = {k: v for k, v in (gr.get("layers") or {}).items() if not k.startswith(("x_", "_"))}
    used = set()
    for lid, lay in layers.items():
        p = f"ground.layers.{lid}"
        for k in ("albedo", "normal", "height"):
            if k in lay and not ctx.file(lay[k]["uri"]).is_file():
                rep.warn(f"{p}.{k}.uri", f"file not found: {lay[k]['uri']}")
        if not 0.05 <= lay["tile"] <= 1000:
            rep.warn(f"{p}.tile", f"{lay['tile']} m per repeat: tile is metres per repeat, not repeats per metre")
        if "surface" in lay:
            ctx.used_surfaces.add(lay["surface"])
            if lay["surface"] not in ctx.surface_ids:
                rep.error(f"{p}.surface", f"unknown surface '{lay['surface']}'")
        if lay.get("projection") == "road" and not ctx.line:
            rep.error(f"{p}.projection", "'road' projection needs a reference centerline")
    for i, tl in enumerate(((doc.get("geometry") or {}).get("terrain") or {}).get("layers", [])):
        if "ground_layer" in tl:
            used.add(tl["ground_layer"])
            if tl["ground_layer"] not in layers:
                rep.error(f"geometry.terrain.layers[{i}].ground_layer", f"unknown ground layer '{tl['ground_layer']}'")
            if "material" in tl:
                rep.note(f"geometry.terrain.layers[{i}]", "both ground_layer and material: ground_layer wins")
    cache = {}
    for i, gm in enumerate(gr.get("materials", [])):
        p = f"ground.materials[{i}]"
        pal = gm["palette"]
        used.update(pal)
        for j, lid in enumerate(pal):
            if lid not in layers:
                rep.error(f"{p}.palette[{j}]", f"unknown ground layer '{lid}'")
        for dup in sorted({x for x in pal if pal.count(x) > 1}):
            rep.warn(f"{p}.palette", f"'{dup}' appears twice")
        w = gm["weights"]
        enc = w["encoding"]
        if enc in ("image", "id_map"):
            if "maps" not in w:
                rep.error(f"{p}.weights", f"encoding '{enc}' needs maps")
            elif enc == "image":
                chans = sum(1 if m.get("channels", "rgba") == "gray" else len(m.get("channels", "rgba")) for m in w["maps"])
                if chans < len(pal):
                    rep.error(f"{p}.weights.maps", f"{chans} channels for {len(pal)} palette layers")
            elif len(w["maps"]) != 1:
                rep.error(f"{p}.weights.maps", "id_map takes exactly one map")
            if ("texcoord" in w) == ("extent" in w):
                rep.error(f"{p}.weights", "give either texcoord or extent")
            for j, m in enumerate(w.get("maps", [])):
                if not ctx.file(m["uri"]).is_file():
                    rep.warn(f"{p}.weights.maps[{j}].uri", f"file not found: {m['uri']}")
        if enc == "vertex_dense" and len(w.get("attributes", [])) * 4 < len(pal):
            rep.error(f"{p}.weights.attributes", f"{len(w.get('attributes', []))} VEC4 attributes cannot hold {len(pal)} layers")
        blend = gm.get("blend") or {}
        if blend.get("method", "height") == "height" and not any(
                layers.get(l, {}).get("height") or layers.get(l, {}).get("albedo", {}).get("height_in_alpha") for l in pal):
            rep.warn(f"{p}.blend", "height blend, but no palette layer has a height (albedo alpha or height map)")
        for j, mc in enumerate(gm.get("macro", [])):
            if not ctx.file(mc["uri"]).is_file():
                rep.warn(f"{p}.macro[{j}].uri", f"file not found: {mc['uri']}")
        if gm["mesh_ref"] not in ctx.meshes:
            rep.error(f"{p}.mesh_ref", f"unknown mesh '{gm['mesh_ref']}'")
            continue
        if gm["mesh_ref"] not in ctx.mesh_names:
            continue
        tcs = [layers[l]["projection"]["texcoord"] for l in pal if isinstance(layers.get(l, {}).get("projection"), dict)]
        tcs += [w["texcoord"]] if "texcoord" in w else []
        tcs += [mc.get("texcoord", "st") for mc in gm.get("macro", []) if "extent" not in mc]
        check_usd_palette(ctx, p, gm["mesh_ref"], gm["material"], w, len(pal), tcs)
    for lid in sorted(set(layers) - used):
        rep.note(f"ground.layers.{lid}", "not used by any ground material or terrain layer")


def check_chainage(ctx):
    """Stored chainage and Hermite tangents on the centerline (spec §7.1)."""
    rep = ctx.rep
    cl = (ctx.doc.get("reference") or {}).get("centerline") or {}
    n = len(cl.get("points", []))
    ch = cl.get("chainage")
    if ch is not None:
        p = "reference.centerline.chainage"
        if len(ch) != n:
            rep.error(p, f"{len(ch)} values for {n} points")
        elif ch[0] != 0:
            rep.error(p, "must start at 0 (keep a survey's kilometre-post offset in a _note)")
        elif any(b <= a for a, b in zip(ch, ch[1:])):
            rep.error(p, "must increase")
        elif ctx.line and abs(ctx.line.length - ctx.line.geometric_length) > 0.01 * ctx.line.geometric_length:
            rep.warn(p, f"chainage gives {ctx.line.length:.1f} m, the geometry {ctx.line.geometric_length:.1f} m: more than 1% apart")
    tans = cl.get("tangents")
    if tans is not None:
        p = "reference.centerline.tangents"
        if len(tans) != n:
            rep.error(p, f"{len(tans)} tangents for {n} points")
        elif ctx.line:
            pts = ctx.line.points
            for i in range(len(pts) - 1):
                chord = math.dist(pts[i][:2], pts[i + 1][:2])
                for j in (i, i + 1):
                    mag = math.hypot(*ctx.line.tangents[j][:2])
                    if chord > 1e-6 and not 0.3 <= mag / chord <= 3.0:
                        rep.warn(f"{p}[{j % n}]", f"tangent length {mag:.1f} m against a {chord:.1f} m segment: "
                                                  "tangents are dP/du over the segment, about its length")
                        break


def check_surface_maps(ctx):
    """Surfaces that vary inside collision primitives (spec §6.3)."""
    rep = ctx.rep
    maps = (ctx.doc.get("surfaces") or {}).get("maps", [])
    for i, sm in enumerate(maps):
        p = f"surfaces.maps[{i}]"
        for j, sid in enumerate(sm["palette"]):
            ctx.used_surfaces.add(sid)
            if sid not in ctx.surface_ids:
                rep.error(f"{p}.palette[{j}]", f"unknown surface '{sid}'")
        mesh = ctx.meshes.get(sm["mesh_ref"])
        if mesh is None:
            rep.error(f"{p}.mesh_ref", f"unknown mesh '{sm['mesh_ref']}'")
            continue
        if "collision" not in mesh.get("roles", []):
            rep.warn(f"{p}.mesh_ref", f"mesh '{sm['mesh_ref']}' has no 'collision' role")
        if i > 0 and "when" not in maps[i - 1] and any(m["mesh_ref"] == sm["mesh_ref"] and m["material"] == sm["material"]
                                                       for m in maps[:i]):
            rep.warn(p, "an earlier map for the same material has no condition, so this one is never used")
        w = sm["weights"]
        if w["encoding"] in ("image", "id_map") and ("texcoord" in w) == ("extent" in w):
            rep.error(f"{p}.weights", "give either texcoord or extent")
        if sm["mesh_ref"] not in ctx.mesh_names:
            continue
        check_usd_palette(ctx, p, sm["mesh_ref"], sm["material"], w, len(sm["palette"]),
                          [w["texcoord"]] if "texcoord" in w else [])


def check_mu(ctx):
    """Absolute mu per tyre class against surfaces.reference_mu (spec §6.5)."""
    rep = ctx.rep
    surf = ctx.doc.get("surfaces") or {}
    ref = surf.get("reference_mu") or {}
    for cls, mu in ref.items():
        if cls.startswith("_"):
            continue
        if not 0.3 <= mu["peak"] <= 3.0:
            rep.warn(f"surfaces.reference_mu.{cls}.peak", f"{mu['peak']}: a tyre's peak mu on dry asphalt is usually 0.8..2")
        if mu.get("sliding", 0) > mu["peak"]:
            rep.warn(f"surfaces.reference_mu.{cls}", "sliding mu above peak mu")
    for sid, s in (surf.get("library") or {}).items():
        if sid.startswith(("x_", "_")) or not isinstance(s, dict):
            continue
        for cls, ov in (s.get("by_tyre_class") or {}).items():
            mu = ov.get("mu") if isinstance(ov, dict) else None
            if not mu:
                continue
            p = f"surfaces.library.{sid}.by_tyre_class.{cls}.mu"
            if cls not in ref:
                rep.error(p, f"absolute mu needs surfaces.reference_mu.{cls}")
            if mu.get("sliding", 0) > mu["peak"]:
                rep.warn(p, "sliding mu above peak mu")
            if {"LMUX", "LMUY"} & set((ov.get("mf_scaling") or {})):
                rep.note(p, "mu replaces LMUX and LMUY of the same entry")
        rough = (s.get("roughness") or {}).get("sinusoid")
        if rough and rough["amplitude"] > 0.5:
            rep.warn(f"surfaces.library.{sid}.roughness.sinusoid.amplitude", f"{rough['amplitude']} m: amplitudes are in metres")
        eff = (s.get("deformable") or {}).get("effective") or {}
        if "base_offset" in eff and eff.get("sinkage", 0) > eff["base_offset"]:
            rep.warn(f"surfaces.library.{sid}.deformable.effective", "sinkage deeper than base_offset, where the hard ground is")


def check_rbr_lessons(ctx):
    """Invisible edges, bendable props, sections, weather options, reflections, pace-note hints."""
    rep, doc = ctx.rep, ctx.doc
    for i, e in enumerate(doc.get("edges") or []):
        p = f"edges[{i}]"
        if e["kind"] == "invisible":
            if "behaviour" not in e:
                rep.error(p, "an invisible edge needs a behaviour (drag, sensor or respawn)")
            elif e["behaviour"] == "drag" and "drag_coefficient" not in e:
                rep.warn(p, "drag behaviour without drag_coefficient: engines will guess")
        elif "behaviour" in e or "drag_coefficient" in e:
            rep.note(p, "behaviour and drag_coefficient only apply to invisible edges")
        if e.get("tearable") and e.get("style") not in ("tape", "fence", "debris_fence", "other"):
            rep.note(f"{p}.tearable", f"a tearable {e.get('style', e['kind'])}?")
    for pid, pr in ((doc.get("scenery") or {}).get("prototypes") or {}).items():
        ph = pr.get("physics") if isinstance(pr, dict) else None
        if ph and ph["mode"] == "bendable" and "stiffness" not in ph:
            rep.warn(f"scenery.prototypes.{pid}.physics", "bendable without stiffness: engines will guess")
    secs = (doc.get("race") or {}).get("sections", [])
    _dups(rep, "race.sections", secs, "section")
    prev_end = None
    for i, sc in enumerate(secs):
        p = f"race.sections[{i}]"
        ok = check_s(ctx, f"{p}.s_start", sc["s_start"]) & check_s(ctx, f"{p}.s_end", sc["s_end"])
        if ok and sc["s_end"] <= sc["s_start"] and not ctx.lapped():
            rep.error(p, "s_end must be after s_start")
        if prev_end is not None and sc["s_start"] < prev_end - TOL and not ctx.lapped():
            rep.warn(p, "overlaps the previous section")
        prev_end = sc["s_end"]
        if "surface" in sc:
            ctx.used_surfaces.add(sc["surface"])
            if sc["surface"] not in ctx.surface_ids:
                rep.error(f"{p}.surface", f"unknown surface '{sc['surface']}'")
    variants = {v["id"] for v in doc.get("variants", [])}
    for i, wo in enumerate((doc.get("environment") or {}).get("weather_options", [])):
        p = f"environment.weather_options[{i}]"
        if "variant" in wo and wo["variant"] not in variants:
            rep.error(f"{p}.variant", f"unknown variant '{wo['variant']}'")
        if "weather" in wo:
            check_weather(rep, f"{p}.weather", wo["weather"])
        if "variant" not in wo and "weather" not in wo:
            rep.warn(p, "neither a variant nor a weather: the option says nothing")
    refl = (doc.get("audio") or {}).get("reflections", [])
    for j, row in enumerate(refl):
        if j and row[0] <= refl[j - 1][0]:
            rep.error(f"audio.reflections[{j}]", "s must increase")
        if row[1] < 0 or row[2] < 0:
            rep.error(f"audio.reflections[{j}]", "distances must not be negative")
        check_s(ctx, f"audio.reflections[{j}]", row[0])
    notes = ((doc.get("race") or {}).get("pacenotes") or {}).get("notes", [])
    for i, (n, nxt) in enumerate(zip(notes, notes[1:] + [None])):
        p = f"race.pacenotes.notes[{i}]"
        if abs(n.get("call_adjust", 0)) > 5:
            rep.warn(f"{p}.call_adjust", f"{n['call_adjust']} s: call_adjust is in seconds")
        if "distance_to_next" in n and nxt is not None:
            gap = nxt["s"] - n["s"]
            if abs(n["distance_to_next"] - gap) > max(15.0, 0.25 * gap):
                rep.warn(f"{p}.distance_to_next", f"{n['distance_to_next']} m, but the next note is {gap:.0f} m away")


def _coverage(rep, ctx, p, items, what):
    """Ranges in order along s; gaps and overlaps reported (lap distance on closed lines)."""
    prev = None
    for i, it in enumerate(items):
        ok = check_s(ctx, f"{p}[{i}].s_start", it["s_start"]) & check_s(ctx, f"{p}[{i}].s_end", it["s_end"])
        if ok and not ctx.lapped() and it["s_end"] <= it["s_start"]:
            rep.error(f"{p}[{i}]", "s_end must be after s_start")
        if prev is not None and ok and abs(lap_d(ctx, it["s_start"], prev)) > TOL and lap_d(ctx, it["s_start"], prev) < (ctx.length or 0) - TOL:
            rep.warn(f"{p}[{i}].s_start", f"{what} do not join: the previous one ends at {prev:.1f}")
        prev = it["s_end"]


def check_marshals(ctx):
    """Marshal sectors, posts, vehicles, restricted zones and reset rules (spec §10.1)."""
    rep, doc = ctx.rep, ctx.doc
    m = doc.get("marshals")
    sig = []
    _walk_signals({k: v for k, v in doc.items() if k not in ("layouts", "variants")}, "", sig)
    if any(n["signal"] == "sector_flag" for _p, _k, n in sig) and not (m or {}).get("sectors"):
        rep.warn("marshals.sectors", "sector_flag is used, but no marshal sectors are defined")
    if not m:
        return
    sectors = m.get("sectors", [])
    _dups(rep, "marshals.sectors", sectors, "sector")
    _coverage(rep, ctx, "marshals.sectors", sectors, "sectors")
    by_id = {x["id"]: x for x in sectors}
    posts = m.get("posts", [])
    _dups(rep, "marshals.posts", posts, "post")
    for i, po in enumerate(posts):
        p = f"marshals.posts[{i}]"
        if "s" not in po and "position" not in po:
            rep.warn(p, "neither s nor position: the post has no place")
        if "s" in po:
            check_s(ctx, f"{p}.s", po["s"])
        sec = po.get("sector")
        if sec is not None:
            if sec not in by_id:
                rep.error(f"{p}.sector", f"unknown sector '{sec}'")
            elif "s" in po:
                a, b = by_id[sec]["s_start"], by_id[sec]["s_end"]
                inside = a <= po["s"] <= b if a <= b else (po["s"] >= a or po["s"] <= b)
                if not inside:
                    rep.warn(f"{p}.s", f"s = {po['s']} is outside sector '{sec}' ({a}..{b})")
        if po["kind"] == "radio_point" and po.get("signals"):
            rep.note(f"{p}.signals", "a radio point does not usually show flags")
    post_ids = {po["id"] for po in posts}
    for i, v in enumerate(m.get("vehicles", [])):
        p = f"marshals.vehicles[{i}]"
        if "base" in v and v["base"] not in post_ids:
            rep.error(f"{p}.base", f"unknown post '{v['base']}'")
        if "pose" in v:
            pose_s(ctx, f"{p}.pose", v["pose"])
        if "pose" not in v and "base" not in v:
            rep.warn(p, "neither pose nor base: the vehicle has no place")
    _dups(rep, "marshals.vehicles", m.get("vehicles", []), "vehicle")
    _dups(rep, "marshals.restricted_zones", m.get("restricted_zones", []), "zone")
    for i, z in enumerate(m.get("restricted_zones", [])):
        p = f"marshals.restricted_zones[{i}]"
        if "band" in z["shape"]:
            check_band(ctx, f"{p}.shape.band", {**z["shape"]["band"], "surface": None})
        if z["rule"] in ("penalty", "speed_limit") and "value" not in z:
            rep.error(p, f"rule '{z['rule']}' needs a value")
        if z["rule"] == "speed_limit" and z.get("value", 0) > 25:
            rep.warn(f"{p}.value", f"{z['value']} m/s: speed limits are in m/s (km/h given?)")
    rs = m.get("reset") or {}
    for i, pt in enumerate(rs.get("points", [])):
        check_s(ctx, f"marshals.reset.points[{i}].s", pt["s"])
    if rs.get("mode") == "points_only" and not rs.get("points"):
        rep.error("marshals.reset", "mode 'points_only' without points")


def check_dynamic(ctx):
    """Parameters of the reference evolution laws (spec §6.10)."""
    rep, doc = ctx.rep, ctx.doc
    dyn = doc.get("dynamic")
    if not dyn:
        return
    states = {s["id"] for s in (doc.get("surfaces") or {}).get("line_states", [])}
    for i, ls in enumerate(dyn.get("line_states", [])):
        if ls["line_state"] not in states:
            rep.error(f"dynamic.line_states[{i}].line_state", f"unknown line state '{ls['line_state']}'")
    lines = {l["id"] for l in (doc.get("race") or {}).get("racing_lines", [])}
    lib = (doc.get("surfaces") or {}).get("library") or {}
    for i, r in enumerate(dyn.get("ruts", [])):
        p = f"dynamic.ruts[{i}]"
        if r["line"] not in lines:
            rep.error(f"{p}.line", f"unknown racing line '{r['line']}'")
        for j, sid in enumerate(r["surfaces"]):
            if sid not in ctx.surface_ids:
                rep.error(f"{p}.surfaces[{j}]", f"unknown surface '{sid}'")
            elif lib[sid].get("class") not in LOOSE_CLASSES:
                rep.warn(f"{p}.surfaces[{j}]", f"ruts on a '{lib[sid].get('class')}' surface")
        if r["max_depth"] > 0.5:
            rep.warn(f"{p}.max_depth", f"{r['max_depth']} m: depths are in metres")
        if r["depth_per_pass"] > r["max_depth"]:
            rep.error(p, "depth_per_pass cannot exceed max_depth")
    tt = dyn.get("track_temperature") or {}
    if tt.get("shade"):
        _extent_ok(rep, "dynamic.track_temperature.shade.extent", tt["shade"]["extent"])
        if not ctx.file(tt["shade"]["uri"]).is_file():
            rep.warn("dynamic.track_temperature.shade.uri", f"file not found: {tt['shade']['uri']}")
    if tt and not 60 <= tt["tau"] <= 86400:
        rep.warn("dynamic.track_temperature.tau", f"{tt['tau']} s: track temperature changes over minutes to hours")
    if tt.get("sun_gain", 0) > 40:
        rep.warn("dynamic.track_temperature.sun_gain", f"{tt['sun_gain']} K above air temperature is implausible")


def check_worlds(ctx):
    """Chunks with local origins, tiles and several terrains (spec §7.6)."""
    rep = ctx.rep
    geo = ctx.doc.get("geometry") or {}
    terrains = geo.get("terrains", [])
    for i, ter in enumerate(terrains):
        if "id" not in ter:
            rep.error(f"geometry.terrains[{i}]", "terrains in an array need an id")
        check_one_terrain(ctx, ter, f"geometry.terrains[{i}]")
    _dups(rep, "geometry.terrains", terrains, "terrain")
    ter_ids = {t["id"] for t in terrains if "id" in t}
    chunks = geo.get("chunks", [])
    tiles = (geo.get("tiles") or {}).get("items", [])
    _dups(rep, "geometry.chunks", chunks, "chunk")
    owners = {c["id"] for c in chunks}
    if chunks:
        _coverage(rep, ctx, "geometry.chunks", sorted(chunks, key=lambda c: c["s_start"]), "chunks")
    for i, c in enumerate(chunks):
        p = f"geometry.chunks[{i}]"
        for j, mid in enumerate(c.get("meshes", [])):
            if mid not in ctx.meshes:
                rep.error(f"{p}.meshes[{j}]", f"unknown mesh '{mid}'")
            elif ctx.meshes[mid].get("chunk") != c["id"]:
                rep.warn(f"{p}.meshes[{j}]", f"mesh '{mid}' does not say chunk '{c['id']}', so it is not placed at this origin")
        if "terrain" in c and c["terrain"] not in ter_ids:
            rep.error(f"{p}.terrain", f"unknown terrain '{c['terrain']}'")
    seen = set()
    for i, tl in enumerate(tiles):
        p = f"geometry.tiles.items[{i}]"
        key = tuple(tl["index"])
        if key in seen:
            rep.error(f"{p}.index", f"tile {list(key)} appears twice")
        seen.add(key)
        owners.add(f"tile_{key[0]}_{key[1]}")
        for j, mid in enumerate(tl.get("meshes", [])):
            if mid not in ctx.meshes:
                rep.error(f"{p}.meshes[{j}]", f"unknown mesh '{mid}'")
        if "terrain" in tl and tl["terrain"] not in ter_ids:
            rep.error(f"{p}.terrain", f"unknown terrain '{tl['terrain']}'")
    for i, m in enumerate(geo.get("meshes", [])):
        if "chunk" in m and m["chunk"] not in owners:
            rep.error(f"geometry.meshes[{i}].chunk", f"unknown chunk '{m['chunk']}' (tiles are named tile_<i>_<j>)")


def check_presentation(ctx):
    """Probes, screens, crowds and climate (spec §8.8, §11)."""
    rep, doc = ctx.rep, ctx.doc
    env = doc.get("environment") or {}
    _dups(rep, "environment.probes", env.get("probes", []), "probe")
    for i, s in enumerate(doc.get("screens", [])):
        p = f"screens[{i}]"
        tg = s["target"]
        _mesh_has(ctx, rep, f"{p}.target", tg["mesh_ref"], tg.get("material"), [tg["prim"]] if "prim" in tg else ())
        if s["content"] in ("image", "video") and "uri" not in s:
            rep.error(p, f"content '{s['content']}' needs a uri")
        if "uri" in s and not ctx.file(s["uri"]).is_file():
            rep.warn(f"{p}.uri", f"file not found: {s['uri']}")
    _dups(rep, "screens", doc.get("screens", []), "screen")
    crowds = (doc.get("scenery") or {}).get("crowds", [])
    _dups(rep, "scenery.crowds", crowds, "crowd")
    for i, c in enumerate(crowds):
        p = f"scenery.crowds[{i}]"
        if "prototype" in c and c["prototype"] not in ctx.prototype_ids:
            rep.error(f"{p}.prototype", f"unknown prototype '{c['prototype']}'")
        if c["density"] > 6:
            rep.warn(f"{p}.density", f"{c['density']} people per m²: more than a packed crowd")
        if "band" in c["area"]:
            check_band(ctx, f"{p}.area.band", {**c["area"]["band"], "surface": None})
        if c.get("behaviour") == "flee" and "flee_distance" not in c:
            rep.warn(p, "flee without flee_distance: engines will guess")
    months = [m["month"] for m in (env.get("climate") or {}).get("monthly", [])]
    for dup in sorted({x for x in months if months.count(x) > 1}):
        rep.error("environment.climate.monthly", f"month {dup} appears twice")
    for i, m in enumerate((env.get("climate") or {}).get("monthly", [])):
        if "t_min" in m and "t_max" in m and m["t_min"] > m["t_max"]:
            rep.error(f"environment.climate.monthly[{i}]", "t_min above t_max")
        if m.get("rain_days", 0) > 31:
            rep.error(f"environment.climate.monthly[{i}].rain_days", "more rain days than days in a month")


V03_KEYS = ("marshals", "dynamic", "screens")


def check_version(ctx):
    """Keys newer than the declared version."""
    doc = ctx.doc
    ver = (doc.get("_metadata") or {}).get("version")
    if ver not in ("0.1", "0.2"):
        return
    geo = doc.get("geometry") or {}
    found = [k for k in V03_KEYS if k in doc]
    found += [f"geometry.{k}" for k in ("chunks", "tiles", "terrains") if k in geo]
    found += [f"environment.{k}" for k in ("probes", "climate") if k in (doc.get("environment") or {})]
    found += ["scenery.crowds"] * ("crowds" in (doc.get("scenery") or {}))
    terrains = ([geo["terrain"]] if geo.get("terrain") else []) + list(geo.get("terrains", []))
    found += ["geometry.terrain.macro"] * any("macro" in t for t in terrains)
    found += ["ground macro encoding 'colour'"] * any(
        m.get("encoding") == "colour" for gm in (doc.get("ground") or {}).get("materials", [])
        for m in gm.get("macro", []))
    if found:
        ctx.rep.warn("_metadata.version", f"declares {ver} but uses v0.3 features: {', '.join(found[:4])}")


def _usd_stage(ctx, mid):
    """Cached USD stage of a mesh entry (only for meshes whose file was read)."""
    cache = ctx.__dict__.setdefault("_usd_stages", {})
    if mid not in cache:
        cache[mid] = core.usd_stage(ctx.file(ctx.meshes[mid]["uri"]))
    return cache[mid]


def check_usd_palette(ctx, p, mid, material, weights, n_palette, texcoords=()):
    """Weights and UV sets of a USD material for ground materials and surface maps (spec §7.2)."""
    rep = ctx.rep
    stage = _usd_stage(ctx, mid)
    hits = core.usd_material_meshes(stage, material)
    if not hits:
        rep.error(f"{p}.material", f"no mesh uses material '{material}' in {ctx.meshes[mid]['uri']}")
        return
    enc = weights["encoding"]
    for mesh, faces in hits:
        uv = core.usd_texcoord_names(mesh)
        for tc in texcoords:
            if tc not in uv:
                rep.error(p, f"UV primvar '{tc}' missing on {mesh.GetPath()}")
        if enc != "vertex_top3":
            continue
        raw_ids = weights.get("indices", "_STJ_SURF_LAYERS")
        w_name = core.usd_attr_name(weights.get("weights", "_STJ_SURF_WEIGHTS"))
        if isinstance(raw_ids, list):
            # three uniform int primvars: the form Blender can write and read (it has no int3 attribute)
            parts = [core.usd_primvar(mesh, core.usd_attr_name(n)) for n in raw_ids]
            for n, part in zip(raw_ids, parts):
                if part is None:
                    rep.error(p, f"primvar '{core.usd_attr_name(n)}' missing on {mesh.GetPath()}")
            ids = None if None in parts else (parts[0][0], [tuple(v[0] for v in vs) for vs in zip(*(q[1] for q in parts))])
            ids_name = ", ".join(core.usd_attr_name(n) for n in raw_ids)
        else:
            ids_name = core.usd_attr_name(raw_ids)
            ids = core.usd_primvar(mesh, ids_name)
            if ids is None:
                rep.error(p, f"primvar '{ids_name}' missing on {mesh.GetPath()}")
        ws = core.usd_primvar(mesh, w_name)
        if ws is None:
            rep.error(p, f"primvar '{w_name}' missing on {mesh.GetPath()}")
        if ids is None or ws is None:
            continue
        interp, vals = ids
        if interp != "uniform":
            rep.error(p, f"'{ids_name}' must be uniform (one value per face), not {interp}")
        sel = vals if faces is None else [vals[f] for f in faces if f < len(vals)]
        bad = [v for v in sel if len(v) != 3 or any(x < 0 or x >= n_palette for x in v)]
        if bad:
            rep.error(f"{p}.weights.indices", f"{len(bad)} faces with indices outside the palette (0..{n_palette - 1}), e.g. {bad[0]}")
        badw = [w for w in ws[1] if len(w) != 2 or w[0] < -1e-4 or w[1] < -1e-4 or w[0] + w[1] > 1 + 1e-3]
        if badw:
            rep.error(f"{p}.weights.weights", f"{len(badw)} values with wa, wb outside 0..1 or wa + wb > 1")


def check_usd(ctx, path):
    """USD-specific rules: animations by time range, variant sets, payloads, authoring source (spec §7.7, §7.8)."""
    rep, doc = ctx.rep, ctx.doc
    usd_meshes = [mid for mid in ctx.meshes if mid in ctx.mesh_names]
    sets = {}
    for mid in usd_meshes:
        for k, v in core.usd_variant_sets(ctx.file(ctx.meshes[mid]["uri"])).items():
            sets.setdefault(k, set()).update(v)
    for i, v in enumerate(doc.get("variants", [])):
        for vset, name in (v.get("usd_variants") or {}).items():
            if not usd_meshes:
                rep.note(f"variants[{i}].usd_variants", "no USD mesh was read, so the variant sets are not checked")
            elif vset not in sets:
                rep.error(f"variants[{i}].usd_variants.{vset}", f"no variant set '{vset}' in the USD meshes")
            elif name not in sets[vset]:
                rep.error(f"variants[{i}].usd_variants.{vset}", f"variant '{name}' not in set '{vset}' ({', '.join(sorted(sets[vset]))})")
    for i, c in enumerate((doc.get("geometry") or {}).get("chunks", [])):
        if "payload" in c:
            if not core.is_usd(c["payload"]):
                rep.error(f"geometry.chunks[{i}].payload", "a payload is a USD file")
            elif not ctx.file(c["payload"]).is_file():
                rep.warn(f"geometry.chunks[{i}].payload", f"file not found: {c['payload']}")
    # D2: the STJ JSON is normative; USD-native physics that disagrees is reported
    for pid, pr in ((doc.get("scenery") or {}).get("prototypes") or {}).items():
        m, ph = (pr.get("mesh"), pr.get("physics")) if isinstance(pr, dict) else (None, None)
        if not (m and ph and "mass" in ph and m.get("prim", "").startswith("/") and m["mesh_ref"] in usd_meshes):
            continue
        from pxr import UsdPhysics
        prim = _usd_stage(ctx, m["mesh_ref"]).GetPrimAtPath(m["prim"])
        if prim and prim.HasAPI(UsdPhysics.MassAPI):
            usd_mass = UsdPhysics.MassAPI(prim).GetMassAttr().Get()
            if usd_mass and abs(usd_mass - ph["mass"]) > 1e-6:
                rep.warn(f"scenery.prototypes.{pid}.physics.mass", f"{ph['mass']} kg, but UsdPhysics on {m['prim']} says {usd_mass} kg; "
                                                                   "the STJ JSON is normative (spec §7.2)")
    src = (doc.get("_metadata") or {}).get("authoring_source")
    if src and not ctx.file(src["uri"]).is_file():
        rep.note("_metadata.authoring_source", f"{src['uri']} is not shipped with this package")


def check_metadata(ctx):
    rep = ctx.rep
    md = ctx.doc.get("_metadata") or {}
    lic = md.get("licence") or {}
    if lic.get("redistributable") is False:
        rep.note("_metadata.licence.redistributable", "false: keep this file to yourself; do not publish or upload it")
    if not lic:
        rep.note("_metadata.licence", "no licence stated")
    prov = md.get("provenance") or {}
    if prov.get("type") == "converted" and not prov.get("converted_from"):
        rep.warn("_metadata.provenance", "type 'converted' without converted_from")


def check_unused_surfaces(ctx):
    sc = ctx.doc.get("scenery") or {}
    for layer in sc.get("scatter", []):
        ctx.used_surfaces.update(layer["area"].get("surfaces", []))
    for sid in sorted(ctx.surface_ids - ctx.used_surfaces):
        ctx.rep.note(f"surfaces.library.{sid}", "not referenced by a default, binding, band, mesh material or base_surface")


class PrefixReport(Report):
    """Writes into another report with a path prefix (for layouts and variants)."""

    def __init__(self, target, prefix):
        super().__init__()
        self.target, self.prefix = target, prefix

    def add(self, level, path, msg):
        self.target.add(level, f"{self.prefix}.{path}" if path and not path.startswith("(") else f"{self.prefix} {path}", msg)


def check_layouts(ctx):
    """Each layout: timing, race and edges on the layout's own reference line (spec §3.5)."""
    rep, doc = ctx.rep, ctx.doc
    layouts = doc.get("layouts", [])
    ids = [l["id"] for l in layouts]
    for dup in {x for x in ids if ids.count(x) > 1}:
        rep.error("layouts", f"duplicate layout id '{dup}'")
    for i, lay in enumerate(layouts):
        p = f"layouts[{i}]"
        for k in ("include_meshes", "exclude_meshes"):
            for j, mid in enumerate(lay.get(k, [])):
                if mid not in ctx.meshes:
                    rep.error(f"{p}.{k}[{j}]", f"unknown mesh '{mid}'")
        if lay.get("direction") == "reverse" and "reference" not in lay and not (doc.get("reference") or {}).get("centerline") \
                and not ((doc.get("reference") or {}).get("opendrive") or {}).get("route"):
            rep.error(p, "a reverse layout without its own reference needs a base centerline or an OpenDRIVE route")
        own_line = "reference" in lay or lay.get("direction") == "reverse"
        if own_line and "timing" not in lay:
            rep.note(p, "own reference line but no timing: nothing timed in this layout")
        ldoc = core.layout_document(doc, lay, merge_edges=False)
        lrep = PrefixReport(rep, f"{p}({lay['id']})")
        lctx = Ctx(ldoc, ctx.base_dir, lrep)
        lctx.mesh_names = ctx.mesh_names
        # reference problems of an inherited line were already reported for the base
        lctx.rep = lrep if "reference" in lay else Report()
        check_reference(lctx)
        lctx.rep = lrep
        origin = check_timing(lctx)
        check_race(lctx, origin)
        check_edges(lctx)
        ctx.used_surfaces |= lctx.used_surfaces


def check_variants(ctx, path):
    """Each variant is an override of this very file and validates (spec §3.6)."""
    rep = ctx.rep
    variants = ctx.doc.get("variants", [])
    ids = [v["id"] for v in variants]
    for dup in {x for x in ids if ids.count(x) > 1}:
        rep.error("variants", f"duplicate variant id '{dup}'")
    for i, v in enumerate(variants):
        p = f"variants[{i}]"
        if "override" not in v:
            continue
        vpath = ctx.file(v["override"])
        if not vpath.is_file():
            rep.error(f"{p}.override", f"file not found: {v['override']}")
            continue
        raw = core.load_document(vpath)
        if not core.is_override(raw):
            rep.error(f"{p}.override", "not an STJ-OVERRIDE file")
            continue
        base = (vpath.parent / str(raw["_metadata"].get("base", ""))).resolve()
        if path is not None and base != Path(path).resolve():
            rep.error(f"{p}.override", f"its base is {raw['_metadata'].get('base')}, not this file")
            continue
        sub = validate(vpath, check_variants=False)
        target = PrefixReport(rep, f"{p}({v['id']})")
        seen = set(rep.items)       # report only what the variant adds
        for level, sp, msg in sub.items:
            if sp != "(override)" and (level, sp, msg) not in seen:
                target.add(level, sp, msg)


def cross_check(doc, base_dir, rep, path=None, variants=True):
    ctx = Ctx(doc, base_dir, rep)
    check_metadata(ctx)
    check_reference(ctx)
    check_geometry(ctx)
    check_surfaces(ctx)
    origin = check_timing(ctx)
    check_race(ctx, origin)
    check_edges(ctx)
    check_cameras(ctx)
    check_environment(ctx)
    check_scenery(ctx)
    check_terrain(ctx)
    check_ground(ctx)
    check_chainage(ctx)
    check_surface_maps(ctx)
    check_mu(ctx)
    check_rbr_lessons(ctx)
    check_marshals(ctx)
    check_dynamic(ctx)
    check_worlds(ctx)
    check_presentation(ctx)
    check_version(ctx)
    check_usd(ctx, path)
    check_water(ctx)
    check_surfaces_v02(ctx)
    check_props(ctx)
    check_animated(ctx)
    check_audio(ctx)
    check_track_info(ctx)
    check_signals(ctx)
    check_v02_extras(ctx)
    check_layouts(ctx)
    check_unused_surfaces(ctx)
    if variants:
        check_variants(ctx, path)
    return ctx


# ── driver ───────────────────────────────────────────────────────────────────

def usdz_package_rules(path, rep):
    """OpenUSD's own package validators (allowed file types, encapsulation, alignment), when available."""
    try:
        from pxr import Usd, UsdValidation
    except ImportError:
        return
    vals = [v for v in UsdValidation.ValidationRegistry().GetOrLoadAllValidators()
            if v.GetMetadata().name.startswith("usdUtilsValidators:")]
    stage = Usd.Stage.Open(str(path))
    for err in UsdValidation.ValidationContext(vals).Validate(stage):
        level = rep.error if err.GetType() == UsdValidation.ValidationErrorType.Error else rep.warn
        level("(usdz)", f"{err.GetName()}: {err.GetMessage()}")


def validate(path, schema=None, check_variants=True):
    """Validate one file. Returns a Report. Variants listed in a base file are validated too."""
    rep = Report()
    path = Path(path)
    schema = schema or core.load_json(SCHEMA)
    try:
        raw = core.load_document(path)
    except (OSError, json.JSONDecodeError, core.StjLoadError) as e:
        rep.error("(file)", f"cannot load: {e}")
        return rep
    if path.suffix.lower() == ".usdz":
        usdz_package_rules(path, rep)
    if core.is_override(raw):
        before = len(rep.items)
        schema_errors(raw, core.load_json(OVERRIDE_SCHEMA), rep)
        if len(rep.items) > before:
            return rep
    try:
        doc, chain = core.resolve(path)
    except core.StjLoadError as e:
        rep.error("(file)", str(e))
        return rep
    if len(chain) > 1:
        rep.note("(override)", "resolved " + " <- ".join(p.name for p in chain))
    schema_errors(doc, schema, rep)
    if rep.count("ERROR") == 0:
        # base_dir: relative URIs in the merged document are those of the base file (spec §3.3)
        # an override's merged document carries its base's variants list; those are checked with the base
        # a USD file's document resolves URIs next to its layer (inside an unpacked .usdz, chain[0] is that layer)
        cross_check(doc, chain[0].parent, rep, path=chain[0], variants=check_variants and len(chain) == 1)
    return rep


def main(argv):
    if "-h" in argv or "--help" in argv or not argv:
        print(__doc__)
        return 0 if argv else 2
    strict = "--strict" in argv
    schema_path = SCHEMA
    files = []
    it = iter(argv)
    for a in it:
        if a == "--strict":
            continue
        if a == "--schema":
            schema_path = Path(next(it))
            continue
        files.append(a)
    schema = core.load_json(schema_path)
    failed = False
    for f in files:
        print(f"\nValidating: {f}")
        print("=" * 60)
        rep = validate(f, schema)
        for level, path, msg in rep.items:
            print(f"  {level:<5}  {path}: {msg}")
        e, w, n = rep.count("ERROR"), rep.count("WARN"), rep.count("NOTE")
        ok = e == 0 and (w == 0 or not strict)
        print(f"  {'PASS' if ok else 'FAIL'}  {e} error(s), {w} warning(s), {n} note(s)")
        failed |= not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
