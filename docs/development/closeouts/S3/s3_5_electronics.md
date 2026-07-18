# S3.5 closeout - electronics

Status: **passed** (2026-07-18). Entry revisions: frozen specification
`73960ed`; implementation `eb1ea68`; pinned protocol/off-state baseline
`451b98a`. Predecessors:
`docs/development/closeouts/S3/s3_3_channel_response.md` and
`docs/development/closeouts/S3/s3_4_seeded_noise.md`.

## Frozen-tolerance provenance

The complete S3.5 electronics model, fixtures, sample counts, measurement
methods, seeds, rounding rule, accepted values, and tolerances were committed
prospectively in `docs/development/specs/s3_channel_effects_chain.md` at
`73960ed`, before S3.5 implementation or acceptance evidence. That dated
specification entered from revision `451b98a`, which pins the completed S3.4
closeout and the off-state golden corpus. Implementation and retained evidence
landed later at `eb1ea68`. No S3.5 threshold, fixture, seed, sample count, or
measurement method was selected or adjusted from the measured results.

The roll-up retains the field values `protocol_revision: "451b98a"` and
`implementation_revision: "73960ed57c43e4c3dd98b8dca7c454f043ba242b"`.
Those names reflect how the pre-commit evidence runner recorded its entry and
HEAD revisions: `451b98a` is the pinned protocol/off-state entry, while the
full `73960ed` hash is the frozen specification and implementation base. The
implementation itself is commit `eb1ea68`; this closeout does not relabel the
machine-readable fields or represent `73960ed` as the landed implementation.

## Gate results

`outputs/isaac_audio_sensors/S3/S3.5/electronics_gate.json` reports
`all_rows_passed: true`; all 16 machine-readable criterion rows passed.

