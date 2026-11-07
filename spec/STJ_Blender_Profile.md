# STJ Blender profile, version 0.1

The profile says how a `.blend` file holds an STJ track, so that every translator reads and writes Blender
the same way. It is separate from the STJ spec and has its own version (`PROFILE_VERSION` in
`tools/blender/stj_profile.py`). Decisions: `proposals/stj_blender_profile_proposal.md`. Background and the
rows that are still advice: `docs/blender_mapping.md`.

"Must" and "must not" are normative for the rows in section 4, which were run in Blender. The rows of
`docs/blender_mapping.md` section 3 that are not listed here stay advice until they are probed.

## 1. Scope and Blender versions

- The profile targets **Blender LTS releases**. The rows below were run on **5.2 LTS** (5.2.2). The checker
  warns for any other major.minor, because the bundled OpenUSD and the USD exporter differ between versions.
- Each row will record the lowest LTS it was tested on as more versions are probed.

## 2. The scene

- The scene property `stj_blender_profile` holds the profile version (`"0.1"`). A checker rejects a newer
  version than it knows and warns when the property is missing.
- The text block **`track.stj.json`** is the base document. It must be a complete STJ document except for
  the parts the scene supplies (section 4). A scene without it is an error.
- **Objects win.** The exported document is the text block with the scene's data applied as an RFC 7396
  merge patch. A value in the scene that replaces a different value in the text block is reported as a note.
  Arrays the scene supplies (`timing.split_points`, `race.grid`, `race.pit_boxes`, `race.spawns`) replace the
  text block's arrays whole.
- Axes need no conversion: Blender's Z-up scene coordinates are STJ coordinates, metres.

## 3. Names

`STJ::<category>::<id>[::<part>]`. In a USD file the same name is `STJ__<category>__<id>[__<part>]`, because
USD forbids `::`; both spellings are the same name. Blender's `.001` suffix for a second object of the same
name is ignored, so two objects with the same STJ name are an error.

- `<category>` is one of the categories of section 4. An unknown category is a warning.
- `<id>` is lowercase letters, digits and underscores (the STJ `id` rule). It must not contain `__`.
- A name that starts with `STJ` and does not have this form is an error.
- Other STJ-looking names (`STJ_Collision`, `STJ_Visual`) are collections and are not parsed as entities.

## 4. Entity rows (normative)

| Name | Blender type | Fills | Rule |
|---|---|---|---|
| `STJ::reference::<id>` | Curve | `reference.centerline` | Exactly one. The first spline gives `points` in world coordinates; a cyclic spline gives `closed: true`; a Bezier spline gives `tangents_out` = 3 (handle_right − point) and `tangents_in` = 3 (point − handle_left) (the cubic Bezier as a Hermite segment). The curve's custom property `stj` (a dictionary) is merged into the centerline (width, `cross_section`, …). |
| `STJ::timing::start_finish`, `::start`, `::finish`, `::stop` | Empty | `timing.<name>` | The empty is projected onto the reference line: `s` is its station. `t_min` and `t_max` come from the `stj` property. A gate more than the half-width plus 5 m from the line is a warning. |
| `STJ::timing::<id>` (any other id) | Empty | `timing.split_points[]` | As above; the list is sorted by `s`. |
| `STJ::grid::<n>` | Empty | `race.grid[]` | `<n>` is the position (1, 2, …). The pose is the empty's world position and its heading. |
| `STJ::pit::<id>`, `STJ::pit::<id>::garage` | Empty | `race.pit_boxes[]` | The pose of the box, and `garage_pose`. A box without a pose is dropped. |
| `STJ::spawn::<id>` | Empty | `race.spawns[]` | The pose. |
| `STJ::surface::<id>` | Material | surface binding | `<id>` should be in `surfaces.library`; otherwise a warning. |

**Heading** is the angle of the empty's local X axis in the world, counter-clockwise from +X (rad), the STJ
`heading`. An empty's arrow shows the direction a vehicle faces.

## 5. Export

`tools/blender/stj_blender.py` (run inside Blender):

```
blender -b track.blend --python tools/blender/stj_blender.py -- lint
blender -b track.blend --python tools/blender/stj_blender.py -- export <out_dir> [name]
```

`lint` reports ERROR, WARN and NOTE and exits 1 on an error. `export` runs the lint, refuses on an error,
and writes `<name>.stj.json` (the document) and `<name>.usd` (Blender's USD export, with the document in the
root layer's `customLayerData["stj"]`, spec §7.8). The decisions are in `tools/blender/stj_profile.py`, which
does not need Blender and is tested without it.

## 6. Conformance

`examples/make_blender_reference.py` builds `test_ring_profile.blend`, which uses every row of section 4. A
translator is conformant when reading that file gives the Test Ring document (`tests/test_blender_profile.py`
runs the lint and the export on it when Blender is available).

## 7. Not in version 0.1

Import (USD or document back to a scene), meshes and collision collections, roads and junctions, structures,
scatter, cameras, edges, audio, physics and the sky. Their conventions are in `docs/blender_mapping.md`; each
becomes normative when it is probed and has a row here.
