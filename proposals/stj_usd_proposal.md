# STJ proposal: OpenUSD as the rich container

Status: **accepted** 2026-11-03, with the recommended answers in §7:
- D1: L1 + L2a now; L2b schemas later
- D2: the STJ JSON is normative
- D3: variants may select USD variant sets
- D4: `pxr` is optional in the validator

Implemented 2026-11-03 in v0.3 (draft): spec §3.4, §3.6, §5.2, §7.7, §7.8; `tools/stj_usd.py`; the validator; `examples/`. Implementation found three things that change §3–§4:
1. **USD primvar names use an `stj_` prefix, not the `stj:` namespace.** Blender drops per-corner attributes with `:` in the name.
2. **Per-face layers may also be three int primvars.** Blender has no int3 attribute.
3. **A `.usdz` may hold only USD layers, images and audio,** so override files inside a package are USD layers. They carry the STJ-OVERRIDE in their own metadata and select the USD variants themselves.

Source: the OpenUSD probe in Blender 5.2 / OpenUSD 0.26.3 (`docs/blender_mapping.md` §4, `tools/blender/usd_probe.py`), and open questions Q12 (single-file delivery) and Q23 (USD).

---

## 1. Why

STJ uses glTF 2.0 for geometry. glTF is a lean delivery format, and much of what a track is falls outside it:
- per-face data
- curves
- procedural materials
- physics
- audio
- variants
- streaming

STJ invented JSON for each of those. The probe showed that OpenUSD carries all of them natively, is an open standard (Alliance for OpenUSD), is written by Blender, Houdini, Maya and Unreal, and has a plain-text form (`.usda`) that diffs in git.

The aim is a **rich source** that loses as little as possible, alongside the lean glTF delivery. The `.blend` stays the authoring file of one tool (`authoring_source`, §5).

## 2. Two levels

| Level | What it is | Effort |
|---|---|---|
| **L1: USD meshes** | `geometry.meshes[].uri` may be `.usd`, `.usda`, `.usdc` or `.usdz`. Bindings, attributes, instances and animations get USD equivalents of their glTF rules (§3). The STJ JSON stays a separate file. | Small |
| **L2a: STJ inside USD** | The STJ document lives in the root layer's `customLayerData["stj"]` (verified to round-trip byte for byte). One `.usdz` is then a whole track (Q12). STJ variants, layouts and chunks may use USD's own variant sets and payloads (§4). | Medium |
| **L2b: STJ as USD schemas** | STJ concepts become typed USD schemas (`StjSurfaceAPI`, `StjTimingLine`, `StjPacenote`…), defined as *codeless* schemas: a `schema.usda` plus `plugInfo.json`, no C++. | Large; only once the JSON is stable |

The recommendation is **L1 + L2a now, L2b later**.

## 3. L1: USD geometry next to glTF

| glTF rule (today) | USD rule |
|---|---|
| Node name `STJ::<category>::<id>` | Prim name `STJ__<category>__<id>`. **USD forbids `::` in names**; Blender already writes `__`. Both spellings mean the same in STJ. |
| `bindings[] {mesh_ref, material \| node}` | `{mesh_ref, material \| prim}`. `material` is the UsdShade material's name, `prim` a prim path in the file (a Mesh or a GeomSubset). |
| Material named `STJ::surface::<id>` | Material named `STJ__surface__<id>`. Materials are bound per face through GeomSubsets, which Blender writes. |
| `_STJ_SURF_LAYERS` (VEC3, per vertex, vertices split where the layer set changes) | `primvars:stj:surf_layers`: `int3[]` with **`uniform`** interpolation, one per face, so **no vertex splitting** |
| `_STJ_SURF_WEIGHTS` (VEC2 per vertex) | `primvars:stj:surf_weights`: `float2[]`, `vertex` or `faceVarying` |
| `_STJ_LAYERS`, `_STJ_WEIGHTS` (ground) | `primvars:stj:ground_layers` (uniform int3), `primvars:stj:ground_weights` |
| `_STJ_DENSITY`, `_SWAY` | `primvars:stj:density`, `primvars:stj:sway` |
| `TEXCOORD_n` in a projection or macro map | A named UV primvar: `{"texcoord": "st"}` or an index into the primvars of role `textureCoordinate` |
| glTF animation by name | `{"time_range": [start, end]}` in time codes, at the stage's `timeCodesPerSecond`. USD has no named clips. |
| `KHR_lights_punctual` | UsdLux lights |
| `EXT_mesh_gpu_instancing` | PointInstancer or native instances |
| Prop physics in `prototype.physics` | The same JSON. Prims may also carry **UsdPhysics** (RigidBodyAPI, MassAPI, CollisionAPI, physics material). See D2 for which wins. |
| `audio.emitters` | The same JSON. Prims may also carry **UsdMedia SpatialAudio**. |
| `extras` | Typed attributes in the `stj:` namespace, or one `stj:json` string attribute. **Never nested Blender dictionaries**: the exporter drops them. |

