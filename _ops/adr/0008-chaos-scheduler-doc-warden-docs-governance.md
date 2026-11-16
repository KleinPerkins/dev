# ADR 0008: `chaos-scheduler` is doc-warden-governed for documentation only
Status: Accepted — 2026-08-22

`chaos-scheduler` (`KleinPerkins/chaos-scheduler`) has been a permanent hard exclusion from every
`~/dev` fleet controller because it is independently governed — its own branch-protection ruleset,
its own `chaos-scheduler-automerge` GitHub App, and its own signed release pipeline. The operator has
decided its architecture documentation should nonetheless be governed by `doc-warden`.

## Decision

`doc-warden` governs `chaos-scheduler`'s **documentation only** — its `docs/adr/` and `docs/plans/`
against the shared taxonomy/templates in `POLICY.md`. It remains a hard exclusion from `repo-baseline`
`apply`/`enforce` and from pr-automation: `bl_classify_repo` still returns `EXCLUDED`, so the local
`dev-doctor` fleet sweep does not sweep it. Governance is enforced **on demand** via
`doc-warden.sh check chaos-scheduler` (run against a clean checkout) and at PR-authoring time — not the
laptop fleet sweep. No engine change is required: `doc-warden.sh check` is already repo-agnostic (it
classifies any repo path) and was used to verify the repo's initial `docs/adr/` + baseline as
`CONFORMANT`.

## Why

- **Alternatives considered.**
  - (a) *Keep the full permanent exclusion.* Rejected: it leaves `chaos-scheduler`'s many irreversible
    decisions (service boundary, core-model swap, app-owned provisioning, minisign signing, …) recorded
    only in `AGENTS.md` prose and commit messages, with no governed ADR/plan surface — the exact gap the
    operator asked to close.
  - (b) *Fully un-exclude it (bring it into `repo-baseline` + pr-automation too).* Rejected: it is
    independently governed; `repo-baseline enforce` would fight its own ruleset and the
    `chaos-scheduler-automerge` App, and pr-automation would collide with its release pipeline. That hard
    exclusion exists for a real reason and must stand.
  - (c) *Scoped documentation-only carve-out.* Chosen: doc-warden governs its docs (the operator's
    intent) while every mutating fleet controller keeps excluding it.
- **Why on-demand rather than the fleet sweep.** The `dev-doctor` sweep classifies each repo's local
  working tree. `chaos-scheduler`'s primary checkout is intentionally bare/PR-driven — changes land via
  the GitHub git-data API to keep the working tree pristine — so a local-tree sweep would classify a
  stale snapshot. `doc-warden.sh check` against a clean checkout (or the PR branch) is the accurate
  surface. Wiring it into the local sweep is deferred until that checkout is de-staled.

## Consequences

- **Enables.** `chaos-scheduler` carries governed, byte-identical-forever ADRs/plans under the shared
  doc-warden taxonomy; drift is catchable with `doc-warden.sh check chaos-scheduler` on demand and at
  PR time.
- **Forecloses.** This carve-out is documentation-only; it does NOT make `chaos-scheduler` eligible for
  `repo-baseline` `apply`/`enforce` or pr-automation, and `bl_classify_repo` must keep returning
  `EXCLUDED`. Any future change that routes a mutating fleet controller at `chaos-scheduler` is a
  regression against this ADR and against `_ops/baseline`'s hard-exclusion.
- **Invariant to keep true.** doc-warden's reach into `chaos-scheduler` is read-only classification of
  documentation. If the local sweep is later wired to include it, it must target a non-stale checkout
  (post de-staling), never the bare primary.
