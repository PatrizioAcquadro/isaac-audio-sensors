# Continuous Acoustic Clock

## Decision

The September 2026 propagation correction keeps NumPy and the existing optional SciPy/PyRoom stack. The adapter owns continuous emission and reception clocks; the room provider owns image geometry, materials, visibility, and statistical responses. This corrects existing sensing behavior before 07.2, without adding a geometry-acoustics backend.

| Existing solution | Fit for this correction |
| --- | --- |
| [PyRoom](https://pyroomacoustics.readthedocs.io/en/stable/pyroomacoustics.room.html) | Reuse the integrated room solver and RIRs. Scheduling across captures still belongs to the adapter. |
| [SoXR](https://python-soxr.readthedocs.io/en/stable/soxr.html), [pyfar](https://pyfar.readthedocs.io/en/develop/modules/pyfar.dsp.html) | Useful resampling/delay primitives, but neither owns acoustic trajectories and source lifetime. SoXR also introduces resampler latency and an experimental variable-rate interface. No concrete dependency benefit here. |
| [DynamicSound](https://github.com/vlsi-nanocomputing/dynamic-sound) | Relevant retarded-emission model, but the evaluated implementation takes complete trajectories and produces WAV output. Adapting it would substantially overlap the existing runtime. |
| [Acoular](https://acoular.org/acoular/dev/api_ref/generated/generated/acoular.sources.MovingPointSource.html), [Pyroadacoustics](https://github.com/steDamiano/pyroadacoustics) | Useful moving-source references; neither directly replaces the supported contracts and environments. Pyroadacoustics assumes a stationary array. |

This is an integration decision, not a claim that these libraries are generally inferior. Keeping the current stack provides the smallest maintainable change while preserving indoor capabilities and shared consumers.

## Signal and Time

For microphone reception time `t_r`, moving paths solve `t_r - t_e = |microphone(t_r) - source(t_e)| / c`. The source is sampled at `t_e`; the same distance controls travel time and geometric attenuation. Doppler follows the variable delay, without an additional pitch resampler. The existing velocity formula remains an instantaneous diagnostic, not a second signal transformation.

Static paths convolve the RIR with the necessary absolute emission history and select only the requested receiver samples. This preserves delayed onset, file loops, source stops, and acoustic tails across 10/50/100 ms captures, including propagation delays longer than a capture. Removed emitters remain until their in-flight history can drain. No final-WAV normalization, fading, or repair is applied.

Snapshots without a motion plan anchor positions at the window start. Positions interpolate linearly between observations; authored velocity, or the difference between successive poses when velocity is absent, supplies endpoint extrapolation. Bracketed Isaac plans retain their existing segment semantics. Histories are pruned according to travel time and the room tail, and solved-room caching is bounded. A source's asset/schedule/gain is assumed stable over the retained history; consumers must reset after discontinuous edits to those values. Orientations now use shortest-arc quaternion interpolation between available poses. Before the first pose the orientation is held; after the last bracket the latest angular velocity is extrapolated. Bracketed motion plans carry orientation endpoints without changing frame or recording schemas.

Core direct/half-space pressure keeps its existing `1/(4*pi*r)` convention. PyRoom paths retain the provider's `1/r` convention and fractional-delay-filter latency. Relative levels and intermicrophone timing are meaningful; absolute SPL or identical amplitude between providers is not claimed.

## Lifetime and Consumers

`propagate(scene, array_id, time_window)` and immutable `MicrophoneSignalBlock` remain unchanged. The analytic backend adds `reset()`; external plugins acquire no new required method. Per-stage/array state restarts on backwards time, gaps, or environment/channel geometry changes. Explicit reset marks the next block discontinuous. Overlapping windows select existing absolute samples rather than adding duplicate arrivals.

Isaac retains the backend across captures and recreates it on configuration changes. Pose-history teleport, stale-pose, and time-reset signals discard analytic history. The existing Lab reference binding owns one backend per environment and resets only selected environments. Sensor, perception, waveform sinks, and dataset truth/recording all use the same render. This does not implement the 07.2 entity sensing path.

Channel FIR/delay and banded attenuation receive surrounding signal history before the official window is cropped. A demonstrated circular-wrap error in banded attenuation is corrected with a fixed 16,385-tap centered FIR and linear convolution, retaining the existing log-frequency magnitude/zero-phase convention. Noise and electronics still process the final microphone mixture once. Existing effects were not replaced wholesale.

## Approximation Boundaries

- Motion is subsonic. Fixed-point iteration has a bracketed fallback near the speed of sound; supersonic paths and coincident source/microphone positions are rejected.
- Linear fractional sampling is not a band-limited variable-rate resampler. Near-Nyquist motion can attenuate or alias content; the 700/1,000 Hz physical tests do not qualify that region.
- Microphone offsets and polar axes use orientation at reception; source polar axes use orientation at each path's retarded emission time. Constant turns and bracketed rotations pass numerical arrival/partition tests; angular acceleration outside the available pose bracket remains an extrapolation, not measured motion.
- Specular image transforms reuse the provider's solved paths. Visibility and material state refresh at snapshots/segments, so path appearance/disappearance can still be abrupt. Polygon ancestry is recovered from provider images and generating walls; missing visible parents fail explicitly rather than inventing a path.
- Statistical ray-traced tails remain a quasi-static residual response. Finite-output smoke coverage does not qualify diffuse coherence, moving late-field Doppler, or visibility transitions.
- Direct-path entity directivity still weights the complete pair stem; distinct reflection angles are not modeled. Existing finite-window spectral filters retain numerical edge approximations.
- Room responses and trajectories are reconstructed from available snapshots, not a complete past physical scene. Teleports, changed environments, and unsampled acceleration cannot preserve unavailable history.

Numerical propagation tests live in `tests/integration/test_propagation_continuity.py` and `tests/integration/test_rotating_arrivals.py`. The rotation tests cover a closed-form tonal arrival with rotating microphone offsets and a rotating cardioid source, shortest-arc interpolation, and direct/room partition equivalence. The independent motion/indoor DOA comparison and retained estimator decision are documented in [[experiments/04-4-multisource-localization|04.4 Multisource Localization]].
