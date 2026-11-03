# STJ proposal: layered ground materials

Status: **accepted** 2026-11-02, with the four recommended answers in §8: four weight encodings, a normative reference blend, a top-level `ground` block, and the STJ core first. Implemented in v0.2 (draft), spec §8.7.

Source: an analysis of how DiRT Rally 2.0 shades its ground, done for ACR Stage Tools 0.4.0 (not published), which builds on the format notes of the open [acr-extrastages](https://github.com/cherrymcgerry/acr-extrastages) project (`docs/dr2-formats.md` §5.1).

---

## 1. The gap

Almost every engine draws the ground the same way:
1. a few small **detail layers** that repeat (gravel, grass, rock): colour, normal, height
2. **weights** that say where each layer goes
3. a **blend**, usually height-based, so stones show through grass before the grass fades
4. a large, low-resolution **macro** tint and occlusion map on top, so the repetition does not show

glTF 2.0 cannot express this: a glTF material has one base colour. STJ v0.2 only touches it in `geometry.terrain.layers`, and only for heightfields, with image weight maps.

A rally stage is a **mesh corridor**, not a heightfield, and DR2 keeps its weights **on the vertices**. Today a converter can only **bake** the ground into images. Baking loses sharpness (0.5 m/px, or 5 cm/px next to the road), produces huge files, and throws away the layers that BeamNG, UE, Unity and AC (with CSP) could rebuild natively.

That breaks principle 7 (spec §2): describe it semantically, and carry the native form alongside.

## 2. What the engines share

| | Layers | Where the weights live | Blend | Macro |
|---|---|---|---|---|
| **DR2** | 17-slice texture array; alpha = height | **Vertices**: 3 layers per triangle (`COLOR_0`, `slice·8+3`), weights in `ST1.zw` | Height-based (formula not public) | `TColourMap` ×2 and lightmap ×2, grey-centred, on the section atlas UV |
| **Unity** Terrain | TerrainLayer: diffuse, normal, mask (height), `tileSize` | Splatmaps, RGBA = 4 layers per image | Height-based blend (HDRP) | – |
| **Unreal** Landscape | Landscape layers | One weightmap per layer | `LandscapeLayerBlend` with `LB_HeightBlend` | Material-defined |
| **BeamNG** TerrainBlock | Terrain materials: base, detail, macro | Layer map: **one material per texel** | Height-based at borders | Macro texture per material |
| **AC + CSP** | `ksMultilayer` shaders *(m)* | RGBA mask per object: 4 detail layers *(m)* | Linear *(m)* | – |

The concepts are the same everywhere. What differs is the **weight encoding**: per-vertex top-3, per-vertex dense, image per layer, RGBA image per 4 layers, or one id per texel. STJ should name the concept once and allow the encodings that carry information losslessly.

## 3. Proposed shape

A new top-level `ground` block. It is shared by mesh materials and by `geometry.terrain`.

```json
"ground": {
  "layers": {
    "gravel_fine": {
      "albedo": { "uri": "ground/gravel_fine.png", "height_in_alpha": true },
      "normal": { "uri": "ground/gravel_fine_n.png" },
      "tile": 8.0,
      "projection": "world_xy",
      "height_contrast": 1.0,
      "surface": "gravel_loose",
      "x_dr2": { "slice": 4, "slot": 7 }
    },
    "verge_grass": {
      "albedo": { "uri": "ground/grass.png", "height_in_alpha": true },
      "tile": 8.0, "projection": { "texcoord": 1, "scale": 1.0 }, "height_contrast": 3.0
    }
  },
  "materials": [ {
    "mesh_ref": "stage_terrain", "material": "Terrain_Sec03",
    "palette": ["gravel_fine", "verge_grass", "rock_face"],
    "weights": { "encoding": "vertex_top3", "indices": "_STJ_LAYERS", "weights": "_STJ_WEIGHTS" },
    "blend": { "method": "height", "height_influence": 0.5, "depth": 0.2 },
    "macro": [
      { "kind": "tint", "uri": "ground/sec03_colour.png", "texcoord": 0, "encoding": "grey_centred" },
      { "kind": "occlusion", "uri": "ground/sec03_ao.png", "texcoord": 0, "encoding": "grey_centred" }
    ]
  } ]
}
```

### 3.1 Layers

| Key | Meaning |
|---|---|
| `albedo {uri, height_in_alpha}` | Colour (sRGB). With `height_in_alpha`, the alpha channel is the layer's height (DR2, many terrain packs). |
| `normal`, `height` | Optional; `height` when it is not in the alpha |
| `tile` | Metres per texture repeat. DR2 `WorldUVScale` 0.125 = 8 m. |
| `projection` | Where the UVs come from: <ul><li>`world_xy`: top-down; u = x/tile, v = y/tile</li><li>`road`: along the reference line; u = t/tile, v = s/tile. Computable by any converter, because STJ has the line.</li><li>`{texcoord, scale}`: a UV set already in the glTF (DR2's own road UVs)</li></ul> |
| `height_contrast` | How strongly the height pushes in the blend (DR2 `Thickness`) |
| `surface` | Optional physics surface. Where set, a contact uses the dominant layer, as for terrain (spec §7.4). |

### 3.2 Weight encodings

| `encoding` | Storage | Lossless for | Notes |
|---|---|---|---|
| `vertex_top3` | glTF `_STJ_LAYERS` (VEC3, palette indices, constant over a triangle) and `_STJ_WEIGHTS` (VEC2 wa, wb; wc = 1 − wa − wb) | DR2 | Triangles with different layer sets do not share vertices, as in DR2 |
| `vertex_dense` | `_STJ_WEIGHTS_0…n` (VEC4, 4 palette entries each) | Vertex-painted meshes | Simple, heavy beyond 8 layers |
| `image` | `maps[] {uri, channels}` on a `texcoord` or over an `extent` | Unity splatmaps, UE weightmaps, CSP masks, STJ terrain | Today's `terrain.layers[].weight` is the one-layer-per-map case |
| `id_map` | One palette index per texel over an `extent` | BeamNG layer maps | Lossy from every other encoding |

Converters move between encodings:
- top-3 → dense or images by rasterising
- images → top-3 by keeping the 3 strongest layers per triangle
- anything → `id_map` by taking the argmax

Custom glTF attributes start with `_`, which Blender's exporter keeps (verified for POINT attributes). Blender's exporter **drops face attributes** (verified). ACR's `dr2_layers` face attribute therefore has to be written per vertex by the STJ exporter, with vertices split where the layer sets change.

### 3.3 Blend

STJ fixes a **reference blend**: the one ACR's bake and node group use, not DR2's own, which is not public.

```
score_i = w_i + (h_i − mean(h_i)) · height_influence · height_contrast_i
m_i     = max(score_i − (max_j score_j − depth), 0)
detail  = Σ colour_i · m_i / Σ m_i
```

- `method: linear` gives `detail = Σ colour_i · w_i`.
- The defaults are `height_influence` 0.5 and `depth` 0.2, fitted by eye.
- `mean(h_i)` is the mean height of layer i's texture, which a converter computes once.

### 3.4 Macro

`final = detail × Π (2 · macro_k)` for `grey_centred` maps, which are linear data where 0.5 changes nothing. `kind` is `tint`, `occlusion`, or another kind; `multiply` encoding is also allowed. Each macro map uses its own `texcoord`: DR2's section atlas is UV 0.

### 3.5 Fallback

The glTF material keeps a plain base colour: a bake, or just the tint. Viewers that ignore STJ still show something sensible. Converters that understand `ground` ignore the base colour.

### 3.6 Terrain

`geometry.terrain.layers[]` may name a `ground` layer (`"ground_layer": "gravel_fine"`) instead of `material` + `tile`. Its weight maps are then the `image` encoding. v0.2 files stay valid.

## 4. Conversions

| From / to | How |
|---|---|
| **DR2 via ACR dr2-extract 0.4 → STJ** | Each mapping is lossless except as noted:<ul><li>`COLOR_0` bytes → `_STJ_LAYERS` = (byte − 3)/8</li><li>`TEXCOORD_3` → `_STJ_WEIGHTS`</li><li>`DifUV = 0` → `{texcoord: 1, scale: 8}`, because the road UV × 8 is metres (ACR uses road UV × WorldUVScale/0.125); `DifUV = 1` → `world_xy`. Both take `tile = 1/WorldUVScale`. DR2 XZ is STJ x, −y, so v flips.</li><li>`Thickness` → `height_contrast`</li><li>`_sliceN.dds` → layers with `height_in_alpha`</li><li>`TColourMap` → macro tint, `TAmbientOcclusion` → macro occlusion (UV 0)</li><li>`TNormal` → layer normals, when extracted</li><li>`TWetMask`, `TSkidMap` → `x_dr2`</li></ul> |
| **STJ → Blender** | Generalise ACR's node group (`DR2 terrain <material>`) to read `ground` instead of DR2 constants. It already implements the same maths. |
| **STJ → BeamNG** | <ul><li>Now: baked tiles (ACR's current path).</li><li>Better: rasterise the corridor into `geometry.terrain`, `id_map` = argmax, `ground` layers → TerrainMaterials (detail = albedo, macro = tint, height blending), physics from `surface`.</li></ul> |
| **STJ → UE** | Heightfield: Landscape layers + `LB_HeightBlend`, using `height_contrast`. Meshes: a vertex-weight material from `vertex_dense`. |
| **STJ → Unity** | TerrainLayer per `ground` layer (diffuse, normal, mask with height, `tileSize` = `tile`); splatmaps from `image` / rasterised weights |
| **STJ → AC (CSP)** | Per chunk, keep the 4 most-used layers, bake an RGBA mask, use a multilayer shader *(m: shader names and parameters to verify)* |
| **STJ → RBR, Speed Dreams** | Bake |

## 5. Validation (validator additions)

- Layer textures exist.
- `projection.texcoord` and macro `texcoord` exist on the bound glTF primitives.
- `_STJ_LAYERS` and `_STJ_WEIGHTS` exist, indices < palette length, and weights are in 0…1 with `wa + wb` ≤ 1.
- Palette ids exist.
- `tile` > 0, and below 0.05 m or above 1 km gets a WARN (scale given instead of metres?).
- Image weight maps have enough channels for the palette.
- Layer surfaces exist.

## 6. Where portability is a lie (spec §14 additions)

1. **The blend.** DR2's real formula is unknown, and UE, Unity and BeamNG each have their own height blend. The STJ reference blend is close to DR2's, not equal to it. In another engine it looks similar, not identical.
2. **Encodings.** Top-3 per triangle to one id per texel (BeamNG) loses the soft transitions. The reverse invents them.
3. **The art.** Detail textures taken from a game are that game's art. A converted ground is `redistributable: false`; STJ stores the recipe and paths to the user's local files and never embeds them.

## 7. Implementation plan

1. **STJ core** (this repository):
   - schema `ground`, plus `terrain.layers[].ground_layer`
   - validator checks (§5)
   - `stj_core.ground_colour()` as the reference blend
   - an example: a synthetic corridor with generated detail textures (height in alpha), `vertex_top3` weights and a tint map
   - tests, spec section, Blender mapping rows
2. **ACR adapter**: DR2 extract → STJ `ground`. This is part of converter-plan step 0 (ACR IR → STJ).
3. **Blender**: generalise ACR's node group to STJ. Add a probe check: are FACE_CORNER attributes exported, and are `_` VEC3 attributes kept with split vertices?
4. **BeamNG TerrainBlock path** (later): rasterise to heightfield + `id_map`.

## 8. Decisions

**D1. Weight encodings.** Recommendation: **allow the four encodings** (§3.2), so DR2, Unity/UE and BeamNG each go in losslessly. Alternatives:
- images only: every converter bakes per-vertex weights to images, which is lossy for DR2 and needs a UV layout
- per-vertex only: Unity, UE and BeamNG imports must rasterise backwards

**D2. Blend.** Recommendation: a **normative reference blend** with its parameters (§3.3), so a Blender preview and a BeamNG export agree. Alternative: only a hint (`method: height`) and each engine uses its own.

**D3. Location.** Recommendation: a top-level **`ground`** block in the STJ file. Alternative: a custom glTF extension (`STJ_materials_layered`) inside the `.glb`. That keeps the recipe with the mesh, but Blender's exporter cannot write it without a plugin, and the JSON is hidden from people.

**D4. Scope now.** Recommendation: step 1 (STJ core) now, step 2 (ACR adapter) next. Steps 3–4 follow.
