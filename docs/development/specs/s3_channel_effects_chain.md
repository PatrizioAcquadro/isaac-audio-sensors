# S3 channel-effects chain

## Status and scope

| Field | Frozen value |
| --- | --- |
| State | `S3.3` and `S3.4` frozen/implemented/closed; `S3.5` and `S3.6` designs and acceptance protocols frozen prospectively; their implementation and evidence do not yet exist |
| Design date | 2026-07-18 |
| Entry revision | `716336095f3436d824c76de4387374ff009022c3` |
| S3.4 protocol revision | `776ec423efd9e84fd798db465050b459ab75f1fb` |
| S3.5 protocol revision | `451b98a` |
| S3.6 protocol revision | `31e0282` |
| Governing gates | `S3.3` channel response, `S3.4` seeded noise, `S3.5` electronics, `S3.6` waveform directivity |
| Governing acceptance | `docs/development/specs/s0_squadbot_readiness_acceptance.md` §S3 |
| Evidence roots | `outputs/isaac_audio_sensors/S3/S3.3/` through `outputs/isaac_audio_sensors/S3/S3.6/` |

This specification freezes the common per-channel effects architecture and the
complete `S3.3`, `S3.4`, `S3.5`, and `S3.6` acceptance protocols before their
owning acceptance evidence. It preserves the existing `ias.audio_sensor_frame.v1`
fields and meaning. Effects add optional configuration and diagnostics; they do
not create a new frame contract or a new propagation backend.

The dated `31e0282` revision freezes the complete `S3.6` pattern model,
configuration, fixtures, numerical tolerances, and verification map before any
`S3.6` acceptance evidence is generated or viewed.

### Status revision history

Prior entries are retained; the later row amends only the named subphase.

| Date | Revision | Status entry |
| --- | --- | --- |
| 2026-07-18 | `716336095f3436d824c76de4387374ff009022c3` | Initial common architecture and complete prospective `S3.3` protocol frozen. |
| 2026-07-18 | `776ec423efd9e84fd798db465050b459ab75f1fb` | Complete prospective `S3.4` seeded-noise protocol, fixtures, tolerances, and verification map frozen; documentation only, with no `S3.4` evidence viewed or claimed. |
| 2026-07-18 | `451b98a` | Complete prospective `S3.5` electronics model, fixtures, tolerances, and verification map frozen; documentation only, with no `S3.5` evidence generated or viewed. |
| 2026-07-18 | `31e0282` | Complete prospective `S3.6` waveform-directivity model, fixtures, tolerances, and verification map frozen; documentation only, with no `S3.6` evidence generated or viewed. |

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

`S3.5` completes the electronics records and ranges in §3.6. `S3.6` completes
the directivity records below; all optional fields default to `None`, mappings
are immutable copies, and only `DirectivityConfig.enabled` defaults to
`False`.

| Record | Fields and defaults |
| --- | --- |
| `DirectivityFrequencyPointConfig` | `freq_hz=None`, `gain_db=None` |
| `DirectivityPatternConfig` | `family=None`, `frequency_points=None` |
| `DirectivityPatternSetConfig` | `default=None`, `overrides=None` |
| `DirectivityConfig` | `enabled=False`, `source_patterns=None`, `mic_patterns=None`, `mode=None` |

`source_patterns.overrides` is keyed by exact `AudioSourceSpec.source_id` and
`mic_patterns.overrides` by exact `MicrophoneSpec.mic_id`. Each optional
`default` is a pattern, not a reserved entity id. Pattern resolution is exact
override, then the corresponding default, then frequency-flat `omni`.
`mode=None` resolves to `per_pair_direct_path`; that is the only Stage 1 mode.
The existing `AudioSourceSpec.directivity` field remains the L0/L1 amplitude
input and is not an implicit second fallback for this waveform configuration.
Shared-family consistency is verified explicitly in §9.5 rather than by
silently coupling the two configuration surfaces. `motion` is routed through
the same immutable configuration surface but is implemented and accepted by
`S3.1`/`S3.2`, not by this chain.

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

### 3.6 S3.5 electronics records, TOML form, and validation

`S3.5` replaces the reserved electronics payload with these exact immutable
records. Every optional value defaults to `None`; an absent table normalizes to
the shown disabled record.

| Record | Fields and defaults |
| --- | --- |
| `AgcConfig` | `enabled=False`, `target_rms_dbfs=None`, `attack_time_s=None`, `release_time_s=None`, `gain_floor_db=None`, `gain_ceiling_db=None` |
| `ElectronicsConfig` | `enabled=False`, `full_scale=None`, `bit_depth=None`, `dither_enabled=None`, `agc=None` |

`full_scale` is the positive float-domain clipping amplitude. `bit_depth`
controls the uniform quantization interval, and `dither_enabled=None` has the
same active-stage meaning as `False`. `agc=None` has the same active-stage
meaning as a disabled `AgcConfig`. Electronics settings are global to the
selected microphone array rather than per-microphone overrides; the same
transfer path is applied independently to each microphone in deterministic
array order.

The normative TOML form is:

```toml
# Section 5's existing stochastic root seed also keys electronics dither.
[audio.effects.noise]
seed = 20260718

[audio.effects.electronics]
enabled = true
full_scale = 1.0
bit_depth = 16
dither_enabled = true

[audio.effects.electronics.agc]
enabled = true
target_rms_dbfs = -12.041199826559248
attack_time_s = 0.010
release_time_s = 0.050
gain_floor_db = -12.041199826559248
gain_ceiling_db = 12.041199826559248
```

No second stochastic-root field is added. When dither is active, the `seed`
in the §5 canonical key is exactly `EffectsConfig.noise.seed`, even when the
noise stage itself is disabled. This retains one already-frozen seed range and
uses the `electronics` domain to isolate the draw from every S3.4 stream.

All supplied fields are validated before a draw or sample operation, including
fields under an explicitly disabled electronics stage. The frozen rules are:

- For every numeric rule below, bool is rejected rather than treated as an
  integer or real number.
- `ElectronicsConfig.enabled` and `AgcConfig.enabled` are exact bools.
  Non-`None` `dither_enabled` is also an exact bool; integers are not bools.
- Active electronics requires `full_scale` and `bit_depth`. `full_scale` is a
  finite real number strictly greater than zero. `bit_depth` is an exact
  integer in `[8, 32]`; bool is rejected.
- The derived `Delta=2*full_scale/2**bit_depth` must be finite and strictly
  positive. For enabled AGC, the derived target, linear gain bounds, and both
  per-sample coefficients must likewise be finite and strictly positive (with
  each coefficient also strictly less than one). Overflow or underflow fails
  before processing.
- Active dither requires `EffectsConfig.noise.seed` to be an exact integer in
  `[-2**63, 2**63 - 1]`. Dither-disabled electronics needs no seed.
- An enabled AGC requires every other `AgcConfig` field. `target_rms_dbfs` is
  finite in `[-120.0, 0.0]` dBFS. `attack_time_s` and `release_time_s` are
  finite in `(0.0, 60.0]` seconds. Both gain bounds are finite in
  `[-120.0, +120.0]` dB, with
  `gain_floor_db <= 0.0 <= gain_ceiling_db` and
  `gain_floor_db <= gain_ceiling_db`.
