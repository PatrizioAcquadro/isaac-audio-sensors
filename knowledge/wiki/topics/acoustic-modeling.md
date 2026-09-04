# Acoustic Modeling

## Microphone Geometry

Built-in local layouts are `mono`, `stereo_y`/`two_mic_y`, `quad_front`/`quad_cross`, and `tetrahedral`; arbitrary arrays can provide explicit microphone IDs and local positions.

Named layouts use a positive finite spacing, with `tetrahedral` as the built-in rank-3 geometry that permits elevation estimation.

World microphone positions are produced from the array XYZW orientation and its forward/right/up basis. Exactly two microphones are supported only by TDOA least-squares and require distinct XY positions. Least-squares with three or more microphones and all SRP-PHAT uses require at least three microphones whose centered XY coordinates have rank two. Four non-collinear microphones remain the recommended practical configuration for redundancy and robustness, not a mandatory minimum.

For two microphones, the public azimuth model returns every normalized, deduplicated bearing compatible with the measured delay in `candidate_bearing_deg`. The ordinary result has `estimated_bearing_deg`, `bearing_sector`, and elevation unset, confidence zero, and `ambiguity_class="ambiguous_front_back"`. Only a delay at the physical baseline endpoint, where the two candidates coincide, produces one unique bearing. Core accepts no contextual prior; assumptions such as “the source is in front” belong to downstream consumers.

Three non-collinear microphones are the minimum geometry for a unique 360-degree azimuth estimate, not a guarantee against noise, reverberation, or spatial aliasing. Collinear arrays with three or more microphones fail explicitly instead of falling back to a linear-array model. Rank-three geometry is still required when elevation itself must be resolved.

## Fidelity Ladder

The public ladder describes modeled behavior and missing physics; it is not a claim that simulation matches a physical room or microphone.

L0 direct geometry is stable deterministic behavior internal to `analytic_acoustics`: it computes source distance, bearing, eight-sector labels, and analytical per-microphone relative RMS without requiring waveforms.

L1 analytic TDOA is stable deterministic behavior internal to `analytic_acoustics`: it computes direct-path per-microphone delay, analytical amplitude diagnostics, first-order entity directivity, optional air absorption, self-noise floors, seeded stress controls, and ambiguity metadata without reverberation.

L2 `analytic_acoustics` is the only runtime propagation backend. Its free-field and half-space solvers are deterministic Core capabilities; its shoebox and polygon-prism solvers use optional PyRoom. TDOA least-squares and SRP-PHAT are estimator choices rather than separate propagation backends.

L3 is provisional advanced realism: the shipped capability is opt-in Isaac raycast occlusion and material-aware transmission, not a complete advanced-acoustics backend.

L4 is experimental calibration tooling direction and does not claim automatic hardware calibration or sim-to-real transfer.

## Entity Directivity

`AudioSourceSpec.directivity` is the sole source authority and `MicrophoneSpec.directivity` is the sole microphone authority. Both store the public `DirectivityPattern` enum. The exact supported families are `omni`, `cardioid`, `supercardioid`, and `figure_eight`; their first-order coefficients are respectively `1.0`, `0.5`, `0.37`, and `0.0` from one canonical Core table.

Every backend and both Isaac Lab binding modes use `per_pair_direct_path`: source and microphone factors are evaluated from their resolved orientations and multiplied for each direct source/microphone pair. Unknown values and non-omni entities without the required orientation fail; there is no implicit omni fallback.

Direct feature paths report the magnitude of that pair factor in RMS. Waveform paths apply its signed value to the complete PyRoom-convolved pair stem, so negative lobes invert waveform polarity while RMS remains magnitude-only. The model does not evaluate a separate angle for each reflection.

Directivity is not an audio effect. The removed `audio.effects.directivity` tables, pattern sets, and `frequency_points` have no v3 alias or parser. Former directivity frequency points are not migrated because they represented frequency response independently of angle. A maintained microphone response must be authored manually under `audio.effects.channel_response.<mic>.frequency_response`.

## Gain and Asset Amplitude

Every scalar nominal or delta `gain_db` is an amplitude gain using `10 ** (gain_db / 20)` and must convert to a positive finite linear value. Boolean, non-real, non-finite, overflowing, and underflow-to-zero inputs fail closed.

