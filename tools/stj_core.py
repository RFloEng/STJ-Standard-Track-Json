"""
STJ core helpers
================
Shared by the validator and the tools:

- loading with $ref expansion (spec §3.2) and override resolution (spec §3.3, RFC 7396)
- the reference line: s along a centerline polyline, (s, t) -> world point
- reading road lengths from an OpenDRIVE file
- the signal vocabulary, PNG/raw rasters, terrain sampling, line states, the effective
  water-film depth, the ground blend and the evolution laws (spec §6.8–§6.10, §7.4, §8.7, §11.1)
- OpenUSD: the STJ document inside a layer, meshes, primvars, variant sets, .usdz (spec §7)

Standard library, plus the pxr module (pip install usd-core) for OpenUSD.
"""

import copy
import json
import math
import struct
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

LAPPED_TYPES = {"circuit", "oval", "rallycross"}
OPEN_TYPES = {"point_to_point", "hillclimb", "drag"}


class StjLoadError(Exception):
    pass


# ── loading ──────────────────────────────────────────────────────────────────

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def expand_refs(node, base_dir, _stack=()):
    """Replace every {"$ref": "file"} object with the referenced file's content, recursively.

    Paths are relative to the file that contains the $ref. Circular references raise StjLoadError.
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            target = (Path(base_dir) / ref).resolve()
            if target in _stack:
                chain = " -> ".join(str(p.name) for p in (*_stack, target))
                raise StjLoadError(f"circular $ref: {chain}")
            if not target.is_file():
                raise StjLoadError(f"$ref not found: {ref} (from {base_dir})")
            return expand_refs(load_json(target), target.parent, (*_stack, target))
        return {k: expand_refs(v, base_dir, _stack) for k, v in node.items()}
    if isinstance(node, list):
        return [expand_refs(v, base_dir, _stack) for v in node]
    return node


def merge_patch(target, patch):
    """RFC 7396 JSON Merge Patch."""
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    result = copy.deepcopy(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value)
    return result


def is_override(doc):
    return isinstance(doc, dict) and (doc.get("_metadata") or {}).get("specification") == "STJ-OVERRIDE"


def resolve(path, _stack=()):
    """Load an .stj.json or .stj-override.json and return (document, chain).

    An override's base may itself be an override. chain lists the files applied, base first.
    """
    path = Path(path).resolve()
    if path in _stack:
        raise StjLoadError("circular override base: " + " -> ".join(p.name for p in (*_stack, path)))
    if is_usd(path):
        # STJ inside USD (spec §7.8): a .usdz is unpacked, so relative URIs resolve inside the package.
        # An override may be a USD layer too; it then resolves like an .stj-override.json.
        path = usdz_extract(path) if path.suffix.lower() == ".usdz" else path
        doc = expand_refs(usd_document(path), path.parent, (path,))
    else:
        doc = expand_refs(load_json(path), path.parent, (path,))
    if not is_override(doc):
        return doc, [path]
    base_rel = doc["_metadata"].get("base")
    if not isinstance(base_rel, str):
        raise StjLoadError(f"{path.name}: override has no _metadata.base")
    base_path = (path.parent / base_rel).resolve()
    if not base_path.is_file():
        raise StjLoadError(f"{path.name}: base not found: {base_rel}")
    base_doc, chain = resolve(base_path, (*_stack, path))
    return merge_patch(base_doc, doc.get("patch") or {}), [*chain, path]


# ── reference line ───────────────────────────────────────────────────────────

class ReferenceLine:
    """A centerline: points, optional cubic Hermite tangents, optional stored chainage (spec §7.1).

    s is the cumulative x/y-plane length from the first point (OpenDRIVE convention), or the stored
    chainage where given. Within a segment s maps linearly onto the curve parameter u, as a
    stored-distance driveline does; with straight segments that is exact arc length.
    """

    SAMPLES = 32

    def __init__(self, points, closed=False, chainage=None, tangents=None, tangents_out=None, tangents_in=None):
        """tangents: one per point, shared by the two segments around it. tangents_out / tangents_in: a segment
        starts with tangents_out[i] and ends with tangents_in[i + 1]; tangents_in defaults to tangents_out, and
        either wins over tangents."""
        pts = [tuple(float(c) for c in p) for p in points]

        def vecs(v):
            return [tuple(float(c) for c in t) for t in v] if v else None
        t_out = vecs(tangents_out) or vecs(tangents)
        t_in = vecs(tangents_in) or t_out
        if closed:
            pts = pts + [pts[0]]
            if t_out:
                t_out = t_out + [t_out[0]]
            if t_in:
                t_in = t_in + [t_in[0]]
        tans = t_out
        self.points = pts
        self.tangents = tans            # the tangent at the start of each segment (None: straight segments)
        self.t_out = t_out
        self.t_in = t_in
        self.closed = bool(closed)
        self.geo = [0.0]
        for i in range(len(pts) - 1):
            self.geo.append(self.geo[-1] + self._segment_length(i))
        if chainage:
            s = [float(c) for c in chainage]
            if closed:
                s.append(s[-1] + self.geo[-1] - self.geo[-2])
            self.s = s
        else:
            self.s = list(self.geo)
        self.length = self.s[-1]
        self.geometric_length = self.geo[-1]
        # dense (x, y, s) polyline for projection
        self._dense = []
        for i in range(len(pts) - 1):
            n = self.SAMPLES if tans else 1
            for k in range(n):
                u = k / n
                x, y, _z = self._pos(i, u)
                self._dense.append((x, y, self.s[i] + u * (self.s[i + 1] - self.s[i])))
        self._dense.append((pts[-1][0], pts[-1][1], self.s[-1]))

    def _pos(self, i, u):
        a, b = self.points[i], self.points[i + 1]
        if not self.tangents:
            return tuple(a[k] + u * (b[k] - a[k]) for k in range(3))
        ta, tb = self.t_out[i], self.t_in[i + 1]
        u2, u3 = u * u, u * u * u
        h = (2 * u3 - 3 * u2 + 1, u3 - 2 * u2 + u, -2 * u3 + 3 * u2, u3 - u2)
        return tuple(h[0] * a[k] + h[1] * ta[k] + h[2] * b[k] + h[3] * tb[k] for k in range(3))

    def _dir(self, i, u):
        a, b = self.points[i], self.points[i + 1]
        if not self.tangents:
            return (b[0] - a[0], b[1] - a[1])
        ta, tb = self.t_out[i], self.t_in[i + 1]
        u2 = u * u
        h = (6 * u2 - 6 * u, 3 * u2 - 4 * u + 1, -6 * u2 + 6 * u, 3 * u2 - 2 * u)
        return tuple(h[0] * a[k] + h[1] * ta[k] + h[2] * b[k] + h[3] * tb[k] for k in range(2))

    def _segment_length(self, i):
        a, b = self.points[i], self.points[i + 1]
        if not self.tangents:
            return math.hypot(b[0] - a[0], b[1] - a[1])
        total, prev = 0.0, self._pos(i, 0.0)
        for k in range(1, self.SAMPLES + 1):
            p = self._pos(i, k / self.SAMPLES)
            total += math.hypot(p[0] - prev[0], p[1] - prev[1])
            prev = p
        return total

    def zero_length_segments(self):
        return [i for i in range(len(self.s) - 1) if self.s[i + 1] - self.s[i] < 1e-9]

    def _segment(self, s):
        if self.closed:
            s = s % self.length
        s = min(max(s, 0.0), self.length)
        lo, hi = 0, len(self.s) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.s[mid] <= s:
                lo = mid
            else:
                hi = mid
        return lo, s

    def frame(self, s):
        """(x, y, z, heading) on the line at s."""
        i, s = self._segment(s)
        ds = self.s[i + 1] - self.s[i]
        u = 0.0 if ds < 1e-12 else (s - self.s[i]) / ds
        x, y, z = self._pos(i, u)
        dx, dy = self._dir(i, u)
        return (x, y, z, math.atan2(dy, dx))

    def point(self, s, t=0.0):
        """World point at (s, t); t is positive to the left."""
        x, y, z, h = self.frame(s)
        return (x - t * math.sin(h), y + t * math.cos(h), z)

    def project(self, x, y):
        """(s, t) of the point on the line nearest to (x, y), with t positive to the left."""
        best = None
        d = self._dense
        for a, b in zip(d, d[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            ds = dx * dx + dy * dy
            u = 0.0 if ds < 1e-18 else max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / ds))
            d2 = (x - a[0] - u * dx) ** 2 + (y - a[1] - u * dy) ** 2
            if best is None or d2 < best[0]:
                seg = math.sqrt(ds)
                side = 0.0 if seg < 1e-9 else (dx * (y - a[1]) - dy * (x - a[0])) / seg
                best = (d2, a[2] + u * (b[2] - a[2]), side)
        s = best[1] % self.length if self.closed and self.length else best[1]
        return s, best[2]

    def lap_distance(self, s, s0):
        """Distance travelled from s0 to s in the race direction (wraps on a closed line)."""
        d = s - s0
        return d % self.length if self.closed else d


def reference_line(doc):
    """ReferenceLine from reference.centerline, or None."""
    cl = (doc.get("reference") or {}).get("centerline")
    if not isinstance(cl, dict) or not isinstance(cl.get("points"), list) or len(cl["points"]) < 2:
        return None
    n = len(cl["points"])
    ch = cl.get("chainage")
    # malformed chainage or tangents are reported by the validator; the line falls back to the geometry
    ch = ch if isinstance(ch, list) and len(ch) == n and all(b > a for a, b in zip(ch, ch[1:])) else None

    def per_point(key):
        v = cl.get(key)
        return v if isinstance(v, list) and len(v) == n else None
    t_out = per_point("tangents_out")
    t_in = per_point("tangents_in") if t_out else None
    return ReferenceLine(cl["points"], cl.get("closed", False), ch, per_point("tangents"), t_out, t_in)


def half_widths(doc, s):
    """(left, right) drivable half-widths at s, or None when not given."""
    cl = (doc.get("reference") or {}).get("centerline") or {}
    prof = cl.get("width_profile")
    if prof:
        if s <= prof[0][0]:
            return prof[0][1], prof[0][2]
        for a, b in zip(prof, prof[1:]):
            if a[0] <= s <= b[0]:
                u = 0.0 if b[0] == a[0] else (s - a[0]) / (b[0] - a[0])
                return a[1] + u * (b[1] - a[1]), a[2] + u * (b[2] - a[2])
        return prof[-1][1], prof[-1][2]
    w = cl.get("width")
    if w:
        return w["left"], w["right"]
    return None


# ── layouts ──────────────────────────────────────────────────────────────────

def reverse_reference(ref):
    """The same reference driven backwards: s' = L - s (mod L on a closed line), t' = -t."""
    out = copy.deepcopy(ref or {})
    cl = out.get("centerline")
    if cl:
        pts = cl["points"]
        length = reference_line({"reference": {"centerline": cl}}).length
        # a closed line keeps its first point, so s' = 0 stays where s = 0 was
        cl["points"] = [pts[0]] + pts[:0:-1] if cl.get("closed") else pts[::-1]
        def flip(v):
            tan = [[-c for c in t] for t in v]
            return [tan[0]] + tan[:0:-1] if cl.get("closed") else tan[::-1]
        if "tangents" in cl:
            cl["tangents"] = flip(cl["tangents"])
        if "tangents_out" in cl:
            # driven backwards a segment starts where it ended: what left a point now arrives at it
            out_, in_ = cl["tangents_out"], cl.get("tangents_in", cl["tangents_out"])
            cl["tangents_out"], cl["tangents_in"] = flip(in_), flip(out_)
        if "chainage" in cl and len(cl["chainage"]) == len(pts):
            ch = cl["chainage"]
            cl["chainage"] = [0.0] + [length - c for c in ch[:0:-1]] if cl.get("closed") else [length - c for c in ch[::-1]]
        if "width" in cl:
            cl["width"] = {"left": cl["width"]["right"], "right": cl["width"]["left"]}
        if "width_profile" in cl:
            cl["width_profile"] = [[length - s, right, left] for s, left, right in reversed(cl["width_profile"])]
    od = out.get("opendrive")
    if od and od.get("route"):
        flip = {"forward": "backward", "backward": "forward"}
        od["route"] = [{**r, "direction": flip[r.get("direction", "forward")]} for r in reversed(od["route"])]
    return out


def layout_document(doc, layout, merge_edges=True):
    """The document as seen when `layout` (a layouts[] entry or its id) is selected (spec §3.5).

    reference, timing and race are replaced wholesale by the layout's. When the layout has its own
    reference line (or reverses the base line) nothing s-based is inherited from the top level except
    surface bands and CRG placements, which always stay on the base line. Layout edges are added to
    the top-level edges when the line is unchanged (merge_edges), otherwise they replace them.
    """
    if isinstance(layout, str):
        layout = next(l for l in doc.get("layouts", []) if l.get("id") == layout)
    out = {k: copy.deepcopy(v) for k, v in doc.items() if k not in ("layouts", "variants")}
    own_line = "reference" in layout or layout.get("direction") == "reverse"
    if "reference" in layout:
        out["reference"] = copy.deepcopy(layout["reference"])
    elif layout.get("direction") == "reverse":
        out["reference"] = reverse_reference(doc.get("reference"))
    for key in ("timing", "race"):
        if key in layout:
            out[key] = copy.deepcopy(layout[key])
        elif own_line:
            out.pop(key, None)
    edges = copy.deepcopy(layout.get("edges", []))
    if merge_edges and not own_line:
        edges = copy.deepcopy(doc.get("edges", [])) + edges
    out.pop("edges", None)
    if edges:
        out["edges"] = edges
    info = out.setdefault("track_info", {})
    if layout.get("name"):
        info["layout"] = layout["name"]
    if layout.get("type"):
        info["type"] = layout["type"]
    meshes = (out.get("geometry") or {}).get("meshes")
    if meshes is not None:
        keep = set(layout.get("include_meshes") or [m["id"] for m in meshes]) - set(layout.get("exclude_meshes") or [])
        out["geometry"]["meshes"] = [m for m in meshes if m["id"] in keep]
    return out


# ── OpenDRIVE ────────────────────────────────────────────────────────────────

def opendrive_road_lengths(path):
    """{road id: length} from an OpenDRIVE file."""
    root = ET.parse(path).getroot()
    return {r.get("id"): float(r.get("length", "0")) for r in root.iter("road")}


# ── signals (spec §11.1) ─────────────────────────────────────────────────────

SESSIONS = ["practice", "qualifying", "warmup", "race", "stage"]
FLAGS = ["none", "green", "yellow", "double_yellow", "red", "blue", "white", "chequered",
         "safety_car", "virtual_safety_car", "code_60"]

# name: (kind, unit or enum values, (min, max) for numbers)
SIGNALS = {
    "sun_elevation": ("number", "rad", (-math.pi / 2, math.pi / 2)),
    "local_time": ("number", "s", (0.0, 86400.0)),
    "day_of_year": ("number", "day", (1.0, 366.0)),
    "precipitation": ("number", "mm/h", (0.0, 500.0)),
    "water_depth": ("number", "m", (0.0, 0.1)),
    "wetness": ("number", "-", (0.0, 1.0)),
    "wind_speed": ("number", "m/s", (0.0, 80.0)),
    "snow_cover": ("number", "-", (0.0, 1.0)),
    "leaf_fraction": ("number", "-", (0.0, 1.0)),
    "session": ("enum", SESSIONS, None),
    "session_phase": ("enum", ["pre_session", "formation", "countdown", "running", "suspended", "finished"], None),
    "session_time": ("number", "s", (0.0, None)),
    "flag": ("enum", FLAGS, None),
    "start_lights_lit": ("number", "count", (0.0, None)),
    "nearest_vehicle_distance": ("number", "m", (0.0, None)),
    "sector_flag": ("enum", FLAGS, None),
    "wear": ("number", "-", (0.0, 1.0)),
    "time_to_arrival": ("number", "s", (0.0, None)),
}


def eval_curve(curve, x):
    """Piecewise-linear [[x, y], ...], clamped at both ends."""
    if x <= curve[0][0]:
        return curve[0][1]
    for a, b in zip(curve, curve[1:]):
        if a[0] <= x <= b[0]:
            return a[1] if b[0] == a[0] else a[1] + (x - a[0]) / (b[0] - a[0]) * (b[1] - a[1])
    return curve[-1][1]


def eval_condition(cond, state):
    """Evaluate a condition against {signal: value}; a leaf on a missing signal is false."""
    if "all" in cond:
        return all(eval_condition(c, state) for c in cond["all"])
    if "any" in cond:
        return any(eval_condition(c, state) for c in cond["any"])
    if "not" in cond:
        return not eval_condition(cond["not"], state)
    if cond["signal"] not in state:
        return False
    v, op, ref = state[cond["signal"]], cond["op"], cond["value"]
    return {"eq": lambda: v == ref, "ne": lambda: v != ref, "lt": lambda: v < ref, "le": lambda: v <= ref,
            "gt": lambda: v > ref, "ge": lambda: v >= ref, "in": lambda: v in ref}[op]()


# ── rasters (PNG and raw float32) ────────────────────────────────────────────

class Raster:
    """A decoded image: width, height, channels, maxval and a flat row-major sample list (row 0 = top)."""

    def __init__(self, width, height, channels, maxval, data):
        self.width, self.height, self.channels, self.maxval, self.data = width, height, channels, maxval, data

    def get(self, i, j, c=0):
        return self.data[(j * self.width + i) * self.channels + c]

    def sample(self, extent, x, y, c=0):
        """Bilinear sample at world (x, y), vertex-registered over extent; None outside."""
        x0, y0, x1, y1 = extent
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            return None
        fx = (x - x0) / (x1 - x0) * (self.width - 1)
        fy = (y1 - y) / (y1 - y0) * (self.height - 1)
        i, j = min(int(fx), self.width - 2), min(int(fy), self.height - 2)
        u, v = fx - i, fy - j
        g = self.get
        return ((1 - u) * (1 - v) * g(i, j, c) + u * (1 - v) * g(i + 1, j, c)
                + (1 - u) * v * g(i, j + 1, c) + u * v * g(i + 1, j + 1, c))


PNG_MAGIC = bytes([0x89]) + b"PNG\r\n" + bytes([0x1A]) + b"\n"
PNG_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}  # colour type -> channels (palettes not supported)


def read_png(path):
    """Decode a non-interlaced greyscale, grey+alpha, RGB or RGBA PNG of 8 or 16 bits."""
    data = Path(path).read_bytes()
    if data[:8] != PNG_MAGIC:
        raise StjLoadError(f"{Path(path).name}: not a PNG file")
    pos, idat, head = 8, b"", None
    while pos < len(data):
        length, kind = struct.unpack_from(">I4s", data, pos)
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            head = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    width, height, depth, ctype, _comp, _filt, interlace = head
    if ctype not in PNG_CHANNELS or depth not in (8, 16) or interlace:
        raise StjLoadError(f"{Path(path).name}: unsupported PNG (colour type {ctype}, {depth} bit, interlace {interlace})")
    ch = PNG_CHANNELS[ctype]
    bpp = ch * depth // 8
    stride = width * bpp
    raw = zlib.decompress(idat)
    out = bytearray()
    prev = bytearray(stride)
    for j in range(height):
        f = raw[j * (stride + 1)]
        line = bytearray(raw[j * (stride + 1) + 1:(j + 1) * (stride + 1)])
        if f:
            for k in range(stride):
                a = line[k - bpp] if k >= bpp else 0
                b = prev[k]
                if f == 1:
                    line[k] = (line[k] + a) & 255
                elif f == 2:
                    line[k] = (line[k] + b) & 255
                elif f == 3:
                    line[k] = (line[k] + (a + b) // 2) & 255
                elif f == 4:
                    c = prev[k - bpp] if k >= bpp else 0
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    line[k] = (line[k] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out += line
        prev = line
    values = list(struct.unpack(f">{len(out) // 2}H", bytes(out))) if depth == 16 else list(out)
    return Raster(width, height, ch, 65535 if depth == 16 else 255, values)


def write_png(path, width, height, values, channels=1, depth=8):
    """Write a PNG from a flat row-major sample list (filter 0, no interlace)."""
    ctype = {1: 0, 2: 4, 3: 2, 4: 6}[channels]
    fmt = ">" + ("H" if depth == 16 else "B") * (width * channels)
    rows = b"".join(b"\x00" + struct.pack(fmt, *values[j * width * channels:(j + 1) * width * channels])
                    for j in range(height))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    Path(path).write_bytes(PNG_MAGIC
                           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, ctype, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


# ── terrain (spec §7.4) ──────────────────────────────────────────────────────

class Terrain:
    """Heights, holes and layer weights of geometry.terrain."""

    def __init__(self, terrain, base_dir):
        hm = terrain["heightmap"]
        self.extent = hm["extent"]
        self.height_channels = 1
        nx, ny = hm["size"]
        path = Path(base_dir) / hm["uri"]
        if hm["format"] == "png16":
            img = read_png(path)
            if img.maxval != 65535:
                raise StjLoadError(f"{path.name}: a png16 heightmap must be a 16-bit PNG")
            lo, hi = hm.get("height_min", 0.0), hm.get("height_max", 0.0)
            nodata = hm.get("nodata")
            # the first channel is the height (Blender saves 16-bit images as RGBA); the nodata code is a void
            heights = [float("nan") if v == nodata else lo + v / 65535.0 * (hi - lo) for v in img.data[::img.channels]]
            w, h = img.width, img.height
            self.height_channels = img.channels
        else:
            blob = path.read_bytes()
            if len(blob) != nx * ny * 4:
                raise StjLoadError(f"{path.name}: {len(blob)} bytes, expected {nx * ny * 4} for {nx} x {ny} float32")
            heights, w, h = list(struct.unpack(f"<{nx * ny}f", blob)), nx, ny
            nodata = hm.get("nodata")
            if nodata is not None:
                heights = [float("nan") if v == nodata else v for v in heights]
        if (w, h) != (nx, ny):
            raise StjLoadError(f"{path.name}: image is {w} x {h}, heightmap.size says {nx} x {ny}")
        self.heights = Raster(w, h, 1, 1.0, heights)
        self.void_count = sum(1 for v in heights if v != v)      # cells with no measurement (NaN)
        self.holes = read_png(Path(base_dir) / terrain["holes"]["uri"]) if terrain.get("holes") else None
        self.layers = terrain.get("layers") or []
        self.weights = {}
        for layer in self.layers[1:]:
            wt = layer.get("weight")
            if wt:
                channel = wt.get("channel", "gray")
                self.weights[layer["id"]] = (read_png(Path(base_dir) / wt["uri"]),
                                             0 if channel == "gray" else "rgba".index(channel))

    def height(self, x, y):
        """Terrain height at (x, y), or None outside the grid and over cells with no measurement."""
        h = self.heights.sample(self.extent, x, y)
        return None if h is None or h != h else h

    def is_hole(self, x, y):
        if self.holes is None:
            return False
        x0, y0, x1, y1 = self.extent
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            return False
        i = round((x - x0) / (x1 - x0) * (self.holes.width - 1))
        j = round((y1 - y) / (y1 - y0) * (self.holes.height - 1))
        return self.holes.get(i, j) != 0

    def surface_at(self, x, y):
        """Surface id of the dominant layer at (x, y); None without layers."""
        if not self.layers:
            return None
        w = {}
        for layer in self.layers[1:]:
            img_c = self.weights.get(layer["id"])
            v = img_c[0].sample(self.extent, x, y, img_c[1]) if img_c else None
            w[layer["id"]] = 0.0 if v is None else v / img_c[0].maxval
        w[self.layers[0]["id"]] = max(0.0, 1.0 - sum(w.values()))
        return max(self.layers, key=lambda l: w[l["id"]])["surface"]


# ── line states and water film (spec §6.8, §6.9) ─────────────────────────────

def racing_line_offsets(line_points, ref):
    """[(s, t), ...] of a racing line's points projected onto the reference line, sorted by s."""
    return sorted(ref.project(p[0], p[1]) for p in line_points)