- Any optional electronics or AGC value supplied while its owning substage is
  disabled still must meet its type/range rule. Explicitly disabling the stage
  controls application; it does not turn malformed configuration into valid
  configuration.
- Active electronics on `geometry_only` (L0) or `tdoa_synthetic` (L1), under
  either runtime profile, raises `UnsupportedEffectError` before a detection,
  frame, diagnostic, waveform, or other asset is partially emitted. No
  clipping flag, scalar RMS adjustment, or other metadata approximation is
  permitted.

Validation errors name the complete `audio.effects.electronics` field path,
offending value, and backend/profile envelope. Runtime non-finite arrays use
the chain-level fail-closed rule in §11.

### 3.7 S3.6 directivity TOML form and validation

The normative TOML shape is:

```toml
[audio.effects.directivity]
enabled = true
mode = "per_pair_direct_path"

[audio.effects.directivity.source_patterns.default]
family = "omni"

[audio.effects.directivity.source_patterns.overrides.talker]
family = "cardioid"
frequency_points = [
  { freq_hz = 100.0, gain_db = -3.0 },
  { freq_hz = 1000.0, gain_db = 0.0 },
  { freq_hz = 20000.0, gain_db = -6.0 },
]

[audio.effects.directivity.mic_patterns.default]
family = "supercardioid"

[audio.effects.directivity.mic_patterns.overrides.rear]
family = "figure_eight"
```

All supplied fields are validated before `_scheduled_window_signal`, room
construction, a random draw, or any output write, including values beneath a
disabled directivity stage. The frozen rules are:

- `enabled` is an exact bool. `mode`, when non-`None`, is exactly
  `"per_pair_direct_path"`; every other value raises
  `UnsupportedEffectError`.
- `family` is required for every supplied pattern and is one of the exact,
  case-sensitive strings `omni`, `cardioid`, `figure_eight`, or
  `supercardioid`. Unknown families and missing family values raise
  `ConfigValidationError`; there is no alias, case folding, or silent omni
  fallback for a supplied record.
- `overrides` is an immutable mapping in selected scene/array order. Empty,
  duplicate-after-normalization, reordered, or unknown ids fail. Source ids
  are validated against the complete selected `AudioSceneSnapshot.sources`,
  not only the sources active in the current window, and microphone ids are
  validated against the selected array.
- A non-omni resolved pattern requires a non-`None` orientation. Source
  patterns use `AudioSourceSpec.orientation_world_quat`; microphone patterns
  use the composed array-world and microphone-relative orientation defined in
  §9.1. A missing orientation fails before synthesis rather than converting
  the pattern to omni. Omni does not require an orientation.
- `frequency_points` is absent for a frequency-flat pattern. When supplied it
  reuses the §3.3/§6.1 magnitude-response validation: at least two points;
  finite, positive, strictly increasing `freq_hz`; finite `gain_db`; and the
  highest point no greater than Nyquist. Values below the first and above the
  last point use the same flat extrapolation as §6.1. There is no phase field.
- An enabled configuration must supply at least one source or microphone
  pattern set. Resolving every active pair to frequency-flat omni is a
  deliberate no-op governed by §9.5, not an unsupported configuration.
- Active directivity is waveform-only. It is supported only by
  `room_acoustics` and `room_acoustics_srp` under `waveform_fidelity`; L0/L1,
  `training_features`, and every other backend/profile combination raise
  `UnsupportedEffectError` before partial synthesis.

Every validation error names the complete `audio.effects.directivity` field
path, offending value or id, selected backend/profile, and supported envelope.

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

## 8. S3.5 electronics — frozen design and tolerances

### 8.1 Operation definitions and order

The statement in frozen §7.3 that S3.5 “remains deferred” records the status at
the S3.4 protocol revision. This dated §8 supersedes only that status; §7's
frozen input boundary and prohibition on moving/distributing stages remain
binding.

`electronics.py` runs after the complete response and noise stages. Its
internal order is fixed and may not be reordered by a backend or profile:

```text
summed mixture -> AGC (when enabled) -> hard saturation -> quantization
```

Electronics processes the summed mixture exactly once. AGC, clipping, and
quantization are not distributive over source stems, so no electronics
dispatcher may run in the per-source premix loop. The processed mixture is the
one consumed by aggregate RMS, waveform export, and any estimator that claims
electronics-aware input. Known-source premix diagnostics remain signal-only as
defined in §2.2.

For microphone `m`, the AGC detector is the float64 RMS of the complete input
window presented to the electronics stage, before any electronics operation:

```text
R_m = sqrt((1/N) * sum_{n=0}^{N-1} x_m[n]**2)
T   = full_scale * 10**(target_rms_dbfs / 20)
g_floor = 10**(gain_floor_db / 20)
g_ceiling = 10**(gain_ceiling_db / 20)
```

The implementation evaluates the mathematically equivalent RMS with scaled
norm arithmetic so a finite high-amplitude input does not overflow while
squaring. A non-finite derived detector fails before output is changed.

For `R_m > 0`, the feed-forward asymptotic gain is
`g_star_m=clip(T/R_m, g_floor, g_ceiling)`. For exact silence (`R_m==0`), the
policy is **release toward unity**: `g_star_m=1.0`. Configuration guarantees
that unity lies within the gain bounds. The detector and gain state are local
to one call; there is no cross-frame mutable AGC state, and every call starts
from exact unity `g_m[-1]=1.0`. This makes replay independent of prior call
order.

At each sample, attenuation uses the attack coefficient and increasing gain
uses the release coefficient:

```text
alpha_attack  = exp(-1 / (attack_time_s  * sample_rate_hz))
alpha_release = exp(-1 / (release_time_s * sample_rate_hz))
alpha_m[n] = alpha_attack  if g_star_m < g_m[n-1]
             alpha_release if g_star_m > g_m[n-1]
             0.0           otherwise
g_m[n] = g_star_m + alpha_m[n] * (g_m[n-1] - g_star_m)
a_m[n] = g_m[n] * x_m[n]
```

For a constant target and direction, the exact analytical reference after
sample `n` is:

```text
g_m[n] = g_star_m + (g_m[-1] - g_star_m) * alpha**(n + 1)
```

AGC-disabled electronics defines `g_m[n]=1.0` exactly for every sample and
does not evaluate the RMS detector. An enabled AGC on an empty-time array is
invalid because its per-window detector is undefined; electronics with AGC
disabled supports the empty array behavior in §11. A one-sample window uses
`R_m=abs(x_m[0])` and exactly one recurrence update.

Saturation is the float-domain hard clip:

```text
s_m[n] = min(max(a_m[n], -full_scale), full_scale)
clipped_m[n] = abs(a_m[n]) > full_scale
```

Equality at either full-scale boundary is not clipping. No soft knee,
waveshaping curve, hysteresis, or recovery state is included.

For `B=bit_depth`, the mid-tread quantization step is exactly:

```text
Delta = 2 * full_scale / 2**B
```

With dither disabled, `d_m[n]=0`. With dither enabled, construct a fresh §5
named generator for each microphone using `domain="electronics"` and
`effect="tpdf_dither"`. Draw exactly `2*N` `Generator.random` float64 values in
one call, split the first and second `N` values into `u_m` and `v_m`, and set:

