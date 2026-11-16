# ADR 0003: Local-only lifecycle, no cpp delivery
Status: accepted — 2026-08-05

## Decision

`doc-warden` is a local-only capability for the operator's `~/dev` KleinPerkins ecosystem. There is no WF2 `cpp-sync`, no cpp quiver payload, and no cpp control-plane change, now or as a default future path. cpp was used during design **only** as read-only comparison input (its integrity-engine shape informed ADR-0002; its lack of an ADR/plans convention informed the execution plan) — never inspected or intended as a delivery target.

## Why

The governing brief posed this as a choice between two capability-lifecycle shelf options (local-scope vs. global-with-explicit-exclusion). ADR-0001 already resolves the underlying placement question a level deeper: `doc-warden` is not a capability-lifecycle artifact at all — it is an `_ops/`-resident subsystem, structurally identical in kind to `repo-baseline` and `dev-doctor`, neither of which participate in WF1/WF2. `_ops/` has no cpp-sync path, no `meta.yml`, and no registry surface for anything living there. No-cpp-delivery is therefore a structural fact of where the capability lives, not a policy flag that could later be toggled or drift.

## Consequences

No future work item under this plan should introduce a `meta.yml`, registry entry, or lockkit participation for `doc-warden` without first superseding this ADR and ADR-0001 together. If cpp evidence is needed again later (e.g., to inform a future trigger), it remains available under the same read-only, comparison-only terms — this ADR does not need to be revisited for that.
