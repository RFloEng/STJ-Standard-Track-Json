# STJ proposal: Tier 2 features (v0.2)

Status: **accepted** 2026-11-02, with the recommended answers in §11:
- D1: all nine features
- D2: a first-class terrain heightfield
- D3: a closed signal list with declarative conditions and bindings
- D4: parametric line states covering rubber and swept gravel

Implemented in `schema/stj.schema.json` v0.2 and `spec/STJ_Spec.md`. Changes made during implementation:
- `surfaces.rubber` became `surfaces.line_states[]` with `kind: rubber | swept`.
- `animated_objects` became an array. This is the one change that is not additive, and it touches only a key that v0.1 reserved.

Source: `docs/feature_survey.md` Tier 2, items 7–14. Shapes follow STJ conventions: SI units, angles in rad, `s` in metres along the reference line, `x_<engine>` and `_est` everywhere, strict objects.

All of it is additive, so it would ship as **v0.2** (`_metadata.version: "0.2"`), and every v0.1 file stays valid.

---

## 0. Overview

| # | Feature | Where it goes | Portable? | Depends on |
|---|---|---|---|---|
| 1 | State signals and conditions | `definitions` used by lights, animations, scenery, audio, water | The data, yes; running it needs a runtime in the target engine | – |
| 2 | Terrain heightfield | `geometry.terrain` | Shape yes; layer blending and resolution limits no | – |
| 3 | Water bodies, wetting and drying | top-level `water`, surface `water` block | Extent, depth and where water stands, yes; buoyancy, shading and how water evolves, no | 1 (puddles, film depth) |
| 4 | Animated objects | top-level `animated_objects` (now reserved) | glTF keyframes yes; triggers depend on the engine | 1 |
| 5 | Seasons and surface substitution | `environment.season`, `surfaces.substitutions` | Yes | 1 |
| 6 | Static rubber baseline | `surfaces.rubber` | Data yes; feel no | – |
| 7 | Physical props | `scenery.prototypes.<id>.physics` | Mostly | – |
| 8 | Audio | top-level `audio` | Positions and ranges yes; sound banks no | 1 |
| 9 | UI and minimap | `track_info` | Yes | – |

Signals come first because five other features use them. Without signals, each feature would invent its own "only at night" or "only when wet" switch. The v0.1 light `schedule: night` is already one such switch.

---

## 1. State signals and conditions

### 1.1 What a signal is

A signal is a named value **the engine supplies at runtime**. STJ fixes the name, unit and range; the engine maps its own state onto it. A signal the engine does not support takes its **default**, so a static converter (one with no runtime) bakes the default state and still gets a sensible track.

| Signal | Unit / type | Default when unsupported | Typical source |
|---|---|---|---|
| `sun_elevation` | rad, −π/2…π/2 | computed from `default_time` | every engine with time of day |
| `local_time` | s since local midnight | `default_time` | idem |
| `day_of_year` | 1…366 | `default_time.date` | rF2 GDB, BeamNG |
| `precipitation` | mm/h (**exception to SI**, see below) | 0 | OpenSCENARIO, CARLA, rF2 `.wet` |
| `water_depth` | m, film on the racing surface | `default_weather.water_depth` | rF2, AMS2, CSP RainFX |
| `wetness` | 0…1, how wet things look | 0 | CSP, CARLA |
| `wind_speed` | m/s | `default_weather.wind_speed` | rF2, CSP |
| `snow_cover` | 0…1 | `environment.season.snow_cover` or 0 | CSP year conditions, ACR |
| `leaf_fraction` | 0…1 (1 = full foliage) | `environment.season.leaf_fraction` or 1 | – (new) |
| `session` | `practice`, `qualifying`, `warmup`, `race`, `stage` | `race` | all race games |
| `session_phase` | `pre_session`, `formation`, `countdown`, `running`, `suspended`, `finished` | `running` | rF2, AC |
| `session_time` | s since session start | 0 | all |
| `flag` | `none`, `green`, `yellow`, `double_yellow`, `red`, `blue`, `white`, `chequered`, `safety_car`, `virtual_safety_car`, `code_60` | `none` | rF2, AC (CSP) |
| `start_lights_lit` | integer 0…`start_procedure.lights.count` | 0 | rF2 start lights |
| **local** `nearest_vehicle_distance` | m, from the consumer's position | +∞ | CSP conditions, BeamNG triggers |
| **local** `sector_flag` | as `flag`, for the marshal sector at the consumer's `s` | `none` | rF2, CSP |

