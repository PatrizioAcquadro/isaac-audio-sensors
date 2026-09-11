# Geometry Acoustics

Current contract: optional prepared-USD producer, Steam 4.8.1 direct/planar
transmission plus corrected native PRA 0.10.1 specular reflections. Experimental
NLOS and joint diffuse pressure are not production options. See
[[implementation_phases/r10-geometry-acoustics-integration|R10]] for remaining work
and [[decisions/robot-audition-fidelity|the approved fidelity boundary]].

## Scene and materials

`AcousticSceneSession(stage, roots=None)` imports composed polygon meshes, concave
faces/holes, supported primitives and instances. Coordinates become meters/Y-up
for Steam. Curved primitives are polygonal approximations; unsupported subdivision,
deformation and point instancers need explicit acoustic representations.

USD is the authority. `ias:acoustic_geometry` replaces an owner's visual geometry;
explicit proxies may be outside roots or hidden. Otherwise eligible physical
surfaces include robot/housing geometry. Guides, technical prims and conventional
duplicate collider representations are excluded with reasons. Unusual duplicate
authoring needs explicit inclusion/proxies; there is no automatic decimation or
bounding-box replacement. Room containment never crops the acoustic scene.

Caches separate geometry, materials, assemblies and poses. USD notices trigger
selective updates; live PhysX poses are read even without USD transform writes.
Static resources are reused; reset/close release owned native state. Native OBJ
coordinates are compared with USD after motion (the former matrix ABI error is fixed).

Coefficient precedence is per family: prim/construction override, bound acoustic
material, configured semantic/name association, scene fallback. Invalid explicit
values fail. Defaults: `pra.hard_surface` absorption, nominal scattering 0.05 and
opaque transmission without a usable curve. Inferred associations are not calibration.

The shared catalog preserves source bands; `resolve_material_coefficients()`
defaults to six analytic bands and `band_centers_hz=None` retains native bands.
There are 23 absorption and seven documented scattering-only presets; the latter
retain their source conditions and must not double-count modeled furniture.
`ias:scattering_material_id` selects scattering independently. Legacy nominal
presets remain explicit choices; generic wood/glass/metal names do not silently
supply transmission. Per-family fallback provenance remains visible.

Steam absorption/transmission use 400/2500/15000 Hz, log-frequency interpolation
and endpoint hold; 15 kHz extrapolation is not measured material data. Scattering
uses the 1 kHz value. Transmission mapping is the qualified amplitude conversion
`10**(-loss_db/20)`, once. `ias:acoustic_partition_id`/component identity group
consistent coplanar fragments; proximity/labels alone do not merge constructions.
Closed/nonplanar assemblies are opaque with an explicit limit. Thick/sequential
construction transmission and the rejected paired-face proxy are not supported.

Python and Kit share USD edits, current edit target, coefficient-family precedence,
proxies, mixed values, persisted defaults and Undo/Redo. Preparation/native verification
states are not evidence of propagated PCM. Operating controls remain 08.3 work.

## Signal producer

`GeometryAcoustics` receives a prepared session and `GeometryAcousticsConfig`,
returns one `MicrophoneSignalBlock`, and feeds unchanged perception. The session
is caller-owned. Native dependencies load lazily and are not bundled/downloaded.
Static TOML/Kit selection is rejected until the prepared-session workflow is supported.

Geometry owns occlusion and rejects precomputed `SourceOcclusion`. Steam reflection
reconstruction is disabled; positive native PRA image orders own specular paths.
The adapter removes PRA's fixed fractional-filter latency once, retaining physical
path delays. Gains and signed source-departure/mic-arrival directivity apply once.
Banded specular material synthesis uses native minimum-phase filters, not measured
material phase. Steam frequency-dependent EQ renders internally at >=48 kHz and
resamples with impulse-area preservation to avoid its unstable 16 kHz Nyquist term;
flat direct/transmission gain uses the native frequency-independent one-tap path.

Receiver-clock convolution retains source/filter history; RIR changes crossfade
without restarting on fragmented reads. This intermediate quasi-static motion
model is not general retarded moving-scene transport. Gaps/reconfiguration reset
context, rewind requires reset, provider replacement resets streams, and array
cursors remain independent. Channel response is included in complete responses.
No observation, recording or Lab schema contains provider paths.

## Native build and reproduction

The qualified Steam source is tag `v4.8.1`, commit
`0da18255cca520771f363ee01f100572b39a308e`, Linux Release/Embree. The production
binding checks its qualified binary because compatible API versioning does not
identify the exact runtime. Different builds require requalification. Historical
SDK builds and installed PRA remain unchanged by extension experiments.

Build the specular bridge from pinned PRA 0.10.1 using existing `room` dependencies,
Eigen and nanoflann headers:

```bash
.venv/bin/python tools/native/build_specular.py \
  --source .venv/lib/python3.12/site-packages/pyroomacoustics/libroom_src \
  --eigen /usr/include/eigen3 --nanoflann /path/to/nanoflann/include \
  --output build/native/libias_specular.so
```

The builder patches a temporary source copy and rejects unmatched anchors. Configure
`library_path` and `specular_library_path`; defaults are reflection order 3,
`max_delay_s=1`, `max_image_candidates=1_000_000`, frame size 128 and transition 32.
The explicit delay bound includes microphone response. Excessive image expansion
fails with an acoustic-proxy/order requirement; no silent truncation. Air absorption
is explicitly unavailable in this intermediate configuration.

Selected-route experimental tooling: `tools/native/build_pathing.py`,
`steam_paths.patch`, `steam_paths.h`, `pathing.py`, `steam_visibility.cpp`,
`retarded_pathing.py`. Private versioned callbacks copy selected route topology,
length, weights and native EQ before aggregation; storage is temporary/thread-local.
Native segment visibility uses immutable scene epochs. Empty route output still
confounds no route with missing probe coverage; rebaking invalidates probe IDs.
These tools are not production propagation or a visualization-derived route solver.

Exact local replay recipes: `local/r10/08_2_intermediate/README.md`,
`local/r10/08_2_extensions/README.md`, `local/r10/08_2_dynamics/README.md`.
[[experiments/geometry-acoustics-admission|The admission record]] owns results;
source/tests remain authoritative for executable behavior.
