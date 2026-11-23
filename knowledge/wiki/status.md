# Current Status

Updated: 2026-11-23. Package version: `3.0.0`.

## What can I run?

| Workflow | Supported use |
| --- | --- |
| Python and CLI | Model microphone arrays, simulate analytic propagation, detect activity, estimate direction, and export multichannel audio. Free-field and half-space runs use Core. Closed rooms use the optional room solver. [Getting started](topics/getting-started.md) |
| Recording and replay | Record aligned microphone samples and observed frames, store optional ground truth separately, validate recordings, recover interrupted sessions, and prepare learning splits. [Recording contracts](topics/public-contracts-and-recording.md) |
| Isaac Sim and Kit | Attach arrays to robots or scenes, discover sources, inspect observations, and record through the extension. Optional native Geometry providers model direct transmission and specular reflections, with selected-route diffraction and diffuse pressure available. [Sim and Kit](topics/isaac-sim-and-kit.md) · [Geometry setup](topics/geometry-acoustics.md) |
| Isaac Lab | Bind a batched sensor to simulated entities and read fixed-shape, masked observations on CUDA. A separate scalar binding provides a reference for parity checks. [Lab integration](topics/isaac-lab-integration.md) |

## What has been demonstrated?

| Evidence | Result and operating conditions |
| --- | --- |
| Single-voice indoor trial | Two 30-second runs on an RTX 4090 delivered 600 observations at about 10 Hz with no lost windows. The full set of active directions was correct on 97.71% and 94.87% of active windows. The trial used one planar array, one line-of-sight voice at 2.25 m, 60 Hz acquisition, a loaded Alex articulation, and 15 Hz RGB/depth. The opt-in profile used 16 kHz audio, 200 ms context, no WPE, and 0.98 coherence. [Combined quality and timing](experiments/consumer-audio-runtime-performance.md) |
| Free-field and competing voices | The short-context profile sustained 10 Hz in the tested free-field workload with a 30 Hz camera. A separate stable-source experiment demonstrated bounded multisource localization. With weak or overlapping indoor voices, the coherence filter can remove genuine directions. [Runtime measurements](experiments/consumer-audio-runtime-performance.md) · [Multisource reference](experiments/04-4-multisource-localization.md) · [Indoor failure cases](experiments/consumer-audio-indoor-quality.md) |
| Geometry | Native provider and live Sim, Lab, and Kit checks cover material transmission, specular paths, optional NLOS/diffuse combinations, motion, reset, and environment isolation in the documented test scenes. [Admission results and limits](experiments/geometry-acoustics-admission.md) |
| Physical comparison and ONR | A 25-take real/simulated comparison verified the common signal-processing path and exposed weak-signal activity disagreement. ONR videos 1–6 were delivered as demonstrations. The production page records the review status of each film and the remaining scenes. [Physical comparison](experiments/physical-signal-comparison.md) · [ONR demonstrations](topics/onr-video-production.md) |

## Open issues

- **Perception.** Reliable weak or overlapping speech, arbitrary rooms and levels, and a uniform 100 ms directional-response bound remain open. Scalar/CUDA agreement measures agreement between implementations. Accuracy requires comparison against independent directions. [Operating envelope](experiments/consumer-audio-operating-envelope.md) · [Motion and lag](experiments/consumer-audio-dynamic-quality.md)
- **Acoustics.** Selected-route diffraction remains uncalibrated. Full-room moving pressure equivalence, general robot-body acoustics, hardware calibration, and physical transfer remain unverified. [Geometry evidence](experiments/geometry-acoustics-admission.md) · [Physical evidence](experiments/physical-signal-comparison.md)
- **Learning and scale.** The single-environment indoor result leaves other camera loads, multi-robot optimizer throughput, and downstream policy performance open. Robot mounting, queues, and task-level acceptance belong to each consumer. [Lab integration](topics/isaac-lab-integration.md) · [Consumer trial](implementation_phases/squadbot-audio-runtime-readiness.md)
- **Development.** Practical realism and randomization, product-wide validation, and semantic perception have separate roadmap phases. [Realism](implementation_phases/09-practical-realism-and-randomization.md) · [Product closeout](implementation_phases/10-end-to-end-validation-and-product-closeout.md) · [Future perception](implementation_phases/11-future-semantic-perception.md)

## Distribution

The v3.0.0 GitHub release at `9aeaea4` includes the Linux x86_64 Kit archive for Kit 110.1 and Python 3.12. The extracted release passed 39 live Kit workflow checks. Native Geometry libraries require separate setup. NVIDIA Community Registry discovery and installation remain unverified. [GitHub release](https://github.com/PatrizioAcquadro/isaac-audio-sensors/releases/tag/v3.0.0) · [Release validation](topics/validation-and-release.md)

PyPI published the wheel and source distribution on October 22, 2026, with provenance for both. The release workflow also passed public-index installation checks on Python 3.10, 3.11, and 3.12 and the Python 3.12 room/FLAC check. [PyPI release files](https://pypi.org/project/isaac-audio-sensors/3.0.0/) · [Release workflow](https://github.com/PatrizioAcquadro/isaac-audio-sensors/actions/runs/39832955999)
