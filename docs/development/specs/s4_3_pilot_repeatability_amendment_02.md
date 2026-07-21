# S4.3 Operational-Gates Amendment 02

Status: frozen before the next S4.3 recording on 2026-07-21.

This amendment supplements the immutable S4.3 base specification and Array-
Frame Amendment 01. It changes only preflight classification and ZED version
gate semantics. It does not change the pilot matrix, repetitions, stimuli,
placements, acquisition settings, analysis algorithms, thresholds, scientific
acceptance criteria, supported claims, stopping rule, privacy contract, or the
authorized 180 degree array-frame correction.

The prior configuration, preregistration, precollection inventory, every trial
attempt, and every favorable or unfavorable result remain retained and
immutable. The effective configuration for all subsequent S4.3 captures is
`configs/s4_3_pilot_amendment_02.v1.json`. S4.4 is not started.

## 1. Mac dynamic preflight

The read-only Mac dynamic preflight remains mandatory before every deterministic
Mac reference capture. Its complete report, command return code, aggregate
`status`, and power object are retained as provenance metadata. AC versus battery
power, battery percentage, charging state, battery condition, power-source text,
and an aggregate failure caused only by those power fields cannot reject a take.

The preflight still fails closed if it cannot return a valid report or if any of
these independently evaluated hard fields differs from the frozen contract:

- output device: `MacBook Pro Speakers`;
- output channel count: 2;
- nominal output sample rate: 48000 Hz;
- output volume: 40 percent;
- output mute: false.

The corresponding helper checks for device, channels, sample rate, volume, and
unmuted output must also be true. The deterministic reference must remain present
and SHA-256-identical on both hosts. Trial placement and operator confirmation,
Mac identity, ReSpeaker identity/channel contract, recorded WAV format and
quality, and the privacy contract remain independent hard gates. No helper may
change any Mac, audio, privacy, firmware, or other operator-controlled setting.

## 2. ZED impact capture

For `s4_3_rob_impact_av_01`, the observed ZED SDK version, camera firmware, and
sensor firmware, their frozen reference values, and match booleans are provenance
metadata. A version mismatch alone cannot prevent recording or acceptance. This
is not a compatibility or performance claim for other versions.

The following remain fail-closed:

- expected ZED serial and required USB video/serial interfaces at the minimum
  USB speed;
- requested and observed HD720, 30 fps capture contract and requested
  PERFORMANCE depth mode;
- successful grab, image, depth, IMU, pose, and SVO2 recording startup;
- present, strictly increasing device timestamps and retained host timestamps;
- zero grab/retrieval/timestamp failures and complete non-empty producer outputs;
- immutable artifact checksums, transfer/producer integrity, and corruption
  detection;
- full SVO2 replay to end-of-file with matching serial, resolution, fps,
  declared/replayed frame counts, and representative-frame retrieval;
- privacy-clean scene and the separately bounded coarse audio-video annotation.

The shared S4.2 ZED producer retains its historical default `exact` version
policy. S4.3 explicitly invokes its `metadata` version policy, so this amendment
does not rewrite or weaken historical S4.2 evidence.

## 3. Freeze and validation

Before another recorder starts, the amendment preregistration must bind this
specification, the strict configuration overlay, the unchanged effective matrix,
the current retained-attempt inventory, the superseded Amendment 01 records, and
every changed implementation/test file by SHA-256. Focused tests must prove:

1. battery operation and aggregate preflight failure pass only when every hard
   Mac field/check remains valid;
2. every hard Mac field/check still rejects independently;
3. SDK and firmware mismatches pass only under the S4.3 metadata policy;
4. serial, USB, resolution, fps, depth-mode, and timestamp failures still reject;
5. the exact-version default remains available for S4.2; and
6. all retained S4.3 analyses replay deterministically with no evidence removed.

No result-dependent scientific threshold or physical trial definition may be
changed through this amendment.
