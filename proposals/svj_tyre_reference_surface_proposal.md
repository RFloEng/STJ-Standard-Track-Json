# SVJ proposal: the surface a tyre was fitted on (for SVJ v0.105)

Status: **proposed**, accepted for STJ on 2026-11-02. To be applied in the SVJ repository. Additive; no existing file changes meaning.

## Problem

`tires.sets.<id>.reference` records the conditions of the Magic Formula coefficients: load, pressure, speed and camber. It does not record the **surface**. Rig data is fitted on abrasive belts; a game's tyre is fitted to that game's road; a gravel tyre is fitted to gravel. Without this field no track format can scale grip correctly: STJ surfaces are relative to STJ-REF, dry clean dense asphalt (STJ_Spec §6.2).

## Change

Two optional fields:

```json
"tires": { "sets": { "gravel_r5": {
  "tyre_class": "gravel",
  "reference": {
    "load": 4000,
    "surface": {
      "stj_class": "gravel",
      "mf_scaling": { "LMUX": 0.76, "LMUY": 0.72, "LKX": 0.55, "LKY": 0.6 },
      "description": "Fitted on loose gravel over hardpack",
      "_est": true
    }
  },
  "pacejka": { "model": "MF62", "...": "..." }
} } }
```

| Key | Type | Meaning |
|---|---|---|
| `tyre_class` | enum | `slick`, `road`, `intermediate`, `wet`, `gravel`, `snow`, `studded`, `mud`, `offroad`. STJ surfaces may give values per class (STJ_Spec §6.5). |
| `reference.surface.stj_class` | enum | STJ surface class of the fitting surface |
| `reference.surface.mf_scaling` | object | The fitting surface expressed as STJ factors relative to STJ-REF (`LMUX`, `LMUY`, `LKX`, `LKY`, …). Absent factors are 1. |
| `reference.surface.description` | string | Free text: rig and belt, game, test site |

**Default:** with no `reference.surface`, the tyre describes STJ-REF (all factors 1). Every existing SVJ file keeps its current meaning.

## Use (STJ_Spec §6.4)

```
λ_eff,i = λ_tyre,i · λ_surface,i / λ_tyre_ref,i
```

A tyre fitted on gravel, driven on that same gravel, gets exactly its fitted scaling. On asphalt it gets the ratio.

## Compatibility

SVJ's schema accepts additional properties, so files carrying these fields already validate today. The SVJ change adds them to the schema and the spec (§11.5), adds a `tyre_class` enum check, and makes `tools/tire_model.py` accept an STJ surface to evaluate on.