| Criterion | Frozen threshold or exact requirement | Measured result | Status |
| --- | --- | --- | --- |
| Frozen config/defaults | Exact `AgcConfig` and `ElectronicsConfig` fields/defaults; frozen nested AGC; absent-table normalization; shared dither seed at `audio.effects.noise.seed` | Both exact field/default sets matched; nested AGC frozen; absent table normalized exactly; shared seed `20260718` at the required path | passed |
| Fail-closed validation | Every frozen type/range/required-field/backend failure precedes draw, sample change, diagnostic, frame, or asset | Retained matrix: 7/7 invalid cases raised located errors; `all_failed_closed: true`; partial-output listing reports no emitted frame, diagnostic, waveform, or asset | passed |
| Boundary clipping and ratio | At `N=16`, exact counts `(0,0,16,8)` in `(front,right,rear,left)` order and exact aggregate ratio `0.375` | Counts `(0,0,16,8)`; ratio `0.375` | passed |
| Quantization-noise power | Uncentered error-power ratio in `[0.9,1.1]` at `N=2**18`; `Delta=1/32768` | Ratio `1.0000076296592806`; measured power `7.761080669078359e-11` versus analytical `7.761021455128987e-11`; `Delta=3.0517578125e-05` | passed |
| TPDF dither decorrelation | Every microphone `abs(r)<=0.010`; TPDF peak-to-peak no greater than one LSB; exact named-stream descriptors | Maximum `abs(r)=0.002294744828159694`; maximum peak-to-peak `3.045941469556915e-05 <= 3.0517578125e-05`; all four stream descriptors retained | passed |
| AGC analytical response/settling | Maximum trace error `<=1e-12`; attack/release within `0.01 dB` by exactly `8*tau` (3,840/19,200 updates); correct coefficient direction | Maximum trace error `0.0`; maximum settling error `0.008736978433394993 dB`; attack and release fixtures monotone with the frozen coefficients | passed |
| AGC unity/silence/bounds | Disabled trace exactly float64 unity and output byte-identical; silence has exact unity trace and zero output; every enabled gain in `[0.25,4.0]` with no overshoot | Disabled trace exact unity and output byte-identical; silent trace exact unity and output exact zero; every enabled trace within bounds | passed |
| Quantizer edge invariants | Half-to-even ties exact; both endpoints representable; all 65,537 frozen 16-bit reconstruction levels idempotent without dither; full-scale signs preserved with zero clipping count | Tie codes mapped to `(-2,-2,-0,+0,+2,+2)`; endpoints exact; 65,537 levels byte-idempotent; full-scale clipping count `0` and sign bytes preserved | passed |
| Diagnostics contract | Exactly `clipping_count_per_mic`, `saturated_sample_ratio`, `quantization_step`, and `agc_gain_trace_summary`, with ordered microphones and exact values | Exact four-key payload; counts `{front:0,right:0,rear:16,left:8}`; ratio `0.375`; step `3.0517578125e-05`; bounded four-microphone gain summary | passed |
| Electronics once on mixture | Equal one-source/four-source sums produce byte-identical output and diagnostics; one mixture dispatch and zero premix electronics dispatches | Inputs equal, outputs byte-identical, diagnostics exact; dispatch counts `1` mixture / `0` premix for source counts `1` and `4` | passed |
| Waveform/RMS/estimator consistency | Aggregate RMS absolute error `<=1e-12`; export and any electronics-aware estimator use the final mixture without reclassifying signal-only estimators | Maximum RMS error `0.0`; export used final mixture; final-mixture hash `900ca3635a0f815ae19053df65ab82151634510cb7163f2dd747f63a73d9c5b2`; no electronics-aware estimator claim; known-source estimators remained signal-only | passed |
| L0/L1 rejection | Enabled electronics raises `UnsupportedEffectError` on both waveform-free backends before partial frame or asset creation | `geometry_only` and `tdoa_synthetic` both raised the typed error; both partial-output lists empty | passed |
| Pure/backend off-state | Pure object/bytes exact with empty diagnostics; revision-`451b98a` frame/waveform exact and no `effects` key | Object and bytes exact; diagnostics `{}`; frame hash `2b3f7b929dc3ae3e97d71f00f21552b91ca0772052c242eb6ea0e1d78413a16b`; waveform hash `a856ae93a9d1036f5fa11390f48cffd228cc3b10da1d0fd092b00a6e135abcdd`; `effects` absent | passed |
| Seed replay/separation | Fresh same-seed instances have exact output/diagnostics; alternate seed changes every active dither seed and at least one output byte | Same-seed output hash `fd64771a8bff166b58db1905a57645a21933fa5b6d63b307e9c2c64be5796e07` and diagnostics were exact; seed `20260719` changed all four derived seeds and output hash to `c1cca5a79a16922174ae4483df59e593f850f171277d61c2e5d695b106b65d98` | passed |
| Registry determinism | Exact two-factory/two-run self-test with the fully enabled primary fixture | Frames exact with hash `6a6bbece1587162edd04aeb5bcef74abda8824d40d20609eceed759193412256`; waveforms exact with hash `8cc282c8e9db977f14b229a89994092d50d5786d51ae8f8338fcce8d50b3346d` | passed |
| Minimum-window/runtime failures | Empty, one-sample, DC, silence, non-finite, full-scale signs, bit-depth endpoints, and idempotence follow the frozen rules | Empty shape `(1,0)` with ratio `0.0`; one-sample detector `0.5` and finite output; DC absolute-amplitude rule; silence unity/zero rule; non-finite input failed closed; bit depths `8` and `32` validated; sign/idempotence evidence passed in the edge-invariants row | passed |

The retained invalid-configuration artifact enumerates seven representative
fail-closed cases, while the frozen §11 matrix and focused test suite cover
additional type, range, endpoint, backend, and runtime variants. This closeout
claims the 16 roll-up rows and the cases actually retained in their artifacts;
it does not claim that the seven-row JSON is a one-to-one enumeration of every
variant in the specification prose.

## Chain dispatch and observable ownership

Electronics runs exactly once on the summed mixture after S3.3 response and
S3.4 noise. It is not distributable across source premixes: AGC, clipping,
quantization, and dither are nonlinear or stochastic and would otherwise
become source-count dependent. Frame aggregate RMS and waveform export use the
same final effected mixture. Detection-level known-source estimators remain
signal-only; this gate makes no electronics-aware estimator-confidence claim.

