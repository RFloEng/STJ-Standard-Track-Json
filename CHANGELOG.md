# Changelog

## 0.3 (draft) — 2026-11-02

- **Blender profile: surface library, track info, layouts, variants, emitter lines**: a surface material carries its library entry in `stj` (edit friction and the rest in Blender); `STJ::track_info::track_info`, `STJ::layout::<id>`, `STJ::variant::<id>` as records; line-source emitters as open curves.

- **Blender profile: prototype physics as a Rigid Body**: `STJ::prototype::<id>::body`, a proxy mesh with a Rigid Body (type, mass, friction, restitution, collision shape, size) for each prototype with `physics`. Only what changed since import reaches the document; verified in Blender 5.2 by changing a mass and a scale. Animation stays with the mesh files' time samples.

- **Blender profile: pit lane**: `STJ::pit_lane::pit_lane` carries `timing.pit_lane` with its path as a curve.

- **Blender profile: racing lines and water paths**: `STJ::line::<id>` (race, qualifying, pit and AI side lines as curves; the checker warns when `speed` or `width` no longer match the points) and open curves for water bodies with a `path`.

- **Blender profile: dynamic**: `STJ::dynamic::dynamic` carries the `dynamic` block.

- **Blender profile: chunks and tiles**: `STJ::chunk::<id>` (at its `origin`) and `STJ::tiles::tiles`.

- **Blender profile: ground, sky and screens**: `STJ::ground_layer::<id>`, `STJ::ground_material::<mesh>_<n>`, `STJ::sky::sky` and `STJ::screen::<id>` carry `ground.layers`, `ground.materials`, `environment.sky` and `screens` as records; the Test Ring GP and Coll de Prova documents still round trip exactly.

- **Portals and retaining walls**: `structures[].portals {start, end}` (style, height, mesh) for the mouths of tunnels, underpasses and galleries; edge styles `retaining_wall` and `parapet`. No new Blender row: structures and edges already carry them.

- **Road class, limits and markings** (spec §7.10): `road_class`, `speed_limit`, `lanes` and `oneway` on roads; top-level `markings[]` (centre, lane and edge lines, stop lines, crossings, arrows, chevrons, hatching, text) located by road, `s` and `t`. The validator checks the road, `s`, geometry per kind and surfaces. Blender profile row `STJ::marking::<id>`: an open curve for a line, a closed four-corner curve for a patch; moving it writes new `s` and `t`.

- **Blender profile: ring curves for water and service areas**: a water body with an `outline` and every service area is a closed curve; pulling a corner changes the outline or polygon.

- **Blender profile: more records** (`water`, `scatter`, `sector`, `post`, `marshal_vehicle`, `restricted`, `audio_zone`, `probe`, `service`): list entries carried as empties with the entry in `stj`; probes and marshal posts follow their empty. The patch merges `race` and `environment` instead of replacing them.

- **Blender profile: terrain** (`STJ::terrain::<id>`): a heightmap becomes a grid mesh on import and is sculpted in Blender; an untouched terrain exports as it was, an edited one writes its heightmap again (png16 or raw_f32) with new height range. `stj_core.png_bytes`.

- **Handoff additions** (`proposals/stj_handoff_proposal.md`; from a third-party v0.4 restructure proposal, taking only what is additive and keeping the current names):
  - conformance profiles `_metadata.conformance` (`core`, `race`, `rally`, `physics`), checked by the validator (§3.7);
  - surface `function` (driving, shoulder, run_off, barrier, pit, infield, spectator, decor) and a `quality {basis, confidence, method}` block next to `_est` (§6.11);
  - `race.route_policy`, `race.pacenote_sets[]` and `racing_lines[].vehicle_class` (§10);
  - override `ops` (add, replace, update, remove an array element by key) and a table of which arrays have an identity (§3.3);
  - `position_ref` (`world`, `road:<id>`, `route:<id>`) on cameras and audio emitters, resolved by `stj_core.resolve_position` (§3.8);
  - `tools/canonicalize.py` and `tools/migrate.py`, and a deprecation rule: one minor version of warning before removal (§3.9, §3.10).
  - Not taken: the wholesale rename and restructure of v0.4, an `extensions` object in place of `x_` keys, and absolute `peak_mu` / `sliding_mu`.

- **Names, tags, buildings and areas** (spec §7.9; `proposals/stj_places_proposal.md`): `name`, `ref`, `tags {string: string}` and `source {id, osm_id, key}` on roads, structures, junctions and edges, so real-world data keeps its identity; top-level `buildings[]` (footprint, holes, height, levels, roof, class, mesh) and `areas[]` (polygon, holes, class). The validator checks sources, rings, heights and mesh references. The Blender profile has rows for both (`STJ::building::<id>`, `STJ::area::<id>`).

