# S3 channel-effects chain

## Status and scope

| Field | Frozen value |
| --- | --- |
| State | `S3.3` frozen/implemented; `S3.4` design and acceptance protocol frozen prospectively; `S3.4` implementation and evidence do not yet exist |
| Design date | 2026-07-18 |
| Entry revision | `716336095f3436d824c76de4387374ff009022c3` |
| S3.4 protocol revision | `776ec423efd9e84fd798db465050b459ab75f1fb` |
| Governing gates | `S3.3` channel response, `S3.4` seeded noise, `S3.5` electronics, `S3.6` waveform directivity |
| Governing acceptance | `docs/development/specs/s0_squadbot_readiness_acceptance.md` §S3 |
| Evidence roots | `outputs/isaac_audio_sensors/S3/S3.3/` through `outputs/isaac_audio_sensors/S3/S3.6/` |

This specification freezes the common per-channel effects architecture and the
complete `S3.3` and `S3.4` acceptance protocols before their owning acceptance
evidence. It preserves the existing `ias.audio_sensor_frame.v1` fields and
meaning. Effects add optional configuration and diagnostics; they do not create
a new frame contract or a new propagation backend.

The numerical tolerances for `S3.5` and `S3.6` remain intentionally unset.
Their architecture placement is frozen by this document, and each owning
section carries the mandatory pre-evidence revision rule.

### Status revision history

Prior entries are retained; the later row amends only the named subphase.

| Date | Revision | Status entry |
| --- | --- | --- |
| 2026-07-18 | `716336095f3436d824c76de4387374ff009022c3` | Initial common architecture and complete prospective `S3.3` protocol frozen. |
| 2026-07-18 | `776ec423efd9e84fd798db465050b459ab75f1fb` | Complete prospective `S3.4` seeded-noise protocol, fixtures, tolerances, and verification map frozen; documentation only, with no `S3.4` evidence viewed or claimed. |

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
frame id, and immutable configuration. When S3.4 timing effects are active, the
backend additionally supplies the exact integer nominal window-start sample
defined in §7.2. It returns an array with the same shape and a stage-diagnostics
mapping. An enabled stage may allocate a new array; the all-disabled path has
the stronger identity rule in §2.4.

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

`S3.4` freezes the following additional immutable records and exact field
names. All optional fields default to `None`; the only non-`None` default is
`NoiseConfig.enabled=False`.

| Record | Fields and defaults |
| --- | --- |
| `NoiseSpectrumPointConfig` | `freq_hz=None`, `level_db=None` |
| `NoiseLevelSpecConfig` | `level_db=None`, `spectrum=None` |
| `SelfNoiseConfig` | `default=None`, `microphones=None` |
| `AmbientNoiseConfig` | `level_db=None`, `spectrum=None`, `coherent_fraction=None` |
| `NoiseConfig` | `enabled=False`, `seed=None`, `self_noise=None`, `ambient=None`, `clock_jitter_std_s=None`, `clock_drift_ppm=None` |

`SelfNoiseConfig.microphones` and `clock_drift_ppm` are mappings keyed by exact
`MicrophoneSpec.mic_id`. `clock_jitter_std_s` is either one scalar applied to
all microphones or a per-microphone mapping; mixed scalar/mapping forms are
invalid. A missing microphone in a timing mapping means zero jitter or drift.
`self_noise` resolves a microphone in this order: exact `microphones` entry,
`default`, then a flat-spectrum level from `MicrophoneSpec.self_noise_db`, then
no self-noise. This resolution runs only when `NoiseConfig.self_noise` is not
`None`; `None` disables self-noise without consulting microphone metadata. An
explicit `level_db=-inf` overrides every fallback with exact zero. A missing
`ambient.spectrum` or noise-level spectrum means white.

The `S3.5`/`S3.6` records continue to reserve only their architectural
containers: electronics has optional per-microphone quantization, saturation,
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

### 3.5 S3.4 TOML form and fail-closed validation

The normative TOML shape is:

```toml
[audio.effects.noise]
enabled = true
seed = 20260718
clock_jitter_std_s = { front = 0.000010, right = 0.000020 }
clock_drift_ppm = { front = 125.0, right = -80.0 }

[audio.effects.noise.self_noise.default]
level_db = -48.0
spectrum = [
  { freq_hz = 100.0, level_db = -18.0 },
  { freq_hz = 2000.0, level_db = 0.0 },
  { freq_hz = 20000.0, level_db = -12.0 },
]

[audio.effects.noise.self_noise.microphones.front]
level_db = -42.0

[audio.effects.noise.ambient]
level_db = -36.0
coherent_fraction = 0.25
spectrum = [
  { freq_hz = 100.0, level_db = -9.0 },
  { freq_hz = 1000.0, level_db = 0.0 },
  { freq_hz = 20000.0, level_db = -18.0 },
]
```

Static validation occurs before any random draw. A draw-dependent usable-region
check is then completed from the stateless named draw before samples are
changed or any frame, waveform, or diagnostic is emitted. The frozen ranges
are:

- `enabled` is an exact bool. Any nonzero stochastic setting requires `seed`
  to be an exact integer in `[-2**63, 2**63 - 1]`; bool is not an integer for
  this contract. Deterministic drift and explicitly zero-level settings need
  no seed.
- An absolute `level_db` is finite in `[-300.0, +60.0]` dBFS RMS, except that
  negative infinity is the sole accepted sentinel for exact zero. Positive
  infinity, NaN, strings, and all other non-finite values fail. Floating
  waveforms may exceed 0 dBFS before the deferred electronics stage, hence the
  intentional positive upper range.
- Every explicitly configured `NoiseLevelSpecConfig` and non-`None` ambient
  record requires a non-`None` `level_db`; a spectrum without an absolute
  level fails rather than guessing a level.
- A spectrum has at least two points. `freq_hz` values are finite, positive,
  strictly increasing, and no greater than Nyquist. Point `level_db` values
  are finite in `[-120.0, +120.0]`; NaN and either infinity fail. The designed
  FIR energy and every generated scale must also be finite and nonzero unless
  the absolute level is the exact-zero sentinel.
- `coherent_fraction` is finite in `[0.0, 1.0]`; `None` means `0.0`. It is a
  power fraction, not an amplitude weight.
- Every jitter standard deviation is finite in `[0.0, 0.25]` seconds. For the
  selected window, positive jitter additionally requires
  `ceil(6 * jitter_std_s * sample_rate_hz) < sample_count`; an actual seeded
  draw whose absolute shift leaves no sample-valid region also fails before
  processing. Thus a positive-jitter one-sample window is invalid rather than
  silently clamped.
- Every drift value is finite in `[-1000.0, +1000.0]` ppm. The implementation
  computes the accumulated integer and fractional sample offsets without an
  unbounded phase accumulator; if the required zero-extended source interval
  leaves no sample-valid region, validation fails rather than wrapping or
  resetting drift.
- Unknown microphone ids, duplicate ids after normalization, mapping order
  inconsistent with the selected array, an empty id, and a scalar/map type
  mismatch fail with `ConfigValidationError` naming the full table path and
  backend/profile envelope.
- On L0/L1, self-noise and ambient settings are waveform-only and raise
  `UnsupportedEffectError`. Only jitter and drift are adapted to additive
  delay metadata. The legacy TDOA stress knobs and derivation remain separate
  and unchanged.

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

## 7. S3.4 seeded noise — frozen design and tolerances

### 7.1 Absolute level and spectral-noise definitions

Waveforms use the existing normalized floating convention with full scale
equal to `1.0`. An absolute noise level `L` is **full-band dBFS RMS**:

```text
A(L) = 10 ** (L / 20)
L = 20 * log10(rms / 1.0)
A(-inf) = 0 exactly
```

It is not a per-bin or per-Hz level. A spectrum point's `level_db` is instead
a relative band-magnitude value. Adding the same constant to every spectrum
point does not alter absolute RMS because the designed filter is energy
normalized. This separation prevents bandwidth or FFT-size changes from
silently changing the configured noise level.

For a configured spectrum, construct the odd-length, Hann-windowed FIR `h0`
with the exact §6.1 `firwin2`-style design, interpolation, extrapolation, and
tap policy. Point amplitude is `10 ** (point.level_db / 20)`. Normalize it as:

```text
h = h0 / sqrt(sum_k(h0[k] ** 2))
```

For an `N`-sample output and `T=len(h)`, draw `N + T - 1` independent standard
normal values from the named stream and take the `N`-sample valid convolution:

```text
z = convolve(w, h, mode="valid")
n = A(L) * z
```

Guard draws, rather than zero padding, make every output sample stationary and
give even a one-sample window the declared population RMS. With no spectrum,
`h=[1.0]` is the exact white-noise definition. With `L=-inf`, the stage returns
an exact all-zero contribution and makes no generator draw.

Self-noise uses one `domain="noise", effect="self_noise"` stream for each
exact microphone id. Streams are independent across microphones. An explicit
effects level follows the resolution order in §3.1. When it falls back to
`MicrophoneSpec.self_noise_db`, that field has this same full-band dBFS RMS
meaning. Thus the existing L0/L1 metadata power term
`(10 ** (self_noise_db / 20)) ** 2` and an enabled L2 waveform realization
refer to the same population power. This is a unit/meaning agreement, not a
claim that waveform self-noise is representable on L0/L1. The all-disabled
path preserves the existing backend behavior: it does not newly synthesize L2
noise and does not change the legacy L0/L1 metadata floor.

Ambient noise has one shared spectrum and absolute level. For microphone `m`,
let `u_m` be its independently drawn, filtered, unit-population-RMS sequence
and let `u_c` be the common sequence. If `c=coherent_fraction`, then:

```text
ambient_m = A(L) * (sqrt(1 - c) * u_m + sqrt(c) * u_c)
```

The independent stream uses `effect="ambient"` and the exact microphone id.
The common stream uses `effect="ambient_common"` and the reserved component
`mic_id="__common__"`; this label is not a microphone-id normalization rule.
At `c=0`, no common draw is made. At `c=1`, no per-microphone ambient draw is
made and the pre-clock ambient contribution is byte-identical on every
microphone. The coefficient is a power fraction, so the expected total ambient
RMS remains `A(L)`. This optional common component is the only spatial
coherence model: there is no diffuse-field, spacing-dependent, direction-
dependent, or frequency-dependent inter-microphone coherence claim.

For each microphone, the additive contribution is exactly:

```text
additive_noise_m = self_noise_m + ambient_m
pre_clock_m = channel_response_mixture_m + additive_noise_m
```

Self-noise and ambient are added exactly once to the summed mixture. The room
backend must not call the noise dispatcher while iterating source premixes.
Changing source count while holding the already-summed input mixture fixed
therefore leaves the generated noise contribution byte-identical.

### 7.2 Clock jitter and drift

Noise-stage internal order is fixed as additive self/ambient noise, clock
drift, then clock jitter. Electronics follows the entire noise stage.

For each window and microphone, positive `clock_jitter_std_s=sigma_m` draws:

```text
J_m ~ Normal(0, sigma_m ** 2)
```

from `domain="noise", effect="clock_jitter"`. The draw is constant over that
microphone's window and is applied to `pre_clock_m` as a fractional delay using
the exact zero-padded rFFT phase-shift and crop in §6.1. Zero standard deviation
produces exact zero delay and makes no draw.

Clock drift is configured, not randomly drawn. For `p_m=clock_drift_ppm[m]`,
set `epsilon_m=p_m*1e-6`. The backend supplies the exact integer nominal sample
origin `q0=int(round(time_window.start_time_s*sample_rate_hz))` for the
half-open window, matching the existing scheduling/sample-count rounding path.
It is never derived from `frame_id`, wall clock, or mutable call count. At local
output sample `n`, the ideal accumulated delay in samples and source position
are:

```text
D_m(q0 + n) = (q0 + n) * epsilon_m / (1 + epsilon_m)
u_m[n] = n - D_m(q0 + n)
```

Positive ppm therefore means a faster microphone clock and an increasing
positive effective delay under the §6 sign convention. Evaluate the resampled
waveform by zero-extended first-order fractional interpolation:

```text
k = floor(u_m[n])
alpha = u_m[n] - k                 # always in [0, 1)
drifted_m[n] = (1-alpha)*x_m[k] + alpha*x_m[k+1]
```

