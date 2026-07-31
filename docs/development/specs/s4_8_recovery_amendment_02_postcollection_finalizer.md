# S4.8 Amendment-02 Postcollection Finalizer

This additive finalizer seals the completed 37-take official collection. It
does not change the frozen acquisition controller, protocol, precollection
records, retained attempts, authorization records, or ledger.

The finalizer parses only collection-control metadata: the frozen session,
partition, precollection seal, official ledger, official attempt wrappers,
take authorizations, candidate seals, and clearance-consumption records.
Technical reports, audio, SVO2, frame, replay, producer-status, producer-summary,
and process-journal content are never decoded or interpreted. Those files are
read only as opaque byte streams for SHA-256 and byte-size inventory.

Finalization requires a complete authenticated ledger, exactly 37 completed
planned takes, every retained attempt directory, matching authorization copies,
valid official wrappers, and candidate-seal bindings for every PASS. Missing,
extra, duplicate, symlinked, path-escaping, stale, or hash-mismatched state
fails closed.

The only generated evidence is:

- `outputs/isaac_audio_sensors/S4/S4.4/amendments/s4_4_data_expansion_amendment_04/holdout_seal.v2.json`;
- `configs/s4_8_recovery_amendment_02_holdout_binding.v2.json`.

The seal binds the frozen precollection records, ledger head, completion
census, and every retained collection artifact. The binding authenticates the
seal as `sealed_unopened` against the preregistration commit stored in the
precollection seal.

This step creates and consumes no grant, does not create an evaluation ledger
or journal, does not add independent review, and does not open or evaluate the
holdout. After authentication, only
`new_unseen_holdout_not_collected_or_bound` is removed. Official evaluation
readiness remains `no_go`.
