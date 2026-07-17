# S0.3 live baseline closeout

| Field | Recorded value |
| --- | --- |
| Subphase | `S0.3` - Live baseline |
| Closeout date | 2026-07-16 |
| Entry revision | `161d429` |
| Package version | `1.7.0` |
| Host environment | Ubuntu 24.04.4 LTS; Linux `6.8.0-136-generic`; x86_64 |
| GPU and driver | NVIDIA GeForce RTX 4090; driver `580.159.03`; 24564 MiB |
| Isaac Sim runtime | `6.0.1-rc.7+release.42383.32955d8d.gl` from `/home/pacquadr/isaacsim/VERSION`; `/home/pacquadr/isaacsim/python.sh`; Kit Python 3.12.13 at `/home/pacquadr/isaacsim/kit/python/bin/python3` |
| Kit runtime | app `6.0.1`; build `110.1.2+production.326809.f9bf0dda.gl` |
| Isaac Lab runtime | checkout release `3.0.0` from `/home/pacquadr/IsaacLab/VERSION`; `/home/pacquadr/IsaacLab/isaaclab.sh -p`; `_isaac_sim` resolves to `/home/pacquadr/isaacsim` |
| Torch and CUDA device | PyTorch `2.10.0+cu128`; one CUDA device, `cuda:0`, NVIDIA GeForce RTX 4090 |
| Evidence root | `outputs/isaac_audio_sensors/S0/S0.3/` |

The host OS and kernel are independently preserved in
`outputs/isaac_audio_sensors/S0/S0.2/environment.txt`. The GPU, driver, memory,
and Isaac Sim import check are preserved in
`outputs/isaac_audio_sensors/S0/S0.3/runtime_facts.txt` and repeated by the
Isaac Sim gate logs and JSON GPU probes.

The Isaac Sim and extension JSON probes record `isaacsim_version` and generic
`kit_version` as `unavailable`, but they also record Kit app `6.0.1`, Kit build
`110.1.2+production.326809.f9bf0dda.gl`, and the imported module under
`/home/pacquadr/isaacsim`. The full Isaac Sim build string above therefore
comes from that installation's `VERSION` file. Similarly, the Isaac Lab
checkout `VERSION` is `3.0.0`, while its loaded `isaaclab` extension metadata
is `6.1.14`; both Lab JSON files preserve the latter in
`runtime.isaaclab_version` and show that the imported module came from the
3.0.0 checkout.

## Scope

This closeout records the six live checks required by Section 6.3 of
`docs/final_sensor_development_plan.md`: Isaac Sim lifecycle and audio,
ray/transmission occlusion, extension UX and screenshots, Isaac Lab CPU and GPU
integration, and supported optional acoustic backends. All six gate processes
passed on the runtime pair and host named above. Unavailable or blocked
sub-probes are retained separately below and are not promoted to passing
capability evidence.

## Gate results

The commands were run from the repository root. Make resolved
`ISAAC_SIM_COMMAND` to `/home/pacquadr/isaacsim/python.sh`,
`ISAAC_LAB_PYTHON` to `/home/pacquadr/IsaacLab/isaaclab.sh -p`, and the JSON
post-check interpreter to `.venv/bin/python`. Each recorded gate log ends in
an exit status of 0.

