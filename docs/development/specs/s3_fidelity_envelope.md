# Stage 1 fidelity envelope

## Status and authority

| Field | Published value |
| --- | --- |
| State | **Passed S3.1-S3.8 evidence; S3.9 claim reconciliation** |
| Publication date | 2026-07-18 |
| Entry revision | `a54b7f6f0d8f5833612224d5db4cdb6cc5fddc23` (`a54b7f6`) |
| Scope | Stage 1 simulation behavior needed by the S3 bench, moving-robot, hallway, occlusion, and multi-source scenarios |
| Public-contract effect | None. This document does not expand `docs/v1_scope.md`, the frame-v1 contract, or the v1 release promises. |
| Claim map | `outputs/isaac_audio_sensors/S3/S3.9/claim_evidence_map.json` |
| Gate | `outputs/isaac_audio_sensors/S3/S3.9/fidelity_envelope_gate.json` |

This is the published, evidence-bounded S3 fidelity envelope. A capability is
supported only inside the backend, runtime profile, geometry, dependency, and
limitation boundaries below. Passing simulation fixtures do not establish a
calibrated physical microphone, robot, room, material, hardware, real-time, or
sim-to-real claim.

The public v1 boundary remains deliberately narrower. In particular, v1 still
does not promise complete L3/L4 fidelity or realistic occlusion/material
acoustics. The S3 results are opt-in implementation and validation records, not
a public-contract expansion.

## 1. Status by fidelity level and path

| Level/path | Stage 1 status | Geometry and output | Dependencies | Runtime-profile applicability |
| --- | --- | --- | --- | --- |
| L0 `geometry_only` | Stable geometry path; S3 effects are limited to metadata-representable channel gain/delay/polarity, already-resolved occlusion/material attenuation, and multi-source identity. It makes no Doppler observation. | Arbitrary finite 3D source poses and 3D microphone arrays; no waveform or room solver. | Base package only; live ray resolution separately requires Isaac/PhysX. | `training_features` and `waveform_fidelity`, without implying waveform effects. |
| L1 `tdoa_synthetic` | Stable synthetic direct-path timing path; adds authored/derived linear-velocity Doppler diagnostics, metadata gain/delay/polarity, jitter/drift timing offsets, already-resolved occlusion attenuation, and explicit ambiguity. | Arbitrary finite 3D poses and arrays; synthetic delays/RMS, no room waveform. | Base package only; live ray resolution separately requires Isaac/PhysX. | `training_features` and `waveform_fidelity`; waveform-only settings fail typed. |
| L2 `room_acoustics` / `room_acoustics_srp` | Supported optional approximate waveform path with the S3 channel/noise/electronics/directivity chain, piecewise motion, measured-absorption selection, and resolved ray/transmission attenuation. | Axis-aligned shoebox rooms only; arbitrary finite 3D source poses and 3D arrays inside the room under the configured out-of-bounds policy. | Linux acoustic pack / `room` extra with pyroomacoustics `0.10.1`; evidence also used SciPy and soundfile. Live occlusion requires Isaac/PhysX. | `waveform_fidelity` for waveform effects. |
| Isaac Sim live adapter | Supported live pose and ray-resolution adapter within its recorded runtime. | Current 3D stage poses; room backend remains shoebox even when anchored from a stage bounding box. | User-managed Isaac Sim/Kit; PhysX for live raycasts; room pack for L2. | Forwards the selected backend/profile. |
| Isaac Lab batched path | Effects-off selected envelope only. Authored velocity works through the scalar core-frame path; batched derived velocity and all S3 waveform effects/occlusion/materials fail explicitly. | Fixed-shape 3D tensor observations; no S3 batched waveform path. | User-managed Isaac Lab and CUDA for the recorded GPU gate. | The recorded 4,096-environment gate is the effects-off batched `tdoa_synthetic` path. |
| L3 `advanced_realism` | Provisional metadata level, not a selectable backend. The first shipped L3 capability remains opt-in Isaac-layer ray/transmission attenuation. | No independent L3 room/wave backend. | Isaac/PhysX for the live capability. | Not runtime-selectable as `advanced_realism`. |
| L4 `sim_real_calibration` | Experimental/tooling vocabulary only. | No stable backend or accepted automatic calibration workflow. | Future calibration tooling. | Not runtime-selectable. |