```text
d_m[n] = (Delta / 2) * (u_m[n] - v_m[n])
```

This is triangular PDF dither with support `(-Delta/2, +Delta/2)`, hence one
LSB peak-to-peak. A zero-length array makes no draw. Quantization uses IEEE/NumPy
round-to-nearest, ties-to-even (`rint`) and reconstructs in the float domain:

```text
q_m[n] = clip(Delta * rint((s_m[n] + d_m[n]) / Delta),
                  -full_scale, full_scale)
```

Thus zero and both full-scale endpoints are representable. `bit_depth`
specifies `2**B` equal intervals over `[-full_scale, full_scale]`; this model is
not a packed signed-PCM storage codec. With dither disabled, every in-range
reconstruction value `k*Delta` is idempotent under repeated quantization.

### 8.2 Frozen diagnostics contract

When electronics is enabled, its stage diagnostic contains exactly the four
§4 keys:

- `clipping_count_per_mic` maps microphone ids in selected array order to the
  exact integer count of `clipped_m[n]`.
- `saturated_sample_ratio` is
  `sum_m(clipping_count_per_mic[m])/(microphone_count*N)`. It is `0.0` for an
  AGC-disabled empty-time array.
- `agc_gain_trace_summary` maps each microphone id to exactly
  `initial_gain`, `final_gain`, `minimum_gain`, `maximum_gain`, and
  `detector_rms`. Gains are linear float64 values. `initial_gain` is always
  `1.0`; for an empty or AGC-disabled trace all four gain values are `1.0`, and
  `detector_rms` is `null` when AGC is disabled.
- `quantization_step` is the scalar float64 `Delta` shared by the array.

The full microphone-major gain trace is retained only as an evidence artifact.
Counts describe samples changed by hard saturation, not samples merely at the
boundary, rounded to a different quantization level, or clipped only after a
dither excursion inside the quantizer reconstruction rule.

### 8.3 Frozen acceptance numbers

All deterministic bounds are maxima. Statistical rows use exactly the seeds,
sample counts, and signals in §8.4; no retry, seed selection, selective sample
removal, or result-dependent threshold change is permitted. The frozen
quantization-error whitening assertion is the error-versus-signal correlation
measurement below; S3.5 makes no additional PSD-flatness claim.

| Criterion | Frozen pass threshold | Brief basis |
| --- | --- | --- |
| Boundary clipping counts | For the exact boundary fixture, `clipping_count_per_mic == {"front": 0, "right": 0, "rear": 16, "left": 8}` | The comparison is strictly `abs(a)>full_scale`; all 16 rear samples and exactly half the left samples exceed the boundary, while equality and one-LSB-below samples do not |
| Saturated-sample ratio | Exact `24/64 == 0.375`, with no tolerance | The ratio is derived from the same integer mask over four microphones and 16 samples; any other numerator or denominator is a diagnostic defect |
| Quantization-noise power | `0.9 <= mean((q-x)**2)/(Delta**2/12) <= 1.1` at `N=2**18`, dither disabled | The deterministic full-range ramp samples the half-to-even quantization phase densely; the 10% band covers endpoint/tie discretization while rejecting an incorrect step, rounding rule, or grossly nonuniform error |
| Dither whitening/decorrelation | For every microphone, `abs(Pearson r(x, q-x)) <= 0.010` at `N=2**18` | Independent TPDF draws should leave correlation at the finite-record scale `1/sqrt(N)=0.00195`; 0.010 is a simultaneous regression allowance and detects signal-locked error or reused/missing dither |
| AGC analytical trace | Maximum `abs(observed_gain-reference_gain) <= 1e-12` over every sample of the frozen attack/release fixture | The recurrence has a closed-form float64 reference; this tolerance permits evaluation-order roundoff but not a different coefficient, initial state, or direction rule |
| AGC attack settling | At or before exactly `8*attack_time_s`, gain is within `0.01 dB` of `g_star` and remains within that bound | First-order residual is `exp(-8)`; for the frozen 1-to-0.5 step the analytical gain error is below `0.003 dB`, leaving numerical margin |
| AGC release settling | At or before exactly `8*release_time_s`, gain is within `0.01 dB` of `g_star` and remains within that bound | The same `exp(-8)` basis applies to the frozen 1-to-2 increasing-gain step and rejects use of the attack coefficient in the release direction |
| AGC unity and bounds | Disabled AGC trace is elementwise and bytewise float64 `1.0`; enabled traces satisfy `g_floor <= g_m[n] <= g_ceiling` for every sample with exact comparisons | Unity is an explicit bypass, and the bounded target plus convex first-order update cannot legitimately overshoot either configured bound |
| Diagnostics | Exactly the §8.2 keys, values, integer counts, scalar ratio, ordered microphones, and summary schema; `quantization_step == Delta` in the power-of-two fixture | Diagnostics are a protocol, not approximate telemetry |
| Mixture-only insertion | Equal summed input and seed produce byte-identical electronics output and diagnostics for one-source and four-source decompositions; exactly one mixture dispatch and zero premix electronics dispatches | Directly detects source-count-dependent AGC, clipping, quantization, or dither |
| Pure/backend off-state | Pure chain returns the same array object and empty diagnostics; backend frame and waveform are byte-identical to revision `451b98a`, with no `effects` key | Disabled electronics is the compatibility branch and performs no floating-point operation |
| L0/L1 rejection | Every enabled-electronics fixture raises `UnsupportedEffectError` before partial frame or asset creation | Electronics has no honest metadata representation on waveform-free backends |
| Seed replay and registry determinism | Two fresh same-seed instances produce byte-identical float64 output, diagnostics, gain traces, and dither artifacts; an alternate seed changes every dither derived seed and at least one output byte; the registry two-factory/two-run self-test passes with the enabled primary fixture | Named streams make dither a pure function of configuration, frame identity, and microphone id without weakening the deterministic backend declaration |

### 8.4 Frozen fixtures and measurement methods

Unless a row says otherwise, fixtures use float64, 48,000 Hz, microphone-major
arrays ordered `("front", "right", "rear", "left")`, `full_scale=1.0`,
`bit_depth=16`, primary seed `20260718`, alternate seed `20260719`, frame id
`s3_5_frame_000000`, and no response, noise contribution, directivity, or
motion. The seed is carried by the disabled `NoiseConfig` as frozen in §3.6.
Every fixture array and retained artifact records a SHA-256 value.

