# Acoustic Modeling

## Microphone Geometry

Built-in local layouts are `mono`, `stereo_y`/`two_mic_y`, `quad_front`/`quad_cross`, and `tetrahedral`; arbitrary arrays can provide explicit microphone IDs and local positions.

Named layouts use a positive finite spacing, with `tetrahedral` as the built-in rank-3 geometry that permits elevation estimation.

World microphone positions are produced from the array XYZW orientation and its forward/right/up basis; TDOA requires at least two non-coincident microphones and useful azimuth or elevation depends on the layout rank.

Two microphones have an explicit front/back ambiguity unless an additional prior such as `front_hemisphere` is selected; the package never hides that ambiguity as a confident unique estimate.

## Fidelity Ladder

The public ladder describes modeled behavior and missing physics; it is not a claim that simulation matches a physical room or microphone.

L0 `geometry_only` is stable and deterministic: it computes source distance, bearing, eight-sector labels, and analytical per-microphone RMS without waveforms.

L1 `tdoa_synthetic` is stable and deterministic: it computes direct-path per-microphone delay, analytical amplitude diagnostics, first-order entity directivity, optional air absorption, self-noise floors, seeded stress controls, and ambiguity metadata without reverberation.

L2 `room_acoustics` and `room_acoustics_srp` are supported optional backends: they use approximate shoebox impulse responses, multichannel mixtures, GCC-PHAT diagnostics, and either GCC-based or SRP-PHAT DOA when the `room` dependencies are installed.

L3 is provisional advanced realism: the shipped capability is opt-in Isaac raycast occlusion and material-aware transmission, not a complete advanced-acoustics backend.

L4 is experimental calibration tooling direction and does not claim automatic hardware calibration or sim-to-real transfer.

## Entity Directivity

`AudioSourceSpec.directivity` is the sole source authority and `MicrophoneSpec.directivity` is the sole microphone authority. Both store the public `DirectivityPattern` enum. The exact supported families are `omni`, `cardioid`, `supercardioid`, and `figure_eight`; their first-order coefficients are respectively `1.0`, `0.5`, `0.37`, and `0.0` from one canonical Core table.

Every backend and both Isaac Lab binding modes use `per_pair_direct_path`: source and microphone factors are evaluated from their resolved orientations and multiplied for each direct source/microphone pair. Unknown values and non-omni entities without the required orientation fail; there is no implicit omni fallback.

L0/L1 report the magnitude of that pair factor in RMS. L2 applies its signed value to the complete PyRoom-convolved pair stem, so negative lobes invert waveform polarity while RMS remains magnitude-only. The model does not evaluate a separate angle for each reflection.

Directivity is not an audio effect. The removed `audio.effects.directivity` tables, pattern sets, and `frequency_points` have no v3 alias or parser. Former directivity frequency points are not migrated because they represented frequency response independently of angle. A maintained microphone response must be authored manually under `audio.effects.channel_response.<mic>.frequency_response`.

## Gain and Asset Amplitude

Every scalar nominal or delta `gain_db` is an amplitude gain using `10 ** (gain_db / 20)` and must convert to a positive finite linear value. Boolean, non-real, non-finite, overflowing, and underflow-to-zero inputs fail closed.

Generated and file-backed source samples keep the amplitude encoded by the asset. Source nominal gain is applied exactly once after content selection and before propagation; `gain_db = 0` is unity and WAV input is never peak- or RMS-normalized automatically.

L0/L1 order is asset reference, source nominal gain, source/microphone directivity magnitude, analytical `1/d` with the existing floor and optional air absorption, occlusion loss, microphone nominal gain, optional TDOA gain-mismatch stress, then channel-response gain correction. L2 order is original samples, source nominal gain, PyRoom RIR, signed pair directivity, occlusion, microphone nominal gain, channel-response FIR/gain/polarity/delay, source summation, then noise/electronics. PyRoom owns L2 propagation distance and reflections; no second manual `1/d` is applied.

Channel-response gain is a configured per-channel correction delta, TDOA gain mismatch is a seeded stress delta, and occlusion is a non-positive propagation-loss delta. Diagnostics keep them distinct from source and microphone nominal gains. Calibration-profile gain is stored data only and is never applied automatically.