Local signals are evaluated at the position of whatever uses them: a light, an emitter, an animated node.

`precipitation` uses mm/h because SI (m/s) gives numbers like 2.8·10⁻⁷ that nobody can read or check. It is the second documented exception after latitude and longitude in degrees.

Engine-specific signals use `x_<engine>_<name>` (for example `x_csp_headlights`). A converter that does not know one uses the consumer's default.

### 1.2 Bindings and conditions

Two small shapes, used everywhere:

```json
"when": { "all": [
  { "signal": "sun_elevation", "op": "lt", "value": 0.05 },
  { "signal": "session", "op": "in", "value": ["race", "qualifying"] }
] }
```

- **Condition**: `{signal, op, value}` with `op` one of `eq`, `ne`, `lt`, `le`, `gt`, `ge`, `in`; combined with `all`, `any`, `not`. No arithmetic and no scripting. This is the CSP "conditions" model reduced to what converters can translate.
- **Binding**: maps a signal to a number. `{signal, curve: [[in, out], …]}` (linear, clamped) for numbers, or `{signal, map: {value: out}}` for enums, plus `smoothing` (s, first-order lag), so floodlights do not flicker on and off at dusk.

**v0.1 compatibility.** Light `schedule` stays as a shorthand: `night` means `sun_elevation < 0`, `always` means no condition, and `event` means the engine decides. A light with both `schedule` and `when` uses `when`.

### 1.3 Who consumes signals

| Consumer | Field | Example |
|---|---|---|
| Lights | `when`, `intensity_by` | floodlights below 3° sun elevation; start lights by `start_lights_lit` |
| Animated objects | `when`, `speed_by`, `time_by` | windmill speed ∝ `wind_speed`; a barrier arm driven by `nearest_vehicle_distance` |
| Scenery instances and scatter | `when`, `density_by` | leafless trees in winter; snow banks when `snow_cover > 0.5` |
| Audio emitters | `when`, `gain_by` | crowd louder during `running`; PA silent at night |
| Water (puddles) | `fill` binding on `wetness` | puddles that grow with rain |

---

## 2. Terrain heightfield (`geometry.terrain`)

### 2.1 Shape

```json
"terrain": {
  "heightmap": {
    "uri": "terrain/height.png", "format": "png16",
    "size": [2049, 2049], "extent": [-1024, -1024, 1024, 1024],
    "height_min": -12.0, "height_max": 188.0
  },
  "holes": { "uri": "terrain/holes.png" },
  "layers": [
    { "id": "grass", "surface": "verge_grass", "material": { "mesh_ref": "terrain_mat", "material": "Grass" }, "tile": 4.0 },
    { "id": "dirt",  "surface": "dirt_dry", "weight": { "uri": "terrain/splat0.png", "channel": "r" }, "tile": 3.0,
      "x_beamng": { "material": "dirt_loose" } }
  ],
  "collision": true
}
```

### 2.2 Grid rules (these are where converters go wrong)

