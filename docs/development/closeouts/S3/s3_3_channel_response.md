# S3.3 closeout - channel response and mismatch

Status: **passed** (2026-07-18). Entry revisions: frozen specification
`8cf153f`; implementation `fcb93c9`; off-state golden baseline `7163360`.
Predecessors: `docs/development/closeouts/S2_closeout.md` and the S1.2/S1.3
dependency closeouts `docs/development/closeouts/S1/s1_2_public_contracts.md`
and `docs/development/closeouts/S1/s1_3_plugin_contracts.md`.

## Frozen-tolerance provenance

The complete S3.3 architecture, fixtures, measurement methods, and tolerances
were committed in `docs/development/specs/s3_channel_effects_chain.md` at
`8cf153f`, before implementation and acceptance evidence. The implementation
and evidence runner entered from that revision and landed at `fcb93c9`. The
roll-up records `implementation_base_revision` as the full `8cf153f` hash and
`entry_revision` as the full `7163360` hash used by the off-state golden.
No tolerance was selected or adjusted from the measured results.

## Gate results

`outputs/isaac_audio_sensors/S3/S3.3/channel_response_gate.json` reports
`status: "passed"`; all 10 criterion rows passed. Numerical entries below are
maximum errors, not means or percentiles.

| Criterion | Frozen threshold | Measured result | Status |
| --- | --- | --- | --- |
| Tone gain recovery | `<= 0.05 dB` | `1.7763568394002505e-15 dB` | passed |
| Fractional delay recovery | `<= 0.10 sample` (`<= 2.0833333333333334e-6 s`) | `0.056966922675175446 sample` (`1.1868108890661552e-6 s`) | passed |
| Polarity | exact element and byte equality to `numpy.negative(input)` | element-exact and byte-exact | passed |
| Frequency-response recovery | `<= 0.25 dB` on every accepted Welch passband bin | `0.05422703518646843 dB` | passed |
| Pure chain off-state | same object; identical dtype, shape, strides, and bytes; empty diagnostics | object and bytes identical; `float32`, shape `(4, 16)`, strides `(64, -4)`; diagnostics `{}` | passed |
| Backend off-state | frame and waveform byte-identical to golden; no `effects` key | frame and waveform byte-identical; `effects` absent | passed |
| L1 gain adapter | `<= 0.05 dB` per microphone | `2.6645352591003757e-15 dB` | passed |
| L1 delay adapter | `<= 1e-12 s` per microphone | `3.5744790374131474e-19 s` | passed |
| L1 polarity adapter | exact metadata; RMS and delay unchanged when polarity-only | exact metadata and observables unchanged | passed |
| Unknown microphone / order mismatch | `ConfigValidationError` before simulation | both invalid cases rejected with typed, located errors | passed |
| Unsupported waveform feature on L0/L1 | `UnsupportedEffectError`; no partial frame or asset | both `geometry_only` and `tdoa_synthetic` rejected; partial-output lists empty | passed |
| Deterministic backend | registry twice-run self-test and enabled fixture exact | both enabled hashes `cd2cf94631947ff628a3728eaeab15adfe72bbf51cd94741ad6f300a5b6323ba` | passed |

The table expands the roll-up's L1 adapter row into its three frozen checks and
combines the related invalid-configuration cases; it does not add acceptance
criteria beyond the 10 machine-readable rows.

## Off-state compatibility and adapter honesty

Disabled effects preserve the exact input array object and its bytes, and the
room backend preserves serialized frame and waveform bytes from the pre-S3
golden. The frame SHA-256 is
`588c27a1975bac944ca4cae6adf9df93556e1165d2a329f5de835732abe9746e`;
the waveform SHA-256 is
`f290fa7b187d845960e272193996711aa0adb3827ba0d78395509467e78464c4`.
No `effects` diagnostic key is emitted in the backend off-state.

On L1, gain and delay change only their representable metadata observables.
Polarity is recorded exactly as metadata but is metadata-only: it does not
pretend to invert a waveform that L1 does not produce, and polarity-only
configuration leaves RMS and delay observables unchanged. A waveform-only
frequency response on either L0 or L1 fails closed with
`UnsupportedEffectError` before a partial frame or waveform asset is emitted.

## Tests and environment

- Pre-S3.3 `make test` baseline (S3.0 revision `7163360`): 750 passed,
  0 failed, 74 optional-dependency skips.
- Post-S3.3 `make test` (revision `fcb93c9`): 802 passed, 0 failed, 74
  optional-dependency skips: 52 new passing tests.
- Both totals were measured by the orchestrator with `make test` at the named
  revisions; the gate roll-up records the test and lint commands but not
  their pytest totals.