def offset_at(offsets, s, closed_length=None):
    """t of a projected racing line at s (nearest projected point; adequate for dense lines)."""
    def gap(o):
        d = abs(o[0] - s)
        return min(d, closed_length - d) if closed_length else d
    return min(offsets, key=gap)[1]


def line_state_value(state, level, s, t, t_line):
    """r(s, t) = level * profile(s) * exp(-0.5 * ((t - t_line) / spread)^2)."""
    prof = eval_curve(state["profile"], s) if state.get("profile") else 1.0
    return level * prof * math.exp(-0.5 * ((t - t_line) / state["spread"]) ** 2)


def in_band(band, s, t):
    """True when (s, t) lies in an s_band; s_end < s_start crosses s = 0 on a closed line."""
    lo, hi = band["s_start"], band["s_end"]
    on_s = lo <= s <= hi if lo <= hi else (s >= lo or s <= hi)
    return on_s and band["t_min"] <= t <= band["t_max"]


def point_in_polygon(poly, x, y):
    inside = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def storage_depth(surface):
    """surface.water.storage_depth, defaulting to half the macrotexture MPD (spec §6.9)."""
    w = surface.get("water") or {}
    if "storage_depth" in w:
        return w["storage_depth"]
    return 0.5 * ((surface.get("roughness") or {}).get("mean_profile_depth") or 0.0)


