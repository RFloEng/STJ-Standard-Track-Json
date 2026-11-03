# Best practices for track creators

**For:** people who build tracks in STJ, or convert them, and want them to work in as many engines as possible.

**How to read it:**
- Every number comes from an engine's own documentation **[official]** or from modding forums and wikis **[community]**. Each one links to its source.
- Lines marked **STJ recommendation** are this project's judgment, derived from those numbers.
- Where nothing is published, the guide says so. AMS2 / Project CARS, iRacing, ACC and Le Mans Ultimate publish **no** track budgets. Nothing here is a guess about them.

Status: 2026-11-02. Engine docs change. Re-check a number before relying on it for a release, especially the rF2 pages, which are older Confluence versions.

---

## 1. The portable baseline

Author to these limits and every converter in `docs/converter_plan.md` can take the track without re-modelling. All of them are **STJ recommendations**, set by the strictest engine that publishes a number.

| What | Portable baseline | Set by |
|---|---|---|
| Distance from the origin | ≤ 10 km for any vertex; re-origin and record `environment.origin_offset` (spec §4.4) | float32 precision; BeamNG dev advice (§6) |
| Collision mesh pieces | ≤ 25 000 triangles and ≤ 15 000 vertices each; split drivable surfaces every ~300 m | rF2 [official], AC [community] (§2) |
| Road collision density | ~1 triangle edge every 0.5 m along the road, denser in tight corners and on kerbs; ~5 m on flat run-off far from the road | rF2 [official] |
| Bumps | Only on the collision mesh. The visual mesh follows it. | AC practice [community] |
| Visual mesh pieces | < 55 000 vertices per mesh | AC 16-bit index limit [community] |
| Materials | As few as possible. Merge objects that share a material. | Draw-call cost in BeamNG [official] and AC [community] |
| Textures | Power of two, with mipmaps, ≤ 4096 px per side. Deliver block-compressed DDS per engine (§4); keep PNG masters. | RBR, BeamNG [official] |
| Terrain | Square cells, `2^n + 1` samples per side, ≤ 4097 | Unity, UE, RoR [official] (§5) |
| Terrain height range | Keep it within ±256 m of the terrain's z offset, or plan the UE Z scale | UE default scale [official] |
| Repeated objects | Instances (`scenery.instances`) and scatter rules, never baked copies | BeamNG instancing [official] |

---

## 2. Collision and road surfaces

The road surface is the most physics-critical asset, and the one engines are strictest about.

