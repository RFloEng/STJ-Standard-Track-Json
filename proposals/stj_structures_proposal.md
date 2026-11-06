# STJ proposal: structures (bridges, tunnels and the like)

Status: **accepted** 2026-11-06 with the recommended answers of §5 (D1 to D4), and **implemented** in v0.3 (draft): spec §7.1, `stj_core.structure_defaults` and `structure_at`, the validator, and the gravel stage example. A gallery's reverb is `underpass` (the draft said `stands`, which is a grandstand sound). A bridge implies no audio zone: open air is the default.

Source: the question "does STJ say which part of the mesh is a road, a bridge, a tunnel?", asked on 2026-11-03, and the points where a structure already matters to STJ.

---

## 1. The gap

STJ knows what a road is made of (surfaces) and where it is (`s`, `t`). It has no single statement that a stretch of road is a **bridge**, a **tunnel** or an **underpass**. The fact leaks out in several unrelated places:

| Where | What it says today |
|---|---|
| `water.shelter[] {kind: tunnel \| bridge \| roof \| canopy}` | Where rain does not reach, by an `s` band |
| `audio.zones[] {reverb: tunnel \| underpass \| garage}` | How a stretch sounds |
| `environment.probes[]` | Where to capture local reflections, "such as tunnels" |
| `pacenotes[] {kind: bridge \| tunnel}` | A note for the co-driver |
| `centerline.terrain.sections[]` | A bridge or tunnel stays `free` (§7.1), but only by the author's remembering to say so |
| ASPRS class 17, bridge deck | A source of meshes in a scan (§5.2) |

An engine that wants tunnel lighting, no rain on a deck, a different reverb or "no overtaking here" has to assemble that from several blocks, and nothing ties them together. Nothing marks the deck or the walls as a mesh either.

A related problem: `shelter` with `kind: bridge` is ambiguous. A bridge keeps rain off the road **under** it and not off its own deck.

## 2. Proposal

A top-level `structures[]`, along the reference line (or another road):

```json
"structures": [
  { "id": "viaduct_1", "kind": "bridge", "s_start": 1500, "s_end": 1560, "name": "Pont del Diable",
    "mesh": { "mesh_ref": "stage_visual", "prim": "/track/structures/viaduct_1" } },
  { "id": "tunnel_1", "kind": "tunnel", "s_start": 820, "s_end": 960, "clearance": 5.2 },
  { "id": "under_1", "kind": "underpass", "road": "service", "s_start": 40, "s_end": 52,
    "carried_by": "viaduct_1" }
]
```

- `kind`: `bridge`, `tunnel`, `underpass` (a road passing under something), `gallery` (a covered road open on one side), `other`. An overpass is a `bridge` on the other road.
- `s_start`, `s_end` (m) on the named road. `road` is `reference` by default, or a `roads[]` id.
- `clearance` (m): the free height above the road, for tunnels, galleries and underpasses.
- `mesh {mesh_ref, prim}`: the deck, walls or ceiling in a USD file, so a tool can tell structure from road.
- `carried_by`: for an underpass, the structure above it.

### 2.1 What follows from a kind

The structure states a **fact**, and the defaults below follow from it. An explicit entry in the block concerned always wins; the defaults only fill what the file leaves out. `stj_core.structure_defaults(doc)` returns them as data, so a converter can apply them or ignore them.

| Kind | Rain shelter on the road | Reverb | Terrain rule |
|---|---|---|---|
| `bridge` | none (the deck is open) | `open` | `free` over the span |
| `tunnel` | 1 | `tunnel` | `free` over the span |
| `underpass` | 1 | `underpass` | `free` over the span |
| `gallery` | 0.7 | `underpass` | `free` over the span |

A pace note may name the structure it belongs to (`structure: "viaduct_1"`).

### 2.2 What it does not do

- No structural engineering: no span, load or material.
- No junction geometry (see `roads[]` and `junctions[]`).
- The mesh remains ordinary USD. `structures[].mesh` only names it.

## 3. Mapping

| Source | Into `structures[]` |
|---|---|
| OpenDRIVE `<tunnel>` and `<bridge>` objects | `kind`, `s_start`, `s_end` from their `s` and `length` |
| LAS class 17 (bridge deck) | a `bridge` over the `s` range of the points; the mesh as `mesh` |
| Game track files with tunnel and bridge flags (BeamNG, Speed Dreams) | `kind` and range |
| Blender | an empty or collection named `STJ__structure__<id>` |

## 4. Validator

- ERROR: `s_end` not greater than `s_start`; a range beyond the road; an unknown `road`, `mesh_ref` or `carried_by`.
- WARN: two structures of the same road overlapping, unless one is an underpass.
- WARN: a `tunnel` or `underpass` without `clearance`.
- NOTE: an old-style `shelter` of kind `tunnel` or `bridge` that no structure explains.
- NOTE: a pace note of kind `bridge` or `tunnel` with no structure at that `s`.

## 5. Decisions (accepted 2026-11-06: every recommended answer)

- **D1.** Add `structures[]` at all, or leave the facts in the blocks that use them? Recommended: **add it**.
- **D2.** Should defaults follow from the kind (§2.1), or should it be a tag only? Recommended: **defaults as data** (`structure_defaults`), with the explicit blocks winning.
- **D3.** Should a structure name its mesh (`mesh {mesh_ref, prim}`)? Recommended: **yes, optional**.
- **D4.** Should a pace note be able to name a structure? Recommended: **yes, optional `structure`**.