def film_depth(doc, base_dir, surface, x, y, s, t, water_depth, ref, dry_line_offsets=None):
    """Effective water-film depth at a contact (spec §6.9):
    d = max(0, water_depth * A * (1 - shelter) * D - storage_depth)."""
    water = doc.get("water") or {}
    a = 1.0
    acc = water.get("accumulation")
    if acc:
        img = read_png(Path(base_dir) / acc["uri"])
        v = img.sample(acc["extent"], x, y)
        if v is not None:
            a = 2.0 * v / img.maxval
    for band in water.get("accumulation_bands", []):
        if in_band(band, s, t):
            a = band["factor"]
    shelter = 0.0
    for sh in water.get("shelter", []):
        if (sh.get("band") and in_band(sh["band"], s, t)) or (sh.get("polygon") and point_in_polygon(sh["polygon"], x, y)):
            shelter = max(shelter, sh["factor"])
    d_factor = 1.0
    dl = water.get("dry_line")
    if dl and dry_line_offsets:
        t_line = offset_at(dry_line_offsets, s, ref.length if ref.closed else None)
        d_factor = 1.0 - (1.0 - dl["factor"]) * math.exp(-0.5 * ((t - t_line) / dl["spread"]) ** 2)
    return max(0.0, water_depth * a * (1.0 - shelter) * d_factor - storage_depth(surface))


