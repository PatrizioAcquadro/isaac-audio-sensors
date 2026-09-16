# Geometry Acoustics

Current contract: optional prepared-USD producer, Steam 4.8.1 direct/planar
transmission plus corrected native PRA 0.10.1 specular reflections. Selected-route
NLOS is an explicit option. A shared PRA diffuse candidate is now available as a
separate experimental opt-in, with admission failed in a conditioned smooth room. See
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
material phase. Normalize the material spectrum before that conversion and apply
its level, geometric spreading and signed directivity afterward: the numerical
log-spectrum floor must not make material phase depend on distance or erase a
negative directivity gain. The lowest band extends to DC, consistently with flat
material synthesis. Steam frequency-dependent EQ renders internally at >=48 kHz and
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

### Native PRA transport qualification interface

The same build now additionally exposes private `ias_pra_transport_abi=1`,
`ias_pra_event_size`, `ias_pra_trace` and `ias_pra_trace_outputs`. The existing
specular ABI remains 1. This is an incident/received energy interface; pressure
construction and admission are separate from native energy capture.

`tools/native/pra_diffuse.h` defines the event layout. A surface event records
energy after absorption and before scattering, native face/plane coordinates,
travel/departure direction, traveled distance, parent event and interaction counts.
Its scattering flag describes the continuation actually sampled. Receiver events
exclude direct and pure-specular paths through the configured ISM order; higher
pure-specular and scattered paths use native finite-radius capture. Do not add
surface-event energy directly to received energy. Pressure synthesis and shared
field admission remain separate gates. Native face coordinates/indices are local
to a scene handle; the surface-field adapter maps them to authored objects.

The private `ias_pra_visibility_abi=1` / `ias_pra_segments_visible` interface uses
PRA polygon intersections for paired segments. Endpoint surface contact is allowed;
intervening opaque faces block from either side, including a partition crossed
while interpolating on a floor. `ias_pra_illumination_abi=1` / `ias_pra_illuminate`
integrates direct illumination at surface quadrature nodes using those same
native visibility, absorption and scattering coefficients. `_pra.Transport`
checks the private ABIs and event layout before borrowing a scene handle.

Capture uses an unbiased specular/Lambertian branch with per-band importance
weights and the incident hemisphere, with no additional `scat_ray` deposit.
All authored polygons obstruct traversal. Forward-intersection and departing-plane
checks avoid tolerance-induced backward hits or spurious immediate re-reflections
across two-sided partitions. Escaping rays can reach receivers before the horizon.
Native receiver-radius sampling is a statistical approximation, not exact point
receiver timing. Its radius convergence is not yet qualified.

Each handle owns its output; copy events and `count * band_count` energies before
the next trace. Output capacity, argument errors and event-budget exhaustion fail
explicitly and clear incomplete captures. Serialize calls on a handle; independent
handles have isolated per-thread random streams. Installed PRA and previous native
builds remain unchanged. Set `IAS_PRA_LIBRARY` when running
`tests/isaac/test_pra_transport.py` against a new extension build.

### Experimental shared PRA diffuse field

`GeometryAcousticsConfig.diffuse=PRADiffuseConfig()` adds diffuse pressure to the
same direct/specular producer. The default is `None`. Combining it with `nlos`
is rejected until Step 4; diagnostics explicitly report `not_admitted`, the
smooth-room decay/observation failure and the remaining moving-room limit.
The public PCM, recording, perception and Lab observation contracts are unchanged.

The first scattering interaction uses deterministic surface quadrature, including
native source/node and node/receiver visibility. Subsequent scattering and higher
or mixed specular contributions use native multibounce energy projected onto
persistent object-local surface elements. Native traversal owns every geometric
interaction. The adapter does not trace replacement paths. Specular image orders
through `reflection_order`, direct first scattering, later scattering and the
remaining specular transport are disjoint energy owners.

Surface elements own random pressure signs, temporal and directional modes.
The seed is independent of ray identities, source identifiers, microphone order
and array grouping. Geometry updates move elements with their object; source and
receiver connections update illumination, visibility and sub-bin delays. The
late specular angular density is a normalized pair of mirrored von Mises–Fisher
lobes. Motion of earlier interactions uses a first-order phase anchor; its
accuracy requires dynamic qualification. This is a statistical approximation.

Defaults are seed 0, 16384 rays, 0.25 m first-scatter spacing, 1 m tail spacing,
4 ms temporal bins, 64 directional modes and specular concentration 64. Explicit
event/node limits fail instead of silently truncating work. Independent octave
pressure modes use a partition of filter **power**, with fractional-delay/filter
energy normalization. There is no fitted room gain or receiver-radius parameter
in pressure evaluation. Diagnostics expose projected/rejected surface energy,
expected received energy and arrivals excluded by `max_delay_s`; these are
simulation diagnostics, never perception inputs.