Out-of-window `x_m` samples are zero. Implementations compute `D` as the shown
product/ratio, split it into an integer slip and bounded fractional phase, and
must not accumulate phase by repeated floating additions. This keeps the
fractional phase bounded over long sessions and makes any whole-sample slip
explicit. If the zero-extended window cannot retain a non-empty valid region,
the call fails closed; drift never wraps, saturates, or silently resets at a
frame boundary. `p_m=0` is an exact identity with no interpolation.

The L0/L1 adapter maps timing only. Its per-microphone additive effect offset at
the window midpoint `q_mid=q0+(N-1)/2` is:

```text
noise_timing_offset_s = J_m + D_m(q_mid) / sample_rate_hz
```

For L1 this is added after geometric propagation, unchanged legacy delay noise,
and configured S3.3 channel delay. If both legacy `clock_jitter_s` and S3.4
jitter are configured, both independent values add; the legacy draw and byte
derivation do not change. L0 may report the timing offset but does not alter its
geometry-derived bearing. Spectral self-noise and ambient remain unsupported
on both metadata-only backends.

### 7.3 Diagnostics, electronics, and DOA interaction

When the noise stage has an applicable configured contribution, its diagnostics
contain exactly the §4 keys:

- `streams` maps stable labels (`self_noise:<mic_id>`,
  `ambient:<mic_id>`, `ambient_common`, `clock_jitter:<mic_id>`, and
  deterministic `clock_drift:<mic_id>`) to records containing `effect`,
  `mic_id`, and `stochastic`. Stochastic records additionally contain the full
  canonical-key SHA-256 hex digest and derived unsigned 64-bit seed. Drift is
  labeled for configuration isolation but has `stochastic=false` and no
  derived seed.
- `per_mic_rms` is the float64 RMS of `additive_noise_m` before drift/jitter,
  keyed in selected microphone order. Timing offsets are not misreported as
  amplitude noise.
- `seed_derivation_id` is exactly `sha256-colon-v1-pcg64-le64` whenever a
  noise-stage diagnostic exists, including exact-zero/drift-only cases. It
  identifies the frozen policy even when no stochastic record required a draw.

An enabled exact-zero setting is observably different from a disabled stage:
its added contribution and `per_mic_rms` values are exact zeros and it emits a
noise diagnostic, but it performs no random draw. The all-disabled chain still
returns the exact input object and empty diagnostics under §2.4.

S3.5 remains deferred. Its future input is the single summed mixture after all
operations above; clipping, quantization, or AGC may change an S3.4 PSD/RMS and
therefore must be disabled in every S3.4 numerical fixture. S3.5 may not move
noise after electronics or distribute electronics/noise over source stems.

Waveform GCC/TDOA or SRP-PHAT output that claims to include noise degradation
must consume the final processed mixture after noise (and, later, electronics).
Detection-level known-source premix RMS and source-attribution diagnostics
remain signal-only and may not claim noise-aware confidence. S3.4 freezes input
consistency, not a scene-dependent DOA accuracy threshold; motion/multi-source
noise degradation is exercised in S3.8.

### 7.4 Frozen acceptance numbers

All non-statistical bounds are maxima. Statistical rows use exactly the sample
counts in §7.5; no retry, seed selection, result-dependent bin removal, or
threshold adjustment is permitted.

