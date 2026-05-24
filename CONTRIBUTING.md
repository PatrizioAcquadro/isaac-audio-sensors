# Contributing

Use Python 3.10 or newer and install the development extras:

```bash
python -m pip install -e ".[dev]"
```

Before opening a pull request, run:

```bash
python -m pytest
python -m ruff check .
python -m isaac_audio_sensors --version
python -m build
git diff --check
```

Contribution rules:

- Keep `isaac_audio_sensors.core` free of hard Isaac Sim, Isaac Lab,
  Omniverse, ROS 2, protobuf, and project-specific imports.
- Keep optional integrations lazy and fail with clear exceptions when their
  runtime dependency is missing.
- Do not add private recordings, generated media, restricted robot data, local
  absolute paths, or downloaded third-party scene assets.
- Preserve explicit two-microphone ambiguity handling.
- Add tests for behavior changes and docs for public API changes.

Versioning follows semantic versioning. Public APIs listed in
`docs/api_freeze_0_1.md` remain stable for compatible v1 releases except for
documented deprecations.