The producer reuses receiver-clock convolution, including emission-stop tails,
fragmented PCM reads, independent array clocks and reset. This retains the
intermediate quasi-static motion approximation; it does not establish general
retarded moving-room transport. Use an explicit 2 s horizon for the Step 3
qualification, checked against 4 s. Physical/statistical and observation admission
results belong to [[experiments/geometry-acoustics-admission|the admission record]].

### Optional Steam NLOS

`GeometryAcousticsConfig.nlos=SteamNLOSConfig()` enables the native selected-route
component; `None` preserves the intermediate. Use the checked extension binary
as `library_path`, with the existing separate specular binary. Build it with:

```bash
.venv/bin/python tools/native/build_pathing.py \
  --source build/qualification/r9/steam-audio/core \
  --build build/qualification/r9/steam-audio/core/build/r9-release \
  --output build/native/libias_pathing.so
```

The builder preserves the SDK and original provider; temporary debug paths are
normalized so repeated builds against the same inputs are byte-identical. The
binding accepts only the explicitly checked original/extension artifacts, then
checks private route/probe/visibility ABIs. Route ABI 2 retains original endpoint
probe IDs separately from simplified topology. ABI 1 remains readable only for
historical selected-route replays, not automatic preparation.

Steam generates floor probes inside the prepared static bounds, with defaults
`probe_spacing_m=1`, `probe_height_m=1.2`, `max_probes=4096`, `update_hz=100`.
The native floor grid is centered within horizontal cells. Clearance rays exclude
probes on surfaces and corners; graph baking, live path validation and capture use
the same inclusive native segment bounds (10 micrometres numerical tolerance).
This prevents both wall-endpoint shortcuts and discarded interpolation weight
from inconsistent visibility tests. Probe influence radius is at least the generation height. A bounded grid
precheck and actual retained-probe limit prevent unbounded baking. The static
graph excludes explicitly dynamic objects; every selected route is validated
against the actual live scene. This graph is candidate preparation, never an
all-open acoustic rendering. Structural changes rebake; ordinary doors reuse it.
The bridge queries the native probe tree before selecting the nearest eight
visible endpoint probes, with coordinate-based tie ordering. Steam's original
bounded lookup returns traversal order, which can omit one side of a symmetric
screen. Native interpolation weights and native path search remain unchanged.
The bake's total-path bound covers a simple path through the finite graph; the
scene diagonal bounds individual visibility edges, not accumulated bent-path
length. The producer separately enforces `max_delay_s` without truncating arrivals.
Unchanged endpoint/geometry queries reuse their selection; each native search
memoizes ordered probe-edge visibility only within that immutable scene call.
These caches preserve PCM and do not change native weights or search results.
Missing floor, unavailable endpoint coverage and native failures raise errors;
`no_selected_route` does not certify complete physical silence or diffraction coverage.

Each physical route uses emission-time source pose, reception-time microphone
pose, full polyline delay, native EQ, interpolation weight and directional gain.
Equivalent geometric/EQ representations sum their interpolation weights. Immutable
native snapshots test visibility only during the traveled portions of each epoch;
source-stop and native EQ tails drain on the same sample clock. Fixed integer-clock
route updates are independent of PCM read partitioning. Poses without a supplied
motion plan describe window start; timestamped plans reuse the common trajectory
model. No asynchronous two-gate route discovery or exact moving-boundary wave
solution is claimed.

Scene changes must be committed at their explicit simulation-time boundaries;
PCM windows can be subdivided within those geometry epochs. Unobserved past
geometry cannot be reconstructed from a later live USD pose. Structural rebaking
does not reset already-emitted routes or reuse old probe IDs as persistent identity.
When an ordinary opening reveals a route, still-retained emissions from previously
unselected intervals can use it if each segment is clear at traversal time. This
does not reassign LOS or already-assigned intervals, duplicate their contributions,
or rewrite PCM preceding discovery. Native weights/EQ at discovery remain the
bounded interpolation approximation for those previously unselected emissions.
Probe refinement measurably changes door-transition pressure; selected-route
transport qualification does not establish calibrated diffraction or converged
full-room pressure. See [[experiments/geometry-acoustics-admission|refinement evidence]].

The final mixture retains existing PCM/observation/recording schemas. Optional
geometry diagnostics contain probe counts, rebuild counts and per-source/channel
coverage states; they are not observations. The NLOS microphone response currently
supports gain, polarity and nonnegative delay. Zero-phase microphone FIR/negative
delay is explicitly unqualified for this causal component; the intermediate keeps
its existing response support. Full combined-producer qualification remains Step 4.

Production bindings live in the package; `tools/native/pathing.py` and
`retarded_pathing.py` retain lightweight import compatibility for historical replay
consumers. `tools/native/steam_paths.patch`, `steam_probes.cpp`,
`steam_visibility.cpp` and the private header/build recipe remain maintained.

Exact local replay recipes: `local/r10/08_2_intermediate/README.md`,
`local/r10/08_2_extensions/README.md`, `local/r10/08_2_dynamics/README.md`.
[[experiments/geometry-acoustics-admission|The admission record]] owns results;
source/tests remain authoritative for executable behavior.
