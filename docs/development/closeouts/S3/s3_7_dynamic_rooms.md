# S3.7 closeout - materials, dynamic rooms, and occlusion

Status: **passed** (2026-07-18). Entry revisions: predecessor baseline
`7e29d4f`; frozen specification and recorded evidence-generation HEAD
`a587df1`; landed implementation/live-gate revision `96b8203`. Predecessors:
`docs/development/closeouts/S3/s3_2_time_motion.md` and
`docs/development/closeouts/S3/s3_6_waveform_directivity.md`.

## Frozen-tolerance provenance

The complete S3.7 material-provenance, acoustic-state refresh,
cross-output-consistency, fixture, tolerance, and evidence contract was
committed prospectively in
`docs/development/specs/s3_acoustic_state_invalidation.md` at `a587df1`,
before implementation or acceptance evidence. That specification records
`7e29d4f` as the passed-predecessor entry baseline. The specification is
unchanged from `a587df1` at this closeout.

The first implementation attempt reported **BLOCKED**: the existing
`RoomAcousticsSpec.absorption` surface could not accept material ids, and the
required `extension.py` integration was treated as outside the initial write
scope. The orchestrator then granted a narrow scope expansion. The absorption
union is an additive configuration surface, not a change to the frame
contract; the frozen specification already required
`float | dict[str, float] | str`, assigned stage/room and extension integration
behavior, and named `src/isaac_audio_sensors/isaac/extension.py`. The expanded
scope was limited to those named integration points. No coefficient,
tolerance, fixture, criterion, frame contract, or passing evidence was changed
to resolve the block. This process event is part of the acceptance history and
is recorded rather than hidden.

`dynamic_rooms_gate.json` retains both `design_revision` and
`implementation_revision` as the full `a587df1` hash. The landed implementation
and live-gate revision is `96b8203`. The generated output tree is not stored in
that commit, and the roll-up field reflects the pre-commit HEAD under which the
implementation evidence was generated rather than the later landed
implementation revision. This closeout preserves that machine-readable
provenance discrepancy; it does not relabel `a587df1` as the implementation
commit.

No frozen threshold was adjusted after acceptance evidence existed.

## Gate results

`outputs/isaac_audio_sensors/S3/S3.7/dynamic_rooms_gate.json` reports
`status: "passed"`; all 14 machine-readable rows passed, with empty
`failed_rows`, `dependency_gated_rows`, `live_artifacts_pending`, and no null or
availability-only substitute accepted as a measurement.

