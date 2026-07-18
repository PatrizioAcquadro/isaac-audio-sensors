# S3.9 closeout - fidelity envelope

Status: **passed** (2026-07-18). Entry and evidence revisions: passed S3.8
closeout and S3.9 evidence-entry revision `a54b7f6`; published envelope,
claim-map generator, fidelity-ladder reconciliation, and guard tests
`b171f48` (closeout-authoring HEAD, clean before these documentation-only
changes). Passed predecessors:
`docs/development/closeouts/S3/s3_1_pose_velocity.md`,
`docs/development/closeouts/S3/s3_2_time_motion.md`,
`docs/development/closeouts/S3/s3_3_channel_response.md`,
`docs/development/closeouts/S3/s3_4_seeded_noise.md`,
`docs/development/closeouts/S3/s3_5_electronics.md`,
`docs/development/closeouts/S3/s3_6_waveform_directivity.md`,
`docs/development/closeouts/S3/s3_7_dynamic_rooms.md`, and
`docs/development/closeouts/S3/s3_8_stress.md`.

## Authority and revision provenance

The published Stage 1 fidelity specification is
`docs/development/specs/s3_fidelity_envelope.md`. The S3.9 evidence authority
is `outputs/isaac_audio_sensors/S3/S3.9/fidelity_envelope_gate.json`, together
with its referenced
`outputs/isaac_audio_sensors/S3/S3.9/claim_evidence_map.json`. Both JSON files
record `entry_revision=a54b7f6f0d8f5833612224d5db4cdb6cc5fddc23`, the
passed S3.8 closeout revision on which the envelope work began. The envelope,
evidence generator, reconciliation, and tests landed together at
`b171f488a3567749d681052921f6ddf62ffdb1ab`; that later revision is not
substituted into the generation-time entry field.

`git show --stat b171f48` records 1,265 insertions and 3 deletions across the
370-line published specification, 786-line evidence generator, 17-line
`fidelity.py` reconciliation, and 95-line guard-test file. The retained
evidence JSONs are authoritative for the gate verdict and mappings.

## Aggregate gate result

`fidelity_envelope_gate.json` reports `status: "passed"`, 10 claim rows, all
10 passed, with empty `failed_rows` and `failures`. Its five aggregate checks
are all true:

- every claim id is published exactly once;
- every evidence file exists and every recorded hash matches;
- every owning predecessor gate row passed;
- every referenced validating and off-state test id exists; and
- all mandatory boundary text is present.

The gate pins the published envelope at SHA-256
`635ba6f95c0a10b9436e1dda802f4454674250d142974e2d89a0433815318471`
and the claim map at SHA-256
`70b5ad5d9d3cc00985e4ea80eaeaf4a0d9663d96c7a215468e5dcb86257f151b`.
The claim map reports no `failed_rows`, no row `failures`, and no
`global_failures`.

Across the real claim-map rows, all 41 affirmative fixture artifacts and all
12 compatibility off-state artifacts report `status="passed"`,
`hash_matches=true`, and equality among actual, recorded, and expected
SHA-256 values. Thus 53/53 mapped artifacts were verified. The map names 43
validating test/command ids and 14 off-state test/fixture ids; none is replaced
by an availability probe, prose-only assertion, or synthetic pass.

## Claim, fixture, and off-state reconciliation

The following is the complete 10/10 claim-map roll-up. Counts in the fixture
and off-state columns are artifact counts whose status and hash both passed.
Test ids are reproduced from the authoritative JSON.

### `S3C-01` - pose-derived velocity

- Passing fixtures (4/4): `raw_constant_velocity`, `smoothing_settling`,
  `authored_precedence_bits`, and `tdoa_teleport_no_spike`.
