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
| `STJ::surface::<id>` | Material | `surfaces.library.<id>` | `<id>` should be in `surfaces.library`; otherwise a warning. When the material has a custom property `stj` (a dictionary), it is the surface's library entry (`class`, `mf_scaling`, `by_tyre_class`, `function`, …) and is written over the text block's entry. Import fills it. A material with no property leaves the text block's entry as it is. |
| `STJ::geo::origin` | Empty | `environment.geo_reference`, `north_heading`, `timezone`, `default_time` | At most one, at the frame origin (z = 0 is at `altitude`). Its custom property `stj` holds `latitude`, `longitude`, `altitude`, `proj`, `vertical_datum` (→ `geo_reference`), `timezone`, `date` and `local_time` (→ `default_time`). Its **heading points at true north** (the arrow shows north): it gives `north_heading`, written only when it differs from the document's value, or from +Y when the document has none. Latitude and longitude out of range are an error. |
| `STJ::sun::<id>` | Sun light | `environment.lighting.sun.direction` | At most one. The direction towards the sun is the light's +Z axis. The sun follows date and time (from the geo origin) and nothing is written while it stays within 0.5° of the computed position (`stj_core.sun_direction`). A sun moved away from it is written as a fixed `direction`, with a note, because the file then no longer follows the clock. Any other light type is an error. |
| `STJ::road::<id>` | Curve | `roads[]` | The curve gives `centerline.points`, `closed` and tangents, as the reference curve does. The `stj` property holds the other fields of the road (`name`, `drivable`, `surface`, …); its key `centerline` holds the other fields of the centerline (`width`, `cross_section`, …). |
| `STJ::junction::<id>` | Empty | `junctions[]` | The `stj` property is the junction (`kind`, `through`, `roads`, `height`, `mesh`). The empty sits at the joint point for display; moving it changes nothing, because the joint follows the roads. |
| `STJ::edge::<id>` | Curve | `edges[]` | A curve along the reference line at the edge's `t`. The `stj` property is the edge (`side`, `s_start`, `s_end`, `kind`, `style`, …). While the curve is where the property puts it, the property is written as it is; once the curve is moved, `side`, `s_start`, `s_end` and `t` are read from the curve. |
| `STJ::pit_lane::pit_lane` | Curve | `timing.pit_lane` | The curve gives the pit-lane `path`; the `stj` property holds the rest (`entry_s`, `exit_s`, `speed_limit`, `limit_start`, …). At most one. |
| `STJ::line::<id>` | Curve | `race.racing_lines[]` | The curve gives `points` (and `closed`, when cyclic); the `stj` property holds the rest (`purpose`, `vehicle_class`, and the per-point `speed` and `width` arrays). Adding or removing points leaves `speed` and `width` the old length: the checker warns, and the arrays must be edited with the curve. |
| `STJ::marking::<id>` | Curve | `markings[]` | A line marking (`t`) is an open curve along its road at that offset; a patch (`t_min`, `t_max`: stop line, crossing, arrows, hatching) is a closed curve through its four corners. The `stj` property holds the rest (`kind`, `road`, `style`, `colour`, …). While the curve is where the property puts it, the property is written as it is; once the curve is moved, `s_start`, `s_end` and `t` (or `t_min`, `t_max`) are read from it. |
| `STJ::camera::<set>::<id>` | Camera | `cameras.sets[]` | At the camera's `position`, looking at `look_at` when it has one. The `stj` property is the camera (`kind`, `fov`, `active`, …). A camera that is moved or turned writes its new `position` and `look_at`. |
| `STJ::building::<id>`, `STJ::area::<id>` | Curve (closed) | `buildings[]`, `areas[]` | A closed curve through the footprint (or the polygon) at the building's `z`; the curve gives the ring, and the `stj` property holds everything else (`name`, `class`, `holes`, `height`, `tags`, `source`, …). Pulling a corner out changes the footprint. |
| `STJ::water::<id>`, `STJ::service::<id>` | Curve (closed) | `water.bodies[]`, `race.service_areas[]` | A water body with a `path` (a river or ford; `[x, y, z, width, depth]` per point) is an open curve through the first three numbers, and the width and depth ride in the property; the last ones carry on if points are added. A water body with an `outline`, and every service area, is a closed curve: the curve gives the `outline` (x, y; the height is the body's `level`) or the `polygon` (x, y, z), and the `stj` property holds the rest. A water body without an outline (a ford with a `path`) is an empty, as below. |
| `STJ::scatter::<id>`, `STJ::sector::<id>`, `STJ::post::<id>`, `STJ::marshal_vehicle::<id>`, `STJ::restricted::<id>`, `STJ::audio_zone::<id>`, `STJ::probe::<id>` | Empty | `water.bodies[]`, `scenery.scatter[]`, `marshals.sectors[]`, `.posts[]`, `.vehicles[]`, `.restricted_zones[]`, `audio.zones[]`, `environment.probes[]` | The `stj` property is the entry. The empty is a handle for the list and its order; nothing about its place is written, except for probes and marshal posts, which sit at their `position` and write a new one when the empty is moved. |
| `STJ::ground_layer::<id>`, `STJ::ground_material::<mesh>_<n>`, `STJ::sky::sky`, `STJ::screen::<id>` | Empty | `ground.layers.<id>`, `ground.materials[n]`, `environment.sky`, `screens[]` | The `stj` property is the entry: a ground layer (textures, tile, projection, surface), a ground material (its `mesh_ref`, `palette`, `weights`, `blend`; `<n>` is its place in the list, since the entry has no id), the sky (`model`, `turbidity`, `clouds`, …), a screen (`target`, `content`, `when`). The empty is a handle: nothing about its place is written. Importing into Blender also makes a World with a Sky Texture node named `STJ::sky`, so the viewport shows a sky; it is a view only, and the data stays on the empty. The textures and the weights stay files next to the document. Importing a document also rebuilds each ground material of the imported mesh as shader nodes (`tools/blender/stj_ground.py`): the three layer indices and weights, the height, linear or mask blend, the world, road and texcoord projections and the macro maps, with the same maths as `stj_core.ground_blend`. The nodes are a view of the `ground` block, never read back; a ground that uses something not built (a wetness map is skipped; a mask blend without its masks, or another weight encoding) keeps Blender's preview surface and the import says so. |
| `STJ::surfaces::surfaces` | Empty | `surfaces` (but its `library`) | The `stj` property is the rest of the `surfaces` block: `default`, `bindings`, `bands`, `maps`, `substitutions`, `reference_mu`, … The library entries live on the materials. A handle only. |
| `STJ::environment::environment`, `STJ::track_info::track_info`, `STJ::layout::<id>`, `STJ::variant::<id>` | Empty | `environment` (the rest), `track_info`, `layouts[]`, `variants[]` | The `stj` property is the block or the entry. Handles only. |
| `STJ::dynamic::dynamic` | Empty | `dynamic` | The `stj` property is the whole `dynamic` block (line states, water, ruts, wear, track temperature). A handle only: the laws are tables, not shapes. |
| `STJ::chunk::<id>`, `STJ::tiles::tiles` | Empty | `geometry.chunks[]`, `geometry.tiles` | The `stj` property is the entry. A chunk sits at its `origin` and writes a new one when the empty is moved; the tile grid is a handle only. |
| `STJ::terrain::<id>` | Mesh (grid) | `geometry.terrain`, or `geometry.terrains[]` when there are several | One vertex per heightmap sample, in rows from the north edge (sample `(i, j)` at `x = x_min + i*dx`, `y = y_max - j*dy`), height in z. The `stj` property is the terrain entry (`heightmap`, `holes`, `layers`, `macro`, …). While the heights are as imported the entry is written as it is and the heightmap file is not touched. Once a vertex height changes, the heightmap is written again at its `uri` (next to the exported document) in the entry's format, `height_min` and `height_max` are recomputed, and `nodata` is dropped, because the mesh has a height everywhere. Sculpting must keep one vertex per sample; moving vertices sideways changes nothing. A mesh with another vertex count is an error. Samples with no data come in at the lowest valid height. |
| `STJ::structure::<id>` | Empty | `structures[]` | The `stj` property is the structure. The empty sits at the middle of its `s` range on its road, for display; the structure follows its road, so moving the empty changes nothing. |
| `STJ::animated::<id>` | Empty | `animated_objects[]` | The `stj` property is the entry (`kind`, `target`, `playback`, `speed_by`, …). |
| `STJ::prototype::<id>::body` | Mesh with a Rigid Body | `scenery.prototypes.<id>.physics` | The proxy body of a prototype that has `physics`: a box, sphere or cylinder mesh with its origin at the base centre, sized from `physics.shape`, and a Blender Rigid Body. `physics.mode` `static` is a Passive body and every other mode an Active one; `mass`, `friction` and `restitution` are the Rigid Body's; the shape is the collision shape (`box` → Box, `sphere` → Sphere, `cylinder` → Cylinder, `capsule` → Capsule with the total height, `mesh` → Convex Hull) and the object's dimensions (scale included). Only what changed since import is written: an untouched body gives the stored `physics` back exactly, a changed mass or size replaces just that field, and a body added by hand makes a new `physics`. Cone, Mesh and Compound shapes have no STJ shape and are left as stored. The other fields (`center_of_mass`, `inertia`, `tether`, `break_impulse`, `stiffness`, `respawn`) stay in the prototype's property. |
| `STJ::prototype::<id>` | Empty | `scenery.prototypes.<id>` | The `stj` property is the prototype (`class`, `collision`, `breakable`, `mesh`, `physics`, …). The physics stays in the property: it is not mapped to a Blender Rigid Body yet. |
| `STJ::instance::<prototype>_<n>` | Mesh (vertices only) | `scenery.instances[]` | One vertex per instance: its position. The point attributes `stj_heading` and `stj_scale` (0 = no scale given) hold the other two numbers of each transform. The `stj` property holds `prototype`, `when`, `cull_distance`, `source`, … |
| `STJ::emitter::<id>` | Speaker (or Empty), or Curve for a line source | `audio.emitters[]` | A point source is a Speaker object (an Empty is read the same) at the emitter's `position`; the `stj` property is the rest of the entry. A moved empty writes its new position. An emitter with a `path` and no `position` is an open curve through the path. |
| `STJ::crowd::<id>` | Empty | `scenery.crowds[]` | The `stj` property is the crowd (`prototype`, `area`, `density`, `behaviour`, `when`). |
| collection `STJ::mesh::<id>` | Collection | `geometry.meshes[]` | The mesh objects inside are exported to one USD file by Blender's USD exporter. The `stj` property holds `roles` (required) and the rest of the entry (`uri`, `lod`, `decal`, `chunk`, `baked`, …); `uri` defaults to `<id>.usd`. |

**Collections.** An imported track is sorted into collections under `STJ`, one for each kind of thing, so a big track is easy to work on (hide the scenery, lock the roads): `STJ Track` (reference, timing, sun, sky, environment, layouts, variants, …), `STJ Roads` (roads, junctions, edges, markings), `STJ Race` (grid, pit boxes, spawns, racing lines, marshals, service areas), `STJ Scenery` (instances, prototypes, structures, buildings, areas, crowds, scatter), `STJ Ground` (terrain, water, ground layers) and `STJ Cameras and audio`. The names have no `::`, so they are not entities. Which collection an object is in never changes what is exported, and you can move objects between them or add your own.

**Order and exactness.** Blender sorts objects by name, so the order of a list in the document is kept in the
`_i` key of the object's `stj` property (roads, junctions, edges, cameras). The keys `_i`, `_set`, `_shared` and `_orig`
are the profile's own and are never written to the document. A pose or a gate imported from a document keeps
its original form in `stj` (`pose`, `s`) and is written back in that form while the object has not moved; once
it moves, it is written as a world pose or a new `s`. This is what makes import then export give the document
back exactly.

Blender stores coordinates as 32-bit floats, so a coordinate far from the origin (2527.638) comes back as
2527.6379. A curve therefore keeps the coordinates it was imported with in `stj._orig` (points and tangents), and
a point that is still where the import put it, within what a 32-bit float can lose, is written as it was imported;
a moved point is rounded to four decimals, or fewer where 32 bits cannot hold them. A `null` in a record is kept
as a marker inside Blender (a custom property cannot hold `null`) and comes back as `null`.

**Heading** is the angle of the empty's local X axis in the world, counter-clockwise from +X (rad), the STJ
`heading`. An empty's arrow shows the direction a vehicle faces.

## 5. Export

`tools/blender/stj_blender.py` (run inside Blender):

```
blender -b track.blend --python tools/blender/stj_blender.py -- lint
blender -b track.blend --python tools/blender/stj_blender.py -- export <out_dir> [name]
```

`lint` reports ERROR, WARN and NOTE and exits 1 on an error. `export` runs the lint, refuses on an error,
and writes `<name>.stj.json` (the document), `<name>.usd` (the track stage: Z up, metres, and the document in
the root layer's `customLayerData["stj"]`, spec §7.8) and one USD file per mesh collection, at its `uri`
(Blender's USD exporter, with the preview surface and MaterialX). The decisions are in `tools/blender/stj_profile.py`, which
does not need Blender and is tested without it.

## 6. Import

```
blender -b --factory-startup --python tools/blender/stj_blender.py -- import <track.stj.json|.usd> <out.blend>
```

`import` is the inverse of `export` (`scene_from_document` in `stj_profile.py`). From a document, or the
document inside a USD, it builds a fresh `.blend` that follows sections 2 to 4:

- the reference curve (a Bezier spline when the centerline has tangents, otherwise a poly spline), cyclic when
  the line is `closed`;
- empties for the timing lines and splits, the grid, the pit boxes with their garage and the spawns; a pose
  given as `s`, `t` becomes a world position and heading;
- the geo origin, with the coordinates, height, date, time and time zone, pointing at true north;
- a Sun light at the position the date, time and place give (or at the fixed `direction`);
- a material `STJ::surface::<id>` for each surface of the library;
- the text block `track.stj.json`: the document without what the objects now hold.

What an object cannot hold stays in the text block (a split with a name, a pose with extra keys, a timing
line given by two end points, a geo reference with other keys). Importing and then exporting gives the same
document, except that poses given as `s`, `t` come back as world poses.

## 7. Conformance

`examples/make_blender_reference.py` builds `test_ring_profile.blend`, which uses every row of section 4. A
translator is conformant when:

- reading that file gives the Test Ring document;
- importing a document and exporting it again gives the document back, exactly, for the example documents
  (the Test Ring, the Test Ring GP and the stage Coll de Prova) and for the stages the Richard Burns Rally converter writes;
- exporting the reference `.blend`, importing the result and comparing the two scenes (`stj_blender.py dump`)
  gives the same objects at the same places.

`tests/test_blender_profile.py` runs all three when Blender is available. Mesh files go through Blender's USD
import and export, so their geometry and materials are kept but the files are not byte for byte the same (nested
custom properties and per-corner attributes are dropped by Blender, `docs/blender_mapping.md` section 4).

## 8. Not in version 0.1

The rest of `environment` (weather, season, climate, lighting other than the sun, …) is `STJ::environment::environment`, an Empty whose `stj` property is that block; the geo origin, the sun, the sky and the probes are their own objects, and the sun is still computed from the merged environment. Things STJ does not describe yet are not in this profile.
Animation (`animated_objects`) is not given Blender actions: STJ names the prims that move and their rules, and the keyframes live in the mesh files, which Blender's USD import and export carry as time samples. Conventions that are still advice are in `docs/blender_mapping.md`.