| Fixture | Frozen protocol |
| --- | --- |
| Boundary clipping and ratio | `N=16`, `Delta=1/32768`, AGC/dither disabled. `front[n]=(-1)**n*1.0`; `right[n]=(-1)**n*(1.0-Delta)`; `rear[n]=(-1)**n*1.5`; `left` repeats `(1.0, -1.0, 1.5, -1.5)` four times. Expected counts are `(0,0,16,8)` in array order and the exact aggregate ratio is `24/(4*16)=0.375`. |
| Quantization-noise ramp | One microphone, `N=2**18`, dither/AGC disabled, and `x[n]=-full_scale+Delta/2+(2*full_scale-Delta)*n/(N-1)`. No sample exceeds full scale. Measure uncentered error power `mean((q-x)**2)` against `Delta**2/12`. |
| TPDF decorrelation | Four identical channels, `N=2**18`, `x[n]=0.75*sin(2*pi*5445*n/N)` (exact frequency `5445*48000/N Hz`), dither enabled, AGC disabled, and frame id `s3_5_dither_000000`. Compute Pearson `r` after subtracting each signal/error mean, where error is `q-x`; record the raw dither/error little-endian float64 hashes and named-stream descriptors. |
| AGC attack/release and bounds | `N=24000`; target `-12.041199826559248 dBFS` (`T=0.25`), attack `0.010 s`, release `0.050 s`, floor `-12.041199826559248 dB` (`0.25`), ceiling `+12.041199826559248 dB` (`4.0`), dither disabled. Constant channels are `front=0.5` (`g_star=0.5`, attack), `right=0.125` (`g_star=2.0`, release), `rear=1.0` (`g_star=0.25`, floor), and `left=0.03125` (`g_star=4.0`, ceiling). Compare every sample with the §8.1 analytical trace; evaluate settling after exactly 3,840 attack updates and 19,200 release updates. |
| AGC disabled/silence/single sample | On the AGC fixture with `agc=None`, retain the exact all-ones gain trace. With AGC enabled, a 24,000-sample all-zero array has exact-zero output and an exact-unity trace under the silent release policy. For each AGC channel above, a separate `N=1` input must match the first analytical update exactly within the `1e-12` trace bound. |
| Gain-bound stress | Reuse the `rear` and `left` AGC channels above; assert every trace element lies in `[0.25,4.0]` by exact comparison, the asymptotic targets equal the respective bounds, and the recurrence is monotone with no overshoot. |
| Idempotence and full-scale signs | Dither/AGC disabled. Quantize every `k*Delta` for integer `k` in `[-32768,32768]` in deterministic chunks and require the second quantization bytes to equal the first. A separate alternating `(-1.0,+1.0)` 4096-sample channel has zero clipping count and preserves both endpoints exactly. |
| Mixture/backend and primary registry | `N=48000`; channel frequencies `(997,1499,2203,3301) Hz`; `x_m[n]=0.9*sin(2*pi*f_m*n/48000)+0.6*sin(2*pi*(f_m+211)*n/48000)`. Store one source premix equal to `x`. The four-source decomposition partitions samples without arithmetic overlap: source `j` contains `x[:,n]` only when `n % 4 == j` and exact zero otherwise. Its sum is therefore byte-identical to `x` before dispatch. Enable the AGC settings above and TPDF dither. Aggregate RMS, estimator-input trace when applicable, waveform export, diagnostics, same/alternate-seed replay, and the registry two-run self-test all use this primary fixture. |
| L0/L1 and off-state | Apply the active primary electronics configuration separately to the canonical L0 and L1 fixtures and require typed rejection with an empty partial-output listing. For off-state, use the impulse, tone, broadband, silent, room/backend, waveform-export, and registry golden corpus pinned at revision `451b98a`. |

## 9. S3.6 waveform directivity — frozen design and tolerances

### 9.1 Polar families, axes, and angle convention

For every source/microphone pair, each polar response is the signed first-order
pattern

```text
g(theta) = a + (1 - a) * cos(theta)
```

with these exact family constants and analytical cardinal targets:

| Family | Frozen `a` | `g(0°)` | `g(90°)` | `g(180°)` | `g(270°)` |
| --- | ---: | ---: | ---: | ---: | ---: |
| `omni` | `1.0` | `1.0` | `1.0` | `1.0` | `1.0` |
| `cardioid` | `0.5` | `1.0` | `0.5` | `0.0` | `0.5` |
| `figure_eight` | `0.0` | `1.0` | `0.0` | `-1.0` | `0.0` |
| `supercardioid` | `0.37` | `1.0` | `0.37` | `-0.26` | `0.37` |

The pattern axis is local `+X`. Quaternions use the public `(x,y,z,w)` order.
For a source, rotate `(1,0,0)` by the normalized
`AudioSourceSpec.orientation_world_quat`; `theta_s` is the angle between that
axis and the normalized direct-path direction from source to microphone. This
is the existing `core/backends/amplitude.py::directivity_factor` convention:
that helper normalizes the quaternion, rotates local `+X`, uses `to_mic =
mic_position_world - source.position_world`, clamps the cosine to `[-1,1]`,
and evaluates the `a=0.5` cardioid.

For a microphone, first compose and normalize
`q_mic_world = q_array_world * q_mic_relative`, using the repository's
Hamilton product and treating a missing relative orientation as identity.
Rotate local `(1,0,0)` by `q_mic_world`; `theta_m` is the angle between that
axis and the normalized direct-path incidence direction from microphone to
source. `AudioSourceSpec`, `MicrophoneSpec`, and `MicrophoneArraySpec` already
pass nonzero finite quaternions through `as_quaternion_xyzw`, which normalizes
them. Consequently an unnormalized but finite nonzero input is accepted and
stored normalized, while a zero or non-finite quaternion fails at frame/type
construction before pattern evaluation.

If source and microphone occupy the same world position, the direction is
undefined. S3.6 reuses `directivity_factor`'s zero-distance policy: the polar
factor for each side is exactly `1.0`; configured frequency response still
applies. No arbitrary angle, NaN, or division by zero is produced.

The signed polar value is applied as-is. A cardioid rear null therefore has
exact target zero, while the rear of a figure-eight and supercardioid pattern
reverses waveform polarity. Absolute value, squaring, or clamping negative
lobes to zero is forbidden. With source and microphone patterns active, their
signed values multiply, so two negative lobes restore positive polarity.

### 9.2 Frequency dependence and pair response

Absent `frequency_points` means an exactly frequency-flat response of unity.
Configured points use `gain_db` as relative amplitude dB and the exact §6.1
NumPy-only Type-I linear-phase FIR design, interpolation, flat extrapolation,
tap policy, group-delay compensation, zero-padded linear convolution, crop,
and common edge exclusion. Point amplitude is
`10 ** (gain_db / 20)`. No directivity phase response beyond the signed polar
polarity and the FIR's compensated linear phase is modeled.

Recovery excludes the sum of the active FIR half-supports at each edge:
`sum_i((T_i-1)/2)`, where `T_i` is the §6.1 tap count for each configured
source/microphone response. At 48 kHz this is 256 samples for one 513-tap
response and 512 samples for two; the exported window retains those finite-
support edge transients.

For the contribution from source `s` to microphone `m`, let `x_sm` be the
frequency-flat, nondirectional pair contribution, `F_s` and `F_m` the resolved
source and microphone FIRs (identity when absent), and `p_s`, `p_m` their
signed polar values. The result is exactly:

```text
y_sm = p_s * p_m * F_m(F_s(x_sm))
mixture_m = sum_s(y_sm)
```

Source directivity is thus semantically applied to the source signal separately
for the same source at every microphone, and microphone directivity separately
for every incident source. The responses combine multiplicatively and are
applied before source mixing; there is no post-mix directivity dispatcher. The
room backend realizes this per-pair semantic at the equivalent premix location
frozen in §9.3.