- Validating ids:
  `tests/test_pose_history.py::test_raw_constant_velocity_recovery_frozen_fixture`;
  `tests/test_pose_history.py::test_smoothed_constant_velocity_settles_after_exactly_40_updates`;
  `tests/test_motion_stage_snapshot.py::test_authored_precedence_preserves_bits_while_history_stays_current`;
  `tests/test_motion_doppler_integration.py::test_tdoa_teleport_frame_has_exact_unity_central_and_per_mic_factors`.
- Passing off-state (1/1): `motion_off_state`. Off-state ids:
  `tests/test_motion_stage_snapshot.py::test_disabled_motion_enrichment_is_literal_identity_and_no_history_update`;
  `tests/test_motion_doppler_integration.py::test_tdoa_motion_off_state_is_byte_identical_and_omits_doppler`.

### `S3C-02` - preserved recorder gaps

- Passing fixtures (3/3): `pause_throttle_accounting` and two
  `carry_bounded_streaming` artifacts.
- Validating ids:
  `tests/test_dataset_time_gaps.py::test_pause_inserts_exact_16800_samples_and_validator_reconciles`;
  `tests/test_dataset_time_gaps.py::test_carry_advances_through_gap_then_remainder_is_exact_zero`;
  `tests/test_dataset_time_gaps.py::test_long_gap_allocations_obey_sample_and_one_mib_caps`.
- Passing off-state (1/1): `off_state_segments_one`. Off-state id:
  `tests/test_dataset_time_gaps.py::test_absent_and_explicit_false_use_identical_public_append_bytes`.

### `S3C-03` - segmented intra-window motion

- Passing fixtures (3/3): `analytical_motion_bounds`,
  `boundary_continuity`, and `doppler_rir_assembly`.
- Validating ids:
  `tests/test_intra_window_motion.py::test_linear_interpolation_and_midpoint_hold_obey_frozen_bound`;
  `tests/test_intra_window_motion.py::test_phase_cursor_continuity_residual_is_below_two_e_minus_six`;
  `tests/test_intra_window_motion.py::test_piecewise_room_assembles_exact_window_and_segment_diagnostics`.
- Passing off-state (1/1): `off_state_segments_one`. Off-state id:
  `tests/test_intra_window_motion.py::test_segments_one_selects_literal_room_branch_and_is_byte_identical`.

### `S3C-04` - channel response and mismatch

- Passing fixtures (5/5): `gain_recovery`, `fractional_delay`, `polarity`,
  `frequency_response`, and `l1_adapter_equivalence`.
- Validating ids:
  `tests/test_channel_response.py::test_tone_gain_recovery_meets_frozen_maximum_error`;
  `tests/test_channel_response.py::test_fractional_delay_recovery_meets_frozen_maximum_error`;
  `tests/test_channel_response.py::test_polarity_is_exact_for_asymmetric_values_and_signed_zero`;
  `tests/test_channel_response.py::test_frequency_response_welch_h1_meets_frozen_passband_error`;
  `tests/test_effects_backend_integration.py::test_l1_gain_and_delay_adapter_is_difference_of_matching_baselines`;
  `tests/test_effects_backend_integration.py::test_l1_polarity_is_honest_metadata_only_and_leaves_observables_exact`.
- Passing off-states (2/2): `pure_off_state` and `backend_off_state`.
  Off-state ids:
  `tests/test_channel_effects_chain.py::test_chain_all_disabled_returns_exact_input_identity_and_empty_diagnostics`;
  `tests/test_effects_backend_integration.py::test_room_backend_off_state_matches_pristine_self_reference_and_head_hashes`.

### `S3C-05` - seeded noise and clocks

- Passing fixtures (6/6): `self_noise_psd`, `rms_and_exact_zero`,
  `ambient_coherence`, `jitter_statistics`, `drift_slope_long_session`, and
  `seed_replay_separation`.
