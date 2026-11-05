# Changelog

## 0.3 (draft) — 2026-11-02

Survey Tier 3 (`proposals/stj_tier3_proposal.md`, accepted). Additive; no reserved keys remain.

- **Race control** (`marshals`, spec §10.1):
  - marshal sectors, which `sector_flag` now refers to
  - posts and radio points, vehicles
  - restricted zones (penalty, reset, speed limit, no entry)
  - reset rules
- **Evolution** (`dynamic`, §6.10): reference laws for rubbering and sweeping, rain wash, water film with evaporation, ruts, wear and track temperature. Reference implementations are in `stj_core`.
- **Large worlds** (§7.6): `geometry.chunks` with local origins (overlap allowed for streaming), `geometry.tiles`, `geometry.terrains[]`, and `mesh.chunk`.
- **Presentation** (§8.8, §11): reflection probes, screens, crowd areas with behaviour, climate statistics.
- **Validator**: checks for all of the above; version check for keys newer than the declared version.
- **Examples**: the ring and the stage gain race control, evolution parameters, a probe, a screen, crowds and climate.
- **OpenUSD** (`proposals/stj_usd_proposal.md`, spec §7.7, §7.8):
  - USD meshes next to glTF: `STJ__` names, bindings by prim, per-face layer primvars and per-corner weights with no vertex splitting, UV primvars by name, `time_range` animations
  - the STJ document inside a USD layer; USD override layers; `usd_variants`; chunk payloads
  - `.usdz` single-file tracks and `_metadata.authoring_source`
  - `tools/stj_usd.py` (embed, extract, package)
  - optional `pxr` checks in the validator, including OpenUSD's package rules
  - the `test_ring_blend` ring as `.usda` and `.usdz`, plus a wet layer
