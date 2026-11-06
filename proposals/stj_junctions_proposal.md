# Proposal: junction logic, continuations and routes

Status: accepted, implemented in v0.3 (spec §7.1, §3.5).
Source: `STJ_gap_list_for_repo_owner.md` (TrackCreator), section A, and open question Q6.

## Problem

A junction was `{id, roads[{road, s}]}`: "these roads meet here". That cannot say which road is the
through road, how a joining road meets it, whether two roads cross without connecting, or whether two
road pieces are one road cut in two. And there was no way to describe a lap or a stage that runs over
several roads, so a converter reported that closed loops could not be expressed.

## Decisions

| # | Decision | Chosen |
|---|---|---|
| 1 | Scope | A1 to A6 and a route. A7 (crossing geometry) limited to `corner_radius` and an authored `mesh`. |
| 2 | Route `s` | Continuous along the route: the sum of the step lengths. |
| 3 | Join of a joining road | `join {mode: centre \| edge_snap, reach}` and `end: start \| end \| mid`. |
| 4 | The rest | `continues[]`, `kind`, `height {mode, radius}`, a tolerance and joint-point rule. |

## Mapping to the gap list

| Gap | Field |
|---|---|
| A1 through road, rank | `junctions[].through`, `roads[].rank` |
| A2 how the road meets | `roads[].join {mode, reach}`, `roads[].end` |
| A3 tolerance | 5 m (`JOINT_GAP`); the joint is the through road's point, else the first member's |
| A4 continuation | `continues[] {from, to}` |
| A5 height continuity | `junctions[].height {mode: pinned \| blend, radius}` |
| A6 at grade or not | `junctions[].kind` (`grade_separated` ties to `structures[]`) |
| A7 corners | `roads[].corner_radius`, `junctions[].mesh`; the shape is not described |

Not adopted: physics joints (hinges, chains). STJ has `prototype.physics` and `breakable` only; the
gap list marks the reading as ambiguous and TrackCreator has none either.

## Routes

`routes[] {id, closed, steps[{road, s_start, s_end, direction}]}`; a layout's `route` makes it the
layout's reference line (`layout_document` chains the steps into one centerline). Timing, pacenotes
and lap counting then work on the route's `s` unchanged. The chained line carries points only: each
road's profile, widths and terrain rule stay on that road. Reversing a route is reversing its step
list and flipping each direction.

## Left open

- Alternate lines inside one race (a joker lap chosen during the run).
- Crossing geometry beyond `corner_radius` and an authored patch.
- Sections B to E of the gap list (markings, retaining walls and portals, land cover, buildings and
  areas, non-scan provenance): a separate backlog.