- Validating ids:
  `tests/test_effects_noise.py::test_self_noise_psd_meets_exact_frozen_welch_protocol`;
  `tests/test_effects_noise.py::test_full_band_rms_levels_meet_frozen_bound`;
  `tests/test_effects_noise.py::test_ambient_coherent_power_fraction_matches_pairwise_correlation`;
  `tests/test_effects_noise.py::test_jitter_named_draw_mean_and_std_over_exactly_100000_frames`;
  `tests/test_effects_noise.py::test_drift_slope_and_long_session_phase_arithmetic_meet_frozen_bounds`;
  `tests/test_effects_noise.py::test_seed_replay_separation_diagnostics_and_configuration_isolation`.
- Passing off-state (1/1): `pure_backend_off_state`. Off-state id:
  `tests/test_effects_noise.py::test_backend_off_state_golden_and_enabled_registry_style_determinism`.

### `S3C-06` - electronics

- Passing fixtures (5/5): `boundary_clipping_and_ratio`,
  `quantization_noise_power`, `tpdf_dither_decorrelation`,
  `agc_analytical_response_settling`, and `electronics_once_on_mixture`.
- Validating ids:
  `tests/test_effects_electronics.py::test_boundary_clipping_counts_ratio_and_diagnostics_contract_are_exact`;
  `tests/test_effects_electronics.py::test_quantization_noise_power_frozen_ramp`;
  `tests/test_effects_electronics.py::test_tpdf_dither_named_stream_peak_to_peak_and_decorrelation`;
  `tests/test_effects_electronics.py::test_agc_analytical_trace_settling_direction_silence_and_bounds`;
  `tests/test_effects_electronics.py::test_room_electronics_once_on_mixture_rms_export_and_seed_replay`.
- Passing off-state (1/1): `pure_backend_off_state`. Off-state id:
  `tests/test_effects_electronics.py::test_off_state_identity_backend_golden_and_no_effects_key`.

### `S3C-07` - waveform directivity

- Passing fixtures (4/4): `cardinal_waveform_gain`, `frequency_response`,
  `full_convolved_stem_insertion`, and `estimator_degradation`.
- Validating ids:
  `tests/test_effects_directivity.py::test_cardinal_waveform_gain_sign_and_null_leakage`;
  `tests/test_effects_directivity.py::test_frequency_response_single_and_cascaded_recovery`;
  `tests/test_effects_directivity.py::test_full_pair_stem_weighted_once_before_sum_and_tail_changes`;
  `tests/test_effects_directivity.py::test_real_room_cardinal_gain_and_small_estimator_ladder_direction`.
- Passing off-state (1/1): `disabled_omni_off_state`. Off-state id:
  `tests/test_effects_directivity.py::test_diagnostics_exact_schema_order_and_explicit_omni_off_state`.

### `S3C-08` - measured absorption and dynamic shoebox rooms

- Passing fixtures (4/4): `material_source_provenance`,
  `dynamic_room_material`, `moving_source_array`, and `recompute_always`.
- Validating ids:
  `tests/test_acoustic_materials.py::test_frozen_material_table_rows_and_source_provenance_are_exact`;
  `tests/test_dynamic_rooms_invalidation.py::test_room_hash_and_output_diverge_for_geometry_and_material_mutations`;
  `tests/test_dynamic_rooms_invalidation.py::test_source_and_array_motion_use_current_endpoints_without_stale_output`.
- Passing off-state (1/1): `off_state_predecessors`. Off-state id:
  `tests/test_dynamic_rooms_invalidation.py::test_off_state_frame_has_no_acoustics_namespace_and_is_byte_deterministic`.

### `S3C-09` - live direct-ray/transmission occlusion

- Passing fixtures (2/2): `clear_blocked_partial_material` and
  `live_moving_occluder`.
- Validating ids:
  `tests/test_isaac_occlusion.py::test_live_sensor_occlusion_attenuates_flags_and_reports_diagnostics`;
  `tests/test_isaac_occlusion.py::test_room_backend_band_attenuation_shows_in_exported_wav`;
  `tests/test_dynamic_rooms_invalidation.py::test_live_extension_tracks_occluder_move_and_anchor_refresh_without_stale_state`;
  `make live-isaac-occlusion`.
