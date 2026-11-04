# STJ proposal: road cross-section and the authoring model

Status: **draft** 2026-11-04, for STJ v0.4. Nothing here is implemented yet.

Source: a design discussion about STJ as a non-destructive working format. The part that several engines can regenerate, and that Blender expresses naturally, is the road profile along the reference line (sections 1 to 5). Section 6 onwards takes a track editor such as BeamNG's World Editor as an example of how a track is authored, and adds what STJ is missing to hold that model: how a road relates to the terrain, road networks, and keeping hand-placed objects through regeneration.

---

## 1. The gap

A centerline file (spec §4.2, `reference.centerline`) knows the line in plan and elevation, and one lateral fact: half-widths, constant (`width`) or varying (`width_profile`). That is all. Specifically:

- **No banking.** Corners are flat across `t`. A banked turn, or a rally road that tilts into a corner, cannot be described. OpenDRIVE has `superelevation` for this; STJ only gets it if the file ships an `.xodr`.
- **No crossfall or crown.** Roads are not flat across: a crowned road falls away on both sides, a track drains to one side. This matters for water (puddles, drains in §6.9) and for what a car feels.
- **No shoulders, ditches or verge profile.** `edges` describes kerbs, verges and barriers by what they are, with a `width` and `height`, but not as a surface that leaves the road at a slope.
- **Consequence for tools.** `tools/ribbon_usd.py` builds a collision ribbon from the centerline and surface bands. That ribbon is flat across `t`, so a centerline-only track cannot get an honest collision surface. Converters that rebuild a road mesh have to invent the profile.

Files that ship an OpenDRIVE route are better off, because OpenDRIVE carries superelevation, crossfall and lane sections. The gap is for everything else: Blender-authored tracks, converted tracks, and tracks that want the profile in one place.

## 2. Proposed addition

A `cross_section` block on the centerline (the same place as `width_profile`). It is a **template** of lateral points, applied along `s` with banking on top.

```json
"reference": {
  "centerline": {
    "points": [ ... ],
    "width_profile": [[0, 3.5, 3.5], [900, 4.0, 4.0]],
    "cross_section": {
      "templates": {
        "crowned": {
          "points": [
            { "t": -6.0, "dz": -0.55, "surface": "grass" },
            { "t": -4.5, "dz": -0.30, "surface": "gravel" },
            { "t": -3.5, "dz":  0.00 },
            { "t":  0.0, "dz":  0.04 },
            { "t":  3.5, "dz":  0.00 },
            { "t":  4.5, "dz": -0.30, "surface": "gravel" },
            { "t":  6.0, "dz": -0.55, "surface": "grass" }
          ]
        }
      },
      "sections": [
        { "s_start": 0,   "s_end": 600, "template": "crowned" },
        { "s_start": 600, "s_end": 900, "template": "crowned", "blend": 40 }
      ],
      "bank": [[0, 0.0], [300, 0.0], [340, 0.06], [420, 0.06], [460, 0.0]]
    }
  }
}
```

**Fields**

- `templates`: named lateral profiles. `points` are ordered by increasing `t` (left is positive, as `t` elsewhere), with `dz` as height relative to the centerline at that `t`, in the road's own frame (before banking). An optional `surface` names a surface from `surfaces.library` for the strip that ends at that point (outwards from the previous point).
- `sections[]`: which template applies over which `s` range. `blend` is a distance (m) over which one template mixes into the next (linear in `dz` per matching `t`). Templates blended together must have the same number of points. The validator checks this.
- `bank`: `[[s, angle]]` in radians, linear between entries, positive when the left side is higher (OpenDRIVE `superelevation` convention). It rotates the whole cross-section about the centerline.
- Without `cross_section`, nothing changes: the road is flat across `t` and `width` or `width_profile` keeps its current meaning.

**How it relates to what exists**