Axes and units: the stage declares `upAxis = "Z"` and `metersPerUnit = 1`, which is exactly the STJ world frame (Blender's default). Other values are allowed only if the file declares them, and the converter applies them.

## 4. L2a: STJ inside USD

- **The document.** `customLayerData["stj"]` of the root layer holds the STJ JSON as a string. Tools extract it, then validate it like any `.stj.json`. URIs in it are relative to the USD file. Inside a `.usdz` they are paths inside the package.
- **Single-file delivery (Q12).** A `.usdz` holds the stage, the textures, the audio and the sub-layers in one uncompressed zip. That answers Q12 without hiding the JSON: `stj_extract file.usdz` writes it out.
- **Variants.** Today an STJ variant is an RFC 7396 override file. In USD, a variant may also select **USD variant sets**: `variants[] {…, "usd_variants": {"stj_condition": "wet"}}`. The JSON patch changes semantics (water depth, surfaces). The USD variant changes what the stage shows (textures, lights, snow meshes). This subsumes glTF `KHR_materials_variants`.
- **Layouts.** `include_meshes` / `exclude_meshes` may also be expressed as a variant set `stj_layout` that activates or deactivates prims.
- **Chunks** (spec §7.6). A chunk's meshes may be a USD **payload**: `geometry.chunks[].payload`. The payload prim's transform is the chunk's `origin`, so streaming is USD's own load and unload.

## 5. Authoring source

Neither glTF nor USD round-trips everything back into Blender: physics, audio, the sky and actions do not come back. `_metadata.authoring_source {uri, tool, tool_version}` names the file a package was made from: a `.blend`, a Maya scene, a BTB project. A tool that edits the track opens that instead.

## 6. Validation

- **USD support is optional in the validator.** With `pxr` installed (`pip install usd-core`), it checks USD meshes the same way it checks glTF:
  - materials, prims and primvars exist
  - `stj:surf_layers` indices are inside the palette
  - `upAxis` and `metersPerUnit` match the STJ frame
  - `customLayerData["stj"]` parses
- **Without `pxr`**, USD files are reported as a NOTE ("not checked"), never as an error.
- **`.usdz`**: the validator opens the zip, reads the root layer and extracts the document.

## 7. Decisions

**D1. Level.** Recommendation: **L1 + L2a now** (USD geometry, the STJ document inside USD, `.usdz` single file); L2b schemas later. Alternatives:
- L1 only: USD meshes, with the JSON always separate
- straight to L2b: typed schemas now

**D2. Which source wins** when the STJ JSON and USD-native data say different things, for example `prototype.physics` against UsdPhysics on the prim? Recommendation: **the STJ JSON is normative**; USD-native copies are a convenience for USD tools, and the validator warns on disagreement. Alternative: USD-native wins where it exists.

**D3. Variants.** Recommendation: **STJ variants may select USD variant sets** (`usd_variants`), next to the JSON patch. Alternative: keep only JSON override files; USD variant sets are not used by STJ.

**D4. Validator dependency.** Recommendation: **`pxr` optional**, so USD checks run only where it is installed. Alternative: require `usd-core`, so every STJ check needs it.
