# S1.4 canonical extension build

## Mode-sentinel state machine

The extension loader decides its core-package source before importing
`isaac_audio_sensors`. Exactly one valid sentinel is required.

| Packaged metadata | Developer sentinel | Result |
| --- | --- | --- |
| Valid | Absent | Prepend `_vendor`, import only the vendored package, then verify origin and version. |
| Absent | Valid | Try the ordinary environment, then fall back to the checkout `src/` tree. |
| Valid | Valid | Fail because the mode is ambiguous. |
| Absent | Absent | Fail because no source mode is authorized. |
| Corrupt or incomplete | Any state | Fail before importing the core package. |

Packaged metadata is `_vendor/VENDORED.json`. It contains `mode=packaged`, the
extension version, the source Git revision (or `unknown` when Git is absent),
and the vendored tree hash. The tracked
`isaac_audio_sensors_omni/DEVELOPMENT_MODE.json` file authorizes checkout
development and is excluded from Kit archives.

## Build and audit flow

`scripts/build_kit_extension.py` reads the authoritative project version from
`pyproject.toml`, checks the extension manifest version, copies the extension
runtime files, and vendors `src/isaac_audio_sensors/` without generated cache
files. It writes the provenance metadata, a staging directory, the Kit zip,
and `SHA256SUMS`.

Zip members are written in lexical order with a fixed 1980-01-01 timestamp,
fixed regular-file permissions, and fixed compression settings. Rebuilding the
same inputs and source revision therefore produces identical zip bytes.

`scripts/audit_kit_archive.py` validates required and forbidden members, unsafe
paths, distributed-text hygiene, sentinel exclusion, all three version
surfaces, and the recorded tree hash. By default it also compares the archive
tree with a fresh hash of the current maintained source; use
`--skip-worktree-drift` only when intentionally auditing another revision.

## Tree-hash definition

For every included file under the package root, compute the SHA-256 of its
bytes. Sort records by POSIX relative path. Feed each record into one SHA-256
digest as UTF-8 path, a NUL byte, the lowercase ASCII per-file digest, and a
newline. The resulting lowercase digest is `tree_sha256`. This commits both
file names and byte-for-byte contents while remaining independent of filesystem
metadata and traversal order.