# ── layered ground (spec §8.7) ───────────────────────────────────────────────

MASK_DEFAULT_SOFTNESS = 0.15


def ground_blend(weights, heights, means, contrasts, method="height", influence=0.5, depth=0.2,
                 masks=None, softness=MASK_DEFAULT_SOFTNESS):
    """Blend factors (summing to 1) of the layers present at a point.

    weights: interpolated layer weights; heights: each layer's sampled height (0..1);
    means: each layer texture's mean height; contrasts: height_contrast per layer.
    method "mask": masks holds the sampled mask value (0..1) for each layer after the first. Layer j is laid
    over the result of the layers before it with t_j = clamp((share_j - mask_j) / softness + 0.5, 0, 1), where
    share_j = w_j / (w_0 + .. + w_j). Provisional: not fitted to any engine (spec §8.7).
    """
    if method == "mask":
        n = len(weights)
        if masks is None or len(masks) != n - 1:
            raise ValueError(f"method 'mask' needs {n - 1} mask values for {n} layers")
        t = [0.0]
        run = weights[0]
        for j in range(1, n):
            run += weights[j]
            share = weights[j] / run if run > 0 else 0.0
            t.append(min(max((share - masks[j - 1]) / softness + 0.5, 0.0), 1.0))
        factors = [0.0] * n
        keep = 1.0
        for j in range(n - 1, 0, -1):
            factors[j] = t[j] * keep
            keep *= 1.0 - t[j]
        factors[0] = keep
        return factors
    if method == "linear":
        total = sum(weights)
        return [w / total for w in weights] if total > 0 else [1.0 / len(weights)] * len(weights)
    scores = [w + (h - m) * influence * c for w, h, m, c in zip(weights, heights, means, contrasts)]
    top = max(scores)
    keep = [max(sc - (top - depth), 0.0) for sc in scores]
    total = sum(keep)
    return [k / total for k in keep]