The only accepted room geometry is the pyroomacoustics shoebox/image-source
model. “3D arrays” means finite microphone locations and orientations in 3D;
it does not mean arbitrary room meshes are solved as waves. Rank limitations
still apply to observability and estimator ambiguity.

## 2. Realism claim ledger

Only the following rows are affirmative Stage 1 realism claims. The S3.9
script maps every claim id to the named executed gate row(s), retained fixture
artifact(s) and SHA-256 values, and the compatibility off-state. Prose outside
this ledger reports configuration, measurements, or unsupported boundaries; it
does not create an additional realism claim.

| Claim id | Bounded claim |
| --- | --- |
| `S3C-01` | Live Isaac snapshots can derive world-frame linear source/array velocity from timestamped poses under the frozen first-sample, reset, stale, teleport, smoothing, and authored-precedence policy. |
| `S3C-02` | The opt-in dataset recorder preserves eligible simulation-time gaps as bounded streamed zero input while advancing overlap/reverb carry. |
| `S3C-03` | The validated L2 fixture approximates intra-window motion with eight ordered midpoint-held segments, including phase-continuous Doppler assembly and cross-segment RIR tails. |
| `S3C-04` | L2 waveforms can apply configured per-microphone magnitude response, scalar gain, fractional delay, and polarity; L1 represents only gain/delay/polarity metadata. |
| `S3C-05` | L2 waveforms can add deterministic seeded spectral self-noise, scalar common/independent ambient noise, window jitter, and deterministic clock drift under the frozen named-stream policy. |
| `S3C-06` | L2 waveforms can apply stateless per-window AGC, hard clipping, normalized float-domain mid-tread quantization, and optional deterministic TPDF dither once to the summed mixture. |
| `S3C-07` | L2 waveforms can apply signed source/microphone polar and magnitude responses in `per_pair_direct_path` mode to each full convolved pair stem before summation. |
| `S3C-08` | L2 shoebox rooms can select the frozen measured absorption rows and recompute current room/RIR output for room, material, source, and array changes without an acoustic-result cache. |
| `S3C-09` | The live Isaac adapter can resolve current direct rays with PhysX and apply ordered per-surface transmission loss consistently to waveform, RMS, diagnostics, and export. |
| `S3C-10` | Inside the supported matrix, the combined S3 chain retained finite values, current state, deterministic replay, explicit ambiguity, and source identity through the frozen motion and 2/4/8-source stress fixtures. |

## 3. Velocity derivation

The normative formulas, policy order, and configuration are frozen in
`s3_motion_policies.md` §§2-6. For a strictly later pair,
`v_raw=(p_k-p_(k-1))/(t_k-t_(k-1))`; optional smoothing is
`v_n=alpha*v_raw+(1-alpha)*v_(n-1)`. Authored velocity wins bit-for-bit.
Strict time decrease resets, gaps greater than `0.5 s` are stale, and speeds
strictly greater than `50 m/s` are teleports. Policy-absent velocities yield
exact unity Doppler rather than a fabricated zero estimate.

Measured acceptance: maximum raw component error was
`7.105427357601002e-14 m/s` against `1e-9 m/s`; `alpha=0.5` error after 40
updates was `1.816147232602816e-11 m/s` against `1e-9 m/s`; all 12 policy
boundary rows passed. Teleport fixtures reported exact `1.0` central and
per-microphone factors, no Doppler waveform render, and next-frame recovery.

Off-state: `derive_velocity_from_poses=false` allocates/updates no pose history,
adds no `motion` diagnostic, and preserved the frame bytes at SHA-256
`f4c35bf436ee2b27c0cab239ada54134aaad7244d1b230b17b73eef90b53c555`.
This behavior is base-package core logic when fed timestamped poses; live pose
derivation is an Isaac Sim path. Isaac Lab batched derivation is unsupported.
Only world-frame linear velocity is derived: no angular velocity, angular
Doppler, acceleration estimator, extrapolation, or calibrated real motion is
modeled.

