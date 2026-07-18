# S3.6 closeout - waveform directivity

Status: **passed** (2026-07-18). Entry revisions: frozen specification
`02a2fe5`; implementation `7ba5a1f`; estimator-ladder amendment `1967c03`;
evidence-integrity fix and final evidence `237e56c`. Predecessors:
`docs/development/closeouts/S3/s3_3_channel_response.md`,
`docs/development/closeouts/S3/s3_4_seeded_noise.md`, and
`docs/development/closeouts/S3/s3_5_electronics.md`.

## Frozen-tolerance provenance

The complete S3.6 pattern model, fixtures, sample counts, measurement methods,
accepted bins, and numerical tolerances were committed prospectively in
`docs/development/specs/s3_channel_effects_chain.md` at `02a2fe5`, before the
S3.6 implementation or acceptance evidence. That dated specification records
the pre-implementation protocol and off-state entry as `31e0282`.
Implementation landed at `7ba5a1f`; the estimator-only amendment landed at
`1967c03`; the evidence-integrity repair and regenerated evidence landed at
`237e56c`.

The roll-up therefore retains `protocol_revision: "31e0282"` and the full
`implementation_revision` value
`"1967c035c6ec6c2a162df063de73e01317f7a594"`. These fields are not mislabeled:
`31e0282` is the protocol/off-state entry named by the frozen specification,
and the evidence was generated while `1967c03` was HEAD, before the generated
evidence-integrity change was committed as `237e56c`. This closeout records all
four landed revisions without rewriting the machine-readable provenance.

Two review events are part of the acceptance history:

1. The first evidence generator treated pyroomacoustics availability as enough
   to mark room rows passed, retained null room/estimator measurements, and had
   an assertion-free dependency-gated room test. Independent closeout review
   caught this before any S3.6 closeout was written. Revision `237e56c`
   removed availability-as-evidence, made every room and estimator row execute
   its frozen fixture, added real assertions, regenerated all affected
   artifacts under the dependency-capable Python, and left
   `dependency_gated_rows` empty. The final artifacts contain measured values
   and input/output hashes. Expected semantic nulls remain only where a dB
   error is undefined for an analytical zero target or an optional field is
   absent; the corresponding required linear null measurements are real
   `0.0` values.
2. The original estimator ladder required normalized SRP confidence to fall as
   the cardioid signal vanished. Read-only measurement established that this
   was unsatisfiable under the frozen S1 formula: confidence rose from about
   `0.9623` to `1.0` with the former band-limited-noise fixture. Before any
   passing estimator acceptance evidence existed, dated amendment `1967c03`
   replaced that acceptance observable with measured-margin SRP bearing-error
   increase and peak-grid-power drop, and changed the ladder noise to full-band
   white Gaussian noise so the already-frozen GCC endpoint margin remained
   observable. The specification records its amendment entry as `7ba5a1f`,
   the revision from which the documentation-only amendment entered. The S1
   confidence formula, all non-ladder fixtures, and the already-passing pure
   rows were unchanged.

No threshold was adjusted from passing S3.6 evidence. The only acceptance
change was the dated, narrowly scoped estimator amendment made while that row
was blocked and before it had passing evidence.

## Gate results

`outputs/isaac_audio_sensors/S3/S3.6/waveform_directivity_gate.json` reports
`status: "passed"`; all 14 machine-readable criterion rows passed and no row
is dependency-gated. Numerical entries below are maxima unless the criterion
defines an eight-seed median.

