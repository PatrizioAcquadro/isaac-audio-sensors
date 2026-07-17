# S1.8 installed-artifact consumer gate closeout

| Field | Recorded value |
| --- | --- |
| Subphase | `S1.8` - Installed-artifact consumer gate |
| Closeout date | 2026-07-17 |
| Entry revision | `ebc4b75` |
| Predecessor input | Post-S1.7 immutable artifacts (`outputs/isaac_audio_sensors/S1/S1.7/SHA256SUMS_post_s1_7.txt`); S1.7 freeze |
| Consumer repository | `/home/pacquadr/Desktop/squadbot-av-phase1` @ `8e24e8e` (read-only) |
| Governing gate | `docs/development/specs/s0_squadbot_readiness_acceptance.md`, S1.8 row |
| Design note | `docs/development/specs/s1_installed_consumer_gate.md` |
| Result | **Pass** |

## Scope

`scripts/run_installed_consumer_gate.py` (+ hermetic
`tests/test_cross_repo_consumer.py`, Make target `consumer-gate`) runs the
external adapter's fixtures against the INSTALLED sensor wheel in an
isolated environment. Blocked (consumer/dependency unavailability) is a
distinct verdict from failed, per the cross-repository blocker rule.

## Real-run results (evidence: `outputs/isaac_audio_sensors/S1/S1.8/`)

| Check | Result |
| --- | --- |
| Wheel hash vs `dist/SHA256SUMS` | verified (`133d1995…`) |
| Isolated venv install (wheel + consumer test deps by name; consumer never installed) | OK (`scratch-*/pip-freeze.txt`) |
| Import provenance | installed venv purelib only; not from either repository source tree |
| Consumer fixture suite `tests/test_squadbot_audio_contract_freeze.py` (cwd=consumer, `PYTHONPATH`=consumer, `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, scratch basetemp) | **7 passed, 0 failed, 0 skipped** — multi-source, empty detections, two-mic ambiguity (no graph-shape change), room-acoustics-without-optional-dependency, trace replay identical, deterministic max-events order, candidate-schema lock |
| Determinism double-run (`AudioSensorFrame -> adapter -> protobuf -> AuditoryCue -> graph export`, canonical JSON) | identical sha256 `26de618c…` both runs; normalization policy: none (exact canonical export, mirroring the consumer's own replay test) |
| Generic-boundary scan of installed package (90 files) | zero hits for `AuditoryCue`, `auditory_cue`, `MiniSceneGraph`, `scene_graph`, `ontology`, project token |
| Consumer non-modification | revision unchanged; `git status --porcelain` byte-identical before/after (`consumer_unchanged: true`) |
| Aggregate | `consumer_gate.json` status **passed** |

Pure gates for the harness itself: 504 passed / 67 skipped, lint clean
(`gate_test.log`, `gate_lint.log`).

## Defect found and fixed during the real run

The provenance guard rejected the venv because the scratch venv lives under
`outputs/` inside the sensor repository (same false-positive class as the
S1.6 wheel-venv guard). Fixed by scoping the sibling-source rule to
`<sensor repo>/src` and the consumer checkout while keeping the
must-be-inside-purelib assertion; hermetic tests re-run green.

## Acceptance mapping (S1.8 row)

Installed-artifact `AudioSensorFrame -> protobuf -> AuditoryCue -> graph`
results are deterministic (double-run hash identity plus the consumer's own
replay case); generic exports contain no downstream ontology or behavior
fields (boundary scan + the consumer's candidate-schema lock); the consumer
repository is not modified (before/after git evidence).

## Limitations and next input contract

- The gate ran with the base wheel only; the acoustic pack path has its own
  S1.5 real-install proof and an optional `--with-acoustic-pack` mode for
  future S5 flows.
- Next input (S1 phase closeout / S2): the immutable post-S1.7 artifact
  set, all eight subphase closeouts, and the S1 exit-gate statement.

## Post-review remediation (2026-07-17)

The tracked consumer freeze suite now includes
`test_contract_chain_rejects_malformed_trace_without_partial_outputs`.
An unsupported-schema trace raises `ValueError` before producing any
protobuf wrapper, cue, candidate, or graph mutation; the graph export remains
byte-identical. The installed-consumer harness requires that exact JUnit case
and a passing outcome.

The final gate passed all 8 consumer cases, found the required malformed case
with no errors, produced identical graph hashes
`26de618c877a1e1319ede5eca7f6aba40744fdc7bb0fa9f576c3bc9802db9e11`,
and confirmed the consumer checkout was unchanged during execution. Evidence:
`outputs/isaac_audio_sensors/S1/S1.8/consumer_gate.json`.
