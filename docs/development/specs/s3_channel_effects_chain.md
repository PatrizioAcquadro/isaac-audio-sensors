# S3 channel-effects chain

## Status and scope

| Field | Frozen value |
| --- | --- |
| State | Frozen prospective design; implementation and evidence do not yet exist |
| Design date | 2026-07-18 |
| Entry revision | `716336095f3436d824c76de4387374ff009022c3` |
| Governing gates | `S3.3` channel response, `S3.4` seeded noise, `S3.5` electronics, `S3.6` waveform directivity |
| Governing acceptance | `docs/development/specs/s0_squadbot_readiness_acceptance.md` §S3 |
| Evidence roots | `outputs/isaac_audio_sensors/S3/S3.3/` through `outputs/isaac_audio_sensors/S3/S3.6/` |

This specification freezes the common per-channel effects architecture and the
complete `S3.3` acceptance protocol before implementation or acceptance
evidence. It preserves the existing `ias.audio_sensor_frame.v1` fields and
meaning. Effects add optional configuration and diagnostics; they do not create
a new frame contract or a new propagation backend.

The numerical tolerances for `S3.4`, `S3.5`, and `S3.6` are intentionally not
set here. Their architecture placement is frozen by this document, and each
owning section carries the mandatory pre-evidence revision rule.

## 1. Problem definition and responsibility boundary

The effects chain models channel-local hardware behavior after acoustic
waveform synthesis while keeping propagation, estimation, and export mutually
consistent. Its responsibilities are:

1. apply configured microphone frequency response, scalar gain, fractional
   delay, and polarity (`S3.3`);
2. add seed-replayable spectral self-noise, ambient noise, timing jitter, and
   drift without sharing accidental random streams (`S3.4`);
3. model quantization, clipping/saturation, and optional AGC (`S3.5`); and
4. provide the configuration and diagnostics boundary for source/microphone
   waveform directivity, while leaving its actual application at synthesis
   time (`S3.6`).

Propagation backends still own acoustic synthesis and room behavior. DOA
estimators still own localization. Effects are backend configuration, not
plugins, and therefore do not add a `PluginDeclaration` or a registry kind.
Calibration fitting remains owned by `S4.5`; this design only ensures fitted
channel values can enter the effects configuration without renaming or unit
translation.

## 2. Package and chain architecture

### 2.1 Pure package layout

Implementation adds an import-safe, NumPy-only package at
`src/isaac_audio_sensors/core/effects/`:

| Module | Frozen responsibility |
| --- | --- |
| `chain.py` | `ChannelEffectsChain`, ordered stage dispatch, hard off-state fast path, and diagnostics aggregation |
| `channel_response.py` | `S3.3` frequency response, gain, fractional delay, polarity, and L0/L1 metadata adaptation helpers |
| `noise.py` | `S3.4` waveform noise and metadata-representable timing-noise stages |
| `electronics.py` | `S3.5` quantization, clipping/saturation, and AGC |
| `directivity.py` | `S3.6` validated source/microphone pattern evaluation used from synthesis, not from the post-mix chain |
| `streams.py` | Named-stream seed derivation and NumPy `PCG64` generator construction |
| `config.py` | Immutable `@dataclass(frozen=True, slots=True, kw_only=True)` effects configuration records and validation |

“Pure” means no Isaac, Omniverse, GUI, plugin-registry, pyroomacoustics, or
SciPy import. NumPy is the only numerical dependency. Backends call this
package; the package does not import concrete backends.

### 2.2 Stage order and insertion point

The post-synthesis order is fixed:

```text
per-microphone waveform synthesis
    -> channel_response
    -> noise
    -> electronics
    -> GCC/TDOA and DOA estimation
    -> RMS/diagnostics
    -> waveform export
```

Directivity is not a fourth post-mix stage. Source and microphone patterns are
evaluated on each source-to-microphone contribution inside the room backend at
synthesis time, before contributions are summed. This is required because a
post-mix gain cannot retain source angle or source identity.

The effects chain accepts a microphone-major array of shape
`(microphone_count, sample_count)` plus ordered microphone ids, sample rate,
frame id, and immutable configuration. It returns an array with the same shape
and a stage-diagnostics mapping. An enabled stage may allocate a new array;
the all-disabled path has the stronger identity rule in §2.4.

