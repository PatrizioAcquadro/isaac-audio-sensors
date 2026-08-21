# Contributing

Use Python 3.10 or newer and install the development extras:

```bash
python -m pip install -e ".[dev]"
```

Before opening a pull request, run the lanes relevant to the change:

```bash
make test
.venv/bin/python -m pytest -q tests/integration
make test-release
make lint
python -m isaac_audio_sensors --version
git diff --check
```

Contribution rules:

- Keep `isaac_audio_sensors.core` free of hard Isaac Sim, Isaac Lab, Omniverse, ROS 2, protobuf, and project-specific imports.
- Keep optional integrations lazy and fail with clear exceptions when their runtime dependency is missing.
- Do not add private recordings, generated media, restricted robot data, local absolute paths, or downloaded third-party scene assets.
- Preserve explicit two-microphone ambiguity handling.
- Add proportional tests for behavior changes and update the canonical wiki for material public API changes.

Versioning follows semantic versioning and the compatibility rules in [Product Boundary and Compatibility](knowledge/wiki/decisions/product-boundary-and-compatibility.md).
