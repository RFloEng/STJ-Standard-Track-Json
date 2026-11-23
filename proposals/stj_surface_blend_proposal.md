# STJ proposal: surface blending, order of evaluation and engines that take one surface per face

Status: **adopted** 2026-11-23 as recommended (Q1 to Q4): spec §6.3 (order of evaluation), §14 limitation 20 (one surface per face), `docs/interoperability.md` (capability). One precision on Q1: the order only changes the numbers where a value passes through a curve, and §6.3 already evaluates curves per entry. Source: Richard Burns Rally Passo Valle (`rbr2stj` -> STJ -> BeamNG) and the `rbr2stj` surface export.

## 1. What the spec already covers

Surface maps (§6.3 level 0) carry a per-face palette and per-vertex weights (`vertex_top3`, `vertex_dense`, `image`, `id_map`), `contact: blend | dominant`, and a `when` on `wear` and `wetness`. The blend rule says what blends how: numbers by weight, curves evaluated per entry and then blended, categorical fields from the largest weight. Per-surface grip differences are expressible too: `mf_scaling` and `by_tyre_class` (§6.4, with the division by the tyre's reference surface).

So a stage like Passo Valle, where the road is tarmac, snow on gravel and a mix of both (4,902 of about 82,000 faces within 3 m of the line mix the two), is carried completely: palette, weights and states. Nothing here needs a new field.

## 2. What is left open

1. **Order of evaluation.** §6.4 resolves a surface into tyre factors in steps (surface values, `by_tyre_class`, division by the tyre's reference surface). §6.3 says contacts blend "the weighted mean of the palette entries present". The spec does not say whether the weighted mean is taken over the surface values before the tyre steps, or over the final per-tyre results. With `by_tyre_class` and a tyre whose reference surface differs from STJ-REF the two orders give different numbers. RBR blends the surface first and applies the tyre afterwards.
2. **One surface per face.** BeamNG, mesh engines and others take one surface per triangle. §14 limitation 20 says they receive the dominant layer and lose the transition, but gives converters no guidance on how to lose it. Today each one picks the dominant weight per face, which turns a gradual road/snow transition into a hard edge at an arbitrary triangle.
3. **What an engine supports.** Nothing in a file or a reader's declaration says whether blending happens per vertex, per face or per material, so a producer cannot tell whether its blend survives a given consumer.

## 3. Proposal

1. **Blend first, tyre second.** Add to §6.3 level 0: *the weights act on the surface values of §6.4 step 1 (the surface's own generic fields and its `by_tyre_class[<tyre_class>]` block, merged as there); the division by the tyre's reference surface (step 3) and the tyre's own scaling are applied once, to the blended result.* This is the order in which a contact is a single surface, and it matches RBR.
2. **A recommendation for one-surface-per-face targets.** A converter that must give each face one surface SHOULD take the entry with the largest summed corner weight, and MAY subdivide faces whose corner weights differ by more than 0.5 along the edge where the weight of the dominant entry crosses 0.5. It records `lost` what it reduced. This is a SHOULD, not a validator rule.
3. **A capability note per engine** (`interoperability` table of the spec, not the file): per engine, whether surface blending is per vertex, per face or per material. The validator does not read it.

## 4. Decisions

| Q | Recommendation |
|---|---|
| Q1 | State the order (blend first, tyre second). Recommended: yes; it is the only reading under which one contact is one surface, and it is what RBR does. |
| Q2 | Subdividing faces for one-surface-per-face engines. Recommended: a MAY, with the recorded loss; no rule. |
| Q3 | The capability table. Recommended: in the spec's interoperability section only, not in the document. |
| Q4 | A new field for how slippery one surface is relative to another of the same class. Recommended: **no**. `mf_scaling` and `by_tyre_class` already do it; what is missing is data, not a field. |

## 5. Not part of this proposal

The grip numbers themselves. The `rbr2stj` export reads RBR's `physics.lsp` and tyre files, where the three snow-on-gravel and snow-on-ice surfaces of Passo Valle share one surface `Type` and the same default `myStatic` / `myKinetic`, so they come out with equal grip. Whether RBR distinguishes ice from snow elsewhere (engine code, the NGP tyre model) is not established; until it is, the STJ carries the surface names and the same numbers, and a user can set their own per surface with `--surface-table`.