| Criterion | Frozen threshold or exact requirement | Measured result | Status |
| --- | --- | --- | --- |
| Material source/provenance | Exact seven measured absorption rows, nine nominal rows, pyroomacoustics `0.10.1` source, citation, tags, and database hash | 7 measured plus 9 nominal rows exact; Vorländer citation retained; installed and frozen database SHA-256 both `1249f0cfdcd4598cf98ec9be05230f910e53aa1da4861d7fe3f88de23a24e0e0` | passed |
| Material resolution/fail closed | Exact ids, aliases, precedence, coefficient families, typed rejection, and no partial publication | 26/26 retained resolution cases passed; 4/4 retained failures rejected unknown id, missing transmission, seven bands, and unknown USD id; partial listing contains the empty list `[]` | passed |
| Clear/blocked/partial/material | Exact metadata for four fixtures; six-band maximum error `<=0.05 dB` | Clear, all-blocked concrete, right-only wood, and all-blocked glass maps/factors exact; maximum band error `3.552713678800501e-15 dB` | passed |
| RMS/waveform/export | Maximum RMS error `<=1e-12`; FLOAT WAV must equal the float32 in-memory conversion with exact rate/channel/count | Maximum RMS error `0.0`; float32 decode exact; 4 channels, 48,000 samples at 48 kHz, subtype `FLOAT` | passed |
| Determinism | Fresh-run float64 mixture, frame, and raw WAV bytes exact; clear endpoints exact | Mixture hashes both `69db7809e9730073ff413c1f9f8a8d24156a0241866f734da444ae5059e2cc00`; frame/WAV exact; clear endpoint and mixture identity true | passed |
| Recompute-always baseline | No acoustic-result cache; `P=1` requires 1 room/1 RIR call and `P=8` requires 8/8 | `acoustic_result_cache_present=false`; observed room/RIR counts `1/1` and `8/8` | passed |
| Dynamic room/material | Every planted origin, dimension, or absorption change must change the state hash, RIR/output, and exact reason | 3/3 mutations changed room hash and waveform; reasons were `room_geometry_changed`, `room_geometry_changed`, and `material_changed`; real pyroomacoustics baseline/dimension/material renders were distinct | passed |
| Moving source/array | Authored and observed poses exact; geometry-dependent output changes without forced full discovery | Source `(4,0,1)->(3.5,0,1)` and array `(0,0,1)->(0,0.25,1)` observed exactly; both frames changed; full discovery not required | passed |
| Moving occluder/staleness | Five exact maps/factors; affected flat attenuation error `<=1e-6 dB`; clear endpoints identical; planted stale result rejected | Pure trajectory `clear -> right -> all -> left -> clear` exact; maximum attenuation error `0.0 dB`; clear endpoint identity and stale-transition rejection true; `occluder_moved` recorded on all four transitions | passed |
| Stage-cache taxonomy | Exact ordered reason/actions: geometry and material rediscover; occluder movement recompute-only | Exact trace observed; simultaneous geometry/material reasons retained; `occluder_moved` left discovery clean and used `recompute_only` | passed |
| Edge/failure matrix | Unknown/missing material, malformed/negative bands, endpoints, degenerate rays, OOB, anchor loss, multi-hit, and cap behavior fail or resolve exactly as frozen | 4/4 retained JSON cases rejected unknown material, missing transmission, seven bands, and negative transmission; inherited endpoint/multi-hit coverage passed in the named test suite | passed |
| Off-state/predecessors | Pinned `7e29d4f` L0/L1 frame exact with no `acoustics_state`; scalar-room compatibility exact; S3.2/S3.6 regressions pass | `acoustics_state` absent and bytes exact; repeated frame hash `ea15aa9d261f38bfaab520ce62712937ad766b5794c82dd79d5cbe38071842ef`; predecessor rerun 54/54 passed | passed |
| Real dependency | Execute real material/dynamic-room rows under pyroomacoustics `0.10.1`; availability alone and null measurements cannot pass | Real dependency origin recorded under Isaac Python; database hash exact; baseline, dimension, and material renders all executed with distinct hashes/outputs | passed |
| Live moving occluder | Exact five live maps/factors; affected `12.0 +/- 0.5 dB`, unaffected `0 +/- 0.5 dB`; RMS consistency, one occlusion recomputation/frame, four reasons, no pose-only rediscovery | At wall y `[0.25,0.08,0,-0.08,-0.25]`, factors were `[0,0.25,1,0.25,0]` and maps were `clear,right,all,left,clear`; affected attenuation ranged `12.0` to `12.000000000000002 dB`, unaffected residue at most `1.9286549331065747e-15 dB`; all assertions true, full discovery stayed `1`, and `occluder_moved` appeared on four transitions | passed |

The retained edge artifact enumerates four representative explicit failures;
the broader endpoint, degenerate-ray, out-of-bounds, anchor-deletion,
multi-hit, and cap matrix is test-backed and is not overstated as four JSON
rows.

## Cache and material honesty boundaries

The S0 requirement that caches never return stale acoustics is satisfied by
construction through the frozen recompute-always baseline. No cache of RIRs,
premixes, rendered waveforms, or occlusion records exists; there is no
acoustic-result cache. Every successful room simulation constructs and
computes the current room once per segment, and every successful live capture
recomputes current scene occlusion. `StageAudioCache` caches discovery state,
not acoustic results.
Future acoustic-result memoization and its complete canonical key are outside
S3.7 and would require a separately reviewed design and evidence gate.

Measured material evidence covers absorption only. The seven measured records
come from the pyroomacoustics `0.10.1` material database, cite Michael
Vorländer's *Auralization*, and bind to database SHA-256
`1249f0cfdcd4598cf98ec9be05230f910e53aa1da4861d7fe3f88de23a24e0e0`.
That database contains no measured transmission table. Every measured table
row therefore has `transmission_db` absent, and requesting measured
transmission fails closed. The nine compatibility transmission presets remain
explicitly nominal; neither a related name nor a measured absorption citation
promotes them to measured data.

Occlusion remains direct-ray/per-surface transmission. It is **not
diffraction**, edge bending, portal propagation, reflected-path occlusion, a
phase-through-material model, or a complete wave solver. Room propagation
remains the approximate pyroomacoustics shoebox/image-source path. Passing
simulation evidence is not calibrated real-world or sim-to-real material
fidelity.