The current room backend builds a per-source/per-microphone `premix`, sums it,
derives GCC-PHAT delay and per-microphone RMS, estimates DOA, and exports the
mixture. The implementation must insert effects before any downstream consumer
of the affected signal:

- directivity and the deterministic linear channel response are reflected in
  the corresponding per-source premix before source-attribution RMS or
  per-source estimator diagnostics;
- stochastic noise and nonlinear electronics are applied exactly once to the
  actual summed mixture, never once per source and then summed;
- any DOA confidence claimed to reflect noise/electronics consumes the final
  processed mixture; and
- frame `aggregate_per_mic_rms` and exported waveform bytes are computed from
  that same final processed mixture.

Detection-level `per_mic_rms` remains the source-attributable premix quantity
already used by `room_acoustics`; noise and nonlinear electronics are not
falsely apportioned among known sources. Frame aggregate RMS is the authoritative
RMS of the effected mixture. This retains the existing source-premix versus
mixture distinction while preventing a pre-effect waveform, post-effect RMS,
or unrelated estimator input from being reported together.

### 2.3 L0/L1 metadata adapter

`geometry_only` (L0) and `tdoa_synthetic` (L1) do not produce waveforms. A
metadata adapter maps only representable channel settings onto their existing
per-microphone metadata path:

- gain is additive in dB before the linear `per_mic_rms` value is produced;
- delay is additive in seconds in `per_mic_delay_s` (for L1, after geometric
  propagation and the unchanged legacy delay-noise draw);
- polarity is recorded exactly as metadata but cannot change a non-existent
  waveform sign; and
- L1 DOA uses the resulting delays, as the existing mismatch path does.

For L0, configured delay values may populate effect-offset metadata, but the
geometry-derived bearing is not reclassified as an acoustic TDOA estimate.
Frequency response, spectral or ambient waveform noise, quantization,
clipping, AGC, and waveform directivity cannot be represented by L0/L1. Any
such enabled setting raises `UnsupportedEffectError`, a package-specific typed
error, before a frame is partially produced. No setting is silently ignored,
approximated, or downgraded.

The L1 formulas are frozen as:

```text
effective_delay_s = distance / c
                  + legacy_delay_noise_s
                  + configured_channel_delay_s

effective_gain_db = MicrophoneSpec.gain_db
                  + legacy_gain_offset_db
                  + configured_channel_gain_db
                  + other already-supported attenuation/gain terms
```

The legacy `_seeded_gauss`, `_delay_noise_s`, and `_gain_offset_db` byte
derivations are not changed by this adapter.

### 2.4 Hard off-state rule

When every effects stage is disabled, `ChannelEffectsChain` must return the
exact input array object (`output is input`) and an empty diagnostics mapping.
It must perform no copy, dtype conversion, ufunc, scalar multiplication, FFT,
validation rewrite, or other floating-point operation on the samples.

Backends must consequently omit `frame.diagnostics["effects"]` entirely and
follow their pre-S3 branch. The serialized frame, detection values, waveform
bytes, ordering, dtypes, and existing diagnostics must be byte-identical to the
entry-revision golden behavior. This is deliberately stricter than the plan's
“within tolerance” wording.

## 3. Configuration contract

### 3.1 TOML surface and immutable records

The only TOML locations are:

```text
[audio.effects.channel_response]
[audio.effects.noise]
[audio.effects.electronics]
[audio.effects.directivity]
[audio.effects.motion]
```

`EffectsConfig` contains immutable records for all five tables. Every stage
has `enabled: bool = False`; every optional scalar, sequence, mapping, or
nested record defaults to `None`. An absent table therefore normalizes to a
disabled record. Mappings are copied into immutable mappings during validation
so a frozen dataclass cannot retain mutable caller-owned state.

`S3.3` freezes these records and field names:

| Record | Fields and defaults |
| --- | --- |
| `FrequencyResponsePointConfig` | `frequency_hz=None`, `magnitude_db=None`, `phase_deg=None` |
| `ChannelResponseMicConfig` | `gain_db=None`, `delay_s=None`, `polarity=None`, `frequency_response=None` |
| `ChannelResponseConfig` | `enabled=False`, `microphones=None` |