| Criterion | Frozen threshold or exact requirement | Measured result | Status |
| --- | --- | --- | --- |
| Frozen configuration/defaults | Exact immutable records, disabled defaults, source/mic resolution, and resolved mode `per_pair_direct_path` | All four record field sets and defaults matched; override mapping immutable; `talker` resolved to `cardioid`, unknown source to `omni`; resolved mode exact | passed |
| Polar families/angles | Maximum absolute scalar error `<=1e-12`; normalized scaled quaternions equivalent; signed rear lobes retained | Maximum error `0.0` across all 16 family/cardinal rows; scaled-quaternion values exact; figure-eight rear `-1.0`, supercardioid rear `-0.26` | passed |
| Cardinal waveform gain | Non-null signed magnitude error `<=0.05 dB`; null gain and RMS ratio `<=1e-6` | Pure maximum `1.928654933106574e-15 dB`, null leakage `0.0`; 48 executed real-room rows maximum `1.9286549331065747e-15 dB`, null gain `0.0`; signs exact | passed |
| Frequency response | Single-pattern Welch H1 error `<=0.25 dB`; cascaded error `<=0.50 dB`; signed 1 kHz transfer retained | Pure single/cascaded maxima `0.14409013359364728/0.288180267187292 dB`; executed real-room single/cascaded maxima `0.13955040728489496/0.27904434940680023 dB`; all within bounds | passed |
| Source/microphone product | Signed scalar/FIR product applied per pair, including one negative, two negatives, null, and simultaneous patterns | Maximum scalar product error `0.0`; retained targets `-1.0`, `+1.0`, `0.0`, and `-0.26`; simultaneous FIR recovery covered by the frequency row | passed |
| Full-convolved-stem insertion | Whole pair stem weighted once before sum; direct and RIR tail both change; frequency response meets `0.25 dB`; four segment midpoint weights applied before overlap-add | Eight pure pair stems had maximum scalar error `0.0`; real reverberant scalar error `0.0`, frequency error `0.1397396451092308 dB`; direct and tail samples changed; four 12,000-sample segments each had `0.0` scalar error | passed |
| Metadata/waveform consistency | Shared-family non-null error `<=0.05 dB`; null error `<=1e-6` linear | Maximum non-null error `0.0 dB`; maximum null error `0.0` linear across 16 family/cardinal comparisons | passed |
| Estimator degradation | SNR strictly decreasing, first two losses `>=5.5 dB`, front/rear loss `>=40 dB`; GCC strictly decreasing and endpoint drop `>=0.05`; SRP bearing-error increase `>=30 degrees`; SRP peak-power drop `>=15 dB` | SNR medians `18.0, 11.9811376591, 5.9640110670, -61.9930377107 dB`: step losses `6.0188623409/6.0171265921 dB`, endpoint loss `79.9930377107 dB`; GCC medians `0.0603492560, 0.0572349415, 0.0496275160, 0.0019543655`, endpoint drop `0.0583948905`; bearing error `0,0,0,63 degrees`; peak powers `0.3619686685, 0.3431333785, 0.2973301181, 0.0039271624`, endpoint drop `19.6459211735 dB` | passed |
| Fail-closed validation | Located typed failure before scheduling, room construction, draw, frame, waveform, or asset; empty partial-output listing | Retained representative matrix 2/2: unknown family and above-Nyquist point raised `ConfigValidationError` pre-synthesis; partial-output listing was empty | passed |
| Zero direction and nulls | Coincident direction resolves to unity; figure-eight 90/270-degree nulls within `1e-6`; all finite | Coincident gain `1.0`; nulls `[0.0, 0.0]`; finite true | passed |
| Diagnostics contract | Exactly `source_pattern`, `mic_pattern`, and `mode`; stable order; no reflection-angle claim | Exact keys and resolved records; mode `per_pair_direct_path`; reflection-angle claim absent | passed |
| Disabled/omni off-state | Eight entry-revision fixtures have exact disabled and explicit-omni premix/frame/waveform behavior and no added effects diagnostic | 8/8 impulse, tone, broadband, silent, file, generated, reverberant, and export cases had exact frame and waveform hashes against `31e0282` | passed |
| Determinism/registry | Fresh pure replays exact; two factories/two runs produce exact room frames and waveforms | Pure output hashes exact; room registry declaration self-test executed; both frame hashes `ee76c4ad30f785dab6bd42747b6622234f458d746c1b7796445de99b4907aaf4` and both waveform hashes `31fa5ba85468c6b051ff8ffe17e810a8c0066c422c55bd67fa63d2e0daca9ca2` | passed |
| Fidelity limitation ledger | Supported claim restricted to the full convolved pair weighted from its direct-path angle; P2 and S3.9 obligations explicit | `per_pair_direct_path` true; direct-arrival-only, reflection-specific angles, and native pyroomacoustics directivity false; P2 deferrals and `core/fidelity.py` S3.9 reconciliation recorded | passed |

The retained invalid-configuration artifact has two representative cases. The
focused test suite covers the broader frozen type, family, id, point,
orientation, mode, backend, and profile matrix. This closeout claims the 14
roll-up rows and retained artifact measurements; it does not present the
two-row JSON as a one-to-one enumeration of every §11 prose variant.

## Directivity model and observable ownership

