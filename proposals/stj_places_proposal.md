# Proposal: names, tags, buildings and areas

Status: accepted, implemented in v0.3 (spec §7.9).
Source: the repo owner's request that the standard keep the names of roads, streets and buildings, because an
editor will take real-life data; gap list sections B2, D1 and D2 (TrackCreator).

## Problem

`roads[]` and `structures[]` had a `name` and nothing else. Data from OpenStreetMap or a cadastre has a road
class, a speed limit, a house number, the identity of the element it came from, and buildings and land use
that STJ could not hold. A converter had to drop them or hide them in `x_` blocks that no other tool reads.

## Decisions

| # | Decision | Chosen |
|---|---|---|
| 1 | Scope | Names and tags, buildings and areas (gap list B2, D1, D2) |
| 2 | Building | Footprint ring, holes, height or levels, roof shape, class, optional authored mesh |
| 3 | Area | Polygon with holes and a class enum (residential, commercial, industrial, farmland, forest, grass, park, water, wetland, parking, paddock, spectator, quarry, other) |
| 4 | Tags and identity | `tags {string: string}` kept as given, and `source {id, osm_id, key}` pointing at `provenance.sources[]` |

## Fields

- `name`, `ref`, `tags`, `source` on `roads[]`, `structures[]`, `junctions[]` and `edges[]` (`name` and `ref` on
  buildings and areas too).
- `buildings[] {id, name, ref, class, footprint, holes, z, height, levels, roof {shape, height, heading}, mesh, tags, source}`.
- `areas[] {id, name, class, polygon, holes, tags, source}`.

Tags are free text: STJ records and never judges (the same rule as the licences). The class enums are only for
what an engine needs to pick a model or a texture; the real meaning stays in the tags.

## Left open

- ~~Roads' class and speed as typed fields~~ Done later: `road_class`, `speed_limit`, `lanes`, `oneway`, and road `markings[]` (spec §7.10).
- ~~Building parts and addresses as fields~~ Done later (spec §7.9). Indoor data: floors and spaces for garages, workshops, hospitality and control rooms (spec §7.9); detailed interiors stay outside STJ.
- Mapping areas to ground layers, scatter and water automatically.
- Retaining walls, portals, road markings and the rest of gap list sections B to D.
