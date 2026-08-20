# Current Status

Updated: 2026-08-20. Package version: `1.10.0`.

## Product Boundary

`isaac-audio-sensors` is a reusable robot-audition SDK. It owns pure audio
contracts and backends, recording and replay, optional Isaac Sim and Isaac Lab
integration, and the Kit extension. Robot-specific policies, measurement
campaigns, and downstream adapters remain outside this repository.

## Verified Capabilities

- Stable frame, calibration, manifest, serialization, plugin, and CLI
  contracts with packaged JSON Schemas.
- Deterministic geometry and synthetic TDOA backends plus optional room
  acoustics.
- Recording, replay, codecs, GUI/headless flows, filesystem behavior, and
  plugin discovery.
- Lazy Isaac Sim, Isaac Lab, Kit, Omnigraph, and GPU/runtime integration.
- Wheel, source archive, Kit extension, and optional acoustics-pack content
  policy.

The 2026-08-20 cleanup gate passed 414 host tests, 366 integration tests, 27
release tests, and 116 Isaac tests. The Isaac lane used the Isaac Lab
interpreter with the workstation RTX 4090. Wheel, source archive, and Kit
artifacts passed content inspection. See
[[implementation_phases/r2-r3-test-and-boundary-cleanup|R2-R3 Test and Boundary Cleanup]].

## Commands

- `make test` — host unit and contract tests; required below 10 seconds.
- `pytest tests/integration` — host integration tests.
- `make test-release` — archive and release policy.
- `make test-isaac` — Isaac tests through the Isaac Lab interpreter.
- `make test-all` — all lanes in dependency order.

## Limits

- Isaac tests require a compatible local Isaac runtime; GPU checks do not use
  a CPU fallback.
- `room_acoustics` requires its optional dependencies.
- Simulation correctness does not establish physical acoustic fidelity or
  sim-to-real validity.
- Retained historical scientific evidence is local, ignored, and excluded
  from distributions.

## Next Work

Advance product features only through semantic contracts and owner-specific
tests. Keep downstream project fixtures and experiment evidence with their
owners.
