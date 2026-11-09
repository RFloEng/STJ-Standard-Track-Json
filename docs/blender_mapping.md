# STJ in Blender: what the .blend, glTF and USD can hold

Goal: a track is authored in **one `.blend` file** with as few files next to it as possible. An exporter then writes the delivery package that converters read: a **USD stage** (`.usda`, or a single `.usdz`) with the STJ document inside it (spec §3.1, §7.8).

**Where this page stands.** The rules a translator follows are in [the STJ Blender profile](../spec/STJ_Blender_Profile.md), which is normative and has been run on Blender 5.2 LTS; this page is the background: the probes and the reasoning behind them, and conventions that are still advice. STJ geometry is OpenUSD only (spec §7.7). §1 and §2 are the record of the Blender 5.2 **glTF probe**, which is what showed that glTF drops per-face data, the sky, physics and speakers; the results are kept because they are measurements, and they explain why USD is the container. §4 is the USD probe, and §3 lists the exporter's conventions as they stand now.

Everything below was **checked in Blender 5.2.0 LTS**, headless, by building a scene, saving, reopening and exporting glTF with the bundled exporter. To reproduce: `blender -b --factory-startup --python tools/blender/blend_probe.py -- <out_dir>` writes `report.json`. The v0.2 rows come from `blend_probe_v02.py -- <out_dir> <any.wav>`, which writes `report_v02.json` and a 16-bit PNG. `tools/stj_core.read_png` decodes that PNG correctly, filters included.

## 1. Results of the glTF probe

| STJ data | How it is stored in Blender | Survives save and reopen | Survives glTF export |
|---|---|---|---|
| The STJ document (metadata, surface library, pacenotes, weather…) | Text datablock `track.stj.json` | ✓ byte-exact | ✗ (exporter writes it out) |
| OpenDRIVE file | Text datablock `track.xodr` | ✓ | ✗ (exporter writes it out) |
| Per-surface data | Material custom property `stj` (nested dict) | ✓ | ✓ material `extras` |
| Per-object data (timing, roles, prototype semantics, `x_<engine>` blocks) | Object custom property `stj` | ✓ | ✓ node `extras` |
| Collection role (`collision`, `visual`) | Collection custom property | ✓ | ✓ with "full collection hierarchy" |
| Track-wide data | Scene custom property | ✓ | ✓ scene `extras` |
| Surface id per face | INT face attribute | ✓ | ✗ dropped: glTF attributes are per vertex |
| Scatter density per vertex | FLOAT point attribute named `_STJ_DENSITY` | ✓ | ✓ only because the name starts with `_` |
| Reference line | Poly curve | ✓ | ✗ empty node only (exporter writes `reference.centerline`) |
| Timing lines, grid, pit boxes, spawns | Empties with `stj` property | ✓ | ✓ as nodes |
| Sun | Sun light | ✓ | ✓ `KHR_lights_punctual` |
| Sky | World Sky Texture (5.2 types: single scattering, multiple scattering, Preetham, Hosek-Wilkie) | ✓ | ✗ glTF has no sky (exporter writes `environment.sky`) |
| Placed instances (trees, signs) | Linked duplicates parented to one empty | ✓ | ✓ `EXT_mesh_gpu_instancing` |
| Prototype library | Collection, objects marked as assets | ✓ | ✓ as nodes |
| Scatter layers | Geometry-nodes modifier | ✓ (evaluates fine: 200 instances in the test) | ✗ dropped by default (modifiers not applied) |
| Masks, HDRI | Packed images | ✓ **only if the image has a user or a fake user**; otherwise silently dropped on save | – |
| Animated objects (v0.2) | Object action (keyframes) | ✓, with the action name | ✓ as a glTF animation **named after the action** |
| Audio emitters (v0.2) | Speaker object: volume, reference and max distance, attenuation, cone angles, outer cone volume, packed sound | ✓ all of them, sound packed | ✗ only an empty node with its extras (the exporter writes `audio`) |
| Prop physics (v0.2) | Rigid Body: mass, friction, restitution, collision shape (box, sphere, capsule, cylinder, cone, convex hull, mesh, compound) | ✓ | ✗ no physics extension written (the exporter writes `physics`) |
| Terrain heightmap (v0.2) | 16-bit PNG, packed | ✓ (loads as float, 128 bits/pixel) | – ; Blender **saves 16-bit PNGs as RGBA** and its pixel buffer runs **bottom row first** |

## 2. Consequences for the design

- **The authoring package can be a single `.blend`.** Every STJ field has a home in it, and OpenDRIVE fits as text. The files that may remain next to it are:
  - **binary OpenCRG** (ASCII CRG would fit in a text block; not tested)
  - **linked asset libraries**, if the author chooses linking over appending
