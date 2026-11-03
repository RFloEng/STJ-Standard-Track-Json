# STJ proposal: world frame and surface model

Status: **accepted** 2026-11-02, with the four recommended answers in §4: Z-up OpenDRIVE frame; an additive SVJ field for the tyre's reference surface; λ multiplication plus a per-tyre-class table; deformable Tier A + Tier B. Implemented in `schema/stj.schema.json` v0.1 and `spec/STJ_Spec.md` §4 and §6.

---

## 1. What STJ takes from SVJ

| SVJ convention | STJ |
|---|---|
| `_metadata` required (`specification`, `version`, `coordinate_system`, `units`); every other top-level key optional | Same. `specification: "STJ"`. Adds `licence` and `provenance` (§1 of the brief). |
| `data_origin {type, detail, confidence}`, `source_format` | Reused, with `type` extended by `scanned` and `converted`, plus a `converted_from` chain. |
| SI units, angles in rad, temperature in °C, curves as `[[x, y], …]` | Same. |
| `x_<engine>` keys at any level; parsers MUST ignore unknown `x_` keys | Same (`x_rbr`, `x_ac`, `x_beamng`, `x_acr`, …). |
| `_est: true`, `_source`, `_note` field-level provenance | Same. Important for tracks: most surface numbers will be estimates. |
| `$ref` modules; `*.svj-override.json` = `base` + RFC 7396 `patch` | Same: `*.stj-override.json`, `specification: "STJ-OVERRIDE"`. Wet, night, reverse and alternate layouts are overrides. |
| `assets.meshes[] {id, uri}`, relative URIs only | Same, plus `role`: `visual`, `collision`, `lod`. |
| glTF node names `SVJ::<category>::<id>` | `STJ::<category>::<id>`; surfaces bind through glTF **materials** (§3.5). |
| `_metadata.coordinate_system` may be an axis object describing the glTF asset | **Differs**: not needed. glTF 2.0 fixes its own frame (Y up, +Z front, metres), so STJ states one fixed glTF↔STJ mapping (§2.3). |
| Versioning: minor = additive, patch = clarifications | Same, starting at `0.1`. |

**Gap found in SVJ.** `tires.sets.<id>.reference` records load, pressure, speed and camber, but not the **surface** the coefficients were fitted on. `external_models[].conditions.surface` exists, but only as a free string on external files. The whole surface model depends on this field (§3.2).

---

## 2. World frame

### 2.1 Recommendation: Z-up, right-handed, flat, the OpenDRIVE inertial frame

| Axis | Direction |
|---|---|
| X | East when geo-referenced, otherwise any horizontal direction |
| Y | North when geo-referenced (X rotated +90° about Z) |
| Z | Up. `z` is height. |
| heading ψ | rad, counter-clockwise from +X (OpenDRIVE `hdg`) |

Suggested name: `_metadata.coordinate_system: "OpenDRIVE"`. SVJ's schema already lists that value, so the two standards share one vocabulary.

**Why not an SAE J670-style earth frame with Z down:**

1. **Everything STJ references is Z-up.** That includes OpenDRIVE (inertial z up, `hdg` CCW, `t` positive left), OpenCRG (`v` left, `z` up), PROJ/GIS and Blender. glTF is Y-up, but up is still positive. With Z-up, OpenDRIVE and OpenCRG coordinates pass through unchanged. With Z-down, every one of them needs a flip, and every converter author has a chance to get it wrong.
2. **Elevation reads as elevation.** On a hill-climb stage a decreasing z would mean the road goes up. That trap would sit in every file.
3. **Aligning with SVJ costs one fixed rotation, defined once** (§2.4). SVJ is a body frame and STJ is a world frame, so they never had to share axes.

### 2.2 Where "ENU" is a lie, and what STJ says instead