## Live attenuation trajectory

The live summary retained the required sequence and the causal invalidation
diagnostics:

| Wall y (m) | Blocked microphones | Factor | Measured attenuation by `(front, right, rear, left)` dB | Refresh reason |
| --- | --- | --- | --- | --- |
| `+0.25` | none | `0.0` | `(0, 0, 0, 0)` | none |
| `+0.08` | right | `0.25` | `(-1.93e-15, 12.000000000000002, -9.64e-16, 0)` | `occluder_moved` |
| `0.00` | front, right, rear, left | `1.0` | `(12.000000000000002, 12, 12.000000000000002, 12)` | `occluder_moved` |
| `-0.08` | left | `0.25` | `(1.93e-15, 0, 1.93e-15, 12)` | `occluder_moved` |
| `-0.25` | none | `0.0` | `(0, 0, 0, 0)` | `occluder_moved` |

The fully blocked state therefore met the exact requested check of
`12.0 +/- 0.5 dB` on all four microphones. Each transition named
`rig_front:speaker_front` in `changed_occlusion_pairs`; each frame recorded
`occlusion_recompute_count=1`. The summary's waveform/RMS consistency,
blocked-map, attenuation, four-transition, and cached-discovery assertions
were all true.

## Tests and environment

- Pre-S3.7 orchestrator-measured `make test` at `7e29d4f`: 1044 passed, 0
  failed, 77 optional-dependency skips.
- Post-S3.7 orchestrator-measured `make test` at `96b8203`: 1065 passed, 0
  failed, 77 optional-dependency skips: 21 additional passing tests and no
  change in skips.
- The retained S3.2/S3.6 focused regression run passed 54/54 tests under the
  dependency-capable interpreter.

Pure and real-room acceptance evidence used the recorded Isaac executable
`/home/pacquadr/isaacsim/kit/python/bin/python3`: Python 3.12.13, NumPy 2.5.0,
pyroomacoustics 0.10.1, package 1.10.0, with soundfile available, on
Linux 6.8.0-136-generic x86_64/glibc 2.39.

The live moving-occluder run used that same Isaac Python and platform in
headless mode, with NumPy 2.5.0, pyroomacoustics 0.10.1, and soundfile 0.14.0.
It is live Isaac/PhysX simulation evidence, not a live robot, physical
microphone, calibrated room, hardware, or sim-to-real validation claim.

## Evidence artifacts

All paths below are relative to
`outputs/isaac_audio_sensors/S3/S3.7/`. All 48 SHA-256 mappings copied from
`dynamic_rooms_gate.json` were checked against the retained files at closeout;
none was missing or mismatched.

