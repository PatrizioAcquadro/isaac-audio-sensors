# S4.5 active profile handoff and provenance amendment 01

## Scope and authority

This is an additive S4.5-only correction. It does not change the public
`ias.audio_calibration_profile.v1` schema, refit any scientific parameter,
open holdout evidence, apply a profile, or start S4.6. Frozen S4.4 evidence,
the original S4.5 package, and `S4.5_corrective_01` remain immutable.

The fixed active pointer is
`outputs/isaac_audio_sensors/S4/S4.5_active_profile.v1.json`. It must resolve
exactly one active profile and handoff:

- profile:
  `outputs/isaac_audio_sensors/S4/S4.5_corrective_01/calibration_profile.v2.json`;
- handoff:
  `outputs/isaac_audio_sensors/S4/S4.5_handoff_01/active_handoff.v1.json`.

The pointer, handoff, profile, and all hashes and identity guards form one
fail-closed bundle. The historical v1 profile is retained but is never an
authorized S4.6 input.

## Functional association versus geometry

The public profile cannot honestly encode a categorical, fit-supported
channel-to-position association separately from microphone geometry status.
The schema therefore remains unchanged and the association is carried in the
versioned handoff record.

The handoff states, as structured fields, that:

- the retained object is a functional channel-position association supported
  by fitted functional evidence;
- Fit A selected it and Fit B validated it without selecting or tuning it;
- the mapping is `ch0=[-0.033,-0.033,0]`,
  `ch1=[-0.033,+0.033,0]`, `ch2=[+0.033,+0.033,0]`,
  `ch3=[+0.033,-0.033,0]` in `F_project`;
- the coordinate values are nominal acoustic-center coordinates and remain
  `nominal_not_measured`;
- the association is not measured geometry, a scalar bearing correction,
  physically traced wiring, or a mirrored `F_project`; and
- later application is permitted only when every profile, device, array,
  sample-rate, channel-order, frame, and environment guard matches exactly.

## Corrected count semantics

The immutable v2 profile contains six scalar entries in
`fitted_model_parameters`: three relative gains and three unity polarities.
Its legacy fit metric `retained_parameter_count=7` combined those six scalar
entries with the categorical association and is scientifically superseded as
an application count.

The authoritative handoff uses three distinct fields:

- `retained_scalar_profile_parameter_count=6`;
- `retained_functional_association_count=1`; and
- `retained_scientific_component_count=7`.

A consumer must never interpret the last value as seven directly applicable
scalar fitted profile parameters.

## Provenance, replay, and validation

The package binds the active profile, profile hash and identity, corrective
evidence index, binding decision and source artifact, package-location
amendment, this specification, the closeout amendment, implementation,
runner, replay tool, validator, focused tests, public profile schema/reader,
and the immutable corrective package.

The implementation-source commit precedes generated evidence. From a clean
checkout containing the final evidence commit, the exact command recorded in
`reproduction.v1.json` regenerates the package into a temporary directory and
compares every byte with the canonical package.

The validator rejects rechecksummed changes to the active path or hash,
identity, frames, channel order, mapping, binding evidence status, count
semantics, relocation amendment, closeout routing, provenance, source commit,
replay command, or later-phase boundary. `--require-tracked` and
`--require-committed` cover the entire active handoff surface, including files
outside the package directory.

S4.6 through S4.9 remain unstarted. S4 is not SquadBot-ready until S4.8 and
S4.9 pass.