## 4. Time gaps and intra-window motion

The normative placement, round-half-even, carry, segment division, midpoint
geometry, Doppler cursor, RIR overlap-add, and error formulas are frozen in
`s3_motion_policies.md` §§9-12. Gap preservation is the top-level dataset
session field `preserve_time_gaps`, not a backend effect. Piecewise motion uses
`[audio.effects.motion]` and is limited to L2 `waveform_fidelity` with a live
bracketed pose stream.

Measured gap acceptance: starts `0.00, 0.05, 0.45 s` inserted exactly `16,800`
samples, produced exactly `24,000` pure-fixture samples, and placed the
zero-tail interval at `[4,800,21,600)`. The amended live `W=4800`, `H=2400`
fixture produced exactly `26,400` samples and advanced the 2,399-sample carry
bit-for-bit before exact zeros. Allocations were capped at `1,048,576` bytes
and `65,536` samples per block.

Measured motion acceptance at `P=8`: linear error
`0.062291666666666856 m <=0.062500001 m`; acceleration interpolation/total
errors `0.0025000000000000022/0.040497916666666633 m` within
`0.002500001/0.0412890635 m`; circular total error
`0.06350751277362332 m <=0.0751953135 m`; boundary residual was `0.0` pure and
`6.834050669812797e-8` live against `2e-6` full scale.

Off-state: absent `preserve_time_gaps` selects the pinned recorder path;
`segments_per_window=1` selects the literal pre-S3.2 room path and emits no
segment diagnostic. L0/L1 reject `segments_per_window>1`. Orientation is held
at the window end; geometry is midpoint-held rather than continuously solved;
there is no angular interpolation or continuously moving RIR solver.

## 5. Channel response and mismatch

The normative operation is the `s3_channel_effects_chain.md` §6 chain:
magnitude FIR, scalar `10**(gain_db/20)`, polarity, then zero-padded FFT
fractional delay. The Type-I magnitude FIR uses the frozen tap policy (513
taps at 48 kHz). Arbitrary measured phase is unsupported; non-null
`phase_deg` fails typed, and finite-window FIR/delay edge transients remain in
exported windows.

Measured maxima were `1.7763568394002505e-15 dB` tone gain error against
`0.05 dB`, `0.056966922675175446` sample delay error against `0.10`, exact
polarity bytes, and `0.05422703518646843 dB` accepted-bin response error
against `0.25 dB`. The L1 adapter measured gain error
`2.6645352591003757e-15 dB` and delay error
`3.5744790374131474e-19 s`; polarity remains honest metadata only there.

Off-state: the pure chain returns the same array object and empty diagnostics;
the L2 frame/waveform matched the pre-effect goldens and omitted `effects`.
Frequency response is L2 `waveform_fidelity` only and needs the room pack for
backend use. Configured response is not a calibrated microphone response.

## 6. Seeded noise and clocks

The absolute-level, spectrum-energy normalization, ambient mixture, jitter,
clock-drift interpolation, and SHA-256/PCG64 named-stream formulas are frozen
in `s3_channel_effects_chain.md` §§5 and 7. Levels are full-band dBFS RMS, not
dB SPL or A-weighted measured microphone self-noise.

Measured maxima/results: self-noise Welch error
`0.9622565267035996 dB <=2.0 dB`; RMS error
`0.012796524714257629 dB <=0.15 dB`; ambient-correlation errors
`0.004386210225208247` at `c=0` and `0.004066954163581438` at `c=0.25`, both
within `0.02`, with exact bytes at `c=1`; jitter mean/std ratios
`0.001923702666778774/0.0028114851532714535 <=0.01`; jitter delay error
`0.06606662182307899` sample `<=0.10`; drift slope error
`0.02900805148227903 ppm <=0.50`; unintended stream correlation maximum
`0.006212507754909013 <=0.010`. Same seeds replayed exactly.

Off-state: pure input identity and the pinned backend frame/waveform bytes were
exact, and no `effects` key appeared. L1 supports jitter/drift timing metadata
only; spectral self/ambient noise is L2 waveform behavior. The ambient
`coherent_fraction` is only a scalar common/independent power mixture. There
is no diffuse-field noise coherence, microphone-spacing model, directional
field, or frequency-dependent spatial coherence.