- **Surfaces bind through materials first.** Face attributes are the natural Blender tool, but glTF drops them, and materials survive as-is, which is why STJ binds by material (spec §6.3). USD keeps per-face data (§4), so the per-face blends of surface maps and ground (`stj_surf_layers`, spec §7.7) work without splitting primitives.
- **Scatter must be exported as a rule.** The geometry-nodes result is lost on export unless modifiers are applied, and applied it becomes baked geometry. The exporter therefore reads the node group's inputs (density, prototypes, area) into `scenery.scatter[]`, which is exactly what lets each engine regrow it natively (spec §8).
- **Two sources of truth must not drift.** Rule for the exporter: the text block is the base document, and data on Blender objects and materials is applied over it as an RFC 7396 merge patch. Objects win.
- **Axes need no conversion.** Blender's Z-up scene coordinates are STJ coordinates, and a USD stage declares `upAxis = Z` and `metersPerUnit = 1` (§4). For a glTF asset the exporter's "+Y up" does the mapping (spec §4.5), verified to 0.6 mm on a 2 km ribbon.

## 3. Conventions for an STJ Blender exporter

> Nearly every row of this section is now normative in [the STJ Blender profile](../spec/STJ_Blender_Profile.md) (reference, roads, junctions, edges, markings, cameras, timing, race data, surfaces, structures, prototypes with their Rigid Body, instances, emitters, terrain, buildings, areas, water, ground, sky, screens). Where the profile and this table differ, the profile wins. What is left here as advice: speaker objects as emitters, scatter as geometry nodes, layouts as linked scenes and the season properties.

Names are written `STJ__<category>__<id>` in the USD file, because USD forbids `::` in names and Blender's USD exporter writes `__` itself; `STJ::<category>::<id>` is the same name (spec §7.2). The table uses the `::` shorthand. Per-face data goes out as `stj_` primvars (§4).