| Gate | Make target and exact command context | Result | Primary evidence and screenshots | Recorded log |
| --- | --- | --- | --- | --- |
| Isaac Sim audio lifecycle | `make live-isaac-sim-audio` | **Pass** | `outputs/isaac_audio_sensors/S0/S0.3/isaac_sim_live_smoke.json` | `outputs/isaac_audio_sensors/S0/S0.3/gate_live_isaac_sim_audio.log` |
| Live occlusion | `make live-isaac-occlusion` | **Pass** | `outputs/isaac_audio_sensors/S0/S0.3/isaac_occlusion_live_gate.json`; `outputs/isaac_audio_sensors/S0/S0.3/isaac_occlusion_live_gate.viewport.png` | `outputs/isaac_audio_sensors/S0/S0.3/gate_live_isaac_occlusion.log` |
| Extension UX and screenshots | `make live-omniverse-extension-ux-screenshots` | **Pass** | `outputs/isaac_audio_sensors/S0/S0.3/omniverse_extension_live_ux.json`; `outputs/isaac_audio_sensors/S0/S0.3/omniverse_extension_live_ux.viewport.png`; `outputs/isaac_audio_sensors/S0/S0.3/omniverse_extension_live_ux.instruments.png`; scenario capture `outputs/isaac_audio_sensors/omniverse_extension_live_ux.molmo_floorplan1.viewport.png` | `outputs/isaac_audio_sensors/S0/S0.3/gate_live_omniverse_extension_ux_screenshots.log` |
| Isaac Lab live integration | `env -u VIRTUAL_ENV -u CONDA_PREFIX make live-isaac-lab-audio` | **Pass**; one entity-scene sub-probe blocked below | `outputs/isaac_audio_sensors/S0/S0.3/isaac_lab_live_smoke.json` | `outputs/isaac_audio_sensors/S0/S0.3/gate_live_isaac_lab_audio.log` |
| Isaac Lab GPU integration | `env -u VIRTUAL_ENV -u CONDA_PREFIX make live-isaac-lab-audio-gpu` | **Pass**; one entity-scene sub-probe blocked below | `outputs/isaac_audio_sensors/S0/S0.3/isaac_lab_live_smoke_gpu.json` | `outputs/isaac_audio_sensors/S0/S0.3/gate_live_isaac_lab_audio_gpu.log` |
| Optional acoustic backends | Direct Isaac Sim Python import check (no Make target): `/home/pacquadr/isaacsim/python.sh -c 'import pyroomacoustics, soundfile; print("optional backends importable:", pyroomacoustics.__version__, soundfile.__version__)'` | **Pass** | No JSON; the import/version log is the primary evidence | `outputs/isaac_audio_sensors/S0/S0.3/gate_optional_backends.log` |

The screenshot copies under the S0.3 evidence root are byte-identical to their
canonical files under `outputs/isaac_audio_sensors/`. The generic extension
scenario uses the canonical viewport image copied into S0.3; the Molmo
FloorPlan1 scenario has the additional canonical screenshot named in the
table.

## Key extracted facts

### Isaac Sim audio lifecycle

- The gate ran headless in `/home/pacquadr/isaacsim/kit/python/bin/python3` with
  PyTorch `2.10.0+cu128`; the JSON records one visible RTX 4090 and the exact
  `580.159.03` driver/24564 MiB `nvidia-smi` result.
- The JSONL trace contains 9 frames: 3 each for `geometry_only`,
  `tdoa_synthetic`, and `room_acoustics`. Every backend status is `passed`.
- `room_acoustics_available` is true and its status is `passed`; the recorded
  backend version is pyroomacoustics `0.10.1`. The lifecycle also records
  semantic discovery, time-sampled USD motion, and 22 debug primitives.
- The canonical frame trace is
  `outputs/isaac_audio_sensors/isaac_sim_live_smoke.frames.jsonl`.

### Occlusion

- Clear frame 0 is unoccluded. Walled frame 1 is occluded through
  `/World/Wall`, with measured per-microphone attenuation of 20.0 dB within
  floating-point representation. Material frame 3 records 12.0 dB per
  microphone within floating-point representation.
- Debug drawing is `drawn`. The screenshot status is `captured`, frames the
  array, source, and wall from `/World/GateCamera`, and is 44,416 bytes.
- The canonical five-record trace and screenshot are
  `outputs/isaac_audio_sensors/isaac_occlusion_live_gate.frames.jsonl` and
  `outputs/isaac_audio_sensors/isaac_occlusion_live_gate.viewport.png`.

### Extension UX and screenshots

