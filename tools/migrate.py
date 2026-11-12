#!/usr/bin/env python3
"""Bring an STJ document, or an override file, up to a later spec version (spec 3.10).

Each step is a function in MIGRATIONS keyed by (from, to). A step edits the document in place and returns
notes about what it changed. 0.1 -> 0.2 and 0.2 -> 0.3 only add optional features, so they change the version
number and nothing else; later versions that rename or remove a field put the rewrite here, after the field
has been deprecated for one minor version (the policy is in spec 3.10).

Usage:
  python tools/migrate.py FILE [OUT] [--to VERSION] [--dry-run]
    OUT defaults to FILE (rewritten in canonical form). --dry-run writes nothing: it prints the steps and
    the lines of the canonical text that would change.
"""
import copy
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import canonicalize  # noqa: E402

VERSIONS = ("0.1", "0.2", "0.3")


def _bump(doc, new):
    doc["_metadata"]["version"] = new
    return []


MIGRATIONS = {
    ("0.1", "0.2"): lambda doc: _bump(doc, "0.2"),
    ("0.2", "0.3"): lambda doc: _bump(doc, "0.3"),
}


def migrate(doc, to=VERSIONS[-1]):
    """(migrated copy, notes). Raises ValueError for an unknown version or a downgrade."""
    doc = copy.deepcopy(doc)
    cur = (doc.get("_metadata") or {}).get("version")
    if cur not in VERSIONS or to not in VERSIONS:
        raise ValueError(f"unknown version: {cur if cur not in VERSIONS else to}")
    if VERSIONS.index(to) < VERSIONS.index(cur):
        raise ValueError(f"cannot migrate down from {cur} to {to}")
    notes = []
    while cur != to:
        nxt = VERSIONS[VERSIONS.index(cur) + 1]
        notes += [f"{cur} -> {nxt}: {n}" for n in MIGRATIONS[(cur, nxt)](doc)] or [f"{cur} -> {nxt}"]
        cur = nxt
    return doc, notes


def main(argv):
    if not argv or "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0 if argv else 2
    to = VERSIONS[-1]
    dry = False
    args = []
    it = iter(argv)
    for a in it:
        if a == "--to":
            to = next(it)
        elif a == "--dry-run":
            dry = True
        else:
            args.append(a)
    src = Path(args[0])
    out = Path(args[1]) if len(args) > 1 else src
    old_text = src.read_text(encoding="utf-8")
    try:
        doc, notes = migrate(json.loads(old_text), to)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if dry:
        diff = list(difflib.unified_diff(old_text.splitlines(), canonicalize.canonical_text(doc).splitlines(),
                                         f"{src.name} (now)", f"{out.name} (migrated to {to})", lineterm="", n=0))
        print(f"{src.name}: would become {to}; nothing written" + "".join(f"\n  {n}" for n in notes))
        print("\n".join(diff) if diff else "  (the canonical text is unchanged)")
        return 0
    out.write_text(canonicalize.canonical_text(doc), encoding="utf-8", newline="\n")
    print(f"{src.name}: now {to}" + "".join(f"\n  {n}" for n in notes))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