The supported model is exactly `per_pair_direct_path`: for each
source/microphone pair, the source and microphone signed polar responses and
optional FIRs are selected from that pair's direct-path angle and applied once
to the pair's complete convolved premix stem before source summation. Piecewise
room synthesis applies each segment's midpoint direct-path response before
overlap-add.

This is not direct-arrival-only filtering and is not path-resolved
directivity. The direct arrival and every reflected contribution in a pair's
RIR receive the same response selected from the direct-path angle. Reflected-
path departure/incidence angular directivity is **not modeled**.
Pyroomacoustics-native directional source/microphone objects are not a
fallback and are also not Stage 1 behavior. Reflected-path angular modeling
and pyroomacoustics-native directivities are deferred to P2.

L0/L1 metadata and L2 waveform paths share the source omni/cardioid family and
angle convention where representable. Microphone waveform patterns,
frequency-dependent filtering, signed rear-lobe waveform polarity, and the
room insertion model are L2 behavior; the gate does not claim that L0/L1
produce those waveforms.

## SRP confidence limitation and S3.9 obligation

The eight-seed normalized SRP confidence diagnostic was
`0.9635921293431229, 0.9640566760866303, 0.9642531814832411,
0.9842162004789096` across `0, 90, 120, 180 degrees`. It rose by
`0.02062407113578668` front-to-rear while known-component SNR fell by nearly
`80 dB` and bearing error rose to `63 degrees`.

The frozen S1 formula is clamped
`(peak_power - mean_power) / peak_power`. On noise-dominated input, the mean
steered-grid power can approach zero while the finite-grid maximum remains
positive, driving this normalized value toward `1.0`. It is therefore not a
valid localization-confidence indicator on noise-only or effectively
noise-only input. This diagnostic is not an S3.6 acceptance observable and
must not be described as localization evidence.

S3.9 must restate this limitation in the published fidelity envelope and
reconcile `core/fidelity.py` plus the public claim/evidence map with S3.6's
actual narrow L2 envelope. The older S0 gate-row phrase "confidence
degradation" is satisfied only through the dated amended degradation
observables—known-component SNR, GCC peak proxy, SRP bearing error, and
absolute peak grid power—not through normalized SRP confidence.

## Tests, environment, and live-coverage boundary

- Pre-S3.6 `make test` baseline at `31e0282`: 1008 passed, 0 failed, 76
  optional-dependency skips.
- Post-S3.6 `make test` at `237e56c`: 1044 passed, 0 failed, 77
  optional-dependency skips: 36 additional passing tests and one additional
  collected skip.
- The additional skip is the pyroomacoustics-gated real-room directivity test
  in the base `.venv`; the dependency-capable focused suite executes that
  test rather than treating its availability as a pass.

The post-S3.6 total was rechecked during this documentation-only closeout. The
pre-S3.6 total is the orchestrator's recorded run at the named revision.

Acceptance evidence was generated with the recorded Isaac Sim/Kit Python
executable `/home/pacquadr/isaacsim/kit/python/bin/python3`: Python 3.12.13,
NumPy 2.5.0, and pyroomacoustics 0.10.1 on Linux. Isaac's Python supplies the
pinned room-acoustics dependency; no `SimulationApp` was launched. The gate is
pure/offline CPU evidence and makes no live Isaac stage, renderer, GPU,
microphone, robot, hardware, or calibrated sim-to-real claim.

The roll-up retains generic `.venv` command spellings, while
`evidence_environment.json` records the actual dependency-capable executable
and module origins used for the passing artifacts. The current base `.venv`
does not contain pyroomacoustics and therefore skips, rather than passes, the
ordinary optional real-room test. A direct focused rerun under the recorded
Isaac Python with unrelated third-party pytest plugin auto-loading disabled
passed 37/37 tests during closeout verification.

No live scenario is required for S3.6. Moving/rotating mounts, multi-source
imbalance, and live scene stress belong to S3.8 and cannot retroactively alter
this protocol.

## Evidence artifacts

All paths below are relative to
`outputs/isaac_audio_sensors/S3/S3.6/`. SHA-256 values are copied from
`waveform_directivity_gate.json`; all 28 listed hashes were checked against
the files at closeout.