| Blender | STJ |
|---|---|
| Collection `STJ_Collision` (objects inside: collision meshes) | `geometry.meshes[]` with role `collision` |
| Collection `STJ_Visual`, `STJ_LOD<n>` | roles `visual`, `lod` |
| Material named `STJ::surface::<id>`, or material property `stj_surface = "<id>"` | surface binding |
| Material property `stj` = surface object | `surfaces.library.<id>` |
| Curve `STJ::reference::centerline` (cyclic = closed) | `reference.centerline` |
| Empties `STJ::timing::start`, `::finish`, `::split_<n>`, `::start_finish` | timing lines (the exporter computes `s`) |
| Empties `STJ::grid::<n>`, `STJ::pit::<id>`, `STJ::spawn::<id>` | poses |
| Empty `STJ::scatter::<id>` with linked duplicates | `scenery.instances[].usd`. Blender's USD export writes linked duplicates as separate meshes (§4), so the exporter writes a PointInstancer with `pxr`. |
| Geometry-nodes modifier named `STJ_Scatter_<id>` | `scenery.scatter[]` |
| Object property `stj` on prototypes (class, species, height, `x_<engine>`) | `scenery.prototypes` |
| World Sky Texture, Sun light | `environment.sky`, `environment.lighting.sun` |
| Camera objects `STJ::camera::<set>::<id>` (custom property `stj` with `kind`, `active` or `spheres`; lens → `fov`) | `cameras.sets[]` |
| Curve objects `STJ::edge::<id>` (property `stj` with `kind`, `style`, `width`, `height`) | `edges[]` (the exporter projects the curve onto the reference line to get side, `s` range and `t`) |
| Scene property `stj_layout` on a linked scene per layout, or text `layout_<id>.stj.json` | `layouts[]` |
| Objects with an action and property `stj` (`kind`, `when`, `speed_by` / `time_by`) | `animated_objects[]`; `animation` = the action name, `target.nodes` = the object |
| Speaker objects `STJ::audio::<id>` (property `stj` with `kind`, `loop`, `when`, `gain_by`) | `audio.emitters[]`: `volume` → `gain`, `distance_reference` → `ref_distance`, `distance_max` → `max_distance`, `attenuation` → `rolloff`, cone angles and `cone_volume_outer` → `cone`; the packed sound is written next to the file |
| Rigid Body on prototype objects (the normative form is the proxy body `STJ::prototype::<id>::body`, `spec/STJ_Blender_Profile.md` §4) | `prototypes.<id>.physics`: mass, friction, restitution; shape `BOX`, `SPHERE`, `CAPSULE`, `CYLINDER` map directly, `CONVEX_HULL` → `mesh`; `CONE`, `MESH` and `COMPOUND` have no STJ shape (exporter warns) |
| Image `STJ::terrain::macro` (8-bit sRGB, packed; `kind`, `encoding`, `strength` and a non-default `extent` in the image's custom property `stj`) | `geometry.terrain.macro[]`. Same row-flip rule as the heightmap; the extent is the terrain's unless the property says otherwise |
| Image `STJ::terrain::height` (16-bit, packed) and a grid displaced by it | `geometry.terrain.heightmap`. Write the first channel, **flip rows** (Blender's buffer is bottom-up, STJ row 0 is north) |
| Scene property `stj_season`, `stj_substitutions` on a variant scene | `environment.season`, `surfaces.substitutions` in a season override |
| Material with a node group `STJ ground <material>` (ACR's `DR2 terrain` group, generalised), face attribute with the 3 layer indices, a UV map with the weights | `ground.materials[]`. The exporter writes the layer indices as three uniform int primvars `stj_surf_layers_0/1/2` and the weights as a faceVarying `float2` primvar `stj_surf_weights`, so no vertex is split. Blender's USD export drops per-corner FLOAT2 attributes (§4), so the weights are written with `pxr`. |
| Text `track.stj.json` | everything else; the exporter also writes it into the root layer's `customLayerData["stj"]` |
| Text `*.xodr` | `reference.opendrive` |

### Conventions for the v0.3 additions (checked in Blender 5.2)

`tools/blender/blend_probe_v03.py -- <out_dir>` checks four of them and writes `report_v03.json`. The first three rows are results; the last table is the rest of the design, **not probed yet**.

| Convention | Result | Rule for the exporter |
|---|---|---|
| **Road profile**: a Geometry Nodes modifier (`STJ_Road_<id>`) with Curve to Mesh, the profile as a second curve, and the curve's tilt as banking (spec §7.1) | ✓ works. The profile's **x lands on world +Y** (left, as `t`). The profile's **y lands on world −Z**. A **positive tilt raises the left side**, the same sign as STJ's `bank`. | **Draw the profile as `(t, −dz)`.** With that and the tilt set to `bank`, the evaluated cross-section equals `stj_core.profile_point` to 0.01 m (8 m wide, 0.1 rad). The curve's tilt is per point: write the `bank` table into the points' tilt at their `s`. |
| **Material inputs** (`materials[]`, spec §11.1) | ✗ not written as interface inputs. A node-group input is flattened away, and a material custom property comes out as `userProperties:<name>`. | The exporter reads the property and writes `inputs:<name>` on the UsdShade.Material with `pxr`, and connects the shader networks to it. |
| **Per-instance variation** (`usd.primvars[]`, spec §8.2): point attributes named `stj_*` | ✓ `FLOAT` → `float[]` `vertex`; `FLOAT_VECTOR` → `float3[]` `vertex`; `FLOAT_COLOR` → `color4f[]` `vertex` (four components). | Use `FLOAT` for `age`, `scale_jitter` and `phase`, and `FLOAT_VECTOR` or `FLOAT_COLOR` for `tint` (the fourth component of a colour attribute is ignored). On a PointInstancer the exporter copies them with `pxr`, because stock export writes a mesh. |
| **Names** (spec §7.2): `STJ::<category>::<id>` | ✓ becomes `STJ__<category>__<id>`. An object is an Xform prim named after it, with the mesh data as a child prim. **Collections are not exported** as prims, and their custom properties are not either. | The exporter reads the `.blend`, so a collection can still be its input. To make a prim path predictable (`structures[].mesh.prim`, `decal`), name the **objects** `STJ__structure__<id>[__part]` as well. |

The rest of the design follows the same pattern but has **not been run through a probe**:

| Blender | STJ |
|---|---|
| Curve `STJ::road::<id>` (property `stj` with `width`, `surface`) | `roads[]`; empties `STJ::junction::<id>` with the `s` on each road give `junctions[]` |
| Collection `STJ::structure::<id>` (property `stj` with `kind`, `clearance`), its objects named `STJ__structure__<id>…` | `structures[]` with `mesh {mesh_ref, prim}` |
| Objects named `STJ__decal__<id>` (property `stj` with `on`, `depth_offset`); a vertex attribute for the opacity | mesh role `decal` and `decal {on, opacity_primvar, depth_offset}` (spec §7.2) |
| Collection property `stj_source = "generated"` on a scatter result | `instances[].source: "generated"`; hand-placed objects stay `authored` |
| A text block `track.assets.json`, or an add-on list of external files | `assets[]` (hash and licence per file) |

## 4. OpenUSD (checked in Blender 5.2, OpenUSD 0.26.3)

Blender 5.2 bundles OpenUSD and its Python module `pxr`. `tools/blender/usd_probe.py -- <out_dir> <any.wav>` builds a test scene and runs three checks:
- **A**: export with Blender's USD exporter and inspect the result with `pxr`
- **B**: write what Blender does not export, with `pxr`
- re-import both files into Blender

It writes `report_usd.json`.

| STJ data | Blender → USD (A) | USD can hold it (B, written with `pxr`) | USD → Blender re-import |
|---|---|---|---|
| Axes, units | ✓ `upAxis = Z`, `metersPerUnit = 1` with default options; no conversion | ✓ | ✓ |
| Surface id per face (INT face attribute) | ✓ `uniform int[]` primvar (**glTF drops it**) | ✓ including `int3[]` per face | ✓ back as a FACE INT attribute; ✗ the `int3` primvar is not read |
| Per-vertex attribute (`_STJ_DENSITY`) | ✓ `vertex` primvar | ✓ | ✓ |
| Per-corner FLOAT2 attribute | ✗ dropped (only the UV map is written) | ✓ (`faceVarying` primvars) | – |
| Materials per face | ✓ one GeomSubset per material | ✓ | ✓ |
| Principled BSDF | ✓ UsdPreviewSurface **and** a MaterialX network (OpenPBR) | ✓ | ✓ the preview surface only (checked in 5.2 with `tools/ground_materialx.py` output: 4 nodes, an image and a Principled BSDF; the MaterialX network is ignored). The importer in `tools/blender/stj_ground.py` rebuilds the layered ground as Blender nodes instead |
| Procedural texture nodes (noise, colour ramp) | ✗ not translated into MaterialX | ✓ MaterialX can express them | – |
| Simple custom properties (string, number) | ✓ `userProperties:*` on objects and materials | ✓ any typed attribute (`stj:*`) | ✓ back as custom properties |
| **Nested custom properties** (the `stj` dictionaries) | ✗ **dropped** | ✓ as typed attributes or JSON strings | – |
| Scene properties, text blocks (the STJ document) | ✗ | ✓ layer `customLayerData` (the STJ JSON round-trips byte for byte) | – |
| Curves: poly and Bézier (reference line, racing line) | ✓ BasisCurves | ✓ | ✓ as Curves objects |
| Empties (timing gates) | ✓ Xform | ✓ | ✓ |
| Object animation | ✓ as `timeSamples` per frame; the action name is not kept | ✓ | ✗ not re-imported as an action |
| Camera, sun, spot | ✓ Camera, DistantLight, SphereLight + ShapingAPI | ✓ | ✓ |
| World with Sky Texture | ✗ only a DomeLight with a flat colour EXR; the sky model is lost | ✓ a DomeLight with an HDRI; the STJ sky block as data | ✗ |
| Rigid body | ✗ | ✓ **UsdPhysics**: RigidBodyAPI, MassAPI, CollisionAPI, physics MaterialAPI (friction, restitution) | ✗ |
| Speaker | ✗ | ✓ **UsdMedia SpatialAudio** (file, spatial mode, loop) | ✗ (an empty) |
| Linked duplicates | ✗ written as separate meshes, even with "instancing" on | ✓ native instances / PointInstancer | – |
| Geometry-nodes scatter | ✗ the host object is not exported at all | ✓ PointInstancer, or the STJ rule as data | – |
| Variants (dry / wet) | – | ✓ **VariantSets**: switching the variant changes the value | Only the selected variant is imported |
| Chunks for streaming | – | ✓ **payloads** | ✓ loaded |

### What this means for STJ

- **USD can hold everything STJ needs.** Typed per-face data, curves, physics, audio, variants, payloads, and the STJ document itself in the layer metadata all survived. As a rich container it is clearly ahead of glTF.
- **Blender's USD exporter is better than its glTF exporter**, but not complete. Per-face attributes, curves, MaterialX and Z-up survive. Nested properties, corner attributes, procedural textures, the sky, physics, speakers, instancing and scatter do not.
- **The missing parts are easy to write.** The probe wrote all of them with `pxr` from inside Blender in a few lines. A Blender → STJ-USD exporter is the stock USD export plus a `pxr` pass, not a new file writer.
- **The round trip back into Blender is partial.** Per-face attributes, curves and simple properties come back. Physics, audio, animation as actions and the sky do not. For a lossless round trip the `.blend` stays the authoring source (`authoring_source`).
- **Conventions adopted** (spec §7.7, §7.8):
  - **Primvars** use an `stj_` prefix, because Blender drops per-corner attributes with `:` in their names. Per-face layer indices are three uniform int primvars (`stj_surf_layers_0/1/2`), because Blender has no int3 attribute. Blender writes and reads both forms (checked with the `test_ring_blend` ring).
  - **Names.** The probes used `_STJ_DENSITY` for the scatter density attribute. The STJ name is `stj_density` (the schema requires the `stj_` prefix for primvar names), and `stj_core.usd_attr_name` maps the old spelling.
  - **Prim data** goes in `stj:*` typed attributes or a JSON string, never in nested Blender dictionaries.
  - **The STJ document** goes in the root layer's `customLayerData["stj"]`.
