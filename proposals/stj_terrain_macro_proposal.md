# STJ proposal: macro maps on a heightfield terrain

Status: **accepted** 2026-11-05 with the recommended answers of §8 (D1 `geometry.terrain.macro[]`, D2 the `colour` encoding, D3 optional extent, D4 core first, engine converters after). Proposed 2026-11-04; the reference implementation (schema, validator, `stj_core`, the baker, spec text, an example and tests) was merged on that basis.

Source: converting three WRC Generations stages (a 2.2 km shakedown, a 1 km arena stage and a 4.9 km mountain stage) with a WRCG to STJ converter that reads the files the user's own export tool wrote. Every number in §2 was measured on those exports.

---

## 1. The gap

Spec §8.7 gives layered ground a **macro** map: a large, low-resolution image that sits on top of the repeating detail layers so the repetition does not show. It lives in `ground.materials[].macro`, and `ground.materials[]` names a **mesh material** (`mesh_ref` + `material`).

A heightfield terrain (`geometry.terrain`, spec §7.4) has no mesh and no material. Since v0.2 its layers may name a ground layer (`ground_layer`, §7.4), so the detail layers and their weights are covered. The macro is not: there is nowhere to put it.

WRC Generations draws its terrain as a heightfield, with up to 16 detail layers (14 used on the shakedown, 16 on the mountain stage), an image of weights per layer and **one colour map over the whole terrain**. The converter carries the heights, the layers, the weights and the detail textures. The colour map is the one piece it has to drop:

> terrain colour_macro map (STJ has no macro slot on a heightfield terrain)

Unity and UE heightfield terrains, BeamNG's `TerrainBlock` and Rigs of Rods are the other engines named in §7.4 as native to heightfields. The same gap applies to them.

## 2. What the data says

The three exports carry a colour map named `color_macro`, built by the export tool from the terrain tiles' colour blocks (BC1) and resampled to 0.5 m per pixel, north-up, over the same square window as the heights.

| Stage | Map | Window | File | Cropped to the converted terrain, 1 m per pixel | Mean colour (whole map) |
|---|---|---|---|---|---|
| Shakedown, 2.2 km | 4096 × 4096 | 2048 m | 24.5 MB | 1014 × 1700, **3.4 MB** | (153, 117, 82) |
| Arena stage, 1.0 km | 2048 × 2048 | 1024 m | 5.4 MB | 634 × 701, **0.8 MB** | (114, 100, 75) |
| Mountain stage, 4.9 km | 8192 × 8192 | 4096 m | 88.5 MB | 3846 × 1612, **11.8 MB** | (88, 83, 60) |

What it is, and what it is not:
- **A full colour map, not a grey-centred one.** Warm earth tones; no pixel within 8 levels of neutral grey 128 on all channels (0.000 of the pixels on every stage). The existing `grey_centred` encoding ("0.5 changes nothing") does not describe it.
- **Not derived from the detail layers.** Correlation with the weighted mean colour of the layers under each texel is 0.01 to 0.05 per channel (200 000 random texels, measured on the shakedown and the arena stage; the mountain stage was not measured). It is an independent, low-frequency colour field.
- **Same brightness scale as the layers.** The ratio of the map's mean colour to the weighted mean albedo of the layers is 1.34 / 1.17 / 1.03 (shakedown) and 1.13 / 1.15 / 1.09 (arena). The map's own mean is 0.46 (shakedown) and 0.38 (arena) of full scale, so multiplying the detail by it (`multiply`) would darken the ground to about half.

What the data does **not** say: how the game combines the map with the detail layers. Its shader is not public and the numbers above fit more than one reading (a tint, a colour correction, a blend). §3 therefore proposes a definition STJ can state exactly, and §6 says plainly that it is not the game's.

## 3. Proposed shape

`geometry.terrain.macro[]`, an array of maps over the terrain's heightmap grid. The items have the keys of `ground.materials[].macro` (§8.7), minus `texcoord` (a heightfield has no UVs), plus one encoding and one parameter.

```json
"terrain": {
  "heightmap": { "uri": "terrain/height.png", "format": "png16", "size": [1015, 1701],
                 "extent": [391.0, 160.0, 1405.0, 1860.0], "height_min": 110.19, "height_max": 330.9 },
  "layers": [ { "id": "l00_gravel_dry_grass", "surface": "grass", "ground_layer": "l00_gravel_dry_grass" }, "…" ],
  "macro": [
    { "kind": "tint", "uri": "terrain/macro_colour.png", "encoding": "colour", "strength": 1.0,
      "extent": [391.0, 160.0, 1405.0, 1860.0] }
  ]
}
```

