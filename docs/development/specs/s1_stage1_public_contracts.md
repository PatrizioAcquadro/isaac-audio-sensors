# S1.2 Stage 1 public contracts

## Status and scope

This note defines the Stage 1 contract implemented for
`ias.audio_dataset_manifest.v1`, `ias.audio_calibration_profile.v1`, and the
runtime-profile configuration vocabulary. Contract versions are independent
of package version `1.8.0`. Dataset layout policy, atomic writers, replay, and
the training fast path remain assigned to S2.1, S2.2, and P1.

The new core modules are import-safe. They require no Isaac, Kit, torch, GPU,
protobuf, JSON Schema validator, or optional acoustics dependency.

## Runtime profiles

| Value | Contract meaning | Configuration rule |
| --- | --- | --- |
| `training_features` | Feature-oriented large-batch operation; the default loop does not render waveforms. | Accepted only when `audio.write_waveforms` is false. |
| `waveform_fidelity` | Multichannel waveform plus generic frame/feature output for datasets, evaluation, calibration, and demos. | Default when `audio.runtime_profile` is absent. |

Any other value fails `validate_audio_config`. The default preserves the
behavior of configurations written before the field existed.

## Dataset manifest fields

| Record | Required content |
| --- | --- |
| Manifest | Stable dataset id, schema id, creation timestamp, license/source, runtime and device provenance, convention, frames, time base, sample rate, ordered channels, units, dtype, configuration digest, split policy, and completion state. |
| Creation provenance | Tool/version, optional Isaac Sim/Lab/Kit versions, backend id, and estimator id. |
| Episode | Stable episode/scene/environment ids, seed, inclusive step and frame ranges, ordered timestamps, reset markers, array poses, source truth, labels, visual-sync references, and one leakage-prevention group. |
| Shard | Stable shard id, episode references, checksummed portable assets, and explicit `complete` or `incomplete` state. |
| Asset | Stable asset id, relative POSIX path, media kind, and lowercase SHA-256. Frame traces use JSONL/NDJSON; lossless audio uses WAV or FLAC. |
| Split | `train`, `validation`, or `test` plus deterministic group ids. |
| Calibration reference | Profile id/version, relative path, and SHA-256 when a profile was used. |

Dataset units are fixed:

| Key | Unit |
| --- | --- |
| `position` | `m` |
| `orientation` | `quaternion_xyzw` |
| `time` | `s` |
| `timestamp` | `ms` |
| `sample_rate` | `Hz` |

Manifest validation rejects empty or malformed stable ids; unknown schema or
runtime-profile values; non-positive sample rates; non-canonical units and
coordinate conventions; empty or duplicate channel order; absolute, Windows,
or parent-traversing paths; wrong media suffixes; malformed checksums;
negative or non-monotonic timestamps and ranges; undeclared pose frames;
dangling episode, visual, or split references; groups assigned across splits;
unknown completion states; and a complete manifest containing an incomplete
shard. An incomplete manifest remains representable but is never promoted by
validation.

## Calibration profile fields

| Record | Required content |
| --- | --- |
| Profile | Stable profile/device/array identities, profile version, schema id, ordered channels, BOM reference, frames/convention, units, sample rate, environment, acquisition provenance, model outputs, applicability, raw references, tool version, UTC timestamp, evidence status, and explicit unmeasured-field paths. |
| Microphone geometry | Channel id, measured-state value, position, per-axis uncertainty, and array frame. |
| Channel calibration | Gain, delay, polarity, frequency response, self-noise, and usable frequency range. |
| Model parameter | Name, unit, estimate, uncertainty, and evidence state. |
| Metrics and limits | Named fit/holdout metrics and the temperature, frequency, and environment applicability envelope. |
| Raw reference | Relative path and lowercase SHA-256. |

Calibration units are fixed:

| Key | Unit |
| --- | --- |
| `position`, `position_uncertainty` | `m` |
| `gain` | `dB` |
| `delay` | `s` |
| `frequency` | `Hz` |
| `self_noise` | `dB_SPL` |
| `temperature` | `deg_C` |
| `speed_of_sound` | `m/s` |

Every scalar, geometry record, response, and frequency range uses one of
`measured`, `nominal_not_measured`, `unmeasured`, or `unsupported`.
Measured and nominal values must contain a value. Unmeasured and unsupported
values must not contain one. A nominal or unmeasured profile also lists its
unmeasured field paths; nominal fixture values therefore cannot be consumed as
physical calibration evidence without ignoring an explicit contract field.

Profile validation rejects malformed ids, schema ids, units, frames, channel
order, sample rate, paths, checksums, timestamps, frequency ordering, polarity,
status/value combinations, and mismatched geometry or channel identities.
`check_profile_compatibility` checks array and optional device identity,
channel count and order, sample rate, coordinate convention, and an available
array-frame identity before returning. It raises on the first mismatch and
does not apply any subset of channel corrections.

## Serialization and schema reproduction

The JSON readers build nested frozen dataclasses, so validation completes
before a manifest or profile is returned. Writers emit UTF-8 JSON with sorted
keys, two-space indentation, and one trailing newline. Optional tuples and raw
references tolerate absence on read where an empty value has an unambiguous
meaning; required identity, unit, ordering, and compatibility fields do not.

`make export-schema` regenerates all three public schemas without changing the
frozen frame-v1 artifact. `make regenerate-manifests` regenerates only valid
dataset and calibration fixtures. Invalid fixtures remain hand-maintained so
their planted failure cannot disappear through regeneration.
