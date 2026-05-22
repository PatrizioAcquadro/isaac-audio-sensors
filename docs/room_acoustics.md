# Room Acoustics

The room-acoustics path is optional:

```bash
python -m pip install -e ".[room]"
python examples/core/room_acoustics_demo.py
```

`RoomAcousticsBackend` uses `pyroomacoustics` when available. It differs from
the synthetic TDOA backend in three ways:

- it creates approximate room impulse responses for a shoebox room;
- it can produce waveform-derived diagnostics;
- it estimates TDOA from generated microphone signals rather than only direct
  geometry.

The room model is still approximate. Absorption, room dimensions, source
directivity, microphone response, occlusion, and material behavior should be
treated as configuration assumptions, not measured truth.

Tests skip cleanly when `pyroomacoustics` is not installed.
