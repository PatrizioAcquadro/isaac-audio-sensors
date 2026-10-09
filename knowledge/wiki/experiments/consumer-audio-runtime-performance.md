# Consumer Audio Runtime Performance

Phase [[implementation_phases/squadbot-audio-runtime-readiness|7.2]] measures the
SDK's 200 ms, no-WPE listening profile independently of the parallel indoor
quality work. This page owns latency, lifecycle and environment-scale evidence.
[[consumer-audio-dynamic-quality|Dynamic quality]] owns the acoustic operating
limits. A timing pass cannot qualify room accuracy or the consumer's policy.

## Measurement protocol

`tools/validation/audio_runtime_performance.py` launches the actual Isaac Lab
runtime and refuses CPU fallback or SDK imports outside its worktree. It holds
`/tmp/isaac-audio-sensors-gpu.lock` from before CUDA/Kit startup through shutdown.
Each output directory must be new. The source WAV is copied without changing its
bytes into that directory to satisfy the SDK's public-path boundary. Original
inputs and existing evidence remain read-only.

The square array uses XY offsets at +/-33 mm, 16 kHz PCM, acquisition at 60 Hz,
observations every six acquisitions (10 Hz), DOA enabled, -60 dBFS activity,
32 observation slots and two candidate slots. Capacity is independent of source
count. A natural-speech source moves on a 2.25 m arc and the receiver rotates;
scaled environments span 1.5–3 m and different motion phases. Poses are observed
CUDA tensors; private motion and received PCM enter scoring only.

The declared rendering workload has 64 moving rigid bodies per environment,
collision geometry, dome/distant lighting and one shared RGB camera at 640x480
and 60 Hz. A camera read is included in every simulation step. The scene uses
local primitives without downloads. Physics-only and audio-only controls omit
the camera or both bodies and camera. This is a bounded synthetic load, not a
robot, policy update, per-environment camera fleet or full training experiment.

The clocks and endpoints are deliberately separate:

- **Simulation time:** `SimulationContext.get_physics_step_count() * dt`, including scene
  settling. **Audio time:** per-episode sample clock, advancing by 1/60 s on each
  acquisition and restarting on sensor reset. Resetting audio does not rewind
  physics. **Wall time:** monotonic `time.perf_counter()`.
- **Window end:** after the final physics/camera step for a 100 ms window and
  before acquiring its final PCM chunk. **SDK availability:** `sensor.data` has
  returned and a CUDA fence confirms all output tensors ready. `sdk_ready_ms`
  includes final generation/acquisition, buffering, perception and SDK write.
  A CUDA event also records final buffered-PCM to SDK availability separately.
- **Consumer CPU copy:** all public fields copied after SDK availability; this
  additional transfer is reported separately. Free-field production and mixture
  perception remain CUDA-resident; host control and synchronized scalar checks
  are included. The optional Geometry producer runs native CPU propagation,
  transfers poses to CPU and received PCM to CUDA; it has no CUDA producer.
- **Delivery deadline:** origin plus the intended audio-window end in paced
  runs. Deadline-to-SDK cost includes scheduling slip and the final simulation
  step. The audio observation covers 100 ms; localization uses 200 ms of causal
  history. Wall age from the preceding window boundary is recorded separately.
  A fitted past-direction lag is diagnostic and never shifts observation time.

The SDK is synchronous and stores bounded PCM history. It has no asynchronous
producer queue. The runner reports overdue simulation ticks, drift of delivery
deadlines, acquired-minus-processed samples, discontinuities and skipped 100 ms
windows. A slow serial run must not masquerade as sustained real time merely
because it produces ten observations per simulated second. The interactive gate
also requires >=9.8 updates per wall second, no steady delivery above 100 ms,
bounded terminal backlog and no accumulated drift above one observation period.
Small within-period delays are scheduling backlog, not discarded updates.

All per-step/per-update rows survive, along with p50/p95/p99/max and threshold
exceedances. The first second, first activity/direction update, app initialization,
sensor initialization, reset cost and restarted observations are reported
separately. Rendering settles for three simulated seconds without advancing
audio. GPU fences, PCM capture and CPU observation copies make this a conservative
instrumented consumer; these costs are disclosed, not subtracted from gates.

Received onset is the first audible 10 ms energy bin after at least 200 ms of
quiet at -60 dBFS. Its wall receipt is bracketed by the acquisition call containing
that bin. First source-correct direction must occur before the next onset and
within two audio seconds; misses remain explicit. Reports retain audio-clock
response, receipt-to-SDK wall bounds and response from the intended paced onset.
These are generated-audio consumer responses, not physical microphone timestamps.
Ten-millisecond reference bins and 100 ms observation quantization limit precision.

`nvidia-smi pmon` samples external compute and graphics activity throughout. A
sample with another compute client or >=5% external SM activity makes that run
contaminated and unsuitable for qualification. Unknown/failed monitoring also
prevents qualification. Desktop clients and raw samples are retained. The lock
coordinates these two chats; it cannot reserve the machine from other users.

## Reproduction and indoor handoff

Set runtime/input paths explicitly; `IAS_PERF_INPUT` may point to the preserved
main checkout. `PYTHONPATH` must start with this worktree's `src`, while ignored
runtime dependencies may come from the main checkout in read-only mode.

```bash
IAS_PERF_DEPS=/home/pacquadr/Desktop/isaac-audio-sensors/build/validation
IAS_PERF_INPUT=/home/pacquadr/Desktop/isaac-audio-sensors/local/sdk-dynamic-quality/assets/target_1.wav
export PYTHONPATH="$PWD/src:$IAS_PERF_DEPS/phase06_1/runtime_deps:$IAS_PERF_DEPS/continuity_runtime_deps"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONUNBUFFERED=1
"$ISAAC_LAB_ROOT/isaaclab.sh" -p tools/validation/audio_runtime_performance.py \
  --asset "$IAS_PERF_INPUT" --out build/validation/runtime-performance/new-render-run \
  --seconds 30 --paced --workload render --diagnostic-updates 0
```

Use a separate short run with `--diagnostic-updates 8` for synchronized stage
attribution and Chrome/CUDA profiling; never substitute profiler timings for the
loaded delivery result. Repeat the paced single-environment run in a fresh
process. Run unpaced `--envs 1`, `4`, `16` with identical duration/workload for
aggregate simulated seconds per wall second and memory scaling. Throughput is
simulation plus the SDK observation loop, not optimizer throughput.

After integrating the indoor work, rerun these commands from the integrated
checkout with the **selected** context/WPE settings (`--context-s` and `--wpe`
where applicable). Add `--geometry-library`, optional `--specular-library`, and
the selected `--reflection-order` to exercise isolated 6x5x3 m CPU-native rooms
and PCM transfers. The fixture's absorption .4/scattering 0 and declared load
must be disclosed. Also measure the consumer's selected scene/provider if it
differs from this fixture. Repeat the selected indoor quality comparator on
identical received PCM and retain current-time quality, errors and misses.
These branch results cannot qualify a future localizer/configuration by transfer.

[[index|Wiki index]]
