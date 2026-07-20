# Documentation

This documentation describes the standalone `isaac-audio-sensors` package for
public users.

- [Installation](installation.md)
- [Quickstart](quickstart.md)
- [V1 Public Scope](v1_scope.md)
- [Isaac Sim](isaac_sim.md)
- [Omniverse Extension UX](isaac_sim.md#reference-extension-ux)
- [Isaac Lab](isaac_lab.md)
- [Acoustic Fidelity Ladder](acoustic_fidelity.md)
- [Backends](backends.md)
- [Room Acoustics](room_acoustics.md)
- [Audio Assets](audio_assets.md)
- [TDOA And DOA](tdoa_doa.md)
- [API Freeze](api_freeze_0_1.md)
- [Compatibility Matrix](compatibility_matrix.md)
- [Public API Inventory](public_api_inventory.md)
- [AudioSensorFrame Schema](schemas/audio_sensor_frame.v1.schema.json)
- [Validation](validation.md)
- [Limitations](limitations.md)
- [Versioning](versioning.md)
- [Roadmap](roadmap.md)
- [Final Sensor Development Plan](final_sensor_development_plan.md)
- [Reference Rig Hardware And Environment](reference_rig_hardware_environment.md)
- [ZED 2i And ReSpeaker Mount Pre-CAD Input Lock](zed_respeaker_mount_pre_cad.md)
- [Future ZED 2i / ReSpeaker 3D-Printed Mount Handoff](zed_respeaker_mount_model_handoff.md)
- [S4.1 Evidence Index](development/closeouts/S4/s4_1_evidence_index.md)
- [Showcase](showcase.md)
- [Open Source Release Checklist](open_source_release_checklist.md)

## Local Evidence Report

Run `make live-evidence-report` to generate the current machine-local report
source and PDF from the canonical ignored artifacts. The generator is
`scripts/generate_live_evidence_report.py`; it writes:

- `outputs/isaac_audio_sensors/live_validation_evidence.md`
- `outputs/isaac_audio_sensors/live_validation_evidence.pdf`

The report parses these current evidence inputs:

- `outputs/isaac_audio_sensors/isaac_sim_live_smoke.json`
- `outputs/isaac_audio_sensors/isaac_sim_live_smoke.frames.jsonl`
- `outputs/isaac_audio_sensors/isaac_sim_live_smoke.config.json`
- `outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json`
- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.json`
- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.frames.jsonl`
- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.config.json`
- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.replicator/`

The generated report includes exact local `python_executable` values, GPU and
driver facts, pass/optional/blocker tables, artifact paths, and non-promises.
Tracked public docs keep those machine-local absolute paths in the ignored
report and source JSON rather than publishing them as package documentation.

## Isaac Sim Reference UX

The source distribution includes `exts/isaac_audio_sensors.omni`, a reference
Kit extension for authoring microphone arrays and sound sources directly in
Isaac Sim. The documented workflow covers selected-prim binding, array/source
metadata authoring, discovery, backend selection, start/update/stop lifecycle,
debug overlay primitives, package JSON/JSONL export, config import/export, and
optional Omniverse Replicator recording.

## V1 Scope Boundary

[V1 Public Scope](v1_scope.md) is the canonical promise and non-promise page for
the release. V1 does not make SquadBot, Alex, ROS 2/downstream adapters,
sim-real calibration, real hardware benchmarks, complete L3/L4 fidelity,
realistic material/occlusion acoustics, or downstream project validation into
package release gates.

Validation artifacts from the live extension smoke are written under ignored
`outputs/isaac_audio_sensors/`, including:

- `omniverse_extension_live_ux.json`
- `omniverse_extension_live_ux.frames.jsonl`
- `omniverse_extension_live_ux.config.json`
- `omniverse_extension_live_ux.replicator/`

Screenshots are saved as
`outputs/isaac_audio_sensors/omniverse_extension_live_ux.viewport.png` when the
active Kit viewport exposes a capture API; otherwise the evidence JSON records
the exact capture blocker and still includes serialized overlay primitives.