| Criterion | Frozen pass threshold | Brief basis |
| --- | --- | --- |
| Self-noise PSD recovery | Welch maximum absolute error `<= 2.0 dB` at every accepted bin from 200 Hz through 18 kHz, against the analytical one-sided PSD of the normalized FIR | 255 half-overlapped Hann segments put ordinary per-bin error far below 2 dB; the allowance covers the simultaneous maximum over thousands of correlated bins without accepting an unshaped spectrum |
| Full-band RMS level | `abs(20*log10(measured_rms/A(L))) <= 0.15 dB` for every nonzero self/ambient level and microphone at `N=2**20`; exact-zero cases are bytewise all-zero | The frozen record length makes Gaussian RMS uncertainty much smaller than 0.15 dB even after the 513-tap correlation, while retaining a finite statistical allowance |
| Ambient coherence | At `c in {0.0, 0.25}`, `abs(r-c) <= 0.02` for every microphone pair before clock effects; at `c=1.0`, contributions are byte-identical | The formula makes zero-lag correlation equal to the power fraction; `N=2**18` makes 0.02 a conservative finite-sample allowance |
| Jitter draw statistics | For each positive sigma, `abs(sample_mean) <= 0.01*sigma` and `abs(sample_std(ddof=1)/sigma - 1) <= 0.01` over exactly 100,000 frame draws | These are about 3.2 standard errors for the mean and 4.5 for the standard deviation, while rejecting materially biased/scaled draws |
| Jitter waveform delay | Maximum recovered delay error `<= 0.10 sample` for each of the first 256 configured frame draws | Reuses the S3.3 fractional-delay estimator bound on a fixed, prospectively selected draw corpus without tail filtering |
| Drift ramp slope | Maximum absolute recovered slope error `<= 0.50 ppm` for every nonzero configured drift | The deterministic linear phase ramp and long probe resolve sub-ppm slope; 0.50 ppm allows interpolation and lag-fit error without accepting a sign error or per-window reset |
| Seed replay and separation | Same seed/config/frame produces byte-identical float64 waveforms, diagnostics, and artifact hashes in two fresh instances; changing only seed changes at least one waveform byte and every active stochastic derived seed | Exact replay is the contract of named PCG64 streams; a probabilistic equality tolerance would hide state/call-order defects |
| Stream independence | For every pair of distinct latent stochastic streams, maximum `abs(Pearson r) <= 0.010` at `N=2**18`; intentional common-component reuse is excluded and tested by the coherence row | Independent normal-stream correlation has standard scale about `1/sqrt(N)=0.00195`; 0.010 allows a simultaneous pairwise matrix while exposing accidental stream reuse |
| Stream configuration isolation | Changing one mic/effect level, spectrum, coherence setting, or enabling another mic leaves every unrelated raw-draw byte string and derived seed byte-identical | SHA-256 domain/leaf/mic separation is primary evidence; the statistical correlation matrix is secondary evidence |
| Mixture-only insertion | With a fixed summed input and seed, noise delta is byte-identical for one-source and four-source premix decompositions and is added exactly once | Directly detects the source-count multiplication failure mode at the room-backend integration point |
| Metadata/waveform consistency | Recomputed final-mixture RMS differs from `aggregate_per_mic_rms` by at most `1e-12` absolute per mic; an enabled L2 self-noise realization also meets the `0.15 dB` population-level bound implied by its L0/L1 metadata convention | Both frame RMS and export consume the same float64 final mixture; the separate statistical level check covers metadata-vs-waveform meaning |
| Timing metadata adapter | L1 jitter offset equals the named draw within `1e-12 s`; drift midpoint offset equals `D(q_mid)/sample_rate_hz` within `1e-12 s`; legacy draws are byte-identical to baseline | Adapter arithmetic is directly observable and must not inherit waveform-estimator uncertainty |
| Pure/backend off-state | Pure chain returns the same input object and empty diagnostics; serialized backend frame and waveform hashes are byte-identical to revision `776ec42`; no `effects` key | Disabled S3.4 is the compatibility branch, not a statistical comparison |
| Registry determinism | The registry's exact two-factory/two-run test passes with the enabled four-mic seeded-noise fixture | Proves enabled stochastic effects remain a pure function of configuration and frame identity |

The structural seed guarantee is the primary independence proof: distinct
canonical keys produce distinct SHA-256-derived PCG64 seeds, and each call
constructs a fresh generator. Pearson correlation is a regression screen for
key reuse or wiring mistakes, not a proof of cryptographic independence. The
S0 row uses “stream” for all four effect paths; configured drift is a
deterministic, zero-random-variance transform, for which Pearson `r` is
undefined. Its distinct label, formula/slope check, and configuration-isolation
hash are therefore the frozen independence evidence in place of a fabricated
correlation statistic.

### 7.5 Frozen fixtures and measurement methods

Unless a row says otherwise, fixtures use float64, 48,000 Hz, microphone-major
arrays ordered `("front", "right", "rear", "left")`, primary seed `20260718`,
alternate seed `20260719`, frame id `s3_4_frame_000000`, and no other enabled
stage. Fixture arrays and all generated evidence record SHA-256 values.