### 9.3 Honest room-backend insertion model

The frozen diagnostic mode is exactly `per_pair_direct_path`. In the current
room backend, `_scheduled_window_signal` creates one signal per source and
pyroomacoustics convolves it with every source/microphone RIR before returning
`premix[source_index, mic_index, sample]`. A microphone-specific pattern cannot
be placed on that one shared source signal without duplicating the room
simulation. The Stage 1 implementation therefore evaluates the direct-path
angle for each pair and applies its signed scalar/FIR response to that pair's
complete returned premix stem, after `_simulate_premix` and before `np.sum`.
For piecewise room synthesis, it applies to each `segment_premix` before
overlap-add so a segment's direct-path geometry is not replaced by the last
segment's geometry.

This model is named **per-pair direct-path-angle weighting of the full
convolved contribution**. For an LTI scalar/FIR it is algebraically equivalent
to a separate per-pair pre-RIR filter, but it weights the direct arrival and
every image-source reflection in that pair by the same response selected from
the direct-path angle. It is not direct-arrival-only filtering and does not
resolve reflection departure or incidence angles. Applying the response to
the summed mixture, using an array-center angle for every microphone, or
claiming path-resolved reflected directivity violates this protocol.

Pyroomacoustics-native directional sources/microphones and separately angled
image paths are out of scope for Stage 1 and deferred to P2. They are not a
fallback mode: an unavailable or requested mode other than
`per_pair_direct_path` fails before synthesis.

### 9.4 Diagnostics and fidelity reconciliation

When at least one resolved active pattern is non-omni or has frequency points,
the directivity stage diagnostic contains exactly the §4 keys:

- `source_pattern` maps active source ids in scene order to the resolved
  `family` and exact configured `frequency_points` (or `null`);
- `mic_pattern` maps selected microphone ids in array order to the same
  resolved record shape; and
- `mode` is exactly `"per_pair_direct_path"`.

An enabled configuration resolving every active pair to frequency-flat omni is
the explicit no-op in §9.5: it emits no directivity stage mapping so the
complete frame remains entry-behavior byte-identical. No diagnostic may imply
reflection-specific angles.

At revision `31e0282`, `core/fidelity.py` still says L2 source directivity is
metadata-only and places richer directivity in future L3 wording. This
documentation-only revision does not edit that file. The S3.6 closeout must
record the discrepancy, and S3.9 must reconcile the public fidelity ladder and
claim/evidence map with the actual passing S3.6 envelope. Until that
reconciliation, S3.6 evidence supports only this specification's narrow L2
mode and must not be quoted as the broader fidelity metadata claim.

### 9.5 Frozen acceptance numbers

All deterministic bounds are maxima. Statistical estimator rows use exactly
the seeds and counts in §9.6; there is no retry, seed selection, rung removal,
or result-dependent threshold adjustment.

| Criterion | Frozen pass threshold | Brief basis |
| --- | --- | --- |
| Polar evaluator | Maximum absolute scalar error `<= 1e-12` for every family and cardinal angle against the §9.1 table | The evaluator is a closed-form float64 dot/cosine expression; the allowance covers cardinal quaternion roundoff but not a wrong family constant or direction convention |
| Cardinal waveform gain | For every nonzero target, signed least-squares gain has the exact target sign and magnitude error `<= 0.05 dB`; for a zero target, `abs(g_hat) <= 1e-6` and `rms(y)/rms(baseline) <= 1e-6` | Reuses §6's scalar-gain bound; the linear null form avoids an undefined `-inf dB` comparison and rejects residuals above `-120 dB` amplitude |
| Frequency-sweep recovery | Maximum Welch H1 magnitude error `<= 0.25 dB` on every accepted bin for one frequency-dependent pattern and `<= 0.50 dB` when both source and microphone FIRs are active; signed polarity at 1 kHz must also match exactly | One response reuses the §6 FIR bound; two cascaded independently bounded FIR approximations receive the additive dB bound without hiding either individual result |
| Full-contribution room weighting | In the reverberant fixture, each frequency-flat effected pair stem is byte-equivalent to the baseline full convolved stem multiplied once by the analytical signed polar product; frequency-dependent stems meet the corresponding Welch bound, and direct plus RIR-tail samples both change | Detects direct-only edits, post-mix application, source-count multiplication, and false reflection-angle behavior |
| L0/L1-to-L2 shared-family consistency | For source-only frequency-flat `omni` and `cardioid`, L2 signed gain and `amplitude.py::directivity_factor` agree within `0.05 dB` at nonzero cardinal targets and within `1e-6` linear amplitude at the cardioid rear null | Uses the same source `+X`, quaternion normalization, direct-path direction, and first-order cardioid convention across metadata and waveform paths |
| Estimator degradation | Across the `0°,90°,120°,180°` cardioid ladder, the known-component SNR proxy is strictly decreasing, drops at least `5.5 dB` on each of the first two steps and at least `40 dB` front-to-rear; the eight-seed median SRP confidence and median GCC peak proxy are strictly decreasing at every step, with front-to-rear absolute drops `>=0.10` and `>=0.05`, respectively | Cardioid amplitude halves from `1` to `0.5` to `0.25` before its rear null, giving about `6.02 dB` SNR loss per finite step; fixed additive noise converts reduced directional level into lower PHAT coherence/prominence without freezing scene-specific exact values |
| Invalid/unsupported patterns | Every unknown family/id, invalid point list/Nyquist value, missing required orientation, and unsupported mode/backend/profile raises the located typed error before `_scheduled_window_signal`, room construction, draw, frame, waveform, or evidence asset | Fail-closed validation is a pre-synthesis contract, not cleanup after a partial result |
| Disabled and explicit-omni compatibility | Disabled directivity and enabled frequency-flat omni-only configuration produce entry-revision-identical premix, mixture, detection, aggregate RMS, waveform, diagnostics, serialized frame, and artifact hashes; no `effects` key is added | Unity directionality is semantically the prior backend and the omitted no-op diagnostic preserves full byte identity |
| Determinism and registry | Two fresh enabled instances produce byte-identical float64 premixes, mixtures, diagnostics, frames, and artifacts; the existing two-factory/two-run registry self-test passes with the primary directivity fixture | Directivity has no RNG or mutable state and must preserve the backend's deterministic declaration |

For waveform gain, `baseline` is the matching directivity-disabled pair stem
and `g_hat=sum(baseline*y)/sum(baseline**2)` after the §6 common edge
exclusion. A nonzero sign passes only when `sign(g_hat)` equals the analytical
sign; magnitude-only RMS cannot prove figure-eight polarity.

The GCC peak proxy is the median absolute `GccPhatDelay.peak_value` over the six
unordered microphone pairs and then the median over the eight fixed noise
seeds. SRP confidence is exactly `srp_phat_confidence`, namely clamped
`(peak_power-mean_power)/peak_power`. These metrics preserve the current
estimator semantics; S3.6 does not invent a new runtime GCC confidence field.
The ladder feeds the estimators retained directivity-weighted signal plus fixed
noise components as a pure acceptance fixture. It does not relabel the current
scheduled-known-source premix confidence as mixture-noise-aware; any runtime
confidence claim must still obey §2.2, and moving/multi-source behavior remains
S3.8 coverage.

