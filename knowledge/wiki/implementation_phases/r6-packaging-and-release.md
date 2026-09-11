# Phase R6 — Packaging and Release

Status: complete; v2.0.0 publication is historical, current package version is owned by pyproject.toml.

## Objective

Ship auditable clean-source Python sdist/wheel and a self-contained Linux Kit archive. [[topics/validation-and-release|Validation and Release]] owns current commands, locks and distribution behavior.

## Subphase R6.0 — Release Model

#### Implementation

Selected public Python/Kit delivery; R6.8 later added sdist and trusted publication to the original local wheel/Kit model.

#### Key Decisions

One synchronized release version, independently versioned schemas.

#### Problems / Limitations

Do not treat the original no-sdist plan as current policy.

## Subphase R6.1 — Root and Local Workspace Cleanup

#### Implementation

Consolidated root guidance and regenerable outputs; cleanup preserves local evidence, virtualenv and agent/checklist state.

#### Key Decisions

Explicit output overrides remain supported.

#### Problems / Limitations

Build cleanup is not authorization to remove protected evidence.

## Subphase R6.2 — Minimal Python Wheel

#### Implementation

Built minimal first-party wheel and audited source-derived inventories plus isolated installation.

#### Key Decisions

No tests, tools, datasets or project-specific payload.

#### Problems / Limitations

Build through sdist to avoid stale build-tree content returning.

## Subphase R6.3 — Standard Kit Archive

#### Implementation

Created the platform-named Community Registry archive and validated extracted-runtime origins.

#### Key Decisions

Installed extension is self-contained; host NumPy/typing_extensions remain host-owned.

#### Problems / Limitations

Registry discovery is distinct from producing a valid archive.

## Subphase R6.4 — Remove the Custom Acoustic Pack

#### Implementation

Replaced the separate acoustic bundle with locked dependencies inside the Kit archive.

#### Key Decisions

One artifact/dependency path, no redundant installer.

#### Problems / Limitations

Historical five/six-wheel counts are superseded by the current lock.

## Subphase R6.5 — Local Release Workflow

#### Implementation

Added explicit `make check`, preflight and local `make release WHEELHOUSE=...`; no action on bare make.

#### Key Decisions

Build/audit does not publish, tag or push.

#### Problems / Limitations

Missing locked inputs fail before replacing artifacts.

## Subphase R6.6 — Exact Artifact Audits

#### Implementation

Audit first-party and bundled inventories, versions, licenses, unsafe paths and contamination at each artifact boundary.

#### Key Decisions

No unverified download or dependency substitution.

#### Problems / Limitations

The maintained lock and builders define exact current contents.

## Subphase R6.7 — Validation and Closeout

#### Implementation

Passed host/native/optional and actual RTX Sim/Lab/Kit plus extracted offline Kit and downstream checks.

#### Key Decisions

No checkout import path may disguise a broken package.

#### Problems / Limitations

Historical empty-entity timing did not establish active perception throughput.

## Subphase R6.8 — Publication Readiness

#### Implementation

Built sdist then wheel, isolated installation and protected OIDC release workflow; published v2.0.0 at `583d66e` with the validated Kit asset.

#### Key Decisions

Production publication requires a matching non-prerelease GitHub Release/protected environment. Later maintenance removed manual TestPyPI publication.

#### Problems / Limitations

Current package is 3.0.0; this historical release is not evidence of later publication. Community Registry discovery was still pending at that closeout.

## Artifacts

Historical v2.0.0 Python provenance/install and 37-step extracted Kit workflow passed. Current release truth: source metadata, lock, audits and [[topics/validation-and-release|release topic]].

## Files

`tools/release/`, `.github/workflows/`, `pyproject.toml`, `Makefile`, `exts/isaac_audio_sensors.omni/`.