Generated and file-backed source samples keep the amplitude encoded by the asset. Source nominal gain is applied exactly once after content selection and before propagation; `gain_db = 0` is unity and WAV input is never peak- or RMS-normalized automatically.

The direct-feature order is asset reference, source nominal gain, source/microphone directivity magnitude, analytical `1/d` with the existing floor and optional air absorption, occlusion loss where supported, microphone nominal gain, optional TDOA gain-mismatch stress, then channel-response gain correction. The analytic waveform order is original samples, source nominal gain and Doppler, propagation into direct `D` and indirect `R` stems, signed pair directivity, direct-only broadband or banded occlusion, `a * D + R` recombination, microphone nominal gain, channel-response processing, source summation, then noise/electronics. Closed analytic routes use PyRoom RIRs and never apply a second manual distance loss. An unattenuated pair uses the original full premix directly.

Channel-response gain is a configured per-channel correction delta, TDOA gain mismatch is a seeded stress delta, and occlusion is a non-positive propagation-loss delta. Diagnostics keep them distinct from source and microphone nominal gains. Calibration-profile gain is stored data only and is never applied automatically.

Cross-path validation concerns relative amplitude: a `+20*log10(2)` dB change yields a factor of two and the negative change yields one half. It does not require equal absolute RMS across feature and waveform paths and does not claim dB SPL.

## Acoustic Environments and Room Acoustics

`AcousticEnvironmentSpec` provides one world pose and canonical local `AcousticSurfaceSpec` values for `free_field`, `half_space`, `shoebox`, `polygon_prism`, and bounded non-empty `surface_set` topologies. Public builders validate surfaces, materials, complete poses, simple polygons, positive dimensions, and topology invariants; quaternion transforms map source and microphone points between world and environment coordinates.

`AudioSceneSnapshot.environment` is mandatory for every backend. TOML likewise requires one `[environment]` table, with the `environment.surfaces` array of tables for `surface_set`; `[room]`, obsolete room keys, and missing environments fail explicitly.

`AnalyticAcoustics` selects its solver only from environment topology. `free_field_direct` uses Core direct propagation; `half_space_image_source` optionally adds one material-aware local-floor reflection; `pyroom_shoebox` and `pyroom_polygon_prism` use lazy PyRoom construction with per-surface materials. Every route reports its solver ID, provider, and environment kind in signal diagnostics, which perception copies into the resulting frame.

Reflection order, air absorption, and ray tracing remain solver settings supplied to backend construction or `[audio.analytic_acoustics]`, not environment properties. Free field requires order zero, half space accepts zero or one, and air absorption or ray tracing is available only on PyRoom routes. Source and microphone containment is environment-local and fail-closed with no clamping. A polygon prism is validated as a simple extruded footprint with exactly one wall per floor edge before room construction. The removed `[audio.room_acoustics]` table and legacy backend identifiers fail instead of selecting an alias.

Isaac resolves the same Core contract from a manual environment, an explicit anchor, or marked USD candidates. Automatic discovery accepts marked shoebox volumes and half-space floors, tests every microphone with a 1 mm default tolerance, and fails on malformed or unresolved ambiguity; it never guesses from unmarked geometry. Kit uses the explicit `unconfigured`, `manual_free_field`, `anchor`, and `auto` modes and has no implicit shoebox fallback. `polygon_prism` and `surface_set` remain manual Python/TOML inputs until R10.

The analytic backend schedules all active sources into one shared microphone mixture, preserves sample timing, and computes concise render, tail, effect-stage, and solver diagnostics on the exact-window block. Optional per-frame or continuous multichannel export is a separate block consumer.

`AnalyticAcoustics` owns `prepare -> render -> effects -> signal block`, including scheduling, Doppler, gain, directivity, and effects. It neither writes waveforms nor assembles frames. The Plan 02.3 orchestrator passes the block to perception and optional recording; GCC/SRP estimation and source-conditioned observation construction are not backend responsibilities.

The analytic model does not implement arbitrary geometry, `surface_set`, diffraction, connected rooms, a complete wave solver, calibrated materials, diffuse-field coherence, or production beamforming.

## Motion and Doppler

Source and array velocity may be authored or derived from pose history with explicit first-sample, stale-time, teleport, smoothing, and reset handling.