def wet_amount(map_value, wetness, strength=1.0):
    """How wet the ground is at a point (0..1): the `wetness` macro map times the `wetness` signal (spec §8.7).

    What the engine draws for it (darkening, shine, puddles) is the engine's; the reference stops here."""
    return min(max(map_value * strength * wetness, 0.0), 1.0)


MACRO_RATIO_RANGE = (0.25, 4.0)      # the `colour` encoding never scales a channel by more than this
MACRO_EPSILON = 1e-4


def srgb_to_linear(c):
    """One sRGB channel in 0..1 to linear light. Colours are blended in linear light (§8.7)."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def ground_mean_colour(weights, colours):
    """The layers' own average colour at a point: sum(w_i * mean colour_i), weights normalised.

    weights: layer weights; colours: each layer texture's mean colour (r, g, b), linear."""
    total = sum(weights)
    if total <= 0:
        return (0.0, 0.0, 0.0)
    return tuple(sum(w * col[c] for w, col in zip(weights, colours)) / total for c in range(3))


def apply_macro(colour, macro_values, base=None):
    """The detail colour (r, g, b, linear) after each macro map, in order (spec §8.7, §7.4).

    macro_values: [(value or (r, g, b), encoding[, strength]), ...], values linear.
      grey_centred   colour * 2 * value (0.5 changes nothing)
      multiply       colour * value
      colour         value is the average colour the ground should have, `base` the layers' own average
                     (ground_mean_colour; default: `colour` itself). Per channel,
                     ratio = clamp(value / max(base, eps), 0.25, 4); colour *= 1 + strength * (ratio - 1).
                     strength 0 leaves the detail alone, 1 makes its average the map's. Default 1.
    The average (`base`) follows every map applied before, so a second colour map re-targets the average
    instead of compounding: only the last colour map shows."""
    out = list(colour)
    ref = list(base if base is not None else colour)
    lo, hi = MACRO_RATIO_RANGE
    for item in macro_values:
        value, encoding = item[0], item[1]
        strength = item[2] if len(item) > 2 else 1.0
        vals = value if isinstance(value, (list, tuple)) else (value,) * 3
        for c in range(3):
            if encoding == "colour":
                ratio = min(max(vals[c] / max(ref[c], MACRO_EPSILON), lo), hi)
                factor = 1.0 + strength * (ratio - 1.0)
            else:
                factor = 2.0 * vals[c] if encoding == "grey_centred" else vals[c]
            out[c] *= factor
            ref[c] *= factor
    return tuple(out)


