# STJ proposal: visual materials, ground masks, decals and instancing

Status: **accepted** 2026-11-05 with the recommended answers of §6. **Implemented** 2026-11-05 in v0.3 (draft): all of it. §3.1 material profile (spec §7.7), §3.2 ground, §3.3 `decal` role (§7.2), §3.4 `materials[]` (§11.1), §3.5 prototype LODs and `cull_distance` (§8.2), and the editorial cleanup of §4. The instance primvars (`instance_set.usd.primvars[]`) were decided on 2026-11-06 and added: `{name, role}` with the roles `tint`, `age`, `scale_jitter`, `phase`, `other`.

Source: an audit of the Dirt2 Stage Importer 0.11.0 STJ export against what DiRT Rally 2.0 stores, what the Blender scene shows, and what OpenUSD can carry (a real stage, Australia `australia_rally_01_route_5`). This is a condensed record: the original text was written in the `blender_acr_exporter` repository and was not available when this copy was made, so it restates each section rather than quoting it.

## Decisions

| Q | Decision |
|---|---|
| Q1 | The material profile (§3.1) is **normative for the core, SHOULD for the rest**: every visual material has a UsdPreviewSurface fallback and cards set `doubleSided` (validator errors); connecting every source map, with declared colour spaces, is a SHOULD (warnings and a per-material NOTE). |
| Q2 | The mask blend is a **separate `method`** (done, spec §8.7). Provisional until fitted to an engine. |
| Q3 | Signal-driven materials are a **top-level `materials[]`** `{material, input, by}`. |
| Q4 | Prototype LODs **reuse the mesh `lod` shape** (`lods[] {prim, level, switch_distance}` plus `cull_distance`), shared with item 7 of `stj_rbr_gaps_proposal.md`. |
| Decals | A **mesh role `decal`** first. Spline-projected paint (editor-style decal roads) is a separate later proposal. |
| Instance primvars (§3.5) | **Yes (2026-11-06):** `usd.primvars[] {name, role}` on the instance set, so engines can map tint, age, scale jitter and phase to their per-instance data. |
| Road paint (decal roads) | **A separate proposal, later (2026-11-06),** when a converter needs spline-projected paint. The `decal` mesh role covers paint as meshes meanwhile. |
| Trigger volumes | **Stay in `x_<engine>` (2026-11-06).** The portable cases are restricted zones, marshal sectors and track-limit rules; script triggers are game logic, which the spec excludes. |
| Keeping ground blends (2026-11-06) | **A writer plus a cache stamp.** `ground.materials[].fallback` marks a baked image as a cache of the `ground` recipe (hash, stale check), and `tools/ground_materialx.py` writes the recipe as a MaterialX network so Blender and USD viewers show the real layers. MaterialX stays optional and derived: the recipe is the source of truth, and UsdPreviewSurface stays the required baseline. |
| Editorial (§4) | Clean up the leftover glTF and `.stj.json` wording in the spec **now**. |

## 1. The gap

STJ leaves rendering materials to USD, which already has UsdPreviewSurface and MaterialX. The spec never says which USD material features a track can rely on, and four things have no place:

1. **What a material must carry.** A converter can write a diffuse-only material and the track validates, so a renderer cannot tell "no normal map" from "the converter dropped it".
2. **Mask-driven ground blends.** DR2's commonest terrain shaders, and UE and Unity terrain shaders, blend layers through a tiling mask. §8.7 had only a height blend and a linear blend.
3. **Decals.** Tyre marks, road paint, oil and dirt patches are meshes drawn on top of another mesh and need special treatment (draw order, no shadows, depth offset).
4. **Materials that react to state.** Lights follow signals; emissive windows at night and ground that darkens when wet have no way to.

Instancing also lacks prototype LODs and a cull distance.

## 2. What DR2 stores (Australia)

| DR2 shader group | Textures | In the first STJ export |
|---|---|---|
| `object_norm` (176 materials) | diffuse+alpha, normal, specular, occlusion | diffuse only |
| `Object_NormEmis`, `object_emis`, `Object_EmisBlend` (45) | plus emissive | diffuse only |
| `foliage*`, `facing_foliage`, `foliage_billboard` (70) | diffuse+alpha cutout, normal | diffuse + cutout, single-sided |
| `object_2sided_normalpha` | the same, two-sided | single-sided |
| `decal_ao_vc` (30) | diffuse+alpha, normal, specular, AO; opacity × vertex alpha | texture alpha only |
| `terrain_road`, `terrain_wsm_*` (252) | 3 diffuse+spec layers, 3 normals, 2 blend masks, AO, colour map, wet mask | 2 layers, linear blend; no normals, masks or wet mask |
| `terrain_track_vista_d4` | 3 layers + large colour, normal and blend maps | colour only |

## 3. Proposed additions

### 3.1 A visual material profile for USD tracks (spec §7.7), accepted, not implemented

