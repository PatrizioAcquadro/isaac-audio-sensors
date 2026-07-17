# S0.4 performance observation closeout

| Field | Recorded value |
| --- | --- |
| Subphase | `S0.4` - Performance observation |
| Closeout date | 2026-07-16 |
| Entry revision | `ec2e1fa` |
| Instrumentation commit | `1d663c9` - `S0.4: record raw perf samples and add baseline aggregator` |
| Host environment | Ubuntu 24.04.4 LTS; Linux `6.8.0-136-generic`; x86_64 |
| GPU and driver | NVIDIA GeForce RTX 4090; driver `580.159.03`; `cuda:0` |
| Isaac Sim and Isaac Lab runtime | Isaac Sim `6.0.1-rc.7` via the Isaac Lab `3.0.0` checkout launcher with `env -u VIRTUAL_ENV -u CONDA_PREFIX` |
| Torch runtime | PyTorch `2.10.0+cu128` |
| Evidence root | `outputs/isaac_audio_sensors/S0/S0.4/` |

The host and runtime are the same reference installation recorded by
`docs/development/closeouts/S0/s0_3_live_baseline.md`. Each run JSON also
records Isaac Sim app version `6.0.1`, Kit build
`110.1.2+production.326809.f9bf0dda.gl`, the loaded Isaac Lab extension
metadata version `6.1.14`, and the Isaac Lab import from the named `3.0.0`
checkout.

## Scope and frozen scenario

This closeout records the performance observation required by Section 6.3 of
`docs/final_sensor_development_plan.md`. The frozen scenario is the existing
`_batched_perf_evidence` phase in
`scripts/live_isaac_lab_audio_smoke.py`:

- 4,096 environments on `cuda:0` use a deterministic synthetic, duck-typed
  entity tensor scene with a four-microphone `quad_front` array and two source
  entities;
- `AudioArraySensor` uses the `tdoa_synthetic` backend, with `compute_path`
  configured as `auto` and checked to resolve to `batched`;
- every update uses `dt=0.02` and `force_recompute=True`;
- 10 untimed warmup updates run first, followed by an initial
  `torch.cuda.synchronize()` and reset of the CUDA peak-memory counters; and
- each of the 50 timed steps measures wall-clock duration around one sensor
  update and its following `torch.cuda.synchronize()`. Thus asynchronous CUDA
  work launched by the update is complete before the sample ends.

The observation measures the sensor's batched synthetic TDOA observation path.
It does **not** generate waveforms and does not include an Isaac Lab
`InteractiveScene`, rigid-body simulation, or other InteractiveScene physics.
The scene supplies synthetic entity pose tensors; it is not the blocked real
entity-scene sub-probe described by the S0.3 closeout.

Instrumentation commit `1d663c9` additively extended the existing performance
evidence with raw samples, median, worst step, warmup count, and CUDA
peak-memory facts. It also added the standard-library aggregator
`scripts/collect_s0_performance_baseline.py` and its pure tests in
`tests/test_perf_baseline_aggregate.py`. The existing mean-budget pass/fail
logic was not changed.

## Per-run observations

All three launcher logs end in `run<N> exit: 0`, and all three JSON files have
top-level and performance status `passed`. Timing figures below are milliseconds
per step and retain the JSON values at full recorded precision. MiB values are
byte counts divided by 1,048,576; the byte values are the primary recorded
facts.

| Run | Mean (ms) | Median (ms) | p95 (ms) | Worst (ms) | CUDA max allocated | CUDA max reserved | CUDA total memory | Device | Compute path |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `run1.json` | 10.966777660214575 | 10.94308749998163 | 11.263727999903494 | 11.356719998730114 | 13,474,304 B (12.85009765625 MiB) | 27,262,976 B (26 MiB) | 25,215,303,680 B (24,047.1875 MiB) | `cuda:0` | `batched` |
| `run2.json` | 11.04019626021909 | 10.981526498653693 | 11.500238000735408 | 11.670615000184625 | 13,474,304 B (12.85009765625 MiB) | 27,262,976 B (26 MiB) | 25,215,303,680 B (24,047.1875 MiB) | `cuda:0` | `batched` |
| `run3.json` | 10.627432100081933 | 10.552366000410984 | 10.954681998555316 | 11.032790000172099 | 13,474,304 B (12.85009765625 MiB) | 27,262,976 B (26 MiB) | 25,215,303,680 B (24,047.1875 MiB) | `cuda:0` | `batched` |

