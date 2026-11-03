# STJ proposal: Tier 3 and the reserved keys

Status: **accepted** 2026-11-02:
- D1: all four groups
- D2: reference laws
- D3: chunks along s plus a grid
- D4: crowd areas with behaviour

Implemented as **v0.3 (draft)**: spec §6.10, §7.6, §8.8, §10.1 and §11. Changes during implementation:
- the track-temperature `shade` map sits in `dynamic.track_temperature`
- a mesh joins a chunk or tile with `"chunk": "<id>"` (tiles are `tile_<i>_<j>`)

Source:
- `docs/feature_survey.md` Tier 3: reflection probes, video screens, crowd behaviour, marshal and restricted zones, climate statistics, streaming tiles.
- The two keys still reserved: `marshals` and `dynamic`.
- Open questions Q10 (track limits beyond wheel counting) and Q14 (large worlds).

All of it would be additive to v0.2. The two reserved keys change from "any object" to a defined object.

**A gap found while preparing this.** The `sector_flag` signal (spec §11.1) is "the flag of the marshal sector at the consumer's s", but nothing in STJ defines marshal sectors. §1 fixes that.

---

## 1. Race control: `marshals`

```json
"marshals": {
  "sectors": [ { "id": "m1", "s_start": 0, "s_end": 420 }, { "id": "m2", "s_start": 420, "s_end": 977 } ],
  "posts": [
    { "id": "post_3", "kind": "flag_post", "sector": "m1", "s": 310, "side": "right", "position": [x, y, z],
      "signals": ["yellow", "double_yellow", "blue", "white", "red", "slippery", "chequered"], "light_panel": true },
    { "id": "radio_2", "kind": "radio_point", "s": 5200, "side": "left", "position": [x, y, z] }
  ],
  "vehicles": [ { "id": "sc", "kind": "safety_car", "pose": { "s": 60, "t": 8 } },
                { "id": "rec_1", "kind": "recovery", "base": "post_3" } ],
  "restricted_zones": [ { "id": "pit_exit_line", "shape": { "band": { "s_start": 250, "s_end": 300, "t_min": 4, "t_max": 6 } },
                          "rule": "penalty", "value": 5 } ],
  "reset": { "mode": "nearest_on_line", "t": 0, "min_spacing": 20,
             "points": [ { "s": 1450, "t": -2, "_note": "after the hairpin, not in it" } ] }
}
```

- **Sectors** define what `sector_flag` refers to. They are contiguous along s like timing sectors, but independent of them: real circuits have many more marshal sectors than timing sectors.
- **Posts**: `kind` is `flag_post`, `light_panel`, `radio_point` (rally safety, typically every few km), `medical`, `fire` or `spectator_point`. Each post has the flags it can show. Animated marshals (spec §8.5) bind to `sector_flag` there.
- **Vehicles**: `safety_car`, `medical`, `recovery`, `fire`, `course_car`, `helicopter`, each with a starting pose or a base post.
- **Restricted zones**: a band or polygon with a `rule`.
  - `penalty`: `value` is in seconds.
  - `reset`
  - `speed_limit`: `value` is in m/s.
  - `no_entry`: blocked, like an invisible respawn edge but area-based.

  This answers the geometry half of **Q10**. Per-corner rules stay out: they are sporting regulations, not track data.
- **Reset**: where a car is put back after leaving the road. Every game needs a rule, and today each one invents its own. Either `nearest_on_line` (project onto the line at `t`, never closer than `min_spacing` to a corner apex), or explicit `points` that take precedence nearby.

## 2. How a track changes during an event: `dynamic`

v0.2 stores **static states** for these:
- the rubber and swept-line levels per session
- the water depth, with where water stands, drains and is sheltered
- surface maps per wear state

What engines simulate is how those states **evolve**. Two ways to describe that:

**(a) Reference laws.** STJ defines a few simple, first-order evolution laws with parameters. Engines may use their own model, but STJ values are calibrated against these laws, so they mean the same thing everywhere.