`microphones` is keyed by exact `MicrophoneSpec.mic_id`. The value field names
and units mirror `ChannelCalibration`: `gain_db` in dB, `delay_s` in seconds,
`polarity` as `-1` or `1`, and frequency-response points named
`frequency_hz`, `magnitude_db`, and optional `phase_deg`. Thus an `S4.5`
channel fit can serialize the same values into
`ias.audio_calibration_profile.v1` without a field-name or unit translation.
The calibration profile's evidence-status wrappers remain a serialization
concern and are not copied into runtime effects configuration.

The initial `S3.4`/`S3.5`/`S3.6` records reserve only their architectural
containers: noise has optional seed, microphone, ambient, jitter, and drift
settings; electronics has optional per-microphone quantization, saturation,
and AGC settings; directivity has optional source pattern, microphone pattern,
and mode settings. Their concrete nested fields and validation ranges must be
frozen in the mandated later revision before the owning subphase gathers
evidence. `motion` is routed through the same immutable configuration surface
but is implemented and accepted by `S3.1`/`S3.2`, not by this chain.

### 3.2 S3.3 TOML form

The microphone id is the final table key:

```toml
[audio.effects.channel_response]
enabled = true

[audio.effects.channel_response.microphones.front]
gain_db = -0.75
delay_s = 0.0000125
polarity = -1
frequency_response = [
  { frequency_hz = 100.0, magnitude_db = -1.0 },
  { frequency_hz = 1000.0, magnitude_db = 0.0 },
  { frequency_hz = 16000.0, magnitude_db = -2.0 },
]
```

TOML has no null literal; absence maps to `None`. A microphone omitted from the
mapping has unity gain, zero added delay, unchanged polarity, and flat response.
An entry whose fields are all absent is a no-op and is not listed in
`applied_mic_ids`.

### 3.3 Fail-closed validation

Configuration is fully validated against the selected array, backend, runtime
profile, and sample rate before simulation begins:

- an unknown microphone id, duplicate id after normalization, or microphone
  order mismatch raises `ConfigValidationError`;
- gain and delay must be finite; polarity must be exactly `-1` or `1`;
- a frequency response requires at least two finite points, positive strictly
  increasing frequencies, finite magnitudes, and a highest point no greater
  than Nyquist;
- `phase_deg` mirrors the calibration field but non-`None` phase is not modeled
  by the S3.3 magnitude-only linear-phase FIR and therefore raises
  `UnsupportedEffectError` rather than being discarded;
- a requested delay whose zero-padded transform cannot leave a non-empty valid
  region for the current window raises `ConfigValidationError`; and
- a waveform-only feature on L0/L1 raises `UnsupportedEffectError` before any
  detection, diagnostics, or output asset is emitted.

Validation errors name the table, microphone id, field, offending value, and
supported backend/profile envelope.

### 3.4 Runtime profiles

| Runtime profile / backend | Active effects when enabled | Explicitly unsupported |
| --- | --- | --- |
| `training_features`, L0/L1 | metadata-representable channel gain/delay/polarity; seeded timing jitter/drift when its later S3.4 contract permits it; motion metadata | channel frequency response, spectral/ambient waveform noise, all electronics, waveform directivity |
| `waveform_fidelity`, L2/L3 waveform path | channel response, waveform noise, electronics, synthesis-time directivity, and motion | only configurations outside the selected backend's declared waveform capability |

Runtime profile does not silently switch backends. Selecting
`waveform_fidelity` with an L0/L1 backend still does not make waveform-only
effects representable, and selecting `training_features` with such an effect
enabled fails closed.

## 4. Diagnostics and frame compatibility

Effects diagnostics are additive under exactly one frame-level namespace:

```text
frame.diagnostics["effects"][<stage>][<key>]
```

Planned keys are frozen as follows:

| Stage | Keys |
| --- | --- |
| `channel_response` | `applied_mic_ids`, `gain_db`, `delay_s`, `polarity` |
| `noise` | `streams`, `per_mic_rms`, `seed_derivation_id` |
| `electronics` | `clipping_count_per_mic`, `saturated_sample_ratio`, `agc_gain_trace_summary`, `quantization_step` |
| `directivity` | `source_pattern`, `mic_pattern`, `mode` |

