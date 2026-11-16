# Start on the personal Mac

1. Open Codex on the Apple-silicon Mac using your personal account.
2. Give Codex `DESTINATION-PROMPT.txt` from this package, or paste its complete contents.
3. Complete only the sign-in, OS authorization, or exact owner-preview decisions the agent
   identifies as necessary. The agent performs downloads, setup commands, checks and resumption.

For this handoff, the files are staged in personal iCloud Drive under
`Personal Mac Migration/2026-11-01-01a195ae`. The receiving agent must verify availability and
hashes on the new Mac; source-side placement does not prove completed cloud synchronization.

Source: `KleinPerkins/dev` at `@@SOURCE_REVISION@@`.
The package deliberately contains no source Git history, host configuration or credentials.
Verify its checksum against the authenticated handoff, then verify `SHA256SUMS` before executing.

This package can reconstruct eligible sources. Its manifest also records required unresolved
items. It must not report the ecosystem installed while those items remain. In particular, the
full mixed dev history, classified local work, and native capability owner gates need resolution.
Do not run the legacy no-argument dev bootstrap on the personal Mac.