The peak allocated and reserved figures cover the timed sensor phase after the
post-warmup peak-counter reset. The total-memory field comes from the CUDA
device properties and is not a peak-use measurement.

Primary per-run evidence is preserved in:

- `outputs/isaac_audio_sensors/S0/S0.4/run1.json` and `run1.log`;
- `outputs/isaac_audio_sensors/S0/S0.4/run2.json` and `run2.log`; and
- `outputs/isaac_audio_sensors/S0/S0.4/run3.json` and `run3.log`.

## Pooled observation

`outputs/isaac_audio_sensors/S0/S0.4/perf_baseline_aggregate.json` pools all
150 raw step-duration samples and records:

| Samples | Mean (ms) | Median (ms) | p95 (ms) | Worst (ms) |
| ---: | ---: | ---: | ---: | ---: |
| 150 | 10.878135340171866 | 10.901460000241059 | 11.228774001210695 | 11.670615000184625 |

The aggregate `warnings` list is empty. The statistics recomputed from each
run's raw samples therefore agree with the recorded per-run statistics within
the aggregator's checked tolerance, and the three scenario identities agree.
`outputs/isaac_audio_sensors/S0/S0.4/aggregate.log` records
`aggregate exit: 0`.

## Observation variance

Across the three runs, the fastest run by mean was run 3 at
`10.627432100081933 ms`; the slowest was run 2 at `11.04019626021909 ms`.
The observed slowest-minus-fastest mean spread was `0.413 ms` when rounded to
three decimal places. This records run-to-run variation only; no cause is
assigned from these three observations.

## Prior-evidence provenance

For provenance, the pre-S0 snapshot at
`outputs/isaac_audio_sensors/S0/S0.3/pre_run_snapshot/isaac_lab_live_smoke_gpu.json`
records mean `12.734441657084972 ms` and p95 `13.08835600502789 ms`. The S0.3
single run at
`outputs/isaac_audio_sensors/S0/S0.3/isaac_lab_live_smoke_gpu.json` records mean
`10.924308219982777 ms` and p95 `11.16095700126607 ms`. Those artifacts are
retained as provenance, not promoted to cross-run or causal comparison claims.

## Reproduction

From a checkout of entry revision `ec2e1fa`, on the named reference host and
runtime, run the following command separately for `<N>` equal to `1`, `2`, and
`3`:

```bash
env -u VIRTUAL_ENV -u CONDA_PREFIX PYTHONPATH="$PWD/src:$PYTHONPATH" ~/IsaacLab/isaaclab.sh -p scripts/live_isaac_lab_audio_smoke.py --require-gpu --perf-budget-ms 20 --out outputs/isaac_audio_sensors/S0/S0.4/run<N>.json
```

Then aggregate the three preserved runs with the supplied aggregator command:

```bash
.venv/bin/python scripts/collect_s0_performance_baseline.py --runs run1.json run2.json run3.json --out perf_baseline_aggregate.json
```

## Boundary and follow-on gate

These results are an informational baseline observed on the named reference
host. The `20 ms` acceptance gate belongs to phase `P1`, not S0.4. The recorded
S0.4 statuses do not turn this observation into a portable performance promise
for other GPUs, drivers, operating systems, Isaac Sim or Isaac Lab versions,
workloads, scene types, or installation layouts.

## Verification record

This closeout was prepared from the preserved JSON and logs, the benchmark and
aggregator source, instrumentation commit `1d663c9`, the S0.3 closeout and
performance artifacts, and Section 6.3 of the development plan. No GPU work,
Make target, or test was run. Every cited path was checked for existence. The
three 50-sample arrays, per-run statistics, pooled 150-sample statistics,
scenario identity, status, device, compute path, memory bytes, and empty warning
list were cross-checked against the JSON sources; MiB values were independently
recomputed from the byte fields. Git diff and status were checked to confirm
that the only write is this closeout under `docs/development/`.