- `width` or `width_profile` still define the drivable half-widths. Template points inside them are road; points outside are runoff. Surface bands (`surfaces.bands[]`) still win over a template's per-strip `surface`, so existing files behave the same.
- `edges` still describe kerbs and barriers. A kerb's `height` and `width` sit on top of the profile at the road edge.
- An OpenDRIVE route (`reference.opendrive`) wins: when it is present, its lateral profile applies and `cross_section` is ignored, with a validator note. The two should not disagree.

## 3. Mapping

| Target | How the profile maps |
|---|---|
| **OpenDRIVE** | `bank` becomes `<superelevation>`. Template slopes become `<crossfall>` or `<shape>`. Lane widths come from `width_profile`. Export is lossy for arbitrary `dz` points beyond what `<shape>` can hold; `_metadata.provenance.lost` should say so. |
| **OpenUSD** | The templates travel as `BasisCurves` or `stj:` typed attributes next to the document, so a USD tool can see the profile. The collision ribbon is generated from them (`ribbon_usd.py`). |
| **Blender** | The natural non-destructive form: a Geometry Nodes modifier turns the centerline curve into a mesh using the profile as a profile curve (Curve to Mesh), with `bank` as the curve's tilt. `docs/blender_mapping.md` already maps a named modifier to a scatter rule; this would map `STJ_Road_<id>` to `cross_section`. The exported mesh is the baked cache, and the rule stays in the document. |
| **Engines with splines** (UE splines, Unity splines, BeamNG roads) | Width, banking and a few profile points map to their road-spline parameters. Arbitrary profiles are approximated. |

## 4. Validator

- ERROR: template points not in increasing `t`; a section range outside the line, or sections overlapping.
- ERROR: a `blend` between templates with different point counts.
- WARN: `bank` beyond ±0.6 rad (about 34°); `dz` jumps larger than 1 m between neighbouring points (unit slip?).
- WARN: the profile at the road edge disagrees with the nearest edge `height`.
- NOTE: both `reference.opendrive` and `cross_section` present (the OpenDRIVE data wins).

## 5. Reference implementation

`stj_core` gets one function: `cross_section_at(doc, s)` returns the `[t, dz, surface]` points at `s` with `bank` applied. `ribbon_usd.py` then samples it per station instead of a flat quad row. Water-drain logic (§6.9) can read the same function to find low points.

## 6. The authoring model: what an editor like BeamNG's shows

A track editor of this kind defines a track in four layers:

1. **Terrain first**: a heightmap plus painted material layers.
2. **Roads as splines on the terrain**: nodes with position, width and per-node settings. A road either drapes over the terrain or carves the terrain to fit it.
3. **Objects placed on top** by rule (brush-painted density, seed, exclusion areas) or by hand.
4. **Generated geometry is a cache** of the splines and rules.

STJ already matches layers 1, 3 (rules) and 4 (in intent). It differs in three places, sections 7 to 9. The aim is that STJ can hold a project from such an editor without a converter guessing, not that STJ copies any editor's file format.

## 7. Road and terrain relation

STJ makes the road the master: the reference line comes first and the validator requires `geometry.terrain` to stay below it (§12). Editor workflows often run the other way, so a converter has no field to say which side wins.

```json
"reference": {
  "centerline": {
    "points": [ ... ],
    "terrain": { "mode": "carve", "shoulder_blend": 6.0, "falloff": "smooth" }
  }
}
```

- `mode`:
  - `drape`: the road follows the terrain height. The centerline `z` is a result, not an input.
  - `carve`: the terrain is cut or filled to meet the road. The road's `z` wins, and the terrain is shaped around it.
  - `free`: no rule. This is today's behaviour and the default.
- `shoulder_blend` (m): the distance from the road edge over which the terrain blends to its natural height.
- `falloff`: `linear` or `smooth` (smoothstep).
- Per-section overrides use the same `s` ranges as `cross_section.sections[]`: a bridge or tunnel stays `free`, a cutting uses `carve`.
- Validator:
  - For `carve`, WARN where the terrain lies above the road inside the blend distance (the cut was not applied).
  - For `drape`, WARN where the centerline `z` differs from the terrain by more than a tolerance.
  - The existing "terrain below the road" check only applies to `free`.
