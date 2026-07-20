# S4.1 closeout - rig, mount, geometry, and frame lock

Status: **passed** (2026-07-20). The functional S4 acceptance amendment is
frozen at `86d2a5a3bf8b5aba3e2a2c988fc893d92ed6f368`. S4.2 is authorized but has
not started.

## Scope and authority

This closeout evaluates the `S4.1` row in
[`s0_squadbot_readiness_acceptance.md`](../../specs/s0_squadbot_readiness_acceptance.md)
for `S4_TEMP_DESKTOP_FIXTURE_REV0`. The fixture's electronic and practical
checks pass. This is the installed, handmade desktop fixture: the ZED and
ReSpeaker are fixed on two inverted plastic supports over a corrugated-cardboard
riser. Its recorded approximate as-used geometry, marked axes and footprint,
and practical checks are the S4.1 authority.

The Revision A Option 1 3D-printed mount was not fabricated or used for S4.1.
Its reported CAD geometry is future-design context only. The unavailable CAD
source is neither reconstructed from prose nor treated as a blocker for the
different installed fixture.

The authoritative records are:

- [`s4_1_evidence_index.md`](s4_1_evidence_index.md) for tracked/archived
  evidence, hashes, and retrieval;
- [`reference_rig_hardware_environment.md`](../../../reference_rig_hardware_environment.md)
  for hardware, environment, topology, measurements, and limitations;
- [`zed_respeaker_mount_model_handoff.md`](../../../zed_respeaker_mount_model_handoff.md)
  for the future, unbuilt printed-mount handoff; and
- `outputs/isaac_audio_sensors/S4/S4.1/evidence_index.json`,
  `rig_frame_lock.json`, `live_fixture_gate.json`, and
  `future_printed_mount_reference.json`
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

## Installed fixture and future printed mount boundary

The passing S4.1 evidence applies only to `S4_TEMP_DESKTOP_FIXTURE_REV0`, the
handmade fixture visible in the retained top image. The tape-measured
approximate as-used geometry is not derived from the Fusion design and is not a
precision optical/acoustic extrinsic.

The handoff's reported 90 mm nominal separation and checksums describe an
unbuilt future 3D-printed mount. Its source package was not retrievable during
closeout, so those values remain reported context and are not authenticated or
assigned to the installed fixture. This lack of future-design provenance does
not weaken or block evidence for the different as-built fixture.

When the printed mount is fabricated, it must receive a new mount identity.
Its as-built ZED/ReSpeaker pose and uncertainty must be measured, and the
stability, repeatability, microphone-opening, FOV, and cable checks must be
rerun. Evidence from the handmade fixture does not transfer automatically.

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

All commands above must pass at the frozen evidence revision. This closeout
authorizes S4.2 while making no claim that S4.2 work has started.
