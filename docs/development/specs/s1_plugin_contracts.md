# S1.3 Plugin Contracts

Status: implemented for Stage 1 phase S1.3. These contracts implement Section
4.6 of the final sensor development plan under the ownership and binary
boundaries locked in S1.1. They are generic sensor interfaces: no downstream
ontology, transport, robot behavior, learned classifier, or platform-specific
binary enters the base package.

## Public protocols

| Protocol | Ordered input | Output | Structural requirement |
| --- | --- | --- | --- |
| `PropagationBackend` | `AudioSceneSnapshot`, `MicrophoneArraySpec`, `AudioTimeWindow` | `AudioSensorFrame` | `backend_id` and the unchanged `simulate(...)` surface; every existing backend satisfies it without inheritance |
| `DoaEstimator` | NumPy samples `[channel, sample]`, matching array-local microphone XYZ `[channel, 3]` in metres, sample rate in Hz | `(DoaEstimate, diagnostics dict)` | Channel row order binds samples to geometry; result uses the public array-local bearing/elevation convention |
| `AudioFeatureExtractor` | NumPy samples `[channel, sample]`, sample rate in Hz | `(numpy.ndarray, metadata dict)` | Tensor shape and dtype exactly match the declaration's fixed output contract |

The protocols use structural typing and import only the pure-Python core and
NumPy. They do not import Isaac, torch, GPU libraries, protobuf, or optional
acoustic dependencies.

## Declaration fields

`PluginDeclaration` is a frozen, slots-based dataclass. Construction fails
closed for invalid values.

| Field | Contract |
| --- | --- |
| `plugin_id` | Stable, non-empty string containing no whitespace |
| `kind` | `propagation_backend`, `doa_estimator`, or `audio_feature_extractor` |
| `fidelity_level` | `L0` through `L4`, or `None` when the plugin is not itself a propagation level |
| `required_dependencies` | Unique Python import names; missing optional imports are reportable capabilities, not registration failures |
| `supported_devices` | Non-empty unique subset of `cpu`, `cuda` |
| `supported_profiles` | Non-empty unique subset of `training_features`, `waveform_fidelity` |
| `deterministic` | Strict boolean promise checked for fixture-capable signal plugins |
| `output_contract` | Mapping with `shape` and `dtype`; backends declare `AudioSensorFrame`, DOA declares scalar `DoaEstimate`, feature extractors declare a fixed tensor shape and NumPy dtype |
| `description` | Non-empty human-readable capability summary |
| `provenance` | Importable-style Python module path naming the implementation origin |

## Registry semantics

Registration records the dependency state using import discovery without
importing the dependency module. A missing dependency does not erase the
plugin from capability inventory. Explicit availability probes and `resolve`
perform real imports and update the recorded state. This mirrors the existing
room backend's `is_available()` boundary and makes an unavailable declaration
visible while preventing its use.

`resolve(kind, id, device=..., runtime_profile=...)` validates, in order: kind
and id, current dependency imports, device, and runtime profile. Failures are
`ConfigValidationError` instances with the plugin id and rejected capability
or missing import name. An import name such as a standard-library module is
treated exactly like every other dependency: if it imports, it is available;
there is no special allowlist or claim override.

Factories remain lazy. The module-level registry does not instantiate backend
factories or import `pyroomacoustics`. The legacy `get_backend(id, **kwargs)`
is a thin registry lookup using `instantiate_registered`; this deliberately
preserves its frozen behavior of constructing room backend objects before the
optional dependency is checked by `simulate`. New capability-aware consumers
use `resolve` and fail before construction when dependencies or combinations
are unavailable.

`validate_declaration` constructs a test instance. Propagation factories are
checked structurally and against their declared backend id. DOA estimators and
feature extractors run on the same seeded, ordered waveform/geometry fixture;
the result container, output shape/type, dtype, and diagnostics mapping are
checked. A plugin declaring `deterministic=True` is built and run twice and
must produce recursively identical results. Backend determinism remains
covered by the existing seeded frame tests because a generic registry cannot
invent a valid scene/configuration fixture for arbitrary propagation plugins.

## Rejection matrix

| Condition | Registration | Resolution |
| --- | --- | --- |
| Unknown kind | Rejected by declaration and registry validation | Rejected |
| Duplicate id within one kind | Rejected | Not applicable |
| Same id in another kind | Allowed; ids are kind-scoped | Resolved by kind |
| Missing required dependency | Registered and marked unavailable | Rejected with dependency name and install action |
| Unsupported device | Registered | Rejected with supported devices |
| Unsupported runtime profile | Registered | Rejected with supported profiles |
| Invalid DOA/result or feature shape/dtype | Rejected by self-test when dependencies are present | Not registered |
| False deterministic promise | Rejected by repeated seeded self-test | Not registered |
| Unknown id | Not applicable | Rejected with registered ids |

## Built-in inventory

| Kind | Plugin id | Fidelity | Dependencies | Profiles | Device | Deterministic |
| --- | --- | --- | --- | --- | --- | --- |
| Propagation | `geometry_only` | L0 | none | both | CPU | yes |
| Propagation | `tdoa_synthetic` | L1 | none | both | CPU | yes, including seeded stress settings |
| Propagation | `room_acoustics` | L2 | `pyroomacoustics` | waveform fidelity | CPU | yes for fixed inputs/seeds |
| Propagation | `room_acoustics_srp` | L2 | `pyroomacoustics` | waveform fidelity | CPU | yes for fixed inputs/seeds |
| DOA | `tdoa_least_squares` | none | none | both | CPU | yes |
| DOA | `srp_phat` | none | none | both | CPU | yes |

The room determinism declaration is limited to the existing fixed-input,
fixed-seed implementation and its tests; it is not a cross-version
bit-reproducibility promise for third-party numerical libraries.

## Explicit non-claim

The default registry contains no `audio_feature_extractor`. The protocol,
declaration checks, and registry validation exist so a later extractor can
declare a fixed observation shape without making a learned classifier or
model part of the base release. S1.3 tests use only test-local fake extractors.