Cross-backend validation concerns relative amplitude: a `+20*log10(2)` dB change yields a factor of two and the negative change yields one half. It does not require equal absolute RMS across L0/L1 and L2 and does not claim dB SPL.

## Acoustic Environments and Room Acoustics

`AcousticEnvironmentSpec` provides one world pose and canonical local `AcousticSurfaceSpec` values for `free_field`, `half_space`, `shoebox`, `polygon_prism`, and bounded non-empty `surface_set` topologies. Public builders validate surfaces, materials, complete poses, simple polygons, positive dimensions, and topology invariants; quaternion transforms map source and microphone points between world and environment coordinates.

`AudioSceneSnapshot.environment` remains optional through R7.1. TOML uses one `[environment]` table, with the `environment.surfaces` array of tables for `surface_set`; `[room]` and obsolete room keys fail explicitly.

The current `room_acoustics` and `room_acoustics_srp` backends accept only `kind="shoebox"` until R8. Reflection order, air absorption, and ray tracing are solver settings supplied to backend construction or `[audio.room_acoustics]`, not environment properties. Any source or microphone outside the local shoebox fails; clamping is removed.

Isaac may derive a shoebox from one manually designated anchor's world bounds, but the anchor remains outside the simulator-independent Core contract. Kit keeps a temporary array-centered shoebox only for R7.1 when a room backend has no anchor; automatic USD resolution and mandatory environments belong to R7.2.

The backend schedules all active sources into one shared microphone mixture, preserves sample timing, computes per-source and aggregate diagnostics, and can export per-frame or continuous multichannel waveforms.

Its implementation uses an explicit `prepare -> render -> effects -> detections -> frame` pipeline around separate signal, rendering, diagnostic, and assembly modules. This organization does not alter formulas, source ordering, phase cursors, effect placement, or numerical output.

The model remains a shoebox approximation and does not implement arbitrary geometry, diffraction, a complete wave solver, calibrated materials, diffuse-field coherence, or production beamforming.

## Motion and Doppler

Source and array velocity may be authored or derived from pose history with explicit first-sample, stale-time, teleport, smoothing, and reset handling.

Motion windows can be segmented so Doppler, pair geometry, RIR rendering, and session time gaps follow bounded intra-window state instead of one unlabelled static approximation.

L1 records direct-path frequency-ratio behavior; L2 can resample waveform sources across motion segments.

## Effects and Electronics

The channel-effects chain supports configured per-channel gain, fractional delay, polarity, frequency response, seeded noise streams, ambient coherence controls, clock jitter/drift, saturation/clipping, quantization, TPDF dither, and optional AGC. Entity directivity is resolved before this chain.

Effects default to identity; waveform-required effects reject metadata-only backends when an honest equivalent is unavailable.

Configuration normalization always rejects malformed mappings, unknown keys, invalid structural types, and non-finite values. Each effect domain owns its parsing and semantic checks behind the unchanged public parsing/validation facades; range and backend compatibility checks apply only to stages that can affect the selected computation.

Diagnostics retain applied settings and observable outputs so a consumer can distinguish generated stress from estimator behavior.

## Occlusion and Materials

The Isaac layer can raycast each source-to-microphone path, aggregate multiple hits, derive flat or octave-band transmission loss from authored values or nominal presets, apply the resulting non-positive propagation-loss delta once, and mark detections as occluded.

Environment-surface absorption may use measured provenance, but transmission presets remain nominal unless independently measured; the system does not claim diffraction, edge bending, thickness-derived transmission, or reflected-path occlusion.

## DOA and Confidence

Bearings are normalized to `[0, 360)` and map to eight half-open 45-degree sectors with wraparound centered on array forward.

Planar arrays report azimuth without inventing elevation; rank-3 arrays can estimate elevation from full 3D delays.

GCC-PHAT exposes pair-delay evidence, SRP-PHAT scans candidate directions, and confidence is derived from observable signal/estimator evidence rather than oracle ground-truth error.

## Interpretation Limits

Deterministic correctness, GPU execution, plausible waveforms, and agreement between backends do not prove physical fidelity.

Real hardware claims require measured array geometry and response, controlled recordings, calibrated references, and a separate sim-to-real validation protocol.
