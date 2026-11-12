# Proposals from the simulator team (Project Chrono)

Nine items found by running a vehicle simulator on STJ tracks (checked against commit `503f0f8`). What was done, item by item.

| # | Item | Outcome |
|---|---|---|
| T1 | Tyre class and reference surface | **Partly.** The defaults are stated (§6.2): no `reference.surface` means STJ-REF (division by 1), no `tyre_class` means the generic values. **Open (SVJ side):** where the tyre class list lives (open question Q2) and `reference.surface` by reference. |
| T2 | Which prims are the collision surface | **Done** (§7.2): the only role `collision` means every Mesh prim; with other roles, prims marked `stj:collision = true` (on the prim or an ancestor). `stj_core.usd_collision_meshes`; the validator warns when a multi-role file marks none. |
| T3 | Merge or replace, and step 3 | **Merge: done** (§6.3, field by field, class wins). **Step 3 kept:** the division by the tyre's reference surface applies to class-specific values too, because a class value is relative to STJ-REF and the tyre's fit was made on its reference surface; skipping it counts the surface twice. A worked example is in §6.4. |
| T4 | Wet grip rules | **Done** (§6.4, §6.8): `mu.sliding` scales the sliding μ of models that have one, informative for MF; `wet_gain` is one number for both axes and 0 when absent; marbles use the session `level` only; line states apply per palette entry; `wet_response(0) = 1`, applied where d > 0. |
| T5 | Blending of non-scalar fields | **Done** (§6.3): numbers by weight, curves evaluated per entry then blended, categorical fields from the largest weight, absent fields take their default. |
| T6 | Surface precedence and conditional maps | **Done** (§6.3): the binding wins over the material name; `surfaces.maps[]` governs the contact and `ground.materials[]` the look; the first map whose condition holds, else level 1; `when` against the §11.1 defaults when no signal is set. |
| T7 | Definition of `t` near corners | **Done** (§4): the nearest point of the reference line, ties to the smaller `s`; `project(x, y, near, window)` for a continuous, cheap search. Tests in `tests/test_validate.py` (`SimulatorProposals`). |
| T8 | Small fixes | **Done:** `texCoord2f` accepted (both were read already; §7.7), `spread` guard in `line_state_value`, ray tolerance note (§7.4). **Not done:** a point-query entry for `film_depth` of a blended contact; renaming `tools/validate.py` (it would break every documented command, so it needs its own change). |
| T9 | Examples for unexercised features | **Not done.** One small example per feature (`vertex_dense`, `image`, `id_map`, `contact: dominant`, `opendrive_materials`, OpenCRG, `substitutions`, wet variant selection, Y-up stage) with expected query results. |
