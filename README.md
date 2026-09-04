# Isaac Audio Sensors

`isaac-audio-sensors` is an open-source robot-audition SDK for Isaac Sim and Isaac Lab. It models robot-mounted microphone arrays and turns simulated audio scenes into standardized multichannel waveforms, spatial-audio features, recordings, datasets, and fixed-shape observations for robot learning.

It complements NVIDIA Kit Audio and RTX Acoustic with reusable sensor and data contracts, acoustic backends, recording and replay, and Isaac integrations. Robot-specific tasks, policies, assets, and task-level validation remain downstream.

[View the project showcase](https://isaac-audio-showcase-site.vercel.app).

Current package release: `3.0.0`. This release is not yet published.

## What It Provides

- Simulator-independent, versioned contracts for sources, arrays, five analytic acoustic environments, sensor frames, calibration, and datasets, with one topology-routed `analytic_acoustics` backend for direct, TDOA, optional room, and per-microphone direct-path occlusion behavior.
- Entity-owned source and microphone directivity with four first-order families, plus one amplitude-gain convention shared by Core, Isaac Sim, Isaac Lab, and Kit.
- One maintained Auditok activity detector integrated into the standard scalar runtimes, with causal multichannel decisions, an explicit application-owned dBFS threshold, and deterministic reset.
- Generic multichannel recording, validation, sharded datasets, deterministic splits, statistics, FLAC export, and read-only replay.
- Lazy Isaac Sim and Isaac Lab integrations for live stages and fixed-shape, batched observations without making NVIDIA runtimes core dependencies.
- Audited Python source/wheel distributions plus a reference, self-contained Kit archive.

## Install

The core package supports Python 3.10 or newer. Install it from PyPI:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install isaac-audio-sensors
```

Install the optional PyRoom closed-room solvers only when shoebox or polygon-prism propagation is needed:

```bash
python -m pip install "isaac-audio-sensors[room]"
```

Isaac Sim, Isaac Lab, Kit, CUDA, Torch, and Replicator are user-managed runtime capabilities and are not installed with the core package.

## Quickstart

From a source checkout, validate the maintained configuration and generate a deterministic sensor frame:

```bash
isaac-audio-sensors validate-config examples/configs/isaac_audio_sensors_demo.toml
isaac-audio-sensors simulate examples/configs/isaac_audio_sensors_demo.toml --backend analytic_acoustics --array-id rig_front --energy-threshold-dbfs -60
```

Neither command needs Isaac, a GPU, or the optional `room` extra. The threshold is a required runtime argument rather than a TOML or package default; `-60` is specific to this deterministic example. Auditok's 100 ms activity warm-up means an initial 50 ms frame can legitimately contain no observation. Closed-room examples remain available when PyRoom is installed.

## Limitations

- `analytic_acoustics` supports Core free field and half space plus optional PyRoom shoebox and polygon prisms. Two-microphone least-squares reports both compatible azimuths instead of guessing; unique 360-degree least-squares and SRP-PHAT require at least three microphones with rank-2 XY geometry, with four non-collinear microphones recommended for practical redundancy. The mass-parallel Isaac Lab path is free-field and feature-only; scalar reference binding retains the honest two-microphone least-squares case, PyRoom, and closed-topology support. Occlusion attenuates only the direct source-to-microphone path; `surface_set`, diffraction, and reflected-path blocking remain outside this backend, and none of these controlled models is a complete wave solver or calibrated acoustic twin.
- Software and GPU validation do not establish hardware calibration, physical acoustic fidelity, downstream task success, or sim-to-real transfer.
- Auditok requires an application-specific fixed threshold. Initial calibration is not yet a streaming mode, and low SNR, changing noise floors, contaminated calibration, or short impulses can limit energy-based detection.
- This SDK does not provide robot-specific tasks or policies and is not a safety-critical perception component.

## Documentation

- [Technical wiki](https://github.com/PatrizioAcquadro/isaac-audio-sensors/blob/main/knowledge/wiki/index.md)
- [Current verified status](https://github.com/PatrizioAcquadro/isaac-audio-sensors/blob/main/knowledge/wiki/status.md)
- [Getting started](https://github.com/PatrizioAcquadro/isaac-audio-sensors/blob/main/knowledge/wiki/topics/getting-started.md)
- [Changelog](https://github.com/PatrizioAcquadro/isaac-audio-sensors/blob/main/CHANGELOG.md)

## Contributing and Security

Contributions should preserve lazy optional dependencies, subsystem-owned APIs, versioned serialized contracts, and the downstream project boundary. Add proportional tests and update the canonical wiki when public behavior changes.

Report vulnerabilities privately through a GitHub security advisory when available or directly to the maintainer. Never publish credentials, private recordings, restricted robot data, or workstation-specific paths.

## License

Licensed under the Apache License 2.0. See [LICENSE](https://github.com/PatrizioAcquadro/isaac-audio-sensors/blob/main/LICENSE) and [NOTICE](https://github.com/PatrizioAcquadro/isaac-audio-sensors/blob/main/NOTICE).