- Passing off-state (1/1): `off_state_predecessors`. Off-state ids:
  `tests/test_isaac_occlusion.py::test_live_sensor_occlusion_disabled_by_default`;
  `tests/test_dynamic_rooms_invalidation.py::test_off_state_frame_has_no_acoustics_namespace_and_is_byte_deterministic`.

### `S3C-10` - combined stress envelope

- Passing fixtures (5/5): `multi_source_overlap`,
  `occluder_mount_current_state`, `identity_churn_ambiguity`,
  `reverb_and_all_effects`, and `determinism`.
- Validating ids:
  `tests/test_s3_stress_matrix.py::test_p03_overlap_ladder_keeps_every_source`;
  `tests/test_s3_stress_matrix.py::test_p07_p08_current_occlusion_and_moving_mount_state`;
  `tests/test_s3_stress_matrix.py::test_p09_identity_persistence_under_256_frame_churn`;
  `tests/test_s3_stress_matrix.py::test_p10_all_effects_l2_and_complete_live_forwarding`;
  `tests/test_s3_stress_matrix.py::test_p12_gap_preservation_and_p13_determinism_replay`.
- Passing off-states (2/2): `matrix_capability_audit` and
  `live_s3_stress`. Off-state ids:
  `tests/test_s3_stress_matrix.py::test_matrix_profiles_and_explicit_unsupported_cells`;
  `S3.8/live_s3_stress:effects_off`.

## Fidelity-ladder reconciliation

The `b171f48` change to
`src/isaac_audio_sensors/core/fidelity.py` changes limitations only; the
`models` tuples and public v1 scope are untouched. The exact removed and added
`does_not_model` strings are:

| Level | Removed exact string | Added exact strings |
| --- | --- | --- |
| L2 | `full material, occlusion, and directivity realism`; `source directivity and microphone self-noise (metadata-only at L2)` | `non-shoebox room geometry`; `diffraction or a complete wave solver`; `reflected-path angular directivity (per_pair_direct_path uses the direct-path angle for the full convolved pair stem)`; `diffuse-field noise coherence`; `measured material transmission (measured materials cover absorption only; transmission presets are nominal)` |
| L3 | `frequency-dependent or material-based occlusion and diffraction` | `diffraction, edge bending, reflected-path occlusion, or a complete wave solver`; `reflected-path angular directivity (per_pair_direct_path uses the direct-path angle for the full convolved pair stem)`; `diffuse-field noise coherence`; `measured material transmission (measured materials cover absorption only; transmission presets are nominal)` |

The retained L2 exclusions remain `calibrated acoustic twins`, `calibrated
microphone response`, and `production beamforming`. The retained L3
exclusions remain `a complete v1 runtime backend`, `calibrated sim-real
acoustic behavior`, and `production perception or speech recognition`.

## Acceptance-lock checks

The S3.9 row in
`docs/development/specs/s0_squadbot_readiness_acceptance.md` is satisfied
explicitly:

1. The required published specification exists at
   `docs/development/specs/s3_fidelity_envelope.md`; the gate verifies its
   pinned SHA-256 and mandatory boundary text. The pinned specification states
   the supported geometry, dependencies, performance observations, and limits.
2. Every one of the 10 published realism claims maps to at least one passing
   predecessor fixture and at least one passing compatibility off-state. All
   41 affirmative and 12 off-state artifact hashes match, and all referenced
   test ids are present.
3. Ray/transmission occlusion is never claimed as diffraction or a complete
   wave solver. The specification states exactly `Ray/transmission occlusion
   is NOT diffraction and is NOT a complete wave solver.` and describes the
   direct-ray/transmission exclusions. The regression
   `tests/test_fidelity_envelope.py::test_mandatory_occlusion_and_public_boundary_text_is_guarded`
   requires that exact disclaimer, the unchanged public-v1 boundary, and P1
   ownership of the scaled effects-on 20 ms gate.
