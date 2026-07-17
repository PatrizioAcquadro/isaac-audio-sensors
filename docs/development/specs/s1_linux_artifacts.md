# S1.5 Linux artifacts

## Acoustic-pack layout

The only Stage 1 binary artifact is
`isaac_audio_sensors_acoustic_pack-l2l3-1.8.0-linux_x86_64-cp312.tar.gz`.
Its member set is closed: `pack_manifest.json`, `requirements.lock`, the
canonical `install_pack.py`, and five hash-locked files below `wheels/`.
NumPy and `typing_extensions` are absent because they are owned by the Kit
host. The reference Kit runtime supplies NumPy 2.5.0 and
`typing_extensions` 4.12.2 from `omni.kit.pip_archive`'s `pip_prebundle`.
SciPy 1.18.0 imports `typing_extensions.Self` at runtime on CPython 3.12 but
declares `typing_extensions` only in its `dev` extra, so the manifest records
this undeclared upstream runtime dependency as host-owned instead of adding a
sixth pack wheel.

The installer verifies every wheel before invoking pip offline with
`--target`, `--no-deps`, `--no-index`, `--require-hashes`, and a pack-local
`--find-links`. It installs into a hidden staging directory beside the final
root, verifies every manifest-owned installed file, performs every declared
top-level import with staging first on `sys.path`, rejects a staged
top-level module or distribution metadata for any host requirement, copies the
manifest, and atomically renames staging to:

```text
${XDG_DATA_HOME:-~/.local/share}/isaac_audio_sensors/packs/
  acoustics-l2l3/1.8.0/
```

Existing final roots are never overwritten. Hidden staging directories and
directories without a validated manifest are not selectable.

## Manifest schema

| Field | Meaning |
| --- | --- |
| `schema` | `ias.acoustic_pack_manifest.v1` marker |
| `pack_id`, `pack_version` | Private-root identity and immutable version |
| `sensor_package_version` | Exact compatible sensor release |
| `python_version`, `abi`, `os`, `arch` | `3.12`, `cp312`, Linux, `x86_64` target |
| `host_requirements` | Exact host-owned distributions, versions, and reasons |
| `numpy_compatibility` | SciPy/host intersection `>=2.0,<2.8` |
| `pack_distributions` | Name, version, wheel filename/SHA-256, sorted complete top-level imports, and installed-file SHA-256 mapping per wheel |
| `capabilities` | L2 backend ids and WAV/FLAC SoundFile export declarations |
| `build_provenance` | Git revision and acoustic-pack build-tool version |

The builder derives top-level imports from wheel metadata and contents, so
native root modules such as `_cffi_backend` cannot be hidden behind a
distribution-name heuristic. It validates each wheel `RECORD`, rejects
missing, inconsistent, or unhashed entries other than `RECORD` itself, and
stores hashes for every declared installed file. The archive auditor repeats
that derivation from the embedded wheel bytes.

`host_requirements` and `pack_distributions` are disjoint. Activation requires
host modules to resolve outside the pack and pack distribution metadata,
declared installed-file hashes, and the complete top-level import inventory to
match inside it. The required host entries are
`numpy==2.5.0` and `typing_extensions==4.12.2`; their versions are read from
distribution metadata first, with a module `__version__` attribute used only
when metadata is unavailable. This supports `typing_extensions`, whose module
does not need to expose `__version__`.

## Activation state machine

```text
unselected
  -> validate manifest, package/runtime identity, installed distributions/files
  -> validate exact host versions and external origins
  -> reject any conflicting preloaded owned import, including native modules
  -> prepend the private root to sys.path
  -> import and origin-check every declared top-level module
  -> active (same-root activation is a no-op; switching roots is forbidden)
```

Failures before activation leave `sys.path` unchanged. Failures during import
restore the original path, remove newly imported modules, and clear active-pack
state. Process restart is required to switch successful roots, which prevents
mixed dependency provenance.

## Capability origins

| Situation | Status | Origin |
| --- | --- | --- |
| L0/L1 built-ins | available | `base` |
| All declared modules under the active validated root | available | `pack:<id>@<version>` |
| Optional modules importable elsewhere | available | `external-unmanaged` |
| Required module missing | unavailable | `absent` |

L3 remains a provisional, incomplete level: base material-aware
ray/transmission occlusion stays healthy, while missing waveform-dependent
L2/L3 capability messages name the exact acoustic-pack archive. L4 remains
unavailable in Stage 1.

## Umbrella artifact flow

`make artifacts WHEELHOUSE=/offline/wheels` runs version synchronization, then
a fail-closed Git source preflight, the base wheel/sdist build (which recreates
`dist/`), the Kit build and audit, the acoustic-pack build and audit, and
finally writes `dist/SHA256SUMS` for the wheel, sdist, Kit zip, and pack
tarball. The preflight rejects every tracked or untracked worktree change so
setuptools cannot silently add unrelated files to the sdist. Kit and pack
audits validate their recorded full Git revisions against local history and
compare embedded canonical files to those committed trees. Building the base
first prevents its clean `dist/` step from deleting later artifacts.
