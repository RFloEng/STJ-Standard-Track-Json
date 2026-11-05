# STJ proposal: LiDAR and other scan sources

Status: **accepted** 2026-11-05 with the recommended answers of §7 (D1 to D6; D6 extended to include the helper tool), for STJ v0.4.

Source: a design discussion. Many real tracks and stages start as an airborne or mobile LiDAR survey (national mapping agencies publish them as open data), and the same holds for photogrammetry and GNSS surveys. STJ has a label for this (`provenance.scan`) but nothing that connects a track to the survey it came from.

---

## 1. The gap

Today `_metadata.provenance.scan` is `{method, date, accuracy, operator}`. That says a track was scanned. It does not say:

- **Which survey.** There is no pointer to the original point cloud, its coordinate system, its vertical datum, its point density or its classification.
- **Which part of the file came from it.** The terrain heightmap, the OpenCRG road surface, the tree positions and the buildings may each come from the cloud, with different settings. Nothing records how: ground-only or all returns, grid cell size, how voids were filled.
- **What is measured and what is invented.** A heightmap cell finer than the point spacing is interpolated, and a cell under a tree or a roof is a guess. A reader cannot tell.
- **Voids.** Water, dark tarmac and dense canopy return no points. `geometry.terrain.holes` is for tunnels and cuttings, not for "no data".

Raw clouds themselves do not belong in a track. They run to hundreds of millions of points, no simulator renders them, and STJ's job is a description any engine can rebuild. What belongs in the file is what engines can use (the heightmap, the CRG, the instances) and the record of where it came from, so it can be re-derived at a better resolution later.

## 2. What a cloud gives, and where it already goes

| From the cloud | Goes into | Needs a change? |
|---|---|---|
| Ground-classified points, gridded | `geometry.terrain.heightmap` | A `nodata` value and a derivation record |
| Road-surface points at high density | `geometry.crg` (OpenCRG exists for exactly this) | A derivation record |
| Vegetation points (canopy minus ground) | `scenery.instances` with `class`, `height`; or scatter density | A derivation record |
| Building and bridge-deck points | Meshes, or `structures[]` if that is added | No |
| Fitted road centre line | `reference.centerline` | No (`method: gnss` or `lidar` already) |
| Water-classified points | `water.bodies` outlines | No |

LAS class codes (ASPRS) line up with this and are worth stating in the spec as a table: 2 ground, 3 to 5 vegetation, 6 building, 9 water, 11 road surface, 17 bridge deck.

## 3. Proposed additions

### 3.1 Sources: `provenance.scan.sources[]`

```json
"provenance": {
  "type": "scanned",
  "scan": {
    "method": "lidar",
    "date": "2023-04-12",
    "accuracy": 0.08,
    "sources": [{
      "id": "als_2023",
      "format": "copc",
      "reference": "Institut Cartogràfic i Geològic de Catalunya, LiDAR territorial 3rd cover, tile 0404-1234",
      "crs": "EPSG:25831",
      "vertical_datum": "EGM2008",
      "date": "2023-04-12",
      "point_density": 8.0,
      "accuracy": { "horizontal": 0.30, "vertical": 0.15 },
      "classified": true,
      "licence": { "spdx": "CC-BY-4.0", "holder": "ICGC", "redistributable": true }
    }]
  }
}
```