- **Vertex-registered.** Sample (i, j) sits exactly at `x = x_min + i·dx`, `y = y_max − j·dy`, where `dx = (x_max − x_min)/(nx − 1)`. Image column `i` runs east (+X), and **image row 0 is the +Y (north) edge**, so the PNG reads like a map. UE, Unity, BeamNG and RoR all use vertex grids; the row direction is the classic source of mirrored terrains.
- **Axis-aligned** in the STJ world frame. A rotated terrain is rotated by the converter, not described by STJ.
- **Height** = `height_min + v/65535 · (height_max − height_min)` for `png16`. A 200 m range gives 3 mm steps. Large ranges should use `raw_f32` (little-endian float32, metres, row order as above). These are the only two formats: both can be read without libraries. GeoTIFF and EXR are the converter's job.
- **Square cells** (dx = dy) are recommended and `2^n + 1` samples per side are what UE, Unity and RoR need. The validator says so (WARN for non-square, NOTE for other sizes), but STJ does not resample.
- **Holes**: 8-bit mask on the same grid, non-zero = no terrain (tunnels, cuttings, places where a road mesh replaces the terrain).

### 2.3 Layers and surfaces

- The **first layer is the base**. Its weight is `1 − Σ(other weights)`, so it needs no map. Other layers give a weight map (any resolution covering the same extent, sampled bilinearly).
- **Physics**: a terrain contact takes the surface of the **dominant layer** (largest weight) at that point. That is what BeamNG and UE physical materials do. Blended friction is not portable.
- **Visuals**: `material` names a glTF material (in a mesh used only as a material library) and `tile` gives its world repeat in metres. The blend itself is the engine's.
- The layer → surface link doubles as a portable friction map, as RoR's TractionMap. Scatter already attaches to surfaces (`area.surfaces`), so grass that grows on the "grass" layer needs nothing new.

### 2.4 Terrain and meshes together

The terrain is one more collision source. Under a wheel the **higher** of terrain and collision mesh is touched; that is geometry, not a rule. Authors therefore keep the terrain at least 5 cm under road meshes, or cut holes. The validator samples the terrain along the reference line and warns where it rises above the road surface (`centerline z + 2 cm`) without a hole.

**Converting to mesh-only engines** (AC, rF2, RBR): the grid is triangulated exactly and split into primitives by dominant layer. The per-triangle surface is coarser than the blend, which is the loss to record.

### 2.5 Out of scope

Tiles, streaming and terrain LOD (Q14). Sculpting history. Erosion. Terrain painted with more than the engine's layer limit is a converter problem: STJ allows any number.

---

## 3. Water (`water`)

```json
"water": {
  "sea_level": 0.0,
  "bodies": [
    { "id": "reservoir", "kind": "lake", "outline": [[x, y], …], "level": 412.3, "depth": 6.0, "out_of_bounds": true },
    { "id": "ford_ss1", "kind": "ford", "path": [[x, y, z, width, depth], …], "flow_speed": 0.8, "bed_surface": "gravel_loose",
      "wading_drag": 1.5 },
    { "id": "puddle_t3", "kind": "puddle", "outline": [[x, y], …], "level": 402.10,
      "fill": { "signal": "wetness", "curve": [[0.3, 0.0], [1.0, 1.0]] } }
  ],
  "accumulation": { "uri": "water/accum.png", "extent": [x_min, y_min, x_max, y_max] }
}
```

- `kind`: `sea`, `lake`, `pond`, `river`, `stream`, `ford`, `puddle`, `pool`, `other`.
- **Polygon bodies** (`outline` + `level`): lakes, ponds, puddles. **Path bodies** (`path` of `[x, y, z, width, depth]`): rivers, streams, fords; `z` is the water surface and flow runs along the path. `sea_level` is an infinite plane.
- `depth` (m) is optional where the bed is terrain or a mesh. `density` defaults to 1000 kg/m³.
- `out_of_bounds: true` resets a vehicle that enters, which is what engines without water physics should do with a lake.
- `fill` scales a puddle's depth (0…1 of its full depth) by a signal.
- `accumulation` is a greyscale map (0…2) that multiplies the global `water_depth` signal locally: drying lines, wheel ruts and dips where water stands. It is the portable part of AMS2 puddles and CSP RainFX.

**Grip in water.** The film model (`wet_response`) is for films up to about a centimetre. Inside a body the bed surface (`bed_surface`, or the surface underneath) applies with `wet_response` at its deepest tabulated value. Engines with water physics add buoyancy and drag on the vehicle. Engines without use `wading_drag` (s/m, same form as the deformable `drag_coefficient`: `F = c · v · Fz`), which is crude and marked as such.