| Fixture | Frozen protocol |
| --- | --- |
| Self-noise PSD | `N=2**20`; absolute level `-48 dBFS RMS`; points `[(100,-18), (500,-6), (2000,0), (8000,-3), (20000,-12)]`. Welch uses a periodic Hann window, `nperseg=8192`, `noverlap=4096`, per-segment constant detrending, density scaling by `sample_rate_hz*sum(window**2)`, doubling every positive non-Nyquist one-sided bin, and the arithmetic mean of exactly 255 periodograms. Compare measured dBFS-squared/Hz with `2*A(L)**2*abs(H(f))**2/sample_rate_hz` on every bin in 200 Hz–18 kHz; the normalized FIR has `sum(h**2)=1`. |
| RMS levels | `N=2**20`; self-noise and ambient are tested separately at `-60`, `-42`, and `-18 dBFS RMS`, with white and the self-noise PSD spectrum; all four microphones. The `-inf` case is a separate exact-zero assertion. |
| Ambient coherence | `N=2**18`; level `-36 dBFS RMS`; points `[(100,-9), (1000,0), (8000,-6), (20000,-18)]`; `c=0.0`, `0.25`, and `1.0`; Pearson correlation is computed after subtracting each sequence mean and before timing effects. |
| Jitter statistics | Exactly 100,000 frame ids `s3_4_jitter_000000` through `s3_4_jitter_099999`; per-mic sigmas `10`, `20`, `30`, and `40 microseconds` in array order; one draw per frame/mic; sample standard deviation uses `ddof=1`. |
| Jitter waveform | `N=16384` centered band-limited S3.3 delay probe; sigma `20 microseconds`; evaluate exactly frame ids `s3_4_jitter_waveform_000` through `s3_4_jitter_waveform_255` with no draw filtering; recover signed lag by the §6.3 full correlation and three-point parabolic interpolation. |
| Drift slope | `N=2**20` deterministic seed-fixed broadband probe; `q0=0`; ppm values `+125.0`, `-80.0`, `0.0`, `+37.5`; divide into 32,768-sample blocks with 16,384-sample hop, recover each block-center lag by cross-correlation/parabolic interpolation, and fit ordinary least-squares lag in samples versus nominal sample index. Report recovered ppm with the sign convention in §7.2. |
| Long-session drift arithmetic | For each drift value above, evaluate `D(q)` at `q=0`, one hour, one day, and 30 days of 48 kHz samples. Decompose into integer slip plus fractional phase; require fractional phase in `[0,1)`, reconstruction error `<=1e-6 sample`, monotonic magnitude for fixed nonzero sign, and typed fail-closed behavior if a waveform window lacks the required source interval. |
| Replay/isolation/correlation | `N=2**18` raw standard-normal draws for every self-noise, independent ambient, common ambient, and jitter canonical key using frame `s3_4_independence`; store raw little-endian float64 bytes. Drift is excluded from Pearson because it has no random draw, but its configuration-isolation hashes are mandatory. Repeat with one setting changed at a time. |
| Mixture/backend | Four deterministic source premixes whose sum equals a separately stored single-source mixture, plus a silent mixture; 48,000 samples; self-noise default `-48 dBFS RMS`, ambient `-36 dBFS RMS` with `c=0.25`, and jitter `20 microseconds`. Estimator-input, aggregate-RMS, and waveform-export hashes must all trace to the once-effected mixture. |
| L1 adapter | Current canonical single-source quad-array fixture at exact nominal window-start samples `q0=0` and `q0=4096`; legacy `noise_std_s`, `clock_jitter_s`, and `gain_mismatch_db` tested both all-zero and nonzero; subtract the matching baseline to isolate S3.4 jitter/drift while preserving legacy bytes. |
| Registry/off-state | Current canonical registry fixture with the primary four-mic noise configuration, plus the impulse, tone, broadband, silent, and room/plugin off-state corpus at revision `776ec42`. |

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

### 10.1 S3.4 verification map

Implementation adds focused pure tests in `tests/test_seeded_noise.py`, extends
config/chain cases in `tests/test_channel_effects_chain.py`, and extends backend
integration and registry cases in `tests/test_effects_backend_integration.py`
and `tests/test_backend_plugins.py`. Exact function names may follow repository
style, but every row is mandatory.