- The extension `isaac_audio_sensors.omni` ran with UI available in the
  headless-or-existing-viewport mode. All 70 recorded workflow steps passed,
  window/menu/action integration passed, OmniGraph registration passed, and
  extension shutdown was `ok`.
- The generic scenario and Molmo FloorPlan1 scenario both have overall status
  `passed` and screenshot status `captured`. Their viewport captures are
  1280x720: 255,559 bytes for the generic scene and 636,143 bytes for Molmo
  FloorPlan1.
- Instruments status is `passed`: one compass needle, four microphone meters,
  and a 420x192 instruments panel captured at 2,314 bytes. The recorded audio
  output is a four-channel, 48,000 Hz, 0.05 s waveform containing 2,400 frames.
- The direct writer recorded and flushed 7 frames for each scenario. The
  canonical traces are
  `outputs/isaac_audio_sensors/omniverse_extension_live_ux.frames.jsonl` and
  `outputs/isaac_audio_sensors/omniverse_extension_live_ux.molmo_floorplan1.frames.jsonl`.

### Isaac Lab CPU and GPU

- Both gates imported the real `isaaclab` module from
  `/home/pacquadr/IsaacLab/source/isaaclab/isaaclab/__init__.py` after
  `AppLauncher` initialization. `AudioArraySensor` is a real `SensorBase`
  subclass, its configuration is a real `SensorBaseCfg` subclass, and no
  fallback classes were used.
- `isaaclab.sh -p` selected
  `/home/pacquadr/IsaacLab/_isaac_sim/python.sh`; the JSON executable resolves
  to `/home/pacquadr/IsaacLab/_isaac_sim/kit/python/bin/python3`, backed by the
  `/home/pacquadr/isaacsim` symlink target. The runtime reports Isaac Sim
  `6.0.1`, Kit build `110.1.2+production.326809.f9bf0dda.gl`, and PyTorch
  `2.10.0+cu128`.
- The CPU run exercised two environments with fixed observation tensors for
  two event slots and four microphones. Its room-acoustics run passed for both
  anchored rooms. GPU-only batched parity and performance sections are
  recorded as `skipped` in this non-GPU-required gate.
- The GPU run placed all sensor and SensorBase bookkeeping buffers on `cuda:0`.
  Its 64-environment batched parity probe passed; the two-environment live
  observation and anchored room-acoustics checks also passed.
- The GPU performance block records `tdoa_synthetic`, 4,096 environments, 50
  steps, batched compute on `cuda:0`, mean `10.924308219982777 ms` and p95
  `11.16095700126607 ms` (10.924 ms and 11.161 ms when rounded to three decimal
  places). These figures are informational in S0.3; S0.4 owns the formal
  performance observation.

### Optional backends

Under the Isaac Sim Python runtime, `pyroomacoustics` `0.10.1` and `soundfile`
`0.14.0` both imported successfully. The separate Isaac Sim lifecycle evidence
also exercised `room_acoustics` successfully rather than treating import alone
as backend execution evidence.

## Blocked and unavailable sub-probes

There is no claim that every sub-probe was available. The six required gate
processes passed, with these narrower limitations preserved in the JSON:

- **Blocked - real Isaac Lab entity scene:** both Lab JSON files record
  `real_lab_rigid_object_probe_status: blocked`. A real
  `InteractiveScene`/`RigidObject` probe raised PhysX CUDA illegal-memory
  errors in a GPU `SimulationContext`; its CPU form produced passing JSON but
  hung during Kit shutdown. The passing required gates therefore use the
  synthetic tensor scene (`scene_is_interactive_scene: false`) while retaining
  real SensorBase classes, live Kit/USD execution, entity binding, selected
  reset/update behavior, and device placement. The recorded next step is an
  isolated process with a hard timeout and artifact handoff, or a stable
  pre-existing InteractiveScene fixture.
- **Unavailable - full-app instruments screenshot:** the extension probe could
  not import `omni.renderer_capture`. No full swapchain/app image was produced.
  The required rendered instruments panel and both scenario viewport captures
  were produced and passed.
