# `docs/plans/` — planning-document convention

This directory holds every substantial execution/design plan for this repository.

## The convention (already practiced by every file here; now authored)

1. **Header.** Title as an H1, then metadata bullets.
2. **Naming.** `<topic-slug>-vN.md`. A continuously-amended single-version tracker may omit the `-vN` suffix (e.g. `gen3-m0-m1-execution-plan.md`).
3. **Freeze-on-approval.** Once a version is owner-approved (or superseded by a newer version),
   it is **frozen immutable** — never edit it again, including for typos. A revision is always a
   **new** `-v<N+1>.md` file, preserving the prior version byte-identically. State the pointer
   explicitly in the new file's `**Supersedes:**` bullet and, where practical, add a one-line
   "now frozen historical" note to the superseded file's own `**Status:**` bullet (its body stays
   untouched).
4. **Body shape** (established by the `gen3-m0-m1-execution-plan.md` lineage): purpose and boundary →
   decisions → acceptance-test ledger. The earlier `controller-go-live-2-v*.md` lineage uses a
   different, numbered-§0-19 skeleton. Both are valid; do not retrofit old files.

## Index

| File | Status | One-line description |
|---|---|---|
| `gen3-m0-m1-execution-plan.md` | Active | Roadmap map. |
| `controller-go-live-2-v1.md` | Frozen historical | Pre-review draft. |
