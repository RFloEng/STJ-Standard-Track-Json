#!/usr/bin/env python3
"""Canonical form of an STJ file: the same data always gives the same bytes (spec 3.9).

Use it before committing a track to version control, so a diff shows what changed and not how a tool
happened to write it.

Rules:
  - UTF-8, two-space indent, one newline at the end, no escaped non-ASCII.
  - Object keys: `$schema`, then `_metadata`, then `id`, `name`, then the rest in alphabetical order,
    then annotations (`_x`) and engine blocks (`x_y`) in alphabetical order.
  - Arrays keep their order: it can carry meaning (points, steps, notes).
  - Numbers: a float with a whole value is written as an integer (5.0 -> 5, -0.0 -> 0); others as the shortest
    text that reads back the same.
  - An array of plain numbers or short strings that fits in 100 columns is written on one line.

Usage:
  python tools/canonicalize.py FILE...            print the canonical form of the first file
  python tools/canonicalize.py --write FILE...    rewrite the files in place
  python tools/canonicalize.py --check FILE...    exit 1 when a file is not canonical
"""
import json
import sys
from pathlib import Path

FIRST = ("$schema", "_metadata", "id", "name")
INLINE_WIDTH = 100


def _key_order(key):
    if key in FIRST:
        return (0, FIRST.index(key), "")
    if key.startswith("x_"):
        return (3, 0, key)
    if key.startswith("_"):
        return (2, 0, key)
    return (1, 0, key)


def _number(v):
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return int(v)
    return v


def _scalar(v):
    return json.dumps(_number(v), ensure_ascii=False)


def _is_flat(arr):
    return all(isinstance(v, (int, float, str)) and not isinstance(v, bool) or v is None or isinstance(v, bool)
               for v in arr)


def dumps(node, indent=0):
    pad = "  " * indent
    if isinstance(node, dict):
        if not node:
            return "{}"
        items = sorted(node.items(), key=lambda kv: _key_order(kv[0]))
        body = ",\n".join(f"{pad}  {json.dumps(k, ensure_ascii=False)}: {dumps(v, indent + 1)}" for k, v in items)
        return "{\n" + body + "\n" + pad + "}"
    if isinstance(node, list):
        if not node:
            return "[]"
        if _is_flat(node):
            line = "[" + ", ".join(_scalar(v) for v in node) + "]"
            if len(line) + len(pad) <= INLINE_WIDTH:
                return line
        if all(isinstance(v, list) and _is_flat(v) for v in node):
            rows = [dumps(v, indent + 1) for v in node]
            if all("\n" not in r for r in rows):
                return "[\n" + ",\n".join(f"{pad}  {r}" for r in rows) + "\n" + pad + "]"
        return "[\n" + ",\n".join(f"{pad}  {dumps(v, indent + 1)}" for v in node) + "\n" + pad + "]"
    return _scalar(node)


def canonical_text(doc):
    return dumps(doc) + "\n"


def canonicalize_file(path, write=False):
    """(canonical text, whether the file already was)."""
    path = Path(path)
    raw = path.read_text(encoding="utf-8")
    text = canonical_text(json.loads(raw))
    if write and text != raw:
        path.write_text(text, encoding="utf-8", newline="\n")
    return text, text == raw


def main(argv):
    if not argv or "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0 if argv else 2
    write, check = "--write" in argv, "--check" in argv
    files = [a for a in argv if not a.startswith("--")]
    failed = False
    for i, f in enumerate(files):
        text, same = canonicalize_file(f, write=write)
        if check:
            if not same:
                print(f"not canonical: {f}")
                failed = True
        elif write:
            print(("unchanged " if same else "rewrote ") + f)
        elif i == 0:
            sys.stdout.write(text)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
