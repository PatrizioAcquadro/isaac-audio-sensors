# Microphone Arrays

Public coordinates use meters, `+Z` up, local `+X` forward, local `+Y` right,
and local `+Z` up. Bearing `0` degrees is local `+X`; positive bearing rotates
clockwise toward local `+Y`.

Built-in layouts:

- `mono`: one center microphone, valid for geometry-only frames;
- `stereo_y`: left/right two-mic layout, valid for TDOA with explicit ambiguity;
- `quad_front` / `quad_cross`: four-mic cross layout recommended for DOA.

Arbitrary N-mic arrays can be built with explicit `MicrophoneSpec` records.