Per-microphone mappings use microphone ids and deterministic array order.
`streams` contains stable stream labels/ids, not mutable generator state.
`agc_gain_trace_summary` is a bounded summary; a full trace, if retained, is an
evidence asset rather than an unbounded frame diagnostic. Directivity writes
its diagnostics here even though it executes during synthesis.

If a stage is enabled but applies to no microphone/source, its stage mapping
may be omitted. If all stage mappings are empty, the top-level `effects` key is
omitted. Existing frame fields, units, provenance, and diagnostics retain their
current meaning, so this is an additive `ias.audio_sensor_frame.v1` change.

## 5. Determinism and named random streams

### 5.1 Frozen derivation

`S3.4` implements the helper, but its derivation is frozen now. For each draw
stream, construct the UTF-8 key exactly as:

```text
"{seed}:{domain}:{frame_id}:{mic_id}:{effect}"
```

Compute SHA-256, take digest bytes `[0:8]`, interpret those eight bytes as an
unsigned **little-endian** integer, and construct:

```text
numpy.random.Generator(numpy.random.PCG64(derived_integer))
```

`seed` uses canonical base-10 integer text. Other components use their exact
validated strings without case folding. Domains are stable stage ids
(`noise`, `electronics`, `directivity`, or `motion`); `effect` is the stable
leaf name such as `self_noise`, `ambient`, `clock_jitter`, or `clock_drift`.
Changing a domain or leaf creates an independent stream. The frozen diagnostic
identifier is `sha256-colon-v1-pcg64-le64`.

No stochastic stage may use NumPy's process-global RNG, Python's module-global
`random`, time, process id, call count, array iteration accident, or an
unrecorded generator. A microphone's stream must not change merely because
another microphone or effect is enabled.

### 5.2 Legacy TDOA derivation and plugin self-test

The existing TDOA `_seeded_gauss` derivation is a different, public-regression
relevant algorithm: SHA-256 prefix interpreted big-endian, then
`random.Random(...).gauss`. It remains byte-for-byte unchanged. It may be
replaced only after a checked-in golden regression proves identity for the
supported seed/input corpus; statistical similarity is insufficient.

Effects do not receive a `PluginDeclaration`. Existing propagation declarations
remain `deterministic=True`, and the registry's two-factory, same-fixture exact
self-test must continue to pass. Named streams make stochastic output a pure
function of validated configuration and frame identity, satisfying that
declaration rather than weakening it.

## 6. S3.3 channel response — frozen design and tolerances

### 6.1 Operation definition

Within `channel_response`, each configured microphone applies:

```text
frequency-response FIR -> scalar gain -> polarity -> fractional delay
```

Scalar gain is `10 ** (gain_db / 20)`. Polarity is multiplication by exactly
`-1` or `1`. The configured frequency response is a relative channel response;
its magnitude combines multiplicatively with scalar gain. Configured delay is
an additional channel delay, not a replacement for acoustic propagation or
legacy L1 timing mismatch.

Frequency response uses a NumPy-only, `firwin2`-style Type-I linear-phase FIR:

1. convert configured dB magnitudes to linear amplitude;
2. linearly interpolate amplitude versus frequency with flat extrapolation to
   DC and Nyquist;
3. form a dense real, even target spectrum, inverse transform it, retain the
   centered odd-length impulse response, and apply a Hann window; and
4. perform zero-padded linear convolution, compensate the integer group delay,
   and crop to the original window length.

The tap policy is frozen as
`next_odd(clamp(ceil(sample_rate_hz * 0.010667), 129, 2049))`; this is 513 taps
at 48 kHz. The approximately 10.7 ms support resolves the smooth calibration
fixture without pretending to reproduce arbitrarily sharp measured notches.
If a requested response cannot meet its declared usable band with this policy,
configuration/validation fails rather than increasing the order from observed
acceptance evidence.

Fractional delay uses a phase shift on one FFT of the full window, not a block
FIR. For delay `d` seconds, multiply each rFFT bin by
`exp(-j * 2*pi*f*d)`. Before transformation, pad both ends with
`ceil(abs(d * sample_rate_hz)) + 64` zeros and use a transform length at least
the complete padded length. Crop the central original-length window after the
inverse transform. This prevents circular wrap; samples moved outside the
window are discarded and unavailable samples use the zero-extension
assumption. Recovery measurements exclude the FIR half-support and FFT guard
at both edges. The exported full window retains these documented finite-window
edge transients.

