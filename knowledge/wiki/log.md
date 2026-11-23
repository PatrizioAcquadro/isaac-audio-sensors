# Knowledge Log

This log records milestones that changed how the SDK is used or what its evidence supports. The complete log before the November 23 compaction is available with `git show dc7ed2b:knowledge/wiki/log.md`. Subsequent entries are appended in date order.

## 2026-08-21 — update: Establish product and release boundaries

Separated reusable SDK code from downstream campaigns, defined validation lanes and organized the wiki by topic. [[decisions/product-boundary-and-compatibility|Product boundary]] · [[implementation_phases/r6-packaging-and-release|Release engineering]]

## 2026-09-04 — update: Separate signals, observations and truth

Introduced explicit acoustic environments, continuous analytic propagation, waveform-derived activity and direction, and independent recording supervision. [[topics/acoustic-modeling|Acoustic modeling]] · [[topics/public-contracts-and-recording|Recording contracts]]

## 2026-09-07 — experiment: Compare real and simulated signals

The 25-take comparison established common processing and exposed a weak-signal activity mismatch. [[experiments/physical-signal-comparison|Physical comparison]]

## 2026-09-10 — experiment: Validate localization and Lab observations

A bounded stable-source reference and scalar/CUDA parity checks established the roles of the localizer and masked Lab output. Dynamic and reverberant mixtures remained difficult. [[experiments/04-4-multisource-localization|Localization]] · [[experiments/lab-perception-runtime|Lab perception]]

## 2026-09-19 — update: Qualify bounded Geometry operation

Closed the documented Sim, Lab, Kit, and distribution gates for native Geometry. The trials retained moving-room and diffraction limits. [[experiments/geometry-acoustics-admission|Geometry admission]]

## 2026-09-21 — update: Deliver the first six ONR demonstrations

The warehouse multisource and Garage material comparisons completed videos 5 and 6. The production record owns media locations, reviewed revisions, and presentation limits. [[topics/onr-video-production|ONR production]]

## 2026-10-08 — update: Strengthen capture and consumer validation

Corrected guided recording channel order and Replicator teardown, made Kit configuration application transactional, and measured single-voice quality under source and receiver motion. [[topics/isaac-sim-and-kit|Sim and Kit]] · [[experiments/consumer-audio-operating-envelope|Consumer assessment]]

## 2026-10-14 — experiment: Qualify the single-voice indoor trial

The opt-in profile met quality and delivery criteria together in the tested interior. The original heavier room and weaker overlapping voices retained documented failures. [[experiments/consumer-audio-runtime-performance|Loaded trial]] · [[experiments/consumer-audio-indoor-quality|Indoor quality]]

## 2026-10-22 — update: Release version 3.0.0

Published the Python distributions and Linux Kit archive. [[status#Distribution|Distribution status]]

## 2026-11-23 — update: Consolidate the developer and reviewer wiki

Reorganized current capabilities, evidence, open issues, and release status. Moved routine history to Git and retained the technical outcomes with their owning topics and experiments. [[index|Technical wiki]]

## 2026-11-23 — lint: Verify wiki navigation and release references

Checked page coverage, internal links and heading anchors, package-version synchronization, and the published release evidence.