# ── evolution during an event: the reference laws (spec §6.10) ───────────────

def line_state_after_passes(level, gain_per_pass, passes):
    """Rubbering or sweeping: level += gain * (1 - level) per car pass."""
    return 1.0 - (1.0 - level) * (1.0 - gain_per_pass) ** passes


def line_state_washed(level, wash, precipitation, dt):
    """Rain washing a line state: d level/dt = -wash * precipitation (mm/h) * level / 3600."""
    return level * math.exp(-wash * precipitation * dt / 3600.0)


def dew_point(t_air, relative_humidity):
    """Dew point (°C), Magnus formula."""
    a, b = 17.62, 243.12
    g = math.log(max(relative_humidity, 1e-6)) + a * t_air / (b + t_air)
    return b * g / (a - g)


def evaporation_rate(e0, c_wind, wind_speed, t_track, t_dew):
    """Reference evaporation (mm/h): e0 * (1 + c_wind * wind) * max(0, T_track - T_dew) / 10."""
    return e0 * (1.0 + c_wind * wind_speed) * max(0.0, t_track - t_dew) / 10.0


def water_step(depth, dt, precipitation, drain_rate, evaporation, accumulation=1.0, shelter=0.0):
    """Film depth (m) after dt seconds: d depth/dt = precipitation*(1-shelter)*A - drain - evaporation (all mm/h)."""
    rate = precipitation * (1.0 - shelter) * accumulation - drain_rate - evaporation
    return max(0.0, depth + rate / 1000.0 * dt / 3600.0)


