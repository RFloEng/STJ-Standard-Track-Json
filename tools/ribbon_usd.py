"""
Collision ribbon from a centerline and surface bands, as an OpenUSD mesh
=======================================================================
Makes a centerline-only STJ track drivable: one quad mesh along the reference line, a GeomSubset
and a material per surface (spec §6.3, §7.2). Needs the pxr module: pip install usd-core.

    python tools/ribbon_usd.py <track.usda | doc.stj.json> -o <ribbon.usda> [--mesh-id ID] [--step 5]

--mesh-id   the geometry.meshes id the ribbon will have; materials bound to it in surfaces.bindings
            keep their names, other surfaces get materials named STJ__surface__<id>
--step      longitudinal spacing of cross-sections (m), default 5. Band boundaries and centerline
            vertices are always included.
"""

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stj_core as core  # noqa: E402

CLASS_COLORS = {"asphalt": (0.34, 0.34, 0.36), "concrete": (0.6, 0.6, 0.58), "kerb": (0.8, 0.27, 0.23),
                "grass": (0.36, 0.6, 0.24), "gravel": (0.75, 0.61, 0.39), "dirt": (0.6, 0.46, 0.32),
                "sand": (0.88, 0.8, 0.57), "snow": (0.93, 0.95, 0.96), "rock": (0.52, 0.49, 0.45)}


def _in_band(line, band, s, t):
    lo, hi = band["s_start"], band["s_end"]
    on_s = lo <= s <= hi if lo <= hi else line.closed and (s >= lo or s <= hi)
    return on_s and band["t_min"] <= t <= band["t_max"]


def build(doc, mesh_id=None, step=5.0):
    """(points, face vertex counts, indices, {surface: [face index]}, {surface: material name})."""
    line = core.reference_line(doc)
    if line is None:
        raise SystemExit("reference.centerline is required")
    surf = doc.get("surfaces") or {}
    bands = surf.get("bands") or []
    if not bands:
        raise SystemExit("surfaces.bands is required")
    names = {}
    for b in surf.get("bindings", []):
        if b.get("mesh_ref") == mesh_id and "material" in b:
            names.setdefault(b["surface"], b["material"])
    stations = set(line.s[:-1] if line.closed else line.s)
    stations.update(i * step for i in range(int(line.length // step) + 1))
    for b in bands:
        stations.update((b["s_start"], b["s_end"]))
    stations = sorted(s for s in stations if 0 <= s <= line.length)
    if line.closed and stations[-1] >= line.length - 1e-9:
        stations.pop()                      # a closed ribbon joins its last station to the first
    ts = sorted({b["t_min"] for b in bands} | {b["t_max"] for b in bands})
    k = len(ts)
    points = [line.point(s, t) for s in stations for t in ts]
    counts, indices, faces = [], [], {}
    n = len(stations)
    for i in range(n if line.closed else n - 1):
        i1 = (i + 1) % n
        s0, s1 = stations[i], stations[i1] if i1 else line.length
        s_mid = 0.5 * (s0 + s1)
        for j in range(k - 1):
            t_mid = 0.5 * (ts[j] + ts[j + 1])
            sid = None
            for b in bands:                  # later bands win (spec §6.3)
                if _in_band(line, b, s_mid, t_mid):
                    sid = b["surface"]
            if sid is None:
                continue
            faces.setdefault(sid, []).append(len(counts))
            counts.append(4)
            # counter-clockwise seen from above: along s, then to the left
            indices += [i * k + j, i1 * k + j, i1 * k + j + 1, i * k + j + 1]
    return points, counts, indices, faces, {sid: names.get(sid, f"STJ__surface__{sid}") for sid in faces}


def add_ribbon(stage, prim_path, doc, mesh_id=None, step=5.0):
    """Define the ribbon mesh at prim_path in an open stage; returns the mesh prim."""
    from pxr import Sdf, UsdGeom, UsdShade, Vt
    points, counts, indices, faces, materials = build(doc, mesh_id, step)
    mesh = UsdGeom.Mesh.Define(stage, prim_path)
    mesh.CreatePointsAttr(Vt.Vec3fArray([tuple(round(c, 3) for c in p) for p in points]))
    mesh.CreateFaceVertexCountsAttr(Vt.IntArray(counts))
    mesh.CreateFaceVertexIndicesAttr(Vt.IntArray(indices))
    mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
    lib = (doc.get("surfaces") or {}).get("library") or {}
    mat_root = prim_path.rsplit("/", 1)[0] + "/materials"
    for sid, face_ids in faces.items():
        name = materials[sid]
        mat = UsdShade.Material.Define(stage, f"{mat_root}/{name}")
        sh = UsdShade.Shader.Define(stage, f"{mat_root}/{name}/surface")
        sh.CreateIdAttr("UsdPreviewSurface")
        sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(CLASS_COLORS.get((lib.get(sid) or {}).get("class"), (0.6, 0.6, 0.6)))
        sh.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.9)
        mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
        subset = UsdGeom.Subset.CreateGeomSubset(mesh, name, UsdGeom.Tokens.face, Vt.IntArray(face_ids),
                                                 UsdShade.Tokens.materialBind)
        UsdShade.MaterialBindingAPI.Apply(subset.GetPrim()).Bind(mat)
    return mesh.GetPrim()


def write_ribbon(path, doc, mesh_id=None, step=5.0):
    """A standalone .usda with the ribbon at /ribbon/mesh (Z up, metres)."""
    from pxr import Usd, UsdGeom
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    root = UsdGeom.Xform.Define(stage, "/ribbon")
    stage.SetDefaultPrim(root.GetPrim())
    add_ribbon(stage, "/ribbon/mesh", doc, mesh_id, step)
    stage.GetRootLayer().Save()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--mesh-id")
    ap.add_argument("--step", type=float, default=5.0)
    a = ap.parse_args(argv)
    doc, _chain = core.resolve(a.file)
    write_ribbon(a.out, doc, a.mesh_id, a.step)
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
