# S4.2 evidence index and machine-local retrieval

Status: **NO-GO pending authorized frozen-commit validation**. The replacement
hardware take passes and the machine-local raw archive passes checksums and
semantic validation on the capture workstation. The raw-independent
clean-checkout gate remains pending.

The authoritative machine-readable inventory is
`outputs/isaac_audio_sensors/S4/S4.2/remediation_20260721/evidence_index.json`;
its adjacent
`SHA256SUMS` covers every indexed artifact other than itself. The index records
tracked implementation/contracts and every retained machine-local file,
including accepted raw media, failed attempts, partial transfer evidence,
preflights, alignment review frames, and privacy-deletion records.

## Machine-local policy

Raw S4.2 evidence exists only at:

```text
<repository-root>/dataset/S4.2/
```

This directory is gitignored by explicit operator policy. It is not replicated,
not an off-machine archive, not recoverable from Git, and not available from a
fresh clone or another workstation. The hashes and acquisition contracts in
the tracked index do not make an unavailable raw artifact independently
reviewable. Loss of this machine or directory is loss of the raw evidence.

Verify every file on the capture workstation without repair or coercion:

```text
cd <repository-root>
cd dataset/S4.2
sha256sum -c SHA256SUMS.remediation_20260721
cd ../..
PYTHONPATH=src .venv/bin/python scripts/validate_s4_2_integrity.py \
  --index outputs/isaac_audio_sensors/S4/S4.2/remediation_20260721/evidence_index.json \
  --require-machine-local --json
PYTHONPATH=src .venv/bin/python scripts/verify_s4_2_local_dataset.py \
  --index outputs/isaac_audio_sensors/S4/S4.2/remediation_20260721/evidence_index.json \
  --repository-root . --report /tmp/s4_2_local_validation.json
```

The last command deliberately requires a new report path and refuses to
overwrite an earlier report.

## Clean-checkout contract

A clean checkout contains the tracked implementation, configuration,
validators, deterministic reference WAV and metadata, accepted report copies,
evidence index, checksums, and closeout. It does not contain `dataset/S4.2/`.
Validate the raw-independent contract with:

```text
PYTHONPATH=src .venv/bin/python scripts/validate_s4_2_integrity.py \
  --index outputs/isaac_audio_sensors/S4/S4.2/remediation_20260721/evidence_index.json \
  --require-git-tracked --json
```

Omitting `--require-machine-local` is intentional only for the clean checkout.
It verifies every tracked artifact and every declared machine-local contract
while recognizing that ignored raw files are unavailable there. It must never
be reported as raw retrieval or raw semantic validation.
