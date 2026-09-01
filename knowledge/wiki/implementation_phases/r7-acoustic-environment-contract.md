# Phase R7 — Acoustic Environment Contract

## Objective

Define one explicit, simulator-independent description of the simplified acoustic environment. This phase owns environment meaning and input resolution only; propagation belongs to R8 and arbitrary USD geometry belongs to R10.

## Subphase R7.1 — Unified Environment Model

Status: implemented on 2026-09-01.

#### Implementation

Introduce one pure-data analytic environment contract with a world pose and acoustically meaningful surfaces in environment-local coordinates.
Sources and microphones remain world-frame entities and are transformed into the environment frame before propagation.

The contract supports five concise configurations without a public class hierarchy:
- `free_field`: explicitly no surfaces;
- `half_space`: one floor plane without walls or ceiling;
- `shoebox`: a closed rectangular enclosure;
- `polygon_prism`: an extruded closed floor polygon, including L-shaped rooms;
- `surface_set`: a bounded set of floor, wall, or ceiling surfaces for simple open environments.

Common configurations use builders or presets. `dimensions_m` is a shoebox convenience, while general shapes use local surface vertices. The environment world pose handles translated, rotated, or inclined configurations without encoding world coordinates into reusable local geometry.

At the R7.1 cutoff, `AudioSceneSnapshot.environment` remained optional. R7.2 replaces that temporary state with a mandatory environment. The current PyRoom backends accept only `shoebox`; they reject the other four topologies reserved for R8, take propagation settings from backend construction or `[audio.room_acoustics]`, and fail when a source or microphone lies outside the shoebox. The R7.1 Kit array-centered fallback has been removed.

The new contract replaces `RoomAcousticsSpec` outright. R7 migrates `AudioSceneSnapshot.room`, configuration, schemas, Isaac, Kit, examples, and every active consumer to one canonical environment field, then removes the old type and room-only configuration surface. It does not retain a wrapper, alias, parallel `room`/`environment` fields, or compatibility parser once the migration is complete.

#### Key Decisions

- One analytic environment contract replaces separate public room classes and backends.
- `RoomAcousticsSpec` is removed after its active consumers migrate; it is not preserved as a deprecated shoebox wrapper.
- A floor-only scene is half-space, not free field.
- An L-shaped room is one polygon prism, not overlapping shoeboxes.
- Separate real rooms are not merged into one analytic box.
- Isaac anchors remain simulator-layer inputs and are not stored in the Core contract.
- `room_acoustics` and `room_acoustics_srp` remain backend identifiers until R8.

#### Problems / Limitations

The contract intentionally represents simple analytic surfaces, not arbitrary scene meshes, portals, or a complete multi-room acoustic graph. This is a deliberate breaking cleanup: obsolete room-specific types and duplicate configuration paths do not remain in the maintained package.

## Subphase R7.2 — Input and Isaac Resolution

Status: implemented on 2026-09-01.

#### Implementation

Provide three equivalent paths into the same contract:

- TOML is the text path used by CLI and headless workflows; geometry is not duplicated across many command-line flags.
- Python builders provide direct library construction.
- Isaac derives the environment from an explicit anchor, one uniquely resolved acoustic volume, a floor, or a manual configuration.

An environment is always explicit. `AudioSceneSnapshot.environment` and the TOML `[environment]` table are required for every backend. Missing configuration or failed USD resolution is an error; `None` never invents a room or silently means free field.

`IsaacEnvironmentResolutionCfg` exposes `manual`, `anchor`, and `auto` modes, candidate roots, and a default containment tolerance of 1 mm. `manual` accepts the complete Core environment. `anchor` accepts a marked acoustic prim or interprets an explicitly selected unmarked bounded prim as a shoebox whose identifier derives from its prim path. `auto` inspects only prims marked with `ias:environment_kind` and `ias:environment_id`.

The USD marker contract accepts `ias:environment_kind = "shoebox"` or `"half_space"`, requires a non-empty `ias:environment_id` for automatic discovery, and accepts optional integer `ias:environment_priority` with default `0`. Existing bounds, world pose, and acoustic-material attributes remain authoritative for geometry and absorption.

Isaac containment considers every microphone position with the configured tolerance. Automatic resolution first selects containing shoeboxes by greatest priority and then smallest volume. Equal-priority, numerically equivalent best volumes are ambiguous and require an anchor. If no volume contains the array, the resolver considers marked half-space floors; multiple maximum-priority floors are ambiguous. Malformed marked candidates, missing valid candidates, and arrays outside an explicit anchor fail with direct errors.

The stage cache re-resolves after array motion or relevant changes to bounds, transforms, markers, or acoustic materials and reuses the prior result on unchanged ticks. Source poses remain in their original world coordinates; resolution never clamps or moves them, so PyRoom may still reject a source outside a selected shoebox.

Kit exposes `unconfigured`, `manual_free_field`, `anchor`, and `auto`. `unconfigured` blocks validation and sensor start, maintained safe presets choose `manual_free_field`, and binding/configuration schema `ias.omni_extension_binding.v3` serializes the mode, anchor, tolerance, resolved result, and provenance. Version 2 is rejected without a compatibility path.

#### Key Decisions

- Remove the implicit Kit shoebox centered on the array.
- Arbitrary unmarked USD geometry is not guessed to be a room.
- The CLI loads the canonical configuration instead of owning a second geometry interface.
- Do not use prim paths as hidden ambiguity tie-breakers.

#### Problems / Limitations

Containment identifies the array's local acoustic volume but does not solve propagation through doors, corridors, or intermediate rooms. `polygon_prism` and `surface_set` remain manual Python/TOML inputs until R10. Arbitrary scene geometry and cross-room behavior also belong to R10.

## Artifacts

R7 provides the two immutable Core specs; public builders for all five topologies and shoebox bounds; world/environment quaternion transforms; one mandatory fail-closed TOML model; `IsaacEnvironmentResolutionCfg`; marked-USD resolution; cache-aware live refresh; migrated PyRoom, Isaac, Kit, examples, smokes, and downstream fixtures; and Kit binding schema `ias.omni_extension_binding.v3`.

The package remains unreleased at `3.0.0`. The frame, dataset-manifest, and calibration-profile schemas remain v1 because they do not serialize the scene.

## Files

- `src/isaac_audio_sensors/core/types.py`
- `src/isaac_audio_sensors/core/acoustics/environments.py`
- `src/isaac_audio_sensors/core/config.py`
- `src/isaac_audio_sensors/core/backends/room_acoustics/`
- `src/isaac_audio_sensors/isaac/environment_resolution.py`
- `src/isaac_audio_sensors/isaac/stage_snapshot.py`
- `src/isaac_audio_sensors/isaac/stage_cache.py`
- `src/isaac_audio_sensors/kit/`
- `tests/contract/`, `tests/unit/`, `tests/integration/`, and `tests/isaac/`