| Artifact | SHA-256 |
| --- | --- |
| `cardinal_pair_stems_sha256.json` | `4357ee8787d90e7aefb20dbd78018523816795801671c46c80a8737965dc435e` |
| `cardinal_waveform_gain.json` | `d0dc2ee1ba941670c7bee9591b9b6324ccd8e89deee3d0e1a8879e84790ab4bc` |
| `directivity_config_contract.json` | `2674bc4506ed3576e868e12aad302d626bd57752f526a937b19a585df3cc620b` |
| `directivity_diagnostics.json` | `82973f06a0041794e25c5afb8915857371b7a4433ab8deb9dde021e8566ac9d8` |
| `directivity_edge_case_matrix.json` | `163b81e1d05b3cc6e4baf05c190742e3d054a4f98135f907ad923a6f792283bf` |
| `enabled_replay_sha256.json` | `b96e48ce12b9785954e8968da36ee0dbff5c5d144ac99857f3659498b97de62a` |
| `estimator_confidence_ladder.json` | `2d25d909d22d3f74ff7e920f343e5da61d1052d9a6d9d5133eeee49b91a69a9b` |
| `estimator_confidence_overlay.png` | `0af19d6372ac884ead3aa1c7ff44b8793f17d1d7065a4d5e83716f0bae57e461` |
| `estimator_input_sha256.json` | `519a8733ebb775f7f545428292ce74e6c93507675befc934896ef2dfcb46da9c` |
| `evidence_environment.json` | `91de8cb99089d33b5579bb05eb19582dc2ef6fcf33457b2ebc2be55ac483c9e4` |
| `fidelity_reconciliation.json` | `5f7feb6926f80753a8d39d3b5c9a6f690921d35e484b81e366ce4c32b5901a27` |
| `frequency_response_error.png` | `984197f1931d034cf827178b086cb6f0acdec4d6e9d506f1ac7ca757a23c34da` |
| `frequency_response_overlay.png` | `a90faa814e4bce02dae7bebd4239caebf871a8e24b5fd68dff2fc3db6ef22907` |
| `frequency_sweep_welch.json` | `a7723a0040978f7277cf69f46938a54c25f50986ea37871e3ca07abdb9047087` |
| `full_contribution_sha256.json` | `60892f09eee4e1d1eccf5ef74e63b7de3d573cd915e64777346cfda9d2399fa4` |
| `invalid_directivity_config_matrix.json` | `46c6b07536e9092d00b48f7e4067930a88e8fe5f9caa8ebe21702347c6865c98` |
| `metadata_waveform_consistency.json` | `cd626697729e4424b5a4c0c717b8666263f24c64f643adb25cb4d9462529dd2c` |
| `off_state_frame.json` | `92218e1e759e0dc82b3ed71c5605f87d3f20ca6d128f6f8f903a31f4fa63490c` |
| `off_state_golden_sha256.json` | `94b9a5f7db54834d92de2ae8b187eddb565bbc3de66dd508bd32e8cda11c0ced` |
| `off_state_waveform_sha256.txt` | `21b9fb828dc0904a59b131e54d8b316a6816a7e9896a6e3e132c00f689d9caaf` |
| `partial_output_listing.txt` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `per_pair_insertion_trace.json` | `004e7fcc87db9b82a63bf88ce18977b29d5a2e5e0351af42cf01a56eb8ea7ffa` |
| `polar_cardinal_results.json` | `5034287f7eb0a5c9c5b8a5b5b4a1021928c7fdcde638a0d779e0fe13aa1b1507` |
| `polar_response_overlay.png` | `1bf587e787e3eea875a979ca5798a16cef0d6526913a7dfcf12a6391b6c4f113` |
| `registry_determinism_directivity.json` | `730c0f4fb264f3bd8757e1ad44b098d0374d05c53051e00b8b07777ce78e3e2e` |
| `rir_tail_weighting.json` | `6bde2db195afa8e810c01da661a5bbf53da7ba47a3d5a3b2099ec6325d108bba` |
| `source_mic_pair_stems.npz` | `9b9d2892f1179c97dd154c557426bed96f9f25139f75708128085c1b131b6afb` |
| `source_mic_product_matrix.json` | `76aadd114c6475e20443157b59609f33fdc7c00407ac509b6288e0268ae7fc51` |

`waveform_directivity_gate.json` is the machine-readable roll-up and does not
self-report a SHA-256 for itself.

## Reproduction commands

The gate records these commands:

```bash
.venv/bin/pytest -q tests/test_effects_directivity.py
.venv/bin/python scripts/s3_6_evidence.py
make test
make lint
```