Motion windows can be segmented so Doppler, pair geometry, RIR rendering, and session time gaps follow bounded intra-window state instead of one unlabelled static approximation. R8.2 preserves direct/indirect decomposition and direct-only attenuation across every PyRoom segment; its Core free-field and half-space routes reject more than one segment.

L1 records direct-path frequency-ratio behavior; L2 can resample waveform sources across motion segments.

## Effects and Electronics

The channel-effects chain supports configured per-channel gain, fractional delay, polarity, frequency response, seeded noise streams, ambient coherence controls, clock jitter/drift, saturation/clipping, quantization, TPDF dither, and optional AGC. Entity directivity is resolved before this chain.

Effects default to identity; waveform-required effects reject metadata-only backends when an honest equivalent is unavailable.

Configuration normalization always rejects malformed mappings, unknown keys, invalid structural types, and non-finite values. Each effect domain owns its parsing and semantic checks behind the unchanged public parsing/validation facades; range and backend compatibility checks apply only to stages that can affect the selected computation.

Diagnostics retain applied settings and observable outputs so a consumer can distinguish generated stress from estimator behavior.

## Occlusion and Materials

The Isaac layer raycasts each source-to-microphone direct path and derives broadband or octave-band transmission loss from authored values, nominal presets, or the explicit `unknown_material_loss_db` fallback. Optional `ias:acoustic_partition_id` groups fragmented collision prims under one whole-assembly curve; otherwise each prim path is an implicit partition. One curve is applied per partition, conflicting curves and exceeded hit limits fail closed, and sequential partitions add in dB without a fixed total-loss clamp. `SourceOcclusion` carries only exact per-microphone blocked and attenuation state plus optional aligned band rows. Model and partition-level material evidence live once under frame diagnostic `acoustics_state`; optional `debug_draw` traces retain transient geometry outside stable frames and datasets. Analytic waveform propagation applies loss exactly once to `D` and preserves `R`; the mass-parallel Lab path intentionally excludes occlusion. Obstacle loss has no source-obstacle-distance multiplier, and no blocked-map state is promoted into an observation.

Environment-surface absorption may use measured provenance, but transmission presets remain nominal unless independently measured; the system does not claim diffraction, edge bending, thickness-derived transmission, or reflected-path occlusion.

## DOA and Confidence

Bearings are normalized to `[0, 360)` and map to eight half-open 45-degree sectors with wraparound centered on array forward.

Planar arrays report azimuth without inventing elevation; rank-3 arrays can estimate elevation from full 3D delays.

Every estimator consumes only valid rows of the final multichannel mixture, matching array-local microphone positions, and sample rate. Source count, identities, positions, schedules, render stems, and scene diagnostics are unavailable to localization.

GCC-PHAT exposes pair-delay evidence, while SRP-PHAT scans candidate directions. Structurally valid but silent, spatially identical, geometrically unsupported, or below-threshold inputs return explicit unresolved estimates rather than fabricated directions. Malformed or non-finite input still fails.

`bearing_confidence` is an estimator-local reliability ordering, not a probability. Least-squares combines its residual score with median GCC peak strength, internal SRP retains its contrast/coherence score, and PyRoom SRP combines normalized coherent excess with grid contrast after selecting observed-energy STFT bins. These scores are not comparable across estimators without calibration.

Subphase 04.2 qualifies `pyroomacoustics_srp` on independent NumPy mixtures and hash-verified real ReSpeaker audio. Its operating point is a causal 250 ms observation block, 512-point FFT, 256-sample hop, 300–6000 Hz outer band, 2-degree azimuth grid, 5-degree rank-3 elevation grid, and reliability threshold `0.034`. It reaches 97.98% held-out active coverage and 6-degree bearing p95 with four-channel compute p95 below 5.06 ms. Internal SRP and least-squares remain measured, unselected baselines without a complete qualified operating point. NormMUSIC was not needed because PyRoom SRP passed the essential gates.

## Interpretation Limits

Deterministic correctness, GPU execution, plausible waveforms, and agreement between backends do not prove physical fidelity.

Real hardware claims require measured array geometry and response, controlled recordings, calibrated references, and a separate sim-to-real validation protocol.
