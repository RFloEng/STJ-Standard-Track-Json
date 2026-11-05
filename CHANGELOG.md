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
- **Terrain macro maps** (`proposals/stj_terrain_macro_proposal.md`, proposed, pending acceptance; additive):
  - `geometry.terrain.macro[]`: tint, occlusion or colour maps over a heightfield, with an optional extent (§7.4)
  - the `colour` macro encoding (an sRGB map of the ground's average colour) and `strength`, also on `ground.materials[].macro` (§8.7)
  - validator checks and the version check; `stj_core.apply_macro` and `tools/ground_bake.py` handle `colour`
  - the gravel stage's terrain gains a colour map

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
