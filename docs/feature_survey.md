# Survey: what track-creation tools define that STJ v0.1 does not

Status: research notes, 2026-11-02. Two independent web surveys were merged here. Claims marked *(m)* come from memory or forum posts and were not verified against documentation. AMS2/Project CARS, iRacing, DiRT Rally 2.0, EA WRC and Assetto Corsa Rally have **no public track tooling**, so only feature-level information exists for them.

## 1. Feature × tool overview

Y = documented natively · C = Assetto Corsa via Custom Shaders Patch · (m) = unverified · – = none found

| Feature | AC (+CSP) | rF2 / gMotor | BeamNG | RBR / RSF | Speed Dreams / TORCS | Rigs of Rods | UE / Unity | OpenDRIVE / OpenSCENARIO | Others |
|---|---|---|---|---|---|---|---|---|---|
| Several layouts on shared models | Y (m) | Y | prefabs | Y, reverse stages with own pacenotes | (m) | – | – | – | LFS layouts, Wreckfest (m) |
| Time-of-day / weather variants | sun angles (m), C | Y GDB + `.wet` schedule | Y TimeOfDay | Y skybox M/N/E/O, each with its own surface state and pacenotes | Y Local Info | Y | (m) | Y OSC Weather, TimeOfDay | CARLA WeatherParameters |
| Date, timezone, DST, sun/moon/stars | – | Y Lat/Lon/TZ/DST/date | Y lat/lon/date, ScatterSky moon and stars | – | Y time, timezone, sun ascension | – | – | Y OSC `dateTime` | – |
| Wind | C (drives grass, windmills) | Y `.wet` | clouds only | (m) | – | – | Unity grass wind | Y OSC Wind | CARLA |
| Seasons, snow cover | C year conditions | (m) | date only | Y | – | Y | – | – | ACR dynamic snow |
| Terrain heightmap + material layers | – (mesh) | – (mesh) | Y `.ter` + painted layers → ground models | – (mesh) | Y elevation map | Y `.otc` 2^n+1, 6 blend layers | Y Landscape / Terrain | junction elevation grid | – |
| Water bodies (depth, flow) | C visual only | – | Y plane, block, river (depth, flow) | (m) | – | Y water line | Y UE Water (river width, depth, velocity) | – | – |
| Rain: puddles, drains, occluders | C RainFX | – | – | material sets dry/damp/wet × new/normal/worn | rain likelihood | – | – | OSC precipitation | AMS2 puddles |
| Edges: kerbs, borders, barriers as semantics | – | – | – | – | Y side/border/barrier with style, width, height | – | – | Y objects, markings | GT6 curbing, RoadRunner, Milestone |
| Static rubber / groove | Y `groove.ini` | Y RRBIN presets per session | – | – | – | – | – | – | AMS2 / iRacing dynamic (closed) |
| Track cameras | Y `cameras*.ini` | Y `.cam` | bookmarks | (m) | Y (segment, height, fov) | – | – | – | Wreckfest, Trackmania |
| Audio emitters, reverb zones | Y (m), C FMOD | Y ambient sounds | Y SFXEmitter, SFXSpace | – | – | – | UE water audio | – | – |
| Animations, state-driven objects | C animated objects + conditions | Y `.ANIM` | Lua / flowgraph | – | – | – | – | OSC storyboard | Trackmania MediaTracker |
| Start lights, signals, signs | – | Y starting lights count | – | – | (m) | – | – | Y OpenDRIVE `<signal>` | RoadRunner, CARLA |
| AI beyond a racing line | Y `pit_lane.ai`, CSP hints | Y AIW corridor; pit, left, right, block, wet paths; safety car | waypoints | – | Y raceline width | Y AI presets | – | – | Wreckfest AI routes |
| Start procedure, DRS | – | Y lights, formation and pit speeds (m), DRS zones | rolling start flag | – | – | – | – | – | – |
| Rally controls (TC, stop, service) | – | – | – | Y start, splits, finish, end of stage | – | – | – | – | – |
| Movable / breakable props | C | Y loose objects (mass, inertia, spring, damper) | – | (m) | – | Y | – | – | LFS cones and tyres |
| Spectators / crowds | – | (m) | – | (m) | – | – | – | – | GT6, RoadRunner |
| UI / minimap metadata | Y `ui_track.json`, `map.ini` | Y | POIs | RSF track list | – | – | – | – | – |
| Marshals, restricted zones | – | – | gameplay areas | – | – | – | – | – | LFS marshal, restricted circle, route checker |
| Reflection probes, screens | C | Y scoreboard | – | – | – | – | – | – | – |

## 2. Already covered by v0.1

