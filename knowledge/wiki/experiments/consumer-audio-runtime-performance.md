# Consumer Audio Runtime Performance

Phase [[implementation_phases/squadbot-audio-runtime-readiness|7.2]] measures the
SDK's 200 ms, no-WPE listening profile independently of the parallel indoor
quality work. This page owns latency, lifecycle and environment-scale evidence.
[[experiments/consumer-audio-dynamic-quality|Dynamic quality]] owns the acoustic operating
limits. A timing pass cannot qualify room accuracy or the consumer's policy.

## Results — 2026-10-09

Measured on an RTX 4090 (24 GiB), Intel i9-14900KF, 64 GB RAM, driver
580.178.04, PyTorch `2.10.0+cu128` / CUDA 12.8, Isaac Sim `6.0.1-rc.7` and
Isaac Lab `3.0.0` at `2e44ddb2e1`. BLAS/OpenMP use one host thread.
SDK baseline is `6c65a69`; the acquisition change is `dcd4cf6` on
`PatrizioAcquadro/audio-runtime-performance`. App/asset/shader caches on the host
were warm; each qualification run starts a fresh Kit process. These are not
power-on cold-cache results. No CPU inference fallback, push or branch merge.

The initial free-field profile **passes the bounded interactive timing gate**
with 60 Hz physics/acquisition and a **30 Hz shared RGB camera**. Four clean
30-second runs deliver 1,200 observations, including 1,160 after the first
second and 712 returned-active updates. They sustain 9.983–9.988 updates per
wall second, lose no audio windows and declare no discontinuities. SDK p95 is
32.86–33.68 ms across steady updates and 34.98–36.86 ms on returned-active
updates. First active CUDA calls remain included in the tails and are reported
separately: 68.75–83.35 ms. This is sustained generated-audio delivery under the
declared workload, not a guarantee for arbitrary scenes or continuous/multivoice
content. About 61% of steady windows return active observations.

| Workload / code | Updates/s real | SDK p95 / p99 / max, ms | Deadline p95 / max, ms | End scheduling backlog |
| --- | ---: | --- | --- | --- |
| 60 Hz camera, baseline | 9.562 | 33.74 / 41.62 / 77.65 | 1251.92 / 1373.95 | 82 ticks |
| 60 Hz camera, optimized | 9.741 | 33.95 / 41.71 / 73.92 | 705.00 / 798.86 | 47 ticks |
| 30 Hz camera, optimized final | 9.988 | 32.86 / 38.58 / 83.35 | 43.51 / 94.04 | 2 ticks |

The final row is `interactive30-release-check`; the other three 30 Hz runs
have deadline p95 45.02–46.28 ms and maxima 78.03–80.92 ms. No steady delivery
exceeds the 100 ms period. Backlog peaks at five ticks during initial rendering;
terminal two/three ticks reflect the final synchronous perception call and are
recovered between updates. Delivery drift stays within 19.45–34.61 ms, rather
than accumulating across the run. The frame-count control confirms exactly
900 camera updates in the final 30-second runs. The 60 Hz camera workload
**does not qualify**: meeting the SDK compute p95 alone hides substantial queue
growth. Camera cadence selection is a declared workload choice, not an audio
algorithm or localization-quality change.

In the final run, wall age from the oldest 100 ms observation-window boundary
has p95 134.26 ms and maximum 184.76 ms. This differs from both 100 ms of
represented audio and the 200 ms localization history; neither is a wall-clock
latency measurement.

Geometry overhead was the demonstrated reusable optimization target. Default
mounts now skip zero translations and identity quaternion products while
preserving normalization; constant local microphone axes stay on CUDA. In the
same synchronized SDK diagnostic, geometry mean falls 2.901 → 1.536 ms and
acquisition including buffering 3.818 → 2.456 ms. Buffering remains about .16 ms;
perception including projection remains about 22.6 ms across active/quiet calls.
Full loaded acquisition mean falls 4.443 → 3.312 ms at 60 Hz camera cadence.
All 18 public tensor fields across 300 matched updates and all received PCM are
**exactly identical** before/after. Four exact CUDA mount controls cover default
and nonidentity transforms. Localizer, precision, thresholds, capacity, clocks,
masks and reset behavior are preserved.