### 6.2 Frozen acceptance numbers

| Criterion | Frozen pass threshold | Brief basis |
| --- | --- | --- |
| Tone gain recovery | maximum absolute error `<= 0.05 dB` for every microphone, configured gain, and test tone | RMS ratios for bin-centred tones are nearly exact; 0.05 dB leaves only finite-window/numerical margin and is well below a meaningful channel mismatch |
| Fractional delay recovery | maximum absolute error `<= 0.10 sample` (`<= 2.083333 microseconds` at 48 kHz) | Full-window FFT delay is band-limited and sub-sample; 0.10 sample accommodates parabolic peak interpolation without accepting a one-sample implementation |
| Polarity | exact `output == numpy.negative(input)` element-by-element and byte-for-byte for the finite fixture; no tolerance | Polarity is a discrete sign operation and any approximate or partial inversion is wrong |
| Frequency-response recovery | maximum passband magnitude error `<= 0.25 dB` on every evaluated Welch bin | The 513-tap smooth linear-phase fit should be substantially tighter; 0.25 dB covers windowed FIR approximation while remaining calibration-useful |
| Chain off-state | same Python array object, identical dtype/shape/strides/bytes, empty chain diagnostics | This is the compatibility identity branch, not a floating-point comparison |
| Backend off-state | byte-identical serialized frame and waveform assets to the entry-revision golden; no `effects` key | Stronger than the plan's “within tolerance” requirement and proves disabled means prior behavior |
| L1 gain adapter | `abs(20*log10(effected_rms / baseline_rms) - gain_db) <= 0.05 dB` per microphone | Uses the same observable and bound as waveform gain recovery |
| L1 delay adapter | `abs((effected_delay_s - baseline_delay_s) - delay_s) <= 1e-12 s` per microphone | The adapter is direct float addition, so waveform estimator uncertainty is irrelevant |
| L1 polarity adapter | exact configured `-1`/`1` in effects diagnostics; RMS/delay unchanged when polarity is the sole setting | L1 has no signed waveform; this explicitly tests honest metadata-only behavior |

All thresholds are maximum errors, not means or percentiles. A single evaluated
microphone, gain, delay, tone, or passband bin outside its bound fails `S3.3`.

### 6.3 Frozen fixtures and measurement methods

All numerical fixtures use float64 processing, 48 kHz, microphone-major
arrays, deterministic content, and no other enabled stage.

| Fixture | Frozen protocol |
| --- | --- |
| Gain tones | 48,000 samples; bin-centred 1 kHz and 8 kHz sine waves at amplitude 0.1; gains `-12`, `-3`, and `+6 dB`; measure `20*log10(rms_out/rms_in)` after the common edge exclusion |
| Fractional delay | 16,384-sample centered band-limited impulse/probe; delays `-3.25`, `-0.50`, `+0.50`, and `+2.75` samples; full cross-correlation followed by three-point parabolic interpolation around the absolute peak; compare recovered signed lag with configured delay |
| Polarity | finite impulse-plus-asymmetric-random fixture containing positive, negative, and signed-zero values; response/gain/delay disabled; compare directly with `numpy.negative(input)` including bytes |
| Frequency response | `2**18` samples of deterministic seed-fixed broadband Gaussian noise; smooth points spanning 100 Hz–20 kHz; Welch H1 transfer estimate `S_yx/S_xx` with Hann windows, `nperseg=8192`, `noverlap=4096`; compare magnitude with the designed target on all bins from 200 Hz through 18 kHz after edge exclusion |
| Off-state golden | impulse, tone, broadband, silent, and current canonical room/plugin fixture; compare array identity in the pure chain and SHA-256/serialized bytes for backend outputs against revision `7163360` |
| L1 adapter | fixed single-source quad-array fixture with legacy stress controls both zero and nonzero; subtract matching baseline so configured deterministic offsets are isolated without changing legacy RNG |

The broadband target is the same linear-amplitude interpolation and flat outer
extrapolation defined in §6.1. Welch bins outside 200 Hz–18 kHz are retained in
evidence but are not passband acceptance bins because DC/Nyquist edge behavior
and finite FIR support dominate there.

## 7. S3.4 seeded noise — architecture freeze

