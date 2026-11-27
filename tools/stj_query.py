"""
STJ reference queries
=====================
What surface is at a point (spec §6.3), what an OpenDRIVE lane material says there, where an OpenCRG patch is read
(§7.2), and how a USD stage with another up axis or unit is brought into the STJ frame (§4.5). The examples in
`examples/features/` come with the results these queries must give; another implementation can compare itself with
the same file. Reading meshes needs the pxr module (pip install usd-core). Small and slow by design: no spatial index.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stj_core as core  # noqa: E402

# ── frames (spec §4.5) ───────────────────────────────────────────────────────


def to_stj(point, up_axis="Z", metres_per_unit=1.0):
    """A point of a USD stage in the STJ frame: metres, Z up. A Y-up stage turns +90 degrees about X, as glTF does."""
    x, y, z = (float(c) * metres_per_unit for c in point)
    if up_axis == "Z":
        return (x, y, z)
    if up_axis == "Y":
        return (x, -z, y)
    raise ValueError(f"unknown up axis {up_axis!r}")


# ── collision triangles ──────────────────────────────────────────────────────

class CollisionMesh:
    """One mesh entry's collision prims as triangles in the STJ frame, each with its material name and what is needed
    to read a primvar at a point of it."""

    def __init__(self, entry, path):
        from pxr import Usd, UsdGeom, UsdShade
        self.id = entry["id"]
        self.stage = stage = core.usd_stage(path)        # kept: its prims expire with it
        up, mpu = UsdGeom.GetStageUpAxis(stage), UsdGeom.GetStageMetersPerUnit(stage)
        cache = UsdGeom.XformCache()
        self.triangles = []          # (points, prim path, material name, face, face corners, vertex indices)
        self.primvars = {}
        for prim in core.usd_collision_meshes(stage, entry.get("roles", [])):
            mesh = UsdGeom.Mesh(prim)
            matrix = cache.GetLocalToWorldTransform(prim)
            points = [to_stj(matrix.Transform(_vec3d(p)), up, mpu) for p in mesh.GetPointsAttr().Get()]
            counts = list(mesh.GetFaceVertexCountsAttr().Get())
            indices = list(mesh.GetFaceVertexIndicesAttr().Get())
            bound = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()[0]
            material = {f: bound.GetPrim().GetName() if bound else None for f in range(len(counts))}
            for subset in UsdGeom.Subset.GetAllGeomSubsets(UsdGeom.Imageable(prim)):
                m = UsdShade.MaterialBindingAPI(subset.GetPrim()).ComputeBoundMaterial()[0]
                if m:
                    for f in subset.GetIndicesAttr().Get() or []:
                        material[f] = m.GetPrim().GetName()
            corner = 0
            for face, n in enumerate(counts):
                ring = [(corner + k, indices[corner + k]) for k in range(n)]
                corner += n
                for k in range(1, n - 1):
                    tri = (ring[0], ring[k], ring[k + 1])
                    self.triangles.append(([points[v] for _c, v in tri], str(prim.GetPath()), material[face], face,
                                           [c for c, _v in tri], [v for _c, v in tri]))
            self.primvars[str(prim.GetPath())] = prim

    def hits(self, x, y):
        """(height, barycentric weights, triangle) of every triangle a vertical line at (x, y) meets."""
        for tri in self.triangles:
            (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = tri[0]
            den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(den) < 1e-12:
                continue
            a = ((y1 - y2) * (x - x2) + (x2 - x1) * (y - y2)) / den
            b = ((y2 - y0) * (x - x2) + (x0 - x2) * (y - y2)) / den
            c = 1.0 - a - b
            if min(a, b, c) >= -1e-6:
                yield a * z0 + b * z1 + c * z2, (a, b, c), tri

    def value(self, tri, bary, name):
        """A primvar at a point of a triangle: per face as it is, otherwise interpolated between its corners."""
        _points, path, _material, face, corners, vertices = tri
        found = core.usd_primvar(self.primvars[path], core.usd_attr_name(name))
        if found is None:
            raise ValueError(f"primvar '{name}' missing on {path}")
        interpolation, values = found
        if interpolation == "uniform":
            return values[face]
        if interpolation == "constant":
            return values[0]
        where = corners if interpolation == "faceVarying" else vertices
        return tuple(sum(w * values[i][k] for w, i in zip(bary, where)) for k in range(len(values[where[0]])))


def _vec3d(p):
    from pxr import Gf
    return Gf.Vec3d(float(p[0]), float(p[1]), float(p[2]))


# ── surface map weights (spec §6.3, §8.7) ────────────────────────────────────

def _texel(image, u, v, channel):
    """Bilinear sample at a UV: texel centres at (i + 0.5) / width, v up, repeating."""
    fx, fy = u * image.width - 0.5, (1.0 - v) * image.height - 0.5
    i, j = int(fx // 1), int(fy // 1)
    a, b = fx - i, fy - j

    def g(p, q):
        return image.get(p % image.width, q % image.height, channel)
    return (1 - a) * (1 - b) * g(i, j) + a * (1 - b) * g(i + 1, j) + (1 - a) * b * g(i, j + 1) + a * b * g(i + 1, j + 1)


def map_weights(surface_map, base_dir, mesh, tri, bary, x, y):
    """[(surface id, weight)] of a surface map at a point, before `contact` is applied; [] where it gives nothing."""
    palette, w = surface_map["palette"], surface_map["weights"]
    encoding = w["encoding"]
    values = [0.0] * len(palette)
    if encoding == "vertex_top3":
        names = w["indices"]
        if isinstance(names, list):
            ids = [int(mesh.value(tri, bary, n)[0]) for n in names]
        else:
            ids = [int(i) for i in mesh.value(tri, bary, names)]
        wa, wb = mesh.value(tri, bary, w["weights"])[:2]
        for index, weight in zip(ids, (wa, wb, max(0.0, 1.0 - wa - wb))):
            values[index] += weight
    elif encoding == "vertex_dense":
        flat = [c for name in w["attributes"] for c in mesh.value(tri, bary, name)]
        values = flat[:len(palette)]
    else:
        uv = mesh.value(tri, bary, w["texcoord"]) if "texcoord" in w else None
        if encoding == "id_map":                       # the nearest texel: ids are never interpolated
            image = core.read_png(Path(base_dir) / w["maps"][0]["uri"])
            if uv is None:
                x0, y0, x1, y1 = w["extent"]
                if not (x0 <= x <= x1 and y0 <= y <= y1):
                    return []
                i = round((x - x0) / (x1 - x0) * (image.width - 1))
                j = round((y1 - y) / (y1 - y0) * (image.height - 1))
            else:
                i = int((uv[0] % 1.0) * image.width) % image.width
                j = int(((1.0 - uv[1]) % 1.0) * image.height) % image.height
            index = int(image.get(i, j, 0))
            if not 0 <= index < len(palette):
                return []
            values[index] = 1.0
        else:
            at = 0
            for entry in w["maps"]:
                image = core.read_png(Path(base_dir) / entry["uri"])
                for channel in entry.get("channels", "rgba"):
                    c = 0 if channel == "gray" else "rgba".index(channel)
                    if at < len(palette):
                        v = image.sample(w["extent"], x, y, c) if uv is None else _texel(image, uv[0], uv[1], c)
                        values[at] = 0.0 if v is None else v / image.maxval
                    at += 1
                    if channel == "gray":
                        break
    total = sum(values)
    return [(sid, v / total) for sid, v in zip(palette, values) if v > 0] if total > 0 else []


# ── OpenDRIVE lane materials (spec §6.3, level 2) ────────────────────────────

def _poly(element, ds):
    return sum(float(element.get(k, 0.0)) * ds ** p for p, k in enumerate("abcd"))


def _last_at(elements, key, s):
    found = [e for e in elements if float(e.get(key, 0.0)) <= s + 1e-9]
    return max(found, key=lambda e: float(e.get(key, 0.0))) if found else None


def opendrive_lane_material(path, road_id, s, t):
    """The `surface` of the lane <material> at (s, t) of a road, or None (outside every lane, or no material)."""
    road = next((r for r in ET.parse(path).getroot().findall("road") if r.get("id") == str(road_id)), None)
    if road is None:
        raise ValueError(f"no road '{road_id}' in {path}")
    lanes = road.find("lanes")
    section = _last_at(lanes.findall("laneSection"), "s", s)
    if section is None:
        return None
    offset = _last_at(lanes.findall("laneOffset"), "s", s)
    t -= _poly(offset, s - float(offset.get("s", 0.0))) if offset is not None else 0.0
    ds = s - float(section.get("s", 0.0))
    side = section.find("left" if t > 0 else "right")
    if side is None:
        return None
    outer = 0.0
    for lane in sorted(side.findall("lane"), key=lambda e: abs(int(e.get("id")))):
        width = _last_at(lane.findall("width"), "sOffset", ds)
        outer += _poly(width, ds - float(width.get("sOffset", 0.0))) if width is not None else 0.0
        if abs(t) <= outer + 1e-9:
            material = _last_at(lane.findall("material"), "sOffset", ds)
            return None if material is None else material.get("surface")
    return None


# ── the surface at a point (spec §6.3) ───────────────────────────────────────

def _substituted(contact, substitutions):
    """One step of substitutions; two entries that become one surface add their weights."""
    out = {}
    for sid, weight in contact:
        sid = substitutions.get(sid, sid)
        out[sid] = out.get(sid, 0.0) + weight
    return list(out.items())


class SurfaceQuery:
    """`at(x, y, signals)`: the contact of the highest collision triangle under (x, y), or, where no mesh is, of the
    levels that need no mesh. `doc` is a resolved document (a variant: core.resolve of its override file)."""

    def __init__(self, doc, base_dir):
        self.doc, self.base_dir = doc, Path(base_dir)
        self.surfaces = doc.get("surfaces") or {}
        self.meshes = [CollisionMesh(m, self.base_dir / m["uri"]) for m in (doc.get("geometry") or {}).get("meshes", [])
                       if "collision" in m.get("roles", [])]
        self.ref = core.reference_line(doc)

    def _mesh_contact(self, mesh, tri, bary, x, y, state):
        material, prim = tri[2], tri[1]
        for surface_map in self.surfaces.get("maps", []):
            if surface_map["mesh_ref"] != mesh.id or surface_map["material"] != material:
                continue
            if "when" in surface_map and not core.eval_condition(surface_map["when"], state):
                continue
            weights = map_weights(surface_map, self.base_dir, mesh, tri, bary, x, y)
            if weights:
                if surface_map.get("contact") == "dominant":
                    weights = [(max(weights, key=lambda e: e[1])[0], 1.0)]
                return weights, "map"
            break
        for binding in self.surfaces.get("bindings", []):
            if binding["mesh_ref"] != mesh.id or ("when" in binding and not core.eval_condition(binding["when"], state)):
                continue
            if binding.get("material", object()) == material or binding.get("prim", object()) == prim:
                return [(binding["surface"], 1.0)], "binding"
        for prefix in ("STJ__surface__", "STJ::surface::"):
            if material and material.startswith(prefix):
                return [(material[len(prefix):], 1.0)], "material name"
        return None, None

    def _line_contact(self, x, y):
        if self.ref is None:
            return None, None
        s, t = self.ref.project(x, y)
        materials = self.surfaces.get("opendrive_materials")
        opendrive = (self.doc.get("reference") or {}).get("opendrive")
        if materials and opendrive:
            route = opendrive.get("route") or []
            if len(route) > 1:
                raise ValueError("this query reads a reference of one OpenDRIVE road")
            path = self.base_dir / opendrive["uri"]
            road = route[0]["road"] if route else ET.parse(path).getroot().find("road").get("id")
            name = opendrive_lane_material(path, road, s, t)
            if name in materials:
                return [(materials[name], 1.0)], "opendrive"
        bands = [b for b in self.surfaces.get("bands", []) if core.in_band(b, s, t)]
        if bands:
            return [(bands[-1]["surface"], 1.0)], "band"
        return None, None

    def at(self, x, y, signals=None):
        """{"contact": [(surface id, weight)], "level": ..., "height": z or None}."""
        state = {"wear": 0.5, "wetness": 0.0, **(signals or {})}
        hits = [(z, bary, tri, mesh) for mesh in self.meshes for z, bary, tri in mesh.hits(x, y)]
        contact = level = height = None
        if hits:
            height, bary, tri, mesh = max(hits, key=lambda h: h[0])
            contact, level = self._mesh_contact(mesh, tri, bary, x, y, state)
        if contact is None:
            contact, level = self._line_contact(x, y)
        if contact is None and "default" in self.surfaces:
            contact, level = [(self.surfaces["default"], 1.0)], "default"
        if contact is None:
            return {"contact": [], "level": None, "height": height}
        return {"contact": _substituted(contact, self.surfaces.get("substitutions") or {}), "level": level, "height": height}


# ── OpenCRG (spec §7.2) ──────────────────────────────────────────────────────

class CrgGrid:
    """The elevation grid of a small ASCII OpenCRG file, format LRFI with evenly spaced long sections and no
    reference-line channels (a straight patch). For anything else, use the ASAM OpenCRG library."""

    def __init__(self, path):
        text = Path(path).read_text(encoding="ascii").splitlines()
        end = next(i for i, line in enumerate(text) if line.startswith("$$$$"))
        keys, section = {}, None
        for line in text[:end]:
            if line.startswith("$"):
                section = line.strip().upper()           # only $ROAD_CRG holds the keys; $CT is free text
            elif section == "$ROAD_CRG" and "=" in line and not line.startswith("*"):
                k, v = line.split("=", 1)
                keys[k.strip().upper()] = float(v)
        sections = sum(1 for line in text[:end] if line.upper().startswith("D:LONG SECTION"))
        if "#:LRFI" not in (line.strip().upper() for line in text[:end]) or sections < 2:
            raise ValueError(f"{path}: not a plain LRFI grid")
        self.u0, self.du = keys.get("REFERENCE_LINE_START_U", 0.0), keys["REFERENCE_LINE_INCREMENT"]
        self.v0, self.dv = keys["LONG_SECTION_V_RIGHT"], keys["LONG_SECTION_V_INCREMENT"]
        self.rows = []
        for line in text[end + 1:]:
            if line.strip():
                self.rows.append([float(line[k:k + 10]) for k in range(0, 10 * sections, 10)])

    def z(self, u, v):
        """Bilinear height at (u, v), or None outside the grid."""
        fu, fv = (u - self.u0) / self.du, (v - self.v0) / self.dv
        nu, nv = len(self.rows), len(self.rows[0])
        if not (-1e-9 <= fu <= nu - 1 + 1e-9 and -1e-9 <= fv <= nv - 1 + 1e-9):
            return None
        i, j = min(max(int(fu), 0), nu - 2), min(max(int(fv), 0), nv - 2)
        a, b = fu - i, fv - j
        r = self.rows
        return ((1 - a) * (1 - b) * r[i][j] + a * (1 - b) * r[i + 1][j]
                + (1 - a) * b * r[i][j + 1] + a * b * r[i + 1][j + 1])


def crg_lookup(entry, grid, s, t):
    """Where a geometry.crg entry in mode `attached` is read at (s, t) and what it adds to the road's height:
    {"u", "v", "dz"}, or None where the entry does not reach."""
    if entry.get("mode", "attached") != "attached":
        raise ValueError("this query reads the mode 'attached' only")
    if not entry.get("s_start", 0.0) - 1e-9 <= s <= entry.get("s_end", float("inf")) + 1e-9:
        return None
    u = grid.u0 + (s - entry.get("s_start", 0.0))
    v = t - entry.get("t_offset", 0.0)
    z = grid.z(u, v)
    if z is None:
        return None
    return {"u": u, "v": v, "dz": entry.get("z_offset", 0.0) + entry.get("z_scale", 1.0) * z}
