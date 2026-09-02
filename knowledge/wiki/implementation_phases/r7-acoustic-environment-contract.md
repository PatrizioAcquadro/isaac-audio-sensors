# Phase R7 — Acoustic Environment Contract

Status: completed on 2026-09-01.

## Objective

Define one explicit, simulator-independent description of a simplified acoustic environment. R7 owns environment meaning and Isaac input resolution; propagation belongs to [[implementation_phases/r8-analytic-acoustics-backend|R8]], while arbitrary USD geometry belongs to R10.

## Core Contract

`AcousticEnvironmentSpec` stores acoustically meaningful surfaces in environment-local coordinates plus one world pose. Sources and microphone arrays remain world-frame entities and are transformed before propagation.

Five public builders cover the maintained analytic topologies:

- `free_field`: no surfaces;
- `half_space`: one floor plane;
- `shoebox`: one closed rectangular enclosure;
- `polygon_prism`: one extruded closed floor polygon;
- `surface_set`: a bounded collection of simple floor, wall, or ceiling surfaces.

`AudioSceneSnapshot.environment` and TOML `[environment]` are mandatory. Missing configuration, invalid geometry, failed containment, or failed USD resolution raises an error; absence never invents a room or silently means free field. `RoomAcousticsSpec`, `AudioSceneSnapshot.room`, and the room-only configuration surface were removed without aliases or parallel parsers.

## Isaac Resolution

`IsaacEnvironmentResolutionCfg` exposes three paths into the same Core contract:

- `manual` receives a complete `AcousticEnvironmentSpec`;
- `anchor` resolves one explicitly selected acoustic prim;
- `auto` selects marked `shoebox` or `half_space` candidates.

Automatic candidates require non-empty `ias:environment_kind` and `ias:environment_id`; optional `ias:environment_priority` defaults to zero. Shoebox selection considers every microphone, then orders containing candidates by priority and volume. Half-space selection is the fallback when no marked volume contains the array. Ambiguous, malformed, missing, or out-of-bounds candidates fail closed rather than using prim paths as hidden tie-breakers.

The stage cache re-resolves after array motion or relevant bounds, transform, marker, material, or partition changes and reuses the result otherwise. Resolution never clamps or moves sources.

Kit exposes `unconfigured`, `manual_free_field`, `anchor`, and `auto`. `unconfigured` blocks validation and sensor start. R7 introduced bindings v2 and v3 during migration; R8 completed the then-current `ias.omni_extension_binding.v4`, later replaced directly by v5 in R9.1.2. Older binding versions have no runtime parser.

## Historical Subphases

- R7.1 introduced the five-topology contract, local surfaces, world transforms, and the direct replacement of room-specific scene state. Environment optionality and binding v2 existed only at this migration boundary.
- R7.2 made environment state mandatory, added fail-closed `manual`/`anchor`/`auto` resolution, full-array containment, cache invalidation, and binding v3.
- R8 later replaced the staged room backends with the single `analytic_acoustics` runtime and binding v4; this does not change R7 environment semantics.

## Decisions and Limits

- A floor-only scene is `half_space`, not `free_field`.
- An L-shaped room is one `polygon_prism`, not overlapping shoeboxes.
- Separate rooms are not merged into one analytic enclosure.
- Isaac anchors remain simulator inputs and never enter the Core contract.
- `surface_set` expresses simple authored surfaces but is not accepted by the R8 analytic provider.
- Portals, multi-room graphs, arbitrary meshes, diffraction, and cross-room propagation remain outside R7.

At the R7 closeout, the unreleased package remained `3.0.0` and all three schemas remained v1 because R7 did not change their serialized shape. R9.1.1 later replaced only the frame contract with v2.

## Current Implementation

- `src/isaac_audio_sensors/core/acoustics/environments.py`
- `src/isaac_audio_sensors/isaac/environment_resolution.py`
- `src/isaac_audio_sensors/isaac/stage_cache.py`
