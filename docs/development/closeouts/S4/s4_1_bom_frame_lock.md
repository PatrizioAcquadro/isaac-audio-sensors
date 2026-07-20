# S4.1 closeout - rig, mount, geometry, and frame lock

Status: **blocked** (2026-07-20). The functional S4 acceptance amendment is
frozen at `86d2a5a3bf8b5aba3e2a2c988fc893d92ed6f368`. S4.2 is not authorized.

## Scope and authority

This closeout evaluates the `S4.1` row in
[`s0_squadbot_readiness_acceptance.md`](../../specs/s0_squadbot_readiness_acceptance.md)
for `S4_TEMP_DESKTOP_FIXTURE_REV0`. The fixture's electronic and practical
checks pass, but the evidence-integrity gate does not: the exact nominal CAD
transform JSON and an immutable retrievable companion-release locator are not
available. The missing source is not reconstructed from prose.

The authoritative records are:

- [`s4_1_evidence_index.md`](s4_1_evidence_index.md) for tracked/archived
  evidence, hashes, retrieval, and the remaining blocker;
- [`reference_rig_hardware_environment.md`](../../../reference_rig_hardware_environment.md)
  for hardware, environment, topology, measurements, and limitations;
- [`zed_respeaker_mount_model_handoff.md`](../../../zed_respeaker_mount_model_handoff.md)
  for the unverified companion-CAD handoff; and
- `outputs/isaac_audio_sensors/S4/S4.1/evidence_index.json`,
  `rig_frame_lock.json`, `live_fixture_gate.json`, and `cad_provenance.json`
  for machine-readable status.

## Passing functional fixture checks

- ZED 2i serial `39011785` remains on the verified rear USB 3 path with SDK
  `5.4.0`, camera firmware `1523`, and sensor firmware `777`.
- ReSpeaker serial `114993701261100454`, firmware `2.0.8`, records six-channel,
  16 kHz, `S16_LE`: Conference, ASR, then raw microphones 0 through 3.
- Project coordinates are `+X` forward, `+Y` right, and `+Z` up. The axes and
  corrected fixture footprint are marked.
- The tape-measured approximate ReSpeaker-center position from the ZED stereo
  midpoint is `(-0.085, 0.000, +0.095) m`, with `+/-0.005 m` practical
  uncertainty per component. It is not a calibrated optical/acoustic extrinsic.
- The six-channel WAV is 20.000 seconds and 320,000 frames; every channel is
  non-silent and no channel contains a full-scale sample.
- The original obstructed FOV attempt is retained. After the complete fixed
  assembly moved to the front edge, the tracked runner produced 300 image,
  depth, and sensor reads with zero grab failures and strictly increasing
  timestamps. Full-resolution review of the retained unaltered final image
  found no person or personal identifier, so the privacy-clean media check
  passes.

## Blocking CAD provenance

The handoff reports a 90 mm CAD mechanical-center separation, Fusion cloud
version 9, release paths, and release-file checksums. Those statements do not
substitute for the exact `parameters/T_zed_from_array_nominal.json` bytes or a
locator from which the sealed release can actually be retrieved.

Searches of the repository, current workstation, local CAD remnants, and
connected Drive found no exact transform JSON, F3D release, sealed release
directory, or retrievable immutable release URL. The surviving local export is
STL-only. `outputs/isaac_audio_sensors/S4/S4.1/cad_provenance.json` records the
search and blocker without inventing the missing transform.

To unblock S4.1, recover one of the following and verify it against its source:

1. the exact nominal transform JSON, tracked with its SHA-256; or
2. an immutable retrievable release locator containing that JSON, plus the
   release checksum and exact retrieval procedure.

## Evidence retention and verification

The evidence index names every S4.1 JSON record, authoritative document,
closeout, retained media artifact, run log, validator, and checksum. Raw files
that match repository ignore rules are force-tracked in the S4.1 evidence
snapshot so a clean checkout retains them. The index documents exact recovery
from the annotated evidence tag and per-file SHA-256 verification.

Run:

```text
.venv/bin/python scripts/validate_s4_1_integrity.py --json
sha256sum -c outputs/isaac_audio_sensors/S4/S4.1/evidence_manifest.sha256
make test
make lint
make build
make check-version
git diff --check
```

The S4.1 validator must fail until CAD provenance passes. This is a blocked
closeout, not authorization to start S4.2.
