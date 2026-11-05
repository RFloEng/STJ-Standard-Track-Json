# Proposal for STJ: what a Richard Burns Rally conversion could not store

Status: **partly accepted** 2026-11-05, in v0.3 (draft). Items 1 to 3, 5, 6 and 8 to 10 are implemented as below. **Items 4 and 7 are open** and wait for a decision. The original text of the proposal follows the decisions, unchanged.

## Decisions

| # | Item | Decision |
|---|---|---|
| 1 | Per-weather sky, fog, lighting | Already expressible: `weather_options[].variant` points at a weather variant, which patches any part of the document. Added `variant` to `weather_schedule[]` entries, so weather that changes during a session can change the sky too. No inline environment block. |
| 2 | Ambient light, sun direction | Done: `lighting.ambient {color, intensity}`, `lighting.sun.direction` (unit vector towards the sun; fixes the sun and drives `sun_elevation`) and `sun.color`. |
| 3 | Tangents per segment | Done: `tangents_out` and `tangents_in` (spec §7.1). `tangents` stays valid. A reversed layout swaps the two. |
| 4 | Asset manifest with licence per file | **Open.** Shape to decide: an optional `assets[]` for what USD cannot list (hash, licence), cross-checked against the USD asset paths, and recording licences without judging them. |
| 5 | Engine-scripted animated objects | Done, reshaped: an animated object may have a `kind` (new: `clock`) and no `time_range`; the script name stays in `x_<engine>`. The validator warns when neither a `time_range` nor an `x_<engine>` block is there. |
| 6 | Sound events without files | Done: `sound` is optional when the emitter has an `x_<engine>` block naming the event; `max_distance` is the radius of the sphere. No new `shape.sphere`. |
| 7 | Level of detail ranges | **Open.** Mostly covered already: a mesh with the `lod` role and `lod {of, level, switch_distance}` is a far mesh that repeats a near one. `rbr2stj` should emit those. What is left is LODs for scenery prototypes, shared with the visual-materials proposal. |
| 8 | Wind sway, alpha-test | Sway done: `prototypes[].wind {amplitude, frequency, weight_primvar, phase_primvar}`. The alpha cutoff stays in USD (`opacityThreshold`). |
| 9 | Visual-only water, mirrors | Done: `water.bodies[].physical: false` (needs a `mesh`) and `geometry.meshes[].reflective`. |
| 10 | Baked lighting roles | Done: `geometry.meshes[].baked {vertex_colour {primvar, role}, shadow_map, specular_map}`. |

---

## Original proposal (from rbr2stj)

Source: converting real RBR / RSF stages (326 converted in the first full run) with `rbr2stj` against STJ v0.3. Each item says what the game files hold, what STJ
v0.3 lacks, what `rbr2stj` does today (so nothing is lost), and a small schema sketch. Ordered by how much a viewer or an
engine gains. None of this is needed to open a converted package; all of it is currently kept under `x_rbr` or in the USD layers.

## 1. Per-weather environment (sky, fog, lighting)

*Game:* every RSF weather (`TrackSettings<id>.ini`; stage 101 has five) sets its own fog (start, end, colour), ambient and
diffuse light, skybox, cloud mesh, sun intensity and reflectance.
*STJ v0.3:* `environment.sky`, `.lighting` are single objects; `weather_options[].weather` has no fog or light, so only
`visibility` can vary by weather.
*Today:* the default weather fills `sky.fog` (visibility = FogEnd, an estimate) and every weather's raw values sit in
`weather_options[].x_rbr.settings`.
*Proposal:* let a weather option carry the blocks that change with it.

```json
"weather_options": [{
  "weather": {"condition": "overcast", "visibility": 400},
  "environment": {"sky": {"fog": {"visibility": 400, "color": [0.6, 0.62, 0.66]}},
                  "lighting": {"ambient": {"color": [0.5, 0.5, 0.5]}}}
}]
```

## 2. Ambient light and an explicit sun direction