Enabled electronics is never represented on L0/L1. Both waveform-free
backends reject it before producing partial output. The disabled branch
preserves the pure input object and the pinned backend frame/waveform bytes.

## Tests, environment, and live-coverage boundary

- Pre-S3.5 `make test` baseline at `451b98a`: 962 passed, 0 failed, 76
  optional-dependency skips.
- Post-S3.5 `make test` at `eb1ea68`: 1008 passed, 0 failed, 76
  optional-dependency skips: 46 additional passing tests.
- Both totals were measured by the orchestrator at the named revisions; this
  documentation-only closeout did not rerun them.

The roll-up records package version-independent environment facts of Linux,
Python 3.12.3, and NumPy 2.5.1. Every S3.5 verification row is pure CPU and
simulator-runtime-independent. Backend fixtures use the repository's
deterministic fake room backend; no installed Isaac, Omniverse, GPU,
microphone, robot, or hardware execution is inferred.

No live scenario is required or claimed for S3.5. Live moving-scene and
multi-source electronics coverage belongs to S3.8 and cannot retroactively
change the frozen S3.5 protocol.

## Evidence artifacts

All paths below are relative to
`outputs/isaac_audio_sensors/S3/S3.5/`. SHA-256 values are copied from
`electronics_gate.json`; all 31 listed hashes were checked against the files
at closeout.

| Artifact | SHA-256 |
| --- | --- |
| `agc_gain_traces.npz` | `3effe73d6603756b75a7ef4214db7d676023297b82f52b6964b74d690ab26116` |
| `agc_settling_overlay.png` | `666ccdc955cd00854947ed07cb590d21396d9ae9de428e7b4db9e5e16edfe437` |
| `agc_step_response.json` | `fd74db49db370ebffa4d65a592766c0387f7d1d025a180b844faf3ef42d05dd3` |
| `agc_unity_silence_bounds.json` | `1290851599bdf6cfd422587a9ab221de8d635dc13c2a2d22f3bcc21bc0247b48` |
| `clipping_boundary_results.json` | `0bcc3c2d051d8c90418b9d8ce2c5f9fe89784922e04cc284364e6b5b02921284` |
| `dithered_waveform_hashes.json` | `6845fb24bd96687a5f53daaa8555be19e9abeea20956702d5064610b8aedd446` |
| `electronics_config_contract.json` | `7aed9835ddc04ed9f4c3f24806879b6863ef1dd5f8802a18f1162220c3d5e61e` |
| `electronics_diagnostics.json` | `510d1aaf30f99d21a8c11774cb699e20f6d33ac1944a29116ba516c510cac53d` |
| `electronics_edge_case_matrix.json` | `da61f43c7fcf59a4dcb73ff5cf4c0b7fdf3d2e9e7b16918257f72c7ba56185cf` |
| `estimator_input_trace.json` | `d7c7d79d020fe8b4b6c74d7848709734c0ae19339db096d5a7b641341ae78f0c` |
| `final_mixture_sha256.txt` | `6ff5313a06d4729a7c0f1aca25b1e55e010af2d948bab24cef6f24b2688c592e` |
| `full_agc_trace_sha256.txt` | `df2a13d95fec511cd2b19884fe4b52f81b36b106c521f989b5ef85d7852bfeb5` |
| `invalid_electronics_config_matrix.json` | `eac49c4ea5d64c518f14c856741fdfbff05e773c6054cd5d28b35a857b1a119f` |
| `l0_l1_electronics_errors.json` | `a6f984cbbd8d50cb6ee0c563f810f84e9e5b61ebf305ecb583faee9faef61fb2` |
| `metadata_waveform_consistency.json` | `dd1a4615f96ccf476049f72e5d1ba0660945caf8c6af1a09a563141869cc39c9` |
| `mixture_electronics_sha256.json` | `2ca474ad1bb71fee6df085762f87b903bcf08a26d4c985fca9bfc5dfeff4de97` |
| `mixture_once_trace.json` | `50ec5f0a13dae1c1379da6df6a7b3aeeed4d94c1717de8a59c32eb12207e7031` |
| `off_state_chain_identity.json` | `ab682a51c29a0d8a033b0d8c2487f6e3b5fcbb16d045cd7a7e1881e80cf4ed7a` |
| `off_state_frame.json` | `3f73bc68a87c9f2366cc50ced06947c2303db5d5225e40e43806f6107ce8d185` |
| `off_state_golden_sha256.json` | `7810895e3d3f194f4bd0f6959462cc530a3d656c09562076e73d1f9cd88ee2c6` |
| `off_state_waveform_sha256.txt` | `8ac806e05eb7a562e599c6ad3b9c4a6f384b2f748a27eecfe5aca976bb20921a` |
| `partial_output_listing.txt` | `1d039607a9801440b750ce36ebab2ee84258505c328834c92ab63b8693c3f7f0` |
| `quantization_error_histogram.png` | `b33c2d31a7b4c80c9c70580c41f29734b9d0850bc1ff186fa2cf1758cd07c877` |
| `quantization_noise_power.json` | `9c668de98a3b9303226bb56c033291599451b1fece41f186df17759083a66e32` |
| `quantizer_edge_invariants.json` | `4e7a147c32dddc4e787779ba4cc3a1e7ede2b590a580bdd360cd9dff13d8d292` |
| `registry_determinism_electronics.json` | `e65c6743a8e1cf392b52430fa2646999c040e4a5d0f145d3c3949e86c4dee82f` |
| `saturation_mask.npy` | `d87ddf42942f25ebf5c4d05046460a418ec5a2d0c2b50aadc1ba4ba301c6cbf5` |
| `seed_replay_sha256.json` | `a9de1794d1a92dcaf41f1e1c36d81e7f0173b5838b3683f2e42a3cfa6a150bef` |
| `tpdf_dither_correlation.json` | `7cba47ec91c639ff674909fabf22b0c107e07aa10e4e5d2763c0d32235bdabbd` |
| `tpdf_dither_stream_manifest.json` | `c6b7f184b1252464d9bc7bb74eb3607591d6287607a34b315088326f3cae7a83` |
| `tpdf_error_correlation.png` | `11fb7c15a96aecda419b14935b7ff16c61f88e6a95d45f298f4c004e1a80ff1c` |