- **Sun, moon and stars.** No positions are stored. Both surveys agree: date, time, location and time zone are enough to compute them from ephemerides. STJ uses an IANA `timezone`, which already carries the DST rules that rF2's GDB spells out by hand.
- **OpenCRG placement** (`geometry.crg`) and **rolling resistance** (surfaces).
- **Engine-native blocks** (`x_<engine>`), which both surveys recommend for shaders, ground-model internals, binary data (RRBIN, `.dls`) and ecosystem ids (RBR skybox letters, CARLA blueprints).

## 3. Ranked candidates

Each candidate lists the precedent behind it, a minimal data shape, and how portable it is. Shapes are sketches, written in STJ conventions: SI, `s` in metres, angles in rad.

### Tier 1: adopted into v0.1 (2026-11-02)

These were adopted with some changes: see spec §3.5 (layouts), §3.6 (variants), §7.3 (edges), §9 (DRS, controls, side roads), §10 (AI, start procedure, service areas, cameras) and §11 (weather schedule).
- **AI side paths** became `racing_lines` purposes instead of a separate list.
- **Rally controls** sit in `timing`.
- **Layouts** replace `reference`, `timing` and `race` wholesale instead of merging them.

1. **`layouts[]`**: one set of models, several track variants. Universal (AC, rF2, LFS, RBR reverse stages). A layout selects meshes and scenery and owns its reference line, timing, grid, pits, AI lines and pacenotes.
   `{id, name, direction: forward|reverse, reference, timing, race, include_meshes[], exclude_meshes[]}`. The per-layout blocks use the same shapes as the top-level ones. A layout-only override file (§3.3) already works today but repeats everything.
2. **`variants[]` index of conditions**: time of day, weather, season. RBR M/N/E/O variants, rF2 `.wet` schedules, OpenSCENARIO Weather, CARLA.
   `{id, kind: time_of_day|weather|season, override: "file.stj-override.json", material_variant}`. The base file lists its own override files. Texture swaps use glTF `KHR_materials_variants`. Also add a `weather_schedule[]` for sessions. Fully portable except the rendering.
3. **`cameras[]`** (reserved today): `{id, set, kind: static|tracking|onboard, pose | position, look_at, fov: [min, max], near, far, active: {s_start, s_end} | spheres[]}`. AC activates cameras by track position, rF2 by spheres, Speed Dreams by segment; allow both forms. Portable core, engine-specific post effects.
4. **AI data beyond the racing line**: rF2 AIW corridor and paths, AC `pit_lane.ai` and CSP hints, Wreckfest and RoR routes.
   `race.ai: {corridor: [[s, left, right]], paths: [{id, purpose: pit|alternate|block|wet|safety_car, points}], hints: [{s_start, s_end, kind: danger|no_overtake|brake|speed, side, value}]}`. Portable; behaviour quality depends on the engine's AI.
5. **Edges and barriers as semantics**: Speed Dreams side/border/barrier, OpenDRIVE objects, GT6 curbing.
   `edges: [{side, s_start, s_end, kind: kerb|verge|barrier, style: flat|sausage|wall|armco|tyre_wall|fence|tape|hay_bale|concrete, width, height, surface, restitution}]`. Lets an engine rebuild kerbs and walls with its own assets. Portable.
6. **Race control**:
   - start procedure: `start: {type: standing|rolling, lights: {count, node bindings}, formation_speed}`
   - per-session pit speed
   - `drs_zones: [{detection_s, activation_s, deactivation_s}]`
   - rally: `controls: [{kind: tc|start|flying_finish|stop|regroup|service_in|service_out, s}]`, `side_roads: [{s, side, blocked_by, cut_penalty}]`
   Portable.

### Tier 2: adopted into v0.2 (2026-11-02)

Designed in `proposals/stj_tier2_proposal.md` and implemented in spec §5.1, §6.3, §6.8, §6.9, §7.4, §7.5, §8.4–§8.6 and §11.1. Changes from the sketches below:
- The rubber baseline became `surfaces.line_states[]`, which also covers swept gravel.
- Water gained per-surface wetting and drying data, from a second survey of rF2, AMS2, ACC, iRacing, CSP and RBR (proposal §3.1).
- Seasons are a season block plus `surfaces.substitutions`.

7. **Terrain heightfield**. Native to UE, Unity, BeamNG, Rigs of Rods and Speed Dreams. For the others a converter triangulates it.
   `terrain: {heightmap {uri, format: png16|r16|exr32, size, extent, height_min, height_max, origin}, holes, layers: [{surface, weight {uri, channel}, tile}]}`.
   - The layer → surface link doubles as a portable friction map (RoR TractionMap).
   - Converters must resample to 2^n+1 for UE and Unity.
8. **Water bodies**: BeamNG plane/block/river, UE Water, RoR water line.
   `water: {sea_level, bodies: [{id, kind: sea|lake|river|ford|puddle, polyline [[x, y, z, width, depth]], flow, drivable, wetting_surface}]}`. Physics is portable; shading is not.