- Reference implementation: `stj_core` gets `terrain_at_road(doc, s, t)`, the terrain height after the rule is applied. A converter to a mesh-only engine bakes it.

## 8. Road networks

STJ has one reference line per layout, plus `side_roads[]` for rally junctions that competitors must not take. An editor project has a network: several named splines with junctions.

Proposal: an optional top-level `roads[]` for roads other than the reference line.

```json
"roads": [
  { "id": "service_road", "centerline": { "points": [ ... ], "width": { "left": 2.5, "right": 2.5 },
    "cross_section": { ... }, "terrain": { "mode": "drape" } },
    "drivable": true, "surface": "gravel" }
]
"junctions": [
  { "id": "j1", "roads": [ { "road": "reference", "s": 640 }, { "road": "service_road", "s": 0 } ] }
]
```

- Every road in `roads[]` uses the same `centerline` shape as `reference.centerline`, so cross-sections and terrain rules apply to it too.
- `junctions[]` connects roads by `s` on each. `side_roads[]` can then reference a junction instead of repeating a position.
- `s`-based things (timing, pace notes, bands) continue to belong to the reference line. A network road has its own `s` for its own bands and edges.
- A file with an OpenDRIVE route (`reference.opendrive`) already carries a network, and wins as in section 2.
- Out of scope: junction geometry (the mesh at the crossing) and traffic rules.

## 9. Authored versus generated

In an editor, a painted forest can be regenerated from its seed, but a tree the author moved by hand must survive regeneration. STJ scatter has a `seed`, and instances can be listed, but nothing says which is which.

- `instances[].source`: `authored` (default) or `generated`. Regeneration (for example by Blender Geometry Nodes or a converter) replaces `generated` instances and keeps `authored` ones.
- `scatter[]` gains `exclude_instances`: instance ids, or positions, to leave out of a generated layer, for the "I deleted that tree" case.
- Generated geometry, such as a road ribbon built from `cross_section`, carries a stamp in `_metadata.provenance` (the rule, its version, a hash of its inputs). A tool can tell when the cache is stale.
- `x_<engine>` blocks are untouched by regeneration.
- Validator: NOTE when `generated` instances exist without a seed or generator reference, since they cannot be regenerated.

## 10. Out of scope

- Arbitrary modifier stacks or procedural graphs. STJ stays a vocabulary: it carries the rule (a template, a bank angle, a terrain mode), and an editor such as Blender evaluates it.
- Lane markings and road paint (a decal problem, see `stj_visual_materials_proposal.md`). Spline-projected decals, as editors do them, are a separate proposal.
- Junction geometry and traffic rules.
- Any editor's file format. STJ takes the authoring model, not the format.

## 11. Questions for the author

- **Q1.** Should `dz` be relative to the centerline in the banked frame, or absolute heights from a datum? Recommended: relative, because a profile then reads the same on a flat and on a banked section.
- **Q2.** Should templates be allowed to carry more than one surface strip per side, or only the strip ending at each point? Recommended: the latter. It matches how surface bands are already described.
- **Q3.** Should `bank` live inside `cross_section`, or beside `width_profile`? Recommended: inside, so the whole lateral description is one block that can be removed together.
- **Q4.** Should the exporter be required to write the baked mesh as well as the rule? Recommended: yes, as a cache with a note of which rule produced it. Engines that need meshes then keep working, and the rule can regenerate it.
- **Q5.** Is `terrain.mode` (section 7) a property of the road, or of the terrain (`geometry.terrain`)? Recommended: the road, with `s` ranges. Only the road knows where a bridge or cutting is, and a terrain can then serve several roads.
- **Q6.** Should network roads (section 8) be a new `roads[]` block, or should `layouts[]` carry them? Recommended: `roads[]`. Layouts replace the reference wholesale, and a network road coexists with the reference line.
- **Q7.** Should `source: authored | generated` (section 9) be per instance, or per scatter layer plus a list of manual overrides? Recommended: per instance for hand placements, and per layer for the generated bulk. A layer of 15 000 generated trees should not list each one.
