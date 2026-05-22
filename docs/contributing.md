# Documentation Contribution Notes

Public docs should describe the standalone package, not the source project that
originally motivated it.

Keep these rules in mind:

- core imports must stay free of hard optional-runtime dependencies;
- optional Isaac helpers should document how to run with a user-managed Isaac
  environment;
- two-microphone ambiguity must remain explicit;
- generated media, local absolute paths, private recordings, and restricted
  assets should not be added to docs;
- public API changes should update `api_freeze_0_1.md` or a successor API
  freeze document.
