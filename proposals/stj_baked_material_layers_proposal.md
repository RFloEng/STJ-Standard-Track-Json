# STJ proposal: baked lighting kept as a material layer

Status: **adopted** 2026-11-27 with the recommended answers of §7, except question 4: the field went into the 0.4 draft, because a reader that ignores it draws the source picture. Spec §7.2 and §14. Written against the STJ 0.4 spec.

Source: the RCX to STJ converter.

---

## 1. The gap

Some games keep painted shadows apart from the ground texture: a second texture layer on the terrain faces, with its own
UVs and weights, that darkens the layer under it. The source can still take them apart. STJ can keep them (the layer
fits in a MaterialX network, §7.7) but has no way to **say what they are**.

§7.2 `baked` lists lighting "stored in the mesh or beside it, so an engine can use it or leave it out":

| Field | Why it does not fit |
|---|---|
| `vertex_colour` | one value per vertex, no texture |
| `shadow_map {uri, texcoord}` | one image per mesh entry, read through one UV set. Here there are several pages, chosen per material, each with a weight per corner. Making one image of them would be a bake, which a converter from a game does not do (§7.7) |
| `specular_map` | not a shadow |

So a converter from STJ to an engine cannot tell this layer from any other two-layer material:

* An engine with real-time shadows that keeps it, and whose trees and fences cast shadows, draws **two shadows**.
* A converter that drops every second layer to avoid that also drops real surface detail.
* A converter to an engine without real-time shadows must keep it, and has nothing that tells it so.

The decision belongs to the converter to the target engine. STJ should give it what it needs to decide.

## 2. Proposed shape

### 2.1 A strength input on the material

A material with a baked layer has an **interface input** on its `UsdShade.Material`:

```
float inputs:stj_baked_strength = 1.0      # 0 = without the baked layer, 1 = as the source draws it
```

Every network of the material that applies the layer multiplies the layer's contribution by this input. Setting it to 0
removes the baked lighting and nothing else. No texture is edited and no information is lost: setting it back to 1
restores the source's picture. It is the same mechanism as the interface inputs of §11.1.

### 2.2 The declaration, beside the other baked lighting

A new list in `geometry.meshes[].baked`:

```json
"baked": {
  "vertex_colour": { "primvar": "displayColor", "role": "light" },
  "material_layers": [
    {
      "material": "mix_0100_0588_gloss",
      "kind": "shadow",
      "input": "stj_baked_strength",
      "layer": { "uri": "textures/A_TX0588.png", "texcoord": "stj_st_b", "weight_primvar": "stj_weight" },
      "op": "darken",
      "space": "encoded",
      "basis": "inferred",
      "note": "page 588 has the outline of a tree crown; used by a layer that only darkens"
    }
  ]
}
```

(The numbers in the material name are an example.)

| Field | Meaning |
|---|---|
| `material` (required) | the `UsdShade.Material` in the mesh's USD file, by name as in §11.1 |
| `kind` (required) | `shadow` (cast shadow), `occlusion` (ambient occlusion), `light` (other baked lighting, such as pools of light) |
| `input` | the interface input of §2.1; default `stj_baked_strength` |
| `layer` (required) | what a reader without MaterialX needs to rebuild or remove the layer: the texture (`uri`), its UV primvar (`texcoord`) and, if the source has one, a per-corner `weight_primvar` (float, 0..1; absent = 1) |
| `op` (required) | how the layer changes the colour under it (below) |
| `space` | the values the operation works on: `encoded` (the stored texel values, as many older games mix them) or `linear` (default) |
| `basis` (required) | `source`: the game's files or code say it is baked lighting. `inferred`: the producer concluded it |
| `note` | free text; with `inferred`, the evidence |

With `s` the strength input, `w` the weight, `C` and `a` the layer texture's colour and alpha, and `U` the colour under
the layer:

| `op` | result |
|---|---|
| `darken` | `U · (1 − s·w·a·C)`: a brighter layer texel darkens more |
| `multiply` | `U · (1 − s·w·a·(1 − C))`: an ordinary shadow or light map, white changes nothing |

Neither changes the alpha of the surface under the layer. A source that does something else is not described by this
list: it keeps its network and its `x_<engine>` data. More operations can be added when a source needs one.

## 3. Rules

**Producers**

* Keep the layer as the source has it. Do not multiply it into the albedo (§7.7).
* The UsdPreviewSurface fallback shows the surface **without** the baked layer.
* Say `basis: inferred` unless the source itself identifies the layer as lighting. Declare only the materials there is
  evidence for. A darkening layer is not a shadow just because it darkens: it can be dirt, a wet patch or paint.

**Consumers**

* By default, draw the layer (strength 1): that is the picture of the source.
* A consumer MAY remove it when the target makes that lighting itself. For `shadow`, this needs the objects that cast it
  to be present in the target **and** to cast shadows there. A consumer that cannot know this keeps the layer.
* The conversion report (§3.12) says which it did: `mapped` if kept, `dropped` with the reason if removed.
* A consumer that ignores the list gets what it gets today.

A §11.1 binding may drive the same input, for example to fade a baked sun shadow under cloud. The rule that no input is
driven twice applies as it stands.

## 4. Validation (validator additions)

* ERROR: `material` is not in the mesh's USD file (needs `pxr`).
* ERROR: unknown `kind`, `op`, `space` or `basis` (schema).
* WARN: the material has no `input`, or its default is not 1.
* WARN: `layer.uri` is missing, or a mesh bound to the material lacks `texcoord` or `weight_primvar`.
* NOTE: one per mesh, with the number of layers of each `kind` and how many are `inferred`.

The schema change is one property: `baked` has `additionalProperties: false`, so `material_layers` has to be added to it.
Until then a producer can write the same list as `baked.x_<engine>.material_layers`, which the current schema allows.

## 5. Where portability is a lie (spec §14 addition)

Removing a baked shadow does not give the same picture back with real-time shadows. The painted shape need not match the
object that casts it, nor the sun of the target. Some games paint a shadow where there is no object at all. And shading
painted **into** an albedo texture stays there: this proposal only covers lighting the source keeps apart.

## 6. The source case

Left out of this copy: it holds the evidence from one game's files.

## 7. Open questions, with a recommended answer

1. **One input name, or one per kind?** One (`stj_baked_strength`): a material has one baked layer in every case seen.
   `input` can name another if a source has more.
2. **Declare it in the document, or as `customData` on the material?** In the document, beside the rest of `baked`, so a
   converter finds all baked lighting in one place and does not need to walk the materials.
3. **May a producer declare `inferred` layers at all?** Yes, marked as such with the evidence. The consumer decides how
   far to trust it, and its default (draw the layer) is safe either way.
4. **A new minor version?** Yes. The change only adds an optional field.
