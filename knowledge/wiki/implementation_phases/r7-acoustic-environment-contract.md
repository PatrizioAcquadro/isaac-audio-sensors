# Phase R7 — Acoustic Environment Contract

Status: complete (2026-09-01).

## Objective

Define explicit simplified acoustic environments independently of Isaac. R8 owns propagation; R10 owns arbitrary prepared geometry.

## Subphase R7.1 — Environment Contract

#### Implementation

Introduced local surfaces plus world pose, with free_field, half_space, shoebox, polygon_prism and surface_set builders. Sources/arrays remain world-frame entities.

#### Key Decisions

An L-shaped room is one polygon prism; floor-only is half-space; separate rooms are not merged.

#### Problems / Limitations

surface_set describes authored surfaces but is not accepted by Analytic.

## Subphase R7.2 — Isaac Resolution

#### Implementation

Made environment mandatory and added manual/anchor/marked-auto resolution, full-array containment and selective invalidation. Kit unconfigured state blocks capture.

#### Key Decisions

Never infer free field from missing data, clamp sources or resolve ambiguity using hidden path ordering.

#### Problems / Limitations

Automatic marked volumes are not arbitrary room recognition. Multi-room/portals/diffraction remain outside this analytic contract.

## Artifacts

Current solver/resolution details: [[topics/acoustic-modeling|Acoustic Modeling]]. Historical staged binding versions were replaced directly, not retained as aliases.

## Files

`src/isaac_audio_sensors/core/acoustics/environments.py`, `isaac/environment_resolution.py`, `isaac/stage_cache.py`.
