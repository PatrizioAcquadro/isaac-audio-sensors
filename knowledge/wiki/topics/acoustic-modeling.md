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

L2 `analytic_acoustics` is the topology-routed backend. Its free-field and half-space solvers are deterministic Core capabilities; its shoebox and polygon-prism solvers use optional PyRoom. The legacy `room_acoustics` and `room_acoustics_srp` shoebox backends remain available during R8.1.

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

L0/L1 order is asset reference, source nominal gain, source/microphone directivity magnitude, analytical `1/d` with the existing floor and optional air absorption, occlusion loss, microphone nominal gain, optional TDOA gain-mismatch stress, then channel-response gain correction. R8.1 analytic Core order is original samples, source nominal gain, fractional propagation delay with `1/(4*pi*distance)` pressure spreading, optional floor reflection, signed pair directivity, microphone nominal gain, channel-response processing, source summation, then noise/electronics. Closed analytic and legacy room routes use the PyRoom RIR in the propagation position and never apply a second manual distance loss. `analytic_acoustics` rejects occlusion until R8.2 separates direct and reflected stems.

Channel-response gain is a configured per-channel correction delta, TDOA gain mismatch is a seeded stress delta, and occlusion is a non-positive propagation-loss delta. Diagnostics keep them distinct from source and microphone nominal gains. Calibration-profile gain is stored data only and is never applied automatically.

Cross-backend validation concerns relative amplitude: a `+20*log10(2)` dB change yields a factor of two and the negative change yields one half. It does not require equal absolute RMS across L0/L1 and L2 and does not claim dB SPL.

## Acoustic Environments and Room Acoustics

`AcousticEnvironmentSpec` provides one world pose and canonical local `AcousticSurfaceSpec` values for `free_field`, `half_space`, `shoebox`, `polygon_prism`, and bounded non-empty `surface_set` topologies. Public builders validate surfaces, materials, complete poses, simple polygons, positive dimensions, and topology invariants; quaternion transforms map source and microphone points between world and environment coordinates.

`AudioSceneSnapshot.environment` is mandatory for every backend. TOML likewise requires one `[environment]` table, with the `environment.surfaces` array of tables for `surface_set`; `[room]`, obsolete room keys, and missing environments fail explicitly.

`AnalyticAcoustics` selects its solver only from environment topology. `free_field_direct` uses Core direct propagation; `half_space_image_source` optionally adds one material-aware local-floor reflection; `pyroom_shoebox` and `pyroom_polygon_prism` use lazy PyRoom construction with per-surface materials. Every route reports its solver ID, provider, and environment kind on the frame and each detection.

Reflection order, air absorption, and ray tracing remain solver settings supplied to backend construction or `[audio.room_acoustics]`, not environment properties. Free field requires order zero, half space accepts zero or one, and air absorption or ray tracing is available only on PyRoom routes. Source and microphone containment is environment-local and fail-closed with no clamping. A polygon prism is validated as a simple extruded footprint with exactly one wall per floor edge before room construction. The retained `room_acoustics` and `room_acoustics_srp` identifiers continue to accept only `shoebox`.

Isaac resolves the same Core contract from a manual environment, an explicit anchor, or marked USD candidates. Automatic discovery accepts marked shoebox volumes and half-space floors, tests every microphone with a 1 mm default tolerance, and fails on malformed or unresolved ambiguity; it never guesses from unmarked geometry. Kit uses the explicit `unconfigured`, `manual_free_field`, `anchor`, and `auto` modes and has no implicit shoebox fallback. `polygon_prism` and `surface_set` remain manual Python/TOML inputs until R10.

The analytic and legacy room backends schedule all active sources into one shared microphone mixture, preserve sample timing, compute per-source and aggregate diagnostics, and can export per-frame or continuous multichannel waveforms.

`AnalyticAcoustics` reuses the explicit `prepare -> render -> effects -> detections -> frame` room pipeline, including scheduling, Doppler, gain, directivity, effects, waveform export, GCC/SRP estimation, and frame assembly. Only solver selection and propagation construction differ.

The analytic model does not implement arbitrary geometry, `surface_set`, diffraction, connected rooms, a complete wave solver, calibrated materials, diffuse-field coherence, or production beamforming.

## Motion and Doppler

Source and array velocity may be authored or derived from pose history with explicit first-sample, stale-time, teleport, smoothing, and reset handling.

Motion windows can be segmented so Doppler, pair geometry, RIR rendering, and session time gaps follow bounded intra-window state instead of one unlabelled static approximation. R8.1 supports segmented motion on the PyRoom routes; its Core free-field and half-space routes reject more than one segment.

L1 records direct-path frequency-ratio behavior; L2 can resample waveform sources across motion segments.

## Effects and Electronics

The channel-effects chain supports configured per-channel gain, fractional delay, polarity, frequency response, seeded noise streams, ambient coherence controls, clock jitter/drift, saturation/clipping, quantization, TPDF dither, and optional AGC. Entity directivity is resolved before this chain.

Effects default to identity; waveform-required effects reject metadata-only backends when an honest equivalent is unavailable.

Configuration normalization always rejects malformed mappings, unknown keys, invalid structural types, and non-finite values. Each effect domain owns its parsing and semantic checks behind the unchanged public parsing/validation facades; range and backend compatibility checks apply only to stages that can affect the selected computation.

Diagnostics retain applied settings and observable outputs so a consumer can distinguish generated stress from estimator behavior.

## Occlusion and Materials

The Isaac layer can raycast each source-to-microphone path for the legacy backends, aggregate multiple hits, derive flat or octave-band transmission loss from authored values or nominal presets, apply the resulting non-positive propagation-loss delta once, and mark detections as occluded. `analytic_acoustics` rejects `SourceOcclusion` in R8.1 because applying it to the combined direct and reflected signal would be incorrect; direct-stem-only application belongs to R8.2.

Environment-surface absorption may use measured provenance, but transmission presets remain nominal unless independently measured; the system does not claim diffraction, edge bending, thickness-derived transmission, or reflected-path occlusion.

## DOA and Confidence

Bearings are normalized to `[0, 360)` and map to eight half-open 45-degree sectors with wraparound centered on array forward.

Planar arrays report azimuth without inventing elevation; rank-3 arrays can estimate elevation from full 3D delays.

GCC-PHAT exposes pair-delay evidence, SRP-PHAT scans candidate directions, and confidence is derived from observable signal/estimator evidence rather than oracle ground-truth error.

## Interpretation Limits

Deterministic correctness, GPU execution, plausible waveforms, and agreement between backends do not prove physical fidelity.

Real hardware claims require measured array geometry and response, controlled recordings, calibrated references, and a separate sim-to-real validation protocol.