**Separate collision from visuals.** Every engine that documents it uses a separate, invisible physics mesh:
- AC: `1ROAD` and friends, non-renderable [community](https://assettocorsamods.net/goto/post?id=23322)
- rF2: meshes with the HATTarget and CollTarget flags [official](https://docs.studio-397.com/display/DG/Track+Creation+Cheat+Sheet)
- BeamNG: `Colmesh-1` [official](https://docs.beamng.com/modding/levels/level_creation/section5/)

In STJ this is a mesh with role `collision` and surfaces bound to its materials (spec §6.3). Put bumps only on the collision mesh, and shrinkwrap the visual mesh onto it [community](https://assettocorsamods.net/goto/post?id=23322).

**Density.**
- rF2: about one polygon every 0.5 m on the main road, more in tight corners and on kerbs; at most one per 5 m on flat grass or gravel away from the road [official](https://docs.studio-397.com/x/swFDAg).
- Speed Dreams / TORCS: road profile examples use 4 m steps on straights and 3 m in turns [official](https://torcs.sourceforge.net/api/track_manual.html). That is too coarse for modern tyre models, so author to rF2's density.
- `tools/ribbon_usd.py --step` sets the ribbon's station spacing. Use 0.5 for a release.

**Splitting.**
- rF2: ≤ ~15 000 vertices or ~25 000 triangles per object, drivable surfaces split about every 300 m, and at most 2 million vertices across all RealRoad surfaces [official](https://docs.studio-397.com/x/swFDAg).
- AC: physics meshes under ~25 000 vertices, or "holes" can appear [community](https://assettocorsamods.net/goto/post?id=20848). Splitting every ~400 m, or every 4–5 000 triangles, worked best on Targa Florio [community](https://www.assettocorsamods.net/threads/maximize-performance-merge-all-track-objects.777).
- **STJ recommendation:** chunks of ~300 m, each one primitive per surface.

**Small static colliders** (RBR): at most 30 vertices, 84 edges and 56 faces per static shape collision mesh [official](https://richardburnsrally.github.io/blender-track-exporter/features.html). Use boxes and cylinders (spec §8.4 `shape`) where you can.

---

## 3. Visual meshes, draw calls and LODs

- **Per-mesh vertex limit.** AC meshes must stay under ~65k; some modders split at 55k [community](https://assettocorsamods.net/goto/post?id=7530). That is the 16-bit index limit. glTF allows 32-bit indices, but must not use the type's maximum value [official](https://raw.githubusercontent.com/KhronosGroup/glTF/main/specification/2.0/Specification.adoc).
- **Whole-track triangle counts.** No engine publishes a budget. Reference points: AC Monza ~400k triangles, AC Nordschleife ~730k [community](https://assettocorsamods.net/goto/post?id=23322).
- **Draw calls.**
  - BeamNG: each material on a mesh is a draw call; 100 props cost ~100 calls without instancing and ~1 with it; each decal costs ~1 [official](https://docs.beamng.com/modding/levels/level_creation/section8/).
  - AC: merging objects by material cut draw calls from 4818 to 3737, and FPS rose from 75 to 85 even though triangles went from 4.4M to 5.5M [community](https://www.assettocorsamods.net/threads/maximize-performance-merge-all-track-objects.777). **Fewer materials beat fewer triangles.**
- **LODs.**
  - BeamNG: LOD switch by screen size (`_L<pixels>`), halving polygons and materials at each level [official](https://docs.beamng.com/modding/levels/level_creation/section5/).
  - RBR: near geometry under 600 m, far beyond 550 m; geometry more than 40 m from the stage is "any" [official](https://richardburnsrally.github.io/blender-track-exporter/features.html).
  - In STJ, give LODs role `lod` with `lod.switch_distance` in metres. Converters to screen-size engines translate.
- **Lights.** rF2 lights an object with its 20 closest omni lights, and allows at most 20 night lights per object [official](https://docs.studio-397.com/x/swFDAg). Keep `environment.lighting.lights` sparse near any one object.

---

## 4. Textures

| Engine | Format | Size rules | Source |
|---|---|---|---|
| AC | DDS; DXT1 without alpha (DXT5 doubles VRAM) | 4096 atlases are common; no official maximum found | [community](https://assettocorsamods.net/goto/post?id=5768) |
| rF2 / LMU | DDS: **BC7** for albedo (sRGB), **BC5** for normal and data maps (linear). BC1/BC3 not recommended; BC4 does not work. | No maximum found | [official](https://docs.studio-397.com/x/CABDAg) |
| BeamNG | Power of two, with mipmaps | No maximum found | [official](https://docs.beamng.com/modding/levels/level_creation/section8/) |
| RBR | DXT1/3/5, power of two (need not be square). DXT1 for opaque textures. Non-power-of-two textures are rescaled at load, which is very slow. | No maximum found | [official](https://richardburnsrally.github.io/blender-track-exporter/guide.html) |
| Speed Dreams | `_n` in the file name disables mipmaps | Shadow texture must be power of two | [official](https://torcs.sourceforge.net/api/track_manual.html) |
| D3D11 hardware | BC1–BC7 (BC1–3 = DXT1–5, BC4 one channel, BC5 two channels, BC6H HDR, BC7 high-quality RGBA) | 16384 maximum for 2D textures at feature level 11_0 | [official](https://learn.microsoft.com/en-gb/windows/win32/direct3d11/overviews-direct3d-11-resources-limits) |

**STJ recommendation:**
- Keep lossless masters (PNG) next to the glTF.
- Every texture is a power of two, ≤ 4096, with mipmaps.
- Converters compress per target: BC7/BC5 for rF2, DXT1/DXT5 for AC and RBR.
- Mark normal and data maps as linear and albedo as sRGB; glTF already distinguishes them.

---

## 5. Terrain

| Engine | Heightmap size | Notes | Source |
|---|---|---|---|
| Unity | 33, 65, 129, 257, 513, 1025, 2049, 4097 | Width and length up to 100 000 m, height up to 10 000 m; detail resolution per patch 8–128 (16 recommended) | [official](https://docs.unity.com/en-us/engine/current/script-reference/unityengine/terraindata/heightmapresolution), [official](https://docs.unity.com/en-us/engine/current/manual/creating-environments/script-terrain/terrain-other-settings) |
| UE 5 | 8129², 4033², 2017², 1009², 505², 253², 127² recommended; ≤ 1024 components | 16-bit height spans −256…+256 at Z scale 100 (default); each section is one draw call | [official](https://dev.epicgames.com/documentation/en-us/unreal-engine/landscape-technical-guide-in-unreal-engine) |
| BeamNG | Power of two, 128…8192 | World width = size × squareSize; u16 heights scaled by maxHeight; ≤ 254 materials (use far fewer); detail textures stop at 250 m, macro at 1000 m; official levels are 1024², 2048², 4096² | [official](https://documentation.beamng.com/modding/levels/level_formats/terrain/), [official](https://docs.beamng.com/official_content/levels/) |
| Rigs of Rods | PageSize `2^n + 1` (e.g. 1025) | Raw size must match exactly or RoR crashes; 6 layers (5 blend maps); blend map 1024 | [official](https://docs.rigsofrods.org/terrain-creation/terrn2-subsystem) |
| AC, rF2, RBR | – | Mesh terrain only; converters triangulate | – |

**STJ recommendation:**
- Author `2^n + 1` square grids up to 4097. Those go to Unity, UE and RoR unchanged, and to BeamNG by dropping one row and column.
- 1 m cells near the road and 2–4 m further away are typical choices. No engine publishes a rule.
- Keep the terrain ≥ 5 cm under road meshes, or cut holes. The validator checks this (spec §7.4).
- Use few layers: four or five survive every engine (RoR allows 6).

---

## 6. World size and precision

- STJ: keep every vertex within ~10 km of the origin, because float32 loses millimetres beyond that. Re-origin and record `origin_offset` (spec §4.4).
- BeamNG: "only terrains up to like 10 km max should be used" (developer, 2014; dated) [community](https://www.beamng.com/goto/post?id=139310).
- UE 5: Large World Coordinates allow far more (WORLD_MAX 88 million km, beta) [official](https://dev.epicgames.com/documentation/en-us/unreal-engine/large-world-coordinates-in-unreal-engine-5). Other engines don't, so long rally stages still re-origin.
- RBR: a track size limit exists, but its value is not published [official](https://richardburnsrally.github.io/blender-track-exporter/features.html).
- **Long stages (> 20 km)** exceed the 10 km rule from a centred origin. Until STJ has tiles (open question Q14), split them into layouts or separate files.

---

## 7. Vegetation and scatter

- Describe grass and forest fill as `scenery.scatter` rules and placed trees as `scenery.instances`. Never bake them into meshes. Engines instance them: 100 props cost about one draw call instead of 100 in BeamNG [official](https://docs.beamng.com/modding/levels/level_creation/section8/).
- BeamNG GroundCover examples use a radius of 60–100 m and maxElements of 3 000–18 000 [official](https://documentation.beamng.com/modding/levels/level_classes/groundcover/). Set `cull_distance` in that range for grass.
- CSP GrassFX has its own density control (`SHAPE_SIZE`; larger is sparser) and config limits: 4 local adjustment configs with 8 extra areas each, and 4 texture groups of 8 pieces [official](https://cup.acstuff.club/docs/csp/tracks/grass-fx). Carry these in `x_ac`.

---

## 8. Rally stages

- RBR: the driveline must start before the stage start and run past its end [official](https://richardburnsrally.github.io/blender-track-exporter/guide.html). In STJ, make the reference line extend beyond `timing.start` and `timing.stop`.
- RBR: maximum view distance is 600 m when everything is "near" (Wallaby) [official](https://richardburnsrally.github.io/blender-track-exporter/features.html). Detail beyond that is wasted there.
- Surfaces: give loose surfaces both deformable tiers, plus a `swept` line state for running order (spec §6.6, §6.8).

---

## 9. Naming that converters rely on

| Engine | Convention | Source |
|---|---|---|
| AC | Physics mesh name prefix = surface key from `data/surfaces.ini` (`1ROAD`, `1GRASS`, `1WALL`) | [community](https://assettocorsamods.net/goto/post?id=20848) |
| rF2 | RealRoad instances prefixed `RaceSurface`; materials prefixed by surface (`road`, `asph`, `gras`, `grvl`…), wet versions suffixed `_WET` | [official](https://docs.studio-397.com/display/DG/Track+Creation+Cheat+Sheet) |
| BeamNG | Collision `Colmesh-1`; LOD suffix `_L<pixels>`; last LOD `lod_vertcol` | [official](https://docs.beamng.com/modding/levels/level_creation/section5/) |
| STJ | Materials `STJ::surface::<id>` or `surfaces.bindings[]`; nodes `STJ::<category>::<id>` | spec §6.3, §7.2 |

Name collision materials in STJ terms. Converters apply the engine's convention, and the original names stay in `x_<engine>`.

---

## 10. What nobody publishes

- An official maximum texture size for AC, rF2, RBR or BeamNG (only the D3D11 limit of 16384).
- An official whole-track triangle budget for any engine.
- Any track budget for ACC, AMS2 / Project CARS, iRacing or Le Mans Ultimate.
- RBR's track size limit and polygon budgets; BTB limits.

If you have a documented number for any of these, open an issue with the source.

---

## 11. And always

- Convert only files you own. A track converted from a commercial game is `redistributable: false` (README).
- Run `python tools/validate.py <file> --strict` before you share anything.
