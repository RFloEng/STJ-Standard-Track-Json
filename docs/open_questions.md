# Open questions (v0.3)

Numbered so the spec can point at them. Each has a current position. "Decide" marks the ones that need the project owner.

## Physics

**Q1. What is STJ-REF in numbers?**
STJ-REF is defined as dry, clean, unworn dense asphalt with every factor 1. Nobody has published a table mapping test-rig belts (abrasive flat-trac surfaces) to real asphalt per tyre. Until someone measures it, a tyre fitted on a rig declares the rig surface's λ by estimate, marked `_est`.

**Q2. Tyre classes shared with SVJ.**
The list (`slick`, `road`, `intermediate`, `wet`, `gravel`, `snow`, `studded`, `mud`, `offroad`) must be identical in both standards. *Decide* whether the enum lives in SVJ, in STJ, or in a shared file both schemas reference.

**Q3. Hydroplaning.**
It needs tread depth, inflation pressure and speed, all tyre-side. SVJ has pressure but no tread depth. Proposal: SVJ `tires.sets.<id>.tread_depth` (m), plus an STJ-side note that `wet_response` assumes a new tread.

**Q4. Calibrating game surfaces.**
Converting a game's surface friction into λ relative to STJ-REF needs a reference. Proposal: one documented procedure. Drive a reference SVJ tyre on the game's main road surface, then on each other surface; the ratios give λ. This works only for games whose tyres can be replaced or measured.

**Q5. Deformable Tier A from Tier B.**
Can a reference implementation derive Tier A from Tier B for one reference tyre (e.g. via Project Chrono SCM)? That would give converters a reproducible path instead of guesses.

## Geometry and timing

**Q6. Branching and several lines.** *Partly resolved in v0.3:* `roads[]` and `junctions[]` describe several roads and where they meet (spec §7.1). Which route a race takes through them (a joker lap, alternate lines) is still open.
A rallycross joker lap, a pit lane as its own reference, alternate routes: v0.1 has one reference line. Options:
- several named reference lines, each with its own `s`
- OpenDRIVE junctions only

**Q7. Layouts and reverse direction.** *Resolved in v0.1:* `layouts[]` (spec §3.5).
A layout replaces `reference`, `timing` and `race` wholesale; a reverse layout drives the base line backwards.

Still open: a layout on a partly different road (a cut-through) has its own reference line, but its surface bands still sit on the base line. Its new road's surfaces must come from a mesh or from OpenDRIVE. Should layouts be able to add bands on their own line?

**Q8. Which vehicle point does a pose place?**
v0.1 places the SVJ origin (front-axle midpoint). Real grid boxes are defined by the front of the car or the front wheels. Should the pose say which?

**Q9. Pacenote vocabulary.**
The ascending 1–6 scale and the modifier list are a first cut. RBR, the RSF plugin, DiRT and real crews differ. Needs a mapping table per source and a review by someone who writes notes.

**Q10. Track limits beyond wheel counting.** *Partly resolved in v0.3:* restricted zones with penalty, reset, speed-limit and no-entry rules (spec §10.1). Per-corner sporting rules stay out of STJ.

## Format

**Q11. Strict schema.**
STJ rejects unknown keys at schema level (deviation from SVJ, spec §2). *Decide* whether to keep it, or follow SVJ and warn instead.

**Q12. Single-file delivery.** *Resolved in v0.3:* a `.usdz` with the STJ document inside the USD layer (spec §7.8). The folder form stays, and `stj_usd.py extract` always gives the JSON back.

*Original question:*
Blender's glTF exporter writes custom properties to `extras` (verified), so a whole STJ document could ride inside one `.glb` (`scenes[0].extras.stj`). That is attractive for "one file per track", but it hides the JSON from people and tools. Proposal: allow it as an optional packaging, never as the only form.

**Q23. OpenUSD as the rich container.**
Probed in Blender 5.2 (`docs/blender_mapping.md` §4): USD holds everything STJ needs, which glTF cannot. That covers per-face primvars, curves, physics, audio, variants and payloads. Blender's exporter covers about half of it; `pxr` writes the rest. *Decided* 2026-11-03 (`proposals/stj_usd_proposal.md`): USD meshes next to glTF, plus the STJ document inside the USD layer (a `.usdz` is a single-file track). Typed USD schemas later. The JSON stays normative. *Since then (v0.3):* USD became the only mesh format (spec §7.7).

**Q13. Vertical datum and heights.**
Ellipsoidal vs geoid heights only matter for survey data, but a converter from GNSS data must know which it has. v0.1 has `vertical_datum` as free text; it should become EPSG codes.

**Q14. Large worlds.** *Resolved in v0.3:* chunks along s with local origins, a tile grid, several terrains (spec §7.6). Streaming budgets stay the engine's.

**Q15. Licences of converted content.**
*Partly:* `assets[]` records a licence and hash per file (spec §5.3) and the validator warns when a file says it can be redistributed while an asset says not. `redistributable: false` is still a flag, not enforcement. Should validators refuse to run in "publish" mode on such files, and should converters refuse to write output outside the user's folders?

## Survey additions (`docs/feature_survey.md`)

**Q16. Which candidates enter v0.2?** *Resolved:* all of Tier 2 (`proposals/stj_tier2_proposal.md`). Tier 3 remains for later.

**Q19. Variant consistency across layouts.**
A night override patches the base file. If a variant must differ per layout (RBR pacenotes per skybox), it has to repeat the layout's whole `race` block, because arrays are replaced. Is that acceptable, or do variants need a layout key?

**Q17. Terrain.** *Resolved:* a first-class heightfield (spec §7.4).

**Q18. Animations.** *Resolved:* animations are authored in the USD stage and referenced by a `time_range` (they were glTF animations in the first drafts), driven by a closed signal vocabulary with declarative conditions (spec §8.5, §11.1).

**Q20. Growing the signal list.**
The list is closed so that converters can rely on it. New signals (headlights on, safety car deployed per sector, crowd density) arrive as `x_<engine>_…` first. When should one be promoted, and who decides?

**Q21. Calibrating drying.**
`drain_rate` and `storage_depth` are physical quantities, but each engine evolves water with its own model. Is there a reference drying procedure (a film of 1 mm with no rain: time to dry) that converters could fit each engine to, like Q4 for friction?

**Q22. Rubber and sweeping numbers.**
The example `grip_gain` values are estimates. Published tyre-on-rubbered-asphalt data, or a fit to rF2 RRBIN presets, would replace them.