Acceptance artifacts were generated on Linux with Python 3.12.3, NumPy 2.5.1,
pyroomacoustics 0.10.1, and SciPy 1.18.0. Pyroomacoustics and SciPy were present
for the room-backend and Welch evidence fixtures. The base `.venv` does not
carry either optional dependency; its capability tests intentionally exercise
and expect their absence. The evidence therefore proves the optional
room-backend fixtures only in the recorded dependency-capable environment and
does not redefine the base environment.

## Evidence artifacts

All paths below are relative to
`outputs/isaac_audio_sensors/S3/S3.3/`. The listed SHA-256 values are copied
from `channel_response_gate.json` and were checked against the files at
closeout.

| Artifact | SHA-256 |
| --- | --- |
| `delay_correlation_traces.npz` | `94a932e217dbddd4ca289a315333c215925da2e2e13ff36f70b03ad5a9c62f12` |
| `delay_recovery_results.json` | `4c885be12da88a224d37d8d6981cfd4e3ec812c4ad590553b35adeace46bb008` |
| `frequency_response_overlay.png` | `6bcf78fd748caea097a3a100ed4f0f8ac2023cae30779e09c984aa2240e32cef` |
| `frequency_response_welch.json` | `505da2c73c476db78c1d0de8cc5de4db3dbd1bb7351f947c6c586dd076a3468d` |
| `gain_tone_results.json` | `50dcf20592ea857bfbef5242324b5ce1b2999bc9e676b48fa36ce98e57d0509d` |
| `gain_tone_summary.csv` | `3ba5157d666a505c8e32bea1b855b496c66b134cee37483257e4eaf79523d7b1` |
| `invalid_config_matrix.json` | `c09e0bcb70b9964311862eb0e1edfc05f8e6a76a0cfc47e45cf323416b8ff8e2` |
| `l1_metadata_adapter.json` | `54e0b41e70c2ccc7806bf962861b2ae4d96cf695c3d6cd4baa21af9caf423eb3` |
| `off_state_chain_identity.json` | `ad1e1bda68c90643b8208bfa0ee85a45cb8c0d5743cf817c2d491a4fcf9b13fd` |
| `off_state_frame.json` | `d9c64811d402aeb7f0ab7d14ba758a69302402babecc17fea4417b5d15d5d899` |
| `off_state_golden_sha256.json` | `e4b12fd4076254bfa3ec19f53b9eaef20de9a8e5c9f1ddf4f974b9ca7be9f978` |
| `off_state_waveform_sha256.txt` | `d50c4e32e35e178b12a1318bce36cfcf598641e93c54f9b5302a249e43ae39e2` |
| `partial_output_listing.txt` | `4d5ef551d5069fde5f4259887bc7aa0800026ed3d61a83650b79cfad8f896896` |
| `polarity_exact_result.json` | `18033502a36babf9d39b2710ae199f9eb9d3bc055e66af644969c5655999f83f` |
| `registry_determinism.json` | `345ed4e3ded860c8dd4b68595cde8e913ac3887b83d0014e7c66774b60bd9e60` |
| `unsupported_feature_errors.json` | `bffbeda469ad7feb34b5789dbcfad0064efa85eddeadebeaa0b236c57a48670d` |

`channel_response_gate.json` is the machine-readable roll-up and does not
self-report a SHA-256 for itself.

## Reproduction commands

The gate records these commands:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python scripts/s3_3_evidence.py
```

The evidence command requires a reproduction environment containing the
recorded pyroomacoustics 0.10.1 and SciPy 1.18.0 dependencies; the current base
`.venv` deliberately omits them.

## Defects found and fixed during the gate

None recorded. `channel_response_gate.json` has no defects field, and every
machine-readable criterion row is `passed`; no failure/fix/rerun sequence is
claimed.

## Limitations carried forward

- The magnitude FIR does not reproduce arbitrary measured phase. Any non-null
  `phase_deg` fails explicitly; scalar delay is the supported linear phase
  offset.
- Finite-window FFT delay and FIR filtering retain documented edge transients.
  Central-region acceptance does not remove those boundary effects from
  exported windows.
- S3.4 noise, S3.5 electronics, and S3.6 waveform-directivity numerical
  tolerances remain deferred and must be frozen prospectively before their
  evidence is viewed.
- This gate makes no calibrated sim-to-real fidelity claim and no diffraction
  claim.

## Input contract for S3.1

S3.1 pose-derived velocity is next per `TODO.md`. It inherits the immutable
effects configuration surface and the rule that motion metadata must not
silently change channel-response semantics. S3.1 must freeze its motion and
velocity fixtures, measurement methods, and tolerances in a committed spec
before evidence; preserve the S3.3 hard off-state; fail invalid or
unrepresentable configurations before partial output; and keep the established
frame-v1, backend capability, deterministic ordering, and typed-error
contracts intact.