The L2 room rows must be generated with a Python environment containing the
recorded pyroomacoustics 0.10.1 dependency. Dependency absence may skip the
ordinary optional room test but cannot produce passing S3.6 acceptance
evidence.

## Defects found and fixed during the gate

- The original normalized-SRP-confidence drop was measured unsatisfiable under
  the frozen estimator formula. Dated amendment `1967c03` replaced only the
  blocked ladder fixture/observables before any passing estimator evidence;
  the exact measurements, rationale, and S3.9 obligation remain in the frozen
  specification and this closeout.
- The initial generator's availability-as-pass, null measurement, and
  assertion-free room-test defect was caught by independent closeout review
  before any closeout was written. Revision `237e56c` made the fixtures and
  assertions real and regenerated the complete passing artifact set. No
  former placeholder is accepted as evidence by this closeout.

## Limitations carried forward

- `per_pair_direct_path` weights each complete convolved pair stem using its
  direct-path angle. It does not model reflection-specific departure or
  incidence angles and must not be called path-resolved directivity.
- Pyroomacoustics-native directional source/microphone objects are not used;
  native directivities and reflected-path angular modeling are deferred to P2.
- Normalized `srp_phat_confidence` can rise toward unity on noise-dominated
  input. It is diagnostic only for this ladder, is not localization evidence,
  and must be restated and reconciled by S3.9.
- The estimator ladder is a fixed pure fixture with retained clean/noise
  components and eight seeds. It does not relabel scheduled-known-source
  confidence as mixture-noise-aware or prove moving/multi-source behavior.
- `core/fidelity.py` still requires S3.9 reconciliation before the public
  fidelity ladder can describe the passing S3.6 envelope accurately.
- No live Isaac, GPU, robot, physical microphone, hardware, or calibrated
  sim-to-real validation is claimed. S3.8 owns moving/rotating and
  multi-source stress.

## Input contract for S3.7

S3.7 consumes the passed S3.2 time-gap/intra-window-motion contract together
with this passed S3.6 directivity contract. It inherits per-segment midpoint
geometry, per-pair-before-sum insertion, signed patterns, optional frequency
responses, hard off-state identity, deterministic ordering, typed fail-closed
behavior, and the `per_pair_direct_path` fidelity boundary. Materials,
dynamic-room cache invalidation, and occlusion must preserve waveform/RMS/
diagnostic/export agreement without claiming reflected-path angular
directivity, diffraction, or pyroomacoustics-native directivity unless a
separately reviewed later design and evidence explicitly add them.

## Confidence remediation (2026-07-18)

This dated section preserves the original closeout above and supersedes only
its SRP-confidence limitation, proxy-criteria amendment, and associated
carry-forward obligation. The noise-aware formula and decision were frozen in
`docs/development/specs/s3_channel_effects_chain.md` §9.6.2 by commit
`bb2efe7` (prospective specification entry `5bfa67e`), implemented by
`1e6e18f`, and regenerated evidence records
`implementation_revision=497c0fffdae2f77b33905b64c5de41b906c2c0c7`.
The schema remains unchanged, and confidence remains an uncalibrated
reliability ordering rather than a probability.

The original acceptance criterion—“estimator tests show the expected confidence
degradation”—is now met directly. The authoritative S3.6 gate's
`estimator_degradation` row is `passed`; its eight-seed median
`bearing_confidence` values at `0°,90°,120°,180°` are
`0.05814612482686094, 0.05514319161396962, 0.04778229697397164,
0.0006422450143033353`. They are non-increasing, meet the `>=0.050` front
floor and `<=0.005` rear ceiling, and drop by
`0.0575038798125576 >=0.040` front-to-rear. The retained corroborating SNR,
GCC, bearing-error, and peak-power criteria also pass; they no longer stand in
for confidence.

The earlier `1967c03` amendment (entry identifier `7ba5a1f`) remains recorded
above as history but is superseded where it replaced confidence degradation
with proxy observables and treated the saturating formula as immutable. The
development plan §6.6 `S3.6` and S0 acceptance `S3.6` wording are therefore
satisfied as originally written. No governing-document amendment is required.
The regenerated ladder artifact hash is
`c1513fd55ce701c06b266f4e313bc387e39b6f5d003294bd3c531c2e75b1d79b`;
the prior hash in the original table remains revision-specific provenance.