9. **State signals**, the prerequisite for `animated_objects`. CSP conditions show the model works.
   - Signals: `sun_elevation`, `local_time`, `year_progress`, `rain`, `wetness`, `flag_state`, `session_phase`, `start_lights_state`.
   - Lights, animations and scenery variants bind to a signal through an optional curve.
   - Keyframe animation itself uses glTF animations; engine animation files stay in `x_`.
10. **Static rubber baseline**: AC `groove.ini`, rF2 RRBIN presets. `groove: {presets: [{id: green|light|medium|heavy|saturated, mf_scaling_gain}], session_defaults}`. Kept separate from the reserved `dynamic` (live rubbering).
11. **Audio**: `audio: {emitters: [{id, position, sound_uri, volume, ref_distance, max_distance, loop}], reverb_zones: [{shape, preset: tunnel|stands|open|forest|garage}]}`. Sound banks are not portable; WAV/OGG plus a generic preset is.
12. **Physical props**: `prototype.physics: {mode: static|movable|breakable, mass, inertia, break_impulse}` for cones, hay bales and tyre stacks (rF2 loose objects, LFS, CSP).
13. **UI / minimap**: `ui: {display_name, short_name, tags[], preview_uri, map {uri, extent}, record}` (AC `ui_track.json`, rF2 GDB).
14. **Seasons**: a variant kind (item 2) with `snow_cover`, scatter density factors and surface swaps.

### Tier 3: adopted into v0.3 (2026-11-02)

Designed in `proposals/stj_tier3_proposal.md`, together with the reserved keys `marshals` and `dynamic`. Implemented in spec §6.10, §7.6, §8.8, §10.1 and §11.

Reflection probes, video screens, crowd behaviour, marshal and restricted zones (these belong in the reserved `marshals`), climate statistics (rain probability, weather station), streaming tiles.

## 4. Stays in `x_<engine>`

- **Shader tuning**: CSP GrassFX and RainFX, UE Gerstner waves, Unity detail distances.
- **Ground-model internals**: BeamNG ground models, RoR `ms`/`mc`/`va`, RBR `physics.lsp`, NGP ruts.
- **Binary engine data**: rF2 RRBIN, RBR `.dls`, AC `.ksanim`.
- **Ecosystem ids**: RBR skybox letters and stage ids, RSF track list entries, CARLA blueprints, Trackmania MediaTracker clips.
- **Scripting**: OpenSCENARIO storyboards, RoR AngelScript. Reference these, never model them.

## 5. Sources

- **Assetto Corsa / CSP**
  - CSP track docs: https://cup.acstuff.club/docs/csp/tracks/rainfx (also `/animated-objects`, `/audio`, `/conditions`, `/lights`, `/water-shader`, `/grass-fx`, `/local-cubemaps`, `/displays`)
  - AC modding wiki: https://www.sites.google.com/site/hagn99/assettocorsa/modding/tracks
- **rFactor 2**
  - Studio 397 docs: https://docs.studio-397.com/x/hgFDAg (GDB, CAM, WET, RRBIN pages)
  - AIW tutorial: https://www.studio-397.com/wp-content/uploads/2016/12/rF2_AIW_Creation_Tutorial.pdf
- **BeamNG**: https://documentation.beamng.com/modding/levels/level_classes/water/ (also `/tod/`, `/skyweather/`, `/terrainblock/`, `/sound/`)
- **Live for Speed**: https://www.lfs.net/programmer/lyt
- **Speed Dreams / TORCS**
  - https://torcs.sourceforge.net/api/track_manual.html
  - https://sourceforge.net/p/speed-dreams/wiki/UpdatesToTrackFormat/
- **Rigs of Rods**: https://docs.rigsofrods.org/terrain-creation/terrn2-subsystem/
- **Unreal Engine**
  - Landscape: https://dev.epicgames.com/documentation/en-us/unreal-engine/landscape-technical-guide-in-unreal-engine
  - Water bodies: https://dev.epicgames.com/documentation/en-us/unreal-engine/water-body-actors-in-unreal-engine
- **ASAM**
  - OpenDRIVE 1.8 road surface: https://publications.pages.asam.net/standards/ASAM_OpenDRIVE/ASAM_OpenDRIVE_Specification/1.8.0/specification/10_roads/10_06_road_surface.html
  - OpenSCENARIO Weather: https://openscenario.asam.net/ASAM_OpenSCENARIO_XML/v1.3.1/generated/content/Weather.html
- **CARLA**: https://carla.org/Doxygen/html/db/ddb/classcarla_1_1rpc_1_1WeatherParameters.html
- **RBR**
  - Blender track exporter guide: https://richardburnsrally.github.io/blender-track-exporter/guide.html
  - Pacenote plugin: https://rallysimfans.hu/rbr/downloads/other/RBR_Pacenote_Plugin_Quick_Start_Guide.pdf
