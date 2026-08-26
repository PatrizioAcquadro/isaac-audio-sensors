# Isaac Audio Sensors

`isaac-audio-sensors` is an open-source robot-audition SDK for Isaac Sim and Isaac Lab. It models robot-mounted microphone arrays and turns simulated audio scenes into standardized multichannel waveforms, spatial-audio features, recordings, datasets, and fixed-shape observations for robot learning.

It complements NVIDIA Kit Audio and RTX Acoustic with reusable sensor and data contracts, acoustic backends, recording and replay, and Isaac integrations. Robot-specific tasks, policies, assets, and task-level validation remain downstream.

[View the project showcase](https://isaac-audio-showcase-site.vercel.app).

Current package release: `2.0.0`.

## What It Provides

- Simulator-independent, versioned contracts for scenes, microphone arrays, sensor frames, calibration, and dataset manifests, with deterministic geometry and synthetic TDOA backends plus optional room acoustics.
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

Install the optional shoebox-room backend only when needed:

```bash
python -m pip install "isaac-audio-sensors[room]"
```

Isaac Sim, Isaac Lab, Kit, CUDA, Torch, and Replicator are user-managed runtime capabilities and are not installed with the core package.

## Quickstart

From a source checkout, validate the maintained configuration and generate a deterministic sensor frame:

```bash
isaac-audio-sensors validate-config examples/configs/isaac_audio_sensors_demo.toml
isaac-audio-sensors simulate examples/configs/isaac_audio_sensors_demo.toml --backend geometry_only --array-id rig_front
```

These commands require only the core package; no Isaac runtime or GPU is needed.

## Limitations

- The geometry, synthetic TDOA, and shoebox-room backends are controlled models, not a complete wave solver or calibrated acoustic twin.
- Software and GPU validation do not establish hardware calibration, physical acoustic fidelity, downstream task success, or sim-to-real transfer.
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