def rut_depth_after_passes(depth, depth_per_pass, max_depth, passes):
    """Ruts: depth += rate * (1 - depth / max_depth) per pass, in closed form."""
    return max_depth - (max_depth - depth) * (1.0 - depth_per_pass / max_depth) ** passes


def wear_from_cars(cars, cars_to_worn):
    """The wear signal after `cars` cars: 1 - exp(-cars / cars_to_worn)."""
    return 1.0 - math.exp(-cars / cars_to_worn)


def track_temperature_step(t_track, dt, t_air, sun_gain, insolation, shade, tau):
    """First-order approach to T_air + sun_gain * insolation * (1 - shade) with time constant tau."""
    target = t_air + sun_gain * insolation * (1.0 - shade)
    return t_track + (target - t_track) * (1.0 - math.exp(-dt / tau))


# ── OpenUSD (spec §7.7; optional: needs the pxr module, pip install usd-core) ──

USD_SUFFIXES = {".usd", ".usda", ".usdc", ".usdz"}
STJ_LAYER_KEY = "stj"
_usdz_dirs = {}


def is_usd(path):
    return Path(str(path)).suffix.lower() in USD_SUFFIXES


def have_pxr():
    try:
        import pxr  # noqa: F401
        return True
    except ImportError:
        return False


def usd_stage(path):
    from pxr import Usd
    stage = Usd.Stage.Open(str(path))
    if stage is None:
        raise StjLoadError(f"{Path(path).name}: cannot open USD stage")
    return stage


def usd_attr_name(name):
    """glTF-style attribute name to its USD primvar name: '_STJ_SURF_LAYERS' -> 'stj_surf_layers'.

    STJ primvars use an stj_ prefix, not the stj: namespace: Blender's USD exporter drops per-corner
    FLOAT2 attributes whose names contain ':' (checked in Blender 5.2).
    """
    return name.lstrip("_").lower() if name.startswith("_") else name


