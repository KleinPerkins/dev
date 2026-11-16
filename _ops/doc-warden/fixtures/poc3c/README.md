# ecosystem-orchestrator (fixture)

Private cross-workspace ecosystem orchestrator. **INV-zero-link**: only this repo defines the ld↔cpp
relationship (`config/relationship.yml`). `lib/vendor.sh` is the single sanctioned ld→cpp edge writer.

Canonical end-state doc: `~/dev/OPERATING-MANUAL.md` §10h.

## PR authoring on fleet-governed repos

Never arm auto-merge at PR-*create* time on fleet repos gated by `pr-automation / verify`.

This constraint is specific to the `pr-automation / verify` fleet and does **not** apply to WF2's
cpp vendoring path — `lib/vendor.sh` correctly opens `--auto` PRs (WF2 "auto-merge on green").
