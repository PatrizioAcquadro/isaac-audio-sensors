# Examples

Run examples from the repository root after installing the package in editable
mode:

```bash
python -m pip install -e ".[dev]"
python examples/core/two_mic_ambiguity.py
python examples/recording/read_manifest.py
python examples/calibration/read_profile.py
```

Install the optional room dependencies before running:

```bash
python -m pip install -e ".[room]"
python examples/core/room_acoustics_demo.py
```

`examples/isaac_sim/` and `examples/isaac_lab/` contain concise recipes for an
initialized compatible runtime. The maintained end-to-end GPU workflows are:

```bash
make smoke-isaac-sim
make smoke-isaac-lab
```

The tracked traces cover minimal, multi-detection, ambiguity, and diagnostic
records. Manifest paths and hashes are compact references rather than bundled
audio. The nominal ReSpeaker profile is a schema fixture, not measurement
evidence.

The examples are generic and do not depend on downstream project contracts.
