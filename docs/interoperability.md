# Interoperability: what each format carries

This page says, for the formats this repository reads, writes or tests against, how each part of an STJ track travels. It lists only what is exercised here: Blender, OpenUSD, OpenDRIVE and OpenCRG. Converters for particular games live in their own repositories and document their own coverage; this page does not repeat it. A converter reports what it did with the conversion report of [spec §3.12](../spec/STJ_Spec.md).

## How to read the table

| Word | Meaning |
|---|---|
| **native** | The format has a field for it with the same meaning. Nothing is lost. |
| **mapped** | The format has a close field; a rule (in the spec or the Blender profile) says how the two correspond. Names or units may differ. |
| **custom extension** | Carried in the format's extension space (USD `customData`, a Blender custom property, an `x_` key), so it survives a round trip but no other tool understands it. |
| **baked** | Flattened into a lower-level form (a bitmap, a polyline). The result is correct to look at; the recipe is gone or kept only as a stamp. |
| **partial** | Some of it travels, the rest does not. The notes say which. |
| **unsupported** | The format cannot hold it, and the translator drops it and says so. |
| **engine-specific** | Only meaningful to one engine. STJ keeps it under `x_<engine>`; this repository has no engine in this class. |

"Tested" means a test in `tests/` or an example checked by the validator in `python -m pytest tests -q`. Blender rows were run on Blender 5.2 LTS and are skipped by the suite when Blender is not installed.

## Capability matrix

| STJ part | OpenUSD | Blender (profile 0.1) | OpenDRIVE | OpenCRG |
|---|---|---|---|---|
| The STJ document | custom extension: `customLayerData["stj"]` of the root layer; `.usdz` packs it with the files (§7.8) | custom extension: text block `track.stj.json` (base) plus objects | unsupported: no place for it | unsupported |
| Reference line | custom extension: in the document; also mapped to curves if a tool wants them | mapped: a Curve object (Bezier when the line has tangents), cyclic when closed | native: the road geometry; `reference.opendrive` points at the file and the `route` of road ids | native: the CRG reference line, placed like an OpenDRIVE `<CRG>` |
| Roads, junctions, routes (§7.1) | custom extension (document) | mapped: `STJ::road`, `STJ::junction` objects; routes stay in the text block | partial: roads and links are OpenDRIVE concepts; the validator reads road ids and lengths only | unsupported |
| Surfaces and grip (§6) | custom extension: `STJ__surface__<id>` material names bind meshes to surfaces; the physics is in the document | mapped: `STJ::surface::<id>` materials; the surface entry is a custom property | partial: lane materials map to surface ids (§6.3); friction is a number, not the STJ model | partial: CRG can carry friction grids; STJ places them (`geometry.crg`) |
| Timing and race data (§9, §10) | custom extension (document) | mapped: empties for gates, grid, pit boxes, spawns; positions follow the objects | unsupported | unsupported |
| Collision geometry (§7.2) | native: Mesh prims, `bool stj:collision` marks them when a file has several roles | mapped: Blender's USD import and export carry the meshes | unsupported | not exercised here: STJ places CRG files (`geometry.crg`) but no test reads their grid |
| Visual geometry and materials (§7.7) | native: meshes, UsdPreviewSurface, MaterialX network next to it | mapped through Blender's USD import and export; the preview surface and MaterialX are written | unsupported | unsupported |
| Layered ground (§8.7) | native: MaterialX network on the ground material (`ground_materialx.py`) | mapped: rebuilt as shader nodes on import (`stj_ground.py`), checked pixel by pixel against the reference maths | unsupported | unsupported |
| Baked ground | baked: image written by `ground_bake.py`, stamped as a cache of the recipe | baked: the image is shown; the recipe is the source | unsupported | unsupported |
| Terrain heightfields (§7.4) | partial: a PNG referenced from the document; no USD heightfield prim is used | mapped: a grid mesh `STJ::terrain::<id>`, one vertex per sample; the heightmap is rewritten when the heights are edited | unsupported | not exercised here: see the collision row |
| Scenery instances (§8.2) | native: PointInstancer in a mesh file | mapped: instances shown, orientation and scale kept; restored as a PointInstancer on export | unsupported | unsupported |
| Sky, sun, lighting (§8.3) | native: UsdLux lights | mapped: Sun light follows date and place; a placeholder sky and sun are added when the document has none and are marked `stj_placeholder` | unsupported | unsupported |
| Audio emitters (§8.6) | custom extension (document) | mapped: speaker objects | unsupported | unsupported |
| Cameras (§8.8) | custom extension (document) | mapped: Camera objects (`position_ref` stays in the text block) | unsupported | unsupported |
| Animated objects (§8.5) | native: time samples in the mesh file | partial: carried by Blender's USD import and export as time samples; no Blender actions are built | unsupported | unsupported |
| Engine-native data (`x_<engine>`) | custom extension | custom extension (kept in the text block and object properties) | unsupported | unsupported |

## Where each row is tested

| Row | Evidence |
|---|---|
| STJ in USD, `.usdz` | `tests/test_validate.py` (embedding, packing, the examples under strict validation) |
| Reference line, closed lines, routes | `tests/test_validate.py` (`ReferenceLine`, `JointsAndRoutes`) |
| Blender entities, round trip, names, placeholders, instancers | `tests/test_blender_profile.py` and the scripts `tests/blender_*_check.py` |
| Layered ground in Blender | `tests/test_blender_ground.py` |
| MaterialX for ground and ordinary materials | `tests/test_ground_materialx.py`, `tests/test_material_mtlx.py` |
| Collision prims | `tests/test_validate.py` (`SimulatorProposals`) |
| OpenDRIVE: road ids and lengths | `tests/test_validate.py` |
| OpenCRG: placement and references | `tests/test_validate.py` |

## What is not here

- **Other game formats** (Assetto Corsa, BeamNG, Richard Burns Rally, DiRT Rally and others). Each has a converter in its own repository, which says what it maps, approximates and drops. They read and write STJ through the shapes above.
- **An OpenDRIVE evaluator.** The reference line of an OpenDRIVE file is read by whoever has one; the document keeps a `centerline` copy for tools that do not.
- **glTF** as a mesh format: STJ meshes are USD ([spec §13](../spec/STJ_Spec.md)).
