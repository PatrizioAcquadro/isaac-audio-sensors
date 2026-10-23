# Isaac Audio Sensors

**Give simulated robots a sense of hearing.**

[![CI](https://github.com/PatrizioAcquadro/isaac-audio-sensors/actions/workflows/ci.yml/badge.svg)](https://github.com/PatrizioAcquadro/isaac-audio-sensors/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/isaac-audio-sensors?color=76b900)](https://pypi.org/project/isaac-audio-sensors/)
[![Python](https://img.shields.io/pypi/pyversions/isaac-audio-sensors)](https://pypi.org/project/isaac-audio-sensors/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

An open-source robot-audition SDK for **Python, Isaac Sim, Isaac Lab, and NVIDIA Kit**. Model microphone arrays, simulate the sound that reaches each channel, and turn those signals into spatial observations, recordings, and datasets for robot learning.

[Website](https://isaac-audio.vercel.app) · [Documentation](knowledge/wiki/index.md) · [Get started](#quickstart) · [Demos](https://isaac-audio.vercel.app/demos/) · [Releases](https://github.com/PatrizioAcquadro/isaac-audio-sensors/releases)

[![Simulated robot between a fan and compressor, with received microphone levels and two estimated sound directions](https://isaac-audio.vercel.app/media/multiple.webp)](https://isaac-audio.vercel.app/media/introduction.mp4)

**[▶ Watch the 60-second project film](https://isaac-audio.vercel.app/media/introduction.mp4)** — off-camera events, moving sources, occlusion, overlapping sounds, and acoustic materials. Six controlled simulation demonstrations with received microphone audio. [Full demos and model boundaries](https://isaac-audio.vercel.app/demos/) · [Media credits](https://isaac-audio.vercel.app/credits/).

## What you can build

- **Configurable microphone arrays.** Use standalone or robot-mounted arrays with explicit geometry, pose, sample rate, directivity, gain, and signal effects.
- **Acoustic simulation.** Start with analytic direct-path propagation, add approximate room acoustics, or use optional native Geometry Acoustics with prepared USD scenes.
- **Signal-derived perception.** Detect activity and optionally estimate sound directions from the received mixture, preserving ambiguity and unavailable estimates.
- **Recordings and learning datasets.** Keep aligned multichannel audio and sensor frames; validate, recover, split, replay, and optionally export FLAC recordings with bounded-memory storage.
- **Isaac integration.** Author and monitor sensors in Kit, bind to live Isaac Sim scenes, or feed finite, masked observations into Isaac Lab on CUDA.

```text
Acoustic scene + sources → Microphone PCM → Perception → Observations
                                │                           │
                                └── Recordings + replay     └── Isaac Lab inputs
```

Perception consumes microphone mixtures and array geometry. Source identities, source poses, and simulator truth stay outside policy observations; dataset supervision follows a separate path. Robot controllers and task policies belong to the consuming project.

## Quickstart

**Requirements:** Python 3.10 or newer. This first example uses the Python core and needs neither Isaac nor a GPU.

Clone the repository to get the matching example configuration, then create an isolated environment:

```bash
git clone https://github.com/PatrizioAcquadro/isaac-audio-sensors.git
cd isaac-audio-sensors
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --editable .
```

Validate the scene and generate a free-field audio frame:

```bash
isaac-audio-sensors validate-config examples/configs/isaac_audio_sensors_demo.toml
isaac-audio-sensors simulate examples/configs/isaac_audio_sensors_demo.toml \
  --backend analytic_acoustics --array-id rig_front --energy-threshold-dbfs -60
```

The simulation prints a JSON sensor frame with the selected array's sample rate, time window, channel validity, and aggregate microphone levels. Activity depends on the signal and detector history; a short first window can contain no observations. The `-60` dBFS threshold is specific to this generated-signal example; choose a threshold for your application.

To see how two microphones preserve direction ambiguity:

```bash
python examples/core/two_mic_ambiguity.py
```

Add approximate room propagation and planar direction estimation when needed:

```bash
python -m pip install --editable ".[room]"
```

Direction estimation is opt-in: add `--enable-doa` to `simulate`. See [Getting started](knowledge/wiki/topics/getting-started.md) for more examples, recording, schema export, and runtime setup.

### Install a release

For an application that does not need the source examples:

```bash
python -m pip install "isaac-audio-sensors==3.0.0"
# Optional room acoustics, planar DOA, and FLAC support:
python -m pip install "isaac-audio-sensors[room]==3.0.0"
```

Current source version: `3.0.0`. Version 3 introduces breaking changes from 2.0; read the [migration guide](knowledge/wiki/decisions/product-boundary-and-compatibility.md) before upgrading. Use the source and documentation at your installed [release tag](https://github.com/PatrizioAcquadro/isaac-audio-sensors/tree/v3.0.0) when reproducing release behavior.

## Choose your workflow

| Workflow | Use it for | Start here |
| --- | --- | --- |
| **Python / CLI** | Configuration, analytic simulation, perception, recording, and replay without a simulator | [Core examples](examples/core) · [Setup guide](knowledge/wiki/topics/getting-started.md) |
| **Isaac Sim** | Live USD scenes, moving sources, and robot-mounted arrays | [Scene binding recipe](examples/isaac_sim/live_audio_lab.py) · [Sim guide](knowledge/wiki/topics/isaac-sim-and-kit.md) |
| **Isaac Lab** | CUDA perception and fixed-shape, masked observations for learning | [Observation recipe](examples/isaac_lab/isaac_lab_audio_observation.py) · [Lab guide](knowledge/wiki/topics/isaac-lab-integration.md) |
| **Kit extension** | Interactive scene authoring, monitoring, recording, and export | [Extension setup](knowledge/wiki/topics/isaac-sim-and-kit.md) · [Release archive](https://github.com/PatrizioAcquadro/isaac-audio-sensors/releases/tag/v3.0.0) |

Isaac Sim, Isaac Lab, Kit, CUDA, and Torch are user-managed runtime dependencies. The Python core imports without them. The packaged Kit extension targets **Linux x86_64, Kit 110.1, and Python 3.12** and includes its audio dependencies. Native Geometry providers require [separate setup](knowledge/wiki/topics/geometry-acoustics.md).

The Sim and Lab recipes assume an initialized compatible runtime. From a configured checkout, run the live smoke workflows through your Isaac Lab launcher; leave the core virtual environment first:

```bash
deactivate
make smoke-isaac-sim
make smoke-isaac-lab
make smoke-kit
```

Set `ISAAC_LAB_ROOT` or `ISAAC_LAB_PYTHON` if your launcher is outside the default `~/IsaacLab`. The Lab smoke requires a working CUDA GPU. See [runtime validation](knowledge/wiki/topics/validation-and-release.md) for prerequisites and optional native providers.

## Documentation

| Question | Reference |
| --- | --- |
| How do the components fit together? | [System architecture](knowledge/wiki/topics/system-architecture.md) |
| Which propagation model should I use? | [Acoustic modeling](knowledge/wiki/topics/acoustic-modeling.md) · [Geometry Acoustics](knowledge/wiki/topics/geometry-acoustics.md) |
| What do frames and recordings contain? | [Public contracts and recording](knowledge/wiki/topics/public-contracts-and-recording.md) |
| How do I connect a learning policy? | [Isaac Lab integration](knowledge/wiki/topics/isaac-lab-integration.md) |
| What has been implemented and validated? | [Verified status](knowledge/wiki/status.md) · [Localization evidence](knowledge/wiki/experiments/04-4-multisource-localization.md) |
| What changed, and how do I upgrade? | [Changelog](CHANGELOG.md) · [Compatibility and migration](knowledge/wiki/decisions/product-boundary-and-compatibility.md) |

The [technical wiki](knowledge/wiki/index.md) is the full reference. The [website](https://isaac-audio.vercel.app) provides a visual introduction and captioned demonstrations.

## Validation and scope

Software tests establish contracts and behavior in their tested environments. Localization is qualified for bounded simulated cases; weak speech, rapid motion, reverberation, and latency remain limitations. Geometry's selected-route diffraction is uncalibrated, and full-room moving equivalence is not established.

The demonstrations illustrate individual sensing workflows. They do not establish physical acoustic fidelity, general multisource performance, hardware calibration, or sim-to-real transfer. See [verified status](knowledge/wiki/status.md) for the measured domains and remaining work.

## Development and contributions

Bug reports, focused fixes, and reusable examples are welcome. [Open an issue](https://github.com/PatrizioAcquadro/isaac-audio-sensors/issues) with the SDK/runtime versions, a minimal configuration, the expected behavior, and the actual output. Use issues for setup questions and feature proposals too; check existing reports first.

From the source checkout, install development dependencies and run the host gate:

```bash
python -m pip install --editable ".[dev]"
make check
```

`make check` runs version synchronization, Ruff, whitespace checks, and unit, contract, integration, and release tests. Live Isaac/GPU checks are separate; run the workflows relevant to your change using the [validation guide](knowledge/wiki/topics/validation-and-release.md).

Keep changes focused, preserve lazy optional dependencies and public contracts, and update the affected canonical documentation when behavior changes. Add tests for meaningful behavior. In a pull request, explain the problem, the resulting behavior, and what you validated. Keep private recordings, generated evidence, and robot-specific policies outside the public package.

For security concerns, contact the [maintainer](https://github.com/PatrizioAcquadro) privately. Keep vulnerability details, credentials, and private recordings out of public issues.

## License and credits

Licensed under [Apache 2.0](LICENSE). See [NOTICE](NOTICE) for third-party notices and [media credits](https://isaac-audio.vercel.app/credits/) for the demonstration assets and their licenses.
