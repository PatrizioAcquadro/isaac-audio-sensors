# Calibration Profile Fixtures

The top-level JSON file is a deterministic valid
`ias.audio_calibration_profile.v1` fixture. Its ReSpeaker XVF3800 geometry and
channel values are explicitly `nominal_not_measured`; it is not physical
calibration evidence. Regenerate it with `make regenerate-manifests`.

The `invalid/` files are hand-maintained, with one reason-coded file for each
failure class exercised by the contract tests.
