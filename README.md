# Isaac Audio Sensors

An open-source robot-audition SDK for Python, Isaac Sim, Isaac Lab, and NVIDIA Kit. It models standalone or robot-mounted microphone arrays and produces multichannel waveforms, observed audio features, recordings, datasets, and fixed-shape learning observations.

Current source version: `3.0.0`. **Unreleased.** The latest published release is **2.0.0**; the examples below target this checkout.

[Project showcase](https://isaac-audio-showcase-site.vercel.app) · [Verified status](knowledge/wiki/status.md) · [Technical wiki](knowledge/wiki/index.md)

## Capabilities

- Analytic direct-path and optional room propagation, configurable array geometry, source/microphone directivity, gain, and signal effects.
- Optional Geometry Acoustics from composed USD scenes, with native direct/transmission, specular, selected-route NLOS, and diffuse components.
- Waveform-derived activity and optional direction estimation, with explicit ambiguity, missing estimates, and stream resets.
- Aligned multichannel recording, bounded-memory shards, recovery, validation, splits, FLAC export, and replay.
- Live Isaac Sim sensors, CUDA Isaac Lab observations, and a Kit authoring/monitoring interface. Simulator dependencies remain optional.

## Install and try the checkout

Python 3.10 or newer:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --editable ".[dev]"
isaac-audio-sensors validate-config examples/configs/isaac_audio_sensors_demo.toml
isaac-audio-sensors simulate examples/configs/isaac_audio_sensors_demo.toml --backend analytic_acoustics --array-id rig_front --energy-threshold-dbfs -60
```

This free-field example needs neither Isaac nor a GPU. The threshold is specific to the example; applications must choose their own. Add `--enable-doa` for direction estimation. Room propagation and planar DOA additionally need `python -m pip install --editable ".[room]"`.

For the published **2.0.0** package, use `python -m pip install "isaac-audio-sensors==2.0.0"` and its matching release documentation. See [Getting started](knowledge/wiki/topics/getting-started.md) for runtime setup and [migration guidance](knowledge/wiki/decisions/product-boundary-and-compatibility.md) for 3.0 API changes.

## Scope and limits

Activity uses an application-specific energy threshold. Localization is qualified for bounded simulated cases; weak speech, rapid motion, reverberation, and latency remain limitations. Geometry's selected-route diffraction is uncalibrated, and full-room moving equivalence is not established. Software checks do not establish physical fidelity or sim-to-real transfer. Robot policies and task acceptance belong downstream.

[Acoustic models](knowledge/wiki/topics/acoustic-modeling.md), [Geometry setup](knowledge/wiki/topics/geometry-acoustics.md), and [localization evidence](knowledge/wiki/experiments/04-4-multisource-localization.md) define the supported cases and limits.

## Development

Run `make check` for lint, version synchronization, and host tests. Use [Validation and release](knowledge/wiki/topics/validation-and-release.md) for Isaac/GPU checks and audited sdist, wheel, and Kit builds. Preserve lazy dependencies, serialized contracts, and concise canonical documentation when contributing.

[Changelog](CHANGELOG.md) · [Architecture](knowledge/wiki/topics/system-architecture.md) · [License](LICENSE) · [Notice](NOTICE)

Report vulnerabilities privately through a GitHub security advisory or to the maintainer; exclude credentials and private recordings. Licensed under Apache 2.0.