def usd_names(path):
    """(material names, prim names and paths) of a USD file."""
    from pxr import Usd, UsdShade
    stage = usd_stage(path)
    materials, prims = [], []
    for p in stage.Traverse():
        prims += [p.GetName(), str(p.GetPath())]
        if p.IsA(UsdShade.Material):
            materials.append(p.GetName())
    return materials, prims


def usd_frame(path):
    """(upAxis, metersPerUnit) declared by a USD stage."""
    from pxr import UsdGeom
    stage = usd_stage(path)
    return UsdGeom.GetStageUpAxis(stage), UsdGeom.GetStageMetersPerUnit(stage)


def usd_variant_sets(path):
    """{variant set name: {variant names}} over all prims of a stage."""
    out = {}
    stage = usd_stage(path)          # keep the stage alive while its prims are visited
    for p in stage.Traverse():
        vsets = p.GetVariantSets()
        for name in vsets.GetNames():
            out.setdefault(name, set()).update(vsets.GetVariantSet(name).GetVariantNames())
    return out


def usd_material_meshes(stage, material):
    """[(Mesh prim, face indices or None)] drawn with the named material, directly or through GeomSubsets."""
    from pxr import UsdGeom, UsdShade
    out = []
    for p in stage.Traverse():
        if p.IsA(UsdGeom.Mesh):
            bound = UsdShade.MaterialBindingAPI(p).ComputeBoundMaterial()[0]
            subsets = UsdGeom.Subset.GetAllGeomSubsets(UsdGeom.Imageable(p))
            hit = False
            for sub in subsets:
                m = UsdShade.MaterialBindingAPI(sub.GetPrim()).ComputeBoundMaterial()[0]
                if m and m.GetPrim().GetName() == material:
                    out.append((p, list(sub.GetIndicesAttr().Get() or [])))
                    hit = True
            if not hit and bound and bound.GetPrim().GetName() == material:
                out.append((p, None))
    return out


def usd_primvar(mesh, name):
    """(interpolation, values as tuples) of a primvar on a Mesh prim, or None."""
    from pxr import UsdGeom
    pv = UsdGeom.PrimvarsAPI(mesh).GetPrimvar(name)
    if not pv or not pv.HasValue():
        return None
    vals = pv.ComputeFlattened()
    return pv.GetInterpolation(), [tuple(v) if hasattr(v, "__len__") else (v,) for v in vals]


def usd_texcoord_names(mesh):
    """Names of the texture-coordinate primvars of a Mesh prim."""
    from pxr import Sdf, UsdGeom
    return [p.GetPrimvarName() for p in UsdGeom.PrimvarsAPI(mesh).GetPrimvars()
            if p.GetTypeName().role == Sdf.ValueTypeNames.TexCoord2f.role]


def usdz_extract(path):
    """Unpack a .usdz into a temporary folder (once per run); return the root layer's path inside it."""
    import tempfile
    import zipfile
    path = Path(path).resolve()
    if path not in _usdz_dirs:
        folder = Path(tempfile.mkdtemp(prefix="stj_usdz_"))
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            z.extractall(folder)
        root = next((n for n in names if Path(n).suffix.lower() in {".usd", ".usda", ".usdc"}), None)
        if root is None:
            raise StjLoadError(f"{path.name}: no USD layer in the package")
        _usdz_dirs[path] = folder / root
    return _usdz_dirs[path]


def load_document(path):
    """The raw document of an STJ file: JSON, or the STJ data inside a USD layer or package."""
    path = Path(path)
    if is_usd(path):
        return usd_document(usdz_extract(path) if path.suffix.lower() == ".usdz" else path)
    return load_json(path)


def usd_document(path):
    """The STJ document stored in a USD root layer's customLayerData['stj'] (spec §7.8)."""
    if not have_pxr():
        raise StjLoadError(f"{Path(path).name}: reading STJ inside USD needs the pxr module (pip install usd-core)")
    from pxr import Sdf
    layer = Sdf.Layer.FindOrOpen(str(path))
    if layer is None:
        raise StjLoadError(f"{Path(path).name}: cannot open USD layer")
    text = (layer.customLayerData or {}).get(STJ_LAYER_KEY)
    if not text:
        raise StjLoadError(f"{Path(path).name}: no STJ document in customLayerData['{STJ_LAYER_KEY}']")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise StjLoadError(f"{Path(path).name}: the STJ document in the layer is not valid JSON: {e}")


def embed_document(doc, usd_path, out_path=None):
    """Write an STJ document into a USD layer's customLayerData['stj']."""
    from pxr import Sdf
    layer = Sdf.Layer.FindOrOpen(str(usd_path))
    data = dict(layer.customLayerData or {})
    data[STJ_LAYER_KEY] = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    layer.customLayerData = data
    if out_path and Path(out_path).resolve() != Path(usd_path).resolve():
        layer.Export(str(out_path))
    else:
        layer.Save()