- **Earth curvature.** A true local tangent plane falls away from the ground by d²/2R: about 2 m at 5 km and about 18 m at 15 km. A 25 km stage built from GNSS or LiDAR in a tangent plane would come out visibly bent. So, like OpenDRIVE, STJ x/y are **map-projected** coordinates and z is height above a vertical datum. The geo-reference is a PROJ string (`environment.geo_reference`), the same mechanism as OpenDRIVE's `<geoReference>`.
- **Projection scale error.** UTM is off by about −0.4 to +1 m per km, which is 10–25 m over a 25 km stage. The spec recommends a local Transverse Mercator centred on the track, where the error is negligible. A file with UTM is still valid; the spec warns about it.
- **Most game tracks have no geo-reference.** For them x/y are simply a flat right-handed Z-up frame. `environment.north_heading` says where true north is, for the sun. This is also needed with a projection, because grid north is not true north (meridian convergence, up to a few degrees).
- **float32.** Engines store positions in float32. Between 16 and 32 km from the origin the resolution is about 2 mm, enough to make contact patches jitter. JSON keeps doubles, but the spec recommends putting the origin near the track centroid with all geometry within about 10 km. `environment.origin_offset` records any re-origining a converter does.

### 2.3 glTF ↔ STJ

`(x, y, z)_STJ = (x, −z, y)_glTF`, a +90° rotation about X with determinant +1. This is exactly what Blender's glTF importer and exporter do with "+Y up", so **Blender scene coordinates are STJ coordinates**. A track built or edited in Blender needs no transform at all.

### 2.4 Placing an SVJ vehicle

A pose in STJ (grid slot, pit box, spawn) is a ground point `p` and a heading `ψ`. Normative:

```
p_world = p + Rz(ψ) · diag(1, −1, −1) · p_SVJ
```

`diag(1, −1, −1)` is a 180° rotation about X that turns SAE x-fwd/y-right/z-down into x-fwd/y-left/z-up. The pose locates the **SVJ origin**, the front-axle midpoint at ground level. Pitch and roll come from dropping the vehicle onto the surface. Converters that spawn by CG or by bounding box take the offset from the SVJ file.

### 2.5 Track-relative frame (s, t, h)

Positions along the track use OpenDRIVE/OpenCRG reference-line coordinates:

- **s**: distance along the reference line (m), increasing in the race direction.
- **t**: lateral offset, positive to the left.
- **h**: height above the surface.

Timing lines, sectors, splits, pit lane, pacenotes and surface bands are given in `s` (and `t`), not only in x/y. That is what lets the validator check that sectors are ordered, and what keeps timing correct after a mesh swap. For a closed circuit, `s` lies in `[0, L)` and wraps; ordering is checked modulo the lap.

---

## 3. Surface model

### 3.1 The problem

Every simulator computes grip as f(tyre, surface, state). SVJ already describes the tyre: MF coefficients plus the scaling factors λ (`pacejka.scaling`: `LMUX`, `LMUY`, `LKX`, …, all 1 when absent, §11.13.1). A surface "μ = 0.6" only means something relative to the surface the tyre data describes, and that surface is unknown today:

