# S3 phase closeout - Dynamic acoustics required by SquadBot

Status: **PASSED** (2026-07-18). Entry revision `7163360` (S3.0
scaffolding on `main`); exit revision `36af292`, v1.10.0 line. Predecessor
closeout `docs/development/closeouts/S2_closeout.md` (S2 exit gate met at
`fbe6ce7`).

## Exit gate statement

**The S3 exit gate is met:** all physical effects required downstream by the
planned bench, moving-robot, hallway, occlusion, and multi-source scenarios
have measurable behavior, compatibility off-states, additive diagnostics,
explicit supported/unsupported combinations, and honest fidelity and
performance limits. The accepted envelope is bounded simulation behavior,
not calibrated physical or sim-to-real fidelity: occlusion is direct-ray/
transmission attenuation rather than diffraction, and optional diffraction
or richer propagation remains deferred to P2.

## Subphase closeouts (all passed)

| Subphase | Closeout | Key evidence |
| --- | --- | --- |
| S3.0 scaffolding | no acceptance closeout; entry `7163360` | opened the v1.10.0 release line, synchronized the then-known release surfaces, and installed the S3 execution tracker |
| S3.1 pose-derived velocity | `S3/s3_1_pose_velocity.md` | 14/14 gate rows; raw velocity maximum error `7.105e-14 m/s`; the live run retained 5 TDOA frames and 1 room re-render, with exact unity Doppler on the teleport frame |
| S3.2 time gaps and motion | `S3/s3_2_time_motion.md` | 14/14 rows; exact 16,800-sample preserved gap; live `P=8` boundary residual `6.834e-8 <= 2e-6`; reliability 5/5 |
| S3.3 channel response | `S3/s3_3_channel_response.md` | 10/10 rows; gain error `1.776e-15 dB`, delay error `0.05697 sample`, and Welch response error `0.05423 dB`; hard off-state exact |
| S3.4 seeded noise | `S3/s3_4_seeded_noise.md` | 18/18 rows; PSD error `0.9623 dB`, RMS error `0.01280 dB`, drift-slope error `0.02901 ppm`, and deterministic isolated streams |
| S3.5 electronics | `S3/s3_5_electronics.md` | 16/16 rows; quantization-power ratio `1.0000076`, AGC settling error `0.008737 dB`, exact clipping counts, and hard off-state exact |
| S3.6 waveform directivity | `S3/s3_6_waveform_directivity.md` | 14/14 rows with no dependency-gated row; 48 real-room cardinal cases passed; the supported mode is exactly `per_pair_direct_path` |
| S3.7 dynamic rooms | `S3/s3_7_dynamic_rooms.md` | 14/14 rows; 7 measured absorption and 9 nominal transmission rows kept distinct; live clear/partial/blocked trajectory recovered `12 dB` attenuation without stale acoustics |
| S3.8 stress | `S3/s3_8_stress.md` | 16/16 rows and all 55 matrix cells accounted for (34 supported, 14 explicit unsupported, 7 N/A); 4,096-frame pure resource gate and live stress passed |
| S3.9 fidelity envelope | `S3/s3_9_fidelity_envelope.md` | 10/10 claims; all 53 mapped fixture/off-state artifacts hash-verified; 43 validating and 14 off-state test/command ids retained |

## Final phase verification

- Pure battery, orchestrator-measured across closeout revisions
  `9581deb..36af292`: **1100 passed, 0 failed**, 77 documented
  optional-dependency skips; lint clean; version synchronization OK at
  1.10.0; schema export produced no diff; dataset fixture validation was
  clean for 3 episodes / 2 shards / 7 frames; configuration validation and
  import smoke both passed.
- Live regressions at the closeout revision all passed:
  `make live-isaac-sim-audio`, `make live-isaac-occlusion`,
  `make live-isaac-lab-audio-gpu`, and `make live-reliability`. The Isaac Lab
  effects-off p95 was `11.110301013104618 ms` against the frozen `20 ms`
  budget; all five reliability scenarios passed.
- The S1.8 installed-artifact consumer gate was rerun against the freshly
  built 1.10.0 wheel and passed all 8 external consumer cases. The isolated
  graph exports were byte-identical, the consumer checkout remained clean,
  and the generic boundary scan had zero hits. This retained the original
  S1.8 base-artifact scope; the acoustic pack was `not_requested` and is not
  claimed as exercised by this rerun.