**Visual water** is an optional glTF node (`mesh {mesh_ref, node}`); waves, foam and refraction stay in `x_<engine>`.

### 3.1 Wetting and drying: what the track stores

How games handle wet tracks *(sources at the end of this section; mostly developer statements and forum reports, so treat them as (m))*:

| Game | What it stores or simulates |
|---|---|
| rFactor 2 / LMU | RealRoad tracks water on the road with its own update rate. There is a start-of-session water amount, and the racing line dries dynamically. |
| AMS2 (LiveTrack 3.0) | Puddles and dry lines. Water saturation washes rubber away. Build-up and drying follow the weather progression. |
| ACC | A water-film depth per tyre contact, with drainage by tread, load and speed (aquaplaning). Rain can wash out the rubbered line, and a rubbered line is slippery when wet. |
| iRacing | Puddles form from drainage over the laser-scanned surface. Drains are placed where the real ones are. Macrotexture valleys hold water before a film forms. Evaporation depends on surface and air temperature, humidity and wind. Cars remove water by tyre spray and aero. |
| AC + CSP RainFX | Per material: `PUDDLES_MATERIALS`, `SOAKING_MATERIALS` (darken when wet) and `ROUGH_MATERIALS`, plus a `WaterDrain` material. |
| RBR | No simulation. There are discrete surface sets per variant: dry, damp or wet, each new, normal or worn. |

**What a converter needs.** The live part (rain falling, evaporation, cars clearing a line) is engine simulation, and its evolution belongs to the reserved `dynamic` key. But every one of these systems reads **track properties** that do not change during a race. Those are portable, and STJ should store them:

**Per surface**, a new `water` block in the surface object:

```json
"asphalt_main": { "class": "asphalt", "…": "…",
  "water": { "storage_depth": 0.0006, "drain_rate": 8.0, "wet_look": "puddles" } }
```

- `storage_depth` (m): water the macrotexture holds before a film forms; iRacing's "asperities". The default is derived from `roughness.mean_profile_depth` (half the MPD), so most files never set it. Porous asphalt sets it high.
- `drain_rate` (mm/h): how fast a film runs off or soaks in when no rain falls. It is in mm/h so it can be compared with `precipitation` directly: a surface stays dry while rain < drain rate.
- `wet_look`: `puddles`, `soaks`, `rough`, `none`, which maps 1:1 to CSP's three material lists. It is visual only, and cheap.

**Per track**, in `water`:

```json
"accumulation": { "uri": "water/accum.png", "extent": [x_min, y_min, x_max, y_max] },
"accumulation_bands": [ { "s_start": 1210, "s_end": 1260, "t_min": -1.5, "t_max": 3.0, "factor": 1.8 } ],
"drains": [ { "id": "d_t4", "kind": "grate", "position": [x, y, z], "capacity": 40.0 } ],
"shelter": [ { "id": "tunnel_1", "band": { "s_start": 812, "s_end": 905, "t_min": -6, "t_max": 6 }, "factor": 1.0 },
             { "id": "pit_roof", "polygon": [[x, y], …], "factor": 1.0 },
             { "id": "pines_ss1", "band": { "s_start": 300, "s_end": 520, "t_min": -5, "t_max": 5 }, "factor": 0.4 } ],
"dry_line": { "line": "race", "spread": 0.9, "factor": 0.3 }
```

- `accumulation` (map, 0…2) and `accumulation_bands` (along the reference line, for authors without images) mark where water stands: dips, ruts, flat corners. An engine that simulates drainage from slope may compute these itself, but the map is the portable result.
- `drains[]`: `kind` (`grate`, `channel`, `kerb_drain`, `soakaway`), `position` or `band`, and `capacity` (mm/h over its catchment). These are iRacing's drains and CSP's `WaterDrain`.
- `shelter[]`: where rain does not reach. Tunnels, bridges and pit roofs have factor 1; tree canopy is partial. A stage through a forest stays drier under the trees, and this lets a converter say so.
- `dry_line`: a **snapshot** of a drying line: water depth × `factor` within `spread` of a racing line. It describes the state of a "drying" variant. How the line forms over time is engine simulation (`dynamic`).

