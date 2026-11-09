# Proposal: additions from the v0.4 handoff

Status: accepted, implemented in v0.3.
Source: a third-party document, "STJ v0.4 Full Repository Owner Handoff", reviewed point by point with the repo
owner. Parts of it were stale or proposed a wholesale rename and restructure; only additive ideas were kept.

## Decisions

| # | Point | Chosen |
|---|---|---|
| 1 | Conformance profiles | `_metadata.conformance`: `core`, `race`, `rally`, `physics`; declared and checked by the validator |
| 2 | Surface function | New `function` enum; `class` is unchanged |
| 3 | Data quality | New `quality {basis, confidence, method}`; `_est` stays valid |
| 4 | Routes in sessions | `race.route_policy {default, by_session}` |
| 5 | Pace notes and lines per vehicle | `race.pacenote_sets[]` with `vehicle_class`; `racing_lines[].vehicle_class`; the current fields stay |
| 6 | Variant patches | A table of which arrays have an identity, and override `ops` (add, replace, update, remove by key) applied after the merge patch |
| 7 | Tooling and versions | `tools/canonicalize.py`, `tools/migrate.py`, deprecation policy: one minor version of WARN before removal |
| 8 | Positions in a frame | Optional `position_ref {reference: world | road:<id> | route:<id>, s, t, z}` on new entities (cameras, audio emitters); existing fields unchanged |

## Not adopted

- The v0.4 rename and restructure of existing sections: it would break every existing file for no new capability.
- An `extensions` object replacing `x_` keys: `x_` keys already work and tools already ignore them.
- Absolute `peak_mu` and `sliding_mu` in place of the factors on STJ-REF: `reference_mu` already gives absolute values.

## Notes

- `position_ref` is accepted on cameras and audio emitters only. Poses (grid, pit boxes, spawns) keep their two forms, so
  the Blender round trips are untouched. The Blender profile leaves a camera or emitter that has a `position_ref` in the
  text block.
- Pace notes keep `s`; a note at a position in another frame would need a different model and was left out.

## Added after the second review

- Compatibility (backward, forward, semantic) is now spec section 3.11.
- The definition of done (schema, spec text, example, validator check, migration, test together) is stated in the README.
