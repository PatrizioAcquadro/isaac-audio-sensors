# Phase R3 — Product Boundary Cleanup

Status: complete.

## Objective

Keep the reusable SDK separate from robot policies, campaign orchestration and experiment evidence.

## Subphase R3.1 — Active Source Boundary

#### Implementation

Removed campaign-specific interfaces after consumer/evidence review; retained generic sensors, DSP, recording, datasets, plugins and consumers. Kit smoke now owns a portable scene.

#### Key Decisions

Robot rigs/adapters and acceptance campaigns remain downstream; no compatibility shims for retired project surfaces.

#### Problems / Limitations

Ignored evidence is protected local state, not a package input.

## Subphase R3.2 — Distribution Boundary

#### Implementation

One recursive first-party content policy audits wheel/Kit; third-party bundle audit is separate. Schemas ship from package source, never documentation.

#### Key Decisions

Tests/tools/evidence/phase content do not ship; release chronology only in `CHANGELOG.md`.

#### Problems / Limitations

Clean archives do not establish acoustic or task validity.

## Artifacts

[[decisions/product-boundary-and-compatibility|Product boundary]] and [[topics/validation-and-release|release policy]] own current rules.

## Files

`tools/release/content_policy.py`, `tools/release/`, `src/isaac_audio_sensors/kit/microphone_rig_profiles.py`.