## 7. Electronics

The frozen `s3_channel_effects_chain.md` §8 order is stateless per-window AGC,
hard clip, then mid-tread quantization, executed once on the summed mixture.
`Delta=2*full_scale/2**bit_depth`; optional TPDF dither uses the shared root
seed but an isolated `electronics:tpdf_dither` named stream.

Measured results: clipping counts `(0,0,16,8)` and ratio `0.375` were exact;
quantization error-power ratio was `1.0000076296592806` in `[0.9,1.1]`;
maximum dither error correlation was `0.002294744828159694 <=0.010`; AGC trace
error was `0.0` and settling error `0.008736978433394993 dB <=0.01 dB`; all
65,537 frozen 16-bit reconstruction levels were byte-idempotent without
dither.

Off-state: same input object/bytes, empty diagnostics, and pinned backend
frame/waveform identity. Electronics is L2 waveform-only; L0/L1 and Lab
batched compute reject it. The model is not packed PCM, a codec, ADC
nonlinearity/voltage, a soft-knee circuit, cross-frame compressor, linked-array
AGC, peak limiter, or physical circuit.

## 8. Waveform directivity and estimator metrics

The signed first-order polar families, local `+X` axes, quaternion convention,
magnitude FIR, pair product, and insertion point are frozen in
`s3_channel_effects_chain.md` §9. In `per_pair_direct_path` mode, one response
selected from the direct-path source/microphone angles weights the pair's
complete convolved stem before source summation.

Measured maxima/results: polar scalar error `0.0`; cardinal gain error
`1.9286549331065747e-15 dB <=0.05 dB` with exact nulls; pure single/cascaded
frequency errors `0.14409013359364728/0.288180267187292 dB` within
`0.25/0.50 dB`; real-room single/cascaded errors
`0.13955040728489496/0.27904434940680023 dB`; direct and RIR-tail samples both
changed. The eight-seed ladder measured known-component SNR
`18.0, 11.981137659070544, 5.964011067002487, -61.99303771068348 dB`, GCC
peak proxies `0.060349256016301575, 0.057234941463797456,
0.049627515950882085, 0.0019543655363612558`, rear SRP bearing error `63°`,
and a `19.6459211735 dB` peak-grid-power drop.

Off-state: disabled directivity and explicit frequency-flat omni preserved all
eight pinned frame/waveform fixtures exactly and added no effects diagnostic.
This mode is L2 `waveform_fidelity` and requires the room pack.

Reflected-path angular directivity is NOT modeled. The direct arrival and all
reflections in one pair receive the same response selected from the direct
path. This is not path-resolved directivity, and pyroomacoustics-native
directional objects are not a Stage 1 fallback.

### Metric limitations

`bearing_confidence` is a supported noise-aware, uncalibrated reliability
ordering under the formula frozen by the 2026-07-18 remediation in
`s3_channel_effects_chain.md` §9.6.2 (specification/decision commit `bb2efe7`,
prospective entry `5bfa67e`). Across the regenerated `0°,90°,120°,180°`
directivity-suppression ladder, its eight-seed medians were
`0.05814612482686094, 0.05514319161396962, 0.04778229697397164,
0.0006422450143033353`: non-increasing at every rung, above the frozen
`0.050` front floor, below the `0.005` rear ceiling, and with a
`0.0575038798125576` front-to-rear drop against the `0.040` minimum. It ranks
reliability; neither the value nor either formula factor is a probability of
correct localization.

Historically, the superseded prominence-only formula
`clamp((peak_power-mean_power)/peak_power, 0, 1)` saturated on
noise-dominated input: its corresponding medians rose from
`0.9635921293431229` to `0.9842162004789096` while SNR fell nearly 80 dB.
That limitation remains provenance for the legacy behavior; the dated
`bb2efe7`/`5bfa67e` remediation added absolute noise sensitivity without
changing `ias.audio_sensor_frame.v1`.