| Artifact | SHA-256 |
| --- | --- |
| `acoustic_determinism_sha256.json` | `8bf279203f6079fe0b26722b87cf53710b713f6c5d5d616e099b2f67c008cd34` |
| `acoustic_edge_case_matrix.json` | `9a853b11414f9011be508f42c7d5e94e73f1847f1fa6ca33c94617b290879f82` |
| `acoustics_off_state_sha256.json` | `63aa5dbb1e5d4520f4fd77230e05391ae5943fefa0c2eef68afe4060bf5d7c09` |
| `cache_invalidation_results.json` | `adf04756cac0ec2789cedfd26114de89b987921af4f016bad97be7875c4497d6` |
| `cache_invalidation_trace.jsonl` | `3d4181206f6e1417ec3672f074545f93cc1feff1fcce77182194554cbf402649` |
| `dynamic_room_results.json` | `eac8d6ac6ace9dcf62e7eaf31bd94c963e4aa8cf390e898c00d3b2779237c6e1` |
| `evidence_environment.json` | `a438a965627d88f30abd36e735681bd9cae334023341f0f38636c168d91735c0` |
| `export_waveform_sha256.json` | `8d6eaac1f1334a8ae5fdcc528fe739906d339a4c2baef3329e5e64385c4ec16f` |
| `fixture_audio.wav` | `7dfdc930abe0224ef9bb1fdcaf41406375a65324452d03c6500629a840b08068` |
| `fixture_audio_internal/fixture_audio.wav` | `7dfdc930abe0224ef9bb1fdcaf41406375a65324452d03c6500629a840b08068` |
| `identical_frame_results.json` | `248dc4046417157fdcd0a1a3241992e30af3917441402d390814c7972b8b2957` |
| `live_moving_occluder.log` | `a441d37399c9944e1a4b8d19888697c0187b45b2599308191d75267a0dfd874d` |
| `live_moving_occluder_environment.json` | `a6332c6ca8e1540856501228f6b6ccbc5a69a8cfc210614a872fd496bc021083` |
| `live_moving_occluder_frames.jsonl` | `c7f57b515af0055028492a58ad28da738910a9e1d731ddf917863916bb04f915` |
| `live_moving_occluder_stage.usda` | `76cf55b86041c3d941d0687e8e9837d1480e40f1bf820ce85a3af56d1afee6d0` |
| `live_moving_occluder_summary.json` | `890b69834e417c387cb95d71c8fe62dd37497a3fb2a078d36e06cdccda55e732` |
| `live_moving_occluder_viewport.png` | `8898fb01ed6ea05583328c99cc604c9bb0ca258ecfc2abaa14eb5374f4449b8b` |
| `live_moving_occluder_wav_sha256.json` | `62d3055b8f1f8bda9330e7b26bdea9165580055a4c35663b654b7b073bfc8dd4` |
| `live_moving_occluder_wavs/observed_00.wav` | `016ab207a9bb9e1fd2ef6278a4b035f04a5511365adb730161d7b21c8eed6eb7` |
| `live_moving_occluder_wavs/observed_01.wav` | `8ad82cdfa89294bbf233f6041bf5361309f8f721acd38fd4a19fbfc44631356b` |
| `live_moving_occluder_wavs/observed_02.wav` | `b4578e2fa56fea0f66b59f3787c0810a39c2fc22a7b8c07210e8af1b5cebc986` |
| `live_moving_occluder_wavs/observed_03.wav` | `d56d3a6bf47fec33289249f0198665a12a3c3bf72a079ef83649e172a80b5ed3` |
| `live_moving_occluder_wavs/observed_04.wav` | `039466b355ad5f8e19c766de28905e0c6e078e453a930eb6fc20d06a42ce24f5` |
| `live_moving_occluder_wavs/reference_00.wav` | `016ab207a9bb9e1fd2ef6278a4b035f04a5511365adb730161d7b21c8eed6eb7` |
| `live_moving_occluder_wavs/reference_01.wav` | `842d75a06719ffc5ccfe43724438e3a589e400df7110e20b7ed45895ef9d4519` |
| `live_moving_occluder_wavs/reference_02.wav` | `93c51704e5c48a2bba764da716105779a39d0d52acfa8f30562f3f98d5eac14d` |
| `live_moving_occluder_wavs/reference_03.wav` | `f94127c3dc7d4213827fc884f2364eb5f640423bebe5eceb8448360b75ea71b8` |
| `live_moving_occluder_wavs/reference_04.wav` | `039466b355ad5f8e19c766de28905e0c6e078e453a930eb6fc20d06a42ce24f5` |
| `material_failure_matrix.json` | `68837f47d81d9e334fd1b35cf7b30bde9fa0aa7eb859bcf609a19d268fe747b6` |
| `material_resolution_matrix.json` | `91d10f58138e6f3e37fa592061dd87f4edc0466f615e0e568a70d0ec64018073` |
| `material_table_provenance.json` | `4c03a39d8e6b5745c541489c02caf25f8394eab42faeae63c1aceb048ac48471` |
| `material_table_rows.json` | `b5fbabf9643f636f92ea16d25d77504682d48a461c6b7091891948efa1b75583` |
| `moving_endpoint_results.json` | `30b95d56983887ef83019921413d86cd00b950ec4e3614e1d2fa229a91fca964` |
| `moving_endpoint_trace.csv` | `5f5675b0a99887ddd5033b086562ad7145c8d5fafa8dec158e1ee7cb4e93dc3d` |
| `moving_occluder_results.json` | `ebf58dd7b541dd68ddc6176ddbff0cedceae47d8f5980a5c11b9462fcd849383` |
| `moving_occluder_trace.jsonl` | `3522b6546e93bef2b4edcda4fa5830ebb5cc7c66b3c4a7fa08fb1887ebef48c6` |
| `occlusion_band_trace.csv` | `defe09d50b128579b6d5a8887d8353d1e4650c627cde166d434bc168f0d42141` |
| `occlusion_consistency_results.json` | `34165b0d6b3e9e9364321daaa1c7a3713b51577f91bdd8660950d48e630637eb` |
| `occlusion_fixture_waveforms.npz` | `0b95e4caf42061cbe1d7eaccacc09f21d96762bedbff9d0bea6e2212bacd90e3` |
| `partial_output_listing.txt` | `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570` |
| `real_room_material_results.json` | `10da5720b2aff6d9bd14c8f92aea23bb81f31fda40c368a4198e267b3795b7ba` |
| `recompute_baseline_results.json` | `b8a1a048db675c07b3b19a204758a3f1f923503da5e452870686025bbcf7c839` |
| `recompute_call_trace.csv` | `b38258a4323a11bea7c4d090ca71339d681ee36e53e60372f1af3488071fa157` |
| `room_rir_sha256.json` | `e65cdc662544a95a14aa02af14afac9b8c5a379a8ba0399169b4fd76ce81d9ba` |
| `room_state_trace.jsonl` | `f0d2f56024e912ddc65df57cee47164bade3bf380c69ed8a760c623f531375d3` |
| `s3_2_s3_6_regression.json` | `504aacc69dbc02ab53ffc273a302388480a46ada3b6b4119e9280dafa5c5887e` |
| `staleness_detector_results.json` | `0a9d69fdcb5a94cc2493b27486eac60046905b560d5806e243c8c2f91c5cca8d` |
| `waveform_rms_export_results.json` | `7c62ebd1e3cd644e09a913d002064d75a0b7c422eea9d0ac978825f8530f33a5` |