### 9.6 Frozen fixtures and measurement methods

Unless stated otherwise, fixtures use float64, 48,000 Hz, no channel response,
noise-stage contribution, electronics, occlusion, or motion, and record input,
configuration, intermediate-stem, and output SHA-256 values. Let
`r=sqrt(0.5)`. Cardinal yaw quaternions `(x,y,z,w)` are exactly
`q0=(0,0,0,1)`, `q90=(0,0,r,r)`, `q180=(0,0,1,0)`, and
`q270=(0,0,-r,r)`. The 120-degree estimator rung uses
`q120=(0,0,sqrt(3)/2,0.5)`.

| Fixture | Frozen protocol |
| --- | --- |
| Pure cardinal source/mic | Source-polar geometry is source `(0,0,0)` to microphone `(1,0,0)`; microphone-polar geometry is microphone `(0,0,0)` to source `(1,0,0)`. Rotate the tested pattern axis through `q0/q90/q180/q270`, evaluate all four families, and compare with the §9.1 table. Repeat quaternion cases scaled by `3.0` and require the normalized result to meet the same bound. |
| Cardinal L2 waveform | Shoebox room `10 x 8 x 3 m`, origin `(0,0,0)`, `max_order=0`; source `talker` at `(2,4,1.5)`, reference microphone at array-local `(0,0,0)` with array center `(6,4,1.5)`, plus microphones at `(0,+0.08,0)`, `(0,-0.08,0)`, and `(0,0,+0.08)` to keep a valid array. Use a 48,000-sample deterministic broadband probe at `0.1` RMS. Sweep `q0/q90/q180/q270` for source-only patterns. For microphone-only patterns, mirror the source to `(8,4,1.5)` so mic-to-source is `+X` and use the same quaternion sequence. For simultaneous patterns with the source at `(2,4,1.5)`, use source `q0/q90/q180/q270` and reference-mic world quaternions `q180/q270/q0/q90` for microphone-relative angles `0/90/180/270` respectively. Measure the reference pair stem against the matching directivity-disabled baseline and include one- and two-negative-lobe cases. |
| Frequency sweep | `N=2**18` deterministic Gaussian probe with seed `20260718`; points `[(100,-6), (1000,0), (8000,-3), (20000,-9)]`; non-null `0°` polar orientation. Use the exact §6.3 Welch H1 method (`nperseg=8192`, `noverlap=4096`), the summed-half-support edge exclusion in §9.2, and accepted bins 200 Hz–18 kHz. Run source-only, mic-only, and simultaneous source+mic cases; the simultaneous analytical target is the dB sum of both point curves. |
| Reverberant insertion | Reuse the L2 geometry with absorption `0.2`, `max_order=3`, and `N=48000`. Retain direct-arrival and post-direct-arrival RIR-tail masks from the baseline. For each pair, compare the effected stem with one signed multiplication for frequency-flat patterns and with the §9.2 FIR target for frequency-dependent patterns; verify the sum occurs only after all pair responses. For piecewise unit coverage, use four equal 12,000-sample segments and apply each segment's midpoint direct-path angle before overlap-add. |
| Metadata/waveform consistency | Use the source cardinal geometry, `AudioSourceSpec.directivity` in `{omni,cardioid}`, and a present source orientation. Compare L0/L1 `directivity_factor` with an explicitly matching source-only L2 `DirectivityPatternConfig`; mic patterns are omni and frequency-flat. |
| Estimator ladder | Rank-3 tetrahedral array of edge length `0.16 m` centered at `(6,4,1.5)` and source at `(2,4,1.5)`. Build `N=65536` geometrically delayed channels from one 200 Hz–12 kHz deterministic broadband probe (seed `20260718`), apply per-pair cardioid gains for `q0/q90/q120/q180`, then add the same independent per-mic broadband-noise bytes at every rung. Use exactly seeds `20260718` through `20260725`, scaled so the `q0` aggregate known-component SNR is `18.0 dB`. Run GCC with `interp=8` and default SRP grid/confidence semantics. Compute SNR from retained clean directional and noise components, never from an estimator-selected residual. |
| Invalid and zero direction | Parameterize every §3.7 family/id/point/orientation/mode/backend failure, including a highest point of `24000.000001 Hz` at 48 kHz, and assert an empty partial-output listing. Separately co-locate source/reference mic and require unity polar factors, finite frequency-filtered output, and no NaN. Include figure-eight 90°/270° nulls and all source/mic sign products. |
| Off-state and registry | The off-state corpus is the impulse, tone, broadband, silent, file/generated source, reverberant room, waveform export, and registry behavior at revision `31e0282`. Repeat with directivity disabled and with explicit frequency-flat omni defaults. The primary enabled registry fixture is the reverberant geometry with source `cardioid`, reference-mic `supercardioid`, and the frozen frequency points. |

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

### 10.2 S3.5 verification map

Implementation adds focused pure tests in `tests/test_effects_electronics.py`,
extends config/dispatch cases in `tests/test_channel_effects_chain.py`, and
extends backend and registry cases in
`tests/test_effects_backend_integration.py` and
`tests/test_backend_plugins.py`. Exact function names may follow repository
style, but every row below is mandatory.

| Acceptance criterion | Proof type and key assertion | Required evidence below `outputs/isaac_audio_sensors/S3/S3.5/` |
| --- | --- | --- |
| Frozen config/defaults | dataclass-field and TOML round-trip tests; exact §3.6 fields/defaults, immutable nested AGC, seed ownership, and absent-table normalization | `electronics_config_contract.json` |
| Fail-closed validation | parameterized invalid-input tests; every §3.6 type/range/required-field/backend failure precedes draw or output | `invalid_electronics_config_matrix.json`, `partial_output_listing.txt` |
| Boundary clipping and ratio | pure exact-mask test on the §8.4 boundary fixture; counts `(0,0,16,8)` and scalar ratio `0.375` exactly | `clipping_boundary_results.json`, `saturation_mask.npy` |
| Quantization-noise power | pure deterministic-ramp test; power ratio in `[0.9,1.1]` at exactly `N=2**18` | `quantization_noise_power.json`, `quantization_error_histogram.png` |
| TPDF dither decorrelation | pure named-stream test; every microphone `abs(r)<=0.010`, one-LSB peak-to-peak construction and stream descriptors exact | `tpdf_dither_correlation.json`, `tpdf_dither_stream_manifest.json`, `tpdf_error_correlation.png` |
| AGC analytical response/settling | pure constant-window tests; full trace within `1e-12`, attack/release within `0.01 dB` by `8*tau`, correct coefficient direction | `agc_step_response.json`, `agc_gain_traces.npz`, `agc_settling_overlay.png` |
| AGC unity/silence/bounds | exact disabled all-ones trace, silent exact unity/zero output, monotone bound fixtures with no exact inequality violation | `agc_unity_silence_bounds.json` |
| Quantizer edge invariants | pure property/regression tests; half-to-even ties, reconstruction endpoints, all frozen 16-bit levels idempotent without dither, alternating full scale not counted as clipped | `quantizer_edge_invariants.json` |
| Diagnostics contract | chain/backend test; exactly the four §8.2 keys, stable mic order, integer counts, scalar ratio/step, bounded gain summary | `electronics_diagnostics.json`, `full_agc_trace_sha256.txt` |
| Electronics once on mixture | room-backend integration spy/hash test; equal one/four-source sums produce exact output/diagnostics with one mixture and zero premix dispatches | `mixture_once_trace.json`, `mixture_electronics_sha256.json` |
| Waveform/RMS/estimator consistency | backend integration trace; aggregate RMS absolute error `<=1e-12`, export and any electronics-aware estimator consume the same final mixture | `metadata_waveform_consistency.json`, `estimator_input_trace.json`, `final_mixture_sha256.txt` |
| L0/L1 rejection | metadata-backend integration tests; enabled electronics raises `UnsupportedEffectError` with no partial frame/assets | `l0_l1_electronics_errors.json`, `partial_output_listing.txt` |
| Pure/backend off-state | identity and golden regression; input object/bytes exact, empty diagnostics, revision-`451b98a` frame/waveform hashes exact | `off_state_chain_identity.json`, `off_state_golden_sha256.json`, `off_state_frame.json`, `off_state_waveform_sha256.txt` |
| Seed replay/separation | two fresh chain/backend instances; same-seed dither/output/diagnostics/gain artifacts exact, alternate seed changes every active dither seed and output | `seed_replay_sha256.json`, `dithered_waveform_hashes.json` |
| Registry determinism | existing exact two-factory/two-run self-test with the fully enabled §8.4 primary fixture | `registry_determinism_electronics.json` |
| Minimum-window/runtime failures | empty, one-sample, DC, silence, non-finite, full-scale signs, bit-depth endpoints, and idempotence cases follow §11 exactly | `electronics_edge_case_matrix.json` |