The GCC value above is a fixture proxy: the median absolute pairwise
`GccPhatDelay.peak_value`, then the median over eight fixed seeds. It behaved
monotonically in this controlled ladder, but it is not a calibrated
probability, portable confidence score, or moving/multi-source guarantee.

Two microphones do not support a unique bearing without an ambiguity policy.
L1 and room GCC surface ambiguity or an unresolved result. Two-microphone
`room_acoustics_srp` is outside the claimed envelope and fails explicitly; it
must not return one confident bearing. Lab TDOA requires at least three
microphones.

## 9. Materials, dynamic rooms, and occlusion

Material source/provenance, six-band resolution, room state hashing,
recompute-always behavior, and exact invalidation reasons are frozen in
`s3_acoustic_state_invalidation.md`. Room propagation is the approximate
pyroomacoustics shoebox/image-source path. There is no RIR, premix, waveform,
occlusion, or other acoustic-result cache; each successful room simulation
computes one current RIR per segment.

Measured material/dynamic results: all seven measured absorption and nine
nominal rows matched the frozen table/database SHA-256
`1249f0cfdcd4598cf98ec9be05230f910e53aa1da4861d7fe3f88de23a24e0e0`;
six-band attenuation error was `3.552713678800501e-15 dB <=0.05 dB`; waveform
to frame RMS error was `0.0 <=1e-12`; room origin, dimension, and material
mutations changed state hash/RIR/output with exact refresh reasons; `P=1` and
`P=8` observed `1/1` and `8/8` room/RIR counts.

Measured occlusion results: the live five-state sequence produced factors
`0,0.25,1,0.25,0`, with clear/right/all/left/clear blocked maps. Affected
channels measured `12.0` to `12.000000000000002 dB` against the live
`12.0 +/-0.5 dB` bound, unaffected residue was at most
`1.9286549331065747e-15 dB`, each frame recomputed once, and pose-only wall
motion did not force rediscovery.

Off-state: no room/material resolution and disabled occlusion add no
`acoustics_state` namespace and preserve the pinned L0/L1 bytes. Scalar room
compatibility preserves existing samples while adding only the active-room
state diagnostic. Live ray resolution requires current Isaac/PhysX; without
it the capability is unavailable rather than silently treated as physical
occlusion.

Measured materials cover absorption only. The seven `pra.*` rows have no
measured transmission data, and requesting it fails closed. Transmission
presets and explicit USD loss values are nominal simulation parameters. The
shared applied grid ends at 4 kHz; source 8 kHz values are provenance only.

Ray/transmission occlusion is NOT diffraction and is NOT a complete wave solver.
It does not model edge bending, scattering, portal propagation,
thickness/phase-through-material behavior, reflected-path occlusion, or
changes to RIR reflection paths.

## 10. Combined stress envelope

S3.8 executed all 55 supported/unsupported/N/A matrix cells: 34 supported
executions, 14 exact pre-output unsupported errors, and 7 N/A rationales. The
2/4/8-source ladder ran both L2 backends without truncation; coincident and
near/far identities remained distinct; 256-frame churn produced no swap or
ghost; all-effects L2 ran 32 frames per backend; every P01-P12 canonical hash
matched the main process and two fresh processes.

These stress results validate bounded combinations, not richer physics. In
particular they do not add diffraction, arbitrary room geometry,
reflection-specific directivity, diffuse-field noise, calibrated materials,
hardware response, robot behavior, or sim-to-real validity.

## 11. Performance and resource observations

All figures in this section are machine-local telemetry from the recorded S3.8
host. They are not a portable CPU/GPU promise and explicitly are NOT a
real-time envelope.

The pure `P11` 4,096-frame run measured mean/p95/p99/max latency
`20.291947309570315/29.8144695/33.35439085000001/36.819111 ms`. Its Linux
`VmRSS` OLS slope was `0.11077995334605939 MiB/1,000 frames`, peak delta
`0.73046875 MiB`, and settled delta `1.65234375 MiB`, within the frozen
`4/128/32 MiB` guards. This path used two source slots, `max_order=1`,
`segments_per_window=1`, and the remaining L2 effects; it is not a scaled Lab
training result.