`noise.py` owns independent named streams for spectral microphone self-noise,
ambient noise, clock jitter, and clock drift. Waveform self/ambient noise is
added after channel response and before electronics. Timing jitter/drift that
changes waveform sampling is applied in this stage; the L0/L1 adapter may map
only representable timing offsets into delay metadata. Noise is added once to
the real mixture, never independently to every source premix.

The stage must report the stable stream ids, seed derivation id, and measured
per-microphone added-noise RMS under the diagnostics keys in §4. Fixed seeds
must replay exactly and adding/removing one effect or microphone must not alter
unrelated streams.

> **TOLERANCES DEFERRED:** PSD, RMS, delay-statistic, drift, replay, and
> cross-correlation tolerances will be frozen in a dated revision of this
> specification before any `S3.4` acceptance evidence is generated or viewed.
> They may not be selected or adjusted from final `S3.4` results.

## 8. S3.5 electronics — architecture freeze

`electronics.py` runs after response and noise. Its order is AGC (when
enabled), saturation/clipping, then quantization; a later `S3.5` pre-evidence
revision may freeze a different internal order only by explicitly amending
this architecture before implementation evidence. Electronics processes the
summed mixture once because clipping and AGC are nonlinear and cannot be
distributed across source stems.

The stage emits bounded summaries for clipping count per microphone,
saturated-sample ratio, AGC gain trace, and quantization step. With electronics
disabled it contributes no operation and no diagnostics. Electronics is never
metadata-emulated on L0/L1.

> **TOLERANCES DEFERRED:** quantization-noise, clipping-boundary, saturation,
> AGC attack/release/recovery, diagnostic-count, and off-state tolerances will
> be frozen in a dated revision of this specification before any `S3.5`
> acceptance evidence is generated or viewed. They may not be selected or
> adjusted from final `S3.5` results.

## 9. S3.6 waveform directivity — architecture freeze

`directivity.py` validates and evaluates source and microphone polar/frequency
patterns. The room backend applies the product of source and microphone
responses to each direct source-to-microphone synthesis contribution before
per-source contributions are mixed. It is not a post-mix chain operation.
Pattern evaluation uses the source orientation, microphone orientation, and
the existing coordinate convention; invalid or unsupported patterns fail
before partial synthesis.

Stage 1 directivity is a direct-path/source-to-microphone weighting
approximation. It does not claim that each reflected path has a separately
resolved arrival/departure angle. This limitation must be repeated in `S3.6`
evidence and the fidelity envelope.

> **TOLERANCES DEFERRED:** cardinal-angle, frequency-sweep, invalid-pattern,
> and estimator-confidence-degradation tolerances will be frozen in a dated
> revision of this specification before any `S3.6` acceptance evidence is
> generated or viewed. They may not be selected or adjusted from final
> `S3.6` results.

## 10. S3.3 verification map

The implementation is expected to add focused pure tests in
`tests/test_channel_response.py`, chain/config tests in
`tests/test_channel_effects_chain.py`, and backend integration tests in
`tests/test_effects_backend_integration.py`. Exact test names may follow the
repository naming convention, but each row below is mandatory.

| Acceptance criterion | Proof type and key assertion | Required evidence below `outputs/isaac_audio_sensors/S3/S3.3/` |
| --- | --- | --- |
| Gain recovery | parameterized tone unit test; every observed dB ratio within `0.05 dB` | `gain_tone_results.json`, `gain_tone_summary.csv` |
| Fractional delay | impulse/probe unit test; cross-correlation plus parabolic interpolation within `0.10 sample` | `delay_recovery_results.json`, `delay_correlation_traces.npz` |
| Polarity | impulse/asymmetric fixture unit test; exact bytes equal `numpy.negative(input)` | `polarity_exact_result.json` |
| Frequency response | broadband unit/integration test; Welch H1 maximum passband error within `0.25 dB` | `frequency_response_welch.json`, `frequency_response_overlay.png` |
| Pure off-state | chain regression test; object identity plus empty diagnostics | `off_state_chain_identity.json` |
| Backend off-state | room-backend golden regression; exact frame/waveform hashes and no `effects` key | `off_state_golden_sha256.json`, `off_state_frame.json`, `off_state_waveform_sha256.txt` |
| L1 adapter equivalence | TDOA backend integration test; difference-of-baselines meets gain/delay bounds and polarity is metadata-only | `l1_metadata_adapter.json` |
| Unknown microphone | config invalid-input test; `ConfigValidationError` before simulation | `invalid_config_matrix.json` |
| Unsupported feature | L0/L1 integration test with frequency response; typed `UnsupportedEffectError`, no partial frame/assets | `unsupported_feature_errors.json`, `partial_output_listing.txt` |
| Deterministic backend | existing registry exact twice-run self-test plus enabled fixed effects fixture | `registry_determinism.json` |

