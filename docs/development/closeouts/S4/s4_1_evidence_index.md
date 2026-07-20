# S4.1 evidence index and retrieval

Status: **passed**. The functional checks and privacy-clean retained-media
checks pass for the installed handmade `S4_TEMP_DESKTOP_FIXTURE_REV0`. S4.2 is
authorized but has not started.

The machine-readable index is
`outputs/isaac_audio_sensors/S4/S4.1/evidence_index.json`. It is authoritative
for artifact roles, retention state, and SHA-256 values. The adjacent
`evidence_manifest.sha256` covers every indexed file; the index itself is
validated structurally and by Git tracking rather than self-hashed.

## Durable location

The raw WAV, FOV images, top fixture view, and raw ZED run JSON match global
ignore patterns (`outputs/`, `*.wav`, and `*.png`). They are nevertheless
force-tracked in the repository evidence snapshot. The durable local archive is
the Git object database at annotated tag `s4.1-evidence-passed-2026-07-20`;
publication to `origin` is not claimed by this closeout. The earlier
`s4.1-evidence-2026-07-20` tag remains a forensic snapshot of the superseded
CAD-blocked interpretation.

Exact retrieval from a clone or existing checkout that contains the tag:

```text
git checkout --detach refs/tags/s4.1-evidence-passed-2026-07-20
git restore --source refs/tags/s4.1-evidence-passed-2026-07-20 --worktree -- \
  outputs/isaac_audio_sensors/S4/S4.1
sha256sum -c outputs/isaac_audio_sensors/S4/S4.1/evidence_manifest.sha256
.venv/bin/python scripts/validate_s4_1_integrity.py --json
```

For one raw file without changing the worktree:

```text
git show refs/tags/s4.1-evidence-passed-2026-07-20:outputs/isaac_audio_sensors/S4/S4.1/evidence/current_fixture_audio_6ch.wav > current_fixture_audio_6ch.wav
sha256sum current_fixture_audio_6ch.wav
```

Compare the result to the SHA-256 in `evidence_index.json`. A missing tag,
missing tracked path, hash mismatch, incomplete manifest, or non-passing
validator rejects retrieval.

## Mount authority and future replacement

The installed S4.1 authority is the photographed and measured handmade fixture,
not the Fusion design. The handoff's reported values and checksums are retained
only as context for a future 3D-printed replacement; its unavailable files are
not reconstructed and do not block the different installed fixture. A printed
replacement requires a new mount identity, new as-built pose/uncertainty, and a
rerun of the practical fixture checks before its evidence can replace this
snapshot.
