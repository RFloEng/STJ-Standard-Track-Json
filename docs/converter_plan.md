# Converter plan

Order: **Blender export → Assetto Corsa import → RBR / BTB import**, plus one quick win that reuses work that already exists. Every converter works on files the user owns, writes `_metadata.provenance.converted_from[]` including a `lost` list, and marks output from commercial content `licence.redistributable: false`. No converter decrypts, unpacks protected archives or bypasses protection. When it meets such a file it stops and says so.

Facts marked *(m)* come from memory or community documentation and must be checked against real files before the converter relies on them.

---

## 0. Quick win: ACR Stage Tools IR → STJ

The existing ACR Stage Tools (DiRT Rally 2.0 → Blender → BeamNG) already produce an intermediate representation shaped like STJ:

| ACR Stage Tools output | Becomes |
|---|---|
| `collision.glb` with one primitive per surface material | `geometry.meshes[]` with role `collision` |
| Materials carrying `acr_surface` / `beamng_ground` | `surfaces.bindings[]` |
| Route curve through the DR2 gates | `reference.centerline` |
| `ACR_Start`, `ACR_Split.*`, `ACR_Finish`, `ACR_Stop` | `timing.start`, `split_points`, `finish`, `stop` |
| Pacenote labels | `race.pacenotes` |
| DR2 terrain from dr2-extract 0.4: `COLOR_0` (slice·8+3), `TEXCOORD_3` weights, `materials.json` constants, `_sliceN.dds`, `TColourMap`, `TAmbientOcclusion` | `ground` (spec §8.7):<ul><li>indices = (byte − 3)/8 into `_STJ_LAYERS`, `TEXCOORD_3` into `_STJ_WEIGHTS`</li><li>`DifUV` 0 → `{texcoord: 1, scale: 8}`, 1 → `world_xy` (v flips: DR2 XZ is STJ x, −y)</li><li>`tile` = 1/`WorldUVScale`, `Thickness` → `height_contrast`</li><li>slices → layers with `height_in_alpha`</li><li>colour map → macro tint, lightmap → macro occlusion (UV 0)</li></ul> |
| `ACR_Objects` with `acr_collider` | `scenery.prototypes` and `instances` |

The work is a small adapter. It is also the first real test of the surface model: the DR2 surface codes go into `class` and `x_dr2`, and the numbers are `_est`.

**Lost:**
- DR2's grip values (not in the files; only codes)
- DR2's terrain shader formula: replaced by the STJ reference blend (spec §8.7), which is close but not equal
- dynamic ruts

Output is DR2 content: `redistributable: false`.

---

## 1. Blender → STJ (priority 1)

An add-on with **Export STJ** and **Import STJ**, following `docs/blender_mapping.md`.

**Export:**
1. Write the glTF files with Blender's own exporter: "+Y up", `export_extras`, `export_attributes`, `export_lights`, `export_gpu_instances`, one file per role collection.
2. Build the STJ document:
   - start from the `track.stj.json` text block as base
   - read the reference curve (resampled, cyclic → `closed`)
   - read the timing, grid and pit empties, and project them onto the curve to get `s`
   - read material `stj` properties into `surfaces.library` and `bindings`
   - read geometry-nodes scatter inputs into `scenery.scatter[]`
   - read linked-duplicate groups into `scenery.instances[]`
   - read the World Sky Texture into `environment.sky`
   - apply all of these over the base as a merge patch
3. Write OpenDRIVE text blocks out as `.xodr`.
4. Run `tools/validate.py` on the result and show the report in Blender.

**Import:** the reverse. glTF in, reference curve and empties rebuilt, the STJ document stored as a text block.

**Lost on export:**
- node-based materials beyond glTF PBR (procedural textures, custom shaders) unless baked
- geometry-nodes logic beyond what the scatter schema expresses (only density, prototypes and area survive)
- modifiers are applied to meshes
- Blender drivers and animations (until `animated_objects` exists)

