# Backends

Backends implement `AudioSimulationBackend.simulate(scene, sensor, window)` and
return an `AudioSensorFrame`.

## geometry_only

`GeometryBackend` computes direct geometric bearing, source distance, and an
eight-sector label from the source position relative to the microphone-array
frame. It is deterministic and useful for tests, UI plumbing, and ground-truth
style traces.

It does not simulate propagation, waveforms, reverberation, occlusion, or
physical microphone response.

## tdoa_synthetic

`TdoaSyntheticBackend` computes direct-path time-of-arrival differences from
source and microphone geometry. It reports per-microphone delays, synthetic RMS
diagnostics, candidate bearings, ambiguity metadata, and confidence.

Two-microphone arrays expose front/back ambiguity explicitly. Four or more
non-collinear microphones are recommended for direction-of-arrival examples.

## room_acoustics

`RoomAcousticsBackend` is optional. When `pyroomacoustics` is installed, it can
build an approximate shoebox room response and then estimate TDOA from generated
waveforms. If the dependency is missing, the backend raises
`OptionalDependencyUnavailable` with a clear install hint.

Use it for approximate room experiments, not as a calibrated acoustic twin.
