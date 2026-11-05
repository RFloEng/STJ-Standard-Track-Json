"""
LAS to heightmap
================
Grids the ground points of a LiDAR tile into an STJ heightmap (spec §7.4) and writes the source and
derivation records that go with it (spec §5.2). STJ does not process point clouds: this is the converter
step that sits in front of it.

    python tools/las_dtm.py tile.las -o terrain/height.png --cell 1.0 [--classes 2,11]
                            [--format png16|raw_f32] [--extent X0 Y0 X1 Y1] [--offset X Y]
                            [--fill-radius N] [--source-id als_2023] [--crs EPSG:25831] [--json out.json]

- Reads uncompressed LAS 1.0 to 1.4 with the standard library. `.laz` and COPC need the optional
  `laspy` package with a LAZ backend: pip install "laspy[lazrs]".
- Keeps the points whose ASPRS class is in --classes (default 2, ground) and drops withheld points.
- The grid is vertex-registered like the heightmap (sample (i, j) at x = x0 + i*cell, y = y1 - j*cell,
  row 0 = north): each point goes to the nearest vertex and a vertex takes the mean height of its points.
- Vertices with no point have no measurement. They stay `nodata` (-9999 in raw_f32; code 0 in png16),
  unless --fill-radius N fills them by inverse-distance weighting from measured vertices within N cells.
- --offset X Y is subtracted from the coordinates, to bring a survey's large projected coordinates to a
  local origin (spec §4.4). The tool prints the `environment.origin_offset` that goes with it.
- --json writes the `heightmap` block, with `derived` and `nodata`, and the `scan.sources[]` entry.
"""

import argparse
import json
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stj_core as core  # noqa: E402

NODATA_F32 = -9999.0
# ASPRS point data record formats 0-5 keep the class in the low 5 bits of byte 15; 6-10 in the whole byte 16
_CLASS_AT = {**{f: (15, 0x1F) for f in range(0, 6)}, **{f: (16, 0xFF) for f in range(6, 11)}}


class LasError(Exception):
    pass


def read_points(path, classes=None):
    """(x, y, z, class) of the points in a LAS file, in the file's coordinates, withheld points dropped."""
    path = Path(path)
    if path.suffix.lower() in (".laz", ".copc") or path.name.lower().endswith(".copc.laz"):
        yield from _read_with_laspy(path, classes)
        return
    blob = path.read_bytes()
    if blob[:4] != b"LASF":
        raise LasError(f"{path.name}: not a LAS file (no LASF signature)")
    major, minor = blob[24], blob[25]
    header_size, offset = struct.unpack_from("<HI", blob, 94)
    fmt_byte, rec_len = blob[104], struct.unpack_from("<H", blob, 105)[0]
    if fmt_byte & 0x80:
        raise LasError(f"{path.name}: compressed points (LAZ) need laspy: pip install \"laspy[lazrs]\"")
    fmt = fmt_byte & 0x3F
    if fmt not in _CLASS_AT:
        raise LasError(f"{path.name}: unknown point data record format {fmt}")
    count = struct.unpack_from("<I", blob, 107)[0]
    if (major, minor) >= (1, 4):
        count = struct.unpack_from("<Q", blob, 247)[0] or count
    sx, sy, sz, ox, oy, oz = struct.unpack_from("<6d", blob, 131)
    cls_at, cls_mask = _CLASS_AT[fmt]
    withheld_mask = 0x80 if fmt < 6 else None        # formats 6-10 keep the flags in byte 15
    want = None if classes is None else set(classes)
    if offset + count * rec_len > len(blob):
        raise LasError(f"{path.name}: {count} points of {rec_len} bytes do not fit in the file")
    for k in range(count):
        base = offset + k * rec_len
        x, y, z = struct.unpack_from("<3i", blob, base)
        cls = blob[base + cls_at] & cls_mask
        if fmt < 6:
            if blob[base + 15] & withheld_mask:
                continue
        elif blob[base + 15] & 0x04:
            continue
        if want is not None and cls not in want:
            continue
        yield x * sx + ox, y * sy + oy, z * sz + oz, cls


def _read_with_laspy(path, classes):
    try:
        import laspy
    except ImportError:
        raise LasError(f"{path.name}: LAZ and COPC need the laspy package: pip install \"laspy[lazrs]\"") from None
    want = None if classes is None else set(classes)
    with laspy.open(str(path)) as f:
        for chunk in f.chunk_iterator(1_000_000):
            for x, y, z, c in zip(chunk.x, chunk.y, chunk.z, chunk.classification):
                if want is None or int(c) in want:
                    yield float(x), float(y), float(z), int(c)


def grid(points, extent, cell, offset=(0.0, 0.0)):
    """Mean height per vertex: (nx, ny, heights row-major with row 0 north, None where empty, points used)."""
    x0, y0, x1, y1 = extent
    nx, ny = round((x1 - x0) / cell) + 1, round((y1 - y0) / cell) + 1
    total, count = [0.0] * (nx * ny), [0] * (nx * ny)
    used = 0
    for x, y, z, _c in points:
        i = round((x - offset[0] - x0) / cell)
        j = round((y1 - (y - offset[1])) / cell)
        if 0 <= i < nx and 0 <= j < ny:
            k = j * nx + i
            total[k] += z
            count[k] += 1
            used += 1
    return nx, ny, [total[k] / count[k] if count[k] else None for k in range(nx * ny)], used