- **Terrain macro maps** (`proposals/stj_terrain_macro_proposal.md`, accepted 2026-11-05; additive):
  - `geometry.terrain.macro[]`: tint, occlusion or colour maps over a heightfield, with an optional extent (§7.4)
  - the `colour` macro encoding (an sRGB map of the ground's average colour) and `strength`, also on `ground.materials[].macro` (§8.7)
  - validator checks and the version check; `stj_core.apply_macro` and `tools/ground_bake.py` handle `colour`
  - the gravel stage's terrain gains a colour map

- **Ground materials** (§8.7, from the visual-materials proposal; additive):
  - `albedo.alpha` says what the alpha channel holds (`height`, `specular`, `roughness`, `gloss`, `none`); `height_in_alpha` stays valid and means `alpha: "height"`
  - per-layer `roughness` and `occlusion` maps
  - `blend.method: "mask"` with `blend.mask` and `softness`: a tiling blend mask for each layer after the first, provisional until fitted to an engine
  - `macro` kind `wetness`: where the ground shows water, scaled by the `wetness` signal
  - validator checks; `stj_core.ground_blend` (mask) and `wet_amount`; `tools/ground_bake.py` bakes the mask blend and skips wetness maps
- **RBR conversion gaps** (`proposals/stj_rbr_gaps_proposal.md`; additive):
  - `reference.centerline.tangents_out` and `tangents_in`: one tangent per segment (§7.1)
  - `lighting.ambient`, `sun.direction` (a fixed sun) and `sun.color` (§8.3); `weather_schedule[].variant`
  - animated objects without keyframes (`kind` `clock`, engine script in `x_<engine>`, §8.5); emitters with an engine sound event instead of a file (§8.6)
  - `prototypes[].wind` (§8.2); `water.bodies[].physical: false` (§7.5); `meshes[].reflective` and `baked` (§7.2)
  - validator checks for all of them; `stj_core.ReferenceLine` takes per-segment tangents
  - open: asset manifest with licences, and LOD ranges for prototypes
- **Materials, decals, assets and prototype LODs** (`proposals/stj_visual_materials_proposal.md`, `proposals/stj_rbr_gaps_proposal.md`; additive):
  - material profile for visual and decal meshes: a UsdPreviewSurface fallback and two-sided cards are errors, maps and colour spaces are warnings, a NOTE lists the maps each material carries (§7.7)
  - mesh role `decal` with `decal {on, opacity_primvar, depth_offset}` (§7.2)
  - top-level `materials[]`: material inputs that follow signals (§11.1)
  - `assets[]`: file, hash and licence, cross-checked against the USD asset paths (§5.3)
  - `prototypes[].lods[]` and `cull_distance` on prototypes and instance sets (§8.2)
  - `stj_core.usd_material_report` and friends
- **Road cross-section and authoring model** (`proposals/stj_road_cross_section_proposal.md`; additive):
  - `centerline.cross_section {templates, sections, bank}`: lateral profiles with strip surfaces, blended sections and banking (§7.1)
  - `centerline.terrain {mode, shoulder_blend, falloff, sections}`: drape, carve or free (§7.1)
  - `roads[]` and `junctions[]`: other roads and where they meet; `side_roads[].junction`
  - `instances[].source` (authored or generated) and `scatter[].exclude_zones` (§8.2)
  - `meshes[].generated`: a mesh as a cache of a rule, with `stj_core.rule_hash` (§7.2)
  - reversed layouts map the profile, bank, sections and junctions
  - validator checks; `stj_core` profile, terrain-rule and hash functions; `tools/ribbon_usd.py` follows the profile
  - the gravel stage gains a crowned profile, a flat deck, a banked corner and a service road
- **Scan sources** (`proposals/stj_lidar_proposal.md`; additive):
  - `provenance.scan.sources[]`: the survey a track came from (format, CRS, datum, density, accuracy, licence)
  - `derived {source, product, classes, cell_size, method, void_fill}` on the heightmap, OpenCRG, meshes, instances and scatter (§5.2)
  - `heightmap.nodata` and no-data cells in `stj_core.Terrain` (§7.4)
  - validator checks, including a NOTE for a cell finer than the point density supports
  - `tools/las_dtm.py`: LAS (and, with `laspy`, LAZ and COPC) to a heightmap

## 0.2 (draft) — 2026-11-02

Survey Tier 2 (`proposals/stj_tier2_proposal.md`, accepted). v0.1 files stay valid. The exception is the reserved `animated_objects` key, which is now an array.

- **Signals** (spec §11.1): runtime state with fixed units and defaults, declarative conditions (`when`) and bindings (`*_by`). Used by lights, animated objects, scenery, audio and puddles.
- **Terrain** (§7.4): `geometry.terrain` heightfield.
  - `png16` or `raw_f32`; vertex-registered, with image row 0 at the north edge
  - holes
  - layers bound to surfaces; a contact uses the dominant layer
- **Water** (§6.9, §7.5):
  - water bodies with flow and wading drag
  - per-surface `water` (storage, drain rate, wet look)
  - accumulation map and bands, drains, shelter, a drying-line snapshot
  - the effective film-depth formula used by the grip recipe
- **Line states** (§6.8): rubber and swept gravel along a racing line, with per-session levels.
- **Seasons** (§11): `environment.season`, `surfaces.substitutions`, `snow_bank` edges.
- **Props** (§8.4): `prototype.physics`. Edges can be built from a prototype.
- **Animated objects** (§8.5): glTF animations driven by time or signals.
- **Audio** (§8.6): point and line emitters, reverb zones.
- **UI** (§5.1): short name, abbreviation, tags, media, minimap, records.
- **Tools**:
  - validator checks for all of the above
  - stdlib PNG reader and writer, terrain sampling, reference film-depth and line-state functions
  - `blender/blend_probe_v02.py`
- **Examples**:
  - the GP ring and the gravel stage use the new features
  - new drying and winter variants
  - generated terrain, props glTF, audio placeholders and a minimap
- **Layered ground** (§8.7, `proposals/stj_layered_ground_proposal.md`):
  - `ground.layers` and `ground.materials`
  - four weight encodings: `vertex_top3`, `vertex_dense`, `image`, `id_map`
  - a normative height blend and macro maps
  - `terrain.layers[].ground_layer`
  - validator checks that read the glTF attribute data
  - `tools/ground_bake.py`
  - a DR2-style example section on the gravel stage
- **Lessons from RBR stages** (`proposals/stj_lessons_from_rbr_proposal.md`, from reading the open ReRBR reimplementation):
  - surface maps that vary inside collision primitives and blend
  - surface states chosen by the new `wear` signal and `wetness`
  - absolute μ per tyre class with `reference_mu`
  - centerline `chainage` and Hermite `tangents`
  - sinusoidal roughness, `base_offset`, surface `impact` and `effects`
  - invisible drag edges, tearable fences, conditional water, bendable props, `_SWAY`
  - the `time_to_arrival` signal, `race.sections`, `weather_options`, `audio.reflections`
  - pace-note `call_adjust`; `distance_to_next` checked as derived
- **Schema**: `_` annotations are now allowed on every object.
- **Docs**: `docs/best_practices.md`, a creators' guide with sourced polygon, texture, terrain and world-size limits for AC, rF2, BeamNG, RBR, Unity, UE and RoR, plus a portable baseline.


## 0.1 (draft) — 2026-11-02

First draft.

- **Schema** (`schema/stj.schema.json`, Draft-07): `_metadata` (licence, provenance), `track_info`, `reference`, `geometry`, `surfaces`, `timing`, `race`, `environment`, `scenery`. Reserved: `dynamic`, `animated_objects`, `marshals`.
- **Survey Tier 1** (`docs/feature_survey.md`):
  - `layouts[]`, including reverse direction
  - `variants[]` index of override files
  - `edges[]`: kerbs, verges, barriers
  - `cameras`: sets, activation by range or spheres
  - `race.ai`: corridor and hints, plus new `racing_lines` purposes
  - `race.start_procedure` and `race.service_areas`
  - `timing.drs_zones`, `timing.controls`, `timing.side_roads`
  - `pit_lane.session_speed_limits` and `environment.weather_schedule`
- **Override schema** (`schema/stj-override.schema.json`): RFC 7396 merge patch.
- **Spec** (`spec/STJ_Spec.md`): coordinate frames, the surface model and grip recipe, engine-native data, validation rules, portability limits.
- **Tools**: `validate.py` (schema + cross-references), `ribbon_gltf.py` (centerline + bands → collision glTF), `stj_core.py`, `blender/blend_probe.py`.
- **Examples**:
  - a minimal circuit
  - a race-ready GP version with a reverse layout and a night variant
  - a gravel stage with a reverse layout and a wet variant
  - a generated collision mesh
- **Docs**: Blender storage mapping (verified in Blender 5.2), converter plan, survey of track-creation tools, open questions.
