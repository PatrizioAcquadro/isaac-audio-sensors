# S1.8 Installed-Artifact Consumer Gate

## Scope

S1.8 proves that the external audio adapter consumes the released sensor wheel,
not source imported from either checkout. The harness owns isolation and
evidence only. It does not add downstream concepts to the generic package,
install the consumer as a package, or change the consumer repository.

The gate runs `tests/test_squadbot_audio_contract_freeze.py` from the external
checkout. That suite covers multi-source geometry, empty detections, two-mic
front/back ambiguity, a room-acoustics frame with a fake optional runtime,
trace replay, deterministic event limiting, and the candidate-schema lock.
The tracked suite must include exactly the named
`test_contract_chain_rejects_malformed_trace_without_partial_outputs` case.
It feeds an unsupported-schema trace into the chain, requires an explicit
`ValueError`, and proves that no protobuf wrappers, cues, ontology candidates,
or graph mutation were produced. S1.8 rejects a missing, skipped, failed, or
duplicate JUnit case even if the rest of pytest exits successfully.

## Flow

1. Resolve the consumer checkout, output directory, distribution directory,
   and an output-local scratch directory. Output and scratch paths inside the
   consumer checkout are rejected before any directory is created.
2. Record `git rev-parse HEAD` and the verbatim bytes decoded from
   `git status --porcelain`. Pre-existing dirt is allowed and preserved as the
   baseline.
3. Select the single sensor wheel named by `dist/SHA256SUMS`, verify its hash,
   create a scratch-local venv, and install the wheel. Install the suite's
   direct dependencies by distribution name: `numpy`, `protobuf>=3.20,<6`, and
   `pytest>=8,<9`. The consumer itself is never installed.
4. Probe `isaac_audio_sensors.__file__` in the venv. Its resolved path must be
   under that venv's `site-packages` and outside both repository checkouts.
5. Run the frozen fixture file with the consumer as the working directory and
   only the consumer root on `PYTHONPATH`. Bytecode and pytest cache writes are
   disabled; `TMPDIR`, pytest `--basetemp`, JUnit output, and all logs point at
   the scratch tree. Parse JUnit and require the exact malformed-input case to
   have outcome `passed`.
6. Execute a scratch-local driver twice. Each run reads the sensor checkout's
   `examples/traces/multi_detection_frame.v1.json` by path through the installed
   trace reader, follows the consumer's frame-to-protobuf-to-cue-to-graph
   adapter chain, and writes canonical sorted-key JSON. Both file bytes and
   SHA-256 hashes must match.
7. Scan every Python and JSON file below the installed package directory for
   downstream cue, graph, ontology, and project tokens. A hit reports the
   relative file, line, token, and source text and fails the gate.
8. Repeat both Git commands. The revision and porcelain snapshot must be
   identical to the baseline even if an earlier stage failed.

The default flow installs only the base wheel. `--with-acoustic-pack` first
installs the pack's exact host requirements into the temporary venv, then runs
the archive's own installer with a private scratch-local root. The pack is not
activated or added to `PYTHONPATH`; this is presence-only evidence unless the
consumer contract later requires it.

## Environment boundary

Subprocess environments remove `PYTHONHOME`, the inherited `PYTHONPATH`, and
every `PIP_*` variable. Consumer processes then receive only:

- `PYTHONPATH=<consumer>` for its repository-root imports;
- `PYTHONDONTWRITEBYTECODE=1` and `PYTHONNOUSERSITE=1`;
- the scratch venv at the front of `PATH` and in `VIRTUAL_ENV`; and
- `TMPDIR=<scratch>/tmp`.

Pytest additionally receives `-p no:cacheprovider` and
`--basetemp=<scratch>/pytest`. Consequently, using the consumer as `cwd` does
not authorize or require a write there.

## Determinism normalization policy

No fields are normalized. The consumer's own replay freeze compares
`MiniSceneGraph.to_export_json()` exactly, using fixed frame timestamps and
detection identifiers. S1.8 mirrors that contract and canonicalizes only JSON
representation (`sort_keys=True`, compact separators, ASCII encoding) before
hashing. A future timestamp or identifier normalization is permitted only when
the consumer's documented replay mechanism adopts it; the evidence must then
name every normalized field and the upstream mechanism being mirrored.

## Evidence inventory

`outputs/isaac_audio_sensors/S1/S1.8/consumer_gate.json` is the verdict record.
It includes:

- consumer revision plus verbatim before/after porcelain snapshots;
- verified wheel path, size, and SHA-256;
- environment sanitization deltas and the exact dependency list;
- venv `pip freeze` path and full venv/pip/provenance command logs;
- full pytest output, JUnit path, and a per-case outcome summary;
- both graph paths, driver-printed hashes, independently computed hashes, the
  fixture path, and the empty normalization list;
- installed-package provenance and boundary-scan files/hits;
- optional acoustic-pack presence data; and
- per-stage and total wall-clock timings.

All detailed logs and generated files live in the scratch directory named by
the verdict record.

## Passed, failed, and blocked

`passed` means every invariant held and the consumer snapshot was unchanged.
`failed` means an available gate found an artifact, provenance, contract,
determinism, generic-boundary, or non-modification defect.

`blocked` is a non-passing cross-repository blocker record. It is used when the
consumer checkout or Git is unavailable, when a scratch venv cannot be
created, or when the named external test dependencies cannot be obtained.
The JSON includes an actionable error, and both the script and Make target
exit non-zero. A blocker is never converted into a skip or pass.