Every material bound to a `visual` mesh:
- **MUST** have a UsdPreviewSurface on its default `outputs:surface`, the one material model every USD reader shares.
- **SHOULD** connect every map the source has: colour → `diffuseColor` (sRGB); tangent-space normal → `normal` through a UsdUVTexture with scale (2,2,2,1), bias (−1,−1,−1,0), raw colour space; roughness (gloss → 1 − gloss) → `roughness`; specular colour → `specularColor` with `useSpecularWorkflow = 1`; metalness → `metallic`; occlusion → `occlusion`; emissive → `emissiveColor`; alpha → `opacity`, with `opacityThreshold` for cutouts (0.5 when the source gives none).
- **MAY** add a MaterialX network on `outputs:mtlx:surface` for what UsdPreviewSurface cannot do (layer blends, primvar reads, vertex-alpha decals).
- Colour spaces are declared on every texture. A mesh whose material is a card (foliage, flag, billboard, sign seen from both sides) sets `doubleSided = true`. `x_<engine>.shader` on the material's `customData` names the source shader.

**Validator:** ERROR for a visual material with no `outputs:surface`; WARN for a texture with no colour space and for a cutout opacity without `opacityThreshold`; NOTE per material listing the maps it carries (for example `diffuse+normal+roughness`).

### 3.2 Ground (spec §8.7), **implemented**

Layer alpha meaning (`albedo.alpha`), per-layer `roughness` and `occlusion`, `blend.method: "mask"` with `blend.mask` and `softness`, and a `wetness` macro kind. See the spec and the CHANGELOG (0.3 draft). DR2's exact mask formula is not public and still needs fitting against DR2's pre-baked colours (`terrain_lod`).

### 3.3 Decals (spec §7.2), accepted, not implemented

A new mesh role `decal`: a visual mesh drawn after opaque geometry, without casting shadows, with a small depth offset. Its opacity is the material's `opacity` times an optional vertex primvar:

```json
{ "id": "road_decals", "uri": "stage_geometry.usdc", "roles": ["decal"],
  "decal": { "on": "terrain", "opacity_primvar": "displayOpacity", "depth_offset": 0.02 } }
```

`displayOpacity` is USD's own primvar for this. A MaterialX network multiplies it with the texture alpha; readers without MaterialX use the texture alpha alone.

### 3.4 Materials that follow signals (spec §11.1), accepted, not implemented

A top-level `materials[]` drives named inputs of USD materials the way lights already follow signals:

```json
"materials": [
  { "material": "Hut_windows", "input": "emissive_scale", "by": { "signal": "sun_elevation", "curve": [[-0.1, 1], [0.05, 0]] } },
  { "material": "Terrain_Sec03", "input": "wet_amount", "by": { "signal": "wetness", "curve": [[0, 0], [1, 1]] } }
]
```

`input` names a material interface input (`inputs:emissive_scale` on the UsdShade.Material) that the material's networks read, so a USD tool can also change it by hand. `by` is the existing `binding` definition. The validator checks the input exists on that material.

### 3.5 Instancing (spec §8.2), accepted, not implemented

- Prototype LODs reuse the mesh `lod` shape: `prototype.lods[] {prim, level, switch_distance}` (decided under Q4).
- `prototype.cull_distance` and `instance_set.cull_distance` (m): beyond it the object is not drawn.
- `instance_set.usd.primvars[]`: names of per-instance primvars on the PointInstancer that carry variation (tint, age).
- The spec text still describes glTF instancing (`gltf {mesh_ref, node}`, `EXT_mesh_gpu_instancing`); it should say PointInstancer.

## 4. Editorial: glTF left in the published spec (decided: clean up now)

The schema and tools are OpenUSD-only, but the spec text still says glTF or `.stj.json` in §1, §3.1, §3.4, §3.6 (`material_variant` and `KHR_materials_variants`), §4.1 (light units "follow glTF `KHR_lights_punctual`"), §4.5, §7.7 ("glTF is the lean delivery form" and the table), §8.2 (`gltf {mesh_ref, node}`, `EXT_mesh_gpu_instancing`, `_SWAY`, `mesh_attribute`) and §8.7 (`_STJ_LAYERS` / `_STJ_WEIGHTS`).

## 5. Not STJ gaps: converter fixes in the Dirt2 Stage Importer

These need no change to STJ; the exporter does not use what DR2 has:
1. Foliage, flags and two-sided objects are written single-sided (`doubleSided` never set).
2. Decal opacity loses the vertex alpha.
3. Object normal, specular, occlusion and emissive maps are not used.
4. Ground layer normal maps are not used (`ground.layers.*.normal` is empty).
5. The third layer and second mask of `terrain_road` / `terrain_wsm_*` are ignored.
6. The wet mask and the vista's large colour, normal and blend maps are ignored.
7. The ground group's colour map and lightmap sliders become constants in MaterialX instead of material inputs, and MaterialX roughness is fixed at 0.9.

## 6. Questions and their answers

- **Q1.** Normative or recommendation? **Normative core (fallback surface and `doubleSided`), SHOULD for the rest.**
- **Q2.** Mask blend as a third method or a generalisation of the height blend? **A separate method** (implemented).
- **Q3.** Signal-driven materials as top-level `materials[]` or a key on `surface_binding`? **Top-level.**
- **Q4.** Prototype LODs in STJ or in USD only? **In STJ, reusing the mesh `lod` shape** (a change from the original recommendation of a USD variant set plus `switch_distance`).