*Game:* ambient and diffuse RGB plus a stored `SunDir` vector per weather; the sun does not follow date and time.
*STJ:* sun comes from geo reference and time only; `lighting` has `sun.illuminance` and point/spot lights, no ambient.
*Proposal:* `lighting.ambient {color, intensity}` and `lighting.sun.direction` (unit vector, overrides the astronomical
position when present), documented as the way to describe games with a fixed lighting rig.

## 3. Driveline tangents per segment

*Game:* one Hermite tangent per segment, used at both ends of that segment (stage 101 stores exactly the chord of each segment; stage 107 stores smoothed values, 0.03x to 2.4x the chord; so
neighbouring segments of 5 m and 23 m get unrelated tangents).
*STJ:* one tangent per point, shared by both segments around it, so the curve cannot be reproduced.
`rbr2stj` averages the two sides; measured against the game's own curve that is 0.64 m mean and up to 11 m at the worst length
jumps (stage 101), and the validator warns 3 times on stage 101 and more on others (353 in total over the first full run).
*Proposal:* an optional `tangents_out` (and `tangents_in`, defaulting to `tangents_out`) of the same length as `points`, so a
segment uses `tangents_out[i]` at its start and `tangents_in[i+1]` at its end. Old files stay valid.

## 4. An asset manifest with licence per file

*Game:* meshes use textures from several archives; converters copy them (RSF content is not redistributable).
*STJ:* `geometry.meshes[]` points at a USD file; textures live inside it, so a tool cannot list, check or strip the assets
that carry a restrictive licence.
*Proposal:* `assets[]` entries `{id, uri, role: texture|sound|mesh|script, sha256, licence?, source?}` referenced by mesh
materials, and `licence.redistributable` honoured per asset.

## 5. Engine-scripted animated objects

*Game:* animated objects (start clock, flags) are named in the `.lbs` with Lua script names, with no keyframes stored.
*STJ:* `animated_objects[]` requires `target.nodes` and `time_range`, i.e. USD time samples.
*Proposal:* `animated_objects[].script {engine, name}` as an alternative to `target`/`time_range`, so scripted behaviour can
be recorded without inventing keyframes.

## 6. Sound events without sound files

*Game:* sound spheres (position and radius word) trigger named events from the game's sound banks, which a converter cannot
extract.
*STJ:* `audio.emitters[].sound.uri` is required.
*Proposal:* `sound.event` as an alternative to `uri`, and `shape.sphere` on emitters.

## 7. Level of detail ranges

*Game:* each render chunk has a draw list (near / always / far); far meshes repeat near ones at lower detail and switch at
about 600 m (reRBR notes).
*STJ:* nothing ties a mesh to a distance range.
*Today:* far meshes are separate `_far` prims, hidden, tagged `stj:drawList`.
*Proposal:* `geometry.meshes[].lod {range: [min, max]}` (metres), or the same on `scenery` prototypes.

## 8. Wind-swayed vegetation and alpha-tested lanes

*Game:* "object lanes" are billboards and trees with per-vertex sway (amplitude, frequency, phase), alpha-tested at 60/255.
*STJ:* no sway or alpha-test hint on scenery.
*Proposal:* `scenery.prototypes[].wind {amplitude, frequency}` and `.alpha_cutoff`.

## 9. Visual-only water and reflection surfaces

*Game:* water and mirror faces that are not driving surfaces.
*STJ:* `water.bodies` carry depth and physics.
*Proposal:* `water.bodies[].physical: false` (visual only) with the mesh reference.

## 10. Baked lighting roles

*Game:* vertex colour is baked light, shadow-map and specular UV sets exist per vertex, the shadow images are separate files.
*STJ:* no way to say "this primvar or texture is baked light, do not multiply it blindly".
*Proposal:* a `geometry.meshes[].baked {vertex_colour, shadow_map, specular_map}` description, so an engine can choose to
use or ignore it.

## Not proposed

Grip and tyre physics (NGP `physics.lsp`), rut and deformation state, particle files, shader code: engine-specific, they stay
under `x_<engine>`.
