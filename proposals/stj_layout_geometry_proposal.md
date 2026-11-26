# STJ proposal: geometry that belongs to one layout only

Status: **adopted** 2026-11-26 as recommended (Q1 to Q5, version 0.4): spec §3.5 items 7 to 9 and §7.8. Source: Richard Burns Rally, the BTB stages *Bareyo* and *Bareyo II* (`rbr2stj`): one road run in both directions, with different objects at the roadside in each.

## 1. What the spec already covers

§3.5: the top-level document is the default layout; `layouts[]` lists the alternatives; item 6: `include_meshes` and `exclude_meshes` select geometry. A layout can therefore **leave out** a mesh of the default layout (a chicane that only the default has, in a package whose default holds every mesh).

## 2. What it cannot express

1. **A mesh that the default layout must not load.** Selection exists only inside `layouts[]`. In `stj_core.layout_document` meshes are filtered only for a selected layout, and the top-level document keeps every entry of `geometry.meshes`. A mesh made for an alternative layout is therefore also part of the default one. If it is a collision mesh, the default layout has two sets of barriers at once. Adding a "forward" entry to `layouts[]` does not help: the top-level document is unchanged.
2. **What goes with a mesh.** `layout_document` filters `geometry.meshes` and nothing else. `scenery.instances[]`, `surfaces.maps[]`, `surfaces.bindings[]`, `animated_objects[]`, mesh-bound water bodies and other items with a `mesh_ref` stay, pointing at a mesh that the selected document no longer has. The spec does not say what a reader does with them, and `check_layouts` in the validator checks the line, timing, race data and edges of a layout, not these references.
3. **Placements that differ with a shared model.** An instance set with `transforms` places a prototype whose mesh both layouts use (a cone, a sign, a tree). When only the placements differ there is no mesh to select by.
4. **The USD stage.** A root layer that references every mesh layer shows all of them in a plain USD viewer.

## 3. The case

Measured on the two converted packages (the two source folders are separate BTB stages; their authors' internal paths name them "Fictitious Bareyo" and "Fictitious Bareyo reversed"):

| What | Result |
|---|---|
| Road height under the driven line, sampled every 0.5 m at 0, ±1.5 and ±3 m | equal, except about 4 m of road with up to 10 cm of difference at the sides |
| Dominant surface on the 241,519 collision triangles that are identical | equal on all of them |
| Collision triangles more than 5 cm from the other stage's surface | 1,260 of 242,941 and 2,103 of 243,819; about 62 % near vertical |
| Source placements at the same position in both (18,103) | 18,065 with identical rotation; 14 differ by more than 1° |
| Source placements in total | 18,491 and 19,033 |
| Roadside objects | parked cars removed, added or moved; walls, signs, containers and vegetation differ |
| Textures with the same name (246) | one differs (a sky texture) |
| Driven line | not an exact reversal: median 10 cm, at most 1 m apart |

One package with the common ground once, and each direction's own objects, loses nothing. Today the choice is two packages that repeat almost everything, or one package whose reverse layout drops its own barriers.

The same need appears wherever layouts share a venue but not its furniture: circuit configurations with different barriers, kerbs, cones or chicanes, and stages run both ways with their own tape, spectators and parked cars.

## 4. Proposal

1. **`geometry.meshes[].layout_only: true`.** The mesh is not part of the default layout. It is part of a layout only when that layout names it in `include_meshes`. A layout without `include_meshes` takes every mesh that is not `layout_only` (then applies `exclude_meshes`). `include_meshes` keeps its meaning, "only these meshes", so a layout with its own objects lists the common meshes and its own.
2. **What depends on an absent mesh is absent.** In the default layout and in every selected layout, an item whose geometry is in a mesh that is not selected is not part of the document:
   - `scenery.instances[]` whose `usd.mesh_ref`, or whose prototype's `mesh.mesh_ref`, is not selected;
   - `surfaces.maps[]` and `surfaces.bindings[]` on that mesh;
   - `animated_objects[]` targeting it, mesh-bound water bodies, and any other item whose `mesh_ref` names it.
   `layout_document` removes them, and a new `default_document` does the same for the top level, so a reader gets a document with no dangling reference.
3. **`scenery.instances[].with_mesh: <mesh id>`.** An optional condition for an instance set with `transforms`: the set exists only when that mesh is selected. It carries the case of §2 item 3 without copying the prototype.
4. **USD.** In the root layer, the prim that brings in a `layout_only` mesh layer is authored inactive (`active = false`). A tool that selects a layout activates the prims it needs. A plain USD viewer then shows the default layout.
5. **Validator.**
   - the default document and each layout are checked as `default_document` / `layout_document` return them: no dangling `mesh_ref`;
   - a `layout_only` mesh that no layout includes: warning;
   - a `with_mesh` that names an unknown mesh: error;
   - a layout whose selected meshes hold no collision, when the default layout has one: warning;
   - each selected document gets the existing surface checks for its own collision meshes.

Example:

```json
"geometry": { "meshes": [
  { "id": "ground",   "uri": "meshes/ground.usdc",   "roles": ["collision"] },
  { "id": "objects",  "uri": "meshes/objects.usdc",  "roles": ["collision"] },
  { "id": "objects_reverse", "uri": "meshes/objects_reverse.usdc", "roles": ["collision"], "layout_only": true } ] },
"layouts": [ {
  "id": "reverse", "name": "Bareyo II",
  "reference": { "centerline": { "points": [ [1155.8, 602.8, 69.3], [1150.0, 603.0, 69.4] ] } },
  "include_meshes": ["ground", "objects_reverse"] } ]
```

The default layout is `ground` + `objects`; the reverse is `ground` + `objects_reverse`.

## 5. Compatibility

A document without `layout_only` and `with_mesh` behaves as today, except that a selected layout that already used `exclude_meshes` now also drops what depended on the excluded mesh (item 2), which today is a dangling reference.

A reader that does not know `layout_only` would load every mesh in the default layout, and two sets of barriers would collide. A document that uses it must therefore be distinguishable by version, so an older reader can refuse it or warn.

## 6. Decisions

| Q | Question | Recommendation |
|---|---|---|
| Q1 | How is a mesh kept out of the default layout? (a) `layout_only` on the mesh; (b) a top-level selection block for the default layout; (c) a list of layout ids on each mesh. | (a): one boolean, and `include_meshes` keeps its meaning. (b) adds a second place with the same two lists. (c) needs an id for the default layout, which it does not have. |
| Q2 | Do items that depend on an absent mesh disappear (item 2)? | Yes, as a rule of the spec, implemented in `stj_core`, so converters need no logic of their own. |
| Q3 | `with_mesh` on instance sets (item 3), or duplicate the prototype into the layout's mesh file? | `with_mesh`. Duplicating copies models only to say where they are placed. |
| Q4 | USD: inactive prims (item 4), or the `stj_layout` variant set of `stj_usd_proposal.md`? | Inactive prims: nothing new to resolve. A variant set can be added later without changing the document. |
| Q5 | Version: minor version bump, or no change? | Bump: the failure of an older reader is physical (overlapping collision), not cosmetic. |

## 7. Not part of this proposal

- Layout-dependent surfaces or surface state on a **shared** mesh. In the case above they are equal.
- `scatter[]` and `crowds` by layout: no source needs it yet. `with_mesh` could extend to them.
- How a producer splits two sources into common and own geometry. `rbr2stj` would keep as common only what is identical in both, and put everything else in each direction's own meshes, so no data is changed.