- **Unavailable, non-required - Replicator annotator registration:** the
  generic and Molmo scenarios report no supported annotator registration
  method. Replicator runtime availability is true, the writer is registered,
  and each scenario directly wrote and flushed 7 frames; attachment is
  explicitly `not_required` because the audio frame writer uses direct
  extension updates.

The CPU gate's skipped GPU parity/performance blocks are by construction, not
blocked GPU evidence: the separate required-GPU gate executed and passed both
blocks on `cuda:0`.

## Transient Isaac Lab launcher failure

The passing logs contain only the successful reruns; neither contains the
earlier failure text. The orchestrator recorded that the first Lab attempt was
a transient environment-selection failure: with the repository `.venv`
active, `isaaclab.sh` preferred `$VIRTUAL_ENV/bin/python` and reported
`Neither isaaclab nor omni.isaac.lab imported`. `isaaclab.sh` also prefers
`$CONDA_PREFIX/bin/python` when set. Clearing both variables allowed the
launcher to choose `_isaac_sim/python.sh`, which resolved to the selected Isaac
Sim installation. Consequently both Lab reproduction commands below include
`env -u VIRTUAL_ENV -u CONDA_PREFIX`.

## Prior-evidence provenance

`outputs/isaac_audio_sensors/S0/S0.3/pre_run_snapshot/` preserves the three
pre-S0.3 JSON files before these gates overwrote their canonical outputs. In
particular,
`outputs/isaac_audio_sensors/S0/S0.3/pre_run_snapshot/isaac_lab_live_smoke_gpu.json`
records the earlier 4,096-environment figure cited by S0.1: mean
`12.734441657084972 ms` and p95 `13.08835600502789 ms` over 50 steps. It is
provenance, not the S0.3 rerun result. The adjacent pre-run occlusion and
extension JSON files preserve the corresponding earlier evidence states.

## Reproduction

From a checkout of entry revision `161d429`, on the named host with the same
Isaac Sim and Isaac Lab installations, run:

```bash
make live-isaac-sim-audio
make live-isaac-occlusion
make live-omniverse-extension-ux-screenshots
env -u VIRTUAL_ENV -u CONDA_PREFIX make live-isaac-lab-audio
env -u VIRTUAL_ENV -u CONDA_PREFIX make live-isaac-lab-audio-gpu
```

Reproduce the optional-backend import/version check under the same Isaac Sim
Python runtime with:

```bash
/home/pacquadr/isaacsim/python.sh -c \
  'import pyroomacoustics, soundfile; print("optional backends importable:", pyroomacoustics.__version__, soundfile.__version__)'
```

Expected versions are `0.10.1` and `0.14.0`. Each Make target also performs its
recorded JSON status/artifact post-check; the screenshot targets require files
to exist, not merely a successful capture call.

## Boundary and follow-on gate

This is a single-host observation on the named Isaac Sim 6.0.1 / Isaac Lab
3.0.0 checkout pair, exact Kit build, driver, RTX 4090, and local installation
layout. It is not a portable performance, driver, operating-system, GPU, Isaac
runtime compatibility, display-stack, or clean-install claim. The timing block
is recorded here only to identify the live GPU result; warmed repeated samples,
memory, median, worst step, and the formal informational performance baseline
belong to S0.4.

## Verification record

This closeout was prepared from the preserved JSON, logs, screenshots,
environment records, installation `VERSION` files, and symlink targets without
rerunning any Make target or live gate. Every path cited above was checked for
existence. Statuses, versions, executables, GPU/driver facts, frame and step
counts, screenshot sizes and statuses, optional-backend versions, blocked and
unavailable probes, and current/prior performance values were cross-checked
against their sources. The three copied screenshots were compared byte-for-byte
with their canonical counterparts. Git diff and status were checked to confirm
that the only write is this closeout under `docs/development/`.