| Key | Meaning |
|---|---|
| `kind` | `tint`, `occlusion` or `other`, as in §8.7 |
| `uri` | The image. Same raster rules as every STJ raster over an extent (§7.4): sampled bilinearly, **row 0 is the +Y (north) edge** |
| `extent` | `[x_min, y_min, x_max, y_max]` in metres the image covers. **Default: the heightmap's extent**, so a converter that crops to the terrain writes no extent |
| `encoding` | `grey_centred` (default) and `multiply`, unchanged from §8.7, plus the new **`colour`** |
| `strength` | `colour` only, 0 to 1, default 1 |

### 3.1 The `colour` encoding

An sRGB image that gives the **average colour of the ground** at each point. The detail layers keep their texture; the map replaces their average colour.

With the layers present at a point (weights `w_i`, mean colours `mean_i` as the reference blend already uses them, §8.7), all in linear light:

```
base   = Σ w_i · mean_i                          the layers' own average colour
ratio  = clamp(macro / max(base, ε), 0.25, 4)    per channel
final  = detail · (1 + strength · (ratio − 1))
```

- `strength` 0 leaves the detail alone; 1 makes the average colour of the result equal the map's.
- The clamp keeps a near-black layer from blowing up.
- A terrain with a macro but no ground layers (only a base colour) uses the base colour as `base`.
- Several maps apply one after the other, in order. A file with two `colour` maps gets a validator WARN.

`kind: tint` is the right kind for it: it tints the ground. `grey_centred` and `multiply` keep their meaning, so a DR2-style `TColourMap` still goes in as before.

### 3.2 Where it applies

The terrain's final detail colour, after the layer blend. Road meshes keep their own `ground.materials[]` and macros. The terrain collision is untouched.

## 4. Conversions

| From / to | How |
|---|---|
| **WRCG export → STJ** | Crop `color_macro` to the converted terrain's extent, resample to 1 m per pixel (box filter), write `terrain/macro_colour.png`, `kind: tint`, `encoding: colour`. The export's file and pixel size go in `x_wrcg`. |
| **DR2 → STJ** | Unchanged: `TColourMap` is a grey-centred tint on the section atlas, so it stays in `ground.materials[].macro`. |
| **STJ → BeamNG** | A terrain material has a macro texture with its own scale and strength *(m: field names `macroBaseTex`, `macroSize`, `macroStrength` to verify)*. `colour` needs the layers' mean colours, which a converter can bake into the material's tint. |
| **STJ → UE** | Landscape materials commonly multiply a world-space texture into the base colour (material-defined). `colour` becomes a ratio texture computed once. |
| **STJ → Unity** | Terrain layers have no macro; the usual route is a global colour map in a shader. Otherwise bake the ratio into the splatmap-driven layer colours. |
| **STJ → Blender** | A packed image `STJ::terrain::macro` and a node in the terrain material. The exporter writes the image back byte for byte, as it already does for the heightmap and the layer weights. |
| **STJ → AC (CSP), RBR, Speed Dreams** | Bake into the ground texture. |

## 5. Validation (validator additions)

- Each `terrain.macro[].uri` exists (WARN, like the other ground files).
- `extent`, when given, overlaps the heightmap extent; WARN if it covers less than 90 % of it (parts of the terrain would have no macro).
- The image is at least 2 × 2 and 8-bit RGB or RGBA for `colour` (WARN for greyscale: a colour map is expected).
- `strength` in 0…1 (the schema already enforces it).
- More than one `colour` map on a terrain: WARN.
- `colour` or `multiply` on a terrain with no ground layers: NOTE (it will tint the base colour only).
- A macro on a terrain whose `collision` is true changes nothing for physics: no check.

## 6. Where portability is a lie (spec §14 additions)

1. **The formula.** How the game combines its colour map with the detail layers is unknown. `colour` is a definition chosen so that the result is well-behaved and exactly reproducible, in the spirit of the reference blend (§8.7): in the original it will look similar, not identical. If the game's shader turns out to be a plain grey-centred tint, a converter switches `encoding` and the schema does not change.
2. **Resolution.** 0.5 m per pixel in the game, 1 m in the converted file. A macro is low-frequency, so little is lost, but it is a choice the converter makes.
3. **The art.** The map is the game's data, made from its terrain tiles. A converted file is `redistributable: false`; the image sits next to the file and is not meant to be shared.