| Acceptance criterion | Proof type and key assertion | Required evidence below `outputs/isaac_audio_sensors/S3/S3.4/` |
| --- | --- | --- |
| Frozen config/defaults | dataclass-field and TOML round-trip tests; exact fields/defaults, immutable nested records, precedence, scalar/map forms | `noise_config_contract.json` |
| Fail-closed ranges | parameterized invalid-input unit tests; every §3.5 range/type/id/Nyquist/window failure occurs before draw/output | `invalid_noise_config_matrix.json`, `partial_output_listing.txt` |
| Self-noise PSD | pure Welch test with exact §7.5 protocol; every accepted bin within `2.0 dB` | `self_noise_welch.json`, `psd/self_noise_psd_overlay.png`, `psd/self_noise_psd_error.png` |
| RMS and exact zero | pure self/ambient tests; all nonzero cases within `0.15 dB`, `-inf` delta exact zero with diagnostics and no stream draw | `noise_rms_results.json`, `zero_level_noise.json` |
| Ambient coherence | pure latent/output tests; pairwise `r` follows `c` within `0.02`, `c=1` exact common bytes | `ambient_coherence.json`, `correlation_matrix.json`, `psd/ambient_psd_overlay.png` |
| Jitter statistics | named-draw test over exactly 100,000 frame ids; mean/std bounds per mic | `jitter_statistics.json`, `jitter_histogram.png` |
| Jitter waveform delay | delay-probe test; every included draw recovers within `0.10 sample` | `jitter_delay_recovery.json`, `jitter_delay_traces.npz` |
| Drift slope/long session | deterministic resampler unit tests; slope within `0.50 ppm`, bounded phase decomposition and typed unavailable-history failure | `drift_slope_results.json`, `drift_phase_long_session.json`, `drift_delay_fit.png` |
| Seed replay/separation | two fresh chain/backend instances; exact waveform/diagnostic hashes for same seed and differing bytes/seeds for alternate seed | `seed_replay_sha256.json`, `seeded_waveform_hashes.json` |
| Stream independence | raw latent-draw matrix; all unintended pairwise `abs(r)<=0.010`, canonical keys and derived seeds unique | `correlation_matrix.json`, `stream_key_manifest.json`, `stream_correlation_heatmap.png` |
| Configuration isolation | one-setting-at-a-time property test; unrelated raw-draw bytes and derived seeds unchanged | `stream_isolation_hashes.json` |
| Noise once on mixture | room-backend integration spy/hash test; equal summed input gives equal one-source/four-source noise delta and no per-premix noise dispatch | `mixture_once_trace.json`, `mixture_noise_delta_sha256.json` |
| Diagnostics contract | chain/backend test; exactly `streams`, `per_mic_rms`, and `seed_derivation_id` under noise, stable mic order and labels | `noise_diagnostics.json` |
| Waveform/RMS/DOA consistency | backend integration trace; aggregate RMS within `1e-12`, export and any noise-aware estimator consume the same final mixture | `metadata_waveform_consistency.json`, `estimator_input_trace.json`, `final_mixture_sha256.txt` |
| L0/L1 adapter | metadata integration test; jitter/drift offsets meet `1e-12 s`, waveform-only noise raises typed error, legacy hashes unchanged | `l0_l1_noise_adapter.json`, `legacy_tdoa_rng_sha256.json` |
| Pure/backend off-state | identity and golden regression; input object identity, empty diagnostics, exact revision-`776ec42` frame/waveform hashes | `off_state_chain_identity.json`, `off_state_golden_sha256.json`, `off_state_frame.json`, `off_state_waveform_sha256.txt` |
| Registry determinism | existing exact two-factory/two-run self-test with the enabled §7.5 primary fixture | `registry_determinism_noise.json` |
| Minimum-window/runtime failures | zero/one-sample, empty, non-finite, extreme timing and unavailable-history tests; exact supported behavior from §11 | `noise_edge_case_matrix.json` |