- `format`: `las`, `laz`, `copc`, `e57`, `ept` or `other`.
- `uri` (relative) is given only when the cloud ships with the track, which is rare. Otherwise `reference` says where it came from (a citation or an address). The cloud is a *source*, not a part of the track.
- `crs` and `vertical_datum` are those of the survey. `environment.geo_reference` stays the track's own projection. Together they let a tool check the reprojection.
- `point_density` is mean ground points per m².
- `accuracy` splits horizontal and vertical. The existing `scan.accuracy` stays as the single stated vertical accuracy of the track's surface.
- `licence` is data about the source, like `_metadata.licence`. STJ records it and does not judge it (the README's position on sourcing is unchanged).

### 3.2 Derivation: what was made from which source

A small reusable `derived` block on the products that came from a scan:

```json
"heightmap": {
  "uri": "terrain/height.png", "format": "png16", "size": [2049, 2049], "extent": [...], "nodata": -9999,
  "derived": {
    "source": "als_2023",
    "product": "dtm",
    "classes": [2, 11],
    "cell_size": 1.0,
    "method": "tin",
    "void_fill": "interpolated"
  }
}
```

- `product`: `dtm` (bare ground), `dsm` (top surface), `chm` (canopy height), `road_surface`, `other`.
- `classes`: LAS classification codes used.
- `cell_size`: grid spacing in metres.
- `method`: free text or `binning`, `idw`, `tin`, `kriging`, `other`.
- `void_fill`: `none`, `interpolated`, `from_other_source`, `flat`.
- It can sit on `geometry.terrain.heightmap`, `geometry.crg[]`, `scenery.instances[]`, `scenery.scatter[]` and `geometry.meshes[]`.

### 3.3 No-data in a heightmap

`heightmap.nodata`: the value (`raw_f32`) or the 16-bit integer code (`png16`) that means "no measurement here", separate from `holes`. Engines fill it from the surroundings. The validator counts the voids and says so in a NOTE.

### 3.4 Resolution against density

Point spacing limits what a heightmap can honestly show: a cell finer than about twice the mean spacing, `2 / sqrt(point_density)`, is interpolated detail. The validator compares `cell_size` (or the heightmap's `extent` / `size`) with the density of the named source and says so in a NOTE. It never blocks anything.

## 4. What this does not change

- **No point-cloud geometry type.** A track does not carry the cloud. If a viewer wants a preview, a decimated cloud may be a plain USD file next to the track, without a role.
- **No new heightmap format.** LiDAR products usually arrive as GeoTIFF float32. STJ does not resample (spec §7.4), and `png16` and `raw_f32` stay the only formats. A converter turns the GeoTIFF into one of them and records that in `derived`.
- **No cloud processing in the standard.** Classification, filtering and gridding are the converter's work.

## 5. Mapping to other formats

| Format | How |
|---|---|
| LAS / LAZ / COPC / E57 | `sources[].format`; the cloud stays outside |
| GeoTIFF DTM | converted to `raw_f32` or `png16`; `derived.product: "dtm"` |
| OpenCRG | the scan's road-surface product; `derived.product: "road_surface"` |
| OpenDRIVE | none; the road centre line comes from `reference` |
| Blender | the heightmap and CRG are ordinary files in the `.blend` package; `derived` travels in the STJ document |

## 6. Validator

- ERROR: `derived.source` names no `sources[]` entry.
- WARN: `sources[].crs` missing when `derived` is given (the reprojection cannot be checked).
- WARN: `accuracy.vertical` larger than the smallest feature STJ claims (for example a `cross_section` crown of 4 cm under a 15 cm vertical accuracy).
- NOTE: heightmap cell finer than `2 / sqrt(point_density)`.
- NOTE: heightmap voids (`nodata`) and how they were filled.
- NOTE: `redistributable: false` on a source whose product is in the file.

## 7. Decisions (accepted 2026-11-05)

- **D1.** Should sources be recorded at all, or is `provenance.scan` enough? Recommended: **yes, `sources[]`**. Re-deriving a heightmap at a better resolution needs to know the survey.
- **D2.** Should a derivation be recorded per product (`derived` on each), or once for the whole track? Recommended: **per product**. The heightmap and the road surface usually come from different classes and cell sizes.
- **D3.** Should a point cloud ever ship inside a track? Recommended: **no**. Keep `uri` for the rare case, and no geometry role for it.
- **D4.** Should STJ add GeoTIFF as a heightmap format? **Decided 2026-11-05: no.** Keep `png16` and `raw_f32`, because STJ does not resample, and let a converter write them and record the original file in `derived`. The alternative considered was a restricted `geotiff_f32` subset (uncompressed, single band, striped, with the validator comparing the file's own georeferencing to `extent`); it can be reopened if hand-converting GeoTIFFs turns out to be common.
- **D5.** Should the resolution-against-density check be a NOTE or a WARN? Recommended: **a NOTE**. Finer cells are sometimes right (smoothed, or backed by a second source).
- **D6.** Scope now? **Decided: everything, including the helper** that turns a classified LAS tile into a heightmap and a derivation record. (Recommended was to leave the helper for later.)