`electronics_gate.json` is the mandatory machine-readable roll-up. It records
protocol revision `451b98a`, implementation revision, Python/NumPy/platform
versions, exact configuration and named-stream descriptors, fixture/artifact
SHA-256 values, sample counts, every frozen threshold, measured
counts/ratios/maxima/correlations, per-row status, reproduction commands, and
artifact SHA-256 values. A failed statistical row is fixed and rerun with the
unchanged seed, count, signal, and threshold; selective resampling is
forbidden.

Every S3.5 verification row is pure CPU and simulator-runtime-independent. The
room/backend rows use the repository's deterministic fake backend; there is no
live Isaac, Omniverse, GPU, microphone, robot, or hardware scenario in this
subphase. Live moving-scene and multi-source electronics coverage belongs to
S3.8 stress and cannot retroactively change this protocol. The S3.5 closeout
path is `docs/development/closeouts/S3/s3_5_electronics.md`.

### 10.3 S3.6 verification map

Implementation adds focused pure tests in `tests/test_effects_directivity.py`,
extends config/dispatch cases in `tests/test_channel_effects_chain.py`, and
extends room-backend and registry cases in
`tests/test_effects_backend_integration.py` and
`tests/test_backend_plugins.py`. Exact function names may follow repository
style, but every row below is mandatory.

| Acceptance criterion | Proof type and key assertion | Required evidence below `outputs/isaac_audio_sensors/S3/S3.6/` |
| --- | --- | --- |
| Frozen config/defaults | dataclass-field and TOML round-trip tests; exact §3.1/§3.7 fields/defaults, immutable nested mappings/points, resolution order, and mode default | `directivity_config_contract.json` |
| Polar families/angles | pure parameterized evaluator over all families/cardinal quaternions; scalar error `<=1e-12`, normalized-quaternion equivalence, signed rear lobes | `polar_cardinal_results.json`, `polar_response_overlay.png` |
| Cardinal waveform gain | L2 pair-stem integration test; every nonzero target sign and `0.05 dB` magnitude bound, every null within `1e-6` linear bounds | `cardinal_waveform_gain.json`, `cardinal_pair_stems_sha256.json` |
| Frequency response | pure and L2 Welch H1 tests; one-pattern maximum error `<=0.25 dB`, simultaneous maximum `<=0.50 dB`, signed polarity retained | `frequency_sweep_welch.json`, `frequency_response_overlay.png`, `frequency_response_error.png` |
| Source/mic product | pure/L2 Cartesian pattern test; scalar/FIR product per pair, including one-negative, two-negative, null, and simultaneous frequency patterns | `source_mic_product_matrix.json`, `source_mic_pair_stems.npz` |
| Full-convolved-stem insertion | reverberant and piecewise backend spy/hash tests; direct and tail samples weighted once per pair before sum, segment weighting before overlap-add, zero post-mix dispatches | `per_pair_insertion_trace.json`, `rir_tail_weighting.json`, `full_contribution_sha256.json` |
| Metadata/waveform consistency | L0/L1 helper versus L2 source-only test; shared omni/cardioid nonzero cases within `0.05 dB`, rear null within `1e-6` linear amplitude | `metadata_waveform_consistency.json` |
| Estimator degradation | fixed eight-seed ladder; SNR, SRP confidence, and GCC proxy meet every monotonic/minimum-drop assertion in §9.5 | `estimator_confidence_ladder.json`, `estimator_confidence_overlay.png`, `estimator_input_sha256.json` |
| Fail-closed validation | parameterized invalid family/id/point/orientation/mode/backend tests; located typed exception before scheduling/room/output | `invalid_directivity_config_matrix.json`, `partial_output_listing.txt` |
| Zero direction and nulls | pure boundary tests; co-location produces unity polar factors and finite response, figure-eight nulls meet linear bound, no NaN | `directivity_edge_case_matrix.json` |
| Diagnostics contract | backend test; exactly `source_pattern`, `mic_pattern`, and `mode`, stable source/mic order, exact resolved records, no reflection-angle claim | `directivity_diagnostics.json` |
| Disabled/omni off-state | full golden regression; exact revision-`31e0282` premix/mixture/detection/RMS/waveform/frame hashes and no `effects` key | `off_state_golden_sha256.json`, `off_state_frame.json`, `off_state_waveform_sha256.txt` |
| Determinism/registry | two fresh enabled instances and existing two-factory/two-run self-test; exact stems, output, diagnostics, frame, and artifact bytes | `registry_determinism_directivity.json`, `enabled_replay_sha256.json` |
| Fidelity limitation ledger | static claim/evidence review; records full-convolved-pair limitation, P2 deferrals, and the required S3.9 reconciliation of `core/fidelity.py` | `fidelity_reconciliation.json` |

`waveform_directivity_gate.json` is the mandatory machine-readable roll-up. It
records protocol revision `31e0282`, implementation revision,
Python/NumPy/pyroomacoustics/platform versions and module origins, exact
normalized configuration, fixture and intermediate-stem hashes, sample counts,
Welch parameters, every frozen threshold, measured maxima/ladder statistics,
per-row status, reproduction commands, and artifact SHA-256 values. A failed
row is fixed and rerun with unchanged fixtures, seeds, bins, and thresholds;
selective estimator-seed or angle removal is forbidden.

