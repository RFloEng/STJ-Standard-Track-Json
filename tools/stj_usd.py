"""
STJ and OpenUSD
===============
Puts an STJ document inside a USD layer, takes it out again, and packages a track as one .usdz
(spec §7.8). Needs the pxr module: pip install usd-core.

    python tools/stj_usd.py embed   <doc.stj.json> <stage.usda> [-o out.usda]
    python tools/stj_usd.py extract <track.usda | track.usdz> [-o out.stj.json]
    python tools/stj_usd.py package <track.usda> -o <track.usdz>

`embed` writes the document into the root layer's customLayerData["stj"]. If the stage does not exist it is
created: an empty track, Z up and in metres.
`extract` writes it out as plain JSON, so it is never hidden inside the package.
`package` writes a .usdz: the root layer first, then every file the STJ document and the USD
layers reference, stored uncompressed and 64-byte aligned as the USDZ format requires.
"""

import argparse
import json
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stj_core as core  # noqa: E402

URI_KEYS = {"uri", "override", "payload"}
# what the USDZ format allows inside a package
USDZ_TYPES = {".usd", ".usda", ".usdc", ".usdz", ".png", ".jpg", ".jpeg", ".exr", ".avif", ".m4a", ".mp3", ".wav"}


def document_files(node, out):
    """Relative file paths an STJ document references (uri, override, payload keys)."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "authoring_source":
                continue                 # optional; packaged only when present (see package)
            if k in URI_KEYS and isinstance(v, str) and not v.startswith("data:"):
                out.add(v)
            else:
                document_files(v, out)
    elif isinstance(node, list):
        for v in node:
            document_files(v, out)
    return out


def usd_files(root):
    """Files a USD layer depends on (sub-layers, references, payloads, textures), relative to its folder."""
    from pxr import UsdUtils
    layers, assets, _unresolved = UsdUtils.ComputeAllDependencies(str(root))
    base = Path(root).resolve().parent
    out = set()
    for p in [l.realPath for l in layers] + list(assets):
        if not p:
            continue
        try:
            out.add(Path(p).resolve().relative_to(base).as_posix())
        except ValueError:
            raise SystemExit(f"{p} is outside the package folder; a .usdz holds only files below {base}")
    return out


def write_usdz(root, out_path, extra):
    """Root layer first; every member stored and its data aligned to 64 bytes (USDZ rules)."""
    root = Path(root).resolve()
    base = root.parent
    names = [root.name] + sorted(n for n in extra if n != root.name)
    banned = [n for n in names if Path(n).suffix.lower() not in USDZ_TYPES]
    if banned:
        raise SystemExit("a .usdz may hold only USD layers, images and audio; convert or leave out: " + ", ".join(banned)
                         + " (overrides become USD layers, meshes USD; spec §7.8)")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_STORED) as z:
        for name in names:
            src = base / name
            if not src.is_file():
                raise SystemExit(f"missing file referenced by the track: {name}")
            data = src.read_bytes()
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            header = z.fp.tell() + 30 + len(name.encode("utf-8"))
            pad = (-(header + 4)) % 64
            info.extra = struct.pack("<HH", 0x1986, pad) + b"\0" * pad
            z.writestr(info, data)
    return names


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("embed")
    e.add_argument("doc")
    e.add_argument("stage")
    e.add_argument("-o", "--out")
    x = sub.add_parser("extract")
    x.add_argument("track")
    x.add_argument("-o", "--out")
    p = sub.add_parser("package")
    p.add_argument("track")
    p.add_argument("-o", "--out", required=True)
    a = ap.parse_args(argv)
    if not core.have_pxr():
        raise SystemExit("needs the pxr module: pip install usd-core")
    if a.cmd == "embed":
        core.embed_document(core.load_json(a.doc), a.stage, a.out)
        print(f"embedded {a.doc} -> {a.out or a.stage}")
    elif a.cmd == "extract":
        path = Path(a.track)
        layer = core.usdz_extract(path) if path.suffix.lower() == ".usdz" else path
        text = json.dumps(core.usd_document(layer), indent=2, ensure_ascii=False) + "\n"
        if a.out:
            Path(a.out).write_text(text, encoding="utf-8")
            print(f"extracted -> {a.out}")
        else:
            sys.stdout.write(text)
    else:
        root = Path(a.track)
        doc = core.usd_document(root)
        files = document_files(doc, set()) | usd_files(root)
        src = (doc.get("_metadata") or {}).get("authoring_source")
        if src and (root.parent / src["uri"]).is_file():
            files.add(src["uri"])
        names = write_usdz(root, a.out, files)
        print(f"packaged {len(names)} files -> {a.out}")


if __name__ == "__main__":
    main()
