# Isaac Audio Sensors

`isaac-audio-sensors` is an open-source robot-audition SDK for Isaac Sim and Isaac Lab.

It models robot-mounted microphone arrays and converts audio-scene state into standardized multichannel waveforms, spatial features, recordings, datasets, and fixed-shape observations for robot learning.

The package complements NVIDIA Kit Audio and RTX Acoustic by providing reusable sensor contracts, acoustic backends, recording/replay, and Isaac Lab integration without owning a robot-specific task or policy.

Showcase: <https://isaac-audio-showcase-site.vercel.app>

Current package release: `2.0.0`.

The package version and the serialized schema versions are independent; the current frame contract is `ias.audio_sensor_frame.v1`.

The package root exports only `__version__`. `isaac_audio_sensors.core` exports the eleven fundamental sensor models; config, calibration, backend, plugin, capability, fidelity, and pack APIs remain public from their canonical modules. Dataset contracts belong to `recording`, schema generators to `schemas.generate`, simulator services to `isaac` or `lab`, and the `kit` root exports only `ExtensionController`.

`AudioSensorConfig` is simulator-independent. Isaac Lab configuration uses `isaac_audio_sensors.lab.AudioArraySensorCfg`. Python generators are authoritative for the three public schemas; packaged JSON files and CLI exports are deterministic generated artifacts.

## Capabilities

- Import-safe Python models for scenes, sources, poses, rooms, microphone arrays, detections, DOA estimates, and sensor frames.
- Versioned frame, dataset-manifest, and calibration-profile schemas with deterministic serialization and validation.
- Stable `geometry_only` and `tdoa_synthetic` backends plus optional `room_acoustics` and `room_acoustics_srp` backends resolved through one plugin registry.
- Motion, Doppler, directivity, material/occlusion, channel-response, noise, clock, and electronics effects with explicit diagnostics and identity defaults.
- Generic atomic recording, verified shards, manifests, deterministic splits, statistics, codecs, validation, and read-only replay.
- Lazy Isaac Sim discovery, stage binding, pose tracking, visualization, frame publication, and optional Replicator integration.
- Lazy Isaac Lab `SensorBase` integration with scalar or batched multi-environment observation tensors and explicit GPU validation.
- Reference Kit extension with guided and expert workflows, instruments, audio preview, OmniGraph, recording, and export.
- Deterministic wheel, source, Kit, and optional acoustics-pack build and audit tooling.

## Install

The pure package supports Python 3.10 or newer.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Install the optional shoebox-room backend only when needed:

```bash
python -m pip install -e ".[room]"
```

Isaac Sim, Isaac Lab, Kit, CUDA, Torch, and Replicator are user-managed runtime capabilities and are not PyPI dependencies of the core package.

## Quickstart

Validate the maintained example and generate a deterministic frame:

```bash
isaac-audio-sensors validate-config examples/configs/isaac_audio_sensors_demo.toml
isaac-audio-sensors simulate examples/configs/isaac_audio_sensors_demo.toml --backend geometry_only --array-id rig_front
```

Create a frame directly from Python:

```python
from isaac_audio_sensors.core import AudioSceneSnapshot, AudioSourceSpec, AudioTimeWindow
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.microphone_array import create_microphone_array

array = create_microphone_array(
    array_id="rig_front",
    prim_path="/World/Rig/AudioArray",
    layout_name="quad_front",
)
scene = AudioSceneSnapshot(
    stage_id="demo",
    timestamp_ms=0,
    sources=(
        AudioSourceSpec(
            source_id="speaker",
            prim_path="/World/Sources/Speaker",
            class_label="Speech",
            audio_asset_path="generated://impulse",
            position_world=(4.0, 2.0, 0.0),
            orientation_world_quat=None,
            start_time_s=0.0,
            duration_s=1.0,
            gain_db=0.0,
        ),
    ),
    arrays=(array,),
)
frame = TdoaSyntheticBackend().simulate(
    scene,
    array,
    AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=1.0,
        timestamp_ms=0,
        sample_rate_hz=array.sample_rate_hz,
    ),
)
print(frame.schema_version, frame.detections[0].doa)
```

Run the maintained pure examples from an installed checkout:

```bash
python examples/core/two_mic_ambiguity.py
python examples/recording/read_manifest.py
python examples/calibration/read_profile.py
```

See [examples/README.md](examples/README.md) for the optional room recipe, fixtures, and initialized Isaac Sim/Lab recipes.

## Isaac Runtime

The maintained live gates use the official Isaac Lab launcher and the workstation GPU:

```bash
make smoke-isaac-sim
make smoke-isaac-lab
make smoke-kit
```

Run these commands from a shell without an activated venv or Conda environment; set `ISAAC_LAB_PYTHON` only when the Isaac Lab installation is not at its default location.

The GPU-required Lab gate fails instead of silently falling back to CPU.

## Validation

```bash
make test
.venv/bin/python -m pytest -q tests/integration
make test-release
make test-isaac
make lint
make build
make build-kit
git diff --check
make clean
```

The Isaac lane is required only for runtime changes and for release evidence that claims the supported live path.

## Limitations

- `geometry_only` is geometric observation, not acoustic propagation.
- `tdoa_synthetic` models direct-path synthetic delay and diagnostics, not reverberation.
- Room acoustics is an optional shoebox approximation, not a calibrated acoustic twin or complete wave solver.
- Raycast occlusion and nominal material transmission do not model diffraction or prove physical fidelity.
- Two-microphone DOA retains front/back ambiguity without an additional prior.
- Software and GPU validation do not establish hardware calibration, downstream task success, or sim-to-real transfer.

## Documentation

- [Technical wiki](knowledge/wiki/index.md)
- [Current status](knowledge/wiki/status.md)
- [Getting started](knowledge/wiki/topics/getting-started.md)
- [System architecture](knowledge/wiki/topics/system-architecture.md)
- [Public contracts and recording](knowledge/wiki/topics/public-contracts-and-recording.md)
- [Acoustic modeling](knowledge/wiki/topics/acoustic-modeling.md)
- [Isaac Sim and Kit](knowledge/wiki/topics/isaac-sim-and-kit.md)
- [Isaac Lab integration](knowledge/wiki/topics/isaac-lab-integration.md)
- [Validation and release](knowledge/wiki/topics/validation-and-release.md)
- [Product boundary and compatibility](knowledge/wiki/decisions/product-boundary-and-compatibility.md)
- [Changelog](CHANGELOG.md)

## Contributing and Security

Keep core imports independent from optional runtimes, add proportional tests for behavior changes, update canonical wiki pages for material interface changes, and keep discussions professional and technical.

Report vulnerabilities privately through a GitHub security advisory when available or directly to the maintainer. Never publish credentials, private recordings, restricted robot data, generated media dumps, or workstation-specific paths in issues, pull requests, examples, or fixtures.

This package is simulation tooling, not a safety-critical perception component. Independent validation, calibration, and runtime safety controls are required for safety-relevant use.

## License

This project is licensed under Apache License 2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE).