## 7. Implementation plan

1. **STJ core** (this repository):
   - schema: `terrain.macro[]` and the `colour` encoding and `strength` (Appendix A; also on `ground.materials[].macro`, so both places mean the same)
   - validator: the checks of §5
   - `stj_core.apply_macro()` takes the layers' mean colour for `colour`
   - spec: §7.4 (a sentence and the key table) and §8.7 (the encoding)
   - an example: add a generated colour map to the gravel stage's terrain
   - tests and a CHANGELOG line
   - `docs/blender_mapping.md`: one row for `STJ::terrain::macro`
2. **WRCG converter** (outside this repository): write the map as in §4. The converter already writes the layers, the weights, the holes and the ground textures.
3. **Blender exporter** of the same converter: carry the macro image like the weight maps.

## 8. Decisions

**D1. Location.** Recommendation: **`geometry.terrain.macro[]`**, next to the heightmap whose grid and extent it follows. Alternatives:
- `ground.materials[]` with a `terrain` target instead of `mesh_ref`: it repeats the palette and weights the terrain layers already carry.
- a separate `ground.terrain_macro`: the extent rules would live away from the terrain they describe.

**D2. Encodings.** Recommendation: **add `colour`** (§3.1). The measured map is a full colour map, so forcing it into `grey_centred` states the wrong maths, and `multiply` darkens the ground to about half (§2). Alternative: only the two existing encodings and let converters rescale the map: lossy and not reversible.

**D3. Extent.** Recommendation: **optional, defaulting to the heightmap's**. Alternative: required: every file would repeat a number it already has.

**D4. Scope now.** Recommendation: step 1 now (schema, validator, reference function, example), step 2 once it is accepted. Engine converters follow.

---

## Appendix A. The schema change

Added to `definitions` (and the two edits to existing definitions listed after it):

```json
"terrain_macro": {
  "type": "object",
  "description": "A low-resolution map over the whole heightfield (spec 7.4): tint, occlusion or an absolute colour.",
  "required": ["kind", "uri"],
  "additionalProperties": false,
  "patternProperties": { "^x_": {}, "^_": {} },
  "properties": {
    "kind": { "type": "string", "enum": ["tint", "occlusion", "other"] },
    "uri": { "$ref": "#/definitions/relative_uri" },
    "extent": { "$ref": "#/definitions/extent",
                "description": "[x_min, y_min, x_max, y_max] (m) the image covers; default: the heightmap's extent." },
    "encoding": { "type": "string", "enum": ["grey_centred", "multiply", "colour"], "default": "grey_centred" },
    "strength": { "type": "number", "minimum": 0, "maximum": 1, "default": 1 }
  }
}
```

- `definitions.terrain.properties.macro`: `{ "type": "array", "items": { "$ref": "#/definitions/terrain_macro" } }`
- `definitions.ground_material.properties.macro.items.properties.encoding.enum`: `["grey_centred", "multiply", "colour"]`, and a `strength` property as above.

### Tried on copies

The patch was applied to a **copy** of the schema (the repository was not touched) and a real converted package of the arena stage was validated with `tools/validate.py --strict`, with the real colour map cropped to its terrain and added:

| Schema | Package | Result |
|---|---|---|
| current | with `terrain.macro` | exit 1: `geometry.terrain: 'macro' does not match any of the regexes: '^_', '^x_'` |
| proposed | with `terrain.macro` (`colour`, explicit extent) | exit 0, no warnings |
| proposed | `encoding: "bogus"`, `strength: 2` | exit 1, two errors, one for each |
| proposed | extent omitted, `grey_centred` | exit 0, no warnings |

That trial covered the schema only. The §5 checks, the version check, `apply_macro`, `tools/ground_bake.py`, the spec text and an example were implemented afterwards and are covered by `tests/test_validate.py`.

## Appendix B. The example from the arena stage

```json
"macro": [ {
  "kind": "tint", "uri": "terrain/macro_colour.png", "encoding": "colour",
  "extent": [-354.0, -302.0, 280.0, 399.0],
  "x_wrcg": { "source": "terrain/color_macro.png", "px_m": 0.5, "resampled_to_m": 1.0 }
} ]
```
