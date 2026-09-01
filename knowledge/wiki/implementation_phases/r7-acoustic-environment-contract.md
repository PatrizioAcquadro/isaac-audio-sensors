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

R7.1 keeps `AudioSceneSnapshot.environment` optional until R7.2. The current PyRoom backends accept only `shoebox`; they reject the other four topologies reserved for R8, take propagation settings from backend construction or `[audio.room_acoustics]`, and fail when a source or microphone lies outside the shoebox. Kit temporarily retains its explicit array-centered shoebox when no anchor is selected.

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

#### Implementation

Provide three equivalent paths into the same contract:

- TOML is the text path used by CLI and headless workflows; geometry is not duplicated across many command-line flags.
- Python builders provide direct library construction.
- Isaac derives the environment from an explicit anchor, one uniquely resolved acoustic volume, a floor, or a manual configuration.

An environment is always explicit. Missing configuration or failed USD resolution is an error; `None` never invents a room or silently means free field.

Isaac containment considers the complete microphone array with a geometric tolerance. One containing volume is selected automatically. Multiple valid volumes use explicit priority and then the smallest valid containing volume; unresolved ambiguity requires manual selection. A source in another room is not clamped into the array's room.

#### Key Decisions

- Remove the implicit Kit shoebox centered on the array.
- Arbitrary unmarked USD geometry is not guessed to be a room.
- The CLI loads the canonical configuration instead of owning a second geometry interface.

#### Problems / Limitations

Containment identifies the array's local acoustic volume but does not solve propagation through doors, corridors, or intermediate rooms. That behavior belongs to R10.

## Artifacts

R7.1 provides the two immutable Core specs; public builders for all five topologies and shoebox bounds; world/environment quaternion transforms; one fail-closed TOML model; migrated PyRoom, Isaac, Kit, examples, smokes, and downstream contract coverage; and Kit binding schema `ias.omni_extension_binding.v2`.

The frame, dataset-manifest, and calibration-profile schemas remain v1 because they do not serialize the scene. R7.2 input resolution and environment mandatory-state work remain future scope.

## Files

- `src/isaac_audio_sensors/core/types.py`
- `src/isaac_audio_sensors/core/acoustics/environments.py`
- `src/isaac_audio_sensors/core/config.py`
- `src/isaac_audio_sensors/core/backends/room_acoustics/`
- `src/isaac_audio_sensors/isaac/`
- `src/isaac_audio_sensors/kit/`
- `tests/contract/`, `tests/unit/`, `tests/integration/`, and `tests/isaac/`
