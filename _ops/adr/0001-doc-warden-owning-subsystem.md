# ADR 0001: `doc-warden` owning subsystem and scope
Status: accepted — 2026-08-05

## Decision

`doc-warden` — the uniform documentation-governance capability — lives as a sibling subsystem under `~/dev`'s own `_ops/` (`_ops/doc-warden/` for policy, `_ops/bin/doc-warden{,-lib}.sh` for the engine, `_ops/skills/doc-warden/` for its thin operator-facing wrapper), peer-called from `dev-new-repo.sh` and `dev-doctor.sh`. It is **not** a capability-lifecycle shelf (local-scope or global-with-exclusion), and it is **not** folded into `baseline-lib.sh`.

## Why

Two real alternatives were traced against `dev-new-repo.sh`'s actual call sequence and `_ops/baseline/README.md`'s own documented extension path before this decision:

- **A capability shelf** (`capabilities/skills/{local,global}/tools/doc-warden/`) fits reusable, installable units consumed by other repos or agents. `doc-warden` has no second consumer — it only ever operates on `~/dev`'s own fleet, exactly like `repo-baseline` and `dev-doctor`, neither of which are capabilities either. Forcing `meta.yml`/`install.sh`/registry ceremony onto it adds pure overhead for zero benefit.
- **Folding into `baseline-lib.sh`** is `_ops/baseline/README.md`'s own documented way to extend "the floor," and would give zero-new-call-site integration. But baseline's entire model is a small, finite set of marker-diffable files (`SECURITY.md`, `CODEOWNERS`, a `.gitignore` block, `dependabot.yml`). Documentation governance requires a trigger catalog, `NEEDS_OPERATOR` escalation, provenance-driven reconstruction, semantic-collision detection, and supersession/archival — none of which map onto `bl_baseline_verdict`'s file-existence/diff vocabulary. Folding it in would make baseline "a second documentation-repair implementation," which the governing brief explicitly bars.

The sibling-engine shape reuses baseline's *rendering pattern* (marker-block render/diff, verdict/receipt shape) as a design template — not shared code — while keeping full ownership of the actual reconciliation doctrine in one place. Integration cost is one peer line in `dev-new-repo.sh` (after its scaffold and first commit) and one fleet-loop call in `dev-doctor.sh`.

## Consequences

`doc-warden` never needs a `meta.yml`, `install.sh`, registry entry, or lockkit participation. It gains no automatic discoverability outside `~/dev` (correct — it isn't meant to). Its GitHub-settings surface is empty by construction (`repo-baseline enforce` remains the sole owner of ruleset/branch-protection mutation). Future repos needing similar fleet-governance tooling (not just documentation) should use this ADR as precedent for when a sibling `_ops/` engine is warranted over a capability shelf.