def fill_voids(heights, nx, ny, radius):
    """Inverse-distance fill of empty vertices from measured ones within `radius` cells; returns the new list."""
    out = list(heights)
    r = int(radius)
    for j in range(ny):
        for i in range(nx):
            if heights[j * nx + i] is not None:
                continue
            num = den = 0.0
            for dj in range(-r, r + 1):
                for di in range(-r, r + 1):
                    ii, jj = i + di, j + dj
                    if 0 <= ii < nx and 0 <= jj < ny and (di or dj) and di * di + dj * dj <= r * r:
                        v = heights[jj * nx + ii]
                        if v is not None:
                            w = 1.0 / (di * di + dj * dj)
                            num += w * v
                            den += w
            if den:
                out[j * nx + i] = num / den
    return out


def write_heightmap(path, fmt, nx, ny, heights):
    """Write the grid; returns the heightmap fields (format, height_min, height_max, nodata)."""
    measured = [h for h in heights if h is not None]
    if fmt == "raw_f32":
        data = struct.pack(f"<{nx * ny}f", *[NODATA_F32 if h is None else h for h in heights])
        Path(path).write_bytes(data)
        return {"format": "raw_f32", "nodata": NODATA_F32}
    lo = math.floor(min(measured) * 100) / 100 if measured else 0.0
    hi = math.ceil(max(measured) * 100) / 100 if measured else 1.0
    if hi <= lo:
        hi = lo + 0.01
    # 0 = no measurement; a measured height never takes it, so the lowest ones share code 1
    codes = [0 if h is None else max(1, round((h - lo) / (hi - lo) * 65535)) for h in heights]
    core.write_png(path, nx, ny, codes, 1, 16)
    return {"format": "png16", "height_min": lo, "height_max": hi, "nodata": 0}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("las")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--cell", type=float, required=True, help="grid spacing in metres")
    ap.add_argument("--classes", default="2", help="ASPRS classes to keep, comma separated (default 2)")
    ap.add_argument("--format", choices=["png16", "raw_f32"], default="raw_f32")
    ap.add_argument("--extent", type=float, nargs=4, metavar=("X0", "Y0", "X1", "Y1"),
                    help="grid extent in the track's coordinates (default: the points' bounds)")
    ap.add_argument("--offset", type=float, nargs=2, default=(0.0, 0.0), metavar=("X", "Y"))
    ap.add_argument("--fill-radius", type=float, default=0.0, help="fill voids from measured cells within N cells")
    ap.add_argument("--source-id", default="scan")
    ap.add_argument("--crs", help="coordinate system of the survey, such as EPSG:25831")
    ap.add_argument("--vertical-datum")
    ap.add_argument("--reference", help="where the survey came from")
    ap.add_argument("--json", help="write the heightmap block and the scan source here")
    a = ap.parse_args(argv)
    if a.cell <= 0:
        raise SystemExit("--cell must be positive")
    classes = [int(c) for c in a.classes.split(",") if c.strip()]
    try:
        pts = list(read_points(a.las, classes))
    except LasError as e:
        raise SystemExit(f"las_dtm: {e}")
    if not pts:
        raise SystemExit(f"las_dtm: no points of class {classes} in {a.las}")
    ox, oy = a.offset
    if a.extent:
        extent = list(a.extent)
    else:
        xs, ys = [p[0] - ox for p in pts], [p[1] - oy for p in pts]
        extent = [math.floor(min(xs) / a.cell) * a.cell, math.floor(min(ys) / a.cell) * a.cell,
                  math.ceil(max(xs) / a.cell) * a.cell, math.ceil(max(ys) / a.cell) * a.cell]
    nx, ny, heights, used = grid(pts, extent, a.cell, a.offset)
    voids = sum(1 for h in heights if h is None)
    filled = False
    if a.fill_radius > 0 and voids:
        heights = fill_voids(heights, nx, ny, a.fill_radius)
        filled = True
    left = sum(1 for h in heights if h is None)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    fields = write_heightmap(a.out, a.format, nx, ny, heights)

    area = (extent[2] - extent[0]) * (extent[3] - extent[1])
    density = round(used / area, 3) if area > 0 else None
    block = {"uri": Path(a.out).name, **fields, "size": [nx, ny],
             "extent": extent,
             "derived": {"source": a.source_id, "product": "dtm", "classes": classes, "cell_size": a.cell,
                         "method": "binning" + (" + idw fill" if filled else ""),
                         "void_fill": ("interpolated" if filled else "none") if voids else "none"}}
    source = {"id": a.source_id, "format": Path(a.las).suffix.lstrip(".").lower() or "las", "classified": True}
    for key, val in (("crs", a.crs), ("vertical_datum", a.vertical_datum), ("reference", a.reference),
                     ("point_density", density)):
        if val:
            source[key] = val
    print(f"{used} points of class {classes} on a {nx} x {ny} grid of {a.cell:g} m "
          f"({voids} empty vertices, {left} left without a measurement) -> {a.out}")
    if a.offset != (0.0, 0.0):
        print(f"environment.origin_offset: x_original = x + [{ox:g}, {oy:g}]")
    if a.json:
        Path(a.json).write_text(json.dumps({"heightmap": block, "scan_source": source}, indent=2), encoding="utf-8")
        print(f"records -> {a.json}")
    else:
        print(json.dumps({"heightmap": block, "scan_source": source}, indent=2))


if __name__ == "__main__":
    main()