`dynamic_rooms_gate.json` is the machine-readable roll-up and does not
self-report a SHA-256 for itself.

## Reproduction commands

The roll-up records:

```bash
.venv/bin/python scripts/s3_7_evidence.py
.venv/bin/pytest -q tests/test_acoustic_materials.py tests/test_dynamic_rooms_invalidation.py
make test
make lint
```

The live row is produced through the frozen public
`make live-isaac-occlusion` path. Real room/material acceptance requires the
recorded dependency-capable Isaac Python; dependency absence may skip an
ordinary optional test but cannot produce a passing real-dependency or live
row.

## Defects and process events during the gate

- The first implementation attempt correctly reported a scope block around
  the required material-id absorption union and `extension.py` integration.
  The orchestrator granted only the frozen spec's named additive config and
  integration surfaces. No tolerance or acceptance observable changed.
- The roll-up's `implementation_revision` remained the generation-time
  `a587df1` HEAD rather than the landed `96b8203` revision. The evidence
  content, 14 passed rows, and 48 file hashes were retained; this closeout
  records both revisions and the field discrepancy rather than rewriting the
  artifact.

## Limitations carried forward

- No acoustic-result memoization exists or is validated; later memoization
  requires a separately frozen complete key and stale-result gate.
- Measured materials cover seven pyroomacoustics absorption records only.
  Measured transmission is absent and fails closed; compatibility
  transmission and explicit USD values remain nominal.
- The coefficient grid has six bands from 125 Hz through 4 kHz. Source 8 kHz
  absorption values are provenance only and are not applied.
- Occlusion is direct-ray/per-surface transmission, not diffraction or a
  complete propagation solver, and it does not alter RIR reflection paths.
- Room propagation remains the approximate pyroomacoustics shoebox/
  image-source model with inherited out-of-bounds constraints.
- S3.6's `per_pair_direct_path` limitation remains unchanged; reflected-path
  source/microphone angles are not modeled.
- The gate isolates one known source/pair for causal consistency. Moving-mount,
  multi-source imbalance, endurance, performance, and resource stress belong
  to S3.8.
- No physical robot, microphone, calibrated room/material pack, hardware, or
  sim-to-real claim follows from the passing simulation fixtures.

## Input contract for S3.8

S3.8 consumes the complete passed S3.1-S3.7 chain and the supported backend
matrix. It inherits S3.7's recompute-always/no-result-cache boundary, exact
reason taxonomy, material provenance and fail-closed rules, six-band limits,
cross-output consistency, direct-ray transmission limitation, and S3.2/S3.6
motion/directivity contracts.

Before any S3.8 stress acceptance evidence is generated,
`docs/development/specs/s3_stress_matrix.md` must prospectively freeze the
supported/unsupported combination matrix, fixtures, measurements, limits,
resource bounds, and failure behavior. Unsupported combinations must be
recorded and excluded from claims rather than silently downgraded. That stress
specification is the next required input and does not exist at this closeout.