- **STJ Blender profile 0.1** (`spec/STJ_Blender_Profile.md`; `proposals/stj_blender_profile_proposal.md`): a normative description of how a `.blend` holds a track, with its own version (scene property `stj_blender_profile`), for Blender LTS releases (run on 5.2 LTS). Normative rows: reference curve, timing gates and splits, grid, pit boxes and garage, spawns, surface materials, the base text block `track.stj.json` with objects applied over it. `tools/blender/stj_profile.py` (rules, no Blender needed), `tools/blender/stj_blender.py` (`lint` and `export` inside Blender: document plus USD with the document embedded), `examples/make_blender_reference.py` (the conformance `.blend`), `tests/test_blender_profile.py`. `stj_blender.py import` builds the profile scene from a document or a USD (`scene_from_document`); import then export gives the document back. The place and the sun are rows too: `STJ::geo::origin` (coordinates, height, date, time, time zone, true north) and `STJ::sun::<id>` (a Sun light that follows the clock until moved). `stj_core.sun_direction` and `sun_enu` compute the sun from place and time. Round trips are exact: poses and gates keep their form until moved, and the three example documents come back unchanged. More rows: `STJ::mesh::<id>` collections (the meshes go through Blender's USD import and export), `STJ::road::<id>`, `STJ::junction::<id>`, `STJ::edge::<id>`, `STJ::camera::<set>::<id>`. The export now writes the track stage (document only) and one USD per mesh collection. `stj_blender.py dump` writes the scene description. Also structures, animated objects, prototypes (with their physics as data), instance sets (a vertex per instance), audio emitters and crowds; the Test Ring GP and Coll de Prova documents round trip exactly through Blender. Scatter rules, ground layers, terrain, water, screens and marshals stay in the text block.

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
- **Sources and licences** (spec §5.2; `proposals/stj_junctions_proposal.md`, gap list sections B5, C5, E1, E2): `provenance.sources[]` for data that is not a scan (OSM, cadastre, imagery, global DEMs, land cover), licence fields `attribution`, `share_alike` and `commercial_use`, `derived.sources[]` and `derived.void_source` (several sources, and where the gaps were filled from), and `derived` on a road's `centerline` and `cross_section` (measured heights, camber). `stj_core.licence_summary`, `data_sources`, `needs_attribution`, `derived_sources`. The validator warns when a redistributable file has a source that is not, and when a licence that asks for a credit line has none.
- **Junctions, continuations and routes** (spec §7.1, §3.5; `proposals/stj_junctions_proposal.md`): from the TrackCreator gap list. `junctions[]` gain `kind` (`at_grade`, `grade_separated`, `merge`, `split`, `roundabout`), `through`, per-road `end`, `rank`, `join {mode: centre|edge_snap, reach}` and `corner_radius`, `height {mode: pinned|blend, radius}` and an authored `mesh`; new `continues[]` for a road cut in two and `routes[]` (steps along roads with one continuous `s`), and `layouts[].route` makes a route the layout's reference line. The validator checks the joint position (5 m), height step (1 m), `end` against `s`, the through road and ranks, and that route steps meet. `stj_core`: `joint_point`, `roads_linked`, `route_pieces`, `route_length`, `route_locate`, `route_s`, `route_centerline`. Closes the loop-of-several-roads case of Q6.
- **Layouts: ground data stays on the base line** (spec §3.5): surface bands, CRG placements, structures, junctions and the road profile and terrain rule of the reference keep their base-line `s` and `t` in every layout document, and `layout_document(..., ground="layout")` or `stj_core.reverse_ground` maps the profile, structures and junctions when a tool needs layout coordinates (the validator does). `reverse_reference` now reverses the line only. Rule 3 no longer says edges stay on the base line: a layout lists its own.
- **Closed lines** (fix; spec §7.1): the sections of the road profile and of the terrain rule, and structures, can cross `s = 0` on a lapped line with `s_end < s_start`, as surface bands and edges already could (they were rejected before); an OpenDRIVE-only reference is a loop when `track_info.type` is lapped and `reference.length` is given (`stj_core.reference_lap`); the profile's `bank` table wraps across `s = 0`; overlaps are found across `s = 0`. `stj_core` gains `s_in_range`, `s_since`, `s_segments` and `s_overlap`, and the profile functions take the lap length.
- **Keeping the ground blend** (`proposals/stj_visual_materials_proposal.md`; additive): `ground.materials[].fallback {uri, texcoord, tool, inputs_sha256}` marks a baked image as a cache of the recipe, with a stale check (`stj_core.rule_hash(doc, "ground.materials[<i>]")`, printed by `ground_bake.py`); `tools/ground_materialx.py` writes the recipe as a MaterialX network (height, linear and mask blends, macro maps), checked against the reference blend by `tests/mtlx_eval.py`; the gravel stage's ground material shows its stamped fallback (§8.7).
- **Blender probe for the v0.3 conventions** (`tools/blender/blend_probe_v03.py`, `docs/blender_mapping.md` §3): the road profile modifier agrees with `stj_core.profile_point` when the profile is drawn as `(t, −dz)`; material inputs and PointInstancers must be written with `pxr`; a `tint` primvar may have four components (the last is ignored).
- **Tools**: `stj_usd.py embed` creates the stage when the file does not exist, so a plain document becomes a track in one step.
- **Instance variation** (`proposals/stj_visual_materials_proposal.md` §3.5; additive): `scenery.instances[].usd.primvars[] {name, role}` names the per-instance primvars of a PointInstancer (tint, age, scale_jitter, phase) (§8.2).
- **Structures** (`proposals/stj_structures_proposal.md`; additive):
  - `structures[]`: bridges, tunnels, underpasses and galleries by `s` range, with `clearance`, an optional mesh and `carried_by` (§7.1)
  - the kind implies rain shelter, a reverb zone and a free terrain rule as data (`stj_core.structure_defaults`); explicit entries win
  - `pacenotes.notes[].structure`; `stj_core.structure_at`
  - the gravel stage's flat deck is the bridge `viaduct_1`
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
  - the profile, bank, sections and junctions are ground data: in a reversed layout they keep their base-line coordinates (see the layout rule below)
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
