# Consistency audit

Where the parts of this repository agree and where they do not, as of the v0.3 draft. The five layers are the schema (`schema/`), the spec (`spec/STJ_Spec.md`), the Blender profile (`spec/STJ_Blender_Profile.md` and `tools/blender/`), the core and tooling (`tools/`), and the tests (`tests/`).

| Status | Meaning |
|---|---|
| **consistent** | All the layers that apply say the same, and a test shows it. |
| **partial** | The layers agree on what they cover, but one does not cover all of it. The note says which. |
| **contradictory** | Two layers say different things. None is open at the time of writing; this is where one would be listed. |
| **missing** | A layer that should cover it does not. |
| **not applicable** | The layer has no reason to cover it. |

| Area | Schema | Spec | Blender profile | Core and tooling | Tests | Notes |
|---|---|---|---|---|---|---|
| Version list (`0.1`, `0.2`, `0.3`) | consistent | consistent | consistent | consistent (`migrate.VERSIONS`) | consistent | One list in four places; a test of `migrate` covers the steps. |
| `(s, t)` and the reference line (§4.2) | not applicable | consistent | consistent | consistent (`ReferenceLine`) | consistent | The nearest-point definition and the 1 mm tolerance are in the spec and exercised. |
| Closed lines, lap distance | consistent | consistent | consistent | consistent | consistent | |
| Roads, junctions, routes (§7.1) | consistent | consistent | partial | consistent | consistent | Routes stay in the Blender text block; there is no route object. |
| Layouts (§3.5) | consistent | consistent | partial | consistent | consistent | The profile has a `layout` category; editing a layout's `s` values in Blender is not checked. |
| Overrides and `ops` (§3.3) | consistent | consistent | not applicable | consistent | consistent | The profile does not apply override files; the user resolves them first (profile §2.1). |
| Conformance profiles (§3.7) | consistent | consistent | not applicable | consistent | consistent | |
| `position_ref` (§3.8) | consistent | consistent | partial | consistent | consistent | Cameras and emitters with a `position_ref` stay in the text block, because a moved object has nothing to write back to. Poses (grid, pit boxes) do not accept it. |
| Surfaces, STJ-REF, grip (§6) | consistent | consistent | consistent | consistent | consistent | The merge and blending rules (§6.3, §6.4) have a worked example in the spec and tests. |
| Tyre class list | missing | partial | not applicable | consistent | consistent | The list in §6.2 is the working list; where it should live is an open decision with the SVJ side. |
| Collision prims (§7.2) | not applicable | consistent | consistent | consistent | consistent | |
| Material fidelity, MaterialX (§7.7) | not applicable | consistent | partial | consistent | consistent | Blender's importer reads MaterialX nodes only in part; the preview surface is the fallback. |
| Layered ground (§8.7) | consistent | consistent | consistent | consistent | consistent | Texture formats: PNG and DDS for layer textures, PNG for data rasters. |
| Terrain and water (§7.4, §7.5) | consistent | consistent | consistent | consistent | consistent | |
| Identity and names (§7.9, profile §3) | consistent | consistent | consistent | consistent | consistent | The id is authoritative; renaming is a new entity, `.001` is ignored and duplicates are an error (profile §3.1). |
| Merge precedence and deletion | not applicable | consistent | consistent | consistent | consistent | Profile §2.1. |
| Validator diagnostics | not applicable | partial | not applicable | partial | consistent | `--json` gives severity, path, JSON Pointer and message. Messages have no stable codes yet (spec §15.1: proposed). |
| Conversion report | not applicable | consistent | not applicable | consistent (`ConversionReport`) | consistent | Spec §3.12. Converters in other repositories adopt it on their own schedule. |
| Large worlds, probes, screens, crowds, animated objects | consistent | consistent | partial | partial | partial | Marked experimental (§15.1). Fewer readers, fewer cross-checks. |
| Examples for every feature | not applicable | not applicable | not applicable | not applicable | partial | Open item T9 of `proposals/stj_simulator_proposal.md`: `vertex_dense`, `image`, `id_map`, `contact: dominant` and others have no example yet. |

## How this table is kept honest

- The rows with a test are those a test covers by name; a row says **consistent** only when a test runs against the claim.
- `tests/test_handoff.py` checks that every `§n.m` reference in the README, the changelog, the docs and the tools points at a heading that exists in the spec.
- A **contradictory** row is a bug. It gets a changelog line when it is closed and the row goes back to consistent.