| Process | Reference law | Parameters |
|---|---|---|
| Rubbering / sweeping (a line state) | per car pass: `level += gain · (1 − level)`; in rain: `d level/dt = −wash · precipitation · level` | `gain_per_pass`, `wash` (per mm) |
| Water film | `d depth/dt = precipitation · (1 − shelter) · A − drain_rate − evaporation`, clamped ≥ 0, where `evaporation = e0 · (1 + c_wind · wind) · max(0, T_track − T_dew)/10` | `e0` (mm/h), `c_wind` (s/m) |
| Ruts (loose surfaces) | per pass on the line's wheel tracks: `depth += rate · (1 − depth/max_depth)` | `depth_per_pass`, `max_depth`, `track_width`, `rut_width` |
| Wear signal | `wear` rises with the cars that have passed: `wear = 1 − exp(−cars / cars_to_worn)` | `cars_to_worn` |
| Track temperature | towards `T_air + sun_gain · insolation · (1 − shade)`, with time constant `tau` | `sun_gain`, `tau` (s), plus `shade` from `water.shelter` and a new optional shade map |
| Marks and debris | how long tyre marks and debris last | `persistence` per surface (`effects.marks` already has it) |

**(b) Parameters only.** Engines decide the laws. STJ just carries the numbers, which then mean something only to the engine that wrote them.

The recommendation is (a). Without a shared law, a "rubbering rate" is a number with no unit. With one, the numbers stay small and checkable, and `stj_core` gets a reference stepper, like the film-depth function.

## 3. Large worlds: tiles and local origins (Q14)

Long rally stages (20–50 km) break the 10 km float32 rule of spec §4.4. Today the only answer is to split them into separate files.

```json
"geometry": {
  "chunks": [
    { "id": "c01", "s_start": 0, "s_end": 8000, "origin": [-3200.0, 1250.0, 640.0],
      "meshes": ["c01_road", "c01_visual"], "terrain": "terrain_c01" },
    { "id": "c02", "s_start": 7900, "s_end": 16000, "origin": [2650.0, 4980.0, 702.0],
      "meshes": ["c02_road", "c02_visual"] }
  ]
}
```

- A **chunk** is a stretch of a stage with its own **local origin**. Its glTF files are authored relative to that origin. Everything else in STJ stays in world coordinates; JSON numbers are doubles, so that is exact.
- Chunks may overlap in s, so an engine can stream the next chunk before the current one ends.
- **Open areas** (a test site, a rallycross venue with long transfer roads) use a grid instead: `tiles {size, origin}` with `[i, j] → meshes` entries.
- Terrain gains an array form (`geometry.terrains[]`), one heightfield per chunk or tile.
- What each engine streams, and at what budget, stays the engine's. STJ only says how the world is cut and where each piece's origin is.

## 4. Presentation

| Item | Shape | Why |
|---|---|---|
| **Reflection probes** | `environment.probes[] {id, kind: reflection \| irradiance, position, extent (box), priority, when}` | Where an engine should capture local reflections: tunnels, pit garages, forests. CSP local cubemaps, UE and Unity probes. |
| **Screens** | `screens[] {id, target {mesh_ref, node, material}, content: timing_tower \| leaderboard \| replay \| live_camera \| image \| video, uri, when}` | Scoreboards and big screens show race state. The content is semantic; the engine fills it. |
| **Crowds** | `crowds[] {id, area {band \| polygon}, density (per m²), prototype, behaviour: static \| cheer \| follow \| flee, flee_distance, when}` | Rally spectators who step back as a car arrives (with `time_to_arrival`), grandstands that cheer. One rule instead of thousands of instances. |
| **Climate** | `environment.climate {source, monthly[] {month, t_min, t_max, rain_days, rain_mm, wind_mean}}` | Statistics for generating plausible weather for a date; `weather_options` stays for authored choices. |

## 5. Where portability is a lie (spec §14 additions)

1. **Evolution laws.** The reference laws are simple on purpose. An engine with a real tyre-wear or water model will evolve the track differently. The laws make the numbers comparable, not the result identical.
2. **Crowd behaviour.** "Flee" is a semantic request. How fast and how plausibly spectators move is the engine's.
3. **Reset rules** decide where a car lands after an off. The same rule on two engines with different collision meshes can still put a car in a different place.

## 6. Decisions

**D1. Scope.** Which groups go in now? Recommendation: race control (§1) and presentation (§4), both small and clear, plus whatever D2 and D3 decide.

**D2. `dynamic`.** Recommendation: **reference laws with parameters** (§2a). Alternatives:
- parameters only (§2b)
- keep `dynamic` reserved

**D3. Large worlds.** Recommendation: **chunks along s with local origins, plus a grid for open areas** (§3). Alternatives:
- grid only
- keep tiling out of STJ, which means splitting long stages into files

**D4. Crowds.** Recommendation: **semantic crowd areas with behaviour bound to signals** (§4). Alternative: only spectator prototypes and instances, as today.