The live paired same-stage gate timed 540 frames per phase. Effects-off p95 was
`148.67477135 ms`; effects-on p95 was `940.5367802999998 ms`. The accepted
regression formula was
`effects_on_p95 <= segments_per_window * effects_off_p95 + 5 ms`, giving
`940.5367802999998 <=1194.3981708 ms` for `P=8`. Effects-off p99/max were
`162.17489414000002/174.74667 ms`; effects-on p99/max were
`995.03617189/1021.591402 ms`. This is a linear segment cost-model guard for
eight room/RIR rerenders, not a claim that the path meets audio deadlines.

The Isaac Lab effects-off batched regression used 4,096 environments, four
microphones, two sources, `tdoa_synthetic`, CUDA, 10 warm-ups, and 50 timed
updates. Its p95 was `11.110301013104618 ms` against the machine-local `20 ms`
budget. The effects-on companion was report-only: the supported scalar
`room_acoustics` path with channel response, noise, and electronics measured
mean/p50/p95/p99/max
`6.208645683333333/6.323294499999999/8.3007078/8.43487531/8.470624 ms` over 60
iterations after five warm-ups. It was not the Lab batched path and has no
S3.8 budget.

P1 owns the scaled effects-on 20 ms gate. No S3.8/S3.9 measurement may be
quoted as satisfying that future gate.

## 12. Configuration surfaces and applicability

These are all user-facing `[audio.effects.*]` TOML surfaces. Every absent or
disabled top-level stage normalizes to its compatibility off-state.

- `[audio.effects.channel_response]`
- `[audio.effects.channel_response.microphones.<mic_id>]`
- `[audio.effects.noise]`
- `[audio.effects.noise.self_noise.default]`
- `[audio.effects.noise.self_noise.microphones.<mic_id>]`
- `[audio.effects.noise.ambient]`
- `[audio.effects.electronics]`
- `[audio.effects.electronics.agc]`
- `[audio.effects.directivity]`
- `[audio.effects.directivity.source_patterns.default]`
- `[audio.effects.directivity.source_patterns.overrides.<source_id>]`
- `[audio.effects.directivity.mic_patterns.default]`
- `[audio.effects.directivity.mic_patterns.overrides.<mic_id>]`
- `[audio.effects.motion]`

The recorder field `preserve_time_gaps` is intentionally outside
`[audio.effects.*]` because the session timeline, not the propagation backend,
owns gap placement.

## 13. Fidelity-ladder limitation reconciliation

The exact `does_not_model` strings below are the code/document consistency
surface. They state exclusions; they do not expand the `models` tuples or the
v1 scope.

| Level | Exact exclusions |
| --- | --- |
| L0 | `acoustic propagation`; `waveforms`; `reverberation`; `occlusion`; `physical microphone response` |
| L1 | `reverberant rooms`; `hardware microphone response`; `calibrated noise`; `speech recognition` |
| L2 | `calibrated acoustic twins`; `non-shoebox room geometry`; `diffraction or a complete wave solver`; `reflected-path angular directivity (per_pair_direct_path uses the direct-path angle for the full convolved pair stem)`; `diffuse-field noise coherence`; `measured material transmission (measured materials cover absorption only; transmission presets are nominal)`; `calibrated microphone response`; `production beamforming` |
| L3 | `a complete v1 runtime backend`; `diffraction, edge bending, reflected-path occlusion, or a complete wave solver`; `reflected-path angular directivity (per_pair_direct_path uses the direct-path angle for the full convolved pair stem)`; `diffuse-field noise coherence`; `measured material transmission (measured materials cover absorption only; transmission presets are nominal)`; `calibrated sim-real acoustic behavior`; `production perception or speech recognition` |
| L4 | `a stable v1 runtime backend`; `automatic hardware calibration`; `guaranteed transfer to a physical robot` |

## 14. Deferred boundary

P2 owns optional diffraction/richer propagation, non-shoebox or richer room
models, reflection/path-resolved directivity and occlusion, richer spatial
noise fields, broader measured material coverage (including any measured
transmission claim), and multi-backend fidelity comparison. S4 owns measured
reference-rig calibration and holdout evidence. P1 owns effects-on performance
at scale. None is implied by this S3 closeout.