**Effort:** medium. The patterns exist in ACR Stage Tools.

---

## 2. Assetto Corsa → STJ (priority 2)

**Inputs** (`content/tracks/<track>/[<layout>/]`):

| AC file | Content |
|---|---|
| `.kn5` | Models, binary; community readers exist *(m)* |
| `models_<layout>.ini` | Layouts *(m)* |
| `data/surfaces.ini` | `KEY`, `FRICTION`, `DAMPING`, `IS_VALID_TRACK`, `IS_PITLANE`, `SIN_HEIGHT`, `SIN_LENGTH`, `VIBRATION_*`, `WAV`, `FF_EFFECT` |
| `ai/fast_lane.ai`, `ai/pit_lane.ai` | Binary AI splines |
| Dummies in the kn5 | `AC_START_n`, `AC_PIT_n`, `AC_TIME_n_L/R`, `AC_AB_START_L/R`, `AC_AB_FINISH_L/R`, `AC_HOTLAP_START_0` *(m)* |
| `ui/ui_track.json` | Name, geotags, country, length, pitboxes |
| `data/cameras*.ini`, `data/lighting.ini`, `data/groove.ini`, `data/map.ini` | Cameras, sun, groove, minimap |
| `extension/ext_config.ini` | Custom Shaders Patch |

**Mapping:**

- **Collision meshes.** Physics meshes are named with a digit prefix plus a surface `KEY` (`1ROAD`, `1GRASS`). A mesh becomes a glTF collision primitive with a `bindings[]` entry → surface `<key>`.
- **Surfaces.**
  - `class` comes from the key name (heuristic, so `_est`).
  - `LMUX = LMUY = FRICTION / FRICTION_road`. This is relative to AC's own road. The assumption that AC's road ≈ STJ-REF is unverified (spec §14).
  - `DAMPING` → `deformable.effective.drag_coefficient`. AC's exact definition is not documented, so the value is `_est` and the original goes in `x_ac`.
  - `SIN_*` and `VIBRATION_*` → `x_ac`, plus an ISO 8608 guess marked `_est`.
  - `IS_VALID_TRACK` → `track_limits`; `IS_PITLANE` → `pit_lane`.