- The wheel, sdist, self-contained Kit archive, and Linux x86_64 cp312
  acoustic pack were built and audited. The pack used the S1 locked
  wheelhouse. `dist/SHA256SUMS` records:

  | Artifact | SHA-256 |
  | --- | --- |
  | `isaac_audio_sensors-1.10.0-py3-none-any.whl` | `34dc3af065e5dc038ebd7934fd8da82b613b33e6cf6c21065e0acfac0b6c4e25` |
  | `isaac_audio_sensors-1.10.0.tar.gz` | `60a445843006002ac339aede0556780b5778109975c9fd806678f4258ff9e6db` |
  | `kit/isaac_audio_sensors.omni-1.10.0.zip` | `ccd3574812788f6f724b82b830801eeb81c1547897bdc9056e32c52434b58aa7` |
  | `packs/isaac_audio_sensors_acoustic_pack-l2l3-1.10.0-linux_x86_64-cp312.tar.gz` | `5b2002a481213e12558ef9d4612d32352f3e4d8b9e4f4b779fc77f34d946b070` |

- The phase-final artifact build found two release-surface defects. Revision
  `8d2fa51` removed a machine-local path token from the distributed S3.8
  evidence script after the sdist audit rejected it and synchronized
  `pack.toml`'s `pack_version`; revision `36af292` synchronized the separately
  embedded `artifact_name`. The complete artifact and verification battery
  passed after both fixes.

## Execution record

Claude orchestrated sequential, bounded Codex runs for prospective design/
specification, implementation and evidence, independent closeout review, and
targeted live-gate or micro-fixes. Diffs were reviewed against pinned entry
revisions, the orchestrator ran the final gates independently, and blocked
write scopes in S3.2 and S3.7 were expanded only to integration surfaces
already required by the frozen specifications. The resulting history contains
8 dedicated prospective-spec commits for S3.1-S3.8, 9 implementation/evidence
commits (S3.9 published its specification and implementation together), 9
closeout commits, and 12 targeted amendment, live-gate, evidence-integrity, or
artifact micro-fix commits. Thus the requested exclusive log range
`7163360..36af292` contains **38 commits**; S3.0 scaffolding is the entry
commit and is not included in that count.

The affected-evidence-prospective amendment record has three distinct classes:
(1) S3.8's pre-evidence clerical correction for the shipped profile name and
acceptance-locked closeout path; (2) S3.2's live-fixture feasibility correction
after pure evidence but before any live evidence, leaving the pure protocol
unchanged; and (3) S3.6's blocked-observable correction after read-only
measurement but before any passing estimator evidence, leaving the estimator
formula and already-passing rows unchanged. Separately, S3.8's live cost-model,
allocator-retention, and teardown-verdict amendments followed failed or
terminated observations and are retained explicitly as non-prospective, with
their original measurements preserved.

Independent closeout review also caught evidence-integrity defects before
acceptance. S3.6 had treated dependency availability as a pass, retained null
room measurements, and carried an assertion-free dependency-gated test;
`237e56c` forced real room/estimator execution and regenerated the evidence.
S3.8 first had reduced or synthetic matrix/determinism rows; `dd8ed5c` made
every scenario and all 55 cells execute for real. A second review found the
checksum manifest was written only after destructive Kit teardown and command
metadata was stale; `d493072` made both durable and truthful before the full
passing rerun. Product and harness fixes, including lattice-scale floating-
point handling and Isaac Lab `configclass` import drift, remain itemized in
the owning closeouts rather than being hidden by this aggregate pass.

## Known limitations and next-phase input contract

- The next implementation input is S4.1, BOM and frame lock. It must measure
  and version device/channel identity, microphone coordinates, array/source
  frames, speaker, room, clocks, environmental method, and uncertainty; no S3
  simulation result substitutes for a calibrated measurement.
- The published envelope is an approximate pyroomacoustics shoebox/image-
  source simulation. It does not establish arbitrary room geometry,
  diffraction, edge bending, a complete wave solver, reflected-path
  occlusion/directivity, diffuse-field noise coherence, measured material
  transmission, physical microphone or robot behavior, real-time effects-on
  performance, or sim-to-real validity. P2 owns diffraction and richer
  propagation; P1 retains the scaled effects-on 20 ms gate.
- Occlusion is direct-ray/per-surface transmission only. Measured material
  evidence covers seven absorption records; transmission presets and explicit
  USD losses are nominal. `per_pair_direct_path` applies one direct-path
  angular response to the complete convolved pair stem, including its
  reflected tail.
- Isaac Lab batched pose-derived velocity and batched waveform effects,
  occlusion, and materials remain unsupported in Stage 1 and fail explicitly.
  Authored velocity is supported only through the scalar core-frame path.
- `ias.audio_sensor_frame.v1` remains unchanged. New effects are additive,
  default off, and preserve the documented compatibility off-states; session
  gap preservation is also opt-in.
- `scripts/check_version_sync.py` does not yet cover `pack.toml`'s
  `pack_version` or version-bearing `artifact_name`. Both are correct at
  1.10.0 in the audited artifacts, but adding these surfaces to the S6 CI
  matrix is a required follow-up so a future release cannot repeat the
  phase-final drift.