`seeded_noise_gate.json` is the mandatory machine-readable roll-up. It records
protocol revision `776ec42`, implementation revision, Python/NumPy/platform
versions, canonical stream keys and derived seeds, fixture/artifact SHA-256
values, exact sample counts and Welch parameters, every frozen threshold,
measured maxima/statistics, per-row status, and reproduction commands. It must
link rather than duplicate the complete `correlation_matrix.json` and PSD
artifacts. A failed statistical row is fixed and rerun with the unchanged
seeds, counts, bins, and thresholds; selective resampling is forbidden.

All S3.4 verification is pure CPU and simulator-runtime-independent testing.
No live Isaac, Omniverse, GPU, microphone, robot, or hardware scenario is
required: named stream determinism and the declared statistical transforms do
not depend on a live stage. Live moving-scene and multi-source noise coverage
arrives in S3.8 stress and cannot retroactively change this protocol. The
subphase closeout is `docs/development/closeouts/S3/s3_4_seeded_noise.md`.

## 11. Edge cases and failure behavior

The minimum invalid/boundary matrix includes empty and one-sample arrays,
non-finite samples, zero channels, microphone-count/order mismatch, unknown
microphone ids, non-finite gains/delays, invalid polarity, duplicate or
non-monotonic response points, response above Nyquist, non-`None` response
phase, delay larger than the usable window, silent input, signed zeros, and an
enabled waveform-only effect on each L0/L1 backend.

For S3.4 specifically, the matrix also includes absent and empty noise tables,
seed bool/out-of-range values, `-inf`/minimum/maximum absolute levels, NaN and
infinite absolute levels, invalid/NaN/infinite/non-monotonic spectrum points,
spectrum points above Nyquist, coherent fractions below zero and above one,
unknown or reordered mic maps, scalar/map jitter confusion, negative/NaN/
infinite/excessive jitter standard deviation, drift outside the ppm range, and
accumulated drift whose required source interval is unavailable.

An enabled `level_db=-inf` contribution produces exact zero samples, makes no
draw, and remains distinguishable from a disabled stage through its noise
diagnostic. An empty-time input remains empty and consumes no draw; the effects
package does not invent samples. One-sample self/ambient noise is supported by
the FIR guard-draw definition in §7.1. One-sample positive jitter fails the
six-sigma window bound, while exact-zero jitter and drift are identities.
Extreme seeded jitter that still exceeds the usable window after prospective
configuration validation fails before changing samples. Long-session drift
uses explicit integer-slip/bounded-fractional-phase arithmetic and fails if
zero extension cannot supply a non-empty valid region; it never wraps phase or
silently resets the session origin.

Supported empty-time behavior must follow the backend's existing minimum
window contract; the effects package does not invent samples. Invalid
configuration fails before simulation. Runtime array-shape/dtype failures fail
before any stage mutates caller-owned data. No failed call returns a partial
frame, writes a waveform, advances hidden RNG state, or emits a success
diagnostic.

## 12. Non-goals and limitations

- No diffuse-field spatial-coherence or inter-microphone noise-coherence claim
  beyond §7.1's optional fully common component is made. Named-stream
  independence is a determinism/statistical-isolation contract, not a
  room-noise field model.
- Noise `level_db` and `MicrophoneSpec.self_noise_db` are full-band dBFS RMS in
  this effects contract, not dB SPL, A-weighted self-noise, sensitivity, or a
  calibrated microphone data-sheet value. S4 calibration/evidence is required
  before making a physical self-noise claim.
- Clock drift is deterministic sample-rate mismatch with zero-extended finite
  windows and first-order interpolation. It is not a PLL, clock-recovery,
  oscillator phase-noise, Allan-deviation, or unlimited-history model.
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

Implementation may begin only from this frozen architecture and the owning
frozen protocol. Any change to an `S3.3` or `S3.4` fixture, measurement method,
sample count, seed, accepted bin, or threshold after acceptance evidence is
generated invalidates that subphase evidence and requires a reviewed design
revision plus a complete rerun. `S3.4` is frozen prospectively by the dated
`776ec42` status entry and may proceed to implementation; its acceptance
closeout path is
`docs/development/closeouts/S3/s3_4_seeded_noise.md`. `S3.5` and `S3.6` may not
begin acceptance evidence until their deferred tolerances are frozen
prospectively.

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
