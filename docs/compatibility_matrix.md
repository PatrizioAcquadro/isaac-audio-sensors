# Compatibility Matrix

This matrix freezes the Stage 1 public compatibility surface at package
version `1.8.0`. The package version and every contract schema version remain
independent.

## Release Matrix

| Producer / fixture | Current reader | Result | Compatibility behavior |
| --- | --- | --- | --- |
| `1.7.0` `AudioSensorFrame` JSON | `1.8.0` | Pass | Loads with identical semantics. Serialization equals the original after only the canonical optional-field default expansion below. |
| `1.7.0` `AudioSensorFrame` NDJSON | `1.8.0` | Pass | Every record loads in order with identical semantics and no key removal or value change. |
| `1.7.0` demo TOML | `1.8.0` | Pass | Scene, audio, source, array, room, and Lab values are unchanged; absent `audio.runtime_profile` selects the documented `waveform_fidelity` default. |
| `1.8.0` dataset manifest | `1.8.0` public reader | Pass | `ias.audio_dataset_manifest.v1` valid examples load through `read_dataset_manifest`. |
| `1.8.0` calibration profile | `1.8.0` public reader | Pass | `ias.audio_calibration_profile.v1` valid examples load through `read_calibration_profile`. |
| `1.8.0` propagation / DOA plugin consumer | `1.8.0` public registry | Pass | Built-in `geometry_only` and `tdoa_least_squares` resolve through their public protocols. |

`ias.audio_sensor_frame.v1` retains the same shape and meaning. Its schema,
frame dataclasses, trace serializer, four public trace examples, and demo
configuration are byte-identical to the accepted entry revision `74a4ed6`
(and to the `1.7.0` release revision `b5d4630`).

## Canonical Optional-Field Expansion

Current writers serialize additive optional detection and DOA fields even
when a `1.7.0` record omitted them. This is canonical default expansion, not a
semantic change:

| Absent path in input detection | Canonical serialized value |
| --- | --- |
| `occluded` | `false` |
| `ground_truth_elevation_deg` | `null` |
| `doa.estimated_elevation_deg` | `null` |
| `doa.candidate_elevation_deg` | `[]` |

Only absent occurrences expand. Existing values are preserved. Supplied unit
maps are also preserved exactly; in particular, a historical record without
`units.elevation` does not acquire that key during a read/write round trip.
This additive-optional behavior is unchanged since `74a4ed6`.

The S1.7 regression test compares each complete round-tripped dictionary with
the original after applying exactly this normalization. It independently
checks the recursive key delta and fails if any other key appears, disappears,
or changes value. The historical corpus exercises all four expansion kinds.

## Frozen Artifact Baseline

| Public artifact | SHA-256 at `1.7.0`, `74a4ed6`, and S1.7 |
| --- | --- |
| `docs/schemas/audio_sensor_frame.v1.schema.json` | `1f005443a65567961f22e9bec7c50f1f6a3dffa0e017e79de348fd6203b43933` |
| `examples/traces/ambiguity_frame.v1.json` | `753f49d83b57edf6c9f79ebb23c76f7f5ee51aa2fd4c6dc645f7ae23dfc7210d` |
| `examples/traces/diagnostics_provenance_sequence.v1.ndjson` | `79e4f6483cccffb2953821978f3b74513811496e0877a4139ec0c7e637950b01` |
| `examples/traces/minimal_frame.v1.json` | `2070686b033fe2cb232558d68837fd5705995d56bcf45ae033f94e6027db5c0b` |
| `examples/traces/multi_detection_frame.v1.json` | `a76a6c0e9d7f5c0a7d0ae62f562028a6f44a7d2944be9953d7589459cd0c214b` |
| `configs/isaac_audio_sensors_demo.toml` | `d46a38e3f8ef87160b60eeeda622c1b3aac12041f88dc539d1dea6a51d7e6cb4` |

Public names and identifiers are inventoried in
[Public API Inventory](public_api_inventory.md). An incompatible future frame
change requires a new schema version rather than a silent change to
`ias.audio_sensor_frame.v1`.