The final separate diagnostic runs physics, camera reads and source/receiver
motion while fencing existing audio scopes. Exclusive CUDA propagation mean is
.613 ms, buffering .204 ms, activity 2.592 ms, sparse fitting 21.435 ms, event
extraction .614 ms and projection .149 ms. No-WPE's dtype conversion costs
.022 ms; it is not WPE execution. SDK write is separately timed. These small
instrumented samples locate cost; they are not the qualification distribution.
Source-array H2D construction is about .27 ms at initialization; the largest
localization dictionary transfer/construction is about .43 ms. During free-field
acquisition, PCM stays on CUDA. Copying every public output field to CPU costs
about .18–.20 ms p95 in the qualified runs. Fenced tensor-construction timings
include allocation/conversion, not only DMA.

Fresh-process app startup takes 4.08–4.11 s and simulation/sensor initialization
about .80–.82 s without profiling. The profiled baseline's initialization cannot
be used as a fair startup improvement comparison. Audio context is ready at
200 ms, before this clip's first received onset at 1.31 s. First activation costs
above are not folded invisibly into averages. Sensor reset costs about 2.2 ms;
post-reset first active calls take roughly 24–31 ms after CUDA initialization.
Reset preserves the waveform/content sequence and restarts only the audio clock;
the physical scene continues. Final allocated Torch peak is about 36 MB; the
whole Kit process peaks around 4.9 GB GPU framebuffer and 7.7–7.9 GB host RSS.

For the first two runs, 12 received onsets per run have no missed source-correct
responses. Audio-clock response p95 is 100 ms for this repeated clip, distinct
from the earlier dynamic-quality screen's 200 ms. Receipt-to-SDK **wall upper
bound** p95 is 135.62 / 143.58 ms, maxima 159.46 / 162.24 ms. Response from the
intended paced onset has p95 150.33 / 157.62 ms and maxima 168.03 / 170.92 ms.
The first CUDA activation is retained; later activations are cheaper. These are
12 repeated segments in a bounded motion sequence, not independent voice trials
or physical latency. Diagnostic past-direction lag is 100 ms with approximately
1.5 degree mean / 3.3 degree p95 residual; current-time directions are unchanged.

## Environment throughput

Unpaced eight-second runs include audio startup/first activation but exclude
app/scene initialization and the separately measured reset. They retain the
heavier **60 Hz shared camera**, 64 bodies per environment, one independently
moving voice per environment and source-independent 32-slot output capacity.
All selected runs have clean GPU monitoring.

| Environments | Baseline aggregate sim s / real s | Optimized aggregate sim s / real s | Real s / aggregate sim s | Torch peak MB | Kit framebuffer peak MB |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | excluded contaminated run | 1.053 | .950 | 25.20 | 4926 |
| 4 | 3.370 | 4.273 | .234 | 30.83 | 4928 |
| 16 | 14.252 | 16.635 | .060 | 56.42 | 5236 |

The optimized four-environment result uses the clean repeat; the original
contaminated run is preserved and excluded. The clean 4/16 comparisons improve
about 27% / 17%. Whole-update SDK p95 is 29.76 / 27.63 / 33.35 ms for 1/4/16;
first active maxima are about 71–73 ms. Small batches amortize dispatch and shared
geometry/dictionaries; the single camera and simulation overhead remain material.
Memory is not the limiting resource at these points. These are SDK/simulation
rollout rates, with natural-speech quiet intervals and one shared camera, not
optimizer throughput, a per-environment camera fleet or a promised training scale.
Unpaced deadline references are virtual audio schedules and must not be read as
real-time response latency; the current runner omits paced-onset response there.

## Native-stage boundary and validation

The reproduction path also runs actual Geometry production from a read-only
retained stage. `geometry-retained-stage-01` uses
`local/r10/preparation/controls/E1_R05.usda` from the main checkout, 36 acoustic
triangles, array position (3, 2.5, 1.2), third-order reflections and the same
200 ms no-WPE localizer. In the separate loaded moving-source diagnostic,
CPU-native generation mean/p95 is 12.82 / 14.25 ms per 60 Hz chunk, pose D2H
about .392 ms, PCM H2D tensor construction .099 ms and buffering .206 ms.
The short live run yields only 6.45 observations per real second; SDK p95 is
41.27 ms but startup reaches 112.51 ms and acquisition peaks at 586 ms.
It **does not qualify**, and its acoustic quality is not assessed here.

The default synthetic six-box room is a different, more expensive geometry:
moving native generation mean is about 103 ms. Its static diagnostic had looked
cheap, which is why the final diagnostic explicitly advances motion and physics.
Both runs are preserved. Scene geometry and moving-path cost matter more here
than PCM transfer; a static replay or free-field timing pass cannot qualify the
selected indoor configuration. No native/localizer rewrite overlaps the indoor
work. After integration, repeat a longer loaded run on its actual stage and
settings before accepting that profile for interactive use.

