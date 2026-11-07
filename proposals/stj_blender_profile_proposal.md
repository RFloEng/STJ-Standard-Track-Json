# Proposal: the STJ Blender profile and the official Blender translator

Status: accepted (all five decisions as recommended). First slice implemented: profile 0.1
(`spec/STJ_Blender_Profile.md`), export, import and lint (`tools/blender/`), the reference `.blend`, the geo
origin and the sun. Still to do: meshes and collision collections, roads, and the other rows as they are probed.
Source: question from the repo owner: can a standard `.blend` be defined from the STJ entities, so that
every conversion to and from Blender stays consistent between translators, and where should the
STJ-to-Blender translator live?

## Problem

STJ uses Blender as the hub where tracks from several sims are finished (`docs/blender_mapping.md`).
The conventions for that exist (section 3 of that document: object, empty, collection and material
names, custom properties, the text block), but only as advice, and part of them was never probed.
Each converter author can read them differently, so a track that leaves one sim, passes through
Blender and goes to another can lose or change data depending on which translators touched it.

## Proposal

### 1. The STJ Blender profile (normative)

A profile is a set of rules for a `.blend` that a translator writes and reads. It sits beside the
USD delivery package: the `.blend` is the authoring file, the USD stage with the document in
`customLayerData["stj"]` stays the delivery format.

- **Source of truth.** The STJ document stays normative. The text block `track.stj.json` is the base
  document; data on Blender objects and materials is applied over it as an RFC 7396 merge patch, objects
  win (already the rule in `blender_mapping.md` section 2). The profile adds one rule: after an import
  the scene and the text block agree, and the checker reports any disagreement.
- **Entity map.** The table in `blender_mapping.md` section 3 becomes the profile's entity map, one row
  per STJ entity: name pattern, Blender type, custom properties, and the STJ path it fills. Rows not yet
  probed get probed before they become normative (the "not probed yet" table: roads, junctions, routes,
  structures, decals, `source: generated`, `assets[]`).
- **New rows for v0.3.** `routes[]` (a curve chain or a text-block entry), `continues[]` (an empty pair),
  `provenance.sources[]` (text block), collision and `physics` per prototype (Rigid Body, with the
  `breakable` flag as a custom property).
- **Profile version.** A scene property `stj_blender_profile = "0.1"`, so a translator can refuse a file
  from a newer profile and the checker applies the right rules.
- **Reference `.blend`.** One small file that uses every row of the map, kept in `tests/` or `examples/`
  as the conformance fixture. A translator is conformant when it round-trips the fixture.

### 2. The round-trip contract

Export and import are inverse, up to the documented losses:

1. `.blend` to STJ document + USD (export), then back to `.blend` (import), gives a scene whose document
   equals the first one, and the second export equals the first.
2. The documented losses (`blender_mapping.md` section 4: physics, audio, actions and sky come back only
   from the document, not from USD) are listed in the profile, so a translator knows which fields it must
   restore from the text block.
3. The test runs without Blender where it can: on the document and the USD (`pxr` is enough). The part
   that needs Blender (scene to document) is a separate, optional test.

### 3. The checker

`tools/blender/lint_blend.py`, run inside Blender (`--background --python`), reports as `validate.py`
does (ERROR, WARN, NOTE): missing reference curve, unnamed or unknown surface material, a gate empty
that does not project onto the reference line, object data that disagrees with the text block, a name
that does not match the pattern, a profile version it does not know. It shares the report format and
`stj_core` with the validator.

### 4. Where the official translator lives

In this repository, under `tools/blender/`:

- `stj_blender/` a Blender add-on: **Export** (scene to document + USD) and **Import** (USD or document
  to scene) with the profile's rules, and the lint as an operator;
- the profile spec as a section of the spec or a document of its own (`spec/STJ_Blender_Profile.md`);
- the reference `.blend` and the round-trip tests.

Game-specific converters (AC, RBR, BeamNG, DR2, rF2, OpenDRIVE) stay in their own repositories. They
read and write STJ or the profile, and Blender is only a hub between them.

Reason: the profile and its translator change together. If the add-on lives elsewhere it drifts from the
profile, which is the failure the profile is meant to prevent. The cost is that the repository is no
longer pure Python: the add-on needs Blender to run. CI keeps running without Blender: the add-on's
Blender-only tests are skipped when `bpy` is missing, and everything else (the profile checks on JSON
and USD) runs as now.

## Decisions

All five were taken as recommended (decision 5 without a separate question, as the recommendation).

| # | Question | Chosen |
|---|---|---|
| 1 | Where the official translator lives | In this repo, under `tools/blender/`; game converters elsewhere |
| 2 | How binding the profile is | Normative for rows that were probed; "advice" for the rest until probed |
| 3 | Which direction first | Export first (`.blend` to document + USD), then import |
| 4 | Profile versioning | Scene property `stj_blender_profile`, the profile version independent of the spec's |
| 5 | The reference `.blend` | One small file in `examples/`, built by a script so it is reproducible |

## Left open

- Whether the add-on should also be published as an installable extension (the Blender extensions
  platform) once it is stable.
- Blender version policy (decided): LTS releases only, to start. The probes so far ran on 5.2 (to be
  confirmed as an LTS release). Each profile row records the lowest LTS version it was tested on, and the
  rows are re-probed on every LTS version in the supported set, because the bundled OpenUSD and the USD
  exporter differ between versions. The checker reports a Blender version outside the set.
- A glTF path: USD stays the delivery format; glTF is not part of the profile.
