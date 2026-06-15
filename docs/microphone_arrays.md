# Microphone Arrays

Public coordinates use meters, `+Z` up, local `+X` forward, local `+Y` right,
and local `+Z` up. Bearing `0` degrees is local `+X`; positive bearing rotates
clockwise toward local `+Y`.

Built-in layouts:

- `mono`: one center microphone, valid for geometry-only frames;
- `stereo_y` / `two_mic_y`: left/right two-mic layout, valid for TDOA only
  with an explicit ambiguity policy;
- `quad_front` / `quad_cross`: four-mic front/right/rear/left cross layout
  recommended for unambiguous DOA examples;
- `tetrahedral`: four-mic centered regular tetrahedron with edge length
  `spacing_m`, the built-in rank-3 layout that enables elevation estimation
  (see [TDOA And DOA](tdoa_doa.md)).

Arbitrary N-mic arrays can be built with explicit `MicrophoneSpec` records.
TDOA arrays need at least two microphones with non-degenerate local-XY spacing;
four or more non-collinear microphones are preferred when a single localized
bearing is required. `layout_rank_xyz` reports the full 3D layout rank (0-3):
elevation is estimated only for rank-3 layouts, while planar arrays keep
azimuth-only estimates.