Host checks: 682 unit/contract, 367 integration and 56 release cases pass,
including ten metric/contamination controls. The actual CUDA/Isaac lane passes
265 cases, including four new exact mount controls and retained scalar, custom
directivity, capacity, partial-reset and continuity tests. Ignored native binaries
are linked into this worktree's ignored build paths and read from the main
checkout; imports still resolve to this worktree's source. The initial lane
without those links passed 186 with 79 skips; it is not the final validation.
Wiki link/whitespace/lint checks pass. PyTorch CUDA kernel/copy tracing remains
unavailable because Kit owns a CUPTI subscriber; missing device trace events are
explicitly marked, not reported as measured zero cost. Fenced wall stages and
CUDA endpoint events work and support the latency results.

## Combined indoor work — 2026-10-14

The integrated six-box room bottleneck is the native image-source visibility
solve: approximately 101 ms per moving 60 Hz chunk in the isolated CPU diagnosis.
The bridge now tests the necessary complete polygon-intersection chain before
scanning obstructions. Reverse polygon windings still select both reflecting
sides, but each polygon is tested only once as an obstruction. The complete
visibility test, reflection order, paths, material response and DSP remain in use.

Across 180 moving poses, all image positions, damping, orders, visibility and
**visible-path** departure vectors match exactly; invisible departure vectors
are undefined native workspace and are excluded. Full generated PCM is bitwise
identical. Warm producer median/p95 falls from 99.61/101.38 to 8.45/8.95 ms.
Fifty-five native specular, propagation, scene and diffuse transport controls pass
against the rebuilt library. Original libraries and failed intermediate attempts
remain in `build/validation/indoor-runtime-readiness/`.

These are optimization/preservation results, not a combined interactive pass.
The first live diagnostic also detects another CUDA client and is excluded from
qualification. Loaded dynamic quality, clean delivery and the consumer workload
must still be measured together. The compiled bridge must be rebuilt using the
updated `tools/native/build_specular.py` and `specular.cpp`; changing Python alone
does not install this optimization in an existing native library.

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
with default RTX/DLSS settings at 30 or 60 Hz. Camera reads and actual frame counts
are included in the declared cadence. The scene uses
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

Integrated-main checks and the new native-room timing failure are recorded in
[[implementation_phases/squadbot-audio-runtime-readiness#Integration on main — 2026-10-14|integration validation]].
The original runtime worktree retains all historical artifacts listed below.

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
  --seconds 30 --paced --workload render --camera-hz 30 --diagnostic-updates 0
```

Use a separate short run with `--diagnostic-updates 8` for synchronized stage
attribution and Chrome/CUDA profiling; never substitute profiler timings for the
loaded delivery result. Add `--profile-initialization` to separately fence array
transfer/construction at startup. Repeat the paced single-environment run in a fresh
process. Run unpaced `--envs 1`, `4`, `16` with identical duration/workload for
aggregate simulated seconds per wall second and memory scaling. Throughput is
simulation plus the SDK observation loop, not optimizer throughput.

For the integrated indoor profile, rerun these commands from the integrated
checkout with `--context-s .2 --spatial-coherence .98` and omit `--wpe`.
The coherence flag defaults to `None`; omitting it preserves this experiment's
unfiltered profile. Add `--geometry-library`, optional `--specular-library`, and
the selected `--reflection-order` to exercise isolated 6x5x3 m CPU-native rooms
and PCM transfers. The six-box fixture's absorption .4/scattering 0 and declared
load must be disclosed. Prefer `--acoustic-stage /path/to/selected.usda` and
`--array-position x y z` for the selected consumer scene; the stage is read without
saving or changing it, and only its `/World` acoustics enter the producer.
The rendered physics workload stays separate. Disclose scene geometry/materials,
source trajectories and camera cadence. Repeat the selected indoor quality comparator on
identical received PCM and retain current-time quality, errors and misses.
These branch results cannot qualify a future localizer/configuration by transfer.

Artifacts are separate under this worktree's ignored
`build/validation/runtime-performance/`: baseline/optimized 60 Hz render reports,
four clean `interactive30-*` qualifications, scale reports and clean repeats,
received PCM and all public observation tensors, lifecycle rows/onsets,
`observation-preservation.json`, native-stage controls, profiled scopes/traces,
GPU monitor samples and validation logs. Failed `dev-*` and contaminated runs
remain intact. Originals in the main checkout and `knowledge/raw/` are untouched.

[[index|Wiki index]]