- Flat-belt rig data is fitted on an abrasive belt, not on asphalt.
- A game's tyre is fitted to that game's own road (AC tyres assume AC's road with `FRICTION=0.98`-ish).
- An RBR gravel tyre is fitted to gravel.

### 3.2 A reference surface, defined once

STJ defines **`STJ-REF`**: dry, clean, unworn dense asphalt. All its λ are 1 by definition, and every STJ surface is expressed relative to it.

A tyre set then has to say what surface it was fitted on, in STJ terms. That is the λ of its reference surface, or the id of a standard STJ surface class. With `λ_tyre_ref` denoting that, the combination is

```
λ_eff,i = λ_tyre,i · λ_surface,i / λ_tyre_ref,i        for each scaling factor i
```

A tyre fitted on STJ-REF has `λ_tyre_ref = 1`. A gravel tyre fitted on gravel, put on gravel, gets the scaling it was fitted with, which is the correct result.

**Honesty clause.** This is exact only if grip separates into (tyre factor) × (surface factor). It does not. Compounds respond differently to microtexture (adhesion) and macrotexture (hysteresis), and on loose ground tread pattern matters far more than any scale factor: a slick and a gravel tyre on gravel are not related by a λ. So a surface may also give **per-tyre-class** values (`by_tyre_class`: `slick`, `road`, `wet`, `gravel`, `snow`, `studded`, `mud`). That is how RBR and rF2 organise it internally anyway: a tyre-type × surface table.

### 3.3 Surface object (draft)

```json
"surfaces": {
  "default": "grass",
  "library": {
    "asphalt": {
      "class": "asphalt",
      "mf_scaling": { "LMUX": 1.0, "LMUY": 1.0 },
      "rolling_resistance": 0.0,
      "roughness": { "iso8608": { "gd_n0": 4e-6, "w": 2.0 }, "mean_profile_depth": 0.0008 },
      "wet_response": [[0.0, 1.0], [0.0005, 0.85], [0.002, 0.65]],
      "track_limits": "inside"
    },
    "gravel_loose": {
      "class": "gravel",
      "mf_scaling": { "LMUX": 0.62, "LMUY": 0.58, "LKX": 0.5, "LKY": 0.6, "_est": true },
      "by_tyre_class": { "gravel": { "mf_scaling": { "LMUX": 0.75, "LMUY": 0.72 } } },
      "rolling_resistance": 0.03,
      "deformable": { "…": "§3.4" }
    }
  },
  "bindings": [ { "mesh_ref": "stage_collision", "material": "GravelFine", "surface": "gravel_loose" } ]
}
```

| Field | Unit | Meaning | Who can use it |
|---|---|---|---|
| `class` | enum | `asphalt`, `concrete`, `kerb`, `paint`, `cobbles`, `grass`, `dirt`, `gravel`, `sand`, `mud`, `snow`, `ice`, `rock`, `water`, `wall`, `other` | **Every engine.** In practice the most portable field: BeamNG `groundType`, ACR `PM_Surface*`, RBR material ids and AC keys all map from it. |
| `mf_scaling` | – | Any SVJ `pacejka.scaling` name, multiplied as in §3.2. `LMUX`/`LMUY` are the friction factors λμx/λμy. | MF tyres: all of it. TMeasy/brush/LUT tyres: only `LMUX`/`LMUY`, applied to peak and sliding μ. |
| `by_tyre_class` | – | Overrides of the fields above per tyre class | Engines with tyre-type tables (RBR, rF2) |
| `rolling_resistance` | – | Added to the tyre's own: `F = f · Fz` opposing motion. STJ-REF = 0. | All |
| `roughness.iso8608` | m³, – | ISO 8608 displacement PSD `Gd(n) = gd_n0 · (n/0.1)^(−w)` | Engines with road noise; lossy otherwise |
| `roughness.crg` | – | OpenCRG file + placement (deterministic, high-resolution) | Engines with CRG (pro tools); game converters bake it into the mesh |
| `roughness.mean_profile_depth` | m | Macrotexture, ISO 13473-1. Drives wet grip and drainage, not bumps. | Few |
| `wet_response` | m → factor | Multiplier on LMUX/LMUY versus water-film depth | All, roughly |
| `track_limits`, `pit_lane` | – | Flags (AC `IS_VALID_TRACK`, `IS_PITLANE`) | All |

Water **depth** is state and lives in `environment.weather`, so a wet override patches one value rather than every surface. The **response** (`wet_response`) is a property of the surface. Hydroplaning depends on tread depth, pressure and speed, which are tyre properties SVJ does not have yet: open question.

**Roughness portability.** Games expose vibration knobs, not road profiles: AC has `SIN_HEIGHT`/`SIN_LENGTH` and `VIBRATION_*`. ISO 8608 → one sinusoid throws away the spectrum. The reverse is a guess and gets marked `_est`.

### 3.4 Deformable surfaces (gravel, sand, snow, mud)

Two tiers, in the spirit of SVJ's multi-fidelity tyres:

**Tier A, effective.** Every engine can consume it; it is physically lossy.

| Field | Unit | Meaning |
|---|---|---|
| `mf_scaling` (above) | – | On loose ground: lower μ, lower slip stiffness (`LKX`, `LKY` < 1: the peak moves to larger slip), and a curve that keeps rising or stays flat past the peak (`LEX`/`LEY` towards 1) |
| `drag_coefficient` | s/m | Speed-dependent resistance `F = c · v · Fz` (ploughing, AC `DAMPING`-like) |
| `sinkage` | m | Static sinkage at reference load (ride height drop, visuals) |
| `loose_layer_depth` | m | Depth of loose material over a firm base |
| `base_surface` | id | What the tyre reaches through the loose layer (gravel on hardpack) |

**Tier B, terramechanics.** Physically portable, rarely used by games: Bekker–Wong pressure–sinkage `p = (k_c/b + k_φ) zⁿ` and Janosi–Hanamoto shear `τ = (c + σ tan φ)(1 − e^(−j/K))`.

| Field | Unit |
|---|---|
| `n` | – |
| `k_c` | N/m^(n+1) |
| `k_phi` | N/m^(n+2) |
| `cohesion` | Pa |
| `friction_angle` | rad |
| `shear_deformation_modulus` (K) | m |
| `bulk_density` | kg/m³ |

Published values exist for standard soils and snow (Wong, *Theory of Ground Vehicles*). Project Chrono SCM-type models consume them directly.

**What the spec will say plainly:**

- None of the consumer engines in scope (RBR/NGP, DR2, ACR, BeamNG, AC) publishes its loose-surface model, and each tunes its surface tables against its own tyres. **A Tier A value taken from game X encodes game X's tyre.** Putting it under game Y's tyre will not feel the same. STJ can carry the value with `_source` so nobody mistakes it for a measurement; it cannot make it portable.
- Tier B is portable, but no game reads it. Tier A cannot be derived from Tier B without a tyre model, which is the whole point of a tyre model. The best a converter can do is fit Tier A for one reference tyre and say so.
- Not portable in v0.1, with reserved keys only: rut formation and evolution, displaced material (berms), surface change during an event, rubbering, gravel dragged onto tarmac.

### 3.5 Binding surfaces to geometry

Precedence, highest first:

1. **glTF collision mesh, per primitive material → surface id.** Either the material is named `STJ::surface::<id>`, or an explicit `bindings[]` entry `{mesh_ref, material | node, surface}` covers meshes you would rather not rename (imported game meshes). Your ACR Stage Tools `collision.glb`, one primitive per surface material, is already this shape. AC (mesh-name prefixes `1ROAD`), RBR (per-triangle material ids) and BeamNG (`groundType` per material) all reduce to it.
2. **OpenDRIVE**: lane `<material surface="…">` names → surface id through a map.
3. **Reference-line bands** `{s_start, s_end, t_min, t_max, surface}`. These make a centreline-only file drivable.
4. `surfaces.default`.

### 3.6 SVJ tyre + STJ surface → grip (the recipe the spec will make normative)

1. Find the surface id at the contact point (§3.5).
2. If the surface has `by_tyre_class[<tyre class>]`, use those values; otherwise use the generic ones.
3. `λ_eff,i = λ_tyre,i · λ_surface,i / λ_tyre_ref,i` for every λ the surface gives (§3.2).
4. `LMUX`, `LMUY` ×= `wet_response(water_depth)`.
5. Evaluate SVJ §11.13 with `λ_eff`. Add `−(rolling_resistance + drag_coefficient · v) · Fz` against the direction of motion, on top of the tyre's own `My`.
6. Non-MF tyre models use only the μ factors.
7. An engine with a soil model uses Tier B for that contact instead of steps 3–5. Every other engine uses Tier A.

---

## 4. Decisions needed before the schema

1. **World frame**: Z-up OpenDRIVE inertial frame (recommended), or an SAE-style Z-down earth frame?
2. **Where the tyre's reference surface lives**: an additive SVJ field (`tires.sets.<id>.reference.surface` + `tyre_class`, SVJ v0.105, recommended), or STJ-only with the assumption that every tyre is fitted for STJ-REF?
3. **Grip combination**: multiplicative λ plus an optional per-tyre-class table (recommended), λ only, or table only?
4. **Deformable surfaces in v0.1**: Tier A + Tier B (recommended), or Tier A only, with Tier B reserved?

Smaller choices I will make unless told otherwise:

- Poses locate the SVJ origin (§2.4).
- Surfaces bind through glTF materials (§3.5).
- Versions start at `0.1`.
- Reverse and alternate layouts are override files.
- Reserved top-level keys: `dynamic` (rubber, ruts), `animated_objects`, `marshals`, `cameras`.
