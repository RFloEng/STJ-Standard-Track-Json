# STJ proposal: which side of a collision face is solid

Status: **adopted** 2026-11-21 as recommended (Q1 to Q4): spec §7.2 *Sidedness*, validator `collision-sidedness`, `stj_core.usd_collision_sidedness`. Source: the `rbr2stj` -> STJ -> BeamNG chain on Passo Valle (RBR stage 352).

## 1. The gap

The spec says which prims are collision surface (§7.2, `stj:collision`) and which surface each face has (§6.3), but never **from which side a collision face is solid**. Engines differ:

- BeamNG, Unreal and most physics engines collide a triangle **one-sided**: the side its winding faces is solid, the other side lets a body through. A road that points down is a hole.
- Richard Burns Rally's `.col` mixes windings. In Passo Valle the collision has 258,904 triangles: 227,870 point down, 5,032 point up, 25,935 are vertical. The game does not appear to depend on the winding; it is not documented either way.
- AC (`1ROAD` meshes) and ACR collide both sides in practice.

With no statement in the file, every converter guesses. The BeamNG converter flipped the whole mesh when most of it pointed down, which turned the 5,032 triangles that were already up into holes: stretches of road the car fell through. Any other consumer would have to rediscover the same fix.

## 2. Proposal

Use the USD attribute that already exists, `doubleSided` on the Mesh, for prims with the `collision` role. No new field.

1. **`doubleSided = true`**: every face is solid from both sides. A reader that can only collide one-sided MAY orient each face toward its own up (for ground-like faces) or toward the side that faces the body's approach.
2. **`doubleSided = false` or unauthored** (USD's default is false): a face is solid on the side its normal points to. The normal follows the USD `orientation` attribute and the vertex order, as USD defines it. A producer whose source collides both sides MUST write `true`.
3. A reader MUST NOT flip faces of a mesh with `doubleSided = false` to "repair" it; the file says what it means.
4. The attribute is read per mesh prim. A file that needs both behaviours (a one-sided road and a two-sided wall) uses two prims.

### Validator

- WARN, `collision-sidedness`: a collision prim with `doubleSided` false or unauthored whose area-weighted ground-like faces (|n_z| > 0.3 in the STJ frame) point mostly down (above 50% of their area). It is almost always a producer that forgot `true`, or a mesh wound backwards.
- NOTE: a one-sided collision prim whose ground-like faces mix up and down (each side above 5% of the area). The faces that point down are holes for a one-sided engine.

### Spec text

Add to §7.2 after "Which prims are collision surface":

> **Sidedness.** A collision prim's `doubleSided` says which side of a face is solid. `true`: both. `false` or unauthored: the side the face points to (USD `orientation` and vertex order). Producers whose source game collides both sides write `true`. Engines that collide one-sided and receive `true` orient each face themselves; they do not alter a `false` mesh.

## 3. Consequences

| Who | Change |
|---|---|
| `rbr2stj` | Writes `doubleSided = true` on the collision mesh (RBR does not distinguish sides). Leaves the winding as read. |
| `stj2beamng` | `true`: orient every ground-like face up (per face, not per mesh), keep vertical faces as they are. `false`: keep the STJ winding and do not flip. Replaces the heuristic in `fix_collision_winding`. |
| Other converters (AC, DR2, WRCG) | Set the attribute to what their game does. Meshes already published without it are read as one-sided, so the validator warning above is how they find out. |
| Existing files | Packages made before this change have unauthored `doubleSided` and, for RBR, mixed windings: the new warning flags them and regenerating fixes them. |

## 4. Decisions

| Q | Recommendation |
|---|---|
| Q1 | Reuse `doubleSided` instead of a new `stj:` attribute. Recommended: yes, it is the standard USD meaning and no reader needs new code to find it. |
| Q2 | Default when unauthored. Recommended: USD's own (one-sided). The alternative (two-sided) would make old files look right but hides the one-sided engines' problem. |
| Q3 | Validator severity. Recommended: WARN for mostly-down ground, NOTE for mixed. |
| Q4 | Per-face override (a GeomSubset with its own sidedness). Recommended: not now; two prims cover it. |

## 5. Not covered

Thin shells (a fence modelled as one quad) that must stop a body from either side: they use `doubleSided = true` and the engine's own thin-wall handling. Penetration depth and tunnelling at speed are engine matters.