**Effective film depth** at a contact, used in grip-recipe step 4 instead of the raw global depth:

`d = max(0, water_depth · A(x, y) · (1 − shelter) · D(s, t) − storage_depth)`

where `water_depth` is the signal, `A` the accumulation factor (1 where unspecified), and `D` the dry-line factor (1 off the line). `drain_rate`, `drains` and `precipitation` are inputs for engines that **evolve** `water_depth`. A static converter uses the formula above with the variant's numbers.

**RBR's discrete sets** map to variants: damp and wet are `water_depth` levels. New, normal and worn on gravel describe a **swept line** (loose stones cleared from the racing line). That has the same shape as rubber (§6), with `loose_layer_depth` instead of grip gain. §6 could cover both: see D4.

**Interaction with rubber**, from ACC and AMS2: a rubbered line is slippery when wet (`rubber.wet_gain`, §6), and heavy rain washes rubber away. The washing is evolution, so it goes to `dynamic`.

Sources:
[iRacing dynamic track model](https://www.overtake.gg/threads/iracing-a-closer-look-at-the-new-dynamic-track-surface-model.172186/),
[iRacing rain progress](https://traxion.gg/hill-iracing-team-making-tremendous-progress-on-future-rain-system/),
[CSP RainFX docs](https://cup.acstuff.club/docs/csp/tracks/rainfx),
[CSP water shader](https://cup.acstuff.club/docs/csp/tracks/water-shader),
[AMS2 water discussion](https://forum.reizastudios.com/threads/question-about-water-puddles.36028),
[AMS2 wet weather update](https://traxion.gg/wet-weather-update-for-automobilista-2/),
[ACC wet weather](https://traxion.gg/how-to-use-assetto-corsa-competiziones-wet-weather-to-your-advantage/),
[rF2 Build 1109 rain features](https://www.overtake.gg/threads/rfactor-2-build-1109-released-includes-new-rain-features.145165/),
[rF2 changelog](https://overtake.gg/news/rfactor-2-q2-content-release-and-patch-out-now.594/page/rfactor-2-changelog.131).

---

## 4. Animated objects (`animated_objects`)

This unreserves the v0.1 key.

```json
"animated_objects": [
  { "id": "windmill_1", "kind": "windmill",
    "target": { "mesh_ref": "scenery", "nodes": ["Windmill_Rotor"] },
    "animation": "rotor_spin", "playback": "loop",
    "speed_by": { "signal": "wind_speed", "curve": [[0, 0], [12, 2.0]] } },
  { "id": "pit_gate", "kind": "barrier_arm",
    "target": { "mesh_ref": "pits", "nodes": ["Gate_Arm"] }, "animation": "gate_open",
    "time_by": { "signal": "nearest_vehicle_distance", "curve": [[8, 1.0], [25, 0.0]], "smoothing": 0.5 },
    "collides": true },
  { "id": "flag_marshal_3", "kind": "flag", "target": { "mesh_ref": "scenery", "nodes": ["Flag_M3"] },
    "animation": "wave", "playback": "loop",
    "when": { "signal": "sector_flag", "op": "in", "value": ["yellow", "double_yellow"] } }
]
```

- **Keyframes are glTF animations only** (translation, rotation, scale, morph weights; skinning allowed). `animation` names one in the target's glTF file. Engine files (AC `.ksanim`, rF2 `.ANIM`) stay in `x_<engine>`.
- `playback`: `loop`, `ping_pong`, `once`, `hold`. `speed_by` scales playback rate. `time_by` scrubs normalised animation time 0…1 instead (gates, barrier arms, scoreboards).
- `when`: plays while true. When false the object rests at time 0, or holds its last frame with `hold`.
- `collides: true` makes the moving nodes a kinematic collider. Many engines cannot do this (portability §10).
- `kind` (`flag`, `windmill`, `gate`, `barrier_arm`, `crowd`, `vehicle`, `aircraft`, `scoreboard`, `machinery`, `other`) lets an engine substitute its own system, as scenery does.

Paths for helicopters, blimps and trains are ordinary translation keyframes.

---

## 5. Seasons and surface substitution

Three small pieces that make a winter variant a ten-line override file.

**5.1 `environment.season`**: the static state.
`{name: spring|summer|autumn|winter, snow_cover 0…1, snow_depth m, leaf_fraction 0…1, ground: thawed|frozen|waterlogged}`. It sets the defaults of the `snow_cover` and `leaf_fraction` signals.

**5.2 `surfaces.substitutions`**: `{"asphalt_main": "asphalt_snow", "verge_grass": "snow_soft"}`, applied **after** binding resolution, at every precedence level (meshes, OpenDRIVE, bands, terrain layers, default).
- It is an object, so an RFC 7396 override merges into it instead of replacing a whole bindings array.
- One step only: a target must not itself be substituted (validator ERROR).
- Visual swaps use the v0.1 `material_variant` (glTF `KHR_materials_variants`).

**5.3 Scenery reacts**: `when` and `density_by` on scatter layers and instance sets (§1.3). Leafless trees are a prototype swap: two instance sets with opposite `when` on `leaf_fraction`. Snow banks are a new edge style `snow_bank`.

**Why not more.** Seasonal scatter is the case where arrays hurt: a variant would have to repeat the whole `scatter` array to change one density. Signal bindings avoid that, since the layer itself says how it responds.

---

## 6. Static rubber baseline (`surfaces.rubber`)

### 6.1 Recommended: parametric

```json
"rubber": {
  "applies_to": ["asphalt_main", "asphalt_patch"],
  "line": "race", "spread": 1.2,
  "grip_gain": { "LMUX": 0.06, "LMUY": 0.05 }, "wet_gain": -0.10,
  "profile": [[0, 1.0], [430, 1.4], [520, 1.0]],
  "marbles": { "offset": 2.5, "LMU": 0.85 },
  "session_defaults": { "practice": 0.25, "qualifying": 0.5, "race": 0.6 }
}
```

The rubber level at (s, t) is

`r(s, t) = level · profile(s) · exp(−½ ((t − t_line(s)) / spread)²)`

where `t_line` is the racing line's lateral position, `level` is 0…1 and `profile` is optional (braking zones carry more rubber).

The grip recipe (spec §6.4) gains a step after step 3: `LMUX` and `LMUY` are multiplied by `1 + gain · r` when dry, and `1 + wet_gain · r` when `water_depth` > 0 (a rubbered line is slippery in the rain). Marbles beyond `spread + offset` multiply both by `LMU` at full level.

- **Static only.** How rubber builds up during a session stays in the reserved `dynamic` key. A variant changes the level by patching `session_defaults`.
- **Visual groove** (AC `groove.ini`) is drawn by the engine from the same `r`; the original file goes in `x_ac`.

### 6.2 Alternative: sampled

`levels: [[s, t, r], …]` on a grid. That is closer to rF2's RRBIN, but a grid ties to one reference line and is heavy to author. The parametric form can be **fitted** to a sampled source; the reverse is a lookup.

---

## 7. Physical props (`prototype.physics`)

```json
"cone": { "class": "prop", "height": 0.7,
  "physics": { "mode": "movable", "mass": 4.5, "center_of_mass": [0, 0, 0.2], "inertia": [0.15, 0.15, 0.09],
               "shape": { "kind": "cylinder", "radius": 0.18, "height": 0.7 },
               "friction": 0.7, "restitution": 0.2, "respawn": "session" } }
```

- `mode`: `static`, `movable`, `breakable` (detaches above `break_impulse`, N·s), `tethered` (rF2 loose objects on a spring: `tether {stiffness N/m, damping N·s/m, max_travel m}`).
- `inertia`: principal moments about the centre of mass (kg·m²), in prototype axes. Prototype frame: X forward, Y left, Z up, origin at the base centre, matching instance transforms.
- `shape`: `box {size}`, `cylinder`, `sphere`, `capsule`, or `mesh` (convex hull of the prototype's mesh node).
- `friction` is μ against the ground; the ground's surface factors do not apply to props.
- Values are for scale 1. A scaled physical instance is a WARN; engines disagree whether mass scales with s³.
- v0.1 `breakable: true` without `physics` means `mode: breakable` with engine defaults.
- `edges[]` can name a prototype and `spacing` (m) for walls built from elements: tyre stacks, hay bales, water barriers.

---

## 8. Audio (`audio`)

```json
"audio": {
  "emitters": [
    { "id": "crowd_main", "kind": "crowd", "path": [[x, y, z], …], "sound": { "uri": "audio/crowd_loop.ogg" },
      "gain": 0.8, "ref_distance": 15, "max_distance": 400, "loop": true,
      "gain_by": { "signal": "session_phase", "map": { "running": 1.0, "pre_session": 0.4 } } },
    { "id": "generator_pits", "kind": "machinery", "position": [x, y, z], "sound": { "uri": "audio/genset.ogg" },
      "gain": 0.5, "ref_distance": 3, "max_distance": 60, "loop": true }
  ],
  "zones": [
    { "id": "tunnel_1", "shape": { "band": { "s_start": 812, "s_end": 905, "t_min": -6, "t_max": 6 } }, "reverb": "tunnel" },
    { "id": "forest_east", "shape": { "polygon": [[x, y], …], "z_min": 380, "z_max": 460 }, "reverb": "forest" }
  ],
  "ambience": "open"
}
```

- Emitters are points (`position`) or **line sources** (`path`, for grandstands and rivers). Distance model follows the glTF audio-emitter drafts (KHR_audio_emitter): linear `gain`, `ref_distance`, `max_distance`, `rolloff`, optional `cone`. That extension was a draft when last checked *(m)*; STJ follows its parameter names but does not depend on it.
- `reverb` presets: `open`, `forest`, `stands`, `urban`, `canyon`, `tunnel`, `underpass`, `garage`, `pit_building`, with optional `decay_time` (s). Engines map presets to their own reverb.
- Sound files: WAV, Ogg Vorbis or FLAC, **made or licensed by the author**. FMOD and Wwise banks stay in `x_<engine>`, referenced by event name only. Converters never extract a game's audio.
- **Tyre and rolling sounds** come from the surface `class`; engine sound ids (AC `WAV`) stay in the surface's `x_<engine>`. No new field.

---

## 9. UI and minimap (`track_info`)

Added to `track_info`:

- `short_name`, `abbreviation` (≤ 4 characters, for timing screens), `description`, `tags[]`
- `media {preview, thumbnail, logo, outline}`: relative URIs; `outline` is an SVG of the track shape
- `map {uri, extent}`: a north-up image covering `extent` in world coordinates. When it is absent, engines draw the map from the reference line, which is the most portable map there is.
- `records[] {category, time (s), driver, vehicle, date, event, source}`: real-world lap records, which are public facts

Pit count and length are not repeated: they come from `pit_boxes` and the reference line.

---

## 10. Where portability is a lie (additions to spec §14)

1. **Signals need a runtime.** STJ can say "floodlights on below 3°" or "gate opens when a car is within 8 m"; a target engine without scripting (RBR, AC without CSP) can only bake one state. Converters MUST report which bindings they baked.
2. **Terrain resolution and blending.** UE, Unity and RoR need `2^n + 1` grids, BeamNG powers of two, and mesh engines triangles. Every resample moves the ground by millimetres to centimetres, enough to make a road mesh and the terrain fight. Layer blending is engine shading; physics sees one dominant layer.
3. **Water physics.** Only BeamNG-class engines simulate buoyancy and wading; everywhere else a ford is a surface with `wading_drag`, which is a made-up number.
   **Drying.** STJ stores where water collects, drains and is sheltered, plus a snapshot of a drying line. How fast a track dries is each engine's simulation: the same `drain_rate` dries an rF2 track and an AMS2 track at different speeds, and RBR cannot dry at all.
4. **Rubber feel.** No engine publishes its rubber grip model. `grip_gain` values are estimates, and a fitted RRBIN loses its detail.
5. **Kinematic colliders.** A moving gate that collides is simple in BeamNG or UE and absent in many sim engines; there it becomes a static collider in its rest pose or none.
6. **Audio** is re-mixed, not reproduced. Presets and distance curves give a similar soundscape; no two engines' reverbs sound the same.

---

## 11. Decisions for the project owner

**D1. Scope of v0.2.** Recommendation: all nine. The four groups in increasing order of risk:
- (a) UI, props, audio: small, low risk
- (b) terrain and water
- (c) signals, animated objects and seasons, which come as a set
- (d) rubber

**D2. Terrain.** Recommendation: **first-class heightfield** with the strict grid rules of §2.2, two formats (`png16`, `raw_f32`) and dominant-layer physics. Alternative: meshes only, with terrain in `x_<engine>`. That is simpler, but it throws away the one structure five engines share, and makes BeamNG/UE/Unity imports re-derive a heightfield from triangles.

**D3. Signals and animation.** Recommendation: a **closed signal vocabulary plus declarative conditions and bindings** (§1), with glTF animations for keyframes. Alternatives:
- glTF loops only, with no signals or conditions: simplest, but lights and seasons stay hard-wired
- a small expression language: more power, but every converter needs an interpreter, and it drifts toward scripting, which the survey says to reference, never model

**D4. Rubber.** Recommendation: **parametric** (line + Gaussian spread + gain, §6.1), generalised to a **line state**. The same field also describes a gravel line swept clean (`loose_layer_depth` factor instead of grip gain), which is RBR's new/normal/worn (§3.1). Alternatives: a sampled grid (§6.2), or `x_<engine>` only until someone measures rubber grip.

### Smaller choices made here (say if any is wrong)

- `precipitation` in mm/h, a documented SI exception
- terrain: image row 0 = north edge; only `png16` and `raw_f32`
- terrain contacts use the dominant layer, not blended friction
- surface substitution is one step, with no chains
- puddles are water bodies with a `fill` binding, plus an `accumulation` map
- water rates (`precipitation`, `drain_rate`, drain `capacity`) all in mm/h, so they compare directly
- `storage_depth` defaults to half the macrotexture MPD
- STJ stores the drying line as a snapshot (`dry_line`); its evolution waits for `dynamic`
- physical props must not be scaled
- `track_info` grows instead of a new `ui` block
- light `schedule: night` is defined as `sun_elevation < 0`

---

## 12. Implementation plan once decided

1. Schema: `signal`, `condition` and `binding` definitions; the new blocks; `version` enum `["0.1", "0.2"]`; `animated_objects` unreserved.
2. Validator:
   - signal names and units
   - condition values against enum signals
   - terrain grid and size rules, plus terrain-above-road sampling (a stdlib PNG16 reader)
   - water geometry; shelter and accumulation bands on the line; drain capacities; `dry_line` naming an existing racing line
   - substitution targets and chains
   - inertia triangle inequality, scaled props
   - animation names in the glTF file
   - audio ranges
3. Examples:
   - the gravel stage gets a small terrain, a ford, forest shelter, a winter variant and a crowd emitter; its wet variant gets accumulation bands
   - the GP ring gets rubber, cones, a windmill, floodlights on `when`, drains, a pit-roof shelter and a "drying" variant with a dry line
4. Spec §6.4 grip-recipe step for rubber, §6.3 precedence for terrain and substitutions, §14 additions, a Blender mapping row for each new block. Blender items still to verify with `blend_probe.py`:
   - Actions → glTF animations
   - Speaker objects → emitters (the glTF exporter probably drops them)
   - Rigid Body settings → `physics`
   - 16-bit packed images
5. Tests for each new check, plus the strict pass of all examples.
