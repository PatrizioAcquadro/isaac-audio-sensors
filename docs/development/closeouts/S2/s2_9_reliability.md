# S2.9 closeout - Reliability closeout

Status: **passed** (2026-07-18). Entry revision `7666098`; predecessors
S2.1-S2.8 closeouts. Capture definition ratified to evidence
(`outputs/isaac_audio_sensors/S2/S2.9/ratified_capture_definition.json`)
before any execution.

## Reliability gate (pure, full scale)

`make live-reliability` — all five scenarios passed
(`outputs/isaac_audio_sensors/S2/S2.9/reliability_gate.json` +
`scenario_logs/`): cancellation/restart with resumed validator-clean
continuation; simulator replacement rejected mid-session and clean as a
new session; dependency removal failing explicitly with no partial shard;
three-phase ENOSPC preserving the published prefix; SIGKILL resume
semantically equal to an uninterrupted control.

## Endurance capture (live Isaac Sim 6.0.1, RTX 4090)

Six attempts, all evidence preserved; the frozen limits were never
adjusted:

1. Fast fail — harness scene not adapted for the room backend (array at
   demo origin put a microphone outside `lab_room_a`).
2. Fast fail — adaptation written to state fields that `author_array`
   ignores (it derives pose from the prim xform).
3. Fast fail — `apply_array_pose` writes `ias:position_world`, but on
   real USD the pose resolver prefers the prim's xform stack; fixed by
   also writing the real USD xform (`set_prim_xform_pose`).
4. Full 30-minute run; writer flat ~30-43 MiB throughout, but finalize
   spiked to 173.5 MiB: **real defect found by the gate** — layout
   streaming verification and the validator retained one warning/finding
   object per diagnostics occurrence (~300k on 30k frames). Fixed with
   bounded retention (100 per shard / per code) plus exact totals at both
   layers (commit `c99723a`); recorder finalize verified free of further
   per-frame accumulators.
5. Full 30-minute run; **every measured criterion passed** (RSS peak
   13.7 MiB) but the harness aggregation strict-compared validator status
   `"passed"`, rejecting the contract-permitted `passed_with_warnings`;
   fixed (`3ebe2a8`).
6. **Full 30-minute acceptance run: PASSED** —
   `outputs/isaac_audio_sensors/S2/S2.9/endurance_gate.json`:
   1800.0 s wall; real `room_acoustics` backend (no substitution);
   5 complete shards (6000 frames / ~5 simulated minutes each) plus a
   deliberately in-flight 5301-frame shard proven unpublished
   (`staging marker absent, published marker absent`); 30,000 published
   frames, accounting fully reconciled with **0 unreported drops**;
   peak RSS delta **14.9 MiB** vs the frozen 128 MiB limit, peak fd
   delta 4 vs 16; canonical validator **0 errors**
   (`passed_with_warnings`; 720,000 diagnostics-portability warnings
   counted exactly by the bounded `finding_totals` — warning-only by the
   frozen layout contract); zero stale frames, zero non-monotonic
   timestamps; lifecycle `finalized-incomplete` as ratified.

## Acceptance statement

No stale frame, no incomplete published shard, no unreported drop, no
unbounded memory growth, and no unrecoverable valid configuration
occurred; output passes the canonical validator. The failure->fix->full
rerun policy was followed literally: every fix was followed by a complete
30-minute rerun, never a shortened pass.

## Defects found and fixed by this gate (value delivered)

- Unbounded warning/finding retention in streaming validation (would have
  surfaced in S5 scaled scenarios) — fixed and regression-tested.
- Three harness integration gaps (scene adaptation, pose authoring layer,
  aggregation strictness) — fixed with evidence preserved.