- **Reference line.** AC has none. Build it from `fast_lane.ai`, the AI line, which is not a centerline. If the AI file carries side distances *(m)*, recentre between the edges. Otherwise keep the AI line as `reference.centerline` and as `racing_lines[0]`, and say so in `_note`.
- **Timing and poses.** Project the `AC_TIME` gate pairs onto the reference line to get `s`, giving sectors and splits. `AC_START_n` → grid, `AC_PIT_n` → pit boxes, A-B dummies → `start` and `finish`.
- **Metadata.** `ui_track.json` geotags → `geo_reference` latitude and longitude, without a projection; the converter states that the placement is approximate.
- **Cameras.** `data/cameras*.ini` → `cameras.sets[]`, with AC's normalised track position becoming an `active` s range.
- **Layouts.** Each layout folder becomes a `layouts[]` entry.
- **Pit lane.** `ai/pit_lane.ai` → a `racing_lines` entry with purpose `pit`.
- **Groove.** `data/groove.ini` goes into `x_ac` verbatim, plus a `rubber` line state fitted to it (`_est`) on `fast_lane.ai` *(m: groove.ini's grip content to be checked)*.
- **CSP RainFX** (`extension/ext_config.ini`). Materials listed in `PUDDLES_MATERIALS`, `SOAKING_MATERIALS` and `ROUGH_MATERIALS` set the bound surfaces' `water.wet_look` (`puddles`, `soaks`, `rough`), and `WaterDrain` materials become `water.drains[]`. The reverse direction writes the same lists. Other RainFX and CSP settings stay in `x_ac`.
- **CSP animated objects and conditions** map to `animated_objects[]` and conditions where a condition is one of STJ's signals. The rest stays in `x_ac`.
- **Lighting.** `data/lighting.ini` and the remaining CSP config go into `x_ac` verbatim.

**Lost:**
- kn5 shaders (`ksPerPixel*` and others) → glTF PBR; lightmaps and AO stay only if baked
- encrypted kn5 files: not supported
- AI line speed and side data beyond positions
- AC audio
- CSP effects as behaviour (they are only carried in `x_ac`)
- nothing deformable exists in AC, so there is nothing to carry

**Reverse (STJ → AC).** The same mappings backwards. Scatter becomes CSP GrassFX when the target uses CSP, otherwise baked instances. This is the first test that `x_ac` round-trips untouched.

**Effort:** medium-high; the kn5 reader is most of it.

---

## 3. RBR / BTB → STJ (priority 3)

The best-documented paths come first:

1. **BTB project files** (Bob's Track Builder, the user's own projects). BTB stores its venue and track as editable project files *(m: format to be checked on a real project)*. These carry the road spline, cross-sections, terrain, objects and materials, which is cleaner than anything recovered from RBR's runtime files.
2. **RBR's community Blender track exporter** (richardburnsrally.github.io/blender-track-exporter). For **STJ → RBR** the shortest path is STJ → Blender (converter 1) → RBR with that exporter. The exporter guide documents driveline events (start, splits, finish, end of stage) and material handling. These map directly to STJ `timing`.
3. **RBR runtime stage files** (`track-<id>` geometry, `.dls` driveline and pacenotes, materials, time-of-day variants M/N/E/O). These are thinly documented *(m)*. Import only what a documented reader handles. Never anything packed or protected.
4. **Pacenotes** come from the RSF pacenote plugin's files, which its quick-start guide documents. The `.dls` layout is undocumented. Note types map to STJ `kind`, `direction` and `severity` on the 1–6 scale. The plugin's numeric note id goes in `x_rbr` for a lossless round trip. Reverse stages have their own pacenote set: that is a layout (`docs/feature_survey.md` item 1).

**Surfaces.** RBR material ids → `class` plus `x_rbr.material`. RBR's grip lives in the game's physics (`physics.lsp`, NGP), not in the stage. STJ numbers therefore come from a user-supplied mapping table and are `_est`. NGP ruts and deformation are not documented and stay in `x_rbr`, by name only.

**Variants and layouts.**
- **Time-of-day variants** (M/N/E/O, each with its own surface state and sometimes its own pacenotes) become override files, listed in the stage's `variants[]` with kind `time_of_day` or `weather`.
- **Surface states.** Damp and wet sets become `water_depth` levels in those overrides. New, normal and worn gravel become the `levels` of a `swept` line state (spec §6.8).
- **Reverse stages** become `layouts[]` entries with `direction: reverse` and their own pacenotes.
- **Driveline events.** Time controls and end of stage map to `timing.controls` and `timing.stop`.

**Lost:**
- NGP physics behaviour (not in the stage files)
- dynamic ruts
- RBR-specific shaders and lighting
- anything in an undocumented binary that no open reader handles

**Effort:** depends on the BTB format. Pacenotes and the driveline come first; geometry follows.

---

## 4. Later

- **STJ → BeamNG**: reuse the existing BeamNG level exporter of ACR Stage Tools.
  - collision as `Colmesh-1`, `groundType` from `class`
  - forest items and groundcover from `scenery`
  - v0.2: `geometry.terrain` becomes a TerrainBlock (resampled to a power-of-two size), with layers as terrain materials
  - water bodies become WaterPlane, WaterBlock and River objects
  - audio emitters become SFXEmitters
- **rFactor 2 rubber**: RRBIN presets go into `x_rf2` verbatim, plus a fitted `rubber` line state (`_est`).
- **OpenDRIVE → STJ**, which is mostly free: reference, lane materials, `<CRG>`, `<geoReference>`.
- **rFactor 2**: GDB, AIW and CAM are documented by Studio 397.
- **Speed Dreams**: an open XML format, the best test case for edges and barriers.
