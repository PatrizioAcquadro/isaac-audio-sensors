# Dataset Manifest Fixtures

The two top-level JSON files are deterministic valid fixtures for
`ias.audio_dataset_manifest.v1`. Regenerate them with
`make regenerate-manifests`. The `invalid/` files are hand-maintained, and
their reason-coded names identify the fail-closed invariant they violate.

Paths and checksums in these compact contract fixtures are references; the
large audio and trace payloads are intentionally not distributed here.
