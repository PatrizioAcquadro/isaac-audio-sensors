# Isaac Audio Sensors

`isaac-audio-sensors` is an open-source robot-audition SDK for Isaac Sim and Isaac Lab. It models robot-mounted microphone arrays and turns simulated audio scenes into standardized multichannel waveforms, spatial-audio features, recordings, datasets, and fixed-shape observations for robot learning.

It complements NVIDIA Kit Audio and RTX Acoustic with reusable sensor and data contracts, acoustic backends, recording and replay, and Isaac integrations. Robot-specific tasks, policies, assets, and task-level validation remain downstream.

[View the project showcase](https://isaac-audio-showcase-site.vercel.app).

Current package release: `3.0.0`. This release is not yet published.

## What It Provides

- Simulator-independent, versioned contracts for sources, arrays, five analytic acoustic environments, sensor frames, calibration, and datasets, with one topology-routed `analytic_acoustics` backend for direct, TDOA, optional room, and per-microphone direct-path occlusion behavior.
- Entity-owned source and microphone directivity with four first-order families, plus one amplitude-gain convention shared by Core, Isaac Sim, Isaac Lab, and Kit.
- One maintained Auditok activity detector integrated into the standard scalar runtimes, with causal multichannel decisions, an explicit application-owned dBFS threshold, and deterministic reset.
- Explicit, default-off mixture-only DOA: bounded indoor planar/3D multisource localization at 16 kHz with 750 ms past context; honest stereo ambiguity and other planar rates retain their 250 ms single-event role.
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

Add `--enable-doa` to the simulation command to opt into standard geometry-based direction estimation. Planar DOA requires the `room` extra; two-microphone least-squares does not. Without that flag, neither command needs Isaac, a GPU, or PyRoom. The threshold is a required runtime argument rather than a TOML or package default; `-60` is specific to this deterministic example.

## Limitations

- `analytic_acoustics` supports Core free field and half space plus optional PyRoom shoebox and polygon prisms. Opt-in 16 kHz DOA uses WPE/group-sparse localization, confirmed for bounded simulated indoor, relatively stable sources. Weak speech remains imperfect; source changes can take 1–1.5 seconds, and 3D compute exceeds 50 ms. Rotating microphone arrivals and retarded source orientation are validated at signal level. The motion/indoor DOA comparison retains the existing localizer because faster candidates fail joint moving-pair utility. Physical/general indoor robustness and rapid-motion DOA remain unqualified; see the [measured scope and regressions](knowledge/wiki/experiments/04-4-multisource-localization.md). Stereo retains least-squares ambiguity; other planar rates retain PyRoom SRP. Lab reference mode projects observed events into masked tensors; the entity path remains empty and 07.2 has not started. Occlusion affects only the direct path; `surface_set`, diffraction and reflected-path blocking remain outside this backend.
- Software and GPU validation do not establish hardware calibration, physical acoustic fidelity, downstream task success, or sim-to-real transfer.
- Auditok requires an application-specific fixed threshold; no calibration mode is maintained. Low SNR, changing noise floors, or short impulses can limit energy-based detection.
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
