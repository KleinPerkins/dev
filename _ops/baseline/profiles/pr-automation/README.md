> HISTORICAL CONTROLLER REFERENCE. The installed controller is abandoned; the
> mutation commands described below are retired and must refuse. This material
> supplies compatibility/parser/test provenance, not operational instructions or
> authority to resume a service. Current policy: `_ops/POLICY.md` and
> `_ops/baseline/README.md`. PAC mini actions is planned development.

# PR automation profile (`pr-automation/v1` + `pr-automation/v2`)

This directory is the source of truth for the legacy App-free Phase A lifecycle and the fleet
Phase B App-controller lifecycle. Neither lifecycle reads, updates, pauses, or deletes the existing
`kleinperkins-dev-baseline` history-integrity ruleset.

## Guarantee

> **Phase A promotion blocked (2026-07-10):** Live `kp-mcp` canary PR
> [#31](https://github.com/KleinPerkins/kp-mcp/pull/31) changed a CODEOWNERS-protected
> workflow, had no reviews, and merged normally while
> `required_approving_review_count=0` and `require_code_owner_review=true`.
> GitHub therefore does not provide the path-scoped review guarantee assumed below at zero
> general approvals. The task-created ruleset was rolled back and deleted; do not promote this
> Phase A profile. See `KP-MCP-CANARY-2026-07-10.md`. Phase B closes that invariant with a
> separately qualified App approval and the managed fleet lifecycle below; its original canary
> record is `KP-PR-BOT-CANARY-2026-07-10.md`. Phase A remains App-free and available only for
> compatibility/read/rollback.

Only `required / ci`, produced by GitHub Actions App integration `15368`, is required. Integration
`15368` identifies the GitHub Actions App broadly—not this workflow—so protected workflow/action/
script paths are part of the security boundary. GitHub accepts raw required-check conclusions
`success`, `skipped`, and `neutral`; the stable aggregator therefore uses `if: always()` and turns
every static dependency result other than the literal string `success` into its own failure. It
also refuses a zero/missing discovery count. The ruleset requires PRs, resolved review
threads, linear history, squash merges, a current-base check (`strict=true`), and CODEOWNER review
for protected automation paths. Direct pushes are blocked.

GitHub-native behavior closes the remaining states: failed or missing checks cannot satisfy the
required check; stale heads fail strict; and conflicted and draft PRs remain pending. Pausing never
disables merge protection: it keeps this ruleset active, sets repository auto-merge off, and
owner-disarms already-armed requests. `allow_update_branch` only
exposes GitHub's manual **Update branch** control and update-branch API; it does not keep branches
updated automatically. Phase A contains no controller, App credential, `pull_request_target`,
installation token, or direct merge.

## Managed local files

`profile pr-automation apply` installs:

- `.github/pr-automation.json` — closed-schema profile declaration.
- `.github/workflows/required.yml` — portable starter aggregator. Repositories with richer CI must
  fold the stable `required / ci` job into their primary workflow with a **static** `needs` list;
  dynamic matrix job names must never be required directly. Validation intentionally supports only
  a strict block-style YAML subset; flow/inline jobs or steps and unsupported syntax fail closed.
  Every parsed `uses`, including job-level reusable workflows, requires a full immutable SHA, and
  custom `shell` is forbidden so YAML-decoded shell templates cannot change exit semantics. Every
  workflow with a raw or decoded `name: required / ci` producer is validated; multiple producers
  are refused even when a secondary producer uses legal flow-style YAML.
- `.github/CODEOWNERS` — a managed block for `.github/workflows/**`, `.github/actions/**`,
  `.github/scripts/**`, CODEOWNERS itself, Dependabot config, and the profile config.

The profile replaces only the exact broad baseline-generated CODEOWNERS template (`* @KleinPerkins`)
because leaving it would require a review on every PR. A custom CODEOWNERS file is preserved and the
protected block is appended or refreshed. Existing conflicting profile-owned files are refused.

## GitHub controls

The profile manages exactly three repository settings:
`allow_auto_merge=true`, `delete_branch_on_merge=true`, and `allow_update_branch=true`.
Without an explicit target flag, its branch ruleset targets the live default branch and binds
`required / ci` to integration `15368`. Canary-first adoption uses an exact branch head through
`enforce --target-branch`, exact rollback and re-enforcement, then
`enforce --retarget --canary-proof` to mutate that second owned ruleset id in place.
The central template has no bypass actor. The approved design permits an admin
`bypass_mode: pull_request` only after a live canary proves it cannot push/bypass outside a PR; that
evidence belongs to the later enforcement workstream and does not yet exist. Until then, `pause` is
a safety-preserving auto-merge drain—not a transactional halt or review bypass. A currently
eligible armed PR may merge between disabling repository auto-merge and its individual disarm.
Protected-path changes remain subject to the active ruleset and need an eligible CODEOWNER reviewer.
Lifecycle writes use preimages and best-effort optimistic drift refusal.

GitHub does not path-scope PR-review rulesets. CODEOWNERS supplies the path scope: with
`required_approving_review_count=0`, only PRs changing a matching protected path require a code-owner
review. `pause` does not weaken this requirement or make a self-authored protected-path PR mergeable.
The profile deliberately avoids a push ruleset with `file_path_restriction`, because that
rule applies to the entire fork network and would make routine protected-file maintenance
unmergeable rather than review-gated.

## Commands

```text
repo-baseline.sh profile pr-automation verify <repo>
repo-baseline.sh profile pr-automation apply <repo> [--dry-run]
repo-baseline.sh profile pr-automation enforce <repo> [--dry-run] [--target-branch <exact-branch>]
repo-baseline.sh profile pr-automation enforce <repo> [--dry-run] --retarget <exact-branch> \
  --canary-proof <proof.json>
repo-baseline.sh profile pr-automation status <repo>
repo-baseline.sh profile pr-automation pause <repo> [--dry-run]
repo-baseline.sh profile pr-automation repair <repo> [--dry-run]
repo-baseline.sh profile pr-automation rollback <repo> [--dry-run]
```

`verify` and `status` are read-only. `apply` is local-file-only and refuses dirty trees or conflicts.
Only `enforce`, `pause`, `repair`, and `rollback` mutate GitHub. Existing no-flag behavior remains
actual-default-branch only. An initial `--target-branch` accepts only a plain, exact branch head;
the branch must exist remotely, be checked out locally, contain the locally verified profile files,
track `origin/<target>`, and have one full SHA across local `HEAD`, its upstream, a fresh fetch, and
GitHub's branch API. `--retarget` requires active state whose exact ruleset id is recorded as owned,
changes only that id's target condition, and refuses recreation, replacement, or semantic drift.
Before PUT it persists exact normalized preimage and desired postimage plus both fingerprints. A
retry accepts only that same-id preimage (retry) or same-id desired postimage (finalize);
404/422/5xx/response-loss never permits a third-state guess. Recovery classifies the same-id live
ruleset before freshness checks. An already-applied desired postimage finalizes against the
persisted destination SHA/proof digest even if evidence expired or the branch advanced. An unchanged
preimage is eligible for another PUT only after fresh destination-head and canary-proof validation;
while it remains exact, a refreshed destination/proof binding may replace the pending binding and
is persisted before retry. Retargeting initially or retrying from preimage therefore requires the
clean local destination branch at GitHub HEAD.
Before each independent GitHub write, the engine re-reads and compares the stored resource id and
semantic SHA-256 fingerprints, then verifies the exact id and desired postimage after the write.
This is best-effort optimistic drift refusal across multiple API calls, not atomicity or
compare-and-swap. Settings writes persist exact from/desired fingerprints so a lost PATCH response
can resume only from one of those states. A ruleset POST without a returned, recorded id enters
ownership-ambiguous refusal; it is never adopted or rollback-deleted. `pause` first sets
`allow_auto_merge=false` while preserving the active ruleset, then paginates and owner-disarms
remaining requests through GitHub's `disablePullRequestAutoMerge` mutation. That mutation has no
expected-head input, so the engine verifies PR node id and exact head SHA before and after each
disarm and fails closed on change. Successful return guarantees zero armed requests, but cannot
prevent an already-eligible PR from merging during the non-atomic transition. See `LIFECYCLE.md`.

The exact canary proof sequence is enforced, not advisory: enforce generation-1 canary → test →
rollback to persist exact restoration proof (which deletes that task-created ruleset) → re-enforce
canary (receiving generation 2 and a new owned id) → repeat the mandatory safety matrix → supply a
closed-schema proof bundle → explicitly retarget that second id to the default branch. A deleted
first id is recorded as deleted and never represented as retained; generation-1 evidence is cleared
and cannot be replayed.

The proof bundle is `pr-automation-canary-proof/v1`, no larger than 1 MB and no older than 24 hours.
It binds owner/repo, current generation and owned id, canary branch/SHA, destination, exact live
ruleset/settings fingerprints, `required / ci`, and integration `15368`. It contains exactly:
direct push, red, cancelled, missing, stale, conflict, draft, non-15368 spoof, skipped/neutral
managed-path behavior, green native auto-merge, manual update, protected-path self-authorization,
unchanged history ruleset, pause, and rollback. Every result is `pass`, labelled `live` or `mocked`,
with one secret-free HTTPS URL or API observation. Phase-A live requirements—all except conflict,
draft, and rollback, whose mocked forms are permitted because exact rollback is independently
state-proven—cannot be mocked. Only the normalized digest/bindings/mode summary is retained;
evidence URLs/observations are never copied into lifecycle state. `status` reports proof readiness
without writing state.

## Trust boundary

Lifecycle state, rollback records, and canary bundles are secret-free **operator attestations** and
guards against accidental stale/replayed/mis-bound operations. They are not tamper-proof evidence
against a malicious local operator. An operator who can rewrite this local state already has the
authenticated `gh` authority needed to mutate repository rulesets directly; self-signing with a key
stored beside the state would add no security. Adding an external signer/credential would violate
Phase A's App-free/no-new-credential boundary. The actual security authority is GitHub's live
same-resource-id plus semantic-fingerprint/postimage checks. Evidence URLs and API observations are
preserved in the supplied/final-report bundle for operator review, but this tool validates their
shape and binding only—it does not independently fetch them or prove that their claims are true.

## Files in this source of truth

- `config.schema.json`, `config.json` — closed schema and canonical configuration.
- `canary-proof.schema.json` — closed, secret-free promotion-evidence contract.
- `ruleset.json.tmpl` — exact-target-branch-substituted ruleset payload.
- `required.yml` — starter literal-success aggregator.
- `CODEOWNERS.block` — protected automation paths.
- `profile.py` — lifecycle engine, semantic normalization, fingerprints, and preimages.
- `LIFECYCLE.md` — optimistic-drift and resumable-rollback contract.
- `test_profile.py`, `test.sh` — hermetic lifecycle and refusal tests.
- `KP-MCP-CANARY-2026-07-10.md` — Phase A live-canary record (the blocker that motivates Phase B).

### Phase B (GitHub-App path) — fleet lifecycle

Phase B closes the private-user-repository review gap with an inert-by-default trusted
`workflow_run` controller and two independently owned rulesets:

- `kleinperkins-merge-safety`: no bypass; strict `required / ci` from Actions integration `15368`,
  squash-only, resolved threads, linear history, deletion and force-push protection.
- `kleinperkins-review-gate`: one approval, stale dismissal, last-push and CODEOWNER review; only
  repository administrators may bypass it and only through a pull request.

The hardened controller binds the required check to the triggering check suite, checks add/delete/
rename paths with exact changed-file counts, recognizes only `kleinperkins-review-bot[bot]`, and
rechecks the full PR tuple plus exact live pair before token mint, arm, approval, and direct
fallback. `AUTOMERGE_ENABLED` must be literal `true`; absent/false is inert.

Use the generalized lifecycle:

```text
repo-baseline.sh profile pr-automation phase-b inventory
repo-baseline.sh profile pr-automation phase-b verify|apply|preflight|status <repo>
repo-baseline.sh profile pr-automation phase-b credential-status|credential-provision|credential-revoke <repo>
repo-baseline.sh profile pr-automation phase-b enforce-canary <repo> --target-branch <branch>
repo-baseline.sh profile pr-automation phase-b activate-canary <repo>
repo-baseline.sh profile pr-automation phase-b qualify <repo> --evidence <json>
repo-baseline.sh profile pr-automation phase-b promote|activate|pause|repair|rollback <repo>
```

`fleet.json` is the source-tracked target/exclusion policy. State under `state/v2/` stores only
resource ids, normalized fingerprints, timestamps, credential names/ownership, pair phases, and
qualification summaries—never secret values. Pair creation, retarget, and deletion are ordered and
resumable; unknown ids or third-state fingerprints fail closed. Phase A remains available through
the original commands for read/rollback compatibility.

Future private source repositories stage inert Phase B files by default through `dev-new-repo.sh`;
`--no-pr-automation` is the explicit opt-out. Credential, canary, qualification, and activation use
this same lifecycle—there is no second provisioning script.
