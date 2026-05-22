# Versioning

`isaac-audio-sensors` follows semantic versioning.

Initial release:

- distribution: `isaac-audio-sensors`
- import package: `isaac_audio_sensors`
- version: `0.1.0`
- pure Python support: Python 3.10 or newer

Compatibility policy:

- `0.1.x` patch releases keep the stable API in `api_freeze_0_1.md`
  compatible.
- Experimental modules can change with documentation and changelog notes.
- Internal names starting with `_` are not part of the public compatibility
  contract.

Release checklist:

```bash
python -m pytest
python -m ruff check .
python -m build
git diff --check
```