S3.6 is a pure/offline CPU gate. The pure evaluator, config, estimator, and
fake-backend rows require no Isaac runtime. The real L2 integration rows do
require the pinned pyroomacoustics-capable Python environment; when Isaac
Sim's Python is used only because it supplies that dependency, evidence records
the exact Isaac/Kit/Python/package/module origins in
`evidence_environment.json`, following the S3.1 environment-record pattern,
but does not launch `SimulationApp` or promote the run to a live scenario. A
base environment that lacks pyroomacoustics may skip ordinary optional tests
but cannot pass the L2 acceptance rows; evidence generation must use the
recorded dependency-capable environment.

No live Isaac stage, renderer, GPU, microphone, robot, or hardware scenario is
required for S3.6. Moving/rotating mounts, multi-source imbalance, and live
scene stress belong to S3.8 and cannot retroactively alter this protocol. The
S3.6 closeout path is
`docs/development/closeouts/S3/s3_6_waveform_directivity.md`.

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

For S3.5 specifically, the matrix includes absent and empty electronics/AGC
tables; non-bool enable/dither values; missing active fields; `full_scale` equal
to zero, negative, NaN, or either infinity; bit depths `7`, `8`, `32`, `33`,
bool, and non-integer; active dither with a missing, bool, or out-of-range
shared seed; target RMS and gain bounds at and beyond every endpoint; reversed
or non-unity-containing gain bounds; and zero, negative, NaN, infinite, or
greater-than-60-second attack/release times. Every invalid case raises the
located `ConfigValidationError` or required `UnsupportedEffectError` before a
dither draw, sample change, diagnostic, frame, or asset.

For S3.6 specifically, the matrix also includes absent and empty directivity,
source-pattern, mic-pattern, default, and override tables; non-bool enable;
unknown/missing/case-mismatched families; unknown, empty, duplicate-normalized,
or reordered source and microphone ids; missing non-omni source/microphone
orientations; finite non-unit quaternions (accepted and normalized); zero or
non-finite quaternions (rejected by the frame/type contract); zero-length
source-to-mic direction (unity polar factor); fewer than two, non-finite,
non-positive, duplicate, decreasing, or above-Nyquist frequency points;
unsupported modes/profiles/backends; figure-eight nulls at 90/270 degrees;
negative rear lobes; and simultaneous source/microphone patterns including two
negative lobes. Every invalid case fails before source scheduling, room/RIR
construction, sample filtering, diagnostic, frame, waveform, or asset.

A finite DC input uses its absolute amplitude as the per-window RMS detector
and follows the exact §8.1 recurrence. Alternating-sign samples at exactly
`-full_scale` and `+full_scale` are finite, are not counted as clipped, and
quantize to the exact endpoints. Exact silence under enabled AGC selects a
unity asymptote and therefore produces an exact-unity gain trace and exact-zero
output from the required unity initial state. With AGC disabled, an empty-time
array remains empty, makes no dither draw even when dither is configured, and
reports zero counts/ratio; with AGC enabled it fails because the per-window RMS
is undefined. A single-sample window is supported and uses its absolute sample
as detector RMS followed by one gain update.

NaN or infinite input fails at chain validation before caller-owned data is
changed. With AGC and dither disabled, quantizing any already-quantized in-range
`k*Delta` reconstruction value is idempotent, including zero and both
full-scale endpoints; the second output must be byte-identical to the first.
Dither intentionally removes that repeated-application idempotence and is
excluded from this invariant.

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
- S3.5 saturation is hard clipping only. Soft-knee saturation, analog
  waveshaping, hysteresis, slew-rate limits, anti-alias filtering of nonlinear
  products, and recovery-memory models are out of scope.
- S3.5 AGC uses one stateless per-window RMS detector and independent
  microphone gains. It is not a cross-frame compressor, linked-array gain
  controller, peak limiter, loudness standard, or physical circuit model.
- S3.5 quantization is a normalized float-domain mid-tread model. It does not
  define packed PCM storage, codec behavior, sample-word endianness, ADC
  integral/differential nonlinearity, missing codes, or physical voltage units.
- S3.6 directivity is the §9 `per_pair_direct_path` approximation: one response
  selected from each pair's direct-path angle weights that pair's entire
  convolved contribution. Per-reflection departure/incidence angles,
  direct-arrival-only separation, diffraction-aware pattern changes, and
  path-resolved pattern filtering are not claimed and are deferred to P2.
- Pyroomacoustics-native directional source/microphone objects or any native
  directivity fallback are not Stage 1 behavior. A separately reviewed P2
  design must define their family mapping, RIR/path semantics, compatibility,
  and acceptance evidence before they can replace or augment §9's mode.
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
frozen protocol. Any change to an `S3.3`, `S3.4`, `S3.5`, or `S3.6` fixture,
measurement method, sample count, seed, accepted sample, rounding rule, or
threshold after acceptance evidence is generated invalidates that subphase
evidence and requires a reviewed design revision plus a complete rerun.
`S3.4` is implemented and closed at
`docs/development/closeouts/S3/s3_4_seeded_noise.md`. `S3.5` is frozen
prospectively by the dated `451b98a` status entry and may proceed to
implementation without adjusting this protocol from observed results; its
acceptance closeout path is
`docs/development/closeouts/S3/s3_5_electronics.md`. `S3.6` implementation and
acceptance may proceed prospectively only from the dated `31e0282` freeze in
§9/§10.3, without adjusting it from observed results. Its closeout path is
`docs/development/closeouts/S3/s3_6_waveform_directivity.md`; closeout must
carry the reflected-path limitation and S3.9 `core/fidelity.py` reconciliation
item forward without broadening the supported claim.

This change is documentation only. No implementation, unit, integration,
Isaac, GPU, or hardware verification was run or is claimed by this
specification.

## References

- `docs/final_sensor_development_plan.md`, §§6.2 and 6.6.
- `docs/development/specs/s0_squadbot_readiness_acceptance.md`, §S3.
- `docs/development/specs/s1_architecture_lock.md`.
- `docs/development/specs/s2_atomic_writers.md`.
- `src/isaac_audio_sensors/core/effects/chain.py`.
- `src/isaac_audio_sensors/core/effects/config.py`.
- `src/isaac_audio_sensors/core/effects/noise.py`.
- `src/isaac_audio_sensors/core/effects/streams.py`.
- `src/isaac_audio_sensors/core/backends/amplitude.py`.
- `src/isaac_audio_sensors/core/backends/room_acoustics.py`.
- `src/isaac_audio_sensors/core/backends/tdoa.py`.
- `src/isaac_audio_sensors/core/backends/geometry.py`.
- `src/isaac_audio_sensors/core/calibration_profile.py`.
- `src/isaac_audio_sensors/core/config.py`.
- `src/isaac_audio_sensors/core/constants.py`.
- `src/isaac_audio_sensors/core/math_utils.py`.
- `src/isaac_audio_sensors/core/types.py`.
- `src/isaac_audio_sensors/core/doa/gcc_phat.py`.
- `src/isaac_audio_sensors/core/doa/srp_phat.py`.
- `src/isaac_audio_sensors/core/fidelity.py`.
- `src/isaac_audio_sensors/core/plugins/declarations.py`.
- `src/isaac_audio_sensors/core/plugins/registry.py`.
- `tests/test_effects_noise.py`.