`electronics_gate.json` is the machine-readable roll-up and does not
self-report a SHA-256 for itself.

## Reproduction commands

The gate records these commands:

```bash
.venv/bin/python scripts/s3_5_evidence.py
.venv/bin/python -m pytest -q tests/test_effects_electronics.py
```

The evidence command uses frozen pure fixtures and is not a live-simulator
target.

## Defects found and fixed during the gate

None recorded. `electronics_gate.json` has no defects field, every one of its
16 criterion rows is `passed`, and no failure/fix/resampling sequence is
claimed.

## Limitations carried forward

- Saturation is hard clipping only. There is no soft-knee saturation, analog
  waveshaping, hysteresis, slew-rate limiting, nonlinear anti-alias filtering,
  or recovery-memory model.
- AGC is a stateless first-order per-window RMS model with independent
  microphone gains. It is not cross-frame, linked-array, peak-limiting,
  loudness-standard, or physical-circuit behavior.
- Enabled electronics is never available on L0/L1 because those backends have
  no waveform on which to apply it. They fail typed rather than ignoring or
  approximating the stage.
- This gate contains no live scenario. S3.8 owns live moving-scene and
  multi-source electronics stress; S3.5 does not imply Isaac, robot, hardware,
  or calibrated sim-to-real validation.
- Quantization is a normalized float-domain mid-tread model. It does not model
  packed PCM, codecs, ADC nonlinearity, missing codes, or physical voltage.

## Input contract for S3.6

S3.6 waveform directivity is next. It inherits the frozen chain ordering,
hard off-state, final-waveform ownership, deterministic registry behavior,
typed failure rules, and L2/L3 waveform boundary. Directivity remains a
source-to-microphone synthesis-time weighting before premix summation, not a
post-mix electronics operation. Its cardinal-angle/frequency fixtures,
measurement methods, accepted bins, estimator-confidence expectations, and
numerical tolerances must be frozen prospectively in a dated revision of
`docs/development/specs/s3_channel_effects_chain.md` before any S3.6
acceptance evidence is generated or viewed.
