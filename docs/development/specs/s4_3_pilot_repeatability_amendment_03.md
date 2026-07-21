# S4.3 Occlusion Confirmation Amendment 03

Status: frozen before the confirmation recording on 2026-07-21.

After the first accepted occlusion trial was analyzed, the operator reported a
possible extraneous noise that may have affected its result and requested one
repeat. The original attempt, raw waveform, passing quality decision, 2 degree
median bearing error, 76 degree tail error, 56.4 percent sector/candidate result,
and complete evidence remain retained and unchanged. The operator report is not
used to relabel, reject, or delete that take.

This amendment uses the already-frozen `quality_failure`/unresolved-decision
expansion mechanism to add exactly one same-cell confirmation:
`s4_3_rob_occluded_01_confirm_noise_01`. This is the first and only confirmation
for parent cell `s4_3_rob_occluded_01`, within the maximum of one confirmation per
triggered cell and three total added trials.

## Frozen confirmation cell

From the operator's viewpoint while standing in front of and facing the ZED,
the Mac remains on the operator's left at
`F_operator_facing_zed (0.00,-0.90,-0.135) m`, bearing `270 deg` (canonical
`F_project (0.00,+0.90,-0.135) m`, bearing `90 deg`). The same two stacked rigid
cardboard boxes, combined `39 x 26 x 24 cm`, fully block the direct line without
touching either device. The deterministic WAV, 40 percent volume, pose, room,
rig, mount, and acquisition/analysis settings remain unchanged.

No threshold, estimator, gate, metric, claim, or existing trial definition is
changed. Operational-Gates Amendment 02 and Array-Frame Amendment 01 remain
effective through the strict Amendment 03 overlay. No result from the repeat may
be used for further orientation or threshold tuning.

## Stopping decision

The single confirmation is terminal for this trigger. Both takes must be
reported together:

- similar central and tail behavior supports a repeatable occlusion degradation
  for this one object/placement;
- materially different tails support sensitivity to the operator-reported noise
  or ordinary unreplicated room variation;
- either result remains functional characterization, not a universal occlusion
  transfer claim.

No second occlusion confirmation may be collected. All prior freezes and
attempts remain immutable, no device setting may be changed, and S4.4 remains
untouched.