4. Unsupported or overstated claims were removed through the exact L2/L3
   reconciliation above. No public frame-v1 or v1 release promise was
   expanded.

## Tests

- Pre-S3.9 orchestrator-measured `make test` at the S3.8 evidence revision:
  1096 passed, 0 failed, 77 documented optional-dependency skips.
- Post-S3.9 orchestrator-measured `make test` at `b171f48`: 1100 passed, 0
  failed, 77 documented optional-dependency skips: four additional passing
  guard tests and no change in skips.

The S3.9 guard tests cover every public effects configuration surface, exact
verbatim reconciliation of every `does_not_model` string, mandatory
occlusion/public/performance boundary text, and complete claim-map/gate hash
verification.

## Limitations carried forward

The published envelope is bounded simulation evidence, not calibrated
physical truth. L2 remains an approximate pyroomacoustics shoebox/image-source
path. It does not provide arbitrary room meshes, diffraction or a complete
wave solver, edge bending, reflection/path-resolved occlusion or directivity,
diffuse-field noise coherence, measured transmission, a calibrated microphone
response, hardware behavior, physical-robot behavior, real-time guarantees,
or sim-to-real validity. Measured material rows cover absorption only;
transmission presets and explicit USD loss values are nominal simulation
parameters. `per_pair_direct_path` applies the direct-path angular response to
the complete convolved pair stem, including its reflected tail.

P2 owns optional diffraction/richer propagation, non-shoebox or richer room
models, reflection/path-resolved directivity and occlusion, richer spatial
noise fields, broader measured-material coverage, and multi-backend fidelity
comparison. S4 owns reference-rig measurements, calibration, and holdout
evidence before any calibrated claims. P1 retains the scaled effects-on 20 ms
performance gate; S3.8/S3.9 host telemetry does not satisfy it.

## Next input contract

S3.9 closes the last S3 subphase gate. The next repository step is the S3
phase closeout at `docs/development/closeouts/S3_closeout.md`, including its
final verification battery and `consumer-gate`. After that phase closeout,
the next implementation input is S4.1, BOM and frame lock. No S4 calibrated
claim may inherit a pass from this simulation-only envelope.

## Confidence remediation (2026-07-18)

The published envelope's SRP metric limitation has been updated to the
noise-aware formula frozen in `s3_channel_effects_chain.md` §9.6.2 by commit
`bb2efe7` (prospective entry `5bfa67e`) and implemented by `1e6e18f`.
`bearing_confidence` is now documented as a supported, noise-aware,
uncalibrated reliability ordering that degrades under the frozen directivity-
suppression fixture; it is not documented as a probability. The legacy
prominence-only saturation remains as historical context. Occlusion and all
other fidelity-envelope wording are unchanged by this remediation.

The regenerated authoritative claim map reports `status="passed"`, 10/10
claim rows, 41/41 affirmative fixture hashes, and 12/12 compatibility
off-state hashes: 53/53 mapped artifacts in total. Its SHA-256 is
`a50d758b4828a2c7d80f638f71d1bb32d1714d05ae98a5c7268753f26e07b3d4`,
superseding the earlier claim-map hash recorded above. The regenerated S3C-07
row pins `estimator_confidence_ladder.json` at
`c1513fd55ce701c06b266f4e313bc387e39b6f5d003294bd3c531c2e75b1d79b`;
the S3.9 gate reports all 10 rows `passed`, empty `failed_rows`/`failures`, and
the same claim-map hash.

For exact provenance, that regenerated gate pins the pre-wording-update
envelope SHA-256
`635ba6f95c0a10b9436e1dda802f4454674250d142974e2d89a0433815318471`.
This later documentation-only wording revision has SHA-256
`01b32680e095032ac1853e2cff0a9860a652c5992d9e076b270e367185d3ad0f`;
it is not relabeled as the already-recorded gate run. The gate's passing
claim-map and owning-row evidence remain authoritative at their recorded
revision.