`channel_response_gate.json` is the machine-readable roll-up and records entry
revision, package/runtime versions, fixture hashes, sample counts, every frozen
tolerance, measured maxima, per-row status, commands, and artifact SHA-256
values. The subphase closeout is
`docs/development/closeouts/S3/s3_3_channel_response.md`, following the plan's
artifact convention. Evidence files are machine-local until included in the
declared release evidence package.

## 11. Edge cases and failure behavior

The minimum invalid/boundary matrix includes empty and one-sample arrays,
non-finite samples, zero channels, microphone-count/order mismatch, unknown
microphone ids, non-finite gains/delays, invalid polarity, duplicate or
non-monotonic response points, response above Nyquist, non-`None` response
phase, delay larger than the usable window, silent input, signed zeros, and an
enabled waveform-only effect on each L0/L1 backend.

Supported empty-time behavior must follow the backend's existing minimum
window contract; the effects package does not invent samples. Invalid
configuration fails before simulation. Runtime array-shape/dtype failures fail
before any stage mutates caller-owned data. No failed call returns a partial
frame, writes a waveform, advances hidden RNG state, or emits a success
diagnostic.

## 12. Non-goals and limitations

- No diffuse-field spatial-coherence or inter-microphone noise-coherence claim
  is made. Named-stream independence is a determinism/statistical-isolation
  contract, not a room-noise field model.
- S3.6 directivity is the direct-path/source-to-microphone weighting
  approximation in §9; reflected-path angular directivity remains unsupported
  unless a later reviewed design adds and validates it.
- No diffraction, wave solver, scattering solver, or edge-bending model is
  introduced. Existing ray/transmission occlusion must not be described as
  diffraction.
- The S3.3 magnitude FIR does not reproduce arbitrary measured phase. Non-null
  phase points fail explicitly; scalar delay represents the supported linear
  phase offset.
- Finite-window FFT delay and FIR filtering have documented edge transients;
  central-region acceptance does not erase those exported boundary effects.
- Detection-level source-premix RMS does not apportion mixture noise, AGC, or
  clipping among sources. Frame aggregate RMS and waveform export remain the
  authoritative effected mixture quantities.
- This design does not claim calibrated sim-to-real fidelity. S4 fit/holdout
  evidence and applicability limits are required for that narrower claim.

## 13. Entry, closeout, and verification status

Implementation may begin only from this frozen architecture and `S3.3`
protocol. Any change to an `S3.3` fixture, measurement method, or threshold
after acceptance evidence is generated invalidates that evidence and requires
a reviewed design revision plus a complete rerun. `S3.4`–`S3.6` may not begin
acceptance evidence until their deferred tolerances are frozen prospectively.

This change is documentation only. No implementation, unit, integration,
Isaac, GPU, or hardware verification was run or is claimed by this
specification.

## References

- `docs/final_sensor_development_plan.md`, §§6.2 and 6.6.
- `docs/development/specs/s0_squadbot_readiness_acceptance.md`, §S3.
- `docs/development/specs/s1_architecture_lock.md`.
- `docs/development/specs/s2_atomic_writers.md`.
- `src/isaac_audio_sensors/core/backends/room_acoustics.py`.
- `src/isaac_audio_sensors/core/backends/tdoa.py`.
- `src/isaac_audio_sensors/core/backends/geometry.py`.
- `src/isaac_audio_sensors/core/calibration_profile.py`.
- `src/isaac_audio_sensors/core/config.py`.
- `src/isaac_audio_sensors/core/constants.py`.
- `src/isaac_audio_sensors/core/fidelity.py`.
- `src/isaac_audio_sensors/core/plugins/declarations.py`.
- `src/isaac_audio_sensors/core/plugins/registry.py`.
