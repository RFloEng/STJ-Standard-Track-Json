# STJ proposal: lessons from RBR stages

Status: **accepted** 2026-11-02, with the recommended answers to D1–D4. The batch A1–A15 is implemented with them, in v0.2 (draft): spec §6.3, §6.5–§6.7, §7.1, §7.3, §7.5, §8.2, §8.4, §8.6, §10, §11, §11.1.

Source: the open reimplementation [JodusNodus/rerbr](https://github.com/JodusNodus/rerbr), which parses every RBR stage file (`.trk`, `.dls`, `.col`, `.mat`, `.lbs`, `.fnc`, `TrackSettings.ini`, particle and AI tables). This document is about the **standard**: what a stage carries that STJ v0.2 cannot say, rewritten in engine-neutral terms. It is not a converter design.

---

## 1. What an RBR stage is (short)

- **Reference.** A Hermite spline with **stored distance per point**. Timing, splits and pace notes are keys at a distance along it; there are no gate geometries.
- **Surfaces.**
  - Each collision triangle has **two** surface entries and per-vertex coordinates into a small table of surface ids. The surface therefore **varies inside a triangle**.
  - The tyre **blends two surfaces** by a per-vertex weight.
  - There is one whole surface map per **wear × wetness** state (new/normal/worn × dry/damp/wet), picked at load, and textures switch the same way.
- **Surface physics.** Absolute coefficients per tyre type × surface class:
  - static and kinetic friction, plus soil friction
  - a hard-ground offset below the mesh, soil thickness and density
  - a deterministic **sine bump** (amplitude, period)
  - water factor, rolling resistance
  - impact friction and restitution, and flags (soft, hard, bendable)
  - surface effects: dust, spray, skid-mark look
- **Limits.** An invisible **drag strip** (the "brake wall") slows a car that leaves the road, with sensor and respawn flags. There is no cut detection.
- **Water.** Deep-water quads, plus puddle quads that exist **only when the stage is wet**.
- **Scenery.**
  - props with kind, shape and mass class
  - bendable trees
  - tearable tape and net fences that stay torn for the drive
  - foliage with per-vertex **sway**
  - characters (spectators, marshals, animals, a helicopter) triggered by **time to arrival** (`distance − lead·speed`)
- **Presentation per time of day.** Baked vertex light and shadow maps, sun direction, ambient and fog per variant letter.
- **Sound.** Left and right reflection distances along the road (engine echo), and sound spheres.
- **Pace notes.**
  - Tags with grades whose spoken numbering **depends on the call style**, plus modifier flags.
  - The stage stores **no call timing**. Lookahead is seconds × speed, decided by the player.
  - The distance word and links (into / and) are **derived at runtime** from the gap to the next note.
- **Metadata.** A primary surface class (gravel, tarmac, snow) that picks tyres and setups. Per-section par times and difficulty ratings (curves, rough, obstacles, straights). An allowed-weather table with weights.

---

## 2. Where STJ's model is wrong or incomplete

1. **Surface per contact.** STJ binds one surface per collision primitive. RBR decides per contact point and blends two surfaces. A real ground has gravel patches, worn lines and verges that do not follow triangle edges either. → **D1**.
2. **Surface state is spatial, not just a line.** RBR's wear swaps a whole surface **map**. STJ's `line_states` (a level along a racing line) cannot express "this stretch is cleaner, that bend is rutted". The same goes for wetness: RBR has no water film; its wet maps are authored. → **D2**.
3. **Absolute friction tables.** Games store μ per tyre class × surface, not scalings relative to a reference road. Turning them into λ needs a reference tyre that does not exist. → **D3**.
4. **Stored chainage.** RBR's markers are keyed to a **stored** distance per point, not the recomputed arc length. Real road surveys also carry chainage (kilometre posts) that differs from geometric length. If STJ always recomputes `s`, everything keyed to s shifts. → **D4**.
5. **Pace notes.**
   - `distance_to_next` and link words are derived from the notes' positions; storing them invites inconsistency.
   - When a note is called is the consumer's decision (seconds of lookahead). STJ already says so; it should also make derived fields explicitly derived.

---

## 3. Small additions (recommended as a batch)

| # | Addition | Shape | Why |
|---|---|---|---|
| A1 | **Sinusoidal roughness** | `roughness.sinusoid {amplitude, wavelength}` | RBR's sine bump and AC's `SIN_HEIGHT` / `SIN_LENGTH` are the same idea. Today it can only be approximated from ISO 8608. |
| A2 | **Hard base below the surface** | `deformable.effective.base_offset` (m, hard ground below the mesh) | RBR `SolidGroundOffset`; how deep a wheel sinks before it hits rock |
| A3 | **Impact behaviour of surfaces** | `impact {friction, restitution, response: rigid \| soft \| bendable}` | Rocks, snow walls, bushes and trees hit differently; RBR `CollMy*`, `e*`, SOFT/HARD/BENDABLE |
| A4 | **Bendable props** | `physics.mode: bendable`, with `stiffness` | Bendable trees and posts |
| A5 | **Invisible drag zones** | `edges[].kind: invisible`, `behaviour: drag \| sensor \| respawn`, `drag_coefficient` | RBR's brake wall, and the soft run-off of many games. Physical limits, not timing penalties. |
| A6 | **Conditional water** | `water.bodies[].when` (a condition) | Puddles that exist only when wet. `fill` scales depth; `when` decides presence. |
| A7 | **Time to arrival** | New local signal `time_to_arrival` (s, for the nearest car to reach the consumer's s along the reference line) | Spectators, marshals and helicopters react "2 s before the car", with no trigger structure |
| A8 | **Tearable fences** | `edges[].tearable: true` (tape, net) | They stay torn for the drive and give no force back |
| A9 | **Surface effects** | `effects {dust {color, amount}, spray, marks {color, persistence}}` | Dust colour and skid marks are part of what a surface *is* to a driver; portable at a semantic level |
| A10 | **Foliage sway** | glTF attribute convention `_SWAY` (VEC3: amplitude m, frequency Hz, phase rad), scaled by `wind_speed` | Per-vertex foliage motion that every engine can rebuild |
| A11 | **Primary surface class** | `track_info.primary_surface` (`tarmac`, `gravel`, `snow`, `mixed`…) | Picks tyres and setups before anything is loaded |
| A12 | **Stage character** | `race.sections[] {id, s_start, s_end, reference_time, surface, ratings {curves, rough, obstacles, straights} 1–5}` | Reference times and difficulty for AI times, menus and event generation |
| A13 | **Weather options** | `environment.weather_options[] {variant, weather, weight}` | Which conditions a stage allows and how likely each is. RBR's season table; the climate item from survey Tier 3. |
| A14 | **Acoustic profile** | `audio.reflections [[s, left_m, right_m], …]` | Distance to reflecting walls each side, for engine echo in cuttings and villages |
| A15 | **Pace-note vocabulary** | kind `twisty`; modifiers `tightens_bad`, `narrows`, `widens`; note `call_adjust` (s, + earlier / − later); `distance_to_next` documented as derived (WARN when it disagrees with positions) | Missing RBR/RSF terms, plus inline timing hints without storing call timing |

Engine-specific, stay in `x_<engine>`: visibility cells and near/far/always draw lists, Lua character scripts, particle-system tables, RSF extended call ids and sound takes.

---

## 4. Shapes for the four decisions

### D1. Surfaces inside a primitive

Reuse the weight encodings of `ground` (spec §8.7) for physics:

```json
"surfaces": {
  "maps": [ {
    "mesh_ref": "stage_collision", "material": "Ground",
    "palette": ["gravel_loose", "gravel_hardpack", "verge_grass"],
    "weights": { "encoding": "vertex_top3", "indices": "_STJ_SURF_LAYERS", "weights": "_STJ_SURF_WEIGHTS" },
    "contact": "blend"
  } ]
}
```

- `contact: blend`: the contact's surface parameters (λ, rolling resistance, deformable values) are the weighted mean of the palette entries. This is what RBR does with two surfaces.
- `contact: dominant`: the largest weight wins, as terrain does today.
- A surface map takes precedence over the material binding of the same primitive (spec §6.3).

### D2. Spatial surface states

Two parts:
1. New signal `wear` (0…1: 0 = new or clean, 0.5 = normal, 1 = worn).
2. `when` on surface maps, bindings and ground materials.

A single file can then carry all nine RBR states (or a real event's clean/rutted maps), selected at load or live:

```json
"maps": [
  { "when": { "all": [ {"signal": "wear", "op": "lt", "value": 0.25}, {"signal": "wetness", "op": "lt", "value": 0.2} ] }, "…": "…" },
  { "when": { "signal": "wear", "op": "ge", "value": 0.75 }, "…": "…" }
]
```

The first map whose condition holds is used. `line_states` stays for the parametric case.

### D3. Absolute friction per tyre class

`surfaces.reference_mu {<tyre_class>: {peak, sliding}}`: μ of each tyre class on **STJ-REF**. A surface may then give `by_tyre_class.<class>.mu {peak, sliding}` in absolute terms, and the spec defines `LMUX = LMUY = μ_peak / μ_ref,peak` for that class.

Game tables then go in as they are. Only one number per tyre class needs the reference road, and it is visible and replaceable instead of hidden in every surface.

### D4. Stored chainage

- `reference.centerline.chainage`: optional, one value per point, increasing. Where present, it **defines s**, and geometric length is only checked against it (WARN beyond 1%).
- `reference.centerline.tangents`: optional Hermite tangents, one per point, so a smooth spline is not reduced to a polyline.

---

## 5. Decisions

**D1.** Surfaces that vary inside a collision primitive, with blending (§4 D1). Recommendation: **yes**, reusing the `ground` encodings, with `contact: blend | dominant`.

**D2.** Spatial surface states: a `wear` signal and `when` on surface maps (§4 D2). Recommendation: **yes**. Alternative: keep one state per variant file. That is simpler, but nine variant files per stage, each repeating the arrays.

**D3.** Absolute μ per tyre class with one declared reference μ per class (§4 D3). Recommendation: **yes**, as an alternative to λ. λ stays the primary form.

**D4.** Stored chainage and Hermite tangents on the centerline (§4 D4). Recommendation: **yes**, both optional.
